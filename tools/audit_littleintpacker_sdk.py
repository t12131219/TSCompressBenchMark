"""Verify complete five-API LittleIntPacker SDK execution without claiming Benchmark admission."""

from __future__ import annotations

import hashlib
import json
import runpy
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def sdk_report_path(root: Path = ROOT) -> Path:
    current = root / "build/source-audits/littleintpacker-sdk-20261007-2/report.json"
    return current if current.exists() else root / "build/source-audits/littleintpacker_sdk_tests.json"


def audit(root: Path = ROOT, report_path: Path | None = None) -> dict:
    native = runpy.run_path(str(ROOT / "tools/audit_littleintpacker_native.py"))["audit"](root)
    report_path = report_path or sdk_report_path(root)
    report = json.loads(report_path.read_text())
    out = root / report.get("output_directory", "build/source-audits/littleintpacker-sdk")
    if "execution_suffix" in report:
        require(out == report_path.parent
                and report["actual_cpu_affinity"] == [2]
                and (out / "driver.py").read_bytes() == (root / "tools/qualify_littleintpacker_sdk.py").read_bytes(),
                "SDK immutable driver/affinity differs")
    require(
        report["status"] == "PASS"
        and report["native_current_audit"] == native
        and report["full_logical_entries_qualified"] is False,
        "SDK native evidence absent/stale",
    )
    for field, path in (
        ("driver_sha256", root / "tools/qualify_littleintpacker_sdk.py"),
        ("native_auditor_sha256", root / "tools/audit_littleintpacker_native.py"),
        ("junit_sha256", out / "pytest.xml"),
        (
            "python_closure_sha256",
            out / "python-closure.json",
        ),
    ):
        require(report[field] == sha(path), "SDK evidence drift: " + field)
    require(
        report["qualification_scope"] == "DIRECT_PYTHON_UINT32_FIXED_AUTO_FIVE_API_SDK"
        and report["benchmark_registration"] == report["benchmark_five_layers"] == "PENDING",
        "SDK scope or premature Benchmark claim",
    )
    require(
        report["source_repository_unmodified"] is True
        and report["original_vendor_equal_file_count"] == 14,
        "original source comparison missing",
    )
    junit_path = out / "pytest.xml"
    suites = ET.parse(junit_path).getroot().findall("testsuite")
    totals = {
        field: sum(int(s.get(field, "0")) for s in suites)
        for field in ("tests", "failures", "errors", "skipped")
    }
    require(
        totals == report["test_totals"] == {"tests": 499, "failures": 0, "errors": 0, "skipped": 0},
        "SDK tests incomplete/failed/skipped",
    )
    cases = [c for suite in suites for c in suite.findall("testcase")]
    counts = Counter(c.get("name").split("[", 1)[0] for c in cases)
    require(
        counts
        == {
            "test_full_uint32_tail_wire_ledger_and_native_observations": 115,
            "test_every_width_zero_maximum_and_original_api": 330,
            "test_layout_gather_preserves_logical_order": 15,
            "test_atomic_capacity_domain_alias_lifecycle_and_fresh_decoder": 5,
            "test_native_timing_disable_reaches_actual_library_and_preserves_wire": 5,
            "test_untrusted_descriptor_native_frame_and_every_truncation": 5,
            "test_invalid_parameters": 9,
            "test_wrong_dtype_and_routed_geometry": 5,
            "test_missing_native_artifact_and_invalid_routed_contract": 1,
            "test_bmi2_resolver_requires_avx2_and_bmi2_without_lzcnt": 5,
            "test_horizontal_resolver_requires_ssse3_and_sse4_1": 4,
        }
        and len({(c.get("classname"), c.get("name")) for c in cases}) == 499
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
    if "execution_suffix" in report:
        require(closure["actual_cpu_affinity"] == [2], "SDK actual worker affinity differs")
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
        if "execution_suffix" in report:
            require((out / "sources" / item["path"]).read_bytes() == (root / item["path"]).read_bytes(),
                    "SDK frozen source differs from actual imported bytes")
    require(
        len(paths) == len(report["source_snapshot"])
        and {
            "src/tscompbench/adapters/littleintpacker.py",
            "src/tscompbench/adapters/factory.py",
            "src/tscompbench/adapters/deflate_zlib.py",
            "src/tscompbench/adapters/native_timing.py",
            "src/tscompbench/planning/resolution.py",
            "src/tscompbench/execution/protocol.py",
            "src/tscompbench/execution/repetition.py",
            "tests/adapters/test_littleintpacker.py",
            "tools/qualify_littleintpacker_sdk.py",
        }
        <= paths,
        "SDK dependency closure incomplete",
    )
    require(
        any(
            c["returncode"] == 0 and "--worker" in c["command"] and "499 passed" in c["stdout"]
            for c in report["commands"]
        ),
        "SDK worker execution output absent",
    )
    original = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_LittleIntPacker"
    expected = [
        ["git", "-C", str(original), "rev-parse", "HEAD"],
        ["git", "-C", str(original), "status", "--porcelain"],
        ["git", "-C", str(original), "submodule", "status"],
        [
            report["python_runtime"]["executable"],
            str(ROOT / "tools/qualify_littleintpacker_sdk.py"),
            "--worker",
            *(["--suffix", report["execution_suffix"]] if "execution_suffix" in report else []),
        ],
    ]
    require(
        [c["command"] for c in report["commands"]] == expected
        and all(c["returncode"] == 0 for c in report["commands"])
        and report["commands"][0]["stdout"].strip() == "8777f574a5ab3c653881371819383c986292843c"
        and not report["commands"][1]["stdout"].strip()
        and not report["commands"][2]["stdout"].strip(),
        "SDK source identity or raw command universe differs",
    )
    return {
        "status": "PASS",
        "qualification_scope": report["qualification_scope"],
        "sdk_report_sha256": sha(report_path),
        "sdk_report_path": str(report_path.relative_to(root)),
        "native_report_sha256": native["native_report_sha256"],
        "test_count": totals["tests"],
        "actual_imported_project_file_count": len(paths),
        "source_snapshot_sha256": report["source_snapshot_sha256"],
        "keys": [
            "littleintpacker-pack32-u32",
            "littleintpacker-turbo-u32",
            "littleintpacker-sc-u32",
            "littleintpacker-bmi2-u32",
            "littleintpacker-horizontal-u32",
        ],
        "python_sdk": "QUALIFIED_SCOPED_UINT32_FIXED_AUTO_FIVE_APIS",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/littleintpacker_sdk_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
