"""Recheck MaskedVByte's original failure, explicit patch and actual tested source closure."""

from __future__ import annotations

import hashlib
import itertools
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def audit(root: Path = ROOT) -> dict:
    adapter = root / "adapters/maskedvbyte"
    lock_path = adapter / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    require(
        lock["repository"] == "https://github.com/fast-pack/MaskedVByte"
        and lock["commit"] == "e2298b7a28002e08f3f74755353b7229bfe6475b"
        and lock["license"] == "Apache-2.0"
        and not lock["original_source_modified"],
        "source identity or license differs",
    )
    require(
        len(lock["files"]) == len({item["path"] for item in lock["files"]}) == 11,
        "source files incomplete",
    )
    for item in lock["files"]:
        require(sha(root / item["path"]) == item["sha256"], "original source drift")
    report_path = root / "build/source-audits/maskedvbyte-source-both-tests.json"
    report = json.loads(report_path.read_text())
    require(
        report["status"] == "PASS"
        and report["source_kind"] == "both"
        and report["source_lock_sha256"] == sha(lock_path)
        and report["driver_sha256"] == sha(adapter / "tests/run_source_tests.py")
        and report["guard_sha256"] == sha(adapter / "tests/source_guard.c")
        and report["source_files"] == lock["files"]
        and report["source_repository_unmodified"] is True
        and report["benchmark_adapter_qualification"] == "NOT_CLAIMED",
        "source qualification stale or claims Benchmark admission",
    )
    tests = report["tests"]
    matrix = set(
        itertools.product(
            ("original", "patched"),
            ("release", "debug", "sanitizer"),
            ("upstream", "decode_guard", "query_guard"),
        )
    )
    require(
        len(tests) == 18
        and {(t["source_kind"], t["profile"], t["test_kind"]) for t in tests} == matrix,
        "source test matrix incomplete",
    )
    for test in tests:
        expected_failure = (test["source_kind"], test["profile"], test["test_kind"]) == (
            "original",
            "sanitizer",
            "decode_guard",
        )
        require(
            test["returncode"] == (1 if expected_failure else 0), "unexpected source test failure"
        )
        require(
            test["status"] == ("FAIL" if expected_failure else "PASS"), "source status misreported"
        )
        if expected_failure:
            require(
                "varintdecode.c:1380" in test["stderr"]
                and "left shift of 15 by 28" in test["stderr"]
                and "UndefinedBehaviorSanitizer" in test["stderr"],
                "original uint32 UB evidence missing",
            )
        elif test["test_kind"] == "decode_guard":
            require("cases PASS: 1872;" in test["stdout"], "decode/seed/guard universe incomplete")
        elif test["test_kind"] == "query_guard":
            require(
                "cases PASS: 936; query calls: 175344" in test["stdout"],
                "query universe incomplete",
            )
        expected_test = (
            adapter / "tests/source_guard.c"
            if test["test_kind"] != "upstream"
            else adapter / "vendor/MaskedVByte/tests/unit.c"
        )
        require(sha(expected_test) == test["test_sha256"], "tested program drift")
        require(
            sha(root / test["executable"]["path"]) == test["executable"]["sha256"],
            "tested executable drift",
        )
        require(
            any(
                command == {key: test[key] for key in ("command", "returncode", "stdout", "stderr")}
                for command in report["commands"]
            ),
            "test lacks original command output",
        )
    require(report["failed_test_count"] == 1, "original failure count differs")
    builds = report["builds"]
    require(
        len(builds) == 6
        and {(b["source_kind"], b["profile"]) for b in builds}
        == set(itertools.product(("original", "patched"), ("release", "debug", "sanitizer"))),
        "compiled profile matrix incomplete",
    )
    for build in builds:
        for field in ("source_translation_units", "compiled_source_closure", "objects"):
            require(bool(build[field]), "compiler closure absent")
            for item in build[field]:
                require(sha(root / item["path"]) == item["sha256"], "tested compiled input drift")
    require(len(report["patches"]) == 1, "unexpected patch series")
    patch = report["patches"][0]
    patch_path = root / patch["path"]
    require(sha(patch_path) == patch["sha256"], "patch drift")
    original = adapter / "vendor/MaskedVByte/src/varintdecode.c"
    # Reapply the explicit patch independently; do not trust a patched file label.
    with tempfile.TemporaryDirectory(prefix="tscb-maskedvbyte-patch-") as directory:
        scratch = Path(directory)
        (scratch / "src").mkdir()
        shutil.copyfile(original, scratch / "src/varintdecode.c")
        observed = subprocess.run(
            ["patch", "--batch", "--forward", "-p1", "-d", str(scratch), "-i", str(patch_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        require(observed.returncode == 0, "patch cannot reproduce tested source")
        generated = root / "build/source-audits/maskedvbyte-source/patched/src/varintdecode.c"
        require(
            sha(scratch / "src/varintdecode.c") == sha(generated),
            "patched translation unit is not reproducible",
        )
        encode = adapter / "vendor/MaskedVByte/src/varintencode.c"
        require(
            sha(encode) == sha(generated.parent / "varintencode.c"),
            "patch changed encoder or wire bytes",
        )
    return {
        "status": "PASS",
        "qualification_scope": "PATCHED_PUBLIC_SOURCE_APIS_ONLY",
        "source_lock_sha256": sha(lock_path),
        "report_sha256": sha(report_path),
        "patch_sha256": patch["sha256"],
        "original_failure_retained": "SIGNED_SHIFT_OF_15_BY_28_UBSAN",
        "source_scenarios_per_decode_executable": 1872,
        "source_scenarios_per_query_executable": 936,
        "query_calls_per_executable": 175344,
        "profiles": 3,
        "actual_compiled_dependency_counts": {
            b["source_kind"] + "/" + b["profile"]: len(b["compiled_source_closure"]) for b in builds
        },
        "source_repository_unmodified": True,
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "logical_entries": [93, 113],
        "full_logical_entries_qualified": False,
        "platform": "LINUX_X86_64_SSE4_1",
        "leak_detection": "DISABLED",
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    path = ROOT / "build/source-audits/maskedvbyte-source-current-audit.json"
    try:
        result = audit()
    except Exception as error:
        path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
