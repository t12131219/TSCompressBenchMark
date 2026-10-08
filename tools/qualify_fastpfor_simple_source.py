"""Exercise pinned Simple-9/16 source APIs; retain unsafe original API evidence."""

from __future__ import annotations

import json
import os
import resource
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from freeze_fastpfor_simple_source import (
    ADAPTER,
    GTEST_PIN,
    PIN,
    ROOT,
    SOURCES,
    git,
    sha,
    tracked,
)

PROFILES = {
    "release": ["-O3"],
    "debug": ["-O0", "-g"],
    "sanitizer": [
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
        "-fno-pie",
        "-no-pie",
    ],
}
VARIANTS = [
    (codec, marked) for codec in ("simple9", "simple9hacked", "simple16") for marked in ("0", "1")
]


def record(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path.read_bytes()),
    }


def dependencies(path: Path) -> list[dict]:
    body = path.read_text().replace("\\\n", " ").split(":", 1)[1]
    return [record(p) for p in sorted({Path(p).resolve() for p in shlex.split(body)})]


def validate_source() -> dict:
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    if lock["commit"] != PIN or lock["test_dependency"]["commit"] != GTEST_PIN:
        raise RuntimeError("source pin differs")
    if lock["freezer_sha256"] != sha(
        (ROOT / "tools/freeze_fastpfor_simple_source.py").read_bytes()
    ):
        raise RuntimeError("source freezer changed")
    for entry in lock["files"]:
        repo, commit = (
            (SOURCES / "and-gue_NeaTS", GTEST_PIN)
            if entry["role"] == "UPSTREAM_TEST_ONLY"
            else (SOURCES / "fast-pack_FastPFOR", PIN)
        )
        data = (ROOT / entry["path"]).read_bytes()
        if sha(data) != entry["sha256"] or data != tracked(repo, commit, entry["upstream_path"]):
            raise RuntimeError("source/dependency drift: " + entry["path"])
    for name, pin in (("fast-pack_FastPFOR", PIN), ("and-gue_NeaTS", GTEST_PIN)):
        repo = SOURCES / name
        if git(repo, "rev-parse", "HEAD").decode().strip() != pin or git(
            repo, "status", "--porcelain"
        ):
            raise RuntimeError("source repository changed")
    return lock


