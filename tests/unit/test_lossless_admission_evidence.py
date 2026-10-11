"""Reject stale, empty, skipped and mismatched lossless admission evidence."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import onboard_requested_lossless as tool  # noqa: E402


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def entry(path):
    return {"path": str(path), "sha256": tool.sha(path)}


@pytest.fixture
def native_report(tmp_path):
    driver = tmp_path / "tools/verify_general_native_builds.py"
    driver.parent.mkdir(parents=True)
    driver.write_text("current driver")
    algorithms = ("chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star")
    report = {
        "schema_version": "tscb.general-native-build-audit.v1",
        "status": "PASS",
        "driver": entry(driver),
        "record_count": 12,
        "results": [
            {"algorithm": name, "profile": profile}
            for name in algorithms
            for profile in ("release", "sanitizer")
        ],
    }
    path = tmp_path / "native.json"
    save(path, report)
    return tmp_path, path, report, algorithms


def test_complete_selected_profile_universe(native_report):
    root, path, _, algorithms = native_report
    assert len(tool.read_native_report(root, path, algorithms)) == 12


@pytest.mark.parametrize("mutation", ["empty", "missing", "duplicate", "count", "legacy", "driver"])
def test_rejects_false_native_report_pass(native_report, mutation):
    root, path, report, algorithms = native_report
    if mutation == "empty":
        report["results"], report["record_count"] = [], 0
    elif mutation == "missing":
        report["results"].pop()
        report["record_count"] -= 1
    elif mutation == "duplicate":
        report["results"][-1] = copy.deepcopy(report["results"][0])
    elif mutation == "count":
        report["record_count"] = 0
    elif mutation == "legacy":
        report["schema_version"] = "historical-native-report"
    else:
        report["driver"]["sha256"] = "0" * 64
    save(path, report)
    with pytest.raises(RuntimeError):
        tool.read_native_report(root, path, algorithms)


@pytest.fixture
def native_profile(tmp_path, monkeypatch):
    root = tmp_path
    folder = root / "build/chimp/sanitizer"
    paths = {
        "artifact": folder / "libtscb_chimp.so",
        "source": root / "adapters/rewrite_lossless/tests/qualification.cc",
        "executable": root / "qualification/chimp_abi",
        "dependency": root / "include/api.h",
        "runtime": root / "lib/asan.so",
    }
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key)
    record = {"algorithm": "chimp", "profile": "sanitizer", "artifact": str(paths["artifact"])}
    for field in (
        "compiled_source_closure",
        "compiler_dependency_files",
        "objects",
        "toolchain_programs",
        "build_driver_files",
    ):
        record[field] = [entry(paths["dependency"])]
    record["runtime_dependencies"] = [entry(paths["runtime"])]
    record_path = folder / "build-record.json"
    save(record_path, record)
    command = [
        "c++",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-DTSCB_REWRITE_KIND=1",
        '-DTSCB_REWRITE_KEY="chimp"',
        str(paths["source"]),
        "-L",
        str(folder),
        "-ltscb_chimp",
        f"-Wl,-rpath,{folder}",
        "-o",
        str(paths["executable"]),
    ]
    row = {
        "build_record": entry(record_path),
        "artifact": entry(paths["artifact"]),
        "declared_dependencies_status": "PASS",
        "verified_dependency_count": 1,
        "dependency_verification_scope": "BUILD_RECORD_AUDIT_NOT_PRODUCTION_CDLL_PROFILE",
        "native_tests": [
            {
                "scope": "FINITE_DIRECT_C_ABI_TEST",
                "source": entry(paths["source"]),
                "executable": entry(paths["executable"]),
                "compile": {"command": command, "returncode": 0, "output": ""},
                "run": {
                    "command": [str(paths["executable"])],
                    "returncode": 0,
                    "output": "native qualification PASS",
                },
                "runtime_dependencies": [{**entry(paths["runtime"]), "soname": "asan.so"}],
                "runtime_resolution_scope": (
                    "LDD_SELECTED_FOR_SEPARATE_NATIVE_EXECUTABLE_NOT_PROC_MAP_TRACE"
                ),
            }
        ],
    }
    monkeypatch.setattr(
        tool, "verified_build_dependencies", lambda *args, **kwargs: (paths["dependency"],)
    )
    monkeypatch.setattr(tool, "runtime_paths", lambda path: {paths["runtime"].resolve()})
    monkeypatch.setattr(
        tool, "_standalone", lambda path: [{**entry(paths["runtime"]), "soname": "asan.so"}]
    )
    return root, folder, paths, record, row


def check_profile(fixture):
    root, folder, _, _, row = fixture
    return tool.checked_native_profile(root, "chimp", "sanitizer", folder, {}, 1, row)


def test_real_finite_native_profile(native_profile):
    assert check_profile(native_profile)["profile"] == "sanitizer"


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "skip",
        "wrong_run",
        "wrong_kind",
        "disabled_asserts",
        "no_sanitizer",
        "wrong_link",
        "binary_drift",
        "source_drift",
        "missing_closure",
        "dependency_count",
        "foreign_runtime",
        "build_scope",
        "test_scope",
        "runtime_scope",
        "runtime_empty",
        "runtime_hash",
        "runtime_soname",
        "runtime_path",
    ],
)
def test_rejects_false_native_profile_pass(native_profile, monkeypatch, mutation):
    _, folder, paths, record, row = native_profile
    test = row["native_tests"][0]
    if mutation == "empty":
        row["native_tests"] = []
    elif mutation == "skip":
        test["run"]["returncode"] = None
    elif mutation == "wrong_run":
        test["run"]["command"] = ["true"]
    elif mutation == "wrong_kind":
        test["compile"]["command"].remove("-DTSCB_REWRITE_KIND=1")
    elif mutation == "disabled_asserts":
        test["compile"]["command"].append("-DNDEBUG")
    elif mutation == "no_sanitizer":
        test["compile"]["command"].remove("-fsanitize=address,undefined")
    elif mutation == "wrong_link":
        test["compile"]["command"].remove("-ltscb_chimp")
    elif mutation == "binary_drift":
        paths["executable"].write_text("changed")
    elif mutation == "source_drift":
        paths["source"].write_text("changed")
    elif mutation == "missing_closure":
        record["compiled_source_closure"] = []
        save(folder / "build-record.json", record)
        row["build_record"] = entry(folder / "build-record.json")
    elif mutation == "dependency_count":
        row["verified_dependency_count"] = 0
    elif mutation == "build_scope":
        row["dependency_verification_scope"] = "PRODUCTION_CDLL_PROFILE"
    elif mutation == "test_scope":
        test["scope"] = "UNKNOWN"
    elif mutation == "runtime_scope":
        test["runtime_resolution_scope"] = "PROC_MAP_TRACE"
    elif mutation == "runtime_empty":
        test["runtime_dependencies"] = []
    elif mutation == "runtime_hash":
        test["runtime_dependencies"][0]["sha256"] = "0" * 64
    elif mutation == "runtime_soname":
        test["runtime_dependencies"][0]["soname"] = "foreign.so"
    elif mutation == "runtime_path":
        test["runtime_dependencies"][0]["path"] = "/foreign/runtime.so"
    else:
        monkeypatch.setattr(tool, "runtime_paths", lambda path: {Path("/foreign/runtime.so")})
    with pytest.raises(RuntimeError):
        check_profile(native_profile)


@pytest.fixture
def source_report(tmp_path):
    root = tmp_path
    output = root / "source-oracles"
    paths = {
        "driver": root / "tools/verify_preserved_source_oracles.py",
        "cli": output / "chimp_cli",
        "log": output / "chimp.log",
        "source": output / "isolated/Compression_Rewrite/Source/chimp/upstream/Core.java",
        "native": output / "isolated/Compression_Rewrite/ReWrite/chimp/src/codec.cpp",
        "current": root / "adapters/rewrite_lossless/vendor/chimp/src/codec.cpp",
        "original": root / "Compression_Rewrite/Source/chimp/upstream/Core.java",
    }
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "core"
            if key in {"native", "current"}
            else "upstream"
            if key in {"source", "original"}
            else key
        )
    result_path = output / "result.json"
    result = {"status": "PASS", "cases": [{"status": "PASS"}], "cli_sha256": tool.sha(paths["cli"])}
    save(result_path, result)
    package = {
        "status": "PASS",
        "case_status_counts": {"PASS": 1},
        "cli": str(paths["cli"]),
        "cli_sha256": tool.sha(paths["cli"]),
        "result": str(result_path),
        "result_sha256": tool.sha(result_path),
        "source_files": {"upstream/Core.java": tool.sha(paths["source"])},
        "native_source_files": {"src/codec.cpp": tool.sha(paths["native"])},
    }
    report = {
        "status": "PASS_FRESH_SOURCE_EXECUTION_SCOPED",
        "evidence_kind": "FRESH_SOURCE_EXECUTION_SCOPED",
        "full_parity_granted": False,
        "formal_granted": False,
        "original_reference_or_report_changes": [],
        "driver_sha256": tool.sha(paths["driver"]),
        "packages": {"chimp": package},
        "commands": [
            {
                "label": "chimp-source-differential",
                "command": ["driver"],
                "exit_code": 0,
                "log": str(paths["log"]),
                "log_sha256": tool.sha(paths["log"]),
            }
        ],
    }
    path = output / "report.json"
    save(path, report)
    lock = {"algorithms": {"chimp": {"package": "chimp"}}}
    return root, path, paths, report, result_path, result, lock


def test_independent_scoped_source_evidence(source_report):
    root, path, _, _, _, _, lock = source_report
    snapshot = tool.checked_source_report(root, path, lock, ("chimp",))
    assert snapshot["packages"]["chimp"]["full_native_capability_parity"] == "NOT_GRANTED"


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_commands",
        "no_differential",
        "skip",
        "log_drift",
        "driver_drift",
        "cli_drift",
        "source_drift",
        "core_drift",
        "original_drift",
        "empty_cases",
        "skipped_case",
        "counts",
        "full_parity",
        "historical",
    ],
)
def test_rejects_false_source_pass(source_report, mutation):
    root, path, paths, report, result_path, result, lock = source_report
    if mutation == "empty_commands":
        report["commands"] = []
    elif mutation == "no_differential":
        report["commands"][0]["label"] = "configure-only"
    elif mutation == "skip":
        report["commands"][0]["exit_code"] = None
    elif mutation.endswith("_drift"):
        key = mutation.removesuffix("_drift")
        if key == "core":
            key = "current"
        paths[key].write_text("changed")
    elif mutation == "empty_cases":
        result["cases"] = []
    elif mutation == "skipped_case":
        result["cases"][0]["status"] = "SKIPPED"
    elif mutation == "counts":
        report["packages"]["chimp"]["case_status_counts"] = {"PASS": 1000}
    elif mutation == "full_parity":
        report["full_parity_granted"] = True
    else:
        report["status"] = "PASS"
    save(result_path, result)
    report["packages"]["chimp"]["result_sha256"] = tool.sha(result_path)
    save(path, report)
    with pytest.raises(RuntimeError):
        tool.checked_source_report(root, path, lock, ("chimp",))


def test_existing_admission_directory_never_overwritten(tmp_path, monkeypatch):
    output = tmp_path / "old_evidence"
    output.mkdir()
    original = output / "report.json"
    original.write_text("historical evidence")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "onboard",
            "--build-root",
            str(tmp_path),
            "--native-qualification",
            str(tmp_path / "n.json"),
            "--source-qualification",
            str(tmp_path / "s.json"),
            "--output-directory",
            str(output),
        ],
    )
    with pytest.raises(FileExistsError):
        tool.main()
    assert original.read_text() == "historical evidence"


def test_legacy_source_probe_refuses_existing_output_under_optimized_python(tmp_path):
    output = tmp_path / "previous_probe"
    output.mkdir()
    preserved = output / "report.json"
    preserved.write_text("old qualification")
    script = Path(__file__).resolve().parents[2] / "tools/qualify_rewrite_lossless_native.py"
    result = subprocess.run(
        [sys.executable, "-O", str(script), "--output-directory", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert preserved.read_text() == "old qualification"


@pytest.fixture
def admission_application(tmp_path, monkeypatch):
    actual = Path(__file__).resolve().parents[2] / "registry/onboarding/chimp.json"
    original = actual.read_bytes()
    card = json.loads(original)
    root = tmp_path
    registered = root / "registry/onboarding/chimp.json"
    registered.parent.mkdir(parents=True)
    registered.write_bytes(original)
    save(
        root / "adapters/rewrite_lossless/FROZEN_APIS.json",
        {"algorithms": {"chimp": {"package": "chimp"}}},
    )
    manifest = SimpleNamespace(source_artifact_id=card["source_artifact_id"])
    registry = SimpleNamespace(get=lambda name: manifest)
    monkeypatch.setattr(tool, "ROOT", root)
    monkeypatch.setattr(tool, "SourceRegistry", lambda path: None)
    monkeypatch.setattr(tool, "CodecRegistry", lambda *args: registry)
    snapshot = {
        "native_report": {"path": "native-report", "sha256": "a" * 64},
        "native": ["release", "sanitizer"],
        "source": {
            "report": {"path": "source-report", "sha256": "b" * 64},
            "packages": {
                "chimp": {
                    "case_count": 1,
                    "case_status_counts": {"PASS": 1},
                    "legal_source_cases": 1,
                    "source_end_marker_cases": 0,
                    "archived_source_failure_native_rejection_cases": 0,
                    "fresh_original_java_executed": True,
                    "archived_rejections_fresh_original_java_executed": False,
                    "network_cases": 0,
                    "scope": "FRESH_ORIGINAL_JAVA_SOURCE_AND_CANONICAL_CORE_CLI_DIFFERENTIAL",
                }
            },
        },
    }
    monkeypatch.setattr(tool, "admission_snapshot", lambda *args: copy.deepcopy(snapshot))
    output = root / "new-admission"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "onboard",
            "--build-root",
            str(root / "build"),
            "--native-qualification",
            str(root / "native.json"),
            "--source-qualification",
            str(root / "source.json"),
            "--output-directory",
            str(output),
        ],
    )
    return registered, original, output, snapshot


def test_successful_application_preserves_prior_evidence(admission_application):
    registered, original, output, _ = admission_application
    tool.main()
    assert (output / "before/registry/onboarding/chimp.json").read_bytes() == original
    applied = json.loads(registered.read_text())
    assert applied["upstream_tests"][:-1] == json.loads(original)["upstream_tests"]
    assert applied["upstream_tests"][-1]["source_full_parity"] == "NOT_GRANTED"
    assert json.loads((output / "admission.json").read_text())["native_profile_count"] == 2


@pytest.mark.parametrize("drift_call", [2, 3])
def test_pre_and_post_application_drift_restores_original(
    admission_application, monkeypatch, drift_call
):
    registered, original, output, snapshot = admission_application
    calls = 0

    def changing(*args):
        nonlocal calls
        calls += 1
        current = copy.deepcopy(snapshot)
        if calls == drift_call:
            current["native_report"]["sha256"] = "c" * 64
        return current

    monkeypatch.setattr(tool, "admission_snapshot", changing)
    with pytest.raises(RuntimeError, match="closure drifted"):
        tool.main()
    assert registered.read_bytes() == original
    assert not (output / "admission.json").exists()
