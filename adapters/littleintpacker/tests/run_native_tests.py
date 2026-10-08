"""Exercise real shared libraries and inject faults into their exact shipped objects."""

from __future__ import annotations

import json
import os
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/littleintpacker"
OUT = ROOT / "build/source-audits/littleintpacker-native"
REPORT = ROOT / "build/source-audits/littleintpacker_native_tests.json"
sys.path.insert(0, str(ROOT / "tools"))
from audit_littleintpacker_source import audit  # noqa: E402

ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
MALFORMED = 5 * sum(
    40 + (129 * width + 7) // 8 + 8 + bool(width % 8) + bool(width) for width in range(33)
)
EXPECTED_SHARED = {
    "status": "PASS",
    "cases": 94875,
    "variants": 5,
    "widths": 33,
    "input_alignments": 4,
    "auto_width": True,
    "malformed_rejections": MALFORMED,
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if REPORT.exists():
        raise RuntimeError(
            "native report already exists; preserve prior evidence before a new execution"
        )
    recipe = runpy.run_path(str(ADAPTER / "build_native.py"))
    document = {
        "status": "RUNNING",
        "source_audit": audit(),
        "driver": recipe["identity"](Path(__file__)),
        "commands": [],
        "builds": [],
        "tests": [],
        "fault_tests": [],
        "bounded_abi": "INDEPENDENT_AUDIT_PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "leak_sanitizer": "NOT_QUALIFIED_DETECT_LEAKS_ZERO",
    }
    sources = [
        Path(__file__),
        ADAPTER / "build_native.py",
        ADAPTER / "native/tscb_littleintpacker.cpp",
        ADAPTER / "tests/abi_qualification.cpp",
        ADAPTER / "tests/native_faults.cpp",
        ROOT / "native/include/tscb_adapter_v1.h",
        ROOT / "native/include/tscb_native_timing.h",
    ]
    document["source_snapshot"] = [recipe["identity"](path) for path in sources]
    copies = []
    for path in sources:
        target = OUT / "executed-sources" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        copies.append(recipe["identity"](target))
    document["retained_source_copies"] = copies

    def save() -> None:
        REPORT.write_text(json.dumps(document, indent=2) + "\n")

    def run(command: list[str]) -> dict:
        process = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, env=ENV, timeout=240
        )
        result = {
            "command": command,
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "sanitizer_environment": {key: ENV[key] for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
        }
        document["commands"].append(result)
        save()
        if process.returncode:
            raise RuntimeError(shlex.join(command) + "\n" + process.stderr)
        return result

    save()
    try:
        for profile, options in recipe["FLAGS"].items():
            directory = ROOT / "build/adapters/littleintpacker" / profile
            build_path = directory / "build-record.json"
            build = json.loads(build_path.read_text())
            if build["status"] != "PASS" or build["profile"] != profile:
                raise RuntimeError("actual shared-library build incomplete")
            consumed = (
                build["binding_sources"]
                + build["generated_sources"]
                + build["objects"]
                + build["runtime_dependencies"]
            )
            for item in consumed:
                if recipe["sha"](ROOT / item["path"]) != item["sha256"]:
                    raise RuntimeError("actual build dependency drift: " + item["path"])
            if recipe["sha"](ROOT / build["artifact"]) != build["artifact_sha256"]:
                raise RuntimeError("actual shared library drift")
            document["builds"].append({"record": recipe["identity"](build_path), "build": build})
            flags = [flag for flag in options if flag != "-DNDEBUG"] + [
                "-UNDEBUG",
                "-fno-pie",
                "-no-pie",
            ]
            for target, source_name, expected in (
                ("shared", "abi_qualification.cpp", EXPECTED_SHARED),
                ("faults", "native_faults.cpp", EXPECTED_FAULTS),
            ):
                source = ADAPTER / "tests" / source_name
                exe, dep = OUT / (target + "-" + profile), OUT / (target + "-" + profile + ".d")
                command = [
                    "/usr/bin/g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    *flags,
                    *recipe["BASELINE"],
                    "-I",
                    str(ROOT / "native/include"),
                    "-MD",
                    "-MF",
                    str(dep),
                    str(source),
                ]
                if target == "shared":
                    command += [
                        "-L",
                        str(directory),
                        "-ltscb_littleintpacker",
                        "-Wl,-rpath," + str(directory),
                    ]
                else:
                    command += [str(ROOT / item["path"]) for item in build["objects"]]
                    command += ["-Wl,--wrap=" + name for name in WRAPS]
                command += ["-o", str(exe)]
                run(command)
                result = run([str(exe)])
                observation = json.loads(result["stdout"])
                if observation != expected:
                    raise RuntimeError("native execution matrix incomplete: " + target)
                document["tests" if target == "shared" else "fault_tests"].append(
                    {
                        "profile": profile,
                        "executable": recipe["identity"](exe),
                        "source": recipe["identity"](source),
                        "dependency": recipe["identity"](dep),
                        "compiler_closure": recipe["dependencies"](dep),
                        "shipped_artifact": {
                            "path": build["artifact"],
                            "sha256": build["artifact_sha256"],
                        },
                        "shipped_objects": build["objects"],
                        "observation": observation,
                        "result": result,
                    }
                )
                save()
                print("NATIVE_TEST_PASS", profile, target, flush=True)
        document.update(
            status="BOUNDED_ABI_AND_SAME_OBJECT_FAULTS_EXECUTED_INDEPENDENT_AUDIT_PENDING",
            native_cases=284625,
            malformed_rejections=MALFORMED * 3,
            guard_roundtrips=4455,
            native_fault_checks=510,
        )
    except Exception as error:
        document.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
