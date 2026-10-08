"""Audit actual SIMDComp AVX2 builds, failures, scalar wire and patch replay."""

from __future__ import annotations

import itertools
import json
import runpy
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from audit_simdcomp_source import COUNTS, PROFILES, ROOT, dependency_paths, read, require, sha

MODES = (*COUNTS, "avx2")


def audit(root: Path = ROOT) -> dict:
    sse = runpy.run_path(str(ROOT / "tools/audit_simdcomp_source.py"))["audit"](root)
    require(sse["status"] == "PASS", "SSE source prerequisites failed")

    def local(filename: str) -> Path:
        path = Path(filename)
        return root / path.relative_to(ROOT) if path.is_relative_to(ROOT) else path

    def check(item: dict) -> None:
        require(sha(local(item["path"])) == item["sha256"], "AVX2 file drift: " + item["path"])

    report_path = root / "build/source-audits/simdcomp_avx2_source_tests.json"
    report = read(report_path)
    require(
        report["status"] == "OBSERVATIONS_COMPLETE"
        and report["schema_version"] == "tscb.simdcomp-avx2-source-tests.v1"
        and report["source_lock_sha256"] == sse["source_lock_sha256"]
        and report["actual_isa"] == "AVX2_WITH_SSE_PUBLIC_API_PATHS_NO_AVX512"
        and report["benchmark_adapter_qualification"] == "NOT_CLAIMED"
        and report["cpu_affinity"] == [2]
        and report["leak_detection"] == "DISABLED",
        "AVX2 source provenance differs",
    )
    for field in ("driver", "guard", "sse_guard", "source_auditor"):
        check(report[field])
    expected_patches = [
        *sorted((root / "adapters/simdcomp/patches").glob("*.patch")),
        root / "adapters/simdcomp/patches/avx2/0001-zero-width-unpack-byte-count.patch",
    ]
    require(
        [local(p["path"]) for p in report["patches"]] == expected_patches,
        "AVX2 patch universe differs",
    )
    for item in report["patches"]:
        check(item)
    require(
        len(report["builds"]) == 6
        and {(b["source_kind"], b["profile"]) for b in report["builds"]}
        == set(itertools.product(("original", "patched"), PROFILES)),
        "AVX2 build matrix incomplete",
    )
    dependency_counts = {}
    for build in report["builds"]:
        for item in [
            build["compile_commands"],
            build["library"],
            build["guard_executable"],
            *build["objects"],
            *build["compiled_source_closure"],
        ]:
            check(item)
        commands = read(local(build["compile_commands"]["path"]))
        require(
            len(commands) == len(build["objects"]) == 11, "AVX2 compiled target universe differs"
        )
        for command in commands:
            flags = shlex.split(command["command"])
            require(
                all(f in flags for f in ("-march=x86-64", "-mavx2", "-mno-avx512f", "-UNDEBUG"))
                and not any(f in flags for f in ("-DNDEBUG", "-march=native", "-mavx512f")),
                "AVX2 actual ISA/assertion flags differ",
            )
            if build["profile"] == "sanitizer":
                require(
                    "-fsanitize=address,undefined" in flags
                    and "-fno-sanitize-recover=all" in flags,
                    "AVX2 sanitizer missing",
                )
        directory = local(build["library"]["path"]).parent
        dependencies = [*directory.rglob("*.o.d"), directory / "avx2-source-guard.d"]
        actual = set().union(*(dependency_paths(p, directory) for p in dependencies))
        require(
            actual == {local(p["path"]).resolve() for p in build["compiled_source_closure"]},
            "AVX2 compiler dependency closure differs",
        )
        dependency_counts[build["source_kind"] + "/" + build["profile"]] = len(actual)
        observed = [
            c
            for c in report["commands"]
            if c["command"][-2:] == ["-o", build["guard_executable"]["path"]]
        ]
        require(
            len(observed) == 1 and observed[0]["returncode"] == 0,
            "AVX2 guard compile observation missing",
        )
        flags = observed[0]["command"]
        require(
            all(
                f in flags
                for f in (
                    "-MD",
                    "-march=x86-64",
                    "-mavx2",
                    "-mno-avx512f",
                    "-UNDEBUG",
                    report["guard"]["path"],
                    build["library"]["path"],
                )
            ),
            "AVX2 guard flags/library differ",
        )
        if build["profile"] == "sanitizer":
            require(
                "-fsanitize=address,undefined" in flags and "-fno-sanitize-recover=all" in flags,
                "AVX2 guard sanitizer missing",
            )
        configuration = [
            c
            for c in report["commands"]
            if c["command"][:1] == ["cmake"]
            and "-B" in c["command"]
            and local(c["command"][c["command"].index("-B") + 1]) == directory
        ]
        require(
            len(configuration) == 1
            and configuration[0]["returncode"] == 0
            and all(
                f in configuration[0]["command"]
                for f in ("-DSIMDCOMP_NATIVE=OFF", "-DSIMDCOMP_BUILD_BENCHMARKS=OFF")
            ),
            "AVX2 configuration enabled native tuning or benchmark downloads",
        )
    universe = set(
        itertools.product(
            ("original", "patched"), PROFILES, ("unit", "unit_chars", "example", *MODES)
        )
    )
    require(
        len(report["tests"]) == 72
        and {(t["source_kind"], t["profile"], t["mode"]) for t in report["tests"]} == universe,
        "AVX2 test matrix incomplete",
    )
    failed_count = 0
    for test in report["tests"]:
        check(test["executable"])
        upstream = test["mode"] in ("unit", "unit_chars", "example")
        require(test["kind"] == ("upstream" if upstream else "guard"), "AVX2 test kind differs")
        expected_command = [test["executable"]["path"]] + ([] if upstream else [test["mode"]])
        require(
            test["command"] == expected_command
            and any(
                all(c[k] == test[k] for k in ("command", "returncode", "stdout", "stderr"))
                for c in report["commands"]
            ),
            "AVX2 runtime observation missing",
        )
        require(
            test["sanitizer_environment"]
            == {
                "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
            "AVX2 sanitizer environment differs",
        )
        failed = test["source_kind"] == "original" and (
            test["mode"] in ("query-d1", "query-for", "set-d1", "set-for", "avx2")
            or test["mode"] == "set-plain"
            and test["profile"] == "sanitizer"
        )
        require(
            (test["returncode"] != 0) == failed, "AVX2 original failure/patched success differs"
        )
        failed_count += failed
        if test["mode"] == "avx2":
            require(
                "width=0 count=256: AVX2 decoded values" in test["stderr"]
                if failed
                else test["stdout"]
                == (
                    "SIMDComp source avx2 cases PASS: 1584; 33 widths; "
                    "6 patterns; 8 alignments; scalar wire\n"
                ),
                "AVX2 zero-width/scalar wire evidence missing",
            )
        elif not upstream and not failed:
            cases, calls = COUNTS[test["mode"]]
            require(
                test["stdout"]
                == (
                    f"SIMDComp source {test['mode']} cases PASS: {cases}; "
                    f"query calls: {calls}; exact guard pages; scalar wire\n"
                ),
                "AVX2 SSE API coverage differs",
            )
        elif upstream and test["mode"] == "unit":
            require("All tests OK!" in test["stdout"], "AVX2 upstream success missing")
        elif upstream and test["mode"] == "unit_chars":
            require("Code looks good." in test["stdout"], "AVX2 upstream success missing")
        elif failed:
            expected = (
                "search lower bound position"
                if test["mode"] == "query-d1"
                else "shift exponent 32"
                if test["profile"] == "sanitizer" and test["mode"] != "query-for"
                else "mutation scalar wire differs"
            )
            if test["mode"] == "query-for":
                require(test["returncode"] in (-6, -11), "AVX2 original guard-page failure missing")
                if test["profile"] == "sanitizer":
                    require(
                        all(
                            s in test["stderr"]
                            for s in ("AddressSanitizer", "simdselectFOR", "READ memory access")
                        ),
                        "AVX2 original ASan protected read missing",
                    )
            else:
                require(expected in test["stderr"], "AVX2 original defect observation missing")
    require(
        failed_count == report["failed_test_count"] == 16, "AVX2 original failure count differs"
    )
    lock = read(root / "adapters/simdcomp/SOURCE_LOCK.json")
    with tempfile.TemporaryDirectory(prefix="tscb-simdcomp-avx2-") as directory:
        scratch = Path(directory)
        for item in lock["files"]:
            target = scratch / item["upstream_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(local(item["path"]), target)
        for patch in expected_patches:
            result = subprocess.run(
                ["patch", "--batch", "--forward", "-p1", "-d", str(scratch), "-i", str(patch)],
                capture_output=True,
                timeout=30,
            )
            require(result.returncode == 0, "AVX2 patch replay failed")
        changed = set()
        for item in lock["files"]:
            tested = (
                root / "build/source-audits/simdcomp-avx2/patched-source" / item["upstream_path"]
            )
            require(
                sha(tested) == sha(scratch / item["upstream_path"]),
                "AVX2 tested patched source differs",
            )
            if sha(tested) != item["sha256"]:
                changed.add(item["upstream_path"])
        require(
            changed
            == {
                "src/avxbitpacking.c",
                "src/simdbitpacking.c",
                "src/simdfor.c",
                "src/simdpackedsearch.c",
                "src/simdintegratedbitpacking.c",
            },
            "AVX2 patch changed unexpected source",
        )
    initial_path = root / "build/source-audits/simdcomp_avx2_source_initial_tests.json"
    initial = read(initial_path)
    archive = root / "build/source-audits/simdcomp-avx2-initial"
    require(
        initial["failed_test_count"] == 19 and len(initial["patches"]) == 3,
        "initial unpatched AVX2 failures not retained",
    )
    require(
        sha(archive / "qualify_simdcomp_avx2.py") == initial["driver"]["sha256"]
        and sha(archive / "source_avx2_guard.c") == initial["guard"]["sha256"],
        "initial AVX2 harness drift",
    )
    for profile in PROFILES:
        test = next(
            t
            for t in initial["tests"]
            if t["source_kind"] == "patched" and t["profile"] == profile and t["mode"] == "avx2"
        )
        require(
            test["returncode"] != 0
            and "width=0 count=256: AVX2 decoded values" in test["stderr"]
            and sha(archive / "patched" / profile / "avx2-source-guard")
            == test["executable"]["sha256"],
            "initial AVX2 defect executable missing",
        )
    return {
        "status": "PASS",
        "qualification_scope": "PATCHED_AVX2_AND_SSE_PUBLIC_SOURCE_APIS_ONLY",
        "source_lock_sha256": sse["source_lock_sha256"],
        "source_report_sha256": sha(report_path),
        "initial_report_sha256": sha(initial_path),
        "patches": report["patches"],
        "actual_compiled_dependency_counts": dependency_counts,
        "original_failures_retained": 16,
        "avx2_cases_per_profile": 1584,
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/simdcomp_avx2_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
