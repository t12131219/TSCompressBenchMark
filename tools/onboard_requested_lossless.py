"""Admit existing lossless cards from current native and fresh source evidence.

Historical reports stay unchanged. Finite ABI tests and independent source
differential keep separate scopes; neither grants complete G0-G6 or N1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from qualify_completed_rewrites_native import runtime_paths

from tscompbench.adapters import adapter_artifacts
from tscompbench.adapters.build_evidence import verified_build_dependencies
from tscompbench.adapters.runtime_evidence import _standalone
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PASS_STATES = {"PASS", "PASS_SOURCE_NAN_SENTINEL", "PASS_SOURCE_DOMAIN_REJECTION"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def local(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def checked_file(root: Path, record: dict) -> Path:
    path = local(root, record["path"])
    require(path.is_file() and sha(path) == record["sha256"], "evidence file drift: " + str(path))
    return path


def file_entry(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def read_native_report(root: Path, path: Path, algorithms: tuple[str, ...]) -> dict:
    report = json.loads(path.read_text())
    require(
        report.get("schema_version") == "tscb.general-native-build-audit.v1",
        "fresh general native qualification required; legacy report rejected",
    )
    require(report.get("status") == "PASS", "native qualification did not pass")
    driver = checked_file(root, report["driver"])
    require(
        driver.resolve() == (root / "tools/verify_general_native_builds.py").resolve(),
        "unexpected native qualification driver",
    )
    rows = report.get("results", [])
    require(
        bool(rows) and report.get("record_count") == len(rows),
        "native qualification test universe empty or inconsistent",
    )
    keys = [(row.get("algorithm"), row.get("profile")) for row in rows]
    require(len(keys) == len(set(keys)), "duplicate native qualification algorithm/profile")
    expected = {(name, profile) for name in algorithms for profile in ("release", "sanitizer")}
    selected = {key for key in keys if key[0] in algorithms}
    require(selected == expected, "complete selected native profile universe required")
    return {key: row for key, row in zip(keys, rows, strict=True) if key in expected}


def checked_native_profile(
    root: Path, name: str, profile: str, folder: Path, adapter: dict, kind: int, row: dict
) -> dict:
    record_path = folder / "build-record.json"
    require(
        checked_file(root, row["build_record"]).resolve() == record_path.resolve(),
        "native qualification build path differs",
    )
    record = json.loads(record_path.read_text())
    artifact = local(root, record["artifact"])
    require(
        record.get("algorithm") == name and record.get("profile") == profile,
        "native build algorithm/profile differs",
    )
    require(
        checked_file(root, row["artifact"]).resolve() == artifact.resolve(),
        "native qualification artifact path differs",
    )
    for field in (
        "compiled_source_closure",
        "compiler_dependency_files",
        "objects",
        "runtime_dependencies",
        "toolchain_programs",
        "build_driver_files",
    ):
        require(bool(record.get(field)), "current native build closure missing: " + field)
    # These tests execute separate release/ASan binaries. A Python release
    # CDLL profile cannot describe the ASan executable's runtime selection.
    # All declared build/runtime hashes remain mandatory; production selection
    # is independently checked through adapter_artifacts in admission_snapshot.
    dependencies = verified_build_dependencies(
        root, artifact, name, adapter, verify_runtime_selection=False
    )
    require(
        row.get("declared_dependencies_status") == "PASS"
        and row.get("verified_dependency_count") == len(dependencies),
        "native dependency universe differs from qualification",
    )
    require(
        row.get("dependency_verification_scope")
        == "BUILD_RECORD_AUDIT_NOT_PRODUCTION_CDLL_PROFILE",
        "native build verification scope differs",
    )
    tests = row.get("native_tests", [])
    require(len(tests) == 1, "exact nonempty lossless ABI test universe required")
    test = tests[0]
    require(test.get("scope") == "FINITE_DIRECT_C_ABI_TEST", "native test scope differs")
    source = checked_file(root, test["source"])
    require(
        source.resolve() == (root / "adapters/rewrite_lossless/tests/qualification.cc").resolve(),
        "unexpected lossless ABI test source",
    )
    executable = checked_file(root, test["executable"])
    compile_row, run = test["compile"], test["run"]
    command = compile_row["command"]
    require(
        compile_row.get("returncode") == 0 and run.get("returncode") == 0,
        "native test compile/run failed or was skipped",
    )
    require(run.get("command") == [str(executable)], "executed native test differs")
    require("-UNDEBUG" in command and "-DNDEBUG" not in command, "native test assertions disabled")
    require(
        str(source) in command
        and "-o" in command
        and command[command.index("-o") + 1] == str(executable),
        "native qualification source/output command differs",
    )
    require(
        f"-DTSCB_REWRITE_KIND={kind}" in command and f'-DTSCB_REWRITE_KEY="{name}"' in command,
        "native test algorithm macros differ",
    )
    require(
        "-L" in command
        and command[command.index("-L") + 1] == str(artifact.parent)
        and "-l" + artifact.stem[3:] in command
        and f"-Wl,-rpath,{artifact.parent}" in command,
        "native test linked build differs",
    )
    if profile == "sanitizer":
        require("-fsanitize=address,undefined" in command, "native test sanitizer absent")
    runtime = {local(root, item["path"]).resolve() for item in record["runtime_dependencies"]}
    require(
        test.get("runtime_resolution_scope")
        == "LDD_SELECTED_FOR_SEPARATE_NATIVE_EXECUTABLE_NOT_PROC_MAP_TRACE",
        "native test runtime observation scope differs",
    )
    selected_runtime = test.get("runtime_dependencies", [])
    require(bool(selected_runtime), "native test runtime observation is empty")
    require(
        _standalone(executable) == selected_runtime,
        "native test selected runtime path/hash/SONAME differs",
    )
    require(
        runtime_paths(executable) <= runtime | {artifact.resolve()},
        "native test runtime outside current build lock",
    )
    return {
        "algorithm": name,
        "profile": profile,
        "build_record": file_entry(record_path),
        "artifact": file_entry(artifact),
        "native_test": test,
        "dependencies": [file_entry(path) for path in dependencies],
        "scope": "CURRENT_DECLARED_BUILD_CLOSURE_AND_FINITE_ABI_TEST",
        "runtime_selection_scope": "SEPARATE_NATIVE_EXECUTABLE_NOT_PRODUCTION_CDLL_PROFILE",
    }


def checked_source_report(root: Path, path: Path, lock: dict, algorithms: tuple[str, ...]) -> dict:
    report = json.loads(path.read_text())
    require(
        report.get("status") == "PASS_FRESH_SOURCE_EXECUTION_SCOPED"
        and report.get("evidence_kind") == "FRESH_SOURCE_EXECUTION_SCOPED",
        "fresh source execution report required; historical parity rejected",
    )
    require(
        report.get("driver_sha256") == sha(root / "tools/verify_preserved_source_oracles.py"),
        "source execution driver drift",
    )
    require(
        report.get("original_reference_or_report_changes") == [],
        "source execution changed original evidence",
    )
    require(
        report.get("full_parity_granted") is False and report.get("formal_granted") is False,
        "source scope improperly promoted",
    )
    commands = report.get("commands", [])
    require(bool(commands), "source execution command universe empty")
    labels = [row.get("label") for row in commands]
    require(len(labels) == len(set(labels)), "duplicate source execution labels")
    for row in commands:
        require(
            row.get("exit_code") == 0 and bool(row.get("command")),
            "source execution failed, skipped or unknown",
        )
        checked_file(root, {"path": row["log"], "sha256": row["log_sha256"]})
    packages = {lock["algorithms"][name]["package"] for name in algorithms}
    require(packages <= report.get("packages", {}).keys(), "source package universe incomplete")
    summaries = {}
    for package in sorted(packages):
        row = report["packages"][package]
        require(row.get("status") == "PASS", "source package did not pass")
        require(package + "-source-differential" in labels, "source differential not executed")
        cli = checked_file(root, {"path": row["cli"], "sha256": row["cli_sha256"]})
        result_path = checked_file(root, {"path": row["result"], "sha256": row["result_sha256"]})
        result = json.loads(result_path.read_text())
        cases = result.get("cases", [])
        require(
            result.get("status") == "PASS" and bool(cases), "source result has no passing cases"
        )
        require(
            all(case.get("status") in SOURCE_PASS_STATES for case in cases),
            "source differential contains failed/skipped/unknown cases",
        )
        require(
            dict(Counter(case["status"] for case in cases)) == row.get("case_status_counts"),
            "source differential count universe differs",
        )
        require(result.get("cli_sha256") == row["cli_sha256"], "source result CLI differs")
        source_root = path.parent / "isolated/Compression_Rewrite/Source" / package
        rewrite_root = path.parent / "isolated/Compression_Rewrite/ReWrite" / package
        for field, base in (("source_files", source_root), ("native_source_files", rewrite_root)):
            inventory = row.get(field, {})
            require(bool(inventory), "source execution inventory missing: " + field)
            for relative, digest in inventory.items():
                checked_file(root, {"path": str(base / relative), "sha256": digest})
                if field == "source_files" and relative.startswith("upstream/"):
                    original = root / "Compression_Rewrite/Source" / package / relative
                    checked_file(root, {"path": str(original), "sha256": digest})
        compiled = []
        for relative, digest in row["native_source_files"].items():
            if relative.startswith(("src/", "include/")):
                current = root / "adapters/rewrite_lossless/vendor" / package / relative
                checked_file(root, {"path": str(current), "sha256": digest})
                compiled.append(file_entry(current))
        require(bool(compiled), "source-oracle/current native core association missing")
        counts = dict(Counter(case["status"] for case in cases))
        network_cases = result.get("network_cases", [])
        require(
            len(network_cases) == row.get("network_cases", 0),
            "source network case universe differs",
        )
        summaries[package] = {
            "cli": file_entry(cli),
            "result": file_entry(result_path),
            "case_count": len(cases),
            "case_status_counts": counts,
            "legal_source_cases": counts.get("PASS", 0),
            "source_end_marker_cases": counts.get("PASS_SOURCE_NAN_SENTINEL", 0),
            "archived_source_failure_native_rejection_cases": counts.get(
                "PASS_SOURCE_DOMAIN_REJECTION", 0
            ),
            "fresh_original_java_executed": True,
            "archived_rejections_fresh_original_java_executed": False,
            "network_cases": len(network_cases),
            "current_native_core": compiled,
            "scope": (
                "FRESH_ORIGINAL_JAVA_LEGAL_AND_END_WITH_ARCHIVED_FAILURE_NATIVE_REJECTION"
                if package == "elf-plus"
                else "FRESH_ORIGINAL_JAVA_SOURCE_AND_CANONICAL_CORE_CLI_DIFFERENTIAL"
            ),
            "current_registered_library_was_direct_source_oracle_target": False,
            "full_native_capability_parity": "NOT_GRANTED",
        }
    return {
        "report": file_entry(path),
        "packages": summaries,
        "legal_source_case_count": sum(row["legal_source_cases"] for row in summaries.values()),
        "source_end_marker_case_count": sum(
            row["source_end_marker_cases"] for row in summaries.values()
        ),
        "archived_source_failure_native_rejection_case_count": sum(
            row["archived_source_failure_native_rejection_cases"] for row in summaries.values()
        ),
        "network_case_count": sum(row["network_cases"] for row in summaries.values()),
    }


def admission_snapshot(
    root: Path,
    build_root: Path,
    native_path: Path,
    source_path: Path,
    algorithms: tuple[str, ...],
    registry: CodecRegistry,
) -> dict:
    lock_path = root / "adapters/rewrite_lossless/FROZEN_APIS.json"
    lock = json.loads(lock_path.read_text())
    require(
        bool(algorithms) and set(algorithms) <= lock["algorithms"].keys(),
        "unexpected existing lossless algorithm selection",
    )
    for name in algorithms:
        for item in lock["algorithms"][name]["files"]:
            checked_file(root, item)
    rows = read_native_report(root, native_path, algorithms)
    native = []
    production = []
    for name in algorithms:
        manifest = registry.get(name)
        adapter = manifest.document["adapter"]
        for profile in ("release", "sanitizer"):
            folder = build_root / name.replace("-", "_") / profile
            native.append(
                checked_native_profile(
                    root,
                    name,
                    profile,
                    folder,
                    adapter,
                    lock["algorithms"][name]["kind"],
                    rows[(name, profile)],
                )
            )
        artifact, dependencies = adapter_artifacts(root, manifest)
        production.append(
            {
                "algorithm": name,
                "artifact": file_entry(artifact),
                "dependencies": [file_entry(path) for path in dependencies],
                "scope": "PRODUCTION_REGISTERED_FACTORY_PRELOAD_RUNTIME_SELECTION",
                "postload_execution": "NOT_PERFORMED_BY_ADMISSION",
            }
        )
    registrations = [file_entry(root / "registry/codecs" / (name + ".json")) for name in algorithms]
    return {
        "lock": file_entry(lock_path),
        "registrations": registrations,
        "native_report": file_entry(native_path),
        "native": native,
        "production_factory_dependencies": production,
        "source": checked_source_report(root, source_path, lock, algorithms),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--native-qualification", type=Path, required=True)
    parser.add_argument("--source-qualification", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    algorithms = tuple(sorted(lock["algorithms"]))
    inputs = (
        ROOT,
        args.build_root.resolve(),
        args.native_qualification.resolve(),
        args.source_qualification.resolve(),
        algorithms,
        registry,
    )
    before = admission_snapshot(*inputs)
    staged = []
    for name in algorithms:
        path = ROOT / "registry/onboarding" / (name + ".json")
        old_bytes = path.read_bytes()
        card = validate_onboarding_card(json.loads(old_bytes))
        require(
            card["source_artifact_id"] == registry.get(name).source_artifact_id,
            "existing lossless card source identity differs",
        )
        package = lock["algorithms"][name]["package"]
        # Validate the existing identity first, then derive a new onboarding
        # identity from the additional current evidence.
        card.pop("source_onboarding_id", None)
        source_summary = before["source"]["packages"][package]
        card["upstream_tests"].append(
            {
                "name": "current finite ABI and independently executed source differential",
                "status": "PASS_SCOPED",
                "evidence_kind": "CURRENT_INDEPENDENT_EVIDENCE_SCOPES",
                "native_qualification": before["native_report"],
                "source_qualification": before["source"]["report"],
                "source_package": package,
                "source_case_count": before["source"]["packages"][package]["case_count"],
                "case_status_counts": source_summary["case_status_counts"],
                "legal_source_cases": source_summary["legal_source_cases"],
                "source_end_marker_cases": source_summary["source_end_marker_cases"],
                "network_cases": source_summary["network_cases"],
                "archived_source_failure_native_rejection_cases": source_summary[
                    "archived_source_failure_native_rejection_cases"
                ],
                "fresh_original_java_executed": source_summary["fresh_original_java_executed"],
                "archived_rejections_fresh_original_java_executed": source_summary[
                    "archived_rejections_fresh_original_java_executed"
                ],
                "source_test_scope": source_summary["scope"],
                "source_full_parity": "NOT_GRANTED",
                "standalone_g0_g6": "NOT_GRANTED",
                "complete_n1_compile_link_trace": "NOT_GRANTED",
            }
        )
        card["known_limitations"].append(
            "Fresh source differential tests shared canonical C++ cores through isolated CLI "
            "builds; registered libraries and Python wrappers have separate finite API tests. "
            "Declared build hashes do not grant full N1 trace, G0-G6 or all source capabilities."
        )
        card = validate_onboarding_card(card)
        for label, content in (
            ("before", old_bytes),
            ("candidate", (json.dumps(card, indent=2, ensure_ascii=False) + "\n").encode()),
        ):
            saved = output / label / path.relative_to(ROOT)
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(content)
        staged.append((path, old_bytes))
    require(before == admission_snapshot(*inputs), "evidence closure drifted during admission")
    require(
        all(path.read_bytes() == content for path, content in staged),
        "onboarding registration changed during candidate review",
    )
    try:
        for path, _ in staged:
            path.write_bytes((output / "candidate" / path.relative_to(ROOT)).read_bytes())
            validate_onboarding_card(json.loads(path.read_text()))
        require(
            before == admission_snapshot(*inputs), "evidence closure drifted during application"
        )
    except Exception:
        for path, content in staged:
            path.write_bytes(content)
        raise
    report = {
        "status": "PASS",
        "algorithm_count": len(algorithms),
        "native_profile_count": len(before["native"]),
        "evidence": before,
        "driver_sha256": sha(Path(__file__)),
        "historical_evidence_rewritten": False,
        "codec_runtime_profile_preserved": True,
        "full_parity_granted": False,
        "rewrite_done_granted": False,
        "formal_granted": False,
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "before_sha256": sha(output / "before" / path.relative_to(ROOT)),
                "current_sha256": sha(path),
            }
            for path, _ in staged
        ],
    }
    with (output / "admission.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(
        "current lossless admission",
        len(algorithms),
        "algorithms;",
        len(before["native"]),
        "native profiles PASS; source scope kept separate",
    )


if __name__ == "__main__":
    main()
