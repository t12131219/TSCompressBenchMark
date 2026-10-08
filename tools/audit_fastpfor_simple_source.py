"""Audit original Simple-9/16 probe evidence without declaring safe Benchmark admission."""

from __future__ import annotations

import json
import shlex
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from qualify_fastpfor_simple_source import PROFILES, VARIANTS, validate_source

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/fastpfor_simple"
REPORT = "build/source-audits/fastpfor_simple_source_tests.json"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(root: Path = ROOT) -> dict:
    def local(name: str) -> Path:
        path = Path(name)
        if path.is_absolute() and path.is_relative_to(ROOT):
            path = path.relative_to(ROOT)
        return path if path.is_absolute() else root / path

    def check_file(item: dict) -> None:
        require(sha(local(item["path"])) == item["sha256"], "consumed file drift: " + item["path"])

    report = json.loads((root / REPORT).read_text())
    require(
        report["status"] == "SOURCE_PROBES_COMPLETED_KNOWN_UNSAFE_API_PENDING_BOUNDED_SHIM",
        "source probe execution incomplete",
    )
    require(
        report["full_logical_entry_qualified"] is False
        and all(
            report[key] == "PENDING"
            for key in (
                "bounded_abi",
                "python_sdk",
                "benchmark_registration",
                "benchmark_five_layers",
            )
        ),
        "unsafe source probes cannot declare Benchmark qualification",
    )
    require(
        report["qualification_scope"]
        == "ORIGINAL_SIMPLE9_SIMPLE9HACKED_SIMPLE16_MARKED_AND_UNMARKED",
        "scope differs",
    )
    for field, path in (
        ("source_lock", COMPONENT + "/SOURCE_LOCK.json"),
        ("driver", "tools/qualify_fastpfor_simple_source.py"),
        ("driver_dependency", "tools/freeze_fastpfor_simple_source.py"),
        ("guard_source", COMPONENT + "/tests/source_guard.cpp"),
    ):
        require(report[field]["path"] == path, "source evidence path substituted")
        check_file(report[field])
    lock = json.loads((root / COMPONENT / "SOURCE_LOCK.json").read_text())
    require(lock == validate_source(), "source lock differs from current pinned Git bytes")
    require(
        lock["commit"] == "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
        and lock["copy_policy"] == "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH"
        and lock["dirty"] is False
        and lock["submodules"] == []
        and lock["license"]["spdx"] == "Apache-2.0"
        and lock["license"]["status"] == "RUN_ALLOWED",
        "source identity/license differs",
    )
    require(
        lock["freezer_sha256"] == sha(root / "tools/freeze_fastpfor_simple_source.py"),
        "source lock freezer drift",
    )
    require(
        len(lock["files"]) == report["source_file_count"] == 51
        and len({f["path"] for f in lock["files"]}) == 51,
        "source closure incomplete",
    )
    for item in lock["files"]:
        check_file(item)
        require(local(item["path"]).stat().st_size == item["bytes"], "source size differs")
    require(
        report["leak_sanitizer"] == "UNAVAILABLE_IN_PTRACE_HOST_ORIGINAL_FAILURE_RETAINED",
        "LeakSanitizer scope misrepresented",
    )
    retained = report["retained_initial_failures"]
    require(
        {i["path"] for i in retained}
        == {
            f"build/source-audits/{directory}/fastpfor_simple_source_tests.json"
            for directory in ("fastpfor-simple-initial", "fastpfor-simple-lsan-initial")
        }
        and len(retained) == 2,
        "initial failures missing",
    )
    for item in retained:
        check_file(item)
    leak_failure = json.loads(local(retained[1]["path"]).read_text())
    require(
        leak_failure["status"] == "FAIL"
        and any(
            "LeakSanitizer" in c["stderr"] and "ptrace" in c["stderr"]
            for c in leak_failure["commands"]
        ),
        "ptrace limitation lacks original evidence",
    )
    expected_commands = []
    require(
        len(report["builds"]) == 3 and {b["profile"] for b in report["builds"]} == set(PROFILES),
        "build profile universe incomplete",
    )
    headers = str(ROOT / COMPONENT / "vendor/fastpfor/headers")
    google = ROOT / COMPONENT / "third_party/googletest/googletest"
    closure_counts = {}
    for build in report["builds"]:
        profile = build["profile"]
        flags = [
            "-std=c++17",
            "-UNDEBUG",
            "-march=x86-64",
            "-fno-tree-vectorize",
            "-pthread",
            *PROFILES[profile],
            "-I",
            headers,
        ]
        require(build["flags"] == flags, "compiler flags/assertions/ISA differ")
        directory = ROOT / "build/source-audits/fastpfor-simple" / profile
        objects = build["objects"]
        require(
            len(objects) == 4
            and {o["name"] for o in objects}
            == {"guard", "upstream_test", "upstream_main", "gtest"},
            "object universe incomplete",
        )
        for obj in objects:
            name = obj["name"]
            for field, path in (
                ("object", directory / f"{name}.o"),
                ("dependency_file", directory / f"{name}.d"),
            ):
                require(
                    obj[field]["path"] == str(path.relative_to(ROOT)),
                    "object/dependency substituted",
                )
                check_file(obj[field])
            dep = local(obj["dependency_file"]["path"])
            names = shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1])
            actual = {
                str(Path(p).relative_to(ROOT)) if Path(p).is_relative_to(ROOT) else str(Path(p))
                for p in names
            }
            closure = obj["actual_compiler_closure"]
            require(
                actual == {i["path"] for i in closure} and len(closure) == len(actual),
                "actual compiler dependency universe differs",
            )
            for item in closure:
                check_file(item)
            sources = {
                "guard": ROOT / COMPONENT / "tests/source_guard.cpp",
                "upstream_test": ROOT / COMPONENT / "vendor/fastpfor/unittest/test_simple16.cpp",
                "upstream_main": ROOT / COMPONENT / "vendor/fastpfor/unittest/test_driver.cpp",
                "gtest": google / "src/gtest-all.cc",
            }
            source = sources[name]
            require(str(source.relative_to(ROOT)) in actual, "actual translation unit missing")
            if name == "guard":
                require(
                    {
                        f"{COMPONENT}/vendor/fastpfor/headers/{header}"
                        for header in (
                            "simple9.h",
                            "simple16.h",
                            "common.h",
                            "util.h",
                            "codecs.h",
                            "bitpacking.h",
                            "bitpackinghelpers.h",
                        )
                    }
                    <= actual,
                    "actual algorithm dependency missing",
                )
            closure_counts[profile + "/" + name] = len(actual)
            expected_commands.append(
                [
                    "g++",
                    *flags,
                    "-I",
                    str(google / "include"),
                    "-I",
                    str(google),
                    "-MD",
                    "-MF",
                    str(directory / f"{name}.d"),
                    "-c",
                    str(source),
                    "-o",
                    str(directory / f"{name}.o"),
                ]
            )
        for field, name, members in (
            ("guard", "source-guard", ("guard",)),
            ("upstream", "upstream-simple16", ("upstream_test", "upstream_main", "gtest")),
        ):
            require(
                build[field]["path"] == str((directory / name).relative_to(ROOT)),
                "executable substituted",
            )
            check_file(build[field])
            expected_commands.append(
                [
                    "g++",
                    *flags,
                    *(str(directory / f"{n}.o") for n in members),
                    "-o",
                    str(directory / name),
                ]
            )
        symbols = subprocess.run(
            ["nm", "-u", str(local(build["guard"]["path"]))],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        require(
            ("__asan_init" in symbols) is (profile == "sanitizer")
            and ("__ubsan_handle" in symbols) is (profile == "sanitizer"),
            "actual guard sanitizer instrumentation differs",
        )
    upstream = report["upstream_tests"]
    require(
        len(upstream) == 3 and {u["profile"] for u in upstream} == set(PROFILES),
        "original upstream test universe incomplete",
    )
    for test in upstream:
        check_file(test["junit"])
        suite = ET.parse(local(test["junit"]["path"])).getroot()
        require(
            suite.get("tests") == "1"
            and suite.get("failures") == "0"
            and suite.get("disabled") == "0"
            and test["test_count"] == 1
            and len(suite.findall(".//testcase")) == 1
            and not suite.findall(".//failure")
            and not suite.findall(".//skipped")
            and test["result"]["returncode"] == 0,
            "original upstream test failed/skipped",
        )
        case = suite.find(".//testcase")
        require(
            case.get("name") == "DecodesWithUnknownLength"
            and case.get("classname") == "Simple16Test",
            "original upstream test substituted",
        )
        directory = ROOT / "build/source-audits/fastpfor-simple" / test["profile"]
        command = [
            str(directory / "upstream-simple16"),
            "--gtest_filter=Simple16Test.DecodesWithUnknownLength",
            "--gtest_output=xml:" + str(directory / "upstream.xml"),
        ]
        require(test["result"]["command"] == command, "upstream command differs")
        expected_commands.append(command)
    probes = report["probes"]
    universe = set()
    for profile in PROFILES:
        for codec, marked in VARIANTS:
            modes = {"normal", "range-rejection", "decode-tail", "decode-truncated", "encode-short"}
            if codec != "simple16":
                modes.add("invalid-selector")
            if codec == "simple9hacked":
                modes.add("hacked-tail-read")
            universe.update((profile, codec, marked == "1", mode) for mode in modes)
    require(
        len(probes) == len(universe) == 108
        and {(p["profile"], p["codec"], p["mark_length"], p["mode"]) for p in probes} == universe,
        "source probe universe incomplete/duplicated",
    )
    for item in probes:
        result, mode = item["result"], item["mode"]
        command = [
            str(ROOT / "build/source-audits/fastpfor-simple" / item["profile"] / "source-guard"),
            item["codec"],
            "1" if item["mark_length"] else "0",
            mode,
        ]
        require(result["command"] == command, "probe command differs")
        expected_commands.append(command)
        if mode in ("normal", "range-rejection"):
            require(
                item["status"] == "PASS" and result["returncode"] == 0,
                "valid source wire/range probe failed",
            )
            observed = json.loads(result["stdout"])
            require(observed == item["observation"], "observed source output differs")
            if mode == "normal":
                legal = (
                    16
                    if item["codec"] == "simple16"
                    else 10
                    if item["codec"] == "simple9hacked"
                    else 9
                )
                counts = observed["selector_counts"]
                require(
                    observed["status"] == "PASS"
                    and observed["cases"] == 5075
                    and observed["input_padding_words"] == observed["decode_headroom_words"] == 28
                    and len(counts) == 16
                    and all(v > 0 for v in counts[:legal])
                    and all(v == 0 for v in counts[legal:]),
                    "selector/boundary wire coverage missing",
                )
            else:
                require(
                    observed
                    == {"status": "RANGE_REJECTED", "output_unchanged": not item["mark_length"]},
                    "range/partial-output evidence differs",
                )
        else:
            code, error = result["returncode"], result["stderr"]
            require(
                item["status"] == "KNOWN_UNSAFE_ORIGINAL_API_CONFIRMED"
                and (
                    code in (-11, -6)
                    or (
                        code not in (0, 2)
                        and ("AddressSanitizer" in error or "runtime error:" in error)
                    )
                ),
                "unsafe original API failure erased or unsupported",
            )
            if item["profile"] == "sanitizer":
                require(
                    "AddressSanitizer" in error or "runtime error:" in error,
                    "sanitizer probe lacks an instrumented failure report",
                )
    commands = report["commands"]
    require(
        len(commands) == len(expected_commands)
        and len({tuple(c["command"]) for c in commands}) == len(commands)
        and {tuple(c["command"]) for c in commands} == {tuple(c) for c in expected_commands},
        "build/test command universe differs",
    )
    for command in commands:
        require(
            command["sanitizer_environment"]
            == {
                "ASAN_OPTIONS": "detect_leaks=0:abort_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
            "sanitizer runtime options differ",
        )
        if command["command"][0] == "g++":
            require(command["returncode"] == 0, "failed compilation/link admitted")
    by_command = {tuple(command["command"]): command for command in commands}
    require(
        all(
            item["result"] == by_command[tuple(item["result"]["command"])]
            for item in [*upstream, *probes]
        ),
        "probe result differs from raw command output",
    )
    require(
        report["upstream_test_runs"] == 3
        and report["normal_wire_runs"] == 18
        and report["normal_wire_cases"] == 91350
        and report["range_rejection_runs"] == 18
        and report["original_unsafe_probe_count"] == 72,
        "probe summary differs",
    )
    return {
        "status": "PASS",
        "scope": "SOURCE_PROBE_EVIDENCE_WITH_KNOWN_UNSAFE_ORIGINAL_APIS",
        "report_sha256": sha(root / REPORT),
        "source_lock_sha256": sha(root / COMPONENT / "SOURCE_LOCK.json"),
        "upstream_test_runs": 3,
        "normal_wire_cases": 91350,
        "original_unsafe_probe_count": 72,
        "actual_compiler_dependency_counts": closure_counts,
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "leak_sanitizer": report["leak_sanitizer"],
        "auditor_sha256": sha(Path(__file__)),
        "audit_dependency_sha256": sha(root / "tools/qualify_fastpfor_simple_source.py"),
    }


if __name__ == "__main__":
    output = ROOT / "build/source-audits/fastpfor_simple_source_current_audit.json"
    try:
        result = audit()
    except Exception as error:
        output.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
