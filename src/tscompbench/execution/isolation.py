from __future__ import annotations

import multiprocessing as mp
import os
import resource
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tscompbench.contracts import RunStatus
from tscompbench.measurement.thread_monitor import (
    ParentThreadMonitor,
    thread_boundary,
    unobserved_threads,
)


@dataclass(frozen=True)
class IsolatedCallResult:
    status: RunStatus
    value: Any | None
    exception_type: str | None
    message: str | None
    traceback_text: str | None
    exit_code: int | None
    limit_method: str
    worker_pid: int | None = None
    parent_pid: int | None = None
    start_method: str | None = None
    parent_started_ns: int | None = None
    worker_started_ns: int | None = None
    parent_finished_ns: int | None = None
    worker_exit_confirmed: bool = False
    worker_failure_stage: str | None = None
    worker_measurement_evidence: dict[str, Any] | None = None
    thread_observation: dict[str, Any] | None = None
    absolute_deadline_ns: int | None = None

    def lifecycle_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.isolated-worker-lifecycle.v1",
            "worker_pid": self.worker_pid,
            "worker_launched": self.worker_pid is not None,
            "parent_pid": self.parent_pid,
            "start_method": self.start_method,
            "clock": "PERF_COUNTER_NS",
            "parent_started_ns": self.parent_started_ns,
            "worker_started_ns": self.worker_started_ns,
            "parent_finished_ns": self.parent_finished_ns,
            "worker_exit_confirmed": self.worker_exit_confirmed,
            "exit_code": self.exit_code,
            "failure_stage": self.worker_failure_stage,
            "thread_observation": self.thread_observation or unobserved_threads(self.worker_pid),
            "absolute_deadline_ns": self.absolute_deadline_ns,
            "parent_state_inheritance": (
                "FORK_SNAPSHOT" if self.start_method == "fork" else "SPAWN_ARGUMENTS"
            ),
        }


def _virtual_memory_bytes() -> int:
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            pages = int(handle.read().split()[0])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except OSError, ValueError, IndexError:
        return 0


def _child(
    connection: Any,
    function: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    memory_limit_bytes: int | None,
    cpu_affinity: tuple[int, ...] | None,
    monitor_threads: bool,
) -> None:
    worker_started_ns = time.perf_counter_ns()
    method = "NOT_APPLIED"
    boundaries: dict[str, Any] = {}

    def finish_boundaries() -> dict[str, Any] | None:
        if not monitor_threads:
            return None
        boundaries["function_exit"] = thread_boundary(os.getpid())
        return boundaries

    try:
        if cpu_affinity and hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, set(cpu_affinity))
        if memory_limit_bytes is not None:
            current_virtual = _virtual_memory_bytes()
            effective = max(memory_limit_bytes, current_virtual + 64 * 1024**2)
            resource.setrlimit(resource.RLIMIT_AS, (effective, effective))
            method = "RLIMIT_AS_WITH_EXISTING_VM_HEADROOM"
        if monitor_threads:
            boundaries["function_entry"] = thread_boundary(os.getpid())
        value = function(*args, **kwargs)
        connection.send(
            (
                "PASS",
                value,
                None,
                None,
                None,
                method,
                worker_started_ns,
                None,
                None,
                finish_boundaries(),
            )
        )
    except MemoryError as error:
        connection.send(
            (
                "OOM",
                None,
                type(error).__name__,
                str(error),
                traceback.format_exc(),
                method,
                worker_started_ns,
                None,
                None,
                finish_boundaries(),
            )
        )
    except BaseException as error:
        exception_type = getattr(error, "original_exception_type", type(error).__name__)
        connection.send(
            (
                "OOM" if exception_type == "MemoryError" else "CRASHED",
                None,
                exception_type,
                str(error),
                traceback.format_exc(),
                method,
                worker_started_ns,
                getattr(error, "worker_failure_stage", None),
                getattr(error, "worker_measurement_evidence", None),
                finish_boundaries(),
            )
        )
    finally:
        connection.close()


