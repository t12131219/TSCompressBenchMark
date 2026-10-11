from __future__ import annotations

import copy
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from tscompbench.accounting import AccountingLedger
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "qualify_v32_active_entries", ROOT / "tools/qualify_v32_active_entries.py"
)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


@pytest.fixture(scope="module")
def registry():
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def valid_preflight():
    return {
        "status": "PASS",
        "correctness": {"status": "PASS"},
        "boundary": {
            "passed": True,
            "observations": [{"status": "PASS", "reason": "ROUNDTRIP_EXACT"}],
        },
        "accounting": json.loads(
            canonical_json_bytes(
                AccountingLedger.create(
                    track=BenchmarkTrack.VALUE,
                    canonical_raw_bits=2048,
                    final_physical_bytes=64,
                    value_bits=512,
                    external_side_information_bits=512,
                    accounting_method="MOCK_STREAM+PERSISTED_DECODE_CONTEXT_V1",
                ).to_document()
            )
        ),
        "bitstream_sha256": "a" * 64,
        "diagnostics": {
            "independent_recovery": {
                "start_method": "spawn",
                "encoder_session_available": False,
                "original_input_available": False,
                "output_owned_in_worker": True,
                "stream_sha256": "a" * 64,
                "decode_context_sha256": "b" * 64,
                "required_external_bits": 512,
            },
            "independent_recovery_worker_lifecycle": {
                "worker_exit_confirmed": True,
                "exit_code": 0,
            },
        },
    }


def test_active_scope_does_not_infer_activity_from_builds(registry):
    keys = tool.active_keys(ROOT, registry)
    assert len(keys) == 33
    assert not set(keys) & {"bzip2-stream", "lzsse2-raw", "lzsse8-raw", "oracle-direct"}
    assert {"deepzip", "dzip", "abba", "fabba", "simdcomp-u32"} <= set(keys)


def test_every_active_declared_track_has_legal_frozen_fixture_config(registry):
    keys = tool.active_keys(ROOT, registry)
    cases = [case for key in keys for case in tool.select_cases(ROOT, registry, key, 0)]
    assert len(cases) == 41
    assert all("case_id" in case for case in cases)
    assert all(case["profile"]["measurement_mode"] == "QUALIFICATION" for case in cases)
    assert all(not case["profile"]["query_workload"] for case in cases)
    assert all(not case["profile"]["streaming_workload"] for case in cases)
    deepzip = next(case for case in cases if case["codec_key"] == "deepzip")
    assert deepzip["dataset_key"] == "rewrite_byte_uts"
    assert deepzip["parameters"]["model_key"] == "biGRU"
    neats = next(case for case in cases if case["codec_key"] == "neats-lossless-i64")
    assert neats["template_extension_profiles"]["query_workload"]


def test_frozen_case_identity_uses_serialized_alignment_guarantee(registry, monkeypatch):
    descriptor = tool.descriptor_from_dataset
    cases = []
    for alignment in (16, 32, 64):
        monkeypatch.setattr(
            tool,
            "descriptor_from_dataset",
            lambda dataset, track, alignment=alignment: replace(
                descriptor(dataset, track), alignment_bytes=alignment
            ),
        )
        cases.append(tool.select_cases(ROOT, registry, "lz4-frame", 0))
    assert cases[0] == cases[1] == cases[2]
    assert all(case["descriptor"]["alignment_bytes"] == 1 for case in cases[0])
    assert all(
        case["descriptor_alignment_basis"] == "SERIALIZED_CANONICAL_BYTE_ALIGNMENT_GUARANTEE"
        for case in cases[0]
    )


def test_four_group_denominator_and_fourteen_extension_roles_are_preserved(registry):
    rows = tool.role_ledger(ROOT, registry, tool.active_keys(ROOT, registry))
    core = [row for row in rows if row["in_four_initial_groups"]]
    extension = [row for row in rows if not row["in_four_initial_groups"]]
    assert len(core) == 19
    assert len(extension) == 14
    assert all(row["scope_status"] == "ACTIVE_REQUIRED_WHEN_APPLICABLE" for row in rows)
    roles = {row["codec_key"]: row["role"] for row in extension}
    assert roles["simdcomp-u32"] == "P0_UINT32_PRIMITIVE"
    assert roles["deepzip"] == "FROZEN_MODEL_ALPHABET_RESEARCH_ENTRY"
    assert roles["abba"] == "UNBOUNDED_QUALITY_RESEARCH_ENTRY"


def test_source_api_hashes_do_not_prove_complete_source_or_domain(tmp_path):
    path = tmp_path / "codec.c"
    path.write_bytes(b"original source")
    source = {
        "source_artifact_id": "source-id",
        "identity": {"api_files": [{"path": "codec.c", "sha256": tool.sha256(path)}]},
        "build": {},
    }
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["closure_status"] == "LOCKED_FILE_HASHES_VERIFIED_CLOSURE_UNKNOWN"
    assert evidence["file_hash_validation"] == "LOCKED_HASHES_VERIFIED"
    assert (
        evidence["actual_build_runtime_closure_validation"]
        == "UNKNOWN_NOT_CHECKED_BY_SOURCE_INVENTORY"
    )
    assert evidence["source_domain_validation"] == "UNKNOWN_NOT_INFERRED_FROM_HASHES"
    path.write_bytes(b"changed source")
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["closure_status"] == "DRIFT"
    assert evidence["files"][0]["status"] == "HASH_MISMATCH"


