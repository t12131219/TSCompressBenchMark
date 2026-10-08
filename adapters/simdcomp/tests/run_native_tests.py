"""Qualify shipped SIMDComp shared libraries and their same-object fault paths."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/simdcomp"
OUT = ROOT / "build/source-audits/simdcomp-native"
REPORT = ROOT / "build/source-audits/simdcomp_native_tests.json"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
WRAPS = (
    "malloc",
    "calloc",
    "posix_memalign",
    "free",
    "clock_gettime",
    "simdpack_length",
    "simdpack_shortlength",
    "simdpackFOR_length",
    "simdunpack_length",
    "simdunpack_shortlength",
    "simdunpackFOR_length",
    "simdpack",
    "simdpackwithoutmask",
    "simdpackd1",
    "simdpackwithoutmaskd1",
    "simdpackFOR",
    "simdunpack",
    "simdunpackd1",
    "simdunpackFOR",
    "avxpack",
    "avxpackwithoutmask",
    "avxunpack",
    "maxbits_length",
    "simdmaxbitsd1_length",
    "bits",
)
evidence = {
    "schema_version": "tscb.simdcomp-native-tests.v1",
    "status": "RUNNING",
    "commands": [],
    "tests": [],
    "builds": [],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def save() -> None:
    REPORT.write_text(json.dumps(evidence, indent=2) + "\n")


def run(command: list[str]) -> dict:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=ENV, timeout=300)
    observed = {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "sanitizer_environment": {k: ENV[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
    }
    evidence["commands"].append(observed)
    save()
    if result.returncode:
        raise RuntimeError(json.dumps(observed, indent=2))
    return observed


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save()
    sys.path.insert(0, str(ROOT / "tools"))
    audit_module = runpy.run_path(str(ROOT / "tools/audit_simdcomp_avx2.py"))
    evidence["source_audit"] = audit_module["audit"]()
    evidence["source_auditor"] = identity(ROOT / "tools/audit_simdcomp_avx2.py")
    recipe = runpy.run_path(str(ADAPTER / "build_native.py"))
    for profile, flags in recipe["FLAGS"].items():
        directory = ROOT / "build/adapters/simdcomp_u32" / profile
        build_path = directory / "build-record.json"
        build = json.loads(build_path.read_text())
        if build["status"] != "PASS" or build["artifact_sha256"] != sha(ROOT / build["artifact"]):
            raise RuntimeError(
                "shared build missing or stale; run adapters/simdcomp/build_native.py"
            )
        for item in [
            *build["binding_sources"],
            *build["compiled_source_closure"],
            *build["objects"],
            *build["patches"],
            *build["runtime_dependencies"],
        ]:
            if sha(ROOT / item["path"]) != item["sha256"]:
                raise RuntimeError("build input/object drift: " + item["path"])
        evidence["builds"].append(
            {
                "profile": profile,
                "record": identity(build_path),
                "library": identity(ROOT / build["artifact"]),
                "objects": build["objects"],
            }
        )
        save()
        for kind, source in (
            ("shared", ADAPTER / "tests/abi_qualification.c"),
            ("instrumented", ADAPTER / "tests/abi_qualification.c"),
            ("pointer_regression", ADAPTER / "tests/pointer_return_guard.c"),
        ):
            executable = OUT / f"{kind}-{profile}"
            dependencies = OUT / f"{kind}-{profile}.d"
            command = [
                "/usr/bin/cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                *(f for f in flags if f != "-DNDEBUG"),
                "-UNDEBUG",
                "-march=x86-64",
                "-mno-avx",
                "-fno-pie",
                "-no-pie",
                "-MD",
                "-MF",
                str(dependencies),
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(directory / "patched-source/include"),
            ]
            if kind == "shared":
                command += [
                    str(source),
                    "-L",
                    str(directory),
                    "-ltscb_simdcomp_u32",
                    "-Wl,-rpath," + str(directory),
                ]
            else:
                if kind == "instrumented":
                    command += ["-DINSTRUMENTED"]
                command += [
                    str(source),
                    *(str(directory / (n + ".o")) for n in recipe["OBJECT_NAMES"]),
                ]
                wraps = WRAPS if kind == "instrumented" else WRAPS[5:11]
                command += ["-Wl,--wrap=" + name for name in wraps]
            command += ["-o", str(executable)]
            run(command)
            observed = run([str(executable)])
            closure = sorted(
                {
                    Path(p).resolve()
                    for p in shlex.split(
                        dependencies.read_text().replace("\\\n", " ").partition(":")[2]
                    )
                }
            )
            evidence["tests"].append(
                {
                    "profile": profile,
                    "kind": kind,
                    "source": identity(source),
                    "executable": identity(executable),
                    "compile_command": command,
                    "dependency_file": identity(dependencies),
                    "compiled_test_closure": [identity(p) for p in closure],
                    **observed,
                }
            )
            print(kind, profile, observed["stdout"].strip(), flush=True)
            save()
    timer_source = ROOT / "tests/native/native_timing_smoke.c"
    executable = OUT / "native-timing-faults"
    run(
        [
            "/usr/bin/cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "native/include"),
            str(timer_source),
            "-o",
            str(executable),
        ]
    )
    observed = run([str(executable)])
    evidence["tests"].append(
        {
            "kind": "shared_timer_overflow",
            "source": identity(timer_source),
            "executable": identity(executable),
            **observed,
        }
    )
    evidence.update(
        status="PASS",
        driver=identity(Path(__file__)),
        build_driver=identity(ADAPTER / "build_native.py"),
        contract=identity(ADAPTER / "contract.md"),
        source_lock=identity(ADAPTER / "SOURCE_LOCK.json"),
        cases_per_executable=31878,
        benchmark_five_layers="NOT_CLAIMED",
        python_sdk="PENDING",
        leak_detection="DISABLED",
        cpu_affinity=sorted(os.sched_getaffinity(0)),
    )
    save()


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise
