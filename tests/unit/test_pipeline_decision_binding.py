"""P2 decision binding uses mock inputs/source closure and invokes no codecs."""

from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from tscompbench.comparison import pipeline_runner as runner
from tscompbench.comparison.analysis import AnalysisPolicy
from tscompbench.measurement.v32_protocol import MeasurementProtocol


def _arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner,
        "_child_closure",
        lambda *_: {"children": {"lz4-frame": {}, "zstd-frame": {}}, "mock_source": True},
    )
    monkeypatch.setattr(
        runner,
        "load_pipeline_input",
        lambda document: SimpleNamespace(
            content_id=document["logical_content_id"],
            values={"x": object()},
            timestamp=None,
            validity=None,
            canonical_raw_bits=document["canonical_raw_bits"],
        ),
    )
    return {
        "project_root": tmp_path,
        "run_path": tmp_path,
        "datasets": [
            {
                "dataset_key": "mock_fixed_corpus",
                "test": {
                    "logical_content_id": "mock_test_object",
                    "canonical_raw_bits": 64,
                    "schema": {"mock_schema": True},
                },
                "development": {
                    "logical_content_id": "mock_dev_object",
                    "canonical_raw_bits": 64,
                    "schema": {"mock_schema": True},
                },
            }
        ],
        "protocol": MeasurementProtocol(
            profile="STEADY_PROCESS",
            outer_repetitions=2,
            encode_min_ns=1_000_000,
            decode_min_ns=1_000_000,
            max_trial_wall_ns=100_000_000,
            max_total_wall_ns=500_000_000,
            thread_monitor_interval_ns=1_000_000,
        ),
        "policy": AnalysisPolicy(),
        "resources": {"logical_cpus": [0], "threads": 1, "memory_limit_bytes": 1_073_741_824},
    }


def test_predeclared_pipeline_decision_is_frozen_before_plan_or_measurement(tmp_path, monkeypatch):
    arguments = _arguments(tmp_path, monkeypatch)
    freeze = runner.freeze_experiment_decision
    calls = []

    def observe_freeze(path, document, *, resume):
        assert not (path / "plan.json").exists()
        assert not (path / "qualification_intent.json").exists()
        assert not (path / "pipeline_events.jsonl").exists()
        calls.append(resume)
        freeze(path, document, resume=resume)

    monkeypatch.setattr(runner, "freeze_experiment_decision", observe_freeze)
    plan = runner.prepare_pipeline_comparison(**arguments)
    decision = json.loads((tmp_path / "experiment_decision.json").read_text())
    assert calls == [False]
    assert plan["decision"] == decision and plan["decision_id"] == decision["decision_id"]
    assert decision["target_population"]["datasets"] == arguments["datasets"]
    assert decision["boundaries"]["resources"] == arguments["resources"]
    assert decision["primary_estimands"]["storage"] == (
        "FINALIZED_COMPLETE_OBJECT_BITS_INCLUDING_T_AND_VALIDITY"
    )
    runner.validate_pipeline_plan(plan, tmp_path)


@pytest.mark.parametrize("mutation", ["missing", "sidecar", "plan_body", "plan_id"])
def test_decision_drift_and_missing_original_are_rejected(tmp_path, monkeypatch, mutation):
    plan = runner.prepare_pipeline_comparison(**_arguments(tmp_path, monkeypatch))
    path = tmp_path / "experiment_decision.json"
    if mutation == "missing":
        path.unlink()
    elif mutation == "sidecar":
        document = json.loads(path.read_text())
        document["decision_context"] = "changed after results"
        path.write_text(json.dumps(document))
    elif mutation == "plan_body":
        plan = copy.deepcopy(plan)
        plan["decision"]["decision_context"] = "changed after results"
    else:
        plan = copy.deepcopy(plan)
        plan["decision_id"] = "different-decision"
    monkeypatch.setattr(
        runner, "run_isolated", lambda *_a, **_k: pytest.fail("worker must not run")
    )
    with pytest.raises(runner.PipelineComparisonError, match="decision|identity drift"):
        runner.validate_pipeline_plan(plan, tmp_path)


def test_resume_missing_decision_is_rejected_before_loading_any_child(tmp_path, monkeypatch):
    arguments = _arguments(tmp_path, monkeypatch)
    runner.prepare_pipeline_comparison(**arguments)
    (tmp_path / "experiment_decision.json").unlink()
    monkeypatch.setattr(
        runner, "_child_closure", lambda *_: pytest.fail("child must not be loaded")
    )
    with pytest.raises(runner.PipelineComparisonError, match="pre-measurement"):
        runner.prepare_pipeline_comparison(**arguments)
    assert not (tmp_path / "experiment_decision.json").exists()


def test_decision_cannot_be_backfilled_after_raw_observation(tmp_path, monkeypatch):
    arguments = _arguments(tmp_path, monkeypatch)
    raw = b"retained prior observation\n"
    (tmp_path / "trials.jsonl").write_bytes(raw)
    with pytest.raises(runner.PipelineComparisonError, match="cannot backfill"):
        runner.prepare_pipeline_comparison(**arguments)
    assert not (tmp_path / "plan.json").exists()
    assert not (tmp_path / "experiment_decision.json").exists()
    assert (tmp_path / "trials.jsonl").read_bytes() == raw


def test_saved_decision_is_reused_without_rewriting(tmp_path, monkeypatch):
    arguments = _arguments(tmp_path, monkeypatch)
    plan = runner.prepare_pipeline_comparison(**arguments)
    path = tmp_path / "experiment_decision.json"
    saved = path.read_bytes()
    assert runner.prepare_pipeline_comparison(**arguments) == plan
    assert path.read_bytes() == saved
