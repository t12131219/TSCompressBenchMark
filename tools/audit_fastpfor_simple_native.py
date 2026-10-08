"""Verify actual bounded Simple-9/16 objects, shared tests and injected faults."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

from audit_fastpfor_simple_source import audit as source_audit
from audit_fastpfor_simple_source import require, sha

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/fastpfor_simple"
REPORT = "build/source-audits/fastpfor_simple_native_tests.json"
OPTIONS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ],
}
BASELINE = [
    "-march=x86-64",
    "-mno-ssse3",
    "-mno-sse4.1",
    "-mno-avx",
    "-mno-avx2",
    "-mno-avx512f",
    "-fno-tree-vectorize",
    "-fno-tree-slp-vectorize",
]


def audit(root: Path = ROOT) -> dict:
    def local(name: str) -> Path:
        path = Path(name)
        if path.is_absolute() and path.is_relative_to(ROOT):
            path = path.relative_to(ROOT)
        return path if path.is_absolute() else root / path

    def check(item: dict) -> None:
        require(
            sha(local(item["path"])) == item["sha256"],
            "consumed native file drift: " + item["path"],
        )

    def closure(dependency: dict, items: list[dict]) -> set[str]:
        check(dependency)
        names = shlex.split(
            local(dependency["path"]).read_text().replace("\\\n", " ").split(":", 1)[1]
        )
        actual = {
            str(Path(p).relative_to(ROOT)) if Path(p).is_relative_to(ROOT) else p for p in names
        }
        require(
            {i["path"] for i in items} == actual and len(items) == len(actual),
            "actual compiler dependency universe differs",
        )
        for item in items:
            check(item)
        return actual

    source = source_audit(root)
    report = json.loads((root / REPORT).read_text())
    require(
        report["status"] == "BOUNDED_ABI_MATRIX_AND_FAULT_TESTS_EXECUTED_INDEPENDENT_AUDIT_PENDING"
        and report["source_probe_audit"] == source,
        "native source evidence incomplete/stale",
    )
    require(
        report["driver"]["path"] == COMPONENT + "/tests/run_native_tests.py",
        "native driver substituted",
    )
    check(report["driver"])
    require(
        report["python_sdk"] == report["benchmark_five_layers"] == "PENDING"
        and report["full_logical_entry_qualified"] is False,
        "native tests cannot declare SDK or Benchmark qualification",
    )
    require(
        report["native_cases"] == 91350
        and report["native_executables"] == 3
        and report["native_timing_fault_injection"] == "SAME_SHIPPED_OBJECT_198_CHECKS_PASSED",
        "native coverage summary differs",
    )
    require(
        len(report["builds"]) == 3 and {b["profile"] for b in report["builds"]} == set(OPTIONS),
        "native profile universe incomplete",
    )
    adapter = ROOT / COMPONENT
    dependencies = {}
    expected_commands = []
    for build in report["builds"]:
        profile = build["profile"]
        directory = ROOT / "build/adapters/fastpfor_simple" / profile
        require(
            build == json.loads(local(str(directory / "build-record.json")).read_text()),
            "native build record differs",
        )
        require(
            build["status"] == "PASS"
            and build["upstream_commit"] == "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
            and build["patches"] == []
            and build["runtime_fallback"] is False
            and build["source_isa"] == "BASELINE_X86_64_NO_AUTOVECTORIZATION",
            "native identity/ISA/patch policy differs",
        )
        require(
            build["source_lock_sha256"] == source["source_lock_sha256"], "native source lock stale"
        )
        lock = json.loads((root / COMPONENT / "SOURCE_LOCK.json").read_text())
        require(build["source_files"] == lock["files"], "native source inventory substituted")
        for item in build["source_files"]:
            check(item)
        require(
            {i["path"] for i in build["binding_sources"]}
            == {
                COMPONENT + "/build_native.py",
                COMPONENT + "/SOURCE_LOCK.json",
                COMPONENT + "/native/tscb_fastpfor_simple.cpp",
                "native/include/tscb_adapter_v1.h",
                "native/include/tscb_native_timing.h",
            },
            "binding closure incomplete",
        )
        for item in build["binding_sources"]:
            check(item)
        require(
            build["artifact"] == str((directory / "libtscb_fastpfor_simple.so").relative_to(ROOT)),
            "native library path differs",
        )
        require(sha(local(build["artifact"])) == build["artifact_sha256"], "native library drift")
        require(
            len(build["objects"]) == len(build["dependency_files"]) == 1
            and build["objects"][0]["path"] == str((directory / "shim.o").relative_to(ROOT)),
            "native object universe differs",
        )
        check(build["objects"][0])
        actual = closure(build["dependency_files"][0], build["compiled_source_closure"])
        require(
            {
                COMPONENT + "/native/tscb_fastpfor_simple.cpp",
                "native/include/tscb_adapter_v1.h",
                "native/include/tscb_native_timing.h",
                *(
                    COMPONENT + "/vendor/fastpfor/headers/" + h
                    for h in (
                        "simple9.h",
                        "simple16.h",
                        "codecs.h",
                        "common.h",
                        "util.h",
                        "bitpacking.h",
                        "bitpackinghelpers.h",
                    )
                ),
            }
            <= actual,
            "actual native algorithm/helper closure incomplete",
        )
        require(not any("googletest" in p for p in actual), "test dependency leaked into codec")
        dependencies[profile + "/shim"] = len(actual)
        compile_command = [
            "/usr/bin/g++",
            "-std=c++17",
            "-fPIC",
            "-Wall",
            "-Wextra",
            "-Werror",
            *OPTIONS[profile],
            *BASELINE,
            "-I",
            str(ROOT / "native/include"),
            "-I",
            str(adapter / "vendor/fastpfor/headers"),
            "-MD",
            "-MF",
            str(directory / "shim.d"),
            "-c",
            str(adapter / "native/tscb_fastpfor_simple.cpp"),
            "-o",
            str(directory / "shim.o"),
        ]
        link_command = [
            "/usr/bin/g++",
            *OPTIONS[profile],
            "-shared",
            "-Wl,-z,defs",
            "-Wl,-Bsymbolic-functions",
            str(directory / "shim.o"),
            "-o",
            str(directory / "libtscb_fastpfor_simple.so"),
        ]
        commands = build["commands"]
        require(
            [c["command"] for c in commands]
            == [
                compile_command,
                link_command,
                ["ldd", str(directory / "libtscb_fastpfor_simple.so")],
                ["/usr/bin/g++", "--version"],
            ]
            and all(c["returncode"] == 0 for c in commands),
            "native compile/link recipe differs",
        )
        document = json.loads(local(str(directory / "compile-command.json")).read_text())
        require(
            document["commands"] == [compile_command, link_command]
            and hashlib.sha256(
                json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            == build["compile_commands_sha256"],
            "compile command digest differs",
        )
        for item in build["runtime_dependencies"]:
            check(item)
        symbols = subprocess.run(
            ["nm", "-u", str(local(build["artifact"]))], capture_output=True, text=True, check=True
        ).stdout
        require(
            ("__asan_init" in symbols) is (profile == "sanitizer")
            and ("__ubsan_handle" in symbols) is (profile == "sanitizer"),
            "actual native sanitizer symbols differ",
        )
    by_profile = {b["profile"]: b for b in report["builds"]}
    expected_observations = {
        "tests": {
            "status": "PASS",
            "cases": 30450,
            "variants": 6,
            "input_alignments": 4,
            "all_legal_selectors": True,
            "atomic_failures": True,
            "exact_guard_pages": True,
            "native_timer_toggle_and_accumulation": True,
        },
        "fault_tests": {
            "status": "PASS",
            "checks": 66,
            "allocation_exception_atomicity": True,
            "clock_failure_backward_overflow": True,
            "same_shipped_object": True,
        },
    }
    for group in ("tests", "fault_tests"):
        tests = report[group]
        require(
            len(tests) == 3 and {t["profile"] for t in tests} == set(OPTIONS),
            "native test/fault profile universe incomplete",
        )
        for test in tests:
            profile = test["profile"]
            directory = ROOT / "build/adapters/fastpfor_simple" / profile
            out = ROOT / "build/source-audits/fastpfor-simple-native"
            name = ("shared-" if group == "tests" else "faults-") + profile
            source_name = "abi_qualification.cpp" if group == "tests" else "native_faults.cpp"
            for field, path in (
                ("executable", out / name),
                ("dependency_file", out / (name + ".d")),
                ("test_source", adapter / "tests" / source_name),
            ):
                require(
                    test[field]["path"] == str(path.relative_to(ROOT)),
                    "native test artifact substituted",
                )
                check(test[field])
            actual = closure(test["dependency_file"], test["actual_compiler_closure"])
            require(
                str((adapter / "tests" / source_name).relative_to(ROOT)) in actual,
                "actual native test translation unit missing",
            )
            if group == "tests":
                require(
                    COMPONENT + "/tests/source_guard.cpp" in actual,
                    "actual independent selector oracle missing",
                )
            else:
                require(
                    test["shipped_object"] == by_profile[profile]["objects"][0],
                    "fault tests did not use the shipped object",
                )
                check(test["shipped_object"])
            dependencies[profile + "/" + group] = len(actual)
            flags = [f for f in OPTIONS[profile] if f != "-DNDEBUG"] + [
                "-UNDEBUG",
                "-fno-pie",
                "-no-pie",
            ]
            command = ["/usr/bin/g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", *flags]
            if group == "tests":
                command += [
                    "-march=x86-64",
                    "-fno-tree-vectorize",
                    "-I",
                    str(ROOT / "native/include"),
                    "-I",
                    str(adapter / "vendor/fastpfor/headers"),
                    "-MD",
                    "-MF",
                    str(out / (name + ".d")),
                    str(adapter / "tests" / source_name),
                    "-L",
                    str(directory),
                    "-ltscb_fastpfor_simple",
                    "-Wl,-rpath," + str(directory),
                    "-o",
                    str(out / name),
                ]
            else:
                command += [
                    "-I",
                    str(ROOT / "native/include"),
                    "-MD",
                    "-MF",
                    str(out / (name + ".d")),
                    str(adapter / "tests" / source_name),
                    str(directory / "shim.o"),
                    "-Wl,--wrap=clock_gettime",
                    "-Wl,--wrap=_Znwm",
                    "-o",
                    str(out / name),
                ]
            expected_commands += [command, [str(out / name)]]
            result = test["result"]
            require(
                result["command"] == [str(out / name)]
                and result["returncode"] == 0
                and json.loads(result["stdout"])
                == test["observation"]
                == expected_observations[group],
                "native test/fault output differs or incomplete",
            )
            matches = [c for c in report["commands"] if c["command"] == result["command"]]
            require(matches == [result], "native raw command result differs")
    commands = report["commands"]
    require(
        len(commands) == 12
        and {tuple(c["command"]) for c in commands} == {tuple(c) for c in expected_commands}
        and all(c["returncode"] == 0 for c in commands),
        "native test command universe incomplete",
    )
    for command in commands:
        require(
            command["sanitizer_environment"]
            == {
                "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
            "sanitizer options differ",
        )
    return {
        "status": "PASS",
        "scope": "BOUNDED_UINT28_SIMPLE9_HACKED_SIMPLE16_C_ABI_ONLY",
        "native_report_sha256": sha(root / REPORT),
        "source_probe_audit": source,
        "native_cases": 91350,
        "native_fault_checks": 198,
        "actual_compiler_dependency_counts": dependencies,
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "simple9_original_full_upstream_unit": "PENDING",
        "auditor_sha256": sha(Path(__file__)),
        "auditor_dependency_sha256": sha(root / "tools/audit_fastpfor_simple_source.py"),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/fastpfor_simple_native_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