def main() -> None:
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    lock = validate_source()
    output = ROOT / "build/source-audits/fastpfor_simple_source_tests.json"
    base = ROOT / "build/source-audits/fastpfor-simple"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "status": "RUNNING",
        "source_lock": record(ADAPTER / "SOURCE_LOCK.json"),
        "driver": record(Path(__file__)),
        "driver_dependency": record(ROOT / "tools/freeze_fastpfor_simple_source.py"),
        "guard_source": record(ADAPTER / "tests/source_guard.cpp"),
        "compiler": subprocess.run(
            ["g++", "--version"], capture_output=True, text=True, check=True
        ).stdout,
        "source_file_count": len(lock["files"]),
        "commands": [],
        "builds": [],
        "upstream_tests": [],
        "probes": [],
        "full_logical_entry_qualified": False,
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "leak_sanitizer": "UNAVAILABLE_IN_PTRACE_HOST_ORIGINAL_FAILURE_RETAINED",
        "retained_initial_failures": [
            record(ROOT / "build/source-audits" / directory / "fastpfor_simple_source_tests.json")
            for directory in ("fastpfor-simple-initial", "fastpfor-simple-lsan-initial")
        ],
    }

    def save() -> None:
        output.write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], *, check: bool = True, timeout: int = 180) -> dict:
        environment = dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        )
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=environment
        )
        item = {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "sanitizer_environment": {
                "ASAN_OPTIONS": environment["ASAN_OPTIONS"],
                "UBSAN_OPTIONS": environment["UBSAN_OPTIONS"],
            },
        }
        report["commands"].append(item)
        save()
        if check and result.returncode:
            raise RuntimeError("command failed: " + shlex.join(command) + "\n" + result.stderr)
        return item

    save()
    try:
        headers = ADAPTER / "vendor/fastpfor/headers"
        google = ADAPTER / "third_party/googletest/googletest"
        for profile, options in PROFILES.items():
            directory = base / profile
            directory.mkdir(parents=True, exist_ok=True)
            flags = [
                "-std=c++17",
                "-UNDEBUG",
                "-march=x86-64",
                "-fno-tree-vectorize",
                "-pthread",
                *options,
                "-I",
                str(headers),
            ]
            units = [
                ("guard", ADAPTER / "tests/source_guard.cpp"),
                ("upstream_test", ADAPTER / "vendor/fastpfor/unittest/test_simple16.cpp"),
                ("upstream_main", ADAPTER / "vendor/fastpfor/unittest/test_driver.cpp"),
                ("gtest", google / "src/gtest-all.cc"),
            ]
            objects = []
            for name, source in units:
                obj, dependency = directory / f"{name}.o", directory / f"{name}.d"
                run(
                    [
                        "g++",
                        *flags,
                        "-I",
                        str(google / "include"),
                        "-I",
                        str(google),
                        "-MD",
                        "-MF",
                        str(dependency),
                        "-c",
                        str(source),
                        "-o",
                        str(obj),
                    ]
                )
                objects.append(
                    {
                        "name": name,
                        "object": record(obj),
                        "dependency_file": record(dependency),
                        "actual_compiler_closure": dependencies(dependency),
                    }
                )
            guard, upstream = directory / "source-guard", directory / "upstream-simple16"
            run(["g++", *flags, str(directory / "guard.o"), "-o", str(guard)])
            run(
                [
                    "g++",
                    *flags,
                    *(
                        str(directory / (n + ".o"))
                        for n in ("upstream_test", "upstream_main", "gtest")
                    ),
                    "-o",
                    str(upstream),
                ]
            )
            report["builds"].append(
                {
                    "profile": profile,
                    "flags": flags,
                    "objects": objects,
                    "guard": record(guard),
                    "upstream": record(upstream),
                }
            )
            xml = directory / "upstream.xml"
            result = run(
                [
                    str(upstream),
                    "--gtest_filter=Simple16Test.DecodesWithUnknownLength",
                    "--gtest_output=xml:" + str(xml),
                ]
            )
            suite = ET.parse(xml).getroot()
            if not (
                suite.get("tests") == "1"
                and suite.get("failures") == "0"
                and suite.get("disabled") == "0"
            ):
                raise RuntimeError("original upstream Simple16 test failed/skipped")
            report["upstream_tests"].append(
                {"profile": profile, "result": result, "junit": record(xml), "test_count": 1}
            )
            for codec, marked in VARIANTS:
                modes = [
                    "normal",
                    "range-rejection",
                    "decode-tail",
                    "decode-truncated",
                    "encode-short",
                ]
                if codec != "simple16":
                    modes.append("invalid-selector")
                if codec == "simple9hacked":
                    modes.append("hacked-tail-read")
                for mode in modes:
                    result = run([str(guard), codec, marked, mode], check=False)
                    item = {
                        "profile": profile,
                        "codec": codec,
                        "mark_length": marked == "1",
                        "mode": mode,
                        "result": result,
                    }
                    if mode in ("normal", "range-rejection"):
                        if result["returncode"] != 0:
                            raise RuntimeError("valid source wire/range test failed: " + str(item))
                        observation = json.loads(result["stdout"])
                        if mode == "normal":
                            if observation["status"] != "PASS" or observation["cases"] != 5075:
                                raise RuntimeError("source wire matrix incomplete")
                        elif observation != {
                            "status": "RANGE_REJECTED",
                            "output_unchanged": marked == "0",
                        }:
                            raise RuntimeError("source range diagnostic differs")
                        item.update(status="PASS", observation=observation)
                    else:
                        # Probe exit 2 means it survived or the harness failed, never
                        # evidence of a native fault. Guard SIGSEGV/ASan/UBSan only.
                        code, error = result["returncode"], result["stderr"]
                        if not (
                            code in (-11, -6)
                            or (
                                code not in (0, 2)
                                and ("AddressSanitizer" in error or "runtime error:" in error)
                            )
                        ):
                            raise RuntimeError(
                                "expected source limitation not confirmed: " + str(item)
                            )
                        item["status"] = "KNOWN_UNSAFE_ORIGINAL_API_CONFIRMED"
                    report["probes"].append(item)
                    save()
            print("DONE", profile, flush=True)
        validate_source()
        report.update(
            status="SOURCE_PROBES_COMPLETED_KNOWN_UNSAFE_API_PENDING_BOUNDED_SHIM",
            upstream_test_runs=3,
            normal_wire_runs=18,
            normal_wire_cases=91350,
            original_unsafe_probe_count=72,
            range_rejection_runs=18,
            qualification_scope="ORIGINAL_SIMPLE9_SIMPLE9HACKED_SIMPLE16_MARKED_AND_UNMARKED",
        )
        save()
    except Exception as error:
        report.update(status="FAIL", error=str(error))
        save()
        raise
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "status",
                    "upstream_test_runs",
                    "normal_wire_cases",
                    "original_unsafe_probe_count",
                )
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
