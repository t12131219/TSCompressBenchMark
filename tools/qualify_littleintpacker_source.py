"""Build/run unchanged complete upstream unit and direct original API evidence."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from freeze_littleintpacker_source import ADAPTER, APIS, PIN, ROOT, git

OUT = ROOT / "build/source-audits/littleintpacker-source"
REPORT = ROOT / "build/source-audits/littleintpacker_source_tests.json"
PROFILES = {
    "release": ["-O3", "-g", "-UNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
        "-no-pie",
    ],
}
SOURCES = {
    "bitpacking32.c": [],
    "turbobitpacking32.c": [],
    "scpacking32.c": [],
    "bmipacking32.c": ["-mavx2", "-mbmi2"],
    "horizontalpacking32.c": ["-mssse3", "-msse4.1"],
    "util.c": [],
}
BASELINE = [
    "-march=x86-64",
    "-mno-avx",
    "-mno-avx2",
    "-mno-avx512f",
    "-fno-tree-vectorize",
    "-fno-tree-slp-vectorize",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise RuntimeError(reason)


def dependency_files(path: Path) -> list[Path]:
    content = path.read_text().replace("\\\n", " ").split(":", 1)[1]
    return sorted({Path(name).resolve() for name in content.split()})


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    require(git("rev-parse", "HEAD").decode().strip() == PIN, "original source pin changed")
    require(not git("status", "--porcelain"), "original source repository dirty")
    flags = Path("/proc/cpuinfo").read_text().split("flags\t\t: ", 1)[1].splitlines()[0].split()
    require({"avx2", "bmi2", "sse4_1"} <= set(flags), "complete original unit CPU ISA unavailable")
    for item in lock["files"]:
        require(sha(ROOT / item["path"]) == item["sha256"], "vendor source drift")
        require(
            (ROOT / item["path"]).read_bytes() == git("show", f"{PIN}:{item['upstream_path']}"),
            "vendor differs from pinned Git bytes",
        )
    document = {
        "status": "RUNNING",
        "commit": PIN,
        "profiles": {},
        "commands": [],
        "driver": identity(Path(__file__)),
        "probe": identity(ADAPTER / "tests/source_api_probe.c"),
        "source_lock": identity(ADAPTER / "SOURCE_LOCK.json"),
        "full_logical_entries_qualified": False,
    }

    def save() -> None:
        REPORT.write_text(json.dumps(document, indent=2) + "\n")

    def run(command: list[str], expected_success: bool = True) -> dict:
        environment = dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        )
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=240, env=environment
        )
        record = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        document["commands"].append(record)
        save()
        if expected_success:
            require(result.returncode == 0, "source qualification command failed: " + str(command))
        return record

    save()
    try:
        vendor = ADAPTER / "vendor/littleintpacker"
        for profile, options in PROFILES.items():
            directory = OUT / profile
            directory.mkdir(parents=True, exist_ok=True)
            objects, dependencies = [], set()
            builds = []
            for name, isa in SOURCES.items():
                source = vendor / "src" / name
                obj, dep = directory / (name + ".o"), directory / (name + ".d")
                observation = run(
                    [
                        "/usr/bin/gcc",
                        "-std=c99",
                        "-Wall",
                        "-Wextra",
                        *options,
                        *BASELINE,
                        *isa,
                        "-I",
                        str(vendor / "include"),
                        "-MD",
                        "-MF",
                        str(dep),
                        "-c",
                        str(source),
                        "-o",
                        str(obj),
                    ]
                )
                objects.append(obj)
                closure = dependency_files(dep)
                dependencies.update(closure)
                builds.append(
                    {
                        "source": identity(source),
                        "object": identity(obj),
                        "dependency": identity(dep),
                        "command": observation["command"],
                        "compiler_closure": [identity(p) for p in closure],
                    }
                )
            executions = {}
            for target, source in (
                ("unit", vendor / "tests/unit.c"),
                ("api-probe", ADAPTER / "tests/source_api_probe.c"),
            ):
                exe, dep = directory / target, directory / (target + ".d")
                run(
                    [
                        "/usr/bin/gcc",
                        "-std=c99",
                        *options,
                        *BASELINE,
                        "-I",
                        str(vendor / "include"),
                        "-MD",
                        "-MF",
                        str(dep),
                        str(source),
                        *map(str, objects),
                        "-o",
                        str(exe),
                    ]
                )
                dependencies.update(dependency_files(dep))
                execution = run(
                    [str(exe)], expected_success=profile != "sanitizer" and target == "unit"
                )
                executions[target] = {
                    "artifact": identity(exe),
                    "dependency": identity(dep),
                    "result": execution,
                    "status": "PASS"
                    if execution["returncode"] == 0
                    else "ORIGINAL_FAILURE_RETAINED",
                }
                if profile != "sanitizer" and target == "unit":
                    require(
                        "All tests OK!" in execution["stdout"], "complete original unit incomplete"
                    )
                elif profile != "sanitizer":
                    require(
                        execution["returncode"] == 12
                        and "MATRIX_DONE cases=18975 failures=380" in execution["stdout"],
                        "complete original API matrix or known zero-width failure differs",
                    )
                else:
                    require(
                        execution["returncode"] != 0 and "runtime error:" in execution["stderr"],
                        "expected original undefined behavior not reproduced",
                    )
            raw_probes = []
            exe = directory / "api-probe"
            for api, key in enumerate(APIS):
                for mode in (
                    "exact-input",
                    "exact-packed-output",
                    "exact-decoded-output",
                    "exact-packed-input",
                    "invalid-width",
                    "odd-width-multiple-blocks",
                ):
                    result = run([str(exe), str(api), mode], expected_success=False)
                    raw_probes.append(
                        {
                            "api": key,
                            "mode": mode,
                            "result": result,
                            "status": "ORIGINAL_FAILURE_RETAINED"
                            if result["returncode"]
                            else "RAW_CALL_RETURNED",
                        }
                    )
            document["profiles"][profile] = {
                "builds": builds,
                "executions": executions,
                "raw_probes": raw_probes,
                "compiler_closure": [identity(p) for p in sorted(dependencies)],
            }
            save()
            print("SOURCE_PROFILE_DONE", profile, flush=True)
        document.update(
            status="ORIGINAL_SOURCE_TESTS_EXECUTED_BOUNDED_ABI_PENDING",
            source_repository_unmodified=not bool(git("status", "--porcelain")),
            leak_sanitizer="NOT_QUALIFIED_DETECT_LEAKS_ZERO",
            bounded_abi="PENDING",
            python_sdk="PENDING",
            benchmark_five_layers="PENDING",
        )
    except Exception as error:
        document.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
