"""Release acceptance must recheck domains and proof, not saved PASS labels."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tscompbench.comparison import CorpusSpec
from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import audit_v32_completion as audit  # noqa: E402
import qualify_v32_active_entries as qualification  # noqa: E402

BUNDLES = {
    "byte": "g-byte-ll-v32-20261010-v3.json",
    "f64": "g-float-ll-f64-v32-20261010-v3.json",
    "i16": "g-int-ll-i16-v32-20261010-v3.json",
    "abs": "g-float-abs-v32-20261010-v3.json",
    "quality": "g-quality-v32-20261010-v5.json",
    "model": "g-byte-model-v32-20261010-v5.json",
    "cold": "g-byte-ll-cold-v32-20261010-v3.json",
    "api": "g-byte-ll-api-v32-20261010-v3.json",
    "entropy": "g-byte-entropy-ll-v32-20261010-v2.json",
    "u8": "g-uint8-ll-v32-20261010-v2.json",
}


def bundle(key):
    return json.loads((ROOT / "configs/comparisons" / BUNDLES[key]).read_text())


@pytest.mark.parametrize("key", list(BUNDLES))
def test_release_lane_accepts_corresponding_declared_domain(key):
    audit.validate_lane(key, bundle(key))


@pytest.mark.parametrize(
    "key", ["f64", "i16", "abs", "quality", "model", "cold", "api", "timestamp", "entropy", "u8"]
)
def test_release_cannot_repeat_byte_group_as_another_lane(key):
    with pytest.raises(ValueError):
        audit.validate_lane(key, bundle("byte"))


@pytest.mark.parametrize(
    "key,field,value",
    [
        ("cold", "profile", "STEADY_PROCESS"),
        ("api", "timing_scope", "PIPELINE"),
    ],
)
def test_release_cannot_rename_steady_or_pipeline_observations(key, field, value):
    altered = bundle(key)
    altered["protocol"][field] = value
    with pytest.raises(ValueError):
        audit.validate_lane(key, altered)


def test_release_validation_rejects_empty_logs_and_bare_pass_label():
    current = {"schema_version": "test", "sha256": "current"}
    document = {
        "status": "PASS",
        "full_suite_exit_code": 0,
        "control_plane": current,
        "artifacts": [],
    }
    with pytest.raises(ValueError):
        audit.validate_verification(document, current)


@pytest.mark.parametrize("weather_complete", [False, True])
def test_current_codec_coverage_counts_sources_and_formal_completion(weather_complete):
    corpus = CorpusSpec.from_document(bundle("byte")["corpus"])
    rows = [
        {
            "codec_key": "fse",
            "dataset_id": item["dataset_id"],
            "dataset_role": item["role"],
            "formal_complete": (
                True if item["source"]["independence_unit"] == "etth1" else weather_complete
            ),
        }
        for item in corpus.to_document()["datasets"]
    ]
    assert audit.fully_observed_codecs(corpus, {"matrix": rows}) == (
        {"fse"} if weather_complete else set()
    )


def test_sdk_reference_rejects_changed_report_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    path = tmp_path / "sdk.json"
    path.write_text('{"status":"FAIL"}')
    with pytest.raises(ValueError, match="SDK report reference drift"):
        audit.validate_sdk_reference(
            {"report": {"path": path.name, "sha256": "old"}, "independent_audit": {}}
        )


def test_sdk_reference_rechecks_audit_instead_of_saved_pass(tmp_path, monkeypatch):
    import audit_simdcomp_sdk

    monkeypatch.setattr(audit, "ROOT", tmp_path)
    path = tmp_path / "sdk.json"
    path.write_text('{"status":"PASS"}')
    monkeypatch.setattr(audit_simdcomp_sdk, "audit", lambda *_: {"status": "FAIL"})
    with pytest.raises(ValueError, match="SDK independent audit differs"):
        audit.validate_sdk_reference(
            {
                "report": {"path": path.name, "sha256": audit.sha(path)},
                "independent_audit": {"status": "PASS"},
            }
        )


def test_regression_proof_rejects_tests_modified_after_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    source = tests / "test_contract.py"
    source.write_text("def test_contract(): pass\n")
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
    log = tmp_path / "full-suite.log"
    log.write_text("2 passed in 1.00s\n")
    current = {"sha256": "frozen-source"}
    document = {
        "status": "PASS",
        "full_suite_exit_code": 0,
        "full_suite_command": ["python", "-m", "pytest", "-q", "--tb=short"],
        "control_plane": current,
        "tests_passed": 2,
        "artifacts": [{"role": "FULL_SUITE_LOG", "path": log.name, "sha256": audit.sha(log)}],
        "test_source_manifest": audit.test_source_manifest(tmp_path),
        "test_configuration": [audit.file_evidence(tmp_path / "pyproject.toml")],
        "input_snapshot_unchanged": True,
    }
    audit.validate_verification(document, current)
    source.write_text("def test_weakened_contract(): pass\n")
    with pytest.raises(ValueError, match="test definitions"):
        audit.validate_verification(document, current)


@pytest.mark.parametrize(
    "log,command,passed",
    [
        ("1 failed, 2 passed in 1.00s\n", ["python", "-m", "pytest", "-q", "--tb=short"], 2),
        (
            "2 passed in 1.00s\n",
            ["python", "-m", "pytest", "-q", "--tb=short", "tests/unit/test_one.py"],
            2,
        ),
        ("2 passed in 1.00s\n", ["python", "-m", "pytest", "-q", "--tb=short"], 2000),
    ],
)
def test_release_verification_rechecks_failed_filtered_or_inconsistent_logs(
    tmp_path, monkeypatch, log, command, passed
):
    monkeypatch.setattr(audit, "ROOT", tmp_path)
    path = tmp_path / "verification.log"
    path.write_text(log)
    current = {"sha256": "current"}
    document = {
        "status": "PASS",
        "full_suite_exit_code": 0,
        "control_plane": current,
        "tests_passed": passed,
        "full_suite_command": command,
        "artifacts": [{"role": "FULL_SUITE_LOG", "path": path.name, "sha256": audit.sha(path)}],
    }
    with pytest.raises(ValueError):
        audit.validate_verification(document, current)


def test_release_noop_resume_requires_unchanged_actual_bytes(tmp_path):
    raw = tmp_path / "trials.jsonl"
    raw.write_bytes(b"original\n")
    proof = {
        "status": "COMPLETE",
        "before_sha256": audit.sha(raw),
        "after_sha256": audit.sha(raw),
        "codec_execution_required": False,
        "performance_execution_required": False,
    }
    (tmp_path / "resume_verification.json").write_text(json.dumps(proof))
    audit.check_resume(tmp_path, raw, "COMPLETE")
    raw.write_bytes(b"modified\n")
    with pytest.raises(ValueError, match="resume proof"):
        audit.check_resume(tmp_path, raw, "COMPLETE")


def test_pipeline_resume_discloses_decoder_audit_without_performance_trials(tmp_path):
    raw = tmp_path / "trials.jsonl"
    raw.write_bytes(b"retained\n")
    proof = {
        "status": "COMPLETE",
        "before_sha256": audit.sha(raw),
        "after_sha256": audit.sha(raw),
        "codec_execution_required": True,
        "performance_execution_required": False,
        "codec_execution_scope": "READ_ONLY_INDEPENDENT_DECODER_AUDIT",
    }
    path = tmp_path / "resume_verification.json"
    path.write_text(json.dumps(proof))
    audit.check_resume(tmp_path, raw, "COMPLETE", decoder_audit=True)
    proof["codec_execution_scope"] = "FORMAL_MEASUREMENT"
    path.write_text(json.dumps(proof))
    with pytest.raises(ValueError, match="resume proof"):
        audit.check_resume(tmp_path, raw, "COMPLETE", decoder_audit=True)


@pytest.mark.parametrize("name", ["../outside", "history/run", "sub/history/run"])
def test_release_cannot_use_history_or_escape_paths(tmp_path, name):
    with pytest.raises(ValueError):
        audit._path(tmp_path, name)


def _fake_active(tmp_path, monkeypatch, *, write_cases):
    keys = json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
    plan = {
        "plan_id": "frozen-test-plan",
        "active_keys": keys,
        "selected_keys": keys,
        "entries": [
            {
                "codec_key": key,
                "cases": [{"case_id": stable_id("test-case", {"key": key}), "track": "VALUE"}],
            }
            for key in keys
        ],
    }
    monkeypatch.setattr(qualification, "validate_frozen", lambda plan, root: None)
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    summary = {
        "schema_version": "tscb.active-entry-qualification-summary.v3.2",
        "plan_id": plan["plan_id"],
        "status": "SCOPED_QUALIFICATION_COMPLETE",
        "entire_active_scope_selected": True,
        "active_entry_count": 33,
        "selected_entry_count": 33,
        "expected_track_cases": 33,
        "observed_track_cases": 33,
        "status_counts": {"SCOPED_PASS": 33},
        "performance_claim": False,
        "full_source_domain_claim": False,
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    (tmp_path / "four_matrices.json").write_text("{}")
    (tmp_path / "role_ledger.json").write_text("{}")
    if write_cases:
        (tmp_path / "cases").mkdir()
        for entry in plan["entries"]:
            case = entry["cases"][0]
            # Valid content digest cannot turn an empty/missing preflight into proof.
            result = {
                "plan_id": plan["plan_id"],
                "case_id": case["case_id"],
                "codec_key": entry["codec_key"],
                "acceptance": {"status": "SCOPED_PASS"},
                "preflight": None,
                "performance_eligible": False,
            }
            result["evidence_id"] = stable_id("active-entry-qualification-evidence-v32", result)
            (tmp_path / "cases" / (case["case_id"].rsplit(":", 1)[-1] + ".json")).write_text(
                json.dumps(result)
            )


def test_release_active_fake_complete_summary_cannot_replace_missing_cases(tmp_path, monkeypatch):
    _fake_active(tmp_path, monkeypatch, write_cases=False)
    with pytest.raises((ValueError, FileNotFoundError)):
        audit.validate_active(tmp_path)


def test_release_active_scoped_pass_without_raw_preflight_is_rejected(tmp_path, monkeypatch):
    _fake_active(tmp_path, monkeypatch, write_cases=True)
    with pytest.raises(ValueError):
        audit.validate_active(tmp_path)
