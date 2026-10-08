"""Reject forged kernel qualification while preserving original source failures."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_littleintpacker_source import audit  # noqa: E402


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    for relative in (
        "adapters/littleintpacker",
        "build/source-audits/littleintpacker-source",
        "build/source-audits/littleintpacker-patched",
        "build/source-audits/littleintpacker-initial-zero-width-failure",
    ):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    for name in (
        "freeze_littleintpacker_source.py",
        "prepare_littleintpacker_patch.py",
        "qualify_littleintpacker_source.py",
        "qualify_littleintpacker_patched.py",
    ):
        target = tmp_path / "tools" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(ROOT / "tools" / name)
    for kind in ("source", "patched"):
        name = f"build/source-audits/littleintpacker_{kind}_tests.json"
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


def replace(path: Path, data: bytes) -> None:
    path.unlink()
    path.write_bytes(data)


def write_report(root: Path, kind: str, doc: dict) -> None:
    path = root / f"build/source-audits/littleintpacker_{kind}_tests.json"
    replace(path, (json.dumps(doc) + "\n").encode())
    if kind == "source":
        patched = root / "build/source-audits/littleintpacker_patched_tests.json"
        contents = json.loads(patched.read_text())
        # Forge the dependent hash too, so rejection tests the underlying evidence.
        contents["original_report"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        replace(patched, (json.dumps(contents) + "\n").encode())


def change_observation(doc: dict, result: dict, **changes: object) -> None:
    raw = next(record for record in doc["commands"] if record["command"] == result["command"])
    raw.update(changes)
    result.update(changes)


def test_current_kernel_evidence_retains_failures_and_pending_abi(evidence: Path) -> None:
    result = audit(evidence)
    assert result["status"] == "PASS"
    assert result["patched_api_matrix_cases"] == 56925
    assert result["original_unsafe_probe_count"] == 78
    assert result["original_sanitizer_unit_and_matrix"] == "FAILURES_RETAINED"
    assert (
        result["bounded_abi"]
        == result["python_sdk"]
        == result["benchmark_five_layers"]
        == "PENDING"
    )
    assert not result["full_logical_entries_qualified"]


@pytest.mark.parametrize(
    "tamper",
    [
        "missing_profile",
        "missing_object",
        "missing_command",
        "missing_dependency",
        "filtered_unit",
        "truncated_matrix",
        "changed_isa",
        "removed_sanitizer",
        "claim_full",
        "claim_abi",
        "claim_lsan",
        "hide_padding",
        "wrong_cases",
        "missing_alignment_probe",
        "raw_ledger_mismatch",
    ],
)
def test_forged_patched_success_is_rejected(evidence: Path, tamper: str) -> None:
    doc = json.loads(
        (evidence / "build/source-audits/littleintpacker_patched_tests.json").read_text()
    )
    release = doc["profiles"]["release"]
    if tamper == "missing_profile":
        del doc["profiles"]["sanitizer"]
    elif tamper == "missing_object":
        release["builds"].pop()
    elif tamper == "missing_command":
        doc["commands"].pop()
    elif tamper == "missing_dependency":
        release["builds"][0]["compiler_closure"].pop()
    elif tamper == "filtered_unit":
        doc["upstream_unit_filtered"] = True
    elif tamper == "truncated_matrix":
        result = release["executions"]["api-probe"]["result"]
        change_observation(doc, result, stdout="MATRIX_DONE cases=18975 failures=0\n")
    elif tamper in {"changed_isa", "removed_sanitizer"}:
        build = (
            release["builds"][3]
            if tamper == "changed_isa"
            else doc["profiles"]["sanitizer"]["builds"][0]
        )
        raw = next(r for r in doc["commands"] if r["command"] == build["command"])
        flag = "-mavx2" if tamper == "changed_isa" else "-fsanitize=address,undefined"
        build["command"].remove(flag)
        raw["command"].remove(flag)
    elif tamper == "claim_full":
        doc["full_logical_entries_qualified"] = True
    elif tamper == "claim_abi":
        doc["bounded_abi"] = "QUALIFIED"
    elif tamper == "claim_lsan":
        doc["leak_sanitizer"] = "PASS"
    elif tamper == "hide_padding":
        doc["source_padding_required"] = False
    elif tamper == "wrong_cases":
        doc["api_matrix_cases"] = 1
    elif tamper == "missing_alignment_probe":
        release["alignment_probes"].pop()
    else:
        release["executions"]["unit"]["result"]["returncode"] = 1
    write_report(evidence, "patched", doc)
    with pytest.raises(RuntimeError):
        audit(evidence)


@pytest.mark.parametrize(
    "tamper",
    [
        "zero_width_failures_hidden",
        "sanitizer_failure_hidden",
        "unsafe_probe_relabeled",
        "missing_raw_probe",
        "missing_original_command",
    ],
)
def test_original_failures_cannot_be_erased(evidence: Path, tamper: str) -> None:
    doc = json.loads(
        (evidence / "build/source-audits/littleintpacker_source_tests.json").read_text()
    )
    release = doc["profiles"]["release"]
    if tamper == "zero_width_failures_hidden":
        result = release["executions"]["api-probe"]["result"]
        change_observation(doc, result, stderr="", returncode=0)
    elif tamper == "sanitizer_failure_hidden":
        result = doc["profiles"]["sanitizer"]["executions"]["unit"]["result"]
        change_observation(doc, result, stderr="")
    elif tamper == "unsafe_probe_relabeled":
        probe = release["raw_probes"][0]
        probe["status"] = "RAW_CALL_RETURNED"
        change_observation(doc, probe["result"], returncode=0)
    elif tamper == "missing_raw_probe":
        release["raw_probes"].pop()
    else:
        doc["commands"].pop()
    write_report(evidence, "source", doc)
    with pytest.raises(RuntimeError):
        audit(evidence)


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/littleintpacker/vendor/littleintpacker/tests/unit.c",
        "adapters/littleintpacker/tests/source_api_probe.c",
        "adapters/littleintpacker/patches/0001-zero-width-and-word-access.patch",
        "build/source-audits/littleintpacker-patched/generated/src/scpacking32.c",
        "build/source-audits/littleintpacker-patched/release/bitpacking32.c.o",
        "build/source-audits/littleintpacker-patched/sanitizer/api-probe",
        "build/source-audits/littleintpacker-initial-zero-width-failure/source_api_probe.c",
    ],
)
def test_consumed_source_object_binary_and_history_drift_is_rejected(
    evidence: Path,
    relative: str,
) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift"):
        audit(evidence)


def test_rehashed_generated_kernel_must_still_match_applied_patch(evidence: Path) -> None:
    relative = "build/source-audits/littleintpacker-patched/generated/src/scpacking32.c"
    path = evidence / relative
    replace(path, path.read_bytes() + b"\n/* UNRECORDED_KERNEL_CHANGE */\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    report_path = evidence / "build/source-audits/littleintpacker_patched_tests.json"
    doc = json.loads(report_path.read_text())
    for item in doc["generated_source_files"]:
        if item["path"] == relative:
            item["sha256"] = digest
    lock_path = evidence / "adapters/littleintpacker/PATCH_LOCK.json"
    lock = json.loads(lock_path.read_text())
    next(item for item in lock["changes"] if item["upstream_path"] == "src/scpacking32.c")[
        "patched_sha256"
    ] = digest
    replace(lock_path, (json.dumps(lock) + "\n").encode())
    doc["patch_lock"]["sha256"] = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    write_report(evidence, "patched", doc)
    with pytest.raises(RuntimeError, match="differs from actual patch"):
        audit(evidence)


def test_sanitizer_executable_cannot_be_replaced_with_rehashed_release(evidence: Path) -> None:
    relative = "build/source-audits/littleintpacker-patched/sanitizer/api-probe"
    path = evidence / relative
    replace(
        path,
        (evidence / "build/source-audits/littleintpacker-patched/release/api-probe").read_bytes(),
    )
    doc = json.loads(
        (evidence / "build/source-audits/littleintpacker_patched_tests.json").read_text()
    )
    doc["profiles"]["sanitizer"]["executions"]["api-probe"]["artifact"]["sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    write_report(evidence, "patched", doc)
    with pytest.raises(RuntimeError, match="lacks ASan/UBSan"):
        audit(evidence)
