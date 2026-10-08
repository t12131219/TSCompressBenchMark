"""Freeze and run the entire original FastPFOR unit driver without filtering codecs."""

from __future__ import annotations

import json
import resource
import shlex
import subprocess
from pathlib import Path

from audit_fastpfor_simple_source import require, sha
from freeze_fastpfor_simple_source import PIN, SOURCES, pinned, tracked

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "adapters/fastpfor_simple/third_party/fastpfor_upstream_unit"
REPORT = ROOT / "build/source-audits/fastpfor_simple_upstream_tests.json"
UNITS = [
    "src/unit.cpp",
    "src/bitpacking.cpp",
    "src/bitpackingaligned.cpp",
    "src/bitpackingunaligned.cpp",
    "src/horizontalbitpacking.cpp",
    "src/simdunalignedbitpacking.cpp",
    "src/codecfactory.cpp",
    "src/simdbitpacking.cpp",
    "src/varintdecode.c",
    "src/streamvbyte.c",
]
FLAGS = ["-O3", "-g", "-UNDEBUG", "-march=x86-64", "-msse4.2", "-fno-tree-vectorize"]


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def dependencies(path: Path) -> list[Path]:
    return sorted(
        {
            Path(p).resolve()
            for p in shlex.split(path.read_text().replace("\\\n", " ").split(":", 1)[1])
        }
    )


def main() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    original = SOURCES / "fast-pack_FastPFOR"
    require(not pinned(original, PIN), "unexpected upstream submodule")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    directory = ROOT / "build/source-audits/fastpfor-simple-upstream/release"
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "RUNNING",
        "profile": "release_assertions_enabled",
        "upstream_commit": PIN,
        "driver": identity(Path(__file__)),
        "commands": [],
        "builds": [],
        "full_logical_entry_qualified": False,
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
    }

    def persist() -> None:
        REPORT.write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], timeout: int = 180) -> dict:
        persist()
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        item = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(item)
        persist()
        require(result.returncode == 0, shlex.join(command) + "\n" + result.stderr[-4000:])
        return item

    try:
        # Discover only the actual upstream unit target's project dependencies.
        paths = {original / name for name in (*UNITS, "LICENSE", "AUTHORS", "CMakeLists.txt")}
        for number, name in enumerate(UNITS):
            compiler = "/usr/bin/gcc" if name.endswith(".c") else "/usr/bin/g++"
            standard = "-std=c99" if name.endswith(".c") else "-std=c++11"
            dep = directory / f"discover-{number}.d"
            run(
                [
                    compiler,
                    standard,
                    *FLAGS,
                    "-I",
                    str(original / "headers"),
                    "-MM",
                    "-MF",
                    str(dep),
                    str(original / name),
                ]
            )
            paths.update(p for p in dependencies(dep) if p.is_relative_to(original))
        files = []
        for path in sorted(paths):
            name = str(path.relative_to(original))
            destination = VENDOR / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(tracked(original, PIN, name))
            files.append(
                {**identity(destination), "upstream_path": name, "role": "UPSTREAM_UNIT_TEST_ONLY"}
            )
        lock = {
            "schema_version": "tscb.fastpfor-upstream-unit-lock.v1",
            "repository": "https://github.com/fast-pack/FastPFOR",
            "commit": PIN,
            "license": "Apache-2.0",
            "copy_policy": "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH",
            "scope": "COMPLETE_ORIGINAL_UNIT_AND_UNFILTERED_FACTORY_RELEASE_ASSERTIONS_ENABLED",
            "freezer": identity(Path(__file__)),
            "translation_units": UNITS,
            "files": files,
        }
        lock_path = ROOT / "adapters/fastpfor_simple/UPSTREAM_UNIT_LOCK.json"
        lock_path.write_text(json.dumps(lock, indent=2) + "\n")
        report["lock"] = identity(lock_path)
        objects = []
        for number, name in enumerate(UNITS):
            compiler = "/usr/bin/gcc" if name.endswith(".c") else "/usr/bin/g++"
            standard = "-std=c99" if name.endswith(".c") else "-std=c++11"
            obj, dep = directory / f"unit-{number}.o", directory / f"unit-{number}.d"
            run(
                [
                    compiler,
                    standard,
                    *FLAGS,
                    "-I",
                    str(VENDOR / "headers"),
                    "-MD",
                    "-MF",
                    str(dep),
                    "-c",
                    str(VENDOR / name),
                    "-o",
                    str(obj),
                ]
            )
            report["builds"].append(
                {
                    "source": identity(VENDOR / name),
                    "object": identity(obj),
                    "dependency_file": identity(dep),
                    "actual_compiler_closure": [identity(p) for p in dependencies(dep)],
                }
            )
            objects.append(str(obj))
            persist()
            print("BUILT", name, flush=True)
        executable = directory / "upstream-unit"
        run(["/usr/bin/g++", *FLAGS, *objects, "-o", str(executable)])
        report["executable"] = identity(executable)
        print("RUNNING full original upstream unit", flush=True)
        result = run([str(executable)], timeout=1800)
        require(
            "testing...ok. Your code is good." in result["stdout"],
            "upstream terminal success absent",
        )
        report["result"] = result
        report["status"] = "ORIGINAL_FULL_UPSTREAM_UNIT_RELEASE_ASSERTIONS_ENABLED_PASS"
        print(report["status"], flush=True)
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        raise
    finally:
        persist()


if __name__ == "__main__":
    main()
