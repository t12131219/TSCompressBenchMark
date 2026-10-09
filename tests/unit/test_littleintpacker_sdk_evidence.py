"""SDK evidence must bind actual native qualification, imported code and all test cases."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from test_littleintpacker_native_evidence import evidence as native_evidence  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_littleintpacker_sdk import audit, sdk_report_path  # noqa: E402

SDK_DIRECTORY = str(sdk_report_path(ROOT).parent.relative_to(ROOT))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


@pytest.fixture
def sdk_evidence(native_evidence: Path) -> Path:  # noqa: F811 - imported pytest fixture
    report = json.loads(sdk_report_path(ROOT).read_text())
    paths = {item["path"] for item in report["source_snapshot"]}
    paths.add("tools/audit_littleintpacker_native.py")
    for name in paths:
        path = native_evidence / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.symlink_to(ROOT / name)
    shutil.copytree(
        ROOT / SDK_DIRECTORY,
        native_evidence / SDK_DIRECTORY,
    )
    write(native_evidence / SDK_DIRECTORY / "report.json", report)
    card = native_evidence / "registry/onboarding/littleintpacker-pack32-u32.json"
    card.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "registry/onboarding/littleintpacker-pack32-u32.json", card)
    return native_evidence


def test_complete_sdk_evidence_retains_scoped_qualification(sdk_evidence: Path) -> None:
    result = audit(sdk_evidence)
    assert result["status"] == "PASS"
    assert result["test_count"] == 499
    assert result["actual_imported_project_file_count"] == 82
    assert result["benchmark_five_layers"] == "PENDING"
    assert result["full_logical_entries_qualified"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "skipped_case",
        "omitted_case",
        "duplicate_case",
        "omitted_factory",
        "factory_drift",
        "driver_drift",
        "full_claim",
        "benchmark_claim",
        "failed_command",
        "omitted_original_file",
        "changed_native_evidence",
        "frozen_source_drift",
    ],
)
def test_forged_sdk_success_is_rejected(sdk_evidence: Path, tamper: str) -> None:
    path = sdk_evidence / SDK_DIRECTORY / "report.json"
    document = json.loads(path.read_text())
    junit_path = sdk_evidence / SDK_DIRECTORY / "pytest.xml"
    if tamper in {"skipped_case", "omitted_case", "duplicate_case"}:
        tree = ET.parse(junit_path)
        suite = tree.getroot().find("testsuite")
        cases = suite.findall("testcase")
        if tamper == "skipped_case":
            ET.SubElement(cases[0], "skipped")
            suite.set("skipped", "1")
            document["test_totals"]["skipped"] = 1
        elif tamper == "omitted_case":
            suite.remove(cases[-1])
            suite.set("tests", "498")
            document["test_totals"]["tests"] = 498
        else:
            cases[-1].set("name", cases[0].get("name"))
            cases[-1].set("classname", cases[0].get("classname"))
        tree.write(junit_path)
        document["junit_sha256"] = digest(junit_path)
    elif tamper == "omitted_factory":
        document["source_snapshot"] = [
            item
            for item in document["source_snapshot"]
            if item["path"] != "src/tscompbench/adapters/factory.py"
        ]
        document["source_snapshot_sha256"] = hashlib.sha256(
            json.dumps(document["source_snapshot"], sort_keys=True).encode()
        ).hexdigest()
        closure_path = sdk_evidence / SDK_DIRECTORY / "python-closure.json"
        closure = json.loads(closure_path.read_text())
        closure["source_snapshot"] = document["source_snapshot"]
        write(closure_path, closure)
        document["python_closure_sha256"] = digest(closure_path)
    elif tamper in {"factory_drift", "driver_drift"}:
        name = (
            "src/tscompbench/adapters/factory.py"
            if tamper == "factory_drift"
            else "tools/qualify_littleintpacker_sdk.py"
        )
        source = sdk_evidence / name
        original = source.read_bytes()
        source.unlink()
        source.write_bytes(original + b"\n# unexecuted change\n")
    elif tamper == "full_claim":
        document["full_logical_entries_qualified"] = True
    elif tamper == "benchmark_claim":
        document["benchmark_five_layers"] = "QUALIFIED"
    elif tamper == "failed_command":
        document["commands"][-1]["returncode"] = 1
    elif tamper == "omitted_original_file":
        document["original_vendor_equal_file_count"] = 13
    elif tamper == "frozen_source_drift":
        frozen = sdk_evidence / SDK_DIRECTORY / "sources/src/tscompbench/adapters/factory.py"
        frozen.write_bytes(frozen.read_bytes() + b"\n# changed after execution\n")
    else:
        document["native_current_audit"]["native_cases"] -= 1
    write(path, document)
    with pytest.raises(RuntimeError):
        audit(sdk_evidence)
