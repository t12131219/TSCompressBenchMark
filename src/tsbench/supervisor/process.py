"""Bounded child lifetimes for the functional CPU worker."""
from pathlib import Path
import os
import signal
import subprocess
from threading import Event, Thread
import time
import uuid


def _signal_group(process: subprocess.Popen) -> None:
    # A worker owns its process group; descendants must not escape a cancelled
    # operation just because the group leader happens to exit first.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _kill_group(process: subprocess.Popen) -> None:
    _signal_group(process)
    process.wait()


def _observed_wait(child, deadline_seconds, cancelled, *, capture_usage=False):
    # WNOWAIT notifies promptly without reaping, so the cancelling thread
    # cannot signal a process group whose leader PID has already been reused.
    ready = Event()
    errors = []
    def watch():
        try:
            os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        except Exception as exc:
            errors.append(exc)
        finally:
            ready.set()

    waiter = Thread(target=watch, name="tsbench-exit-observer")
    deadline = time.monotonic() + deadline_seconds
    state, reason = None, None
    try:
        waiter.start()
        while not ready.is_set():
            if cancelled():
                state, reason = "cancelled", "cancel requested during operation"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state, reason = "timeout", "worker exceeded per-operation deadline"
                break
            ready.wait(min(remaining, 0.02))
        if state is not None or not ready.is_set() or errors:
            _signal_group(child)
        # Finish the observer before reaping, even on timeout/cancel.
        waiter.join()
        if errors:
            raise OSError("process timing observer failed") from errors[0]
        usage = {}
        if capture_usage:
            _, exit_status, stats = os.wait4(child.pid, 0)
            code = child.returncode = os.waitstatus_to_exitcode(exit_status)
            usage = {"user_cpu_ns": round(stats.ru_utime * 1_000_000) * 1000,
                     "system_cpu_ns": round(stats.ru_stime * 1_000_000) * 1000,
                     "maxrss_bytes": stats.ru_maxrss * 1024}
        else:
            code = child.wait()
        stopped_ns = time.monotonic_ns()
    finally:
        if child.returncode is None:
            _signal_group(child)
            if waiter.ident is not None:
                waiter.join()
            child.wait()
    if state is None:
        state = "completed" if code == 0 else "crash" if code < 0 else "failed"
        reason = "" if code == 0 else f"worker exit {code}"
    return state, code, reason, stopped_ns, usage


def invoke(argv: list, workspace: Path, log_dir: Path, operation: str,
           deadline_seconds: int, cancelled, *, environment=None, observe_process=False, capture_usage=False) -> dict:
    if capture_usage and (not observe_process or not hasattr(os, "wait4")):
        raise ValueError("wait4 resource observer requires timed Linux process supervision")
    out, err = log_dir / f"{operation}.stdout", log_dir / f"{operation}.stderr"
    status, code, pid, session, reason = "cancelled", None, None, None, "cancel requested before launch"
    timing = {}
    if not cancelled():
        with out.open("xb") as stdout, err.open("xb") as stderr:
            env = environment if environment is not None else {"LC_ALL": "C", "HOME": str(workspace)}
            try:
                started_ns = time.monotonic_ns() if observe_process else None
                child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                         cwd=workspace, env=env, start_new_session=True)
            except FileNotFoundError as exc:
                status, reason = "dependency_failed", str(exc)
            except OSError as exc:
                status, reason = "failed", str(exc)
            else:
                pid, session = child.pid, uuid.uuid4().hex
                if started_ns is not None:
                    status, code, reason, stopped_ns, usage = _observed_wait(
                        child, deadline_seconds, cancelled, capture_usage=capture_usage)
                    if capture_usage:
                        timing["child_usage"] = usage
                    timing["process_wall_ns"] = stopped_ns - started_ns
                else:
                    deadline = time.monotonic() + deadline_seconds
                    try:
                        while True:
                            code = child.poll()
                            if code is not None:
                                status = "completed" if code == 0 else "crash" if code < 0 else "failed"
                                reason = "" if code == 0 else f"worker exit {code}"
                                break
                            if cancelled():
                                status, reason = "cancelled", "cancel requested during operation"
                                break
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                status, reason = "timeout", "worker exceeded per-operation deadline"
                                break
                            time.sleep(min(remaining, 0.02))
                    finally:
                        if code is None:
                            _kill_group(child)
                            code = child.returncode
    return {"operation": operation, "status": status, "returncode": code, "pid": pid,
            "session_id": session, "reason": reason, **timing}