def run_isolated(
    function: Callable[..., Any],
    *args: Any,
    timeout_seconds: float,
    memory_limit_bytes: int | None = None,
    cpu_affinity: tuple[int, ...] | None = None,
    start_method: str | None = None,
    thread_monitor_interval_ns: int | None = None,
    deadline_ns: int | None = None,
    **kwargs: Any,
) -> IsolatedCallResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if deadline_ns is not None and (type(deadline_ns) is not int or deadline_ns <= 0):
        raise ValueError("absolute deadline must be a positive PERF_COUNTER_NS integer")
    if thread_monitor_interval_ns is not None and (
        type(thread_monitor_interval_ns) is not int
        or not 1_000_000 <= thread_monitor_interval_ns <= 2**63 - 1
    ):
        raise ValueError("thread monitor interval must be a finite integer >= 1ms")
    selected_start_method = start_method or (
        "fork" if "fork" in mp.get_all_start_methods() else "spawn"
    )
    if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
        now = time.perf_counter_ns()
        return IsolatedCallResult(
            RunStatus.TIMEOUT,
            None,
            "TimeoutError",
            "absolute trial deadline exhausted before launch",
            None,
            None,
            "PARENT_ABSOLUTE_DEADLINE_NO_WORKER",
            worker_pid=None,
            parent_pid=os.getpid(),
            start_method=selected_start_method,
            parent_started_ns=now,
            parent_finished_ns=now,
            worker_exit_confirmed=False,
            worker_failure_stage="WORKER_NOT_STARTED_DEADLINE_EXHAUSTED",
            thread_observation=unobserved_threads(None),
            absolute_deadline_ns=deadline_ns,
        )
    context = mp.get_context(selected_start_method)
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_child,
        args=(
            child,
            function,
            args,
            kwargs,
            memory_limit_bytes,
            cpu_affinity,
            thread_monitor_interval_ns is not None,
        ),
        daemon=False,
    )
    parent_started_ns = time.perf_counter_ns()
    parent_pid = os.getpid()
    process.start()
    child.close()
    monitor = (
        None
        if thread_monitor_interval_ns is None
        else ParentThreadMonitor(process.pid, thread_monitor_interval_ns)
    )
    lifecycle = {
        "worker_pid": process.pid,
        "parent_pid": parent_pid,
        "start_method": selected_start_method,
        "parent_started_ns": parent_started_ns,
        "absolute_deadline_ns": deadline_ns,
    }
    try:
        remaining_seconds = (
            timeout_seconds
            if deadline_ns is None
            else min(timeout_seconds, max(0, (deadline_ns - time.perf_counter_ns()) / 1e9))
        )
        if monitor is None:
            ready = parent.poll(remaining_seconds)
        else:
            deadline = time.monotonic() + remaining_seconds
            monitor.sample("PARENT_STARTED_WORKER", force=True)
            ready = False
            while time.monotonic() < deadline:
                monitor.sample("WAITING_FOR_WORKER_ENVELOPE")
                if parent.poll(max(0, min(deadline - time.monotonic(), monitor.interval_ns / 1e9))):
                    ready = True
                    monitor.sample("PARENT_RESULT_BOUNDARY", force=True)
                    break
        if ready:
            (
                status,
                value,
                exception_type,
                message,
                trace,
                method,
                worker_started_ns,
                failure_stage,
                measurement_evidence,
                worker_thread_boundaries,
            ) = parent.recv()
            process.join(timeout=1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                status = "CRASHED"
                exception_type = "WorkerExitTimeout"
                message = "worker sent a result but did not exit"
                value = None
            elif status == "PASS" and process.exitcode != 0:
                status = "CRASHED"
                exception_type = "WorkerExit"
                message = "worker exited unsuccessfully after sending a result"
                value = None
            if (
                status == "PASS"
                and deadline_ns is not None
                and time.perf_counter_ns() >= deadline_ns
            ):
                status = "TIMEOUT"
                exception_type = "TimeoutError"
                message = "absolute trial deadline exhausted before worker exit/materialization"
                value = None
            return IsolatedCallResult(
                RunStatus(status),
                value,
                exception_type,
                message,
                trace,
                process.exitcode,
                method,
                **lifecycle,
                worker_started_ns=worker_started_ns,
                parent_finished_ns=time.perf_counter_ns(),
                worker_exit_confirmed=not process.is_alive(),
                worker_failure_stage=failure_stage,
                worker_measurement_evidence=measurement_evidence,
                thread_observation=(
                    unobserved_threads(process.pid)
                    if monitor is None
                    else monitor.to_document(worker_boundaries=worker_thread_boundaries)
                ),
            )
        process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        return IsolatedCallResult(
            RunStatus.TIMEOUT,
            None,
            "TimeoutError",
            "absolute trial deadline exhausted"
            if deadline_ns is not None
            else f"worker exceeded {timeout_seconds} seconds",
            None,
            process.exitcode,
            "PARENT_DEADLINE",
            **lifecycle,
            parent_finished_ns=time.perf_counter_ns(),
            worker_exit_confirmed=not process.is_alive(),
            worker_failure_stage="WORKER_DEADLINE_UNKNOWN_PHASE",
            thread_observation=(
                unobserved_threads(process.pid) if monitor is None else monitor.to_document()
            ),
        )
    except EOFError:
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
        return IsolatedCallResult(
            RunStatus.CRASHED,
            None,
            "WorkerExit",
            "worker exited without a result envelope",
            None,
            process.exitcode,
            "UNKNOWN",
            **lifecycle,
            parent_finished_ns=time.perf_counter_ns(),
            worker_exit_confirmed=not process.is_alive(),
            worker_failure_stage="WORKER_EXIT_UNKNOWN_PHASE",
            thread_observation=(
                unobserved_threads(process.pid) if monitor is None else monitor.to_document()
            ),
        )
    finally:
        parent.close()
