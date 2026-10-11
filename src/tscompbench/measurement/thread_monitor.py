"""Parent-side /proc sampling with explicit lower-bound thread evidence."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def thread_boundary(pid: int) -> dict[str, Any]:
    started = time.perf_counter_ns()
    count = None
    reason = "PROCESS_EXITED_OR_PROC_STATUS_UNAVAILABLE"
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith("Threads:"):
                count = int(line.split()[1])
                reason = None
                break
    except OSError, ValueError, UnicodeError:
        pass
    return {
        "worker_pid": pid,
        "observed_ns": started,
        "read_finished_ns": time.perf_counter_ns(),
        "thread_count": count,
        "reason": reason,
    }


class ParentThreadMonitor:
    """Read a worker's Threads counter without adding a worker sampling thread."""

    def __init__(self, pid: int, interval_ns: int) -> None:
        if type(interval_ns) is not int or not 1_000_000 <= interval_ns <= 2**63 - 1:
            raise ValueError("thread monitor interval must be a finite integer >= 1ms")
        self.pid = pid
        self.interval_ns = interval_ns
        self.samples: list[dict[str, Any]] = []
        self._last_ns: int | None = None

    def sample(self, phase: str, *, force: bool = False) -> None:
        now = time.perf_counter_ns()
        if not force and self._last_ns is not None and now - self._last_ns < self.interval_ns:
            return
        sample = thread_boundary(self.pid)
        self.samples.append({**sample, "phase": phase})
        self._last_ns = sample["observed_ns"]

    def to_document(self, *, worker_boundaries: dict[str, Any] | None = None) -> dict[str, Any]:
        boundaries = worker_boundaries or {}
        counts = [
            sample["thread_count"] for sample in self.samples if sample["thread_count"] is not None
        ]
        counts += [
            sample["thread_count"]
            for sample in boundaries.values()
            if sample["thread_count"] is not None
        ]
        gaps = [
            last["observed_ns"] - first["observed_ns"]
            for first, last in zip(self.samples, self.samples[1:], strict=False)
        ]
        return {
            "schema_version": "tscb.worker-thread-observation.v3.2",
            "status": "OBSERVED" if counts else "UNAVAILABLE",
            "classification": "INSTRUMENTED_SAMPLED_LOWER_BOUND",
            "worker_pid": self.pid,
            "requested_interval_ns": self.interval_ns,
            "actual_min_gap_ns": min(gaps) if gaps else None,
            "actual_max_gap_ns": max(gaps) if gaps else None,
            "sampled_peak_threads": max(counts) if counts else None,
            "samples": list(self.samples),
            "worker_boundaries": boundaries,
            "scope": "TARGET_WORKER_PROCESS_ALL_THREADS_NOT_DESCENDANTS",
            "sampler_location": "SUPERVISING_PARENT_NO_ADDED_WORKER_THREAD",
            "worker_boundary_scope": "FUNCTION_ENTRY_EXIT_NOT_ENCODE_DECODE_BOUNDARIES",
            "captures_all_transient_threads": False,
            "limitation": "THREADS_CREATED_AND_JOINED_BETWEEN_READS_CAN_BE_MISSED",
            "disturbance_requires_matched_pilot": True,
        }


def unobserved_threads(pid: int | None) -> dict[str, Any]:
    return {
        "schema_version": "tscb.worker-thread-observation.v3.2",
        "status": "NOT_OBSERVED",
        "worker_pid": pid,
        "classification": None,
        "sampled_peak_threads": None,
        "samples": [],
        "worker_boundaries": {},
        "requested_interval_ns": None,
        "scope": "TARGET_WORKER_PROCESS_ALL_THREADS_NOT_DESCENDANTS",
        "captures_all_transient_threads": False,
        "reason": "THREAD_MONITOR_DISABLED",
    }


def thread_budget_evidence(observation: dict[str, Any], *, thread_budget: int) -> dict[str, Any]:
    """A sampled excess proves failure; no observed excess cannot prove a strict cap."""
    if type(thread_budget) is not int or thread_budget < 1:
        raise ValueError("thread budget must be a positive integer")
    peak = observation.get("sampled_peak_threads")
    available = observation.get("status") == "OBSERVED" and type(peak) is int
    exceeds = available and peak > thread_budget
    return {
        "thread_budget": thread_budget,
        "sampled_peak_threads": peak,
        "observed_excess": exceeds,
        "within_observed_samples": available and not exceeds,
        "strict_high_water_verified": False,
        "status": "EXCEEDS_BUDGET" if exceeds else "NO_EXCESS_OBSERVED" if available else "UNKNOWN",
        "reason": "TRANSIENT_THREADS_AND_DESCENDANT_PROCESSES_NOT_EXHAUSTIVELY_OBSERVED",
    }
