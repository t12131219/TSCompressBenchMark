"""Qualify the shipped shared ABI plus instrumented same-object fault paths."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/fast_differential"
OUT = ROOT / "build/source-audits/fast-differential-native"
REPORT = ROOT / "build/source-audits/fast-differential-native-tests.json"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
evidence: dict = {"status": "RUNNING", "commands": [], "tests": [], "builds": []}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save() -> None:
    REPORT.write_text(json.dumps(evidence, indent=2) + "\n")


def run(command: list[str]) -> dict:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=ENV, timeout=120)
    item = {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    evidence["commands"].append(item)
    save()
    if result.returncode:
        raise RuntimeError(json.dumps(item, indent=2))
    return item


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save()
    source_report = ROOT / "build/source-audits/fast-differential-source-tests.json"
    source = json.loads(source_report.read_text())
    if (
        source.get("status") != "PASS"
        or source["source_lock_sha256"] != sha(ADAPTER / "SOURCE_LOCK.json")
        or source["driver_sha256"] != sha(ADAPTER / "tests/run_source_tests.py")
    ):
        raise RuntimeError("original API qualification is absent or stale")
    for test in source["tests"]:
        path = (
            ADAPTER / "vendor/FastDifferentialCoding/tests/unit.c"
            if test["kind"] == "upstream"
            else ADAPTER / "tests/source_guard.c"
        )
        if (
            sha(path) != test["test_sha256"]
            or sha(Path(test["command"][0])) != test["executable_sha256"]
        ):
            raise RuntimeError("original source test/executable drift")
    evidence["original_source_report_sha256"] = sha(source_report)
    recipe = runpy.run_path(str(ADAPTER / "build_native.py"))
    test_source = ADAPTER / "tests/abi_qualification.c"
    for profile in recipe["FLAGS"]:
        build = recipe["build"](profile)
        evidence["builds"].append(build)
        save()
        directory = ROOT / "build/adapters/fast_differential_u32" / profile
        # Assertions stay enabled in qualification, including release tests.
        flags = [flag for flag in recipe["FLAGS"][profile] if flag != "-DNDEBUG"]
        for kind in ("shared", "instrumented"):
            executable = OUT / f"{kind}-{profile}"
            command = [
                os.environ.get("CC", "cc"),
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                *flags,
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(ADAPTER / "vendor/FastDifferentialCoding/include"),
            ]
            if kind == "instrumented":
                command += [
                    "-DINSTRUMENTED",
                    str(test_source),
                    str(directory / "shim.o"),
                    str(directory / "source.o"),
                ]
                command += [
                    "-Wl,--wrap=" + name
                    for name in (
                        "malloc",
                        "calloc",
                        "clock_gettime",
                        "compute_deltas",
                        "compute_deltas_inplace",
                        "compute_prefix_sum",
                        "compute_prefix_sum_inplace",
                    )
                ]
            else:
                command += [
                    str(test_source),
                    "-L",
                    str(directory),
                    "-ltscb_fast_differential_u32",
                    "-Wl,-rpath," + str(directory),
                ]
            command += ["-o", str(executable)]
            run(command)
            result = run([str(executable)])
            evidence["tests"].append(
                {
                    "kind": kind,
                    "profile": profile,
                    "test_sha256": sha(test_source),
                    "executable_sha256": sha(executable),
                    **result,
                }
            )
            print(kind, profile, result["stdout"].strip(), flush=True)
            save()
    # This shared timer test additionally injects accumulator overflow.
    timer_test = ROOT / "tests/native/native_timing_smoke.c"
    executable = OUT / "native-timing-faults"
    command = [
        os.environ.get("CC", "cc"),
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-I",
        str(ROOT / "native/include"),
        str(timer_test),
        "-o",
        str(executable),
    ]
    run(command)
    result = run([str(executable)])
    evidence["tests"].append(
        {
            "kind": "shared_timer_overflow",
            "test_sha256": sha(timer_test),
            "executable_sha256": sha(executable),
            **result,
        }
    )
    evidence.update(
        status="PASS",
        driver_sha256=sha(Path(__file__)),
        build_driver_sha256=sha(ADAPTER / "build_native.py"),
        contract_sha256=sha(ADAPTER / "contract.md"),
        source_lock_sha256=sha(ADAPTER / "SOURCE_LOCK.json"),
        cases_per_executable=4160,
        benchmark_five_layers="NOT_CLAIMED",
        leak_detection="DISABLED",
        platform="LINUX_X86_64_SSE4_1",
    )
    save()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise
