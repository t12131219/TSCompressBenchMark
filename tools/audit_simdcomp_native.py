"""Revalidate SIMDComp's actual bounded ABI binaries, compiler closure and faults."""

from __future__ import annotations

import hashlib
import itertools
import json
import runpy
import subprocess
from pathlib import Path

from audit_simdcomp_avx2 import audit as source_audit
from audit_simdcomp_source import PROFILES, ROOT, dependency_paths, read, require, sha


def audit(root: Path = ROOT) -> dict:
    source = source_audit(root)

    def local(filename: str) -> Path:
        path = Path(filename)
        return (
            root / path.relative_to(ROOT)
            if path.is_absolute() and path.is_relative_to(ROOT)
            else root / path
        )

    def check(item: dict) -> None:
        require(sha(local(item["path"])) == item["sha256"], "native file drift: " + item["path"])

    report_path = root / "build/source-audits/simdcomp_native_tests.json"
    report = read(report_path)
    require(
        report["status"] == "PASS"
        and report["schema_version"] == "tscb.simdcomp-native-tests.v1"
        and report["source_audit"] == source,
        "native source evidence changed or qualification did not pass",
    )
    for field in ("driver", "build_driver", "contract", "source_lock", "source_auditor"):
        check(report[field])
    require(
        report["cases_per_executable"] == 31878
        and report["benchmark_five_layers"] == "NOT_CLAIMED"
        and report["python_sdk"] == "PENDING"
        and report["leak_detection"] == "DISABLED"
        and report["cpu_affinity"] == [2],
        "native qualification scope differs",
    )
    recipe = runpy.run_path(str(ROOT / "adapters/simdcomp/build_native.py"))
    test_driver = runpy.run_path(str(ROOT / "adapters/simdcomp/tests/run_native_tests.py"))
    lock = read(root / "adapters/simdcomp/SOURCE_LOCK.json")
    require(
        len(report["builds"]) == 3 and {b["profile"] for b in report["builds"]} == set(PROFILES),
        "native build matrix incomplete",
    )
    builds, counts = {}, {}
    for qualified in report["builds"]:
        for item in (qualified["record"], qualified["library"], *qualified["objects"]):
            check(item)
        build = read(local(qualified["record"]["path"]))
        profile = build["profile"]
        builds[profile] = build
        require(
            build["status"] == "PASS"
            and build["algorithm"] == "simdcomp-source-u32"
            and build["runtime_fallback"] is False
            and build["source_files"] == lock["files"]
            and build["source_lock_sha256"] == sha(root / "adapters/simdcomp/SOURCE_LOCK.json"),
            "native source identity/fallback differs",
        )
        require(
            build["artifact_sha256"] == sha(local(build["artifact"]))
            and qualified["library"]["sha256"] == build["artifact_sha256"]
            and qualified["objects"] == build["objects"],
            "native qualified binary/object differs",
        )
        require(
            build["shim_isa"] == "BASELINE_X86_64_NO_AUTOVECTORIZATION"
            and build["source_isa"] == "SSE4_1_AND_SEPARATE_AVX2_OBJECTS_NO_AVX512",
            "native actual ISA declaration differs",
        )
        require(
            {Path(p["path"]).stem for p in build["objects"]} == set(recipe["OBJECT_NAMES"])
            and len(build["objects"]) == 9,
            "native object universe differs",
        )
        for field in (
            "binding_sources",
            "compiled_source_closure",
            "objects",
            "patches",
            "runtime_dependencies",
            "generated_source_files",
        ):
            for item in build[field]:
                check(item)
        require(
            [p["sha256"] for p in build["patches"]] == [p["sha256"] for p in source["patches"]],
            "native patch series differs",
        )
        directory = local(qualified["record"]["path"]).parent
        command_doc = read(directory / "compile-command.json")
        canonical = json.dumps(command_doc, sort_keys=True, separators=(",", ":")).encode()
        require(
            hashlib.sha256(canonical).hexdigest() == build["compile_commands_sha256"],
            "native actual compile commands drift",
        )
        require(
            all(
                any(o["command"] == c and o["returncode"] == 0 for o in build["commands"])
                for c in command_doc["commands"]
            ),
            "native build command observations absent",
        )
        compiled = [c for c in command_doc["commands"] if "-c" in c]
        require(len(compiled) == 9, "native translation unit universe differs")
        for command in compiled:
            name = Path(command[command.index("-o") + 1]).stem
            require(
                all(f in command for f in ("-MD", "-march=x86-64", "-mno-avx512f"))
                and "-march=native" not in command
                and "-mavx512f" not in command,
                "native ISA/closure flags differ",
            )
            expected = (
                [
                    "-mno-avx",
                    "-mno-avx2",
                    "-mno-ssse3",
                    "-mno-sse4.1",
                    "-fno-tree-vectorize",
                    "-fno-tree-slp-vectorize",
                ]
                if name == "shim"
                else ["-mavx2"]
                if name in ("avxbitpacking", "avx2_bridge")
                else ["-msse4.1", "-mno-avx", "-mno-avx2"]
            )
            require(all(f in command for f in expected), "native separate ISA object flags differ")
            if profile == "sanitizer":
                require(
                    "-fsanitize=address,undefined" in command
                    and "-fno-sanitize-recover=all" in command,
                    "native object sanitizer missing",
                )
        actual = set().union(*(dependency_paths(p, ROOT) for p in directory.glob("*.d")))
        require(
            actual == {local(p["path"]).resolve() for p in build["compiled_source_closure"]},
            "native compiler dependency universe differs",
        )
        counts[profile] = len(actual)
        for item in lock["files"]:
            generated = directory / "patched-source" / item["upstream_path"]
            tested = (
                root / "build/source-audits/simdcomp-avx2/patched-source" / item["upstream_path"]
            )
            require(sha(generated) == sha(tested), "native tested patched source differs")
    universe = set(
        itertools.product(("shared", "instrumented", "pointer_regression"), PROFILES)
    ) | {("shared_timer_overflow", None)}
    require(
        len(report["tests"]) == 10
        and {(t["kind"], t.get("profile")) for t in report["tests"]} == universe,
        "native test matrix incomplete",
    )
    for test in report["tests"]:
        check(test["source"])
        check(test["executable"])
        require(
            test["returncode"] == 0 and test["command"] == [str(ROOT / test["executable"]["path"])],
            "native test result/command differs",
        )
        require(
            any(
                all(
                    c[k] == test[k]
                    for k in ("command", "returncode", "stdout", "stderr", "sanitizer_environment")
                )
                for c in report["commands"]
            ),
            "native runtime command observation missing",
        )
        if test["kind"] == "shared_timer_overflow":
            require(
                test["stdout"] == test["stderr"] == "",
                "shared timer overflow assertion diagnostics",
            )
            continue
        command = test["compile_command"]
        require(
            any(c["command"] == command and c["returncode"] == 0 for c in report["commands"]),
            "native compilation observation missing",
        )
        require(
            all(f in command for f in ("-UNDEBUG", "-MD", "-march=x86-64", "-mno-avx"))
            and "-DNDEBUG" not in command,
            "native test assertions/ISA/closure disabled",
        )
        if test["profile"] == "sanitizer":
            require(
                "-fsanitize=address,undefined" in command
                and "-fno-sanitize-recover=all" in command,
                "native test sanitizer missing",
            )
        check(test["dependency_file"])
        for item in test["compiled_test_closure"]:
            check(item)
        require(
            dependency_paths(local(test["dependency_file"]["path"]), ROOT)
            == {local(p["path"]).resolve() for p in test["compiled_test_closure"]},
            "native test dependency universe differs",
        )
        build = builds[test["profile"]]
        if test["kind"] == "shared":
            require(
                "-ltscb_simdcomp_u32" in command and "-DINSTRUMENTED" not in command,
                "shipped shared ABI not tested",
            )
            observed = subprocess.run(
                ["ldd", str(local(test["executable"]["path"]))],
                capture_output=True,
                text=True,
                timeout=30,
            )
            require(
                observed.returncode == 0
                and any(
                    Path(p).resolve() == (ROOT / build["artifact"]).resolve()
                    for p in observed.stdout.split()
                    if p.startswith("/")
                ),
                "native shared test loads another binary",
            )
        else:
            require(
                {local(p) for p in command if p.endswith(".o")}
                == {local(p["path"]) for p in build["objects"]},
                "same compiled objects were not tested",
            )
            expected = (
                test_driver["WRAPS"]
                if test["kind"] == "instrumented"
                else test_driver["WRAPS"][5:11]
            )
            require(
                all("-Wl,--wrap=" + name in command for name in expected),
                "native source-route/fault wrapper missing",
            )
        if test["kind"] == "pointer_regression":
            require(
                test["stdout"].endswith(
                    "SIMDComp NULL-return qualification: 6/6 rejected atomically\n"
                ),
                "native NULL-return regression missing",
            )
        else:
            expected = (
                "SIMDComp bounded ABI PASS: 31878 scalar-wire cases; 9 configurations; "
                "33 widths; 23 lengths; 8 alignments; 4 D1/FOR seeds; guard pages; "
                "malformed; lifecycle; exact accounting\n"
            )
            if test["kind"] == "instrumented":
                expected = (
                    "SIMDComp same-object allocator/clock/API-length/API-route faults PASS\n"
                    + expected
                )
                require("-DINSTRUMENTED" in command, "native fault test instrumentation absent")
            require(test["stdout"] == expected, "native scalar wire/guard/fault coverage differs")
    initial_path = root / "build/source-audits/simdcomp-native-initial/report.json"
    initial = read(initial_path)
    require(
        initial["status"] == "OBSERVED_FAILURES"
        and initial["returncode"] == 1
        and initial["stdout"].endswith(
            "SIMDComp NULL-return qualification: 0/6 rejected atomically\n"
        ),
        "original ABI NULL-return failure evidence missing",
    )
    for item in initial["files"]:
        check(item)
    return {
        "status": "PASS",
        "qualification_scope": "BOUNDED_UINT32_SSE4_1_AND_AVX2_ABI_ONLY",
        "source_report_sha256": source["source_report_sha256"],
        "native_report_sha256": sha(report_path),
        "initial_abi_failure_report_sha256": sha(initial_path),
        "cases_per_profile_and_linkage": 31878,
        "build_dependency_counts": counts,
        "original_abi_fault_paths_retained": 6,
        "platform": "LINUX_X86_64_SSE4_1_AVX2",
        "leak_detection": "DISABLED",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "checked_int64_timestamp": "PENDING",
        "full_logical_entry_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/simdcomp_native_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
