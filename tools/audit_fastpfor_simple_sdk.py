"""Verify direct Simple-9/16 SDK evidence without declaring Benchmark admission."""

from __future__ import annotations

import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from audit_fastpfor_simple_upstream import audit as audit_upstream

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def audit(root: Path = ROOT, report_path: Path | None = None) -> dict:
    native = runpy.run_path(str(ROOT / "tools/audit_fastpfor_simple_native.py"))["audit"](root)
    upstream = audit_upstream(root)
    if report_path is None:
        card_path = root / "registry/onboarding/simple9-u28.json"
        card = json.loads(card_path.read_text()) if card_path.is_file() else {"upstream_tests": []}
        records = [item for item in card["upstream_tests"] if Path(item["evidence"]).name in ("fastpfor_simple_sdk_tests.json", "report.json") and "sdk" in item["evidence"]]
        report_path = root / records[0]["evidence"] if len(records) == 1 else root / "build/source-audits/fastpfor_simple_sdk_tests.json"
    report = json.loads(report_path.read_text())
    out = root / report.get("output_directory", "build/source-audits/fastpfor_simple-sdk")
    require(out.resolve().is_relative_to(root.resolve()), "SDK output escapes project")
    require(
        report["status"] == "PASS"
        and report["native_current_audit"] == native
        and report["upstream_current_audit"] == upstream,
        "SDK native evidence absent/stale",
    )
    for field, path in (
        ("driver_sha256", root / "tools/qualify_fastpfor_simple_sdk.py"),
        ("native_auditor_sha256", root / "tools/audit_fastpfor_simple_native.py"),
        ("junit_sha256", out / "pytest.xml"),
        (
            "python_closure_sha256",
            out / "python-closure.json",
        ),
    ):
        require(report[field] == sha(path), "SDK evidence drift: " + field)
    require(
        report["qualification_scope"] == "DIRECT_PYTHON_UINT28_SIMPLE_MARKED_AND_UNMARKED_SDK"
        and report["benchmark_registration"] == report["benchmark_five_layers"] == "PENDING",
        "SDK scope or premature Benchmark claim",
    )
    require(
        report["source_repository_unmodified"] is True
        and report["original_vendor_equal_file_count"] == 51,
        "original source comparison missing",
    )
    junit_path = out / "pytest.xml"
    suites = ET.parse(junit_path).getroot().findall("testsuite")
    totals = {
        field: sum(int(s.get(field, "0")) for s in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    require(
        totals == report["test_totals"] == {"tests": 322, "failures": 0, "errors": 0, "skipped": 0},
        "SDK tests incomplete/failed/skipped",
    )
    cases = [c for suite in suites for c in suite.findall("testcase")]
    counts = Counter(c.get("name").split("[", 1)[0] for c in cases)
    require(
        counts
        == {
            "test_tail_wire_ledger_and_native_observations": 96,
            "test_each_source_integer_width": 174,
            "test_every_selector_and_mixed_width_layout": 6,
            "test_layout_gather_preserves_logical_order": 18,
            "test_atomic_capacity_domain_alias_and_lifecycle": 6,
            "test_fresh_marked_decode_timer_disable_and_repeated_queries": 6,
            "test_untrusted_descriptors_frames_and_all_truncations": 6,
            "test_invalid_parameters": 5,
            "test_wrong_dtype_is_rejected": 4,
            "test_wrong_routed_geometry_and_missing_native_artifact": 1,
        }
        and len({(c.get("classname"), c.get("name")) for c in cases}) == 322
        and all(not list(c) for c in cases),
        "actual SDK testcase universe incomplete/duplicated/failed",
    )
    closure = json.loads(
        (out / "python-closure.json").read_text()
    )
    require(
        closure["status"] == "PASS" and closure["source_snapshot"] == report["source_snapshot"],
        "actual imported SDK closure differs",
    )
    require(
        hashlib.sha256(json.dumps(report["source_snapshot"], sort_keys=True).encode()).hexdigest()
        == report["source_snapshot_sha256"],
        "SDK source snapshot digest differs",
    )
    paths = set()
    for item in report["source_snapshot"]:
        require(
            sha(root / item["path"]) == item["sha256"],
            "SDK consumed Python source drift: " + item["path"],
        )
        paths.add(item["path"])
    require(
        len(paths) == len(report["source_snapshot"])
        and {
            "src/tscompbench/adapters/fastpfor_simple.py",
            "src/tscompbench/adapters/factory.py",
            "src/tscompbench/adapters/deflate_zlib.py",
            "src/tscompbench/adapters/native_timing.py",
            "src/tscompbench/execution/protocol.py",
            "src/tscompbench/execution/repetition.py",
            "tests/adapters/test_fastpfor_simple.py",
            "tools/qualify_fastpfor_simple_sdk.py",
        }
        <= paths,
        "SDK dependency closure incomplete",
    )
    require(
        any(
            c["returncode"] == 0 and c["command"][-1] == "--worker" and "322 passed" in c["stdout"]
            for c in report["commands"]
        ),
        "SDK worker execution output absent",
    )
    original = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_FastPFOR"
    expected = [
        ["git", "-C", str(original), "rev-parse", "HEAD"],
        ["git", "-C", str(original), "status", "--porcelain"],
        ["git", "-C", str(original), "submodule", "status"],
        [
            report["python_runtime"]["executable"],
            str(ROOT / "tools/qualify_fastpfor_simple_sdk.py"),
            "--worker",
        ],
    ]
    require(
        [c["command"] for c in report["commands"]] == expected
        and all(c["returncode"] == 0 for c in report["commands"])
        and report["commands"][0]["stdout"].strip() == "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
        and not report["commands"][1]["stdout"].strip()
        and not report["commands"][2]["stdout"].strip(),
        "SDK source identity or raw command universe differs",
    )
    return {
        "status": "PASS",
        "qualification_scope": report["qualification_scope"],
        "sdk_report_sha256": sha(report_path),
        "native_report_sha256": native["native_report_sha256"],
        "upstream_audit": upstream,
        "test_count": totals["tests"],
        "actual_imported_project_file_count": len(paths),
        "source_snapshot_sha256": report["source_snapshot_sha256"],
        "keys": ["simple9-u28", "simple9hacked-u28", "simple16-u28"],
        "python_sdk": "QUALIFIED_SCOPED_UINT28_ONLY",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/fastpfor_simple_sdk_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
