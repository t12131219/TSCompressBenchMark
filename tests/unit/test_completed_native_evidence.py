"""A native qualification must bind the executed build, not a successful CTest exit."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import qualify_completed_rewrites_native as tool  # noqa: E402


@pytest.fixture
def frozen_build(tmp_path, monkeypatch):
    root = tmp_path
    folder = root / "build/adapters/abba/release"
    paths = {
        "vendor": root / "adapters/completed_rewrites/vendor/abba/codec.cpp",
        "binding": root / "adapters/completed_rewrites/native/binding.cpp",
        "binding_header": root / "adapters/completed_rewrites/native/binding.hpp",
        "qualification": root / "adapters/completed_rewrites/tests/qualification.cpp",
        "driver": root / "tools/build_completed_rewrite.py",
        "recipe": folder / "recipe/CMakeLists.txt",
        "artifact": folder / "libtscb_abba.so",
        "header": root / "include/platform.h",
        "runtime": root / "lib/runtime.so",
        "test_binary": folder / "cmake/binding_qualification",
        "standalone_binary": folder / "cmake/standalone/abba_tests",
    }
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.encode())

    def entry(path):
        return {"path": str(path), "sha256": tool.sha(path)}

    lock_path = root / "adapters/completed_rewrites/FROZEN_SOURCES.json"
    lock_path.write_text(json.dumps({"packages": {"abba": {"files": [entry(paths["vendor"])]}}}))
    commands = [
        {
            "directory": str(folder / "cmake"),
            "file": str(paths["vendor"]),
            "arguments": [
                "c++",
                "-fno-fast-math",
                "-ffp-contract=off",
                "-c",
                str(paths["vendor"]),
                "-o",
                "codec.cpp.o",
            ],
        },
        {
            "directory": str(folder / "cmake"),
            "file": str(paths["binding"]),
            "arguments": ["c++", "-c", str(paths["binding"]), "-o", "binding.cpp.o"],
        },
    ]
    compile_path = folder / "cmake/compile_commands.json"
    compile_path.write_text(json.dumps(commands))
    closure = [
        entry(paths[key])
        for key in ("vendor", "binding", "binding_header", "qualification", "header")
    ]
    (folder / "cmake/codec.cpp.o.d").write_text(
        "codec.cpp.o: " + " ".join(item["path"] for item in closure) + "\n"
    )
    (folder / "cmake/binding.cpp.o.d").write_text(
        "binding.cpp.o: " + " ".join(item["path"] for item in closure) + "\n"
    )
    tests = [
        {"name": "framework_binding_qualification", "command": [str(paths["test_binary"])]},
        {"name": "abba_tests", "command": [str(paths["standalone_binary"])]},
    ]
    record = {
        "algorithm": "abba",
        "profile": "release",
        "artifact": str(paths["artifact"]),
        "artifact_sha256": tool.sha(paths["artifact"]),
        "frozen_sources_sha256": tool.sha(lock_path),
        "build_driver_sha256": tool.sha(paths["driver"]),
        "build_recipe_sha256": tool.sha(paths["recipe"]),
        "compile_commands_sha256": tool.sha(compile_path),
        "qualification_source_sha256": tool.sha(paths["qualification"]),
        "binding_sources": [entry(paths["binding"]), entry(paths["binding_header"])],
        "compiled_source_closure": closure,
        "runtime_dependencies": [entry(paths["runtime"])],
        "pinned_native_dependencies": [],
        "test_artifacts": [entry(paths["test_binary"]), entry(paths["standalone_binary"])],
        "ctest_tests": tests,
        "sanitizer_scope": "NOT_APPLICABLE",
    }
    record_path = folder / "build-record.json"
    record_path.write_text(json.dumps(record))
    monkeypatch.setattr(tool, "ctest_inventory", lambda directory: copy.deepcopy(tests))
    monkeypatch.setattr(tool, "runtime_paths", lambda artifact: {paths["runtime"].resolve()})
    return root, folder, paths, record_path, record


def test_valid_native_build_verifies_current_test_and_source_closure(frozen_build):
    root, folder, paths, _, _ = frozen_build
    observed = tool.verify_build(root, "abba", "release", folder)
    assert observed["compiler_closure_file_count"] == 5
    assert {item["path"] for item in observed["test_artifacts"]} == {
        str(paths["test_binary"]),
        str(paths["standalone_binary"]),
    }


@pytest.mark.parametrize(
    "key",
    [
        "vendor",
        "binding",
        "binding_header",
        "qualification",
        "driver",
        "recipe",
        "artifact",
        "header",
        "runtime",
        "test_binary",
        "standalone_binary",
    ],
)
def test_native_qualification_rejects_any_current_execution_dependency_drift(frozen_build, key):
    root, folder, paths, _, _ = frozen_build
    paths[key].write_bytes(b"modified after build")
    with pytest.raises(RuntimeError, match="drift"):
        tool.verify_build(root, "abba", "release", folder)


@pytest.mark.parametrize("field", ["compiled_source_closure", "test_artifacts", "ctest_tests"])
def test_legacy_build_without_actual_test_or_compiler_lock_cannot_be_promoted(frozen_build, field):
    root, folder, _, record_path, record = frozen_build
    record.pop(field)
    record_path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="rebuild required"):
        tool.verify_build(root, "abba", "release", folder)


def test_added_actual_header_is_not_covered_by_old_compiler_closure(frozen_build):
    root, folder, _, _, _ = frozen_build
    header = root / "include/new-header.h"
    header.write_bytes(b"new dependency")
    dependency = folder / "cmake/codec.cpp.o.d"
    dependency.write_text(dependency.read_text().strip() + " " + str(header) + "\n")
    with pytest.raises(RuntimeError, match="dependency universe"):
        tool.verify_build(root, "abba", "release", folder)


def test_each_compiled_tu_requires_its_own_dependency_evidence(frozen_build):
    root, folder, _, _, _ = frozen_build
    # The union of header paths is unchanged: the first depfile contains both
    # source files. It still cannot prove the second TU's compiler dependencies.
    (folder / "cmake/binding.cpp.o.d").unlink()
    with pytest.raises(RuntimeError, match="TU dependency file missing"):
        tool.verify_build(root, "abba", "release", folder)


def test_new_dynamic_dependency_is_not_covered_by_existing_runtime_lock(frozen_build, monkeypatch):
    root, folder, paths, _, _ = frozen_build
    monkeypatch.setattr(
        tool, "runtime_paths", lambda artifact: {paths["runtime"].resolve(), root / "unlocked.so"}
    )
    with pytest.raises(RuntimeError, match="dynamic dependency is not locked"):
        tool.verify_build(root, "abba", "release", folder)


def test_zero_test_ctest_exit_is_not_qualification_success(tmp_path):
    (tmp_path / "cmake").mkdir()
    with pytest.raises(RuntimeError, match="no tests"):
        tool.ctest_inventory(tmp_path)


@pytest.mark.parametrize(
    "case_xml",
    [
        "",
        '<testcase name="one"/>',
        '<testcase name="one"/><testcase name="two"><skipped/></testcase>',
        '<testcase name="one"/><testcase name="two" status="notrun"/>',
        '<testcase name="one"><failure/></testcase><testcase name="two"/>',
    ],
)
def test_junit_requires_all_planned_tests_to_run_and_pass(tmp_path, case_xml):
    junit = tmp_path / "ctest.xml"
    junit.write_text("<testsuite>" + case_xml + "</testsuite>")
    with pytest.raises(RuntimeError):
        tool.verify_junit(junit, [{"name": "one"}, {"name": "two"}])


def test_qualification_does_not_run_tests_on_failed_build_validation(tmp_path, monkeypatch):
    def reject(*args):
        raise RuntimeError("source drift")

    def forbidden(*args, **kwargs):
        pytest.fail("CTest must not run when build closure is stale")

    monkeypatch.setattr(tool, "verify_build", reject)
    monkeypatch.setattr(tool.subprocess, "run", forbidden)
    out = tmp_path / "evidence"
    result = tool.qualify(tmp_path, "abba", "release", tmp_path / "build", out)
    assert result["status"] == "FAIL"
    assert result["error"] == "source drift"
    original = (out / "qualification.json").read_bytes()
    with pytest.raises(FileExistsError):
        tool.qualify(tmp_path, "abba", "release", tmp_path / "build", out)
    assert (out / "qualification.json").read_bytes() == original


def test_zero_exit_with_skipped_test_cannot_sign_pass(tmp_path, monkeypatch):
    before = {"ctest_tests": [{"name": "one"}, {"name": "two"}]}
    monkeypatch.setattr(tool, "verify_build", lambda *args: before)

    def run(command, **kwargs):
        Path(command[-1]).write_text(
            '<testsuite><testcase name="one"/>'
            '<testcase name="two"><skipped/></testcase></testsuite>'
        )
        assert "--no-tests=error" in command
        return subprocess.CompletedProcess(command, 0, stdout=b"success", stderr=b"")

    monkeypatch.setattr(tool.subprocess, "run", run)
    result = tool.qualify(tmp_path, "abba", "release", tmp_path / "build", tmp_path / "evidence")
    assert result["exit_code"] == 0
    assert result["status"] == "FAIL"
    assert "skipped" in result["error"]
    assert result["source_language_oracle"] == "NOT_EXECUTED_NOT_CLAIMED"


@pytest.fixture
def completed_admission(tmp_path, monkeypatch):
    import onboard_completed_rewrites as admission

    monkeypatch.setattr(admission, "ROOT", tmp_path)
    driver = tmp_path / "tools/qualify_completed_rewrites_native.py"
    driver.parent.mkdir()
    driver.write_bytes(b"current qualifier")
    directory = tmp_path / "qualification"
    evidence = directory / "abba/release"
    evidence.mkdir(parents=True)
    log = evidence / "qualification.log"
    log.write_bytes(b"completed tests")
    junit = evidence / "ctest.xml"
    junit.write_text('<testsuite><testcase name="one"/></testsuite>')
    closure = {"ctest_tests": [{"name": "one"}]}
    record = {
        "status": "PASS",
        "algorithm": "abba",
        "profile": "release",
        "exit_code": 0,
        "command": [
            "ctest",
            "--test-dir",
            str(tmp_path / "build/cmake"),
            "--output-on-failure",
            "--no-tests=error",
            "--output-junit",
            str(junit),
        ],
        "driver_sha256": tool.sha(driver),
        "closure": closure,
        "log": str(log),
        "log_sha256": tool.sha(log),
        "junit_sha256": tool.sha(junit),
        "test_count": 1,
    }
    path = evidence / "qualification.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(admission, "verify_build", lambda *args: copy.deepcopy(closure))
    return admission, tmp_path, directory, path, driver, log, junit


@pytest.mark.parametrize("target", ["driver", "log", "junit", "closure", "pass_label", "command"])
def test_admission_cannot_refresh_stale_native_evidence_as_current(
    completed_admission, monkeypatch, target
):
    admission, root, directory, path, driver, log, junit = completed_admission
    if target in {"driver", "log", "junit"}:
        {"driver": driver, "log": log, "junit": junit}[target].write_bytes(b"changed")
    elif target == "closure":
        monkeypatch.setattr(
            admission, "verify_build", lambda *args: {"ctest_tests": [], "changed": True}
        )
    else:
        record = json.loads(path.read_text())
        if target == "command":
            record["command"].remove("--no-tests=error")
        else:
            record["status"] = "FAIL"
        path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError):
        admission.checked_qualification("abba", "release", root / "build", directory)
