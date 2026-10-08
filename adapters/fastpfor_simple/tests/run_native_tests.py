"""Build and exercise actual bounded Simple-9/16 libraries under three profiles."""

from __future__ import annotations

import json
import os
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple_source import audit  # noqa: E402

ADAPTER = ROOT / "adapters/fastpfor_simple"
OUT = ROOT / "build/source-audits/fastpfor-simple-native"
REPORT = ROOT / "build/source-audits/fastpfor_simple_native_tests.json"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source = audit()
    recipe = runpy.run_path(str(ADAPTER / "build_native.py"))
    evidence = {
        "status": "RUNNING",
        "source_probe_audit": source,
        "driver": recipe["identity"](Path(__file__)),
        "commands": [],
        "tests": [],
        "fault_tests": [],
        "builds": [],
        "native_timing_fault_injection": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }

    def save() -> None:
        REPORT.write_text(json.dumps(evidence, indent=2) + "\n")

    def run(command: list[str]) -> dict:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=180, env=ENV
        )
        item = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "sanitizer_environment": {k: ENV[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
        }
        evidence["commands"].append(item)
        save()
        if result.returncode:
            raise RuntimeError(shlex.join(command) + "\n" + result.stderr)
        return item

    save()
    try:
        for profile, options in recipe["FLAGS"].items():
            build = recipe["build"](profile)
            evidence["builds"].append(build)
            directory = ROOT / "build/adapters/fastpfor_simple" / profile
            test = ADAPTER / "tests/abi_qualification.cpp"
            executable, deps = OUT / ("shared-" + profile), OUT / ("shared-" + profile + ".d")
            flags = [flag for flag in options if flag != "-DNDEBUG"]
            flags += ["-UNDEBUG", "-fno-pie", "-no-pie"]
            run(
                [
                    "/usr/bin/g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    *flags,
                    "-march=x86-64",
                    "-fno-tree-vectorize",
                    "-I",
                    str(ROOT / "native/include"),
                    "-I",
                    str(ADAPTER / "vendor/fastpfor/headers"),
                    "-MD",
                    "-MF",
                    str(deps),
                    str(test),
                    "-L",
                    str(directory),
                    "-ltscb_fastpfor_simple",
                    "-Wl,-rpath," + str(directory),
                    "-o",
                    str(executable),
                ]
            )
            result = run([str(executable)])
            observed = json.loads(result["stdout"])
            if observed != {
                "status": "PASS",
                "cases": 30450,
                "variants": 6,
                "input_alignments": 4,
                "all_legal_selectors": True,
                "atomic_failures": True,
                "exact_guard_pages": True,
                "native_timer_toggle_and_accumulation": True,
            }:
                raise RuntimeError("native matrix incomplete")
            closure = sorted(
                {
                    Path(p).resolve()
                    for p in shlex.split(deps.read_text().replace("\\\n", " ").split(":", 1)[1])
                }
            )
            evidence["tests"].append(
                {
                    "profile": profile,
                    "executable": recipe["identity"](executable),
                    "test_source": recipe["identity"](test),
                    "dependency_file": recipe["identity"](deps),
                    "actual_compiler_closure": [recipe["identity"](p) for p in closure],
                    "observation": observed,
                    "result": result,
                }
            )
            save()
            print("DONE", profile, observed["cases"], flush=True)
            fault_source = ADAPTER / "tests/native_faults.cpp"
            fault_executable = OUT / ("faults-" + profile)
            fault_deps = OUT / ("faults-" + profile + ".d")
            run(
                [
                    "/usr/bin/g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    *flags,
                    "-I",
                    str(ROOT / "native/include"),
                    "-MD",
                    "-MF",
                    str(fault_deps),
                    str(fault_source),
                    str(directory / "shim.o"),
                    "-Wl,--wrap=clock_gettime",
                    "-Wl,--wrap=_Znwm",
                    "-o",
                    str(fault_executable),
                ]
            )
            fault_result = run([str(fault_executable)])
            fault_observed = json.loads(fault_result["stdout"])
            if fault_observed != {
                "status": "PASS",
                "checks": 66,
                "allocation_exception_atomicity": True,
                "clock_failure_backward_overflow": True,
                "same_shipped_object": True,
            }:
                raise RuntimeError("same-object fault matrix incomplete")
            closure = sorted(
                {
                    Path(p).resolve()
                    for p in shlex.split(
                        fault_deps.read_text().replace("\\\n", " ").split(":", 1)[1]
                    )
                }
            )
            evidence["fault_tests"].append(
                {
                    "profile": profile,
                    "executable": recipe["identity"](fault_executable),
                    "test_source": recipe["identity"](fault_source),
                    "dependency_file": recipe["identity"](fault_deps),
                    "actual_compiler_closure": [recipe["identity"](p) for p in closure],
                    "shipped_object": recipe["identity"](directory / "shim.o"),
                    "observation": fault_observed,
                    "result": fault_result,
                }
            )
            save()
            print("FAULTS", profile, fault_observed["checks"], flush=True)
        evidence.update(
            status="BOUNDED_ABI_MATRIX_AND_FAULT_TESTS_EXECUTED_INDEPENDENT_AUDIT_PENDING",
            native_cases=91350,
            native_executables=3,
            native_timing_fault_injection="SAME_SHIPPED_OBJECT_198_CHECKS_PASSED",
            source_repository_unmodified=True,
        )
        save()
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise
    print(
        json.dumps(
            {
                k: evidence[k]
                for k in (
                    "status",
                    "native_cases",
                    "native_timing_fault_injection",
                    "python_sdk",
                    "benchmark_five_layers",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
