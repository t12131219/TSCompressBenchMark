from __future__ import annotations

import os
import threading
import time

import pytest

from tscompbench.contracts import RunStatus
from tscompbench.execution.isolation import run_isolated
from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement.thread_monitor import thread_budget_evidence


def temporary_threads():
    stop = threading.Event()
    threads = [threading.Thread(target=stop.wait) for _ in range(3)]
    for thread in threads:
        thread.start()
    time.sleep(0.04)
    stop.set()
    for thread in threads:
        thread.join()
    return os.getpid()


def sleeping_worker():
    time.sleep(5)


def test_parent_sampler_catches_real_threads_that_disappear_before_worker_exit():
    result = run_isolated(
        temporary_threads,
        timeout_seconds=5,
        start_method="spawn",
        thread_monitor_interval_ns=1_000_000,
    )
    assert result.status is RunStatus.PASS
    evidence = result.lifecycle_document()["thread_observation"]
    assert evidence["worker_pid"] == result.value
    assert evidence["classification"] == "INSTRUMENTED_SAMPLED_LOWER_BOUND"
    boundaries = evidence["worker_boundaries"]
    assert evidence["sampled_peak_threads"] >= boundaries["function_entry"]["thread_count"] + 3
    assert (
        boundaries["function_entry"]["thread_count"] == boundaries["function_exit"]["thread_count"]
    )
    assert evidence["captures_all_transient_threads"] is False
    assert evidence["actual_max_gap_ns"] >= evidence["requested_interval_ns"]
    assert canonical_json_bytes(evidence)
    budget = thread_budget_evidence(
        evidence, thread_budget=boundaries["function_entry"]["thread_count"]
    )
    assert budget["status"] == "EXCEEDS_BUDGET"
    observed = thread_budget_evidence(evidence, thread_budget=evidence["sampled_peak_threads"])
    assert observed["status"] == "NO_EXCESS_OBSERVED"
    assert observed["strict_high_water_verified"] is False


def test_disabled_sampler_keeps_unobserved_status_and_legacy_execution():
    result = run_isolated(os.getpid, timeout_seconds=5, start_method="spawn")
    assert result.status is RunStatus.PASS
    evidence = result.lifecycle_document()["thread_observation"]
    assert evidence["status"] == "NOT_OBSERVED"
    assert evidence["sampled_peak_threads"] is None
    assert thread_budget_evidence(evidence, thread_budget=1)["status"] == "UNKNOWN"


def test_timeout_retains_sampled_thread_series_and_worker_exit():
    result = run_isolated(
        sleeping_worker,
        timeout_seconds=0.2,
        start_method="spawn",
        thread_monitor_interval_ns=1_000_000,
    )
    assert result.status is RunStatus.TIMEOUT
    assert result.worker_exit_confirmed
    assert result.thread_observation["samples"]
    assert result.thread_observation["sampled_peak_threads"] >= 1


def test_shared_absolute_deadline_never_starts_later_worker():
    expired = time.perf_counter_ns() - 1
    result = run_isolated(os.getpid, timeout_seconds=5, start_method="spawn", deadline_ns=expired)
    assert result.status is RunStatus.TIMEOUT
    assert result.worker_pid is None
    assert result.worker_failure_stage == "WORKER_NOT_STARTED_DEADLINE_EXHAUSTED"
    assert result.lifecycle_document()["worker_launched"] is False
    deadline = time.perf_counter_ns() + 150_000_000
    started = time.monotonic()
    result = run_isolated(
        sleeping_worker, timeout_seconds=5, start_method="spawn", deadline_ns=deadline
    )
    assert result.status is RunStatus.TIMEOUT
    assert time.monotonic() - started < 2
    assert result.lifecycle_document()["absolute_deadline_ns"] == deadline
    later = run_isolated(os.getpid, timeout_seconds=5, start_method="spawn", deadline_ns=deadline)
    assert later.worker_pid is None


@pytest.mark.parametrize("interval", [0, 1, True, float("inf"), 1_000_000.0])
def test_thread_sampler_rejects_degenerate_interval(interval):
    with pytest.raises(ValueError):
        run_isolated(os.getpid, timeout_seconds=5, thread_monitor_interval_ns=interval)
