"""Bounded Simple evidence must reject forged success and stale shipped objects."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple_native import audit  # noqa: E402
from audit_fastpfor_simple_sdk import audit as audit_sdk  # noqa: E402
from audit_fastpfor_simple_upstream import audit as audit_upstream  # noqa: E402


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    for relative in (
        "adapters/fastpfor_simple",
        "native/include",
        "build/adapters/fastpfor_simple",
        "build/source-audits/fastpfor-simple",
        "build/source-audits/fastpfor-simple-initial",
        "build/source-audits/fastpfor-simple-lsan-initial",
        "build/source-audits/fastpfor-simple-native",
        "build/source-audits/fastpfor-simple-upstream",
        "build/source-audits/fastpfor_simple-sdk",
    ):
        shutil.copytree(
            ROOT / relative,
            tmp_path / relative,
            copy_function=lambda src, dst: os.symlink(src, dst),
        )
    for relative in (
        "tools/freeze_fastpfor_simple_source.py",
        "tools/qualify_fastpfor_simple_source.py",
        "tools/audit_fastpfor_simple_source.py",
        "tools/audit_fastpfor_simple_native.py",
        "tools/qualify_fastpfor_simple_upstream.py",
        "tools/audit_fastpfor_simple_upstream.py",
        "tools/qualify_fastpfor_simple_sdk.py",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(ROOT / relative)
    for path in (ROOT / "build/source-audits").glob("fastpfor_simple*.json"):
        (tmp_path / "build/source-audits" / path.name).write_bytes(path.read_bytes())
    snapshot = json.loads(
        (ROOT / "build/source-audits/fastpfor_simple_sdk_tests.json").read_text()
    )["source_snapshot"]
    for item in snapshot:
        target = tmp_path / item["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(ROOT / item["path"])
    return tmp_path


def replace(path: Path, content: bytes) -> None:
    path.unlink()
    path.write_bytes(content)


def test_current_bounded_evidence_preserves_pending_benchmark_scope(evidence: Path) -> None:
    result = audit(evidence)
    assert result["status"] == "PASS"
    assert result["native_cases"] == 91350
    assert result["native_fault_checks"] == 198
    assert result["source_probe_audit"]["original_unsafe_probe_count"] == 72
    assert result["python_sdk"] == result["benchmark_registration"] == "PENDING"
    assert result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entry_qualified"]


@pytest.mark.parametrize(
    "tamper",
    [
        "claim_sdk",
        "claim_full_entry",
        "missing_profile",
        "missing_fault",
        "missing_raw_command",
        "dependency_omitted",
        "different_shipped_object",
        "insufficient_cases",
        "fault_output_forged",
        "sanitizer_flags_removed",
    ],
)
def test_forged_native_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/fastpfor_simple_native_tests.json"
    doc = json.loads(path.read_text())
    if tamper == "claim_sdk":
        doc["python_sdk"] = "QUALIFIED"
    elif tamper == "claim_full_entry":
        doc["full_logical_entry_qualified"] = True
    elif tamper == "missing_profile":
        doc["builds"].pop()
    elif tamper == "missing_fault":
        doc["fault_tests"].pop()
    elif tamper == "missing_raw_command":
        doc["commands"].pop()
    elif tamper == "dependency_omitted":
        doc["tests"][0]["actual_compiler_closure"].pop()
    elif tamper == "different_shipped_object":
        doc["fault_tests"][0]["shipped_object"] = doc["builds"][1]["objects"][0]
    elif tamper == "insufficient_cases":
        doc["native_cases"] = 1
    elif tamper == "fault_output_forged":
        test = doc["fault_tests"][0]
        test["observation"]["checks"] = 1
        test["result"]["stdout"] = json.dumps(test["observation"])
        raw = next(c for c in doc["commands"] if c["command"] == test["result"]["command"])
        raw["stdout"] = test["result"]["stdout"]
    else:
        build = next(b for b in doc["builds"] if b["profile"] == "sanitizer")
        build["commands"][0]["command"].remove("-fsanitize=address,undefined")
        build_path = evidence / "build/adapters/fastpfor_simple/sanitizer/build-record.json"
        replace(build_path, (json.dumps(build) + "\n").encode())
    replace(path, (json.dumps(doc) + "\n").encode())
    with pytest.raises(RuntimeError):
        audit(evidence)


@pytest.mark.parametrize(
    "relative",
    [
        "adapters/fastpfor_simple/native/tscb_fastpfor_simple.cpp",
        "build/adapters/fastpfor_simple/release/shim.o",
        "build/adapters/fastpfor_simple/release/libtscb_fastpfor_simple.so",
    ],
)
def test_native_source_object_and_library_drift_is_rejected(evidence: Path, relative: str) -> None:
    path = evidence / relative
    replace(path, path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(RuntimeError, match="drift"):
        audit(evidence)


def test_full_original_upstream_and_current_sdk_scope(evidence: Path) -> None:
    upstream = audit_upstream(evidence)
    sdk = audit_sdk(evidence)
    assert upstream["status"] == sdk["status"] == "PASS"
    assert sdk["test_count"] == 322
    assert sdk["python_sdk"] == "QUALIFIED_SCOPED_UINT28_ONLY"
    assert sdk["benchmark_five_layers"] == "PENDING"


@pytest.mark.parametrize(
    "tamper", ["missing_object", "missing_command", "filtered_source", "truncated_stdout"]
)
def test_forged_entire_upstream_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/fastpfor_simple_upstream_tests.json"
    doc = json.loads(path.read_text())
    if tamper == "missing_object":
        doc["builds"].pop()
    elif tamper == "missing_command":
        doc["commands"].pop()
    elif tamper == "filtered_source":
        unit = evidence / "adapters/fastpfor_simple/third_party/fastpfor_upstream_unit/src/unit.cpp"
        replace(
            unit,
            unit.read_bytes().replace(
                b"factory.allSchemes()", b"std::vector<std::shared_ptr<IntegerCODEC>>()"
            ),
        )
    else:
        doc["result"]["stdout"] = doc["result"]["stdout"].replace(
            "length = 33554432", "length = 32"
        )
        doc["commands"][-1]["stdout"] = doc["result"]["stdout"]
    replace(path, (json.dumps(doc) + "\n").encode())
    with pytest.raises(RuntimeError):
        audit_upstream(evidence)


@pytest.mark.parametrize("tamper", ["benchmark_claim", "missing_command", "python_drift"])
def test_forged_sdk_success_is_rejected(evidence: Path, tamper: str) -> None:
    path = evidence / "build/source-audits/fastpfor_simple_sdk_tests.json"
    doc = json.loads(path.read_text())
    if tamper == "benchmark_claim":
        doc["benchmark_five_layers"] = "QUALIFIED"
    elif tamper == "missing_command":
        doc["commands"].pop()
    else:
        module = evidence / "src/tscompbench/adapters/fastpfor_simple.py"
        replace(module, module.read_bytes() + b"\nDRIFT\n")
    replace(path, (json.dumps(doc) + "\n").encode())
    with pytest.raises(RuntimeError):
        audit_sdk(evidence)
