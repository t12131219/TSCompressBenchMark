"""Apply the recorded patch out of tree and test every original API/unit profile."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from freeze_littleintpacker_source import ADAPTER, APIS, ROOT
from prepare_littleintpacker_patch import EXPECTED, corrected
from qualify_littleintpacker_source import (
    BASELINE,
    PROFILES,
    SOURCES,
    dependency_files,
    identity,
    require,
    sha,
)

OUT = ROOT / "build/source-audits/littleintpacker-patched"
REPORT = ROOT / "build/source-audits/littleintpacker_patched_tests.json"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    source_lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    patch_lock = json.loads((ADAPTER / "PATCH_LOCK.json").read_text())
    require(
        sha(ADAPTER / "SOURCE_LOCK.json") == patch_lock["source_lock_sha256"], "source lock drift"
    )
    require(sha(ROOT / patch_lock["patch"]["path"]) == patch_lock["patch"]["sha256"], "patch drift")
    require(
        sha(ROOT / "tools/prepare_littleintpacker_patch.py") == patch_lock["generator_sha256"],
        "patch generator drift",
    )
    original_report = ROOT / "build/source-audits/littleintpacker_source_tests.json"
    original = json.loads(original_report.read_text())
    require(
        original["status"] == "ORIGINAL_SOURCE_TESTS_EXECUTED_BOUNDED_ABI_PENDING",
        "original failure evidence not completed",
    )
    document = {
        "status": "RUNNING",
        "commands": [],
        "profiles": {},
        "driver": identity(Path(__file__)),
        "source_lock": identity(ADAPTER / "SOURCE_LOCK.json"),
        "patch_lock": identity(ADAPTER / "PATCH_LOCK.json"),
        "original_report": identity(original_report),
        "original_failures_retained": True,
        "full_logical_entries_qualified": False,
    }

    def save() -> None:
        REPORT.write_text(json.dumps(document, indent=2) + "\n")

    def run(command: list[str], success: bool = True) -> dict:
        process = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=240,
            env=dict(
                os.environ,
                ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
            ),
        )
        result = {
            "command": command,
            "returncode": process.returncode,
            "stdout": process.stdout,
            "stderr": process.stderr,
        }
        document["commands"].append(result)
        save()
        if success:
            require(process.returncode == 0, "patched command failed: " + str(command))
        return result

    save()
    try:
        generated = OUT / "generated"
        for item in source_lock["files"]:
            source = ROOT / item["path"]
            require(sha(source) == item["sha256"], "original vendor changed")
            target = generated / item["upstream_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        run(
            [
                "/usr/bin/patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(generated),
                "-i",
                str(ROOT / patch_lock["patch"]["path"]),
            ]
        )
        for name in EXPECTED:
            result, _ = corrected((ADAPTER / "vendor/littleintpacker/src" / name).read_text(), name)
            require(
                (generated / "src" / name).read_text() == result, "actual applied patch differs"
            )
        generated_files = [identity(p) for p in sorted(generated.rglob("*")) if p.is_file()]
        document["generated_source_files"] = generated_files
        for profile, options in PROFILES.items():
            directory = OUT / profile
            directory.mkdir(parents=True, exist_ok=True)
            objects, builds, dependencies = [], [], set()
            for name, isa in SOURCES.items():
                source = generated / "src" / name
                obj, dep = directory / (name + ".o"), directory / (name + ".d")
                command = [
                    "/usr/bin/gcc",
                    "-std=c99",
                    "-Wall",
                    "-Wextra",
                    *options,
                    *BASELINE,
                    *isa,
                    "-I",
                    str(generated / "include"),
                    "-MD",
                    "-MF",
                    str(dep),
                    "-c",
                    str(source),
                    "-o",
                    str(obj),
                ]
                run(command)
                closure = dependency_files(dep)
                dependencies.update(closure)
                builds.append(
                    {
                        "source": identity(source),
                        "object": identity(obj),
                        "dependency": identity(dep),
                        "command": command,
                        "compiler_closure": [identity(p) for p in closure],
                    }
                )
                objects.append(obj)
            executions = {}
            for target, source in (
                ("unit", generated / "tests/unit.c"),
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
                        str(generated / "include"),
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
                result = run([str(exe)])
                expected = (
                    "All tests OK!" if target == "unit" else "MATRIX_DONE cases=18975 failures=0"
                )
                require(expected in result["stdout"], "complete patched unit/API matrix missing")
                executions[target] = {
                    "status": "PASS",
                    "artifact": identity(exe),
                    "dependency": identity(dep),
                    "result": result,
                }
            probes = []
            for api, name in enumerate(APIS):
                result = run([str(directory / "api-probe"), str(api), "odd-width-multiple-blocks"])
                probes.append({"api": name, "result": result, "status": "PASS"})
            document["profiles"][profile] = {
                "builds": builds,
                "executions": executions,
                "alignment_probes": probes,
                "compiler_closure": [identity(p) for p in sorted(dependencies)],
            }
            save()
            print("PATCHED_PROFILE_PASS", profile, flush=True)
        require(
            all(sha(ROOT / item["path"]) == item["sha256"] for item in generated_files),
            "generated source changed during execution",
        )
        document.update(
            status="PATCHED_COMPLETE_UPSTREAM_AND_SOURCE_API_MATRIX_PASS",
            api_matrix_cases=56925,
            upstream_unit_filtered=False,
            source_padding_required=True,
            bounded_abi="PENDING",
            python_sdk="PENDING",
            benchmark_five_layers="PENDING",
            leak_sanitizer="NOT_QUALIFIED_DETECT_LEAKS_ZERO",
        )
    except Exception as error:
        document.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
