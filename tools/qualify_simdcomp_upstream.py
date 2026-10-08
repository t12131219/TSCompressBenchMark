"""Run the pinned SIMDComp upstream tests out of tree; do not claim Benchmark admission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/simdcomp"
BUILD = ROOT / "build/source-audits/simdcomp-upstream"
ISA_FLAGS = "-march=x86-64 -msse4.1 -mno-avx -UNDEBUG"
PROFILES = {
    "release": ("Release", "-O3 -UNDEBUG"),
    "debug": ("Debug", "-O0 -g -DSIMDCOMP_DEBUG -UNDEBUG"),
    "sanitizer": (
        "RelWithDebInfo",
        "-O1 -g -UNDEBUG -fsanitize=address,undefined -fno-sanitize-recover=all "
        "-fno-omit-frame-pointer",
    ),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_record(path: Path) -> dict:
    path = path.resolve()
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("original", "patched"), default="original")
    arguments = parser.parse_args()
    lock_path = ADAPTER / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    for item in lock["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError("frozen original source differs: " + item["path"])
    source = ADAPTER / "vendor/simdcomp"
    BUILD.mkdir(parents=True, exist_ok=True)
    report_path = ROOT / f"build/source-audits/simdcomp-upstream-{arguments.kind}-tests.json"
    report = {
        "schema_version": "tscb.simdcomp-upstream-tests.v1",
        "status": "RUNNING",
        "source_kind": arguments.kind,
        "source_lock_sha256": sha(lock_path),
        "driver": file_record(Path(__file__)),
        "files": lock["files"],
        "patches": [],
        "builds": [],
        "tests": [],
        "commands": [],
        "actual_isa": "SSE4_1_SSSE3_NO_AVX",
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "upstream_benchmark_results_imported": False,
        "benchmark_adapter_qualification": "NOT_CLAIMED",
        "leak_detection": "DISABLED",
        "source_repository_modified": False,
    }

    def save() -> None:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def run(command: list[str], *, check: bool = True) -> dict:
        env = dict(os.environ)
        env["ASAN_OPTIONS"] = "detect_leaks=0:abort_on_error=1"
        env["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        result = subprocess.run(
            command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
        )
        observation = {
            "command": command,
            "cwd": str(ROOT),
            "sanitizer_environment": {key: env[key] for key in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(observation)
        save()
        if check and result.returncode:
            raise RuntimeError("command failed: " + shlex.join(command) + "\n" + result.stderr)
        return observation

    try:
        report["compiler"] = run(["cc", "--version"])["stdout"]
        if arguments.kind == "patched":
            patches = sorted((ADAPTER / "patches").glob("*.patch"))
            if not patches:
                raise RuntimeError("patched build requires an explicit saved patch")
            source = BUILD / "patched-source"
            source.mkdir(parents=True, exist_ok=True)
            for item in lock["files"]:
                destination = source / item["upstream_path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / item["path"], destination)
            for patch in patches:
                report["patches"].append(file_record(patch))
                run(["patch", "--batch", "--forward", "-p1", "-d", str(source), "-i", str(patch)])
        for profile, (cmake_type, flags) in PROFILES.items():
            output = BUILD / arguments.kind / profile
            run(
                [
                    "cmake",
                    "-S",
                    str(source),
                    "-B",
                    str(output),
                    "-DSIMDCOMP_NATIVE=OFF",
                    "-DSIMDCOMP_BUILD_BENCHMARKS=OFF",
                    "-DSIMDCOMP_BUILD_TESTS=ON",
                    "-DSIMDCOMP_BUILD_EXAMPLES=ON",
                    "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                    "-DCMAKE_C_COMPILER=/usr/bin/cc",
                    f"-DCMAKE_BUILD_TYPE={cmake_type}",
                    f"-DCMAKE_C_FLAGS={ISA_FLAGS}",
                    f"-DCMAKE_C_FLAGS_{cmake_type.upper()}={flags}",
                ]
            )
            run(["cmake", "--build", str(output), "--parallel", "1", "--verbose"])
            compile_commands = output / "compile_commands.json"
            commands = json.loads(compile_commands.read_text())
            closure: set[Path] = set()
            for dependency in output.rglob("*.o.d"):
                contents = dependency.read_text().replace("\\\n", " ")
                for filename in shlex.split(contents.split(":", 1)[1]):
                    path = Path(filename)
                    if not path.is_absolute():
                        path = output / path
                    closure.add(path.resolve())
            if not closure or len(commands) != 11:
                raise RuntimeError("actual compiler dependencies or build target universe missing")
            build = {
                "profile": profile,
                "compile_commands": file_record(compile_commands),
                "commands": commands,
                "compiled_source_closure": [file_record(path) for path in sorted(closure)],
                "objects": [file_record(path) for path in sorted(output.rglob("*.o"))],
                "library": file_record(output / "libsimdcomp.a"),
            }
            report["builds"].append(build)
            for program in ("unit", "unit_chars", "example"):
                observation = run([str(output / program)], check=False)
                report["tests"].append(
                    {
                        "profile": profile,
                        "test_kind": program,
                        "status": "PASS" if observation["returncode"] == 0 else "FAIL",
                        "executable": file_record(output / program),
                        **observation,
                    }
                )
                save()
                print(
                    json.dumps(
                        {
                            "profile": profile,
                            "test": program,
                            "returncode": observation["returncode"],
                        }
                    ),
                    flush=True,
                )
        report["failed_test_count"] = sum(test["status"] == "FAIL" for test in report["tests"])
        report["status"] = "OBSERVED_FAILURES" if report["failed_test_count"] else "PASS"
        for item in lock["files"]:
            if sha(ROOT / item["path"]) != item["sha256"]:
                raise RuntimeError("original source changed during qualification")
        save()
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "tests": len(report["tests"]),
                    "failed": report["failed_test_count"],
                    "report": str(report_path),
                },
                indent=2,
            ),
            flush=True,
        )
    except BaseException as error:
        report["status"] = "HARNESS_FAILED"
        report["error"] = type(error).__name__ + ": " + str(error)
        save()
        raise


if __name__ == "__main__":
    main()
