"""Freeze and run original/patched AVX2 source tests, including the existing SSE API suite."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/simdcomp"
OUT = ROOT / "build/source-audits/simdcomp-avx2"
REPORT = ROOT / "build/source-audits/simdcomp_avx2_source_tests.json"
ISA = ["-march=x86-64", "-mavx2", "-mno-avx512f", "-UNDEBUG"]
PROFILES = {
    "release": ("Release", ["-O3", "-UNDEBUG"]),
    "debug": ("Debug", ["-O0", "-g", "-DSIMDCOMP_DEBUG", "-UNDEBUG"]),
    "sanitizer": (
        "RelWithDebInfo",
        [
            "-O1",
            "-g",
            "-UNDEBUG",
            "-fsanitize=address,undefined",
            "-fno-sanitize-recover=all",
            "-fno-omit-frame-pointer",
        ],
    ),
}
MODES = ("plain", "d1", "for", "query-d1", "query-for", "set-plain", "set-d1", "set-for", "avx2")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha(path)}


def main() -> None:
    cpuinfo = Path("/proc/cpuinfo").read_text()
    if any("avx2" not in line.split() for line in cpuinfo.splitlines() if line.startswith("flags")):
        raise RuntimeError("AVX2 is unavailable; no fallback is permitted")
    source_audit = runpy.run_path(str(ROOT / "tools/audit_simdcomp_source.py"))["audit"]()
    if source_audit["status"] != "PASS":
        raise RuntimeError("current SSE source/patch evidence must pass first")
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    guard = ADAPTER / "tests/source_avx2_guard.c"
    profile_patches = source_audit["patches"] + [
        record(ADAPTER / "patches/avx2/0001-zero-width-unpack-byte-count.patch")
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "tscb.simdcomp-avx2-source-tests.v1",
        "status": "RUNNING",
        "source_lock_sha256": sha(ADAPTER / "SOURCE_LOCK.json"),
        "driver": record(Path(__file__)),
        "guard": record(guard),
        "sse_guard": record(ADAPTER / "tests/source_guard.c"),
        "actual_isa": "AVX2_WITH_SSE_PUBLIC_API_PATHS_NO_AVX512",
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "cpuinfo_sha256": hashlib.sha256(cpuinfo.encode()).hexdigest(),
        "source_auditor": record(ROOT / "tools/audit_simdcomp_source.py"),
        "patches": profile_patches,
        "builds": [],
        "tests": [],
        "commands": [],
        "benchmark_adapter_qualification": "NOT_CLAIMED",
        "leak_detection": "DISABLED",
    }

    def save() -> None:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    def run(command: list[str], check: bool = True) -> dict:
        env = dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        )
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, env=env, timeout=300
        )
        item = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "cwd": str(ROOT),
            "sanitizer_environment": {k: env[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS")},
        }
        report["commands"].append(item)
        save()
        if check and result.returncode:
            raise RuntimeError(shlex.join(command) + "\n" + result.stderr)
        return item

    try:
        report["compiler"] = run(["/usr/bin/cc", "--version"])["stdout"]
        for kind in ("original", "patched"):
            source = ADAPTER / "vendor/simdcomp"
            if kind == "patched":
                source = OUT / "patched-source"
                for item in lock["files"]:
                    destination = source / item["upstream_path"]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / item["path"], destination)
                for patch in profile_patches:
                    run(
                        [
                            "patch",
                            "--batch",
                            "--forward",
                            "-p1",
                            "-d",
                            str(source),
                            "-i",
                            patch["path"],
                        ]
                    )
            for profile, (cmake_type, flags) in PROFILES.items():
                output = OUT / kind / profile
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
                        f"-DCMAKE_C_FLAGS={shlex.join(ISA)}",
                        f"-DCMAKE_C_FLAGS_{cmake_type.upper()}={shlex.join(flags)}",
                    ]
                )
                run(["cmake", "--build", str(output), "--parallel", "1", "--verbose"])
                executable = output / "avx2-source-guard"
                dependency = output / "avx2-source-guard.d"
                run(
                    [
                        "/usr/bin/cc",
                        "-std=gnu11",
                        *ISA,
                        *flags,
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-MD",
                        "-MF",
                        str(dependency),
                        "-I",
                        str(source / "include"),
                        str(guard),
                        str(output / "libsimdcomp.a"),
                        "-o",
                        str(executable),
                    ]
                )
                closure = set()
                for dep in [*output.rglob("*.o.d"), dependency]:
                    closure.update(
                        Path(p).resolve()
                        for p in shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1])
                    )
                compile_commands = output / "compile_commands.json"
                report["builds"].append(
                    {
                        "source_kind": kind,
                        "profile": profile,
                        "compile_commands": record(compile_commands),
                        "compiled_source_closure": [record(p) for p in sorted(closure)],
                        "library": record(output / "libsimdcomp.a"),
                        "objects": [record(p) for p in sorted(output.rglob("*.o"))],
                        "guard_executable": record(executable),
                    }
                )
                for program in ("unit", "unit_chars", "example"):
                    observed = run([str(output / program)], False)
                    report["tests"].append(
                        {
                            "source_kind": kind,
                            "profile": profile,
                            "kind": "upstream",
                            "mode": program,
                            "executable": record(output / program),
                            **observed,
                        }
                    )
                for mode in MODES:
                    observed = run([str(executable), mode], False)
                    report["tests"].append(
                        {
                            "source_kind": kind,
                            "profile": profile,
                            "kind": "guard",
                            "mode": mode,
                            "executable": record(executable),
                            **observed,
                        }
                    )
                    print(
                        json.dumps(
                            {
                                "source": kind,
                                "profile": profile,
                                "mode": mode,
                                "returncode": observed["returncode"],
                                "stderr": observed["stderr"][:600],
                            }
                        ),
                        flush=True,
                    )
                save()
        report["failed_test_count"] = sum(t["returncode"] != 0 for t in report["tests"])
        report["status"] = "OBSERVATIONS_COMPLETE"
        save()
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "programs": len(report["tests"]),
                    "failures_retained": report["failed_test_count"],
                }
            ),
            flush=True,
        )
    except BaseException as error:
        report.update(status="HARNESS_FAILED", error=type(error).__name__ + ": " + str(error))
        save()
        raise


if __name__ == "__main__":
    main()
