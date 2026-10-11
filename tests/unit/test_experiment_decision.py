"""Pure decision contracts: freeze before work and fail closed on drift."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tscompbench.comparison.decision import (
    comparison_decision,
    freeze_experiment_decision,
    pipeline_decision,
    validate_experiment_decision,
)
from tscompbench.comparison.workload_runner import WorkloadProtocol

ROOT = Path(__file__).resolve().parents[2]


def _bundle(name="g-byte-ll-v32-20261010-v3"):
    return json.loads((ROOT / "configs/comparisons" / (name + ".json")).read_text())


def _decision(bundle=None, workload=None, **kwargs):
    return comparison_decision(
        bundle or _bundle(),
        environment_id=kwargs.get("environment_id", "frozen-machine"),
        control_plane_sha256=kwargs.get("source", "frozen-src"),
        workload_protocol=workload,
    )


def _plan(document):
    return {"decision": document, "decision_id": document["decision_id"]}


def test_fixed_corpus_intent_is_predeclared_and_owns_its_inputs(tmp_path):
    bundle = _bundle()
    document = _decision(bundle)
    freeze_experiment_decision(tmp_path, document)
    before = (tmp_path / "experiment_decision.json").read_bytes()
    validate_experiment_decision(tmp_path, _plan(document), _decision(bundle))
    freeze_experiment_decision(tmp_path, document, resume=True)
    assert (tmp_path / "experiment_decision.json").read_bytes() == before
    assert document["target_population"]["kind"] == "FIXED_CORPUS"
    assert len(document["target_population"]["independent_real_source_groups"]) == 2
    assert "BEFORE_QUALIFICATION" in document["declaration_stage"]
    bundle["corpus"]["datasets"][0]["domain_evidence"].append("later mutation")
    assert "later mutation" not in str(document)


@pytest.mark.parametrize("key", ["decision", "decision_id"])
def test_plan_must_bind_sidecar_identity(tmp_path, key):
    document = _decision()
    freeze_experiment_decision(tmp_path, document)
    plan = _plan(document)
    plan.pop(key)
    with pytest.raises(ValueError, match="sidecar/plan"):
        validate_experiment_decision(tmp_path, plan, document)


@pytest.mark.parametrize("kind", ["source", "environment", "corpus", "question", "config"])
def test_frozen_input_drift_changes_intent_and_is_rejected(tmp_path, kind):
    bundle = _bundle()
    document = _decision(bundle)
    freeze_experiment_decision(tmp_path, document)
    kwargs = {}
    if kind == "source":
        kwargs["source"] = "changed-src"
    elif kind == "environment":
        kwargs["environment_id"] = "changed-machine"
    elif kind == "corpus":
        bundle["corpus"]["datasets"][0]["artifact_sha256"] = "a" * 64
    elif kind == "question":
        bundle["contract"]["research_question"] += " changed question"
    else:
        bundle["config_map"]["members"][0]["configs"][0]["parameters"]["new"] = 1
    changed = _decision(bundle, **kwargs)
    assert changed["decision_id"] != document["decision_id"]
    before = (tmp_path / "experiment_decision.json").read_bytes()
    with pytest.raises(ValueError, match="sidecar/plan"):
        validate_experiment_decision(tmp_path, _plan(changed), changed)
    with pytest.raises(ValueError, match="frozen experiment decision differs"):
        freeze_experiment_decision(tmp_path, changed, resume=True)
    assert (tmp_path / "experiment_decision.json").read_bytes() == before


def test_missing_sidecar_cannot_be_added_at_resume_or_report(tmp_path):
    document = _decision()
    with pytest.raises(ValueError, match="original pre-measurement"):
        freeze_experiment_decision(tmp_path, document, resume=True)
    with pytest.raises(ValueError, match="missing pre-measurement"):
        validate_experiment_decision(tmp_path, _plan(document), document)
    assert not (tmp_path / "experiment_decision.json").exists()


@pytest.mark.parametrize(
    "file",
    [
        "qualification.json",
        "qualification_intent.json",
        "qualification_failure.json",
        "qualification_interruption_audit.json",
        "pilot.json",
        "comparison_trials.jsonl",
        "workload_pilot.json",
        "workload_trials.jsonl",
        "pipeline_events.jsonl",
        "trials.jsonl",
        "events.jsonl",
        "workload_events.jsonl",
    ],
)
def test_decision_cannot_be_backfilled_after_measurement_started(tmp_path, file):
    (tmp_path / file).write_text("already measured")
    with pytest.raises(ValueError, match="after measurement started"):
        freeze_experiment_decision(tmp_path, _decision())


def test_tampered_question_or_unknown_fields_are_rejected(tmp_path):
    document = _decision()
    freeze_experiment_decision(tmp_path, document)
    for field in ("research_question", "unknown"):
        altered = copy.deepcopy(document)
        altered[field] = "post hoc winner"
        (tmp_path / "experiment_decision.json").write_text(json.dumps(altered))
        with pytest.raises(ValueError, match="identity drift|unknown/missing"):
            validate_experiment_decision(tmp_path, _plan(document), document)


@pytest.mark.parametrize(
    "name, required",
    [
        ("g-byte-model-v32-20261010-v5", "MODEL_TRAINING_TEST_OVERLAP_UNKNOWN"),
        ("g-quality-v32-20261010-v5", "EMPIRICAL_QUALITY_GRID"),
        ("g-byte-ll-api-v32-20261010-v3", "NATIVE_COMPONENT_COST"),
    ],
)
def test_distinct_decisions_preserve_actual_scope(name, required):
    document = _decision(_bundle(name))
    assert required in " ".join(document["conclusion_scope"])


def test_fixed_error_and_cold_context_have_specific_estimands():
    fixed = _decision(_bundle("g-float-abs-v32-20261010-v3"))
    assert "fixed error" in fixed["decision_context"]
    assert fixed["primary_estimands"]["quality"]["threshold"] is not None
    cold = _decision(_bundle("g-byte-ll-cold-v32-20261010-v3"))
    assert cold["primary_estimands"]["time"] == "SPAWN_THROUGH_OUTPUT_MATERIALIZATION_WALL_NS"


def test_stream_query_and_cache_policy_are_frozen_before_any_results():
    stream = _decision(workload=WorkloadProtocol("STREAM").to_document())
    query = _decision(workload=WorkloadProtocol("QUERY").to_document())
    fresh = _decision(
        workload=WorkloadProtocol(
            "QUERY", query_cache_policy="FRESH_SESSION_PER_QUERY"
        ).to_document()
    )
    assert len({d["decision_id"] for d in (stream, query, fresh)}) == 3
    assert "finalized full output" in stream["decision_context"]
    assert "point/range/column" in query["decision_context"]
    assert (
        fresh["boundaries"]["workload_protocol"]["query_cache_policy"] == "FRESH_SESSION_PER_QUERY"
    )
    assert "LOGICAL_BYTES_TOUCHED" in " ".join(query["conclusion_scope"])


def test_pipeline_decision_binds_object_null_semantics_and_implementation(tmp_path):
    arguments = {
        "datasets": [
            {
                "dataset_key": "a",
                "test": {
                    "logical_content_id": "original",
                    "schema": {"null_semantics": "SEMANTIC", "value_order": ["a", "b"]},
                },
            }
        ],
        "protocol": {"profile": "STEADY_PROCESS"},
        "analysis_policy": {"fixed": True},
        "resources": {"threads": 1},
        "closure": {"children": {"lz4": "frozen-build"}},
        "boundary": "PIPELINE",
        "scope": "COMPLETE_OBJECT",
    }
    document = pipeline_decision(**arguments)
    assert document["boundaries"]["object_schemas"][0]["null_semantics"] == "SEMANTIC"
    freeze_experiment_decision(tmp_path, document)
    validate_experiment_decision(tmp_path, _plan(document), pipeline_decision(**arguments))
    arguments["closure"]["children"]["lz4"] = "changed-build"
    with pytest.raises(ValueError, match="sidecar/plan"):
        validate_experiment_decision(tmp_path, _plan(document), pipeline_decision(**arguments))


@pytest.mark.parametrize("stage", ["qualify_comparison", "pilot_comparison", "execute_comparison"])
def test_ordinary_stages_validate_intent_before_any_worker(stage, monkeypatch):
    from tscompbench.comparison import runner

    called = []

    def reject(*args):
        called.append(True)
        raise ValueError("missing predeclared decision")

    monkeypatch.setattr(runner, "validate_frozen_comparison", reject)
    fake = SimpleNamespace(path=Path("unused"), bundle={}, plan={})
    with pytest.raises(ValueError, match="predeclared decision"):
        getattr(runner, stage)(fake, {})
    assert called == [True]
