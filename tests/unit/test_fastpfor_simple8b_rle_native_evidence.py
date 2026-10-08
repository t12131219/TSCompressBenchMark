"""Do not qualify RLE when actual safety/fault execution or shipped identity is missing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple8b_rle_native import (  # noqa: E402
    FAULT_REPORT, SAFETY_REPORT, audit, audit_suite,
)
from build_native_integration_plan import simple8b_rle_admission_review  # noqa: E402


def test_actual_rle_native_scope_keeps_sdk_and_full_entry_pending() -> None:
    result = audit()
    assert result["status"] == "PASS"
    assert result["bounded_abi"] == "QUALIFIED_SCOPED_UINT32_ONLY"
    assert result["same_object_fault_checks"] == 102
    assert result["malformed_truncation_cases"] == 106359
    assert result["guard_page_cases"] == 7128
    assert result["python_sdk"] == result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entry_qualified"]


def test_worklist_promotes_only_actual_executed_scopes() -> None:
    state, review = simple8b_rle_admission_review("2457e1ed1af35bbf7f4c509c863fa9797e637cb3")
    assert state == "P0_FASTPFOR_SIMPLE8B_RLE_UINT32_SYNTHETIC_UTS_SCOPE_QUALIFIED_OTHER_DATASETS_DOMAINS_PENDING"
    assert review["native_abi_audit"]["status"] == "PASS"
    assert review["bounded_abi"] == "QUALIFIED_SCOPED_UINT32_ONLY"
    assert review["python_sdk"] == "QUALIFIED_SCOPED_UINT32_MARKED_UNMARKED_ONLY"
    assert review["benchmark_five_layers"] == "SYNTHETIC_UINT32_VALUE_UTS_SCOPE_QUALIFIED"
    assert review["formal_repetition_review"]["records"] == 80
    assert review["formal_repetition_review"]["eligible"] == 74
    assert not review["full_logical_entry_qualified"]


def test_failed_native_audit_preserves_source_but_does_not_promote(monkeypatch: pytest.MonkeyPatch) -> None:
    import audit_fastpfor_simple8b_rle_native as native

    def failed() -> dict:
        raise ValueError("injected current native evidence drift")

    monkeypatch.setattr(native, "audit", failed)
    state, review = simple8b_rle_admission_review("2457e1ed1af35bbf7f4c509c863fa9797e637cb3")
    assert state == "PATCHED_RLE_VALID_UINT32_SOURCE_SCOPE_QUALIFIED_BOUNDED_ABI_AND_FIVE_LAYERS_PENDING"
    assert review["source_api_audit"]["status"] == "PASS"
    assert review["bounded_abi"] == "PENDING"
    assert review["current_native_qualification_failure"]["reason"]
    assert not review["full_logical_entry_qualified"]


@pytest.mark.parametrize("tamper", [
    "scope", "sdk", "leaks", "missing_profile", "missing_raw_command",
    "missing_compiler_dependency", "missing_runtime_dependency", "wrong_shipped_object",
    "wrong_observation", "forged_execution_hash", "wrong_driver_snapshot",
])
def test_fault_evidence_rejects_forgery(tmp_path: Path, tamper: str) -> None:
    report = json.loads(FAULT_REPORT.read_text())
    if tamper == "scope":
        report["full_logical_entry_qualified"] = True
    elif tamper == "sdk":
        report["python_sdk"] = "QUALIFIED"
    elif tamper == "leaks":
        report["leak_sanitizer"] = "PASS"
    elif tamper == "missing_profile":
        report["tests"].pop()
    elif tamper == "missing_raw_command":
        report["commands"].pop()
    elif tamper == "missing_compiler_dependency":
        report["tests"][0]["compiler_closure"].pop()
    elif tamper == "missing_runtime_dependency":
        report["tests"][0]["runtime_closure"].pop()
    elif tamper == "wrong_shipped_object":
        report["tests"][0]["shipped_object"] = report["tests"][2]["shipped_object"]
    elif tamper == "wrong_observation":
        report["tests"][0]["observation"]["checks"] = 1
    elif tamper == "forged_execution_hash":
        report["tests"][0]["execution"]["sha256"] = "0" * 64
    else:
        report["driver_snapshot"] = report["tests"][0]["source_snapshot"]
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        audit_suite(path, "faults")


@pytest.mark.parametrize("tamper", ["malformed_count", "guard_count", "wrong_library", "wrong_suite"])
def test_safety_evidence_rejects_incomplete_scope(tmp_path: Path, tamper: str) -> None:
    report = json.loads(SAFETY_REPORT.read_text())
    if tamper == "malformed_count":
        report["tests"][0]["observation"]["malformed_cases"] -= 1
    elif tamper == "guard_count":
        report["tests"][0]["observation"]["guard_cases"] -= 1
    elif tamper == "wrong_library":
        report["tests"][0]["shipped_library"] = report["tests"][1]["shipped_library"]
    else:
        report["suite"] = "faults"
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        audit_suite(path, "safety")
