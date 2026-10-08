"""Independently verify the entire original release unit target and its closure."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

from audit_fastpfor_simple_source import require, sha
from freeze_fastpfor_simple_source import PIN, SOURCES, pinned, tracked

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/fastpfor_simple"
REPORT = "build/source-audits/fastpfor_simple_upstream_tests.json"
UNITS = (
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
)
FLAGS = ["-O3", "-g", "-UNDEBUG", "-march=x86-64", "-msse4.2", "-fno-tree-vectorize"]


def audit(root: Path = ROOT) -> dict:
    report = json.loads((root / REPORT).read_text())
    require(
        report["status"] == "ORIGINAL_FULL_UPSTREAM_UNIT_RELEASE_ASSERTIONS_ENABLED_PASS"
        and report["profile"] == "release_assertions_enabled"
        and report["upstream_commit"] == PIN,
        "full upstream execution missing",
    )
    require(
        report["full_logical_entry_qualified"] is False
        and report["python_sdk"] == report["benchmark_five_layers"] == "PENDING",
        "upstream unit cannot qualify Benchmark",
    )

    def local(name: str) -> Path:
        path = Path(name)
        return (
            root / path.relative_to(ROOT)
            if path.is_absolute() and path.is_relative_to(ROOT)
            else path
            if path.is_absolute()
            else root / path
        )

    def check(item: dict) -> None:
        require(
            sha(local(item["path"])) == item["sha256"],
            "upstream consumed dependency drift: " + item["path"],
        )

    require(
        report["driver"]["path"] == "tools/qualify_fastpfor_simple_upstream.py",
        "upstream driver substituted",
    )
    check(report["driver"])
    lock_path = COMPONENT + "/UPSTREAM_UNIT_LOCK.json"
    require(report["lock"]["path"] == lock_path, "upstream lock substituted")
    check(report["lock"])
    lock = json.loads((root / lock_path).read_text())
    require(
        lock["repository"] == "https://github.com/fast-pack/FastPFOR"
        and lock["commit"] == PIN
        and lock["copy_policy"] == "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH"
        and lock["license"] == "Apache-2.0"
        and lock["translation_units"] == list(UNITS),
        "upstream source identity differs",
    )
    require(lock["freezer"] == report["driver"], "upstream freezer changed")
    original = SOURCES / "fast-pack_FastPFOR"
    require(not pinned(original, PIN), "unexpected upstream submodule")
    require(
        len(lock["files"]) == len({f["path"] for f in lock["files"]}) == 55,
        "upstream source closure incomplete",
    )
    for item in lock["files"]:
        check(item)
        require(
            item["role"] == "UPSTREAM_UNIT_TEST_ONLY"
            and local(item["path"]).read_bytes() == tracked(original, PIN, item["upstream_path"]),
            "original upstream source filtered or patched",
        )
    vendor = ROOT / COMPONENT / "third_party/fastpfor_upstream_unit"
    directory = ROOT / "build/source-audits/fastpfor-simple-upstream/release"
    commands, objects, actual = [], [], set()
    require(len(report["builds"]) == len(UNITS), "full unit object universe incomplete")
    for i, name in enumerate(UNITS):
        compiler = "/usr/bin/gcc" if name.endswith(".c") else "/usr/bin/g++"
        standard = "-std=c99" if name.endswith(".c") else "-std=c++11"
        commands.append(
            [
                compiler,
                standard,
                *FLAGS,
                "-I",
                str(original / "headers"),
                "-MM",
                "-MF",
                str(directory / f"discover-{i}.d"),
                str(original / name),
            ]
        )
    for i, (name, build) in enumerate(zip(UNITS, report["builds"], strict=True)):
        for field, expected in (
            ("source", vendor / name),
            ("object", directory / f"unit-{i}.o"),
            ("dependency_file", directory / f"unit-{i}.d"),
        ):
            require(
                build[field]["path"] == str(expected.relative_to(ROOT)),
                "upstream unit object/source substituted",
            )
            check(build[field])
        paths = {
            Path(p).resolve()
            for p in shlex.split(
                local(build["dependency_file"]["path"])
                .read_text()
                .replace("\\\n", " ")
                .split(":", 1)[1]
            )
        }
        expected_paths = {
            str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in paths
        }
        require(
            expected_paths == {p["path"] for p in build["actual_compiler_closure"]}
            and len(expected_paths) == len(build["actual_compiler_closure"]),
            "actual upstream compiler closure differs",
        )
        for item in build["actual_compiler_closure"]:
            check(item)
        actual.update(
            p for p in expected_paths if p.startswith(str(vendor.relative_to(ROOT)) + "/")
        )
        compiler = "/usr/bin/gcc" if name.endswith(".c") else "/usr/bin/g++"
        standard = "-std=c99" if name.endswith(".c") else "-std=c++11"
        obj = str(directory / f"unit-{i}.o")
        objects.append(obj)
        commands.append(
            [
                compiler,
                standard,
                *FLAGS,
                "-I",
                str(vendor / "headers"),
                "-MD",
                "-MF",
                str(directory / f"unit-{i}.d"),
                "-c",
                str(vendor / name),
                "-o",
                obj,
            ]
        )
    require(
        actual
        == {
            f["path"]
            for f in lock["files"]
            if f["upstream_path"] not in {"LICENSE", "AUTHORS", "CMakeLists.txt"}
        },
        "upstream source lock does not match actual target closure",
    )
    executable = directory / "upstream-unit"
    require(
        report["executable"]["path"] == str(executable.relative_to(ROOT)),
        "upstream executable substituted",
    )
    check(report["executable"])
    commands += [["/usr/bin/g++", *FLAGS, *objects, "-o", str(executable)], [str(executable)]]
    require(
        [c["command"] for c in report["commands"]] == commands
        and all(c["returncode"] == 0 for c in report["commands"]),
        "full upstream build/run commands incomplete",
    )
    require(report["result"] == report["commands"][-1], "upstream raw observation differs")
    output = report["result"]["stdout"]
    require(
        re.findall(r"testing\.\.\. b = (\d+)", output) == [str(i) for i in range(29)],
        "full upstream width loops incomplete",
    )
    require(
        re.findall(r"length = (\d+)", output) == [str(2**i) for i in (5, 10, 15, 20, 25)],
        "full upstream Zipf sizes incomplete",
    )
    require(
        all(
            output.count(name + " encoding ... decoding ... ok!") == 5
            for name in ("Simple9", "Simple16")
        )
        and output.endswith("testing...ok. Your code is good.\n"),
        "upstream Simple tests or terminal success absent",
    )
    return {
        "status": "PASS",
        "scope": "COMPLETE_ORIGINAL_UPSTREAM_UNIT_RELEASE_ASSERTIONS_ENABLED",
        "source_file_count": 55,
        "source_lock_sha256": sha(root / lock_path),
        "upstream_report_sha256": sha(root / REPORT),
        "simple9_and_simple16_zipf_cases": 10,
        "all_widths": list(range(29)),
        "other_profiles": "NOT_RUN_COMPLETE_FACTORY_SEPARATE_NATIVE_THREE_PROFILE_EVIDENCE",
        "full_logical_entry_qualified": False,
        "auditor_sha256": sha(Path(__file__)),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/fastpfor_simple_upstream_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
