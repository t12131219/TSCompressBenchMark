"""Guard/canary and sanitizer qualification for the retained LZSSE2 source closure."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    log = []
    records = []
    for profile in ("release", "sanitizer"):
        directory = ROOT / f"build/adapters/lzsse2_raw/{profile}"
        executable = directory / "abi-qualification"
        command = [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            "-g",
            *(
                ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
                if profile == "sanitizer"
                else []
            ),
            "-I",
            str(ROOT / "native/include"),
            str(ROOT / "adapters/lzsse2_raw/tests/qualification.cc"),
            "-L",
            str(directory),
            "-ltscb_lzsse2_raw",
            f"-Wl,-rpath,{directory}",
            "-o",
            str(executable),
        ]
        environment = dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        )
        for invocation in (command, [str(executable)]):
            result = subprocess.run(
                invocation,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=240,
            )
            log.extend([shlex.join(invocation), result.stdout])
            (ROOT / "build/source-audits/lzsse2-native-tests-20260918.log").write_text(
                "\n".join(log)
            )
            print(result.stdout, flush=True)
            if result.returncode:
                raise RuntimeError(f"LZSSE2 {profile} qualification failed: {result.returncode}")
        records.append(
            {
                "profile": profile,
                "suite": "project-exact-buffer-guard-canary-195-roundtrips-2048-hostile-streams",
                "status": "PASS",
            }
        )
    vendor = ROOT / "adapters/lzsse2_raw/vendor/lzsse/lzsse2"
    directory = ROOT / "build/adapters/lzsse2_raw/release"
    command = [
        "c++",
        "-std=c++17",
        "-O2",
        "-msse4.1",
        "-I",
        str(ROOT / "native/include"),
        "-I",
        str(vendor),
        str(ROOT / "adapters/lzsse2_raw/tests/vendor_compare.cc"),
        str(vendor / "lzsse2.cpp"),
        "-L",
        str(directory),
        "-ltscb_lzsse2_raw",
        f"-Wl,-rpath,{directory}",
        "-o",
        str(directory / "vendor-compare"),
    ]
    extras = [("unmodified-vendor-compare", command, [str(directory / "vendor-compare")])]
    for profile in ("release", "sanitizer"):
        directory = ROOT / f"build/adapters/lzsse2_raw/{profile}"
        executable = directory / "allocation-failure"
        command = [
            "c++",
            "-std=c++17",
            "-O1",
            "-g",
            "-msse4.1",
            *(["-fsanitize=address,undefined", "-no-pie"] if profile == "sanitizer" else []),
            "-I",
            str(directory),
            "-I",
            str(vendor),
            str(ROOT / "adapters/lzsse2_raw/tests/allocation_failure.cc"),
            "-o",
            str(executable),
        ]
        extras.append((f"{profile}-allocation-failure", command, [str(executable)]))
    for suite, command, invocation in extras:
        for action in (command, invocation):
            result = subprocess.run(
                action,
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=240,
            )
            log.extend([shlex.join(action), result.stdout])
            (ROOT / "build/source-audits/lzsse2-native-tests-20260918.log").write_text(
                "\n".join(log)
            )
            print(result.stdout, flush=True)
            if result.returncode:
                raise RuntimeError(f"{suite} failed: {result.returncode}")
        records.append(
            {
                "profile": "sanitizer" if suite.startswith("sanitizer") else "release",
                "suite": suite,
                "status": "PASS",
            }
        )
    log_path = ROOT / "build/source-audits/lzsse2-native-tests-20260918.log"
    digest = hashlib.sha256(log_path.read_bytes()).hexdigest()
    for record in records:
        record.update(log_sha256=digest, evidence=str(log_path.relative_to(ROOT)))
    (ROOT / "build/source-audits/lzsse2-native-tests-20260918.json").write_text(
        json.dumps(records, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
