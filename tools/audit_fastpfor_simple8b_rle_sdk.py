"""Verify all actual RLE SDK test identities, raw execution and current closures."""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from audit_fastpfor_simple8b_rle_native import audit as audit_native, identity, require, verify

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "build/source-audits/fastpfor-simple8b-rle-sdk-20261007-1/report.json"
COUNTS = {
    "test_uint32_tail_wire_ledger_and_native_observations": 46,
    "test_every_width_pattern_and_original_wire": 396,
    "test_all_fifteen_selectors_and_sparse_rle_identity": 2,
    "test_layout_gather_preserves_full_uint32": 6,
    "test_atomic_capacity_alias_lifecycle_reset": 2,
    "test_timer_disable_fresh_decoder_queries_and_close": 2,
    "test_untrusted_descriptors_native_grammar_and_all_truncations": 2,
    "test_invalid_parameters": 5, "test_wrong_dtype_is_rejected": 4,
    "test_invalid_routed_contract_and_native_identity": 1,
}


def audit(report_path: Path | None = None) -> dict:
    if report_path is None:
        card_path = ROOT / "registry/onboarding/fastpfor-simple8b-rle-u32.json"
        card = json.loads(card_path.read_text()) if card_path.is_file() else {}
        tests = [t for t in card.get("upstream_tests", [])
                 if t["name"] == "direct_python_sdk_466_tests"]
        report_path = ROOT / tests[0]["evidence"] if len(tests) == 1 else DEFAULT_REPORT
    report = json.loads(report_path.read_text())
    require(report["status"] == "SDK_TESTS_EXECUTED_INDEPENDENT_AUDIT_PENDING"
            and report["scope"] == "DIRECT_PYTHON_UINT32_MARKED_UNMARKED_RLE_SDK_ONLY"
            and report["actual_cpu_affinity"] == [2], "SDK execution/scope/affinity differs")
    require(report["full_logical_entry_qualified"] is False
            and report["python_sdk_audit"] == report["benchmark_registration"] == report["benchmark_five_layers"] == "PENDING",
            "SDK execution scope expanded")
    native = audit_native()
    require(report["native_current_audit"] == native, "SDK native evidence stale")
    driver = verify(report["driver"], ROOT / "tools/qualify_fastpfor_simple8b_rle_sdk.py")
    snapshot = verify(report["driver_snapshot"])
    out = snapshot.parent
    require(snapshot.read_bytes() == driver.read_bytes(), "SDK executed driver snapshot differs")
    junit = verify(report["junit"], out / "pytest.xml")
    suites = ET.parse(junit).getroot().findall("testsuite")
    totals = {k: sum(int(s.get(k, "0")) for s in suites) for k in ("tests", "failures", "errors", "skipped")}
    require(totals == report["test_totals"] == {"tests": 466, "failures": 0, "errors": 0, "skipped": 0},
            "SDK cases incomplete, skipped or failed")
    cases = [c for suite in suites for c in suite.findall("testcase")]
    require(Counter(c.get("name").split("[",1)[0] for c in cases) == COUNTS
            and len({(c.get("classname"),c.get("name")) for c in cases}) == 466
            and all(not list(c) for c in cases), "SDK actual testcase identities incomplete")
    closure_path = verify(report["closure"], out / "python-closure.json")
    closure = json.loads(closure_path.read_text())
    require(closure["status"] == "PASS" and closure["actual_cpu_affinity"] == [2]
            and closure["source_snapshot"] == report["source_snapshot"]
            and closure["native_libraries_loaded"] == report["native_libraries_loaded"], "SDK actual closure differs")
    require(hashlib.sha256(json.dumps(report["source_snapshot"],sort_keys=True).encode()).hexdigest()
            == report["source_snapshot_sha256"], "SDK source snapshot digest differs")
    paths = set()
    for item in report["source_snapshot"]:
        path = verify(item)
        paths.add(item["path"])
        require((out / "sources" / item["path"]).read_bytes() == path.read_bytes(), "executed SDK source snapshot differs")
    require(len(paths) == len(report["source_snapshot"]) and {
        "src/tscompbench/adapters/factory.py", "src/tscompbench/adapters/fastpfor_simple8b_rle.py",
        "src/tscompbench/adapters/fastpfor_simple.py", "src/tscompbench/adapters/native_timing.py",
        "src/tscompbench/execution/repetition.py", "src/tscompbench/execution/protocol.py",
        "src/tscompbench/planning/resolution.py", "tests/adapters/test_fastpfor_simple8b_rle.py",
        "tests/adapters/test_fastpfor_simple.py", "tools/qualify_fastpfor_simple8b_rle_sdk.py",
    } <= paths, "SDK Python dependency universe incomplete")
    require(len(report["commands"]) == 1, "SDK raw worker universe differs")
    raw = json.loads(verify(report["commands"][0], out / "worker.json").read_text())
    require(raw["returncode"] == 0 and raw["stderr"] == ""
            and raw["command"] == [report["python_runtime"]["executable"],str(driver),"--worker"]
            and "466 passed" in raw["stdout"], "SDK actual worker execution absent")
    expected_libraries = {
        "build/adapters/fastpfor_simple8b_rle/20261007-2/release/libtscb_fastpfor_simple8b_rle.so",
        "build/adapters/fastpfor_simple/release/libtscb_fastpfor_simple.so",
    }
    require({i["path"] for i in report["native_libraries_loaded"]} == expected_libraries,
            "SDK loaded native library universe differs")
    for item in report["native_libraries_loaded"]:
        verify(item)
    return {
        "status": "PASS", "scope": report["scope"], "sdk_report": identity(report_path),
        "native_current_audit": native, "test_count": 466,
        "actual_imported_project_file_count": len(paths), "source_snapshot": report["source_snapshot"],
        "python_sdk": "QUALIFIED_SCOPED_UINT32_MARKED_UNMARKED_ONLY",
        "benchmark_registration": "PENDING", "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False, "auditor_sha256": identity(Path(__file__))["sha256"],
    }


if __name__ == "__main__":
    out = ROOT / "build/source-audits/fastpfor_simple8b_rle_sdk_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        out.write_text(json.dumps({"status":"FAIL","error":str(error),"full_logical_entry_qualified":False},indent=2)+"\n")
        raise
    out.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("source_snapshot","native_current_audit")},indent=2))
