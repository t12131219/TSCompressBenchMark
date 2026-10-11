"""Verify saved compiler/runtime closures and run finite native ABI tests."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

from tscompbench.adapters.build_evidence import verified_build_dependencies
from tscompbench.adapters.runtime_evidence import _reject_interposition, _standalone

ROOT = Path(__file__).resolve().parents[1]


def entry(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def execute(command: list[str]) -> dict:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        check=False,
        env=dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        raise RuntimeError(f"native test failed: {command}\n{result.stdout}")
    return {"command": command, "returncode": result.returncode, "output": result.stdout}


def native_test(source: Path, executable: Path, command: list[str], scope: str) -> dict:
    compiled = execute(command)
    runtime = _standalone(executable)
    run = execute([str(executable)])
    if _standalone(executable) != runtime:
        raise RuntimeError(f"native executable runtime changed during qualification: {executable}")
    return {
        "scope": scope,
        "source": entry(source),
        "compile": compiled,
        "run": run,
        "executable": entry(executable),
        "runtime_dependencies": runtime,
        "runtime_resolution_scope": (
            "LDD_SELECTED_FOR_SEPARATE_NATIVE_EXECUTABLE_NOT_PROC_MAP_TRACE"
        ),
    }


def qualify(build_root: Path, report_root: Path, expected_record_count: int) -> dict:
    _reject_interposition()
    report_root.mkdir(parents=True, exist_ok=False)
    records = sorted(build_root.glob("*/*/build-record.json"))
    if expected_record_count <= 0 or len(records) != expected_record_count:
        raise RuntimeError(f"expected {expected_record_count} build records, found {len(records)}")
    tests = {
        "snappy-raw": ("snappy_raw/tests/abi_smoke.cc", []),
        "lzss-raw": ("lzss_raw/tests/test_decoder_contract.cc", []),
        "lzsse2-raw": ("lzsse2_raw/tests/abi_smoke.cc", []),
        "lzsse8-raw": ("lzsse2_raw/tests/abi_smoke.cc", []),
        "deflate-zlib": ("deflate_zlib/tests/abi_smoke.c", []),
        "brotli-stream": ("brotli_stream/tests/abi_smoke.c", []),
        "xz-stream": ("xz_stream/tests/abi_smoke.c", []),
        "bzip2-stream": ("bzip2_stream/tests/abi_smoke.c", []),
        "alp": ("alp/tests/abi_smoke.cc", ["-DTSCB_ALP_RD=0"]),
        "alp-rd": ("alp/tests/abi_smoke.cc", ["-DTSCB_ALP_RD=1"]),
        "serf-qt": ("serf/tests/abi_smoke.cc", ["-DSMOKE_XOR=0"]),
        "serf-xor": ("serf/tests/abi_smoke.cc", ["-DSMOKE_XOR=1"]),
        "neats-lossless-i64": ("neats/tests/abi_smoke.cc", ["-DTSCB_TEST_NEATS=1"]),
        "leats-lossless-i64": ("neats/tests/abi_smoke.cc", ["-DTSCB_TEST_NEATS=0"]),
        "zfp-accuracy-1d": ("zfp/tests/abi_smoke.c", []),
        "sprintz-fire-huff0": ("sprintz/tests/sprintz_fire_huff0_test.cc", []),
    }
    lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    for algorithm, package in lock["algorithms"].items():
        tests[algorithm] = (
            "rewrite_lossless/tests/qualification.cc",
            [f"-DTSCB_REWRITE_KIND={package['kind']}", f'-DTSCB_REWRITE_KEY="{algorithm}"'],
        )
    results = []
    for record_path in records:
        record = json.loads(record_path.read_text())
        algorithm, profile = record["algorithm"], record["profile"]
        manifest = json.loads((ROOT / f"registry/codecs/{algorithm}.json").read_text())
        adapter = {**manifest["adapter"], "artifact_path": record["artifact"]}
        library_path = ROOT / record["artifact"]
        # Separate ASan/native test executables do not use the Python release
        # CDLL profile. Their freshly selected runtimes are recorded per test.
        dependencies = verified_build_dependencies(
            ROOT, library_path, algorithm, adapter, verify_runtime_selection=False
        )
        result = {
            "algorithm": algorithm,
            "profile": profile,
            "build_record": entry(record_path),
            "artifact": entry(library_path),
            "declared_dependencies_status": "PASS",
            "verified_dependency_count": len(dependencies),
            "dependency_verification_scope": "BUILD_RECORD_AUDIT_NOT_PRODUCTION_CDLL_PROFILE",
            "native_tests": [],
        }
        if algorithm in tests:
            relative, macros = tests[algorithm]
            source = ROOT / "adapters" / relative
            compiler = shlex.split(record["command_display"])[0]
            if source.suffix == ".c":
                compiler, standard = "cc", "-std=c11"
            else:
                standard = "-std=c++20" if "neats" in relative else "-std=c++17"
            flags = (
                ["-O2"]
                if profile == "release"
                else [
                    "-O1",
                    "-g",
                    "-fno-omit-frame-pointer",
                    "-fsanitize=address,undefined",
                    "-no-pie",
                ]
            )
            executable = report_root / f"{algorithm}_{profile}_abi"
            command = [
                compiler,
                standard,
                "-UNDEBUG",
                *flags,
                *macros,
                "-I",
                str(ROOT / "native/include"),
                str(source),
                "-L",
                str(library_path.parent),
                f"-Wl,-rpath,{library_path.parent}",
                "-l" + library_path.stem[3:],
                "-lm",
                "-o",
                str(executable),
            ]
            result["native_tests"].append(
                native_test(source, executable, command, "FINITE_DIRECT_C_ABI_TEST")
            )
        if algorithm in {"sprintz-delta-u8", "sprintz-fire-u8", "sprintz-delta", "sprintz-fire"}:
            lowdim = algorithm.endswith("-u8")
            names = (
                ("bounded_lowdim_test", "allocation_failure")
                if lowdim
                else ("bounded_sprintz_test", "allocation_failure_full")
            )
            # Direct object linking is required for malloc/calloc interposition.
            # Executable --wrap flags cannot interpose calls inside a shared DSO.
            objects = [ROOT / item["path"] for item in record["objects"]]
            for name in names:
                source = ROOT / "adapters/sprintz/tests" / (name + ".cc")
                flags = (
                    ["-O2"]
                    if profile == "release"
                    else [
                        "-O1",
                        "-g",
                        "-fno-omit-frame-pointer",
                        "-fsanitize=address,undefined",
                        "-no-pie",
                    ]
                )
                executable = report_root / f"{algorithm}_{profile}_{name}"
                wrappers = (
                    ["-Wl,--wrap=malloc", "-Wl,--wrap=calloc"] if "allocation" in name else []
                )
                command = [
                    "c++",
                    "-std=c++17",
                    "-UNDEBUG",
                    *flags,
                    "-mavx2",
                    "-mbmi2",
                    "-mlzcnt",
                    str(source),
                    *map(str, objects),
                    *wrappers,
                    "-o",
                    str(executable),
                ]
                result["native_tests"].append(
                    native_test(
                        source,
                        executable,
                        command,
                        "FINITE_BOUNDED_KERNEL_AND_ALLOCATION_FAILURE",
                    )
                )
        if profile == "release":
            lib = ctypes.CDLL(str(library_path))
            lib.tscb_get_abi_version.restype = ctypes.c_uint32
            assert lib.tscb_get_abi_version() == 1
            result["abi_version"] = "PASS"
        results.append(result)
        print(f"{algorithm}/{profile}: dependencies and finite native tests PASS", flush=True)
    return {
        "schema_version": "tscb.general-native-build-audit.v1",
        "status": "PASS",
        "driver": entry(Path(__file__)),
        "record_count": len(results),
        "results": results,
        "scope": "DECLARED_REAL_BUILD_CLOSURES_AND_FINITE_NATIVE_API_TESTS",
        "production_cdll_profile": "NOT_QUALIFIED_BY_THIS_NATIVE_EXECUTABLE_REPORT",
        "source_full_parity": "NOT_ASSERTED",
        "limits": [
            "Compiler selected programs are recorded via driver discovery, not exec tracing.",
            "ldd covers dynamic runtime files; implicit static startup/runtime archives "
            "are not all pinned.",
            "System libraries are uninstrumented; LeakSanitizer is disabled "
            "under host ptrace limitations.",
            "Stored upstream/paper parity remains separate from these finite native API tests.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", required=True, type=Path)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--expected-record-count", required=True, type=int)
    args = parser.parse_args()
    output = args.report_root.resolve()
    report = qualify(args.build_root.resolve(), output, args.expected_record_count)
    with (output / "qualification.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