@pytest.mark.parametrize("locked_api", [False, True])
def test_observed_source_hashes_do_not_receive_verified_closure(tmp_path, locked_api):
    source_file = tmp_path / "codec.c"
    source_file.write_bytes(b"codec")
    api_file = tmp_path / "api.h"
    api_file.write_bytes(b"api")
    source = {
        "source_artifact_id": "source-id",
        "identity": {"api_files": [{"path": "api.h", "sha256": tool.sha256(api_file)}]}
        if locked_api
        else {},
        "build": {"source_closure": ["codec.c"]},
    }
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["closure_status"] == (
        "UNKNOWN_PARTIALLY_LOCKED_FILES" if locked_api else "UNKNOWN_OBSERVED_HASHES_ONLY"
    )
    assert evidence["file_hash_validation"] == (
        "PARTIALLY_LOCKED" if locked_api else "OBSERVED_ONLY"
    )


def test_verified_api_cannot_hide_unverified_vendor_tree(tmp_path):
    tree = tmp_path / "vendor"
    tree.mkdir()
    (tree / "codec.c").write_bytes(b"codec")
    (tmp_path / "api.h").write_bytes(b"api")
    source = {
        "source_artifact_id": "source-id",
        "identity": {
            "api_files": [{"path": "api.h", "sha256": tool.sha256(tmp_path / "api.h")}],
            "source_path": "vendor",
            "source_closure_sha256": "a" * 64,
        },
        "build": {},
    }
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["file_hash_validation"] == "LOCKED_HASHES_VERIFIED"
    assert evidence["closure_status"] == "UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT"
    assert evidence["observed_vendor_trees"][0]["state"].startswith("UNKNOWN")


def test_selected_closure_requires_declared_protocol_and_all_files(tmp_path):
    import hashlib

    (tmp_path / "codec.c").write_bytes(b"codec")
    (tmp_path / "api.h").write_bytes(b"api")
    paths = ["codec.c", "api.h"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.encode() + b"\0" + (tmp_path / path).read_bytes())
    source = {
        "source_artifact_id": "source-id",
        "identity": {
            "source_path": ".",
            "source_closure": [
                {"path": path, "sha256": tool.sha256(tmp_path / path)} for path in paths
            ],
            "source_closure_sha256": digest.hexdigest(),
            "source_closure_file_count": 2,
            "source_closure_digest_format": (
                "SORTED_REPOSITORY_RELATIVE_PATH_UTF8_NUL_THEN_FILE_BYTES"
            ),
        },
        "build": {},
    }
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["closure_status"] == "HASHES_VERIFIED_SELECTED_CLOSURE"
    # The selected repository-relative digest does not describe a tree-relative inventory.
    # A selected closure match does not certify the compiler/runtime closure either.
    assert evidence["selected_source_closure"]["state"] == "HASH_MATCH"
    assert evidence["actual_build_runtime_closure_validation"].startswith("UNKNOWN")
    source["identity"]["source_closure_file_count"] = 3
    assert tool.source_evidence(tmp_path, source)["closure_status"] == "DRIFT"
    source["identity"]["source_closure_file_count"] = 2
    (tmp_path / "api.h").unlink()
    assert tool.source_evidence(tmp_path, source)["closure_status"] == "DRIFT"


def test_patch_explanation_is_retained_but_real_missing_patch_fails(tmp_path):
    description = (
        "Explicit translation; the original source is reference provenance, not compiled input."
    )
    source = {
        "source_artifact_id": "source-id",
        "identity": {},
        "build": {"patches": [description]},
    }
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["files"] == []
    assert evidence["patch_annotations"] == [description]
    assert evidence["closure_status"] == "UNKNOWN_NO_FILE_CLOSURE"
    source["build"]["patches"].append("adapters/patches/missing.patch")
    evidence = tool.source_evidence(tmp_path, source)
    assert evidence["closure_status"] == "DRIFT"
    assert evidence["files"][0]["status"] == "MISSING"


def test_missing_declared_source_tree_is_a_missing_dependency(tmp_path):
    evidence = tool.source_evidence(
        tmp_path,
        {
            "source_artifact_id": "source-id",
            "identity": {"source_path": "missing-vendor"},
            "build": {},
        },
    )
    assert evidence["observed_vendor_trees"][0]["state"] == "MISSING"
    assert evidence["closure_status"] == "DRIFT"


