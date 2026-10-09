"""Verify direct MaskedVByte SDK evidence without declaring Benchmark admission."""

from __future__ import annotations

import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def audit(root: Path = ROOT, report_path: Path | None = None) -> dict:
    native = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_native.py"))["audit"](root)
    if report_path is None:
        card_path = root / "registry/onboarding/maskedvbyte-u32.json"
        card = json.loads(card_path.read_text()) if card_path.is_file() else {"upstream_tests": []}
        records = [item for item in card["upstream_tests"] if item["name"] == "direct_sdk"]
        report_path = root / records[0]["evidence"] if len(records) == 1 else root / "build/source-audits/maskedvbyte-sdk-tests.json"
    report = json.loads(report_path.read_text())
    out = root / report.get("output_directory", "build/source-audits/maskedvbyte-sdk")
    require(out.resolve().is_relative_to(root.resolve()), "SDK output escapes project")
    require(
        report["status"] == "PASS" and report["native_current_audit"] == native,
        "SDK native evidence absent/stale",
    )
    for field, path in (
        ("driver_sha256", root / "tools/qualify_maskedvbyte_sdk.py"),
        ("native_auditor_sha256", root / "tools/audit_maskedvbyte_native.py"),
        ("junit_sha256", out / "pytest.xml"),
        ("python_closure_sha256", out / "python-closure.json"),
    ):
        require(report[field] == sha(path), "SDK evidence drift: " + field)
    require(
        report["qualification_scope"] == "DIRECT_PYTHON_UINT32_PLAIN_AND_MODULAR_DELTA_SDK"
        and report["benchmark_registration"] == report["benchmark_five_layers"] == "PENDING",
        "SDK scope or premature Benchmark claim",
    )
    require(
        report["source_repository_unmodified"] is True
        and report["original_vendor_equal_file_count"] == 11,
        "original source comparison missing",
    )
    junit_path = out / "pytest.xml"
    suites = ET.parse(junit_path).getroot().findall("testsuite")
    totals = {
        field: sum(int(s.get(field, "0")) for s in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    require(
        totals == report["test_totals"] == {"tests": 159, "failures": 0, "errors": 0, "skipped": 0},
        "SDK tests incomplete/failed/skipped",
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
            "src/tscompbench/adapters/maskedvbyte.py",
            "src/tscompbench/adapters/deflate_zlib.py",
            "src/tscompbench/adapters/native_timing.py",
            "src/tscompbench/execution/protocol.py",
            "src/tscompbench/execution/repetition.py",
            "tests/adapters/test_maskedvbyte.py",
            "tools/qualify_maskedvbyte_sdk.py",
        }
        <= paths,
        "SDK dependency closure incomplete",
    )
    require(
        any(
            c["returncode"] == 0 and c["command"][-1] == "--worker" and "159 passed" in c["stdout"]
            for c in report["commands"]
        ),
        "SDK worker execution output absent",
    )
    return {
        "status": "PASS",
        "qualification_scope": report["qualification_scope"],
        "sdk_report_sha256": sha(report_path),
        "native_report_sha256": native["native_report_sha256"],
        "test_count": totals["tests"],
        "actual_imported_project_file_count": len(paths),
        "source_snapshot_sha256": report["source_snapshot_sha256"],
        "keys": ["maskedvbyte-u32", "delta-maskedvbyte-u32"],
        "python_sdk": "QUALIFIED_SCOPED_UINT32_ONLY",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/maskedvbyte-sdk-current-audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
