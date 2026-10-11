"""P2 interruption contracts use mock workers and never invoke native codecs."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from tscompbench.comparison import pipeline_runner as runner
from tscompbench.comparison.analysis import AnalysisPolicy
from tscompbench.contracts import RunStatus
from tscompbench.execution.isolation import IsolatedCallResult
from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement.v32_protocol import MeasurementProtocol


class Interrupted(BaseException):
    """Model abrupt parent termination without manufacturing a worker outcome."""


class Lease:
    def to_document(self):
        return {"status": "HELD"}


def _setup(tmp_path, monkeypatch, *, count=1):
    protocol = MeasurementProtocol(
        profile="STEADY_PROCESS",
        outer_repetitions=count,
        encode_min_ns=1,
        decode_min_ns=1,
        max_trial_wall_ns=100_000_000,
        max_total_wall_ns=150_000_000,
        thread_monitor_interval_ns=1_000_000,
    )
    slots = [
        {
            "trial_id": "trial:" + str(i).zfill(64),
            "execution_job_id": "job",
            "sequence_index": i,
            "block_index": i,
        }
        for i in range(count)
    ]
    plan = {
        "run_set_id": "frozen-run",
        "decision_id": "mock-decision",
        "decision": {"decision_id": "mock-decision", "scope": "MOCK_TEST_ONLY"},
        "schedule_id": "schedule",
        "project_root": "public-root",
        "resources": {
            "logical_cpus": [0],
            "threads": 1,
            "memory_limit_bytes": 1_073_741_824,
        },
        "protocol": protocol.to_document(),
        "attempt_policy": runner.ATTEMPT_POLICY,
        "schedule": {"trials": slots},
        "cells": [
            {"cell_id": "cell", "dataset_key": "test", "execution_job_id": "job", "recipe": {}}
        ],
        "datasets": [{"dataset_key": "test", "test": {}}],
    }
    (tmp_path / "plan.json").write_bytes(canonical_json_bytes(plan))
    for name in ("qualification.json", "pilot.json"):
        (tmp_path / name).write_text("{}")
    monkeypatch.setattr(runner, "validate_pipeline_plan", lambda *_: None)
    monkeypatch.setattr(runner, "_validate_auxiliary", lambda *_: None)
    monkeypatch.setattr(runner, "_audit_trials", lambda *_: {})
    monkeypatch.setattr(runner, "_lease", lambda *_: nullcontext(Lease()))
    monkeypatch.setattr(runner, "environment_gate", lambda *_: {"eligible": True})
    monkeypatch.setattr(runner, "thread_budget_evidence", lambda *_, **__: {})

    def report(path):
        trials = runner._trials(path / "trials.jsonl")
        state = runner._attempt_state(path, plan, trials)
        return {
            "committed": len(state["committed"]),
            "unresolved": state["unresolved"],
            "budget_used_ns": state["budget_used_ns"],
            "event_log_sha256": state["event_log_sha256"],
        }

    monkeypatch.setattr(runner, "report_pipeline_comparison", report)
    return plan, slots


def _result(*, passed=False):
    return IsolatedCallResult(
        status=RunStatus.PASS if passed else RunStatus.CORRECTNESS_FAIL,
        value={"stream": b"preserved opaque artifact"} if passed else None,
        exception_type=None,
        message="mock outcome",
        traceback_text=None,
        exit_code=0,
        limit_method="MOCK",
        thread_observation={"mock_observed_fraction": 0.25},
    )


def _events(path):
    return [json.loads(line) for line in (path / "pipeline_events.jsonl").read_bytes().splitlines()]


def test_started_intent_is_durable_before_worker_and_failed_attempt_never_retries(
    tmp_path, monkeypatch
):
    plan, slots = _setup(tmp_path, monkeypatch)
    calls = []

    def worker(*args, **kwargs):
        events = _events(tmp_path)
        assert len(events) == 1 and events[0]["event_type"] == "STARTED"
        assert events[0]["frozen_plan_sha256"] == runner._sha(tmp_path / "plan.json")
        assert kwargs["deadline_ns"] == events[0]["started_ns"] + events[0]["reserved_wall_ns"]
        calls.append("worker")
        return _result()

    monkeypatch.setattr(runner, "run_isolated", worker)
    runner.execute_pipeline_comparison(tmp_path)
    trials = runner._trials(tmp_path / "trials.jsonl")
    events = _events(tmp_path)
    assert len(trials) == 1 and trials[0]["status"] == "CORRECTNESS_FAIL"
    assert (
        trials[0]["measurement_lifecycle"]["thread_observation"]["mock_observed_fraction"] == "0.25"
    )
    assert [e["event_type"] for e in events] == ["STARTED", "TERMINAL_COMMITTED"]
    assert (
        events[1]["terminal_trial_sha256"]
        == hashlib.sha256(canonical_json_bytes(trials[0])).hexdigest()
    )
    before = {
        name: runner._sha(tmp_path / name) for name in ("trials.jsonl", "pipeline_events.jsonl")
    }
    runner.execute_pipeline_comparison(tmp_path)
    assert calls == ["worker"]
    assert all(runner._sha(tmp_path / name) == digest for name, digest in before.items())


def test_unknown_started_attempt_keeps_reservation_and_blocks_repeated_resume(
    tmp_path, monkeypatch
):
    plan, slots = _setup(tmp_path, monkeypatch)
    calls = []

    def interrupted_worker(*args, **kwargs):
        calls.append("worker")
        raise Interrupted()

    monkeypatch.setattr(runner, "run_isolated", interrupted_worker)
    with pytest.raises(Interrupted):
        runner.execute_pipeline_comparison(tmp_path)
    before = (tmp_path / "pipeline_events.jsonl").read_bytes()
    assert not (tmp_path / "trials.jsonl").exists()
    for _ in range(2):
        with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
            runner.execute_pipeline_comparison(tmp_path)
        diagnostic = json.loads((tmp_path / "interruption_audit.json").read_text())
        assert diagnostic["status"] == "BLOCKED_INTERRUPTED_ATTEMPT"
        assert diagnostic["budget_used_ns"] == 100_000_000
        assert diagnostic["automatic_retry_permitted"] is False
        assert diagnostic["unresolved_attempts"][0]["trial_id"] == slots[0]["trial_id"]
    assert calls == ["worker"]
    assert (tmp_path / "pipeline_events.jsonl").read_bytes() == before


def test_saved_artifact_without_terminal_append_is_preserved_and_never_overwritten(
    tmp_path, monkeypatch
):
    plan, slots = _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(runner, "load_pipeline_input", lambda *_: object())

    def worker(*args, **kwargs):
        calls.append("worker")
        return _result(passed=True)

    def interrupt_recovery(*args, **kwargs):
        raise Interrupted()

    monkeypatch.setattr(runner, "run_isolated", worker)
    monkeypatch.setattr(runner, "_recovery", interrupt_recovery)
    with pytest.raises(Interrupted):
        runner.execute_pipeline_comparison(tmp_path)
    artifact = runner._artifact_path(tmp_path, slots[0]["trial_id"])
    saved = artifact.read_bytes()
    assert saved == b"preserved opaque artifact"
    assert not (tmp_path / "trials.jsonl").exists()
    with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
        runner.execute_pipeline_comparison(tmp_path)
    assert artifact.read_bytes() == saved and calls == ["worker"]
    diagnostic = json.loads((tmp_path / "interruption_audit.json").read_text())
    assert diagnostic["unresolved_attempts"][0]["artifact"]["sha256"] == runner._sha(artifact)


def test_durable_raw_without_commit_event_recovers_commit_without_worker(tmp_path, monkeypatch):
    plan, slots = _setup(tmp_path, monkeypatch)
    calls = []

    def worker(*args, **kwargs):
        calls.append("worker")
        return _result()

    actual_commit = runner._commit_attempt

    def interrupted_commit(*args, **kwargs):
        raise Interrupted()

    monkeypatch.setattr(runner, "run_isolated", worker)
    monkeypatch.setattr(runner, "_commit_attempt", interrupted_commit)
    with pytest.raises(Interrupted):
        runner.execute_pipeline_comparison(tmp_path)
    raw = (tmp_path / "trials.jsonl").read_bytes()
    assert len(_events(tmp_path)) == 1
    monkeypatch.setattr(runner, "_commit_attempt", actual_commit)
    result = runner.execute_pipeline_comparison(tmp_path)
    assert result["committed"] == 1 and not result["unresolved"]
    assert calls == ["worker"] and (tmp_path / "trials.jsonl").read_bytes() == raw
    event_before = (tmp_path / "pipeline_events.jsonl").read_bytes()
    assert runner.execute_pipeline_comparison(tmp_path) == result
    assert (tmp_path / "pipeline_events.jsonl").read_bytes() == event_before


def test_unbound_existing_artifact_blocks_before_worker_and_is_not_overwritten(
    tmp_path, monkeypatch
):
    plan, slots = _setup(tmp_path, monkeypatch)
    artifact = runner._artifact_path(tmp_path, slots[0]["trial_id"])
    artifact.parent.mkdir()
    artifact.write_bytes(b"unbound old attempt")
    monkeypatch.setattr(
        runner, "run_isolated", lambda *_a, **_k: pytest.fail("worker must not run")
    )
    with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
        runner.execute_pipeline_comparison(tmp_path)
    assert artifact.read_bytes() == b"unbound old attempt"
    assert not (tmp_path / "pipeline_events.jsonl").exists()
    diagnostic = json.loads((tmp_path / "interruption_audit.json").read_text())
    assert diagnostic["budget_accounting_status"] == "UNKNOWN_UNBOUND_ARTIFACT_COST_RUN_BLOCKED"


def test_concurrent_executor_lock_rejects_before_any_worker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        runner, "run_isolated", lambda *_a, **_k: pytest.fail("worker must not run")
    )
    descriptor = os.open(tmp_path / ".pipeline.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(runner.PipelineComparisonError, match="lock is already held"):
            runner.execute_pipeline_comparison(tmp_path)
    finally:
        os.close(descriptor)


def test_remaining_total_budget_limits_next_worker_reservation(tmp_path, monkeypatch):
    plan, slots = _setup(tmp_path, monkeypatch, count=2)
    clock = iter([1, 90_000_001, 100_000_001, 160_000_001])
    monkeypatch.setattr(runner.time, "perf_counter_ns", lambda: next(clock))
    deadlines = []

    def worker(*args, **kwargs):
        deadlines.append((kwargs["timeout_seconds"], kwargs["deadline_ns"]))
        return _result()

    monkeypatch.setattr(runner, "run_isolated", worker)
    runner.execute_pipeline_comparison(tmp_path)
    starts = [e for e in _events(tmp_path) if e["event_type"] == "STARTED"]
    assert [e["reserved_wall_ns"] for e in starts] == [100_000_000, 60_000_000]
    assert deadlines == [(0.1, 100_000_001), (0.06, 160_000_001)]


@pytest.mark.parametrize("mutation", ["hash", "plan", "budget", "repeat", "truncated"])
def test_attempt_event_corruption_cannot_enable_retry(tmp_path, monkeypatch, mutation):
    plan, slots = _setup(tmp_path, monkeypatch)
    state = runner._attempt_state(tmp_path, plan, [])
    runner._attempt_event(
        tmp_path,
        plan,
        state,
        slots[0],
        "STARTED",
        started_ns=1,
        reserved_wall_ns=100_000_000,
        budget_prior_ns=0,
        budget_reserved_total_ns=100_000_000,
    )
    event = _events(tmp_path)[0]
    path = tmp_path / "pipeline_events.jsonl"
    if mutation == "hash":
        event["event_sha256"] = "0" * 64
        path.write_bytes(canonical_json_bytes(event) + b"\n")
    elif mutation == "plan":
        altered = copy.deepcopy(plan)
        altered["run_set_id"] = "different-plan"
        (tmp_path / "plan.json").write_bytes(canonical_json_bytes(altered))
    elif mutation == "budget":
        event["reserved_wall_ns"] = 1
        event.pop("event_sha256")
        event["event_sha256"] = hashlib.sha256(canonical_json_bytes(event)).hexdigest()
        path.write_bytes(canonical_json_bytes(event) + b"\n")
    elif mutation == "repeat":
        repeated = dict(event, event_index=1, previous_event_sha256=event["event_sha256"])
        repeated.pop("event_sha256")
        repeated["event_sha256"] = hashlib.sha256(canonical_json_bytes(repeated)).hexdigest()
        with path.open("ab") as handle:
            handle.write(canonical_json_bytes(repeated) + b"\n")
    else:
        path.write_bytes(path.read_bytes()[:-1])
    monkeypatch.setattr(
        runner, "run_isolated", lambda *_a, **_k: pytest.fail("worker must not run")
    )
    with pytest.raises(runner.PipelineComparisonError):
        runner.execute_pipeline_comparison(tmp_path)


def test_truncated_terminal_and_existing_artifact_cannot_be_replaced(tmp_path):
    path = tmp_path / "trials.jsonl"
    path.write_bytes(b'{"trial_id":"complete JSON without durable line terminator"}')
    with pytest.raises(runner.PipelineComparisonError, match="terminal log truncated"):
        runner._trials(path)
    artifact = tmp_path / "attempt.p2"
    artifact.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        runner._save_artifact(artifact, b"new bytes")
    assert artifact.read_bytes() == b"original"


@pytest.mark.parametrize("raw", [b"null\n", b"42\n", b"[]\n", b'{"trial_id":"bad"}\n'])
def test_malformed_terminal_records_block_before_any_worker(tmp_path, monkeypatch, raw):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "trials.jsonl").write_bytes(raw)
    monkeypatch.setattr(
        runner, "run_isolated", lambda *_a, **_k: pytest.fail("worker must not run")
    )
    with pytest.raises(runner.PipelineComparisonError, match="terminal"):
        runner.execute_pipeline_comparison(tmp_path)
    assert (tmp_path / "trials.jsonl").read_bytes() == raw


def test_report_retains_interrupted_slot_and_reservation_as_inconclusive(tmp_path, monkeypatch):
    real_report = runner.report_pipeline_comparison
    plan, slots = _setup(tmp_path, monkeypatch)
    plan["analysis_policy"] = AnalysisPolicy().to_document()
    plan["scope"], plan["boundary"] = "MOCK_TEST_ONLY", "MOCK_TEST_ONLY"
    plan["cells"][0].update(method_id="lz4-frame", recipe_id="recipe", canonical_raw_bits=8)
    plan["datasets"][0]["test"]["schema"] = {"fixture": True}
    (tmp_path / "plan.json").write_bytes(canonical_json_bytes(plan))
    state = runner._attempt_state(tmp_path, plan, [])
    runner._attempt_event(
        tmp_path,
        plan,
        state,
        slots[0],
        "STARTED",
        started_ns=1,
        reserved_wall_ns=100_000_000,
        budget_prior_ns=0,
        budget_reserved_total_ns=100_000_000,
    )
    report = real_report(tmp_path)
    assert report["status"] == "INCONCLUSIVE"
    assert report["expected_trials"] == 1 and report["recorded_trials"] == 0
    assert report["attempt_audit"]["unresolved_attempts"] == [slots[0]["trial_id"]]
    assert report["attempt_audit"]["budget_used_ns"] == 100_000_000
    assert report["attempt_audit"]["automatic_retry_permitted"] is False


def _qualification_setup(tmp_path, monkeypatch):
    plan, _ = _setup(tmp_path, monkeypatch)
    (tmp_path / "qualification.json").unlink()
    monkeypatch.setattr(runner, "load_pipeline_input", lambda *_: object())
    monkeypatch.setattr(
        runner, "PipelineRecipe", SimpleNamespace(from_document=lambda document: document)
    )
    artifact = SimpleNamespace(
        stream=b"preserved qualification bytes",
        ledger=SimpleNamespace(to_document=lambda: {"test_ledger": True}),
        recipe_id="test_recipe",
    )
    return plan, artifact


def test_qualification_intent_precedes_codec_and_saved_success_is_reused(tmp_path, monkeypatch):
    plan, artifact = _qualification_setup(tmp_path, monkeypatch)
    calls = []

    def encode(*_args):
        intent = json.loads((tmp_path / "qualification_intent.json").read_text())
        assert intent["frozen_plan_sha256"] == runner._sha(tmp_path / "plan.json")
        assert intent["cell_ids"] == [plan["cells"][0]["cell_id"]]
        assert intent["scope"] == "AUXILIARY_QUALIFICATION_NOT_PERFORMANCE"
        calls.append("encode")
        return artifact

    def recovery(*_args):
        assert (tmp_path / "qualification_artifacts" / "cell.p2").read_bytes() == artifact.stream
        calls.append("recovery")
        return {"test_recovery": True, "mock_elapsed_fraction": 0.25}

    monkeypatch.setattr(runner, "_encode", encode)
    monkeypatch.setattr(runner, "_recovery", recovery)
    document = runner.qualify_pipeline_comparison(tmp_path)
    assert document["status"] == "PASS"
    assert document["cases"][0]["recovery"]["mock_elapsed_fraction"] == "0.25"
    saved = (tmp_path / "qualification.json").read_bytes()
    assert runner.qualify_pipeline_comparison(tmp_path) == document
    assert calls == ["encode", "recovery"]
    assert (tmp_path / "qualification.json").read_bytes() == saved


@pytest.mark.parametrize("failure_stage", ["encode", "recovery"])
def test_known_qualification_failure_is_preserved_and_cannot_be_retried(
    tmp_path, monkeypatch, failure_stage
):
    plan, artifact = _qualification_setup(tmp_path, monkeypatch)
    calls = []

    def encode(*_args):
        calls.append("encode")
        if failure_stage == "encode":
            raise runner.PipelineComparisonError("known encoder failure")
        return artifact

    def recovery(*_args):
        calls.append("recovery")
        raise runner.PipelineComparisonError("known decoder failure")

    monkeypatch.setattr(runner, "_encode", encode)
    monkeypatch.setattr(runner, "_recovery", recovery)
    with pytest.raises(runner.PipelineComparisonError, match="known"):
        runner.qualify_pipeline_comparison(tmp_path)
    failure_path = tmp_path / "qualification_failure.json"
    failure_bytes = failure_path.read_bytes()
    failure = json.loads(failure_bytes)
    assert failure["status"] == "FAILED" and failure["automatic_retry_permitted"] is False
    assert (
        failure["artifact_sha256"] is None
        if failure_stage == "encode"
        else (
            failure["artifact_sha256"]
            == runner._sha(tmp_path / "qualification_artifacts" / "cell.p2")
        )
    )
    before_calls = calls[:]
    with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
        runner.qualify_pipeline_comparison(tmp_path)
    assert calls == before_calls and failure_path.read_bytes() == failure_bytes
    if failure_stage == "recovery":
        assert (tmp_path / "qualification_artifacts" / "cell.p2").read_bytes() == artifact.stream


def test_abrupt_qualification_before_artifact_preserves_intent_and_blocks(tmp_path, monkeypatch):
    _qualification_setup(tmp_path, monkeypatch)
    calls = []

    def encode(*_args):
        calls.append("encode")
        raise Interrupted()

    monkeypatch.setattr(runner, "_encode", encode)
    with pytest.raises(Interrupted):
        runner.qualify_pipeline_comparison(tmp_path)
    intent = (tmp_path / "qualification_intent.json").read_bytes()
    with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
        runner.qualify_pipeline_comparison(tmp_path)
    assert calls == ["encode"]
    assert (tmp_path / "qualification_intent.json").read_bytes() == intent
    assert not (tmp_path / "qualification_failure.json").exists()


def test_existing_uncommitted_qualification_artifact_blocks_before_encode(tmp_path, monkeypatch):
    _qualification_setup(tmp_path, monkeypatch)
    path = tmp_path / "qualification_artifacts" / "cell.p2"
    path.parent.mkdir()
    path.write_bytes(b"earlier qualification attempt")
    monkeypatch.setattr(runner, "_encode", lambda *_: pytest.fail("codec must not run"))
    with pytest.raises(runner.PipelineComparisonError, match="no automatic retry"):
        runner.qualify_pipeline_comparison(tmp_path)
    audit = json.loads((tmp_path / "qualification_interruption_audit.json").read_text())
    assert audit["status"] == "BLOCKED_UNCOMMITTED_QUALIFICATION"
    assert audit["artifacts"][0]["sha256"] == runner._sha(path)
    assert path.read_bytes() == b"earlier qualification attempt"


def test_qualification_uses_same_exclusive_run_lock(tmp_path, monkeypatch):
    _qualification_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "_encode", lambda *_: pytest.fail("codec must not run"))
    descriptor = os.open(tmp_path / ".pipeline.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(runner.PipelineComparisonError, match="lock is already held"):
            runner.qualify_pipeline_comparison(tmp_path)
    finally:
        os.close(descriptor)