def test_vendor_top_level_license_is_a_file_not_inferred_tree(tmp_path):
    license_path = tmp_path / "adapters/codec/vendor/LICENSE"
    license_path.parent.mkdir(parents=True)
    license_path.write_bytes(b"license")
    evidence = tool.source_evidence(
        tmp_path,
        {
            "source_artifact_id": "source-id",
            "identity": {},
            "build": {},
            "license": {"files": ["adapters/codec/vendor/LICENSE"]},
        },
    )
    assert evidence["observed_vendor_trees"] == []
    assert evidence["files"][0]["status"] == "HASH_OBSERVED"
    assert evidence["closure_status"] == "UNKNOWN_OBSERVED_HASHES_ONLY"


def test_resume_detects_added_file_in_observed_source_tree(tmp_path, monkeypatch):
    tree = tmp_path / "vendor"
    tree.mkdir()
    (tree / "codec.c").write_bytes(b"codec")
    monkeypatch.setattr(tool, "runtime_evidence", lambda root: [])
    source = tool.source_evidence(
        tmp_path,
        {
            "source_artifact_id": "source-id",
            "identity": {"source_path": "vendor"},
            "build": {},
        },
    )
    missing = tool.file_evidence(tmp_path, "missing.json")
    plan = {
        "runtime_files": [],
        "entries": [
            {
                "execution_files": [],
                "source": source,
                "cases": [],
                "standalone": {
                    "current_artifact": missing,
                    "build_record": missing,
                    "historical_audit": missing,
                    "historical_records": [],
                },
            }
        ],
    }
    plan["plan_id"] = stable_id("active-entry-qualification-plan-v32", plan)
    tool.validate_frozen(plan, tmp_path)
    (tree / "new_header.h").write_bytes(b"additional input")
    with pytest.raises(ValueError, match="source tree inventory drift"):
        tool.validate_frozen(plan, tmp_path)


@pytest.mark.parametrize("missing", ["accounting", "boundary", "correctness", "diagnostics"])
def test_preflight_pass_does_not_replace_missing_mandatory_proof(missing):
    document = valid_preflight()
    assert tool.preflight_acceptance(document)["status"] == "SCOPED_PASS"
    del document[missing]
    assert tool.preflight_acceptance(document)["status"] == "NOT_ACCEPTED"


@pytest.mark.parametrize("wrong", ["encoder_session_available", "original_input_available"])
def test_recovery_cannot_use_encoder_session_or_original_input(wrong):
    document = valid_preflight()
    document["diagnostics"]["independent_recovery"][wrong] = True
    assert tool.preflight_acceptance(document)["status"] == "NOT_ACCEPTED"


def test_recovery_hash_must_match_stream_and_ledger_must_cover_serialized_cost():
    document = valid_preflight()
    document["diagnostics"]["independent_recovery"]["stream_sha256"] = "b" * 64
    assert tool.preflight_acceptance(document)["status"] == "NOT_ACCEPTED"
    document = valid_preflight()
    document["accounting"]["final_bits"] = 128
    assert tool.preflight_acceptance(document)["status"] == "NOT_ACCEPTED"


def test_json_ledger_track_still_enforces_component_ownership():
    document = valid_preflight()
    document["accounting"]["track"] = "TIMESTAMP"
    assert tool.preflight_acceptance(document)["status"] == "NOT_ACCEPTED"


def test_resume_rejects_changed_case_evidence_and_recomputed_false_acceptance():
    result = {"plan_id": "plan", "preflight": valid_preflight()}
    result["acceptance"] = tool.preflight_acceptance(result["preflight"])
    result["evidence_id"] = stable_id("active-entry-qualification-evidence-v32", result)
    plan = {"plan_id": "plan", "entries": []}
    with pytest.raises(ValueError, match="unique frozen"):
        tool.validate_case_evidence(result, plan)
    changed = copy.deepcopy(result)
    changed["preflight"]["status"] = "TIMEOUT"
    with pytest.raises(ValueError, match="content/hash"):
        tool.validate_case_evidence(changed, plan)
    payload = {key: value for key, value in changed.items() if key != "evidence_id"}
    changed["evidence_id"] = stable_id("active-entry-qualification-evidence-v32", payload)
    with pytest.raises(ValueError, match="acceptance"):
        tool.validate_case_evidence(changed, plan)


def test_plan_identity_and_runtime_drift_are_separate_resume_failures(tmp_path, monkeypatch):
    path = tmp_path / "runtime.py"
    path.write_text("first")
    monkeypatch.setattr(
        tool, "runtime_evidence", lambda root: [tool.file_evidence(root, "runtime.py")]
    )
    plan = {"runtime_files": tool.runtime_evidence(tmp_path), "entries": []}
    plan["plan_id"] = stable_id("active-entry-qualification-plan-v32", plan)
    # JSON transport preserves the identity, including tuples and dataclasses.
    plan = json.loads(canonical_json_bytes(plan))
    tool.validate_frozen(plan, tmp_path)
    changed = {**plan, "entries": [{"injected": True}]}
    with pytest.raises(ValueError, match="identity mismatch"):
        tool.validate_frozen(changed, tmp_path)
    path.write_text("second")
    with pytest.raises(ValueError, match="runtime/registry drift"):
        tool.validate_frozen(plan, tmp_path)
