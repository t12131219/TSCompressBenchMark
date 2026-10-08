"""Revalidate current files against completed native qualification evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def audit(root: Path = ROOT) -> dict:
    adapter = root / "adapters/fast_differential"
    lock_path = adapter / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    require(
        lock["repository"] == "https://github.com/lemire/FastDifferentialCoding",
        "wrong upstream repository",
    )
    require(
        lock["commit"] == "714a9febba97ffb6b574c7a41cf1142090558727"
        and lock["dirty"] is False
        and lock["submodules"] == [],
        "wrong source pin",
    )
    for item in lock["files"]:
        require(sha(root / item["path"]) == item["sha256"], "source drift: " + item["path"])
    source_path = root / "build/source-audits/fast-differential-source-tests.json"
    source = json.loads(source_path.read_text())
    require(
        source["status"] == "PASS" and source["source_lock_sha256"] == sha(lock_path),
        "source qualification absent/stale",
    )
    require(
        source["driver_sha256"] == sha(adapter / "tests/run_source_tests.py"),
        "source qualification driver drift",
    )
    require(
        len(source["tests"]) == 6
        and {(t["kind"], t["profile"]) for t in source["tests"]}
        == {
            (kind, profile)
            for kind in ("upstream", "source_guard")
            for profile in ("release", "debug", "sanitizer")
        },
        "incomplete source qualification",
    )
    for test in source["tests"]:
        filename = (
            adapter / "vendor/FastDifferentialCoding/tests/unit.c"
            if test["kind"] == "upstream"
            else adapter / "tests/source_guard.c"
        )
        require(
            test["returncode"] == 0
            and sha(filename) == test["test_sha256"]
            and sha(Path(test["command"][0])) == test["executable_sha256"],
            "source test drift",
        )
        if test["kind"] == "source_guard":
            require("cases PASS: 520" in test["stdout"], "incomplete source guard coverage")
    native_path = root / "build/source-audits/fast-differential-native-tests.json"
    native = json.loads(native_path.read_text())
    require(native["status"] == "PASS", "native qualification not PASS")
    for field, path in (
        ("source_lock_sha256", lock_path),
        ("driver_sha256", adapter / "tests/run_native_tests.py"),
        ("build_driver_sha256", adapter / "build_native.py"),
        ("contract_sha256", adapter / "contract.md"),
        ("original_source_report_sha256", source_path),
    ):
        require(native[field] == sha(path), "native evidence drift: " + field)
    expected = {
        (kind, profile)
        for kind in ("shared", "instrumented")
        for profile in ("release", "debug", "sanitizer")
    }
    matrix = {(t["kind"], t.get("profile")) for t in native["tests"]}
    require(
        len(native["tests"]) == 7 and matrix == expected | {("shared_timer_overflow", None)},
        "native qualification matrix incomplete",
    )
    for test in native["tests"]:
        path = (
            root / "tests/native/native_timing_smoke.c"
            if test["kind"] == "shared_timer_overflow"
            else adapter / "tests/abi_qualification.c"
        )
        require(
            test["returncode"] == 0
            and sha(path) == test["test_sha256"]
            and sha(Path(test["command"][0])) == test["executable_sha256"],
            "native test drift",
        )
        if test["kind"] != "shared_timer_overflow":
            require("cases PASS: 4160" in test["stdout"], "native guard coverage incomplete")
        if test["kind"] == "instrumented":
            require(
                "original API routing/allocation failure/native timer faults/accumulation PASS"
                in test["stdout"],
                "native fault coverage absent",
            )
    require(
        len(native["builds"]) == 3
        and {b["profile"] for b in native["builds"]} == {"release", "debug", "sanitizer"},
        "native build matrix incomplete",
    )
    closure_counts = {}
    for qualified in native["builds"]:
        directory = root / "build/adapters/fast_differential_u32" / qualified["profile"]
        current = json.loads((directory / "build-record.json").read_text())
        require(current == qualified and current["status"] == "PASS", "qualified build changed")
        require(
            current["algorithm"] == "fast-differential-u32" and not current["runtime_fallback"],
            "wrong build identity/path",
        )
        require(sha(root / current["artifact"]) == current["artifact_sha256"], "binary drift")
        command = json.loads((directory / "compile-command.json").read_text())
        require(
            hashlib.sha256(canonical_json_bytes(command)).hexdigest()
            == current["compile_commands_sha256"],
            "compile command drift",
        )
        require(len(command["commands"]) == 3, "baseline/SSE separate builds missing")
        require(
            "-march=native" not in sum(command["commands"], [])
            and "-msse4.1" not in command["commands"][0]
            and "-march=x86-64" in command["commands"][0]
            and "-msse4.1" in command["commands"][1],
            "ISA gate build contract changed",
        )
        for field in (
            "source_files",
            "binding_sources",
            "compiled_source_closure",
            "objects",
            "runtime_dependencies",
        ):
            require(bool(current[field]), "build evidence missing: " + field)
            for item in current[field]:
                require(
                    sha(root / item["path"]) == item["sha256"], "dependency drift: " + item["path"]
                )
        closure_counts[qualified["profile"]] = len(current["compiled_source_closure"])
    return {
        "status": "PASS",
        "algorithm": "fast-differential-u32",
        "object_level": "P0_PRIMITIVE",
        "source_report_sha256": sha(source_path),
        "native_report_sha256": sha(native_path),
        "source_lock_sha256": sha(lock_path),
        "source_cases_per_profile": 520,
        "bounded_cases_per_executable": 4160,
        "bounded_executables": 6,
        "compiled_dependency_counts": closure_counts,
        "original_apis": [
            "compute_deltas",
            "compute_deltas_inplace",
            "compute_prefix_sum",
            "compute_prefix_sum_inplace",
        ],
        "source_modified": False,
        "benchmark_five_layers": "PENDING",
        "platform": "LINUX_X86_64_SSE4_1",
        "leak_detection": "DISABLED",
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/fast-differential-native-current-audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
