"""Qualify frozen standalone/binding tests without inheriting stale build PASS.

The evidence is scoped API/correctness validation, not fresh source-language
parity or complete G0-G6 acceptance. All output goes to a new evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from build_completed_rewrite import KINDS

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def local(root: Path, filename: str) -> Path:
    path = Path(filename)
    return path if path.is_absolute() else root / path


def verify_files(root: Path, entries: list[dict], label: str) -> set[Path]:
    require(bool(entries), label + " missing; rebuild required")
    paths = set()
    for entry in entries:
        path = local(root, entry["path"])
        require(path.is_file() and sha(path) == entry["sha256"], label + " drift: " + str(path))
        require(path.resolve() not in paths, label + " contains duplicate paths")
        paths.add(path.resolve())
    return paths


def compiler_dependencies(folder: Path) -> set[Path]:
    dependencies = set()
    depfiles = sorted((folder / "cmake").rglob("*.o.d"))
    require(bool(depfiles), "actual compiler dependency files missing; rebuild required")
    commands = json.loads((folder / "cmake/compile_commands.json").read_text())
    require(bool(commands), "compile command universe empty")
    for command in commands:
        flags = command.get("arguments") or shlex.split(command["command"])
        require(
            "-o" in flags and flags.index("-o") + 1 < len(flags),
            "compile command has no object output",
        )
        directory = Path(command["directory"])
        path = local(directory, flags[flags.index("-o") + 1] + ".d")
        require(path.is_file(), "compiled TU dependency file missing: " + str(path))
        content = path.read_text().replace("\\\n", " ")
        require(":" in content, "malformed compiler dependency file: " + str(path))
        declared = {
            local(directory, filename).resolve()
            for filename in shlex.split(content.split(":", 1)[1])
        }
        require(
            local(directory, command["file"]).resolve() in declared,
            "compiled TU absent from its dependency file",
        )
    for path in depfiles:
        content = path.read_text().replace("\\\n", " ")
        require(":" in content, "malformed compiler dependency file: " + str(path))
        dependencies.update(
            local(folder / "cmake", filename).resolve()
            for filename in shlex.split(content.split(":", 1)[1])
        )
    return dependencies


def ctest_inventory(folder: Path) -> list[dict]:
    process = subprocess.run(
        ["ctest", "--test-dir", str(folder / "cmake"), "--show-only=json-v1"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    require(process.returncode == 0, "CTest inventory failed: " + process.stderr[-1000:])
    tests = json.loads(process.stdout).get("tests", [])
    require(bool(tests), "CTest has no tests; qualification cannot pass")
    names = [test.get("name") for test in tests]
    require(len(set(names)) == len(names), "CTest inventory has duplicate test names")
    require("framework_binding_qualification" in names, "framework binding test missing")
    require(len(tests) > 1, "standalone tests missing")
    require(all(test.get("command") for test in tests), "CTest test has no executable command")
    return tests


def runtime_paths(artifact: Path) -> set[Path]:
    process = subprocess.run(["ldd", str(artifact)], capture_output=True, text=True, timeout=60)
    require(
        process.returncode == 0 and "not found" not in process.stdout,
        "unresolved runtime dependencies: " + str(artifact),
    )
    return {Path(path).resolve() for path in re.findall(r"(?:=>\s+)?(/\S+)\s+\(", process.stdout)}


def verify_build(root: Path, algorithm: str, profile: str, folder: Path) -> dict:
    record_path = folder / "build-record.json"
    record = json.loads(record_path.read_text())
    require(
        record.get("algorithm") == algorithm and record.get("profile") == profile,
        "build algorithm/profile differs",
    )
    lock_path = root / "adapters/completed_rewrites/FROZEN_SOURCES.json"
    require(record["frozen_sources_sha256"] == sha(lock_path), "frozen source lock drift")
    frozen = json.loads(lock_path.read_text())["packages"][algorithm]["files"]
    verify_files(root, frozen, "frozen vendor source")
    for field, path in (
        ("build_driver_sha256", root / "tools/build_completed_rewrite.py"),
        ("build_recipe_sha256", folder / "recipe/CMakeLists.txt"),
        ("compile_commands_sha256", folder / "cmake/compile_commands.json"),
        (
            "qualification_source_sha256",
            root / "adapters/completed_rewrites/tests/qualification.cpp",
        ),
    ):
        require(record[field] == sha(path), "build input drift: " + field)
    binding = verify_files(root, record["binding_sources"], "binding source")
    require(
        binding
        == {
            (root / "adapters/completed_rewrites/native/binding.cpp").resolve(),
            (root / "adapters/completed_rewrites/native/binding.hpp").resolve(),
        },
        "binding source universe differs",
    )
    artifact = local(root, record["artifact"])
    require(sha(artifact) == record["artifact_sha256"], "codec artifact drift")
    closure = verify_files(root, record.get("compiled_source_closure", []), "compiler closure")
    require(closure == compiler_dependencies(folder), "actual compiler dependency universe differs")
    commands = json.loads((folder / "cmake/compile_commands.json").read_text())
    require(bool(commands), "compile command universe empty")
    for command in commands:
        flags = command.get("arguments") or shlex.split(command["command"])
        require(
            local(Path(command["directory"]), command["file"]).resolve() in closure,
            "compiled source absent from verified dependency closure",
        )
        require(
            "-ffast-math" not in flags and "-Ofast" not in flags,
            "unqualified floating-point compiler flags",
        )
        if profile == "sanitizer":
            require(
                "-fsanitize=address,undefined" in flags, "sanitizer compile instrumentation absent"
            )
    runtime = verify_files(root, record["runtime_dependencies"], "runtime dependency")
    require(runtime_paths(artifact) <= runtime, "actual codec dynamic dependency is not locked")
    pinned = record.get("pinned_native_dependencies", [])
    if pinned:
        require(
            verify_files(root, pinned, "pinned native dependency") <= runtime,
            "pinned native dependency not in runtime closure",
        )
    tests = ctest_inventory(folder)
    require(
        record.get("ctest_tests") == tests,
        "CTest plan drift or missing build lock; rebuild required",
    )
    test_paths = verify_files(root, record.get("test_artifacts", []), "test artifact")
    require(
        test_paths == {Path(test["command"][0]).resolve() for test in tests},
        "executed test binary universe differs from build lock",
    )
    for executable in test_paths:
        require(
            runtime_paths(executable) <= runtime | {artifact.resolve()},
            "test dynamic dependency is not locked: " + str(executable),
        )
    return {
        "build_record_sha256": sha(record_path),
        "artifact_sha256": record["artifact_sha256"],
        "frozen_sources_sha256": sha(lock_path),
        "compiler_closure_file_count": len(closure),
        "test_artifacts": record["test_artifacts"],
        "ctest_tests": tests,
        "runtime_dependencies": record["runtime_dependencies"],
        "sanitizer_scope": record["sanitizer_scope"],
    }


def verify_junit(path: Path, tests: list[dict]) -> int:
    require(path.is_file(), "CTest JUnit evidence missing")
    cases = list(ET.parse(path).getroot().iter("testcase"))
    require(
        sorted(case.get("name") for case in cases) == sorted(test["name"] for test in tests),
        "CTest executed test universe differs from the frozen nonempty plan",
    )
    require(
        all(
            not list(case.iter("failure"))
            and not list(case.iter("error"))
            and not list(case.iter("skipped"))
            and case.get("status", "run").lower() not in {"notrun", "disabled", "skipped"}
            for case in cases
        ),
        "CTest failed, errored or skipped test",
    )
    return len(cases)


def write_json(path: Path, document: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(document, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def qualify(root: Path, algorithm: str, profile: str, folder: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=False)
    record = {
        "algorithm": algorithm,
        "profile": profile,
        "scope": "CURRENT_FROZEN_CPP_STANDALONE_AND_FRAMEWORK_BINDING_TESTS",
        "source_language_oracle": "NOT_EXECUTED_NOT_CLAIMED",
        "full_native_capability_parity": "NOT_CLAIMED",
        "standalone_rewrite_done": "NOT_GRANTED_BY_THIS_QUALIFICATION",
        "driver_sha256": sha(Path(__file__)),
        "build_directory": str(folder),
    }
    try:
        before = verify_build(root, algorithm, profile, folder)
        write_json(out / "preflight.json", before)
        junit = out / "ctest.xml"
        command = [
            "ctest",
            "--test-dir",
            str(folder / "cmake"),
            "--output-on-failure",
            "--no-tests=error",
            "--output-junit",
            str(junit),
        ]
        environment = dict(
            os.environ,
            ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
            UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
        )
        record["command"] = command
        try:
            process = subprocess.run(command, env=environment, capture_output=True, timeout=900)
            output, code = process.stdout + process.stderr, process.returncode
        except subprocess.TimeoutExpired as error:
            output = (error.stdout or b"") + (error.stderr or b"") + b"\nQUALIFICATION_TIMEOUT"
            code = 124
        log = out / "qualification.log"
        with log.open("xb") as stream:
            stream.write(output)
        record.update(exit_code=code, log=str(log), log_sha256=sha(log))
        require(code == 0, "CTest qualification failed or timed out")
        count = verify_junit(junit, before["ctest_tests"])
        after = verify_build(root, algorithm, profile, folder)
        require(before == after, "build/runtime/test closure drifted during qualification")
        record.update(status="PASS", closure=after, test_count=count, junit_sha256=sha(junit))
    except Exception as error:
        record.update(status="FAIL", error_type=type(error).__name__, error=str(error))
    write_json(out / "qualification.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--algorithms", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument(
        "--profiles", nargs="+", choices=["release", "sanitizer"], default=["release", "sanitizer"]
    )
    parser.add_argument("--build-root", type=Path, default=ROOT / "build/adapters")
    parser.add_argument("--output-directory", type=Path)
    args = parser.parse_args()
    output = args.output_directory or ROOT / "build/source-audits" / (
        "completed-native-v3-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    )
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for name in args.algorithms:
        for profile in args.profiles:
            folder = args.build_root / name.replace("-", "_") / profile
            record = qualify(ROOT, name, profile, folder, output / name / profile)
            results.append(record)
            print(name, profile, record["status"], record.get("error", ""), flush=True)
    report = {
        "status": "PASS" if all(r["status"] == "PASS" for r in results) else "FAIL",
        "cases": results,
        "driver_sha256": sha(Path(__file__)),
    }
    write_json(output / "report.json", report)
    raise SystemExit(report["status"] != "PASS")


if __name__ == "__main__":
    main()
