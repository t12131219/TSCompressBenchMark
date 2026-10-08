"""Qualify the exact source algorithms before constructing any Benchmark adapter."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/fast_differential"
VENDOR = ADAPTER / "vendor/FastDifferentialCoding"
OUT = ROOT / "build/source-audits/fast-differential-source"
REPORT = ROOT / "build/source-audits/fast-differential-source-tests.json"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
evidence: dict = {"status": "RUNNING", "commands": [], "tests": []}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save() -> None:
    REPORT.write_text(json.dumps(evidence, indent=2) + "\n")


def run(command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, env=ENV, timeout=120)
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
    lock_path = ADAPTER / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    for item in lock["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError(f"frozen source changed: {item['path']}")
    for profile, options in {
        "release": ["-O3"],
        "debug": ["-O0", "-g"],
        "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
    }.items():
        for kind, test in (
            ("upstream", VENDOR / "tests/unit.c"),
            ("source_guard", ADAPTER / "tests/source_guard.c"),
        ):
            executable = OUT / f"{kind}-{profile}"
            command = [
                "cc",
                "-std=c11",
                "-msse4.1",
                "-Wall",
                "-Wextra",
                *options,
                "-I",
                str(VENDOR / "include"),
                str(test),
                str(VENDOR / "src/fastdelta.c"),
                "-o",
                str(executable),
            ]
            run(command)
            result = run([str(executable)])
            evidence["tests"].append(
                {
                    "kind": kind,
                    "profile": profile,
                    "test_sha256": sha(test),
                    "executable_sha256": sha(executable),
                    **result,
                }
            )
            print(kind, profile, "PASS", flush=True)
    evidence.update(
        status="PASS",
        source_lock_sha256=sha(lock_path),
        driver_sha256=sha(Path(__file__)),
        classification="P0_MODULAR32_D1_TRANSFORM_FOUR_ORIGINAL_APIS",
        benchmark_adapter_qualification="NOT_CLAIMED",
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
