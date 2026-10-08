"""Execute functional matrices against each shipped library, preserving unqualified boundaries."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/fastpfor_simple8b_rle"
OUT = ROOT / "build/source-audits/fastpfor-simple8b-rle-native-smoke-20261007-2"


def identity(path: Path) -> dict:
    import hashlib

    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    if OUT.exists():
        raise RuntimeError("preserve prior native smoke evidence")
    OUT.mkdir(parents=True)
    (OUT / "driver.py").write_bytes(Path(__file__).read_bytes())
    report = {
        "status": "RUNNING",
        "driver": identity(Path(__file__)),
        "commands": [],
        "profiles": [],
        "actual_cpu_affinity": sorted(os.sched_getaffinity(0)),
        "native_safety_and_fault_qualification": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }

    def save() -> None:
        (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str) -> dict:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            env=dict(
                os.environ,
                ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
            ),
        )
        item = {
            "name": name,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(item)
        (OUT / (name + ".json")).write_text(json.dumps(item, indent=2) + "\n")
        save()
        if result.returncode:
            raise RuntimeError(name + " failed: " + result.stderr[-4000:])
        return item

    save()
    try:
        if report["actual_cpu_affinity"] != [2]:
            raise RuntimeError("auxiliary native tests require CPU2")
        for profile, options in (
            ("release", ["-O3"]),
            ("debug", ["-O0", "-g"]),
            (
                "sanitizer",
                [
                    "-O1",
                    "-g",
                    "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all",
                    "-fno-omit-frame-pointer",
                ],
            ),
        ):
            directory = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile
            record_path = directory / "build-record.json"
            build = json.loads(record_path.read_text())
            if (
                build["status"] != "PASS"
                or identity(ROOT / build["artifact"]["path"]) != build["artifact"]
            ):
                raise RuntimeError("shipped library drift")
            exe, dep = OUT / ("smoke-" + profile), OUT / ("smoke-" + profile + ".d")
            source = ADAPTER / "tests/native_smoke.cpp"
            run(
                [
                    "/usr/bin/g++",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-UNDEBUG",
                    "-fno-pie",
                    "-no-pie",
                    "-march=x86-64",
                    "-fno-tree-vectorize",
                    *options,
                    "-I",
                    str(ROOT / "native/include"),
                    "-I",
                    str(directory / "generated/headers"),
                    "-MD",
                    "-MF",
                    str(dep),
                    str(source),
                    "-L",
                    str(directory),
                    "-ltscb_fastpfor_simple8b_rle",
                    "-Wl,-rpath," + str(directory),
                    "-o",
                    str(exe),
                ],
                profile + "-compile",
            )
            result = run([str(exe)], profile + "-execute")
            symbols = run(
                ["/usr/bin/nm", "-C", "--defined-only", str(exe)], profile + "-defined-symbols"
            )
            if "FastPForLib::Simple8b" in symbols["stdout"]:
                raise RuntimeError(
                    "test executable can substitute the native source implementation"
                )
            observation = json.loads(result["stdout"])
            if observation != {
                "status": "PASS",
                "native_functional_cases": 26928,
                "full_native_qualification": False,
            }:
                raise RuntimeError("native functional matrix differs")
            closure = sorted(
                {
                    Path(p).resolve()
                    for p in shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1])
                }
            )
            report["profiles"].append(
                {
                    "profile": profile,
                    "build_record": identity(record_path),
                    "library": build["artifact"],
                    "executable": identity(exe),
                    "dependency_file": identity(dep),
                    "compiler_closure": [identity(p) for p in closure],
                    "observation": observation,
                    "result": result,
                }
            )
            save()
            print(
                "NATIVE_FUNCTIONAL_PASS",
                profile,
                observation["native_functional_cases"],
                flush=True,
            )
        report.update(
            status="FUNCTIONAL_SHARED_LIBRARY_MATRICES_PASS_NATIVE_QUALIFICATION_PENDING",
            native_functional_cases=80784,
            leak_sanitizer="NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        )
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
