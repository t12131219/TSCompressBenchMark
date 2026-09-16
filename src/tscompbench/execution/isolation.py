from __future__ import annotations

import multiprocessing as mp
import os
import resource
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tscompbench.contracts import RunStatus


@dataclass(frozen=True)
class IsolatedCallResult:
    status: RunStatus
    value: Any | None
    exception_type: str | None
    message: str | None
    traceback_text: str | None
    exit_code: int | None
    limit_method: str


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
) -> None:
    method = "NOT_APPLIED"
    try:
        if cpu_affinity and hasattr(os, "sched_setaffinity"):
            os.sched_setaffinity(0, set(cpu_affinity))
        if memory_limit_bytes is not None:
            current_virtual = _virtual_memory_bytes()
            effective = max(memory_limit_bytes, current_virtual + 64 * 1024**2)
            resource.setrlimit(resource.RLIMIT_AS, (effective, effective))
            method = "RLIMIT_AS_WITH_EXISTING_VM_HEADROOM"
        value = function(*args, **kwargs)
        connection.send(("PASS", value, None, None, None, method))
    except MemoryError as error:
        connection.send(
            ("OOM", None, type(error).__name__, str(error), traceback.format_exc(), method)
        )
    except BaseException as error:
        connection.send(
            ("CRASHED", None, type(error).__name__, str(error), traceback.format_exc(), method)
        )
    finally:
        connection.close()


def run_isolated(
    function: Callable[..., Any],
    *args: Any,
    timeout_seconds: float,
    memory_limit_bytes: int | None = None,
    cpu_affinity: tuple[int, ...] | None = None,
    **kwargs: Any,
) -> IsolatedCallResult:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    context = mp.get_context("fork" if "fork" in mp.get_all_start_methods() else "spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_child,
        args=(child, function, args, kwargs, memory_limit_bytes, cpu_affinity),
        daemon=False,
    )
    process.start()
    child.close()
    try:
        if parent.poll(timeout_seconds):
            status, value, exception_type, message, trace, method = parent.recv()
            process.join(timeout=1)
            return IsolatedCallResult(
                RunStatus(status), value, exception_type, message, trace, process.exitcode, method
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
            f"worker exceeded {timeout_seconds} seconds",
            None,
            process.exitcode,
            "PARENT_DEADLINE",
        )
    except EOFError:
        process.join(timeout=1)
        return IsolatedCallResult(
            RunStatus.CRASHED,
            None,
            "WorkerExit",
            "worker exited without a result envelope",
            None,
            process.exitcode,
            "UNKNOWN",
        )
    finally:
        parent.close()
