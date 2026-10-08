"""RLE source evidence must not accept stale, incomplete or expanded qualification claims."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple8b_rle_source import DEFAULT_REPORT, audit  # noqa: E402
from build_native_integration_plan import (  # noqa: E402
    refresh_simple8b_rle_entry,
    simple8b_rle_admission_review,
)


def test_actual_rle_source_audit_retains_full_scope_boundaries() -> None:
    result = audit()
    assert result["status"] == "PASS"
    assert result["patched_roundtrip_cases"] == 211464
    assert result["patched_guard_roundtrips"] == 4788
    assert result["original_and_patched_complete_factory_rle_zipf_cases"] == 10
    assert (
        result["bounded_abi"]
        == result["python_sdk"]
        == result["benchmark_five_layers"]
        == "PENDING"
    )
    assert not result["full_logical_entry_qualified"]


@pytest.mark.parametrize("mutation", [
    "scope", "abi", "leaks", "missing_profile", "guard_count", "compile_flags",
    "fake_native_qualification", "missing_upstream_object", "upstream_rle_missing",
])
def test_rle_source_audit_rejects_bad_evidence(tmp_path: Path, mutation: str) -> None:
    document = json.loads(DEFAULT_REPORT.read_text())
    if mutation == "scope":
        document["full_logical_entry_qualified"] = True
    elif mutation == "abi":
        document["bounded_abi"] = "QUALIFIED"
    elif mutation == "leaks":
        document["leak_sanitizer"] = "PASS"
    elif mutation == "missing_profile":
        document["matrices"].pop()
    elif mutation == "guard_count":
        document["matrices"][-1]["observation"]["guard_roundtrips"] -= 1
    elif mutation == "compile_flags":
        document["builds"][-1]["command"].remove("-fsanitize=address,undefined")
    elif mutation == "fake_native_qualification":
        document["source_capacity_and_malformed_frames"] = "QUALIFIED"
    elif mutation == "missing_upstream_object":
        document["reused_upstream_objects"].pop()
    else:
        original = document["patched_full_result"]["stdout"]
        document["patched_full_result"]["stdout"] = original.replace(
            "Simple8b_RLE encoding ... decoding ... ok!", "OMITTED"
        )
    report = tmp_path / "report.json"
    report.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        audit(report)


def test_rle_source_worklist_refresh_preserves_all_other_rows() -> None:
    document = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    before = copy.deepcopy(document)
    refresh_simple8b_rle_entry(document)
    assert len(document["entries"]) == 221
    assert document["scope_counts"] == before["scope_counts"]
    assert document["scope_counts"]["NATIVE_CORE_CANDIDATE"] == 115
    for old, new in zip(before["entries"], document["entries"], strict=True):
        if new["audit_index"] != 148:
            assert new == old
        else:
            assert new["source_admission_review"]["source_api_audit"]["status"] == "PASS"
            assert not new["full_logical_entry_qualified"]
            assert len(new["current_scope_reviews"]) == 1
            assert new["current_scope_reviews"][0]["eligible_repetitions"] == 74
            assert [c["key"] for c in new["registered_candidates"]] == ["fastpfor-simple8b-rle-u32"]


def test_rle_source_worklist_commit_drift_does_not_qualify() -> None:
    state, review = simple8b_rle_admission_review("0" * 40)
    assert state == "FROZEN_RLE_SOURCE_CURRENT_REQUALIFICATION_REQUIRED"
    assert review["current_qualification_failure"]["reason"]
    assert review["bounded_abi"] == review["benchmark_five_layers"] == "PENDING"
    assert not review["full_logical_entry_qualified"]
