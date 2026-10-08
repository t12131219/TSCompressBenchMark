"""Audit bounded LittleIntPacker binaries, compiler closures and same-object faults."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

from audit_littleintpacker_source import audit as audit_source

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/littleintpacker"
REPORT = "build/source-audits/littleintpacker_native_tests.json"
PROFILES = {
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
UNITS = {
    "bitpacking32.c": [],
    "turbobitpacking32.c": [],
    "scpacking32.c": [],
    "bmipacking32.c": ["-mavx2", "-mbmi2"],
    "horizontalpacking32.c": ["-mssse3", "-msse4.1"],
    "util.c": [],
    "shim": [],
}
WRAPS = (
    "clock_gettime",
    "_Znwm",
    "pack32",
    "turbopack32",
    "scpack32",
    "bmipack32",
    "unpack32",
    "turbounpack32",
    "scunpack32",
    "bmiunpack32",
    "horizontalunpack32",
)
EXPECTED_SHARED = {
    "status": "PASS",
    "cases": 94875,
    "variants": 5,
    "widths": 33,
    "input_alignments": 4,
    "auto_width": True,
    "malformed_rejections": 50860,
    "guard_roundtrips": 1485,
    "atomic_failures": True,
    "exact_guard_pages": True,
    "readonly_input": True,
    "native_timer_toggle_and_accumulation": True,
}
EXPECTED_FAULTS = {
    "status": "PASS",
    "checks": 170,
    "allocation_exception_atomicity": True,
    "kernel_exception_atomicity": True,
    "clock_failure_backward_overflow": True,
    "failed_source_calls_timed": True,
    "same_shipped_objects": True,
}


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path = ROOT) -> dict:
    def local(name: str) -> Path:
        path = Path(name)
        if path.is_absolute():
            return root / path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        require(".." not in path.parts, "evidence path escapes workspace")
        return root / path

    def check_file(item: dict, expected: str | None = None) -> None:
        if expected is not None:
            require(item["path"] == expected, "evidence path substituted")
        path = local(item["path"])
        require(
            path.is_file() and sha(path) == item["sha256"], "consumed file drift: " + item["path"]
        )

    def check_closure(item: dict, items: list[dict]) -> set[str]:
        check_file(item)
        names = shlex.split(local(item["path"]).read_text().replace("\\\n", " ").split(":", 1)[1])
        expected = {
            str(Path(name).relative_to(ROOT)) if Path(name).is_relative_to(ROOT) else name
            for name in names
        }
        require(
            len(items) == len(expected) and {i["path"] for i in items} == expected,
            "actual compiler dependency omitted/substituted",
        )
        for dependency in items:
            check_file(dependency)
        return expected

    document = json.loads(local(REPORT).read_text())
    require(
        document["status"]
        == "BOUNDED_ABI_AND_SAME_OBJECT_FAULTS_EXECUTED_INDEPENDENT_AUDIT_PENDING",
        "native executions incomplete",
    )
    require(
        document["bounded_abi"] == "INDEPENDENT_AUDIT_PENDING"
        and document["python_sdk"] == document["benchmark_five_layers"] == "PENDING"
        and document["full_logical_entries_qualified"] is False,
        "native evidence cannot qualify SDK/Benchmark/full entry",
    )
    require(
        document["leak_sanitizer"] == "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        "LeakSanitizer scope inflated",
    )
    source = audit_source(root)
    require(document["source_audit"] == source, "recorded source audit differs from current source")
    check_file(document["driver"], COMPONENT + "/tests/run_native_tests.py")
    expected_sources = [
        COMPONENT + "/tests/run_native_tests.py",
        COMPONENT + "/build_native.py",
        COMPONENT + "/native/tscb_littleintpacker.cpp",
        COMPONENT + "/tests/abi_qualification.cpp",
        COMPONENT + "/tests/native_faults.cpp",
        "native/include/tscb_adapter_v1.h",
        "native/include/tscb_native_timing.h",
    ]
    require(
        len(document["source_snapshot"]) == len(document["retained_source_copies"]) == 7,
        "execution source snapshot incomplete",
    )
    for item, copy, name in zip(
        document["source_snapshot"],
        document["retained_source_copies"],
        expected_sources,
        strict=True,
    ):
        check_file(item, name)
        check_file(copy, "build/source-audits/littleintpacker-native/executed-sources/" + name)
        require(item["sha256"] == copy["sha256"], "executed source copy differs")
    require(
        len(document["builds"]) == len(document["tests"]) == len(document["fault_tests"]) == 3,
        "build/shared/fault profile universe incomplete",
    )
    expected_test_commands = []
    closure_counts = {}
    lock_path, patch_path = COMPONENT + "/SOURCE_LOCK.json", COMPONENT + "/PATCH_LOCK.json"
    lock, patch_lock = (
        json.loads(local(lock_path).read_text()),
        json.loads(local(patch_path).read_text()),
    )
    for index, (profile, flags) in enumerate(PROFILES.items()):
        holder = document["builds"][index]
        directory = "build/adapters/littleintpacker/" + profile
        check_file(holder["record"], directory + "/build-record.json")
        build = json.loads(local(holder["record"]["path"]).read_text())
        require(
            holder["build"] == build
            and build["profile"] == profile
            and build["status"] == "PASS"
            and build["source_audit"] == source,
            "actual build/record differs",
        )
        require(
            build["upstream_commit"] == lock["commit"]
            and build["upstream_repository"] == lock["repository"]
            and build["source_files"] == lock["files"]
            and build["source_lock_sha256"] == sha(local(lock_path))
            and build["patch_lock_sha256"] == sha(local(patch_path))
            and build["patches"] == [patch_lock["patch"]]
            and build["runtime_fallback"] is False
            and build["full_logical_entries_qualified"] is False,
            "native build provenance or fallback changed",
        )
        expected_binding = [
            COMPONENT + "/build_native.py",
            lock_path,
            patch_path,
            "tools/audit_littleintpacker_source.py",
            COMPONENT + "/native/tscb_littleintpacker.cpp",
            "native/include/tscb_adapter_v1.h",
            "native/include/tscb_native_timing.h",
        ]
        require(
            [i["path"] for i in build["binding_sources"]] == expected_binding,
            "binding closure incomplete",
        )
        for item in build["binding_sources"]:
            check_file(item)
        generated = directory + "/generated"
        hashes = {i["upstream_path"]: i["sha256"] for i in lock["files"]}
        hashes.update({i["upstream_path"]: i["patched_sha256"] for i in patch_lock["changes"]})
        require(
            len(build["generated_sources"]) == len(hashes), "generated build closure incomplete"
        )
        for item, (name, digest) in zip(build["generated_sources"], hashes.items(), strict=True):
            check_file(item, generated + "/" + name)
            require(
                item["sha256"] == digest, "compiled generated source differs from audited patch"
            )
        commands = [
            [
                "/usr/bin/patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(ROOT / generated),
                "-i",
                str(ROOT / patch_lock["patch"]["path"]),
            ]
        ]
        require(
            len(build["translation_units"]) == len(build["objects"]) == 7,
            "shipped object universe incomplete",
        )
        for unit, shipped, (name, isa) in zip(
            build["translation_units"], build["objects"], UNITS.items(), strict=True
        ):
            cpp = name == "shim"
            source_name = (
                COMPONENT + "/native/tscb_littleintpacker.cpp"
                if cpp
                else generated + "/src/" + name
            )
            obj, dep = directory + "/" + name + ".o", directory + "/" + name + ".d"
            for field, path in (("source", source_name), ("object", obj), ("dependency", dep)):
                check_file(unit[field], path)
            require(
                shipped == unit["object"] and unit["required_isa_flags"] == isa,
                "shipped object/ISA substituted",
            )
            command = [
                "/usr/bin/g++" if cpp else "/usr/bin/gcc",
                "-std=c++17" if cpp else "-std=c99",
                "-fPIC",
                "-Wall",
                "-Wextra",
                *(["-Werror"] if cpp else []),
                *flags,
                *BASELINE,
                *isa,
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(ROOT / generated / "include"),
                "-MD",
                "-MF",
                str(ROOT / dep),
                "-c",
                str(ROOT / source_name),
                "-o",
                str(ROOT / obj),
            ]
            require(unit["command"] == command, "native compiler flags/ISA/source differ")
            actual = check_closure(unit["dependency"], unit["compiler_closure"])
            require(source_name in actual, "compiled translation unit missing")
            commands.append(command)
        library = directory + "/libtscb_littleintpacker.so"
        check_file({"path": build["artifact"], "sha256": build["artifact_sha256"]}, library)
        commands.append(
            [
                "/usr/bin/g++",
                *flags,
                "-shared",
                "-Wl,-z,defs",
                "-Wl,-Bsymbolic-functions",
                *[str(ROOT / item["path"]) for item in build["objects"]],
                "-o",
                str(ROOT / library),
            ]
        )
        compile_doc = {
            "schema_version": "tscb.compile-command.v1",
            "algorithm": "littleintpacker-source",
            "profile": profile,
            "commands": commands,
        }
        compile_bytes = json.dumps(compile_doc, sort_keys=True, separators=(",", ":")).encode()
        require(
            local(directory + "/compile-command.json").read_bytes() == compile_bytes + b"\n"
            and hashlib.sha256(compile_bytes).hexdigest() == build["compile_commands_sha256"],
            "compile command document differs",
        )
        commands += [
            ["ldd", str(ROOT / library)],
            ["/usr/bin/g++", "--version"],
            ["/usr/bin/gcc", "--version"],
        ]
        require(
            [r["command"] for r in build["commands"]] == commands
            and all(r["returncode"] == 0 for r in build["commands"]),
            "raw build command ledger incomplete",
        )
        require(
            build["commands"][-3]["stdout"] == build["ldd"]
            and build["commands"][-2]["stdout"].splitlines()[0] == build["compiler"]
            and build["commands"][-1]["stdout"].splitlines()[0] == build["c_compiler"],
            "runtime/compiler observation differs from raw ledger",
        )
        actual_runtime = {
            str(Path(p).resolve())
            for p in build["ldd"].split()
            if p.startswith("/") and Path(p).is_file()
        }
        require(
            len(build["runtime_dependencies"]) == len(actual_runtime)
            and {i["path"] for i in build["runtime_dependencies"]} == actual_runtime,
            "runtime library closure omitted",
        )
        for item in build["runtime_dependencies"]:
            check_file(item)
        symbols = subprocess.run(
            ["/usr/bin/nm", "-D", "--defined-only", str(local(library))],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        for symbol in (*WRAPS[2:], "tscb_get_native_timing", "tscb_get_telemetry_json"):
            require(
                any(line.endswith(" " + symbol) for line in symbols.splitlines()),
                "actual shared API export missing",
            )
        test_flags = [flag for flag in flags if flag != "-DNDEBUG"] + [
            "-UNDEBUG",
            "-fno-pie",
            "-no-pie",
        ]
        for key, target, filename, expected in (
            ("tests", "shared", "abi_qualification.cpp", EXPECTED_SHARED),
            ("fault_tests", "faults", "native_faults.cpp", EXPECTED_FAULTS),
        ):
            execution = document[key][index]
            exe = f"build/source-audits/littleintpacker-native/{target}-{profile}"
            dep = exe + ".d"
            source_name = COMPONENT + "/tests/" + filename
            require(
                execution["profile"] == profile
                and execution["shipped_objects"] == build["objects"]
                and execution["shipped_artifact"]
                == {"path": library, "sha256": build["artifact_sha256"]},
                "fault/shared execution uses different shipped objects/library",
            )
            for field, path in (("source", source_name), ("executable", exe), ("dependency", dep)):
                check_file(execution[field], path)
            actual = check_closure(execution["dependency"], execution["compiler_closure"])
            require(source_name in actual, "actual test source missing from compiler closure")
            closure_counts[profile + "_" + target] = len(actual)
            command = [
                "/usr/bin/g++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                *test_flags,
                *BASELINE,
                "-I",
                str(ROOT / "native/include"),
                "-MD",
                "-MF",
                str(ROOT / dep),
                str(ROOT / source_name),
            ]
            if target == "shared":
                command += [
                    "-L",
                    str(ROOT / directory),
                    "-ltscb_littleintpacker",
                    "-Wl,-rpath," + str(ROOT / directory),
                ]
            else:
                command += [str(ROOT / item["path"]) for item in build["objects"]]
                command += ["-Wl,--wrap=" + name for name in WRAPS]
            command += ["-o", str(ROOT / exe)]
            matches = [r for r in document["commands"] if r["command"] == command]
            require(
                len(matches) == 1 and matches[0]["returncode"] == 0,
                "test compile command absent/changed",
            )
            expected_test_commands += [matches[0], execution["result"]]
            result = execution["result"]
            require(
                result["command"] == [str(ROOT / exe)]
                and result["returncode"] == 0
                and execution["observation"] == json.loads(result["stdout"]) == expected,
                "complete native matrix/fault observation differs",
            )
            expected_stderr = (
                ""
                if target == "faults"
                else "".join(
                    f"ABI_VARIANT_DONE {name} cases={18975 * (i + 1)}\n"
                    for i, name in enumerate(("PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL"))
                )
            )
            require(
                result["stderr"] == expected_stderr,
                "variant execution trace incomplete or sanitizer errors",
            )
            for r in (matches[0], result):
                require(
                    r["sanitizer_environment"]
                    == {
                        "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                    },
                    "sanitizer environment changed",
                )
            if profile == "sanitizer":
                undefined = subprocess.run(
                    ["/usr/bin/nm", "-u", str(local(exe))],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout
                require(
                    "__asan_init" in undefined and "__ubsan_handle" in undefined,
                    "actual executable sanitizer missing",
                )
            if target == "faults":
                defined = subprocess.run(
                    ["/usr/bin/nm", "--defined-only", str(local(exe))],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                ).stdout
                require(
                    all("__wrap_" + name in defined for name in WRAPS),
                    "actual fault wrappers missing",
                )
    require(
        document["commands"] == expected_test_commands,
        "raw native command ledger missing/duplicated/changed",
    )
    require(
        document["native_cases"] == 284625
        and document["malformed_rejections"] == 152580
        and document["guard_roundtrips"] == 4455
        and document["native_fault_checks"] == 510,
        "native totals inflated/incomplete",
    )
    return {
        "status": "PASS",
        "scope": "UINT32_FIXED_AND_AUTO_WIDTH_FIVE_ORIGINAL_API_PAIRS_BOUNDED_ABI",
        "bounded_abi": "QUALIFIED",
        "native_cases": 284625,
        "malformed_rejections": 152580,
        "guard_roundtrips": 4455,
        "native_fault_checks": 510,
        "source_audit": source,
        "compiler_closure_counts": closure_counts,
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        "native_report_sha256": sha(local(REPORT)),
    }


if __name__ == "__main__":
    result = audit()
    result["auditor"] = {
        "path": "tools/audit_littleintpacker_native.py",
        "sha256": sha(Path(__file__)),
    }
    (ROOT / "build/source-audits/littleintpacker_native_current_audit.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
