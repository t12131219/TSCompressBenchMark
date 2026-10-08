"""Reject altered or incomplete actual SDK executions without changing historical files."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple8b_rle_native import identity  # noqa: E402
from audit_fastpfor_simple8b_rle_sdk import DEFAULT_REPORT, audit  # noqa: E402


def test_actual_sdk_keeps_full_entry_and_five_layers_unclaimed() -> None:
    result = audit()
    assert result["status"] == "PASS" and result["test_count"] == 466
    assert result["actual_imported_project_file_count"] == 87
    assert result["benchmark_five_layers"] == "PENDING"
    assert not result["full_logical_entry_qualified"]


@pytest.mark.parametrize("tamper", [
    "skipped", "omitted", "duplicate", "omitted_factory", "frozen_source_drift",
    "raw_failure", "library_omitted", "native_evidence_changed", "full_claim", "five_layer_claim",
])
def test_incomplete_or_forged_sdk_execution_is_rejected(tmp_path: Path, tamper: str) -> None:
    document = json.loads(DEFAULT_REPORT.read_text())
    original = ROOT / document["driver_snapshot"]["path"]
    # Relocate only a disposable evidence copy. All source/native identities stay real.
    for field, name in (("driver_snapshot", "driver.py"), ("junit", "pytest.xml"),
                        ("closure", "python-closure.json")):
        target = tmp_path / name
        shutil.copyfile(ROOT / document[field]["path"], target)
        document[field] = identity(target)
    raw = tmp_path / "worker.json"
    shutil.copyfile(ROOT / document["commands"][0]["path"], raw)
    document["commands"][0] = identity(raw)
    (tmp_path / "sources").symlink_to(original.parent / "sources", target_is_directory=True)
    if tamper in {"skipped", "omitted", "duplicate"}:
        path = tmp_path / "pytest.xml"
        tree = ET.parse(path)
        suite = tree.getroot().find("testsuite")
        cases = suite.findall("testcase")
        if tamper == "skipped":
            ET.SubElement(cases[0], "skipped")
            suite.set("skipped", "1")
            document["test_totals"]["skipped"] = 1
        elif tamper == "omitted":
            suite.remove(cases[-1])
            suite.set("tests", "465")
            document["test_totals"]["tests"] = 465
        else:
            cases[-1].set("classname", cases[0].get("classname"))
            cases[-1].set("name", cases[0].get("name"))
        tree.write(path)
        document["junit"] = identity(path)
    elif tamper == "omitted_factory":
        document["source_snapshot"] = [i for i in document["source_snapshot"]
                                       if i["path"] != "src/tscompbench/adapters/factory.py"]
        document["source_snapshot_sha256"] = hashlib.sha256(
            json.dumps(document["source_snapshot"], sort_keys=True).encode()).hexdigest()
        path = tmp_path / "python-closure.json"
        closure = json.loads(path.read_text())
        closure["source_snapshot"] = document["source_snapshot"]
        path.write_text(json.dumps(closure))
        document["closure"] = identity(path)
    elif tamper == "frozen_source_drift":
        (tmp_path / "sources").unlink()
        shutil.copytree(original.parent / "sources", tmp_path / "sources")
        path = tmp_path / "sources/src/tscompbench/adapters/factory.py"
        path.write_bytes(path.read_bytes() + b"\n# never executed\n")
    elif tamper == "raw_failure":
        command = json.loads(raw.read_text())
        command["returncode"] = 1
        raw.write_text(json.dumps(command))
        document["commands"][0] = identity(raw)
    elif tamper == "library_omitted":
        document["native_libraries_loaded"].pop()
    elif tamper == "native_evidence_changed":
        document["native_current_audit"]["guard_page_cases"] -= 1
    elif tamper == "full_claim":
        document["full_logical_entry_qualified"] = True
    else:
        document["benchmark_five_layers"] = "QUALIFIED"
    report = tmp_path / "report.json"
    report.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        audit(report)
