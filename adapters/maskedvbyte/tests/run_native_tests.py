"""Qualify shipped MaskedVByte shared binaries and same-object fault paths."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/maskedvbyte"
OUT = ROOT / "build/source-audits/maskedvbyte-native"
REPORT = ROOT / "build/source-audits/maskedvbyte-native-tests.json"
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
    # Verify actual source evidence; a prior status string alone is insufficient.
    source_module = runpy.run_path(str(ROOT / "tools/audit_maskedvbyte_source.py"))
    source_audit = source_module["audit"]()
    if source_audit["status"] != "PASS":
        raise RuntimeError("original/patched source API qualification is absent or stale")
    source_report = ROOT / "build/source-audits/maskedvbyte-source-both-tests.json"
    evidence["source_report_sha256"] = sha(source_report)
    evidence["source_audit"] = source_audit
    recipe = runpy.run_path(str(ADAPTER / "build_native.py"))
    test_source = ADAPTER / "tests/abi_qualification.c"
    for profile in recipe["FLAGS"]:
        build = recipe["build"](profile)
        evidence["builds"].append(build)
        save()
        directory = ROOT / "build/adapters/maskedvbyte_u32" / profile
        compiler = os.environ.get("CC", "clang" if profile == "sanitizer" else "cc")
        flags = [flag for flag in recipe["FLAGS"][profile] if flag != "-DNDEBUG"]
        for kind in ("shared", "instrumented"):
            executable = OUT / f"{kind}-{profile}"
            dependencies = OUT / f"{kind}-{profile}.d"
            command = [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                *flags,
                "-fno-pie",
                "-no-pie",
                "-MD",
                "-MF",
                str(dependencies),
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(ADAPTER / "vendor/MaskedVByte/include"),
            ]
            if kind == "instrumented":
                command += [
                    "-DINSTRUMENTED",
                    str(test_source),
                    *(str(directory / (name + ".o")) for name in ("shim", "encoder", "decoder")),
                ]
                command += [
                    "-Wl,--wrap=" + name
                    for name in (
                        "malloc",
                        "calloc",
                        "free",
                        "clock_gettime",
                        "vbyte_encode",
                        "vbyte_encode_delta",
                        "masked_vbyte_decode",
                        "masked_vbyte_decode_delta",
                        "masked_vbyte_decode_fromcompressedsize",
                        "masked_vbyte_decode_fromcompressedsize_delta",
                    )
                ]
            else:
                command += [
                    str(test_source),
                    "-L",
                    str(directory),
                    "-ltscb_maskedvbyte_u32",
                    "-Wl,-rpath," + str(directory),
                ]
            command += ["-o", str(executable)]
            run(command)
            result = run([str(executable)])
            closure = sorted(
                {
                    Path(name).resolve()
                    for name in shlex.split(
                        dependencies.read_text().replace("\\\n", " ").partition(":")[2]
                    )
                }
            )
            evidence["tests"].append(
                {
                    "kind": kind,
                    "profile": profile,
                    "test_sha256": sha(test_source),
                    "compile_command": command,
                    "executable_sha256": sha(executable),
                    "compiled_test_closure": [recipe["identity"](path) for path in closure],
                    **result,
                }
            )
            print(kind, profile, result["stdout"].strip(), flush=True)
            save()
    timer_test = ROOT / "tests/native/native_timing_smoke.c"
    executable = OUT / "native-timing-faults"
    run(
        [
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
    )
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
        source_audit_driver_sha256=sha(ROOT / "tools/audit_maskedvbyte_source.py"),
        cases_per_executable=9360,
        benchmark_five_layers="NOT_CLAIMED",
        python_sdk="PENDING",
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
