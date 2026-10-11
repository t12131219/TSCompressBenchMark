"""Audit the declared current-code V3.2 release without performance remeasurement.

This checks evidence, not the scientific representativeness of its frozen corpus.
Historical runs, source parity and optional capabilities remain separate claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.pipeline_runner import report_pipeline_comparison  # noqa: E402
from tscompbench.comparison.runner import (  # noqa: E402
    control_plane_snapshot,
    prepare_comparison,
    report_comparison,
    validate_comparison_pilots,
    validate_qualification_evidence,
)
from tscompbench.comparison.workload_runner import report_workload_comparison  # noqa: E402
from tscompbench.datasets import DatasetRegistry  # noqa: E402
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402

REQUIRED_COMPARISONS = {
    "byte",
    "f64",
    "f32",
    "i16",
    "abs",
    "quality",
    "model",
    "cold",
    "api",
    "timestamp",
    "entropy",
    "u8",
}
REQUIRED_WORKLOADS = {"stream", "query-fresh", "query-warm"}


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_evidence(path: Path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def _path(evidence_root: Path, value: str):
    path = (evidence_root / value).resolve()
    require(path.is_relative_to(evidence_root.resolve()), "evidence path escapes release directory")
    require(
        "history" not in path.relative_to(evidence_root).parts, "historical evidence is not current"
    )
    return path


def check_resume(path: Path, raw: Path, status: str, *, decoder_audit: bool = False):
    proof = read(path / "resume_verification.json")
    require(
        proof["before_sha256"] == proof["after_sha256"] == sha(raw)
        and proof["status"] == status
        and proof["performance_execution_required"] is False
        and proof["codec_execution_required"] is decoder_audit
        and (
            not decoder_audit
            or proof.get("codec_execution_scope") == "READ_ONLY_INDEPENDENT_DECODER_AUDIT"
        ),
        f"missing or invalid no-op resume proof: {path.name}",
    )


def validate_cost_evidence(path: Path, lane: str):
    from audit_v32_buffer_costs import validate_buffer_cost_audit

    document = validate_buffer_cost_audit(path, lane)
    require(
        document["status"] == "AUXILIARY_COST_AUDIT"
        and document["formal_eligible"] is False
        and document["codec_invoked"] is False
        and document["performance_remeasured"] is False,
        "cost audit must remain an independent auxiliary observation",
    )
    return {"audit_id": document["audit_id"], "lane": lane, "status": document["status"]}


def validate_reference_evidence(path: Path, lane: str):
    from audit_v32_uncompressed_reference import validate_uncompressed_reference

    document = validate_uncompressed_reference(path, lane)
    require(
        document["status"] == "UNCOMPRESSED_REFERENCE_AUDIT"
        and document["baseline_kind"] == "SIZE_BASELINE"
        and document["formal_eligible"] is False
        and document["codec_invoked"] is False
        and document["performance_remeasured"] is False
        and document["registered_codec"] is False
        and document["statistical_method_count"] == 0
        and document["performance"] is None
        and bool(document["performance_unavailable_reason"]),
        "uncompressed reference cannot manufacture a codec or formal performance",
    )
    return {
        "audit_id": document["audit_id"],
        "status": document["status"],
        "object_count": document["object_count"],
        "baseline_kind": document["baseline_kind"],
        "storage_cost_boundary": document["storage_cost_boundary"],
    }


def fully_observed_codecs(corpus, analysis: dict) -> set[str]:
    """Count current formal objects from two ancestry-independent real sources."""
    observed: dict[str, set[int]] = {}
    real_groups = corpus.independent_real_source_groups()
    for row in analysis["matrix"]:
        if row.get("formal_complete") is not True or row.get("dataset_role") != "CORE":
            continue
        for index, datasets in enumerate(real_groups):
            if row["dataset_id"] in datasets:
                observed.setdefault(row["codec_key"], set()).add(index)
    return {key for key, groups in observed.items() if len(groups) >= 2}


def validate_lane(key: str, bundle: dict):
    names = {
        "byte": "G-BYTE-LL",
        "f64": "G-FLOAT-LL-F64",
        "f32": "G-FLOAT-LL-F32",
        "i16": "G-INT-LL-I16",
        "abs": "G-FLOAT-ABS",
        "quality": "G-QUALITY",
        "model": "G-BYTE-MODEL",
        "cold": "G-BYTE-LL-COLD",
        "api": "G-BYTE-LL-API",
        "timestamp": "G-TIMESTAMP",
        "entropy": "G-BYTE-ENTROPY-LL",
        "u8": "G-UINT8-LL",
    }
    c, p = bundle["contract"], bundle["protocol"]
    require(
        c["name"] == names[key] and bundle["group"]["name"] == names[key], "wrong comparison lane"
    )
    require(c["track"] == ("TIMESTAMP" if key == "timestamp" else "VALUE"), "wrong lane track")
    require(
        p["profile"] == ("COLD_PROCESS" if key == "cold" else "STEADY_PROCESS"),
        "wrong process profile",
    )
    require(
        c["cost_boundary"] == ("NATIVE_COMPONENT" if key == "api" else "SCHEMA_BOUND_OBJECT"),
        "wrong lane cost boundary",
    )
    require(p["timing_scope"] == ("CORE" if key == "api" else "PIPELINE"), "wrong timing scope")
    if key == "api":
        require(c["mode"] == "COMMON_NATIVE_API", "wrong native comparison mode")
    if key == "cold":
        require(
            p["cold_start_boundary"] == "SPAWN_THROUGH_OUTPUT_MATERIALIZATION",
            "wrong cold boundary",
        )
    require(
        c["fidelity"]["kind"]
        == ("FIXED_ERROR" if key == "abs" else "QUALITY_CURVE" if key == "quality" else "LOSSLESS"),
        "wrong lane fidelity",
    )


def test_source_manifest(root: Path):
    return [
        {
            "path": str(path.relative_to(root)),
            "sha256": sha(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted((root / "tests").rglob("*"))
        if path.is_file()
        and "__pycache__" not in path.parts
        and ".pytest_cache" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]


def validate_verification(document: dict, current: dict):
    require(
        document["status"] == "PASS"
        and document["full_suite_exit_code"] == 0
        and document["control_plane"] == current,
        "full regression evidence is not current/pass",
    )
    command = document.get("full_suite_command", [])
    require(
        command[1:] == ["-m", "pytest", "-q", "--tb=short"], "full suite was filtered or not run"
    )
    logs = [item for item in document["artifacts"] if item.get("role") == "FULL_SUITE_LOG"]
    require(len(logs) == 1, "full suite log must be bound exactly once")
    for item in document["artifacts"]:
        require(sha(ROOT / item["path"]) == item["sha256"], "verification log hash differs")
    log = (ROOT / logs[0]["path"]).read_text()
    summaries = re.findall(r"(?m)^.*?([0-9]+) passed[^\n]*$", log)
    require(
        bool(summaries) and int(summaries[-1]) == document["tests_passed"],
        "full suite count/log differs",
    )
    require(
        not re.search(r"\b[1-9][0-9]* (?:failed|errors?)\b", log),
        "full suite log contains failures",
    )
    manifest = document.get("test_source_manifest", [])
    require(
        bool(manifest) and manifest == test_source_manifest(ROOT),
        "full suite test definitions/fixtures changed or were not frozen",
    )
    require(
        document.get("test_configuration") == [file_evidence(ROOT / "pyproject.toml")],
        "full suite pytest configuration changed or was not frozen",
    )
    require(
        document.get("input_snapshot_unchanged") is True,
        "source or tests changed during full regression",
    )


def validate_sdk_reference(document: dict):
    """Recheck the published SDK proof against actual current source and JUnit."""
    from audit_simdcomp_sdk import audit as audit_sdk

    path = (ROOT / document["report"]["path"]).resolve()
    require(path.is_relative_to(ROOT), "SDK report escapes project")
    require(sha(path) == document["report"]["sha256"], "SDK report reference drift")
    observed = audit_sdk(ROOT, path)
    require(observed == document["independent_audit"], "SDK independent audit differs")
    require(observed["status"] == "PASS", "SDK qualification failed")
    return observed


def validate_active(path: Path):
    sys.path.insert(0, str(ROOT / "tools"))
    from qualify_v32_active_entries import (
        active_keys,
        build_matrices,
        preflight_acceptance,
        validate_case_evidence,
        validate_frozen,
    )
    from qualify_v32_active_entries import (
        file_evidence as active_file,
    )

    plan, summary = read(path / "plan.json"), read(path / "summary.json")
    validate_frozen(plan, ROOT)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    require(
        plan["active_keys"] == plan["selected_keys"] == list(active_keys(ROOT, registry)),
        "active denominator differs",
    )
    require(summary["plan_id"] == plan["plan_id"], "active summary belongs to another plan")
    cases = {c["case_id"]: (entry, c) for entry in plan["entries"] for c in entry["cases"]}
    require(len(cases) == sum(len(e["cases"]) for e in plan["entries"]), "duplicate active cases")
    results = {}
    for case_id, (entry, case) in cases.items():
        evidence_path = path / "cases" / (case_id.rsplit(":", 1)[-1] + ".json")
        result = read(evidence_path)
        validate_case_evidence(result, plan, entry, case, root=ROOT, output=path)
        require(
            result["case_id"] == case_id and result["codec_key"] == entry["codec_key"],
            "case belongs to another entry",
        )
        preflight = result.get("preflight")
        require(isinstance(preflight, dict) and bool(preflight), "active raw preflight missing")
        require(
            preflight_acceptance(preflight)["status"] == "SCOPED_PASS",
            "active case not accepted",
        )
        require(result["task"]["track"] == case["track"], "case track differs")
        result["evidence_file"] = active_file(ROOT, evidence_path)
        results[case_id] = result
    statuses = dict(Counter(r["acceptance"]["status"] for r in results.values()))
    require(
        summary["status"] == "SCOPED_QUALIFICATION_COMPLETE"
        and summary["entire_active_scope_selected"] is True
        and summary["active_entry_count"] == summary["selected_entry_count"] == 33
        and summary["observed_track_cases"] == summary["expected_track_cases"] == len(cases)
        and summary["status_counts"] == statuses,
        "active-entry qualification is incomplete",
    )
    require(
        read(path / "four_matrices.json") == build_matrices(plan, results),
        "active matrices differ from actual cases",
    )
    return summary


def audit(evidence_root: Path, declaration: dict):
    require(
        set(declaration["comparisons"]) == REQUIRED_COMPARISONS, "release comparison scope differs"
    )
    require(set(declaration["workloads"]) == REQUIRED_WORKLOADS, "release workload scope differs")
    current = control_plane_snapshot(ROOT)
    directories = [
        *declaration["comparisons"].values(),
        *declaration["workloads"].values(),
        declaration["pipeline"],
        declaration["active"],
    ]
    require(
        len(directories) == len(set(directories)), "release lanes must use distinct directories"
    )
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    groups, artifacts, observed_codecs = {}, [], set()
    for key, name in declaration["comparisons"].items():
        path = _path(evidence_root, name)
        require(read(path / "control_plane.json") == current, f"stale code closure: {key}")
        validate_lane(key, read(path / "bundle.json"))
        run = prepare_comparison(
            path / "bundle.json",
            path.parent,
            ROOT,
            datasets,
            codecs,
            run_set_id=path.name,
            resume=True,
        )
        for dataset in run.corpus.to_document()["datasets"]:
            if dataset["role"] != "CORE":
                continue
            metadata = run.artifacts[dataset["dataset_id"]].metadata
            if key in {"f32", "f64", "i16", "model", "entropy", "u8"}:
                dtype = {
                    "f32": "<f4",
                    "f64": "<f8",
                    "i16": "<i2",
                    "model": "|u1",
                    "entropy": "<f8",
                    "u8": "|u1",
                }[key]
                require(
                    all(
                        b["dtype"] == dtype
                        for b in metadata["buffers"]
                        if b["name"].startswith("value/")
                    ),
                    "wrong lane original dtype",
                )
            if key == "timestamp":
                require(
                    any(b["name"] == "timestamp" for b in metadata["buffers"]),
                    "core timestamps absent",
                )
        validate_qualification_evidence(run, read(path / "qualification.json"))
        validate_comparison_pilots(run, read(path / "pilot.json"))
        raw = path / "comparison_trials.jsonl"
        before = sha(raw)
        report = report_comparison(path)
        analysis = read(path / "analysis.json")
        require(sha(raw) == before == analysis["raw_sha256"], f"raw changed during report: {key}")
        require(report["status"] == "CORE_COMPLETE", f"incomplete comparison: {key}")
        require(analysis["distinct_core_methods"] >= 2, f"insufficient different methods: {key}")
        require(analysis["independent_real_source_count"] >= 2, f"insufficient real sources: {key}")
        coverage = analysis["coverage"]
        require(
            coverage["core_expected_pass_cells"] == coverage["core_formal_complete_cells"]
            and coverage["planned_core_raw_bits"] == coverage["formal_complete_core_raw_bits"],
            f"fixed core denominator incomplete: {key}",
        )
        observed_codecs.update(fully_observed_codecs(run.corpus, analysis))
        check_resume(path, raw, "CORE_COMPLETE")
        groups[key] = {
            "result": report["status"],
            "analysis_id": analysis["analysis_id"],
            "comparison_id": analysis["comparison_id"],
            "methods": analysis["distinct_core_methods"],
            "real_sources": analysis["independent_real_source_count"],
            "coverage": coverage,
            "domain": {
                field: read(path / "bundle.json")["contract"][field]
                for field in ("track", "fidelity", "recovery", "cost_boundary", "workload")
            },
            "auxiliary_cost_observation": validate_cost_evidence(path, "comparison"),
            "uncompressed_reference": validate_reference_evidence(path, "comparison"),
        }
        artifacts.extend(
            file_evidence(path / name)
            for name in (
                "analysis.json",
                "analysis_extensions.json",
                "comparison_trials.jsonl",
                "qualification.json",
                "pilot.json",
                "bundle.json",
                "execution_plan.json",
                "control_plane.json",
                "resume_verification.json",
                "report.html",
                "buffer_cost_audit.json",
                "buffer_cost_audit.md",
                "uncompressed_reference.json",
                "uncompressed_reference.md",
                "experiment_decision.json",
            )
        )
    active_keys = read(ROOT / "registry/algorithm_scope.json")["registered_codecs"]
    primitives = {
        key
        for key in active_keys
        if codecs.get(key).document["classification"]["object_level"] == "P0_PRIMITIVE"
    }
    required_complete_codecs = set(active_keys) - primitives
    require(
        required_complete_codecs <= observed_codecs,
        "current complete codecs lack two-source formal coverage: "
        + ", ".join(sorted(required_complete_codecs - observed_codecs)),
    )
    groups["entry_formal_coverage"] = {
        "complete_codec_count": len(required_complete_codecs),
        "two_source_formal_codecs": sorted(required_complete_codecs),
        "separate_primitive_qualification": sorted(primitives),
    }
    for key, name in declaration["workloads"].items():
        path = _path(evidence_root, name)
        require(read(path / "control_plane.json") == current, f"stale workload code: {key}")
        plan = read(path / "workload_plan.json")
        protocol = plan["protocol"]
        require(
            protocol["kind"] == ("STREAM" if key == "stream" else "QUERY"), "wrong workload kind"
        )
        if key != "stream":
            require(
                protocol["query_cache_policy"]
                == ("FRESH_SESSION_PER_QUERY" if key == "query-fresh" else "REUSED_SESSION"),
                "wrong query cache lane",
            )
        require(
            read(path / "execution_plan.json")["independent_real_source_count"] >= 2,
            "workload lacks two sources",
        )
        raw = path / "workload_trials.jsonl"
        before = sha(raw)
        report = report_workload_comparison(path)
        require(sha(raw) == before, f"workload report changed raw: {key}")
        require(report["status"] == "PROFILE_COMPLETE", f"incomplete workload: {key}")
        check_resume(path, raw, "PROFILE_COMPLETE")
        groups[key] = {"result": report["status"], **report}
        groups[key]["auxiliary_cost_observation"] = validate_cost_evidence(path, "workload")
        groups[key]["uncompressed_reference"] = validate_reference_evidence(path, "workload")
        artifacts.extend(
            file_evidence(path / name)
            for name in (
                "workload_plan.json",
                "workload_pilot.json",
                "workload_trials.jsonl",
                "workload_analysis.json",
                "workload_report.html",
                "resume_verification.json",
                "buffer_cost_audit.json",
                "buffer_cost_audit.md",
                "uncompressed_reference.json",
                "uncompressed_reference.md",
                "experiment_decision.json",
            )
        )
    path = _path(evidence_root, declaration["pipeline"])
    raw = path / "trials.jsonl"
    before = sha(raw)
    report = report_pipeline_comparison(path)
    require(sha(raw) == before, "P2 report changed raw")
    require(
        report["status"] == "COMPLETE"
        and report["expected_trials"] == report["recorded_trials"] == report["eligible_trials"],
        "incomplete P2 evidence",
    )
    pipeline_plan = read(path / "plan.json")
    require(
        len(pipeline_plan["datasets"]) >= 4
        and len({c["method_id"] for c in pipeline_plan["cells"]}) >= 2,
        "P2 task/method coverage incomplete",
    )
    require(
        {d["derivation"]["source_key"] for d in pipeline_plan["datasets"]} == {"etth1", "weather"},
        "P2 real sources differ",
    )
    require(
        {d["dataset_key"] for d in pipeline_plan["datasets"]}
        == {
            "etth1_f32",
            "weather_f32",
            "etth1_mixed_nd_tv_validity",
            "weather_mixed_nd_tv_validity",
        },
        "P2 profile coverage differs",
    )
    check_resume(path, raw, "COMPLETE", decoder_audit=True)
    groups["pipeline"] = {
        key: report[key]
        for key in (
            "status",
            "expected_trials",
            "eligible_trials",
            "fixed_cell_denominator",
            "scope",
            "timing_boundary",
            "inference_scope",
        )
    }
    groups["pipeline"]["auxiliary_cost_observation"] = validate_cost_evidence(path, "pipeline")
    groups["pipeline"]["uncompressed_reference"] = validate_reference_evidence(path, "pipeline")
    artifacts.extend(
        file_evidence(path / name)
        for name in (
            "plan.json",
            "qualification.json",
            "pilot.json",
            "trials.jsonl",
            "report.json",
            "resume_verification.json",
            "buffer_cost_audit.json",
            "buffer_cost_audit.md",
            "uncompressed_reference.json",
            "uncompressed_reference.md",
            "experiment_decision.json",
            "pipeline_events.jsonl",
        )
    )
    active = _path(evidence_root, declaration["active"])
    summary = validate_active(active)
    groups["active"] = summary
    artifacts.extend(
        file_evidence(active / name)
        for name in (
            "plan.json",
            "environment.json",
            "summary.json",
            "four_matrices.json",
            "role_ledger.json",
        )
    )
    for directory in ("cases", "datasets", "qualification_artifacts"):
        artifacts.extend(
            file_evidence(item)
            for item in sorted((active / directory).rglob("*"))
            if item.is_file()
        )
    from qualify_v32_channel_collection import validate_collection_qualification

    collection_path = _path(evidence_root, declaration["channel_collection"])
    groups["channel_collection"] = validate_collection_qualification(collection_path)
    artifacts.append(file_evidence(collection_path))
    collection = read(collection_path)
    for row in collection["cells"]:
        for key in ("raw", "encoded"):
            artifacts.append(file_evidence(_path(collection_path.parent, row[key]["path"])))
    validation_path = _path(evidence_root, declaration["validation"])
    validation = read(validation_path)
    validate_verification(validation, current)
    artifacts.append(file_evidence(validation_path))
    sdk_path = _path(evidence_root, declaration["sdk"])
    groups["sdk"] = validate_sdk_reference(read(sdk_path))
    artifacts.append(file_evidence(sdk_path))
    for key in ("legacy", "calibration", "stage_mapping"):
        path = _path(evidence_root, declaration[key])
        document = read(path)
        if key == "legacy":
            require(document["v32_formal_eligible"] is False, "legacy promoted to new formal")
            require(
                document["new_pairing_or_warmup_observations_generated"] is False,
                "fake legacy observations",
            )
            source = Path(document["derived_from"]["run_path"])
            for name, digest in document["derived_from"]["input_files"].items():
                require(sha(source / name) == digest, "legacy input was changed")
        if key == "calibration":
            require(
                document["source_population_inference"] is False,
                "simulation generalized to sources",
            )
            require(
                document["analysis_sha256"] == sha(ROOT / "src/tscompbench/comparison/analysis.py"),
                "stale calibration",
            )
            require(len(document["scenarios"]) == 4, "incomplete calibration scenarios")
        if key == "stage_mapping":
            from build_v32_active_role_ledger import build_document

            bundles = tuple(row["bundle"] for row in document["groups"])
            require(
                document == build_document(ROOT, bundles), "stage mapping not current or complete"
            )
        artifacts.append(file_evidence(path))
    result = {
        "schema_version": "tscb.v32-current-scope-acceptance.v1",
        "status": "CURRENT_CPU_SCOPE_COMPLETE",
        "declaration": declaration,
        "control_plane": current,
        "groups": groups,
        "artifacts": artifacts,
        "claim_limits": [
            "FROZEN_CORPORA_AND_LEGAL_DOMAINS_ONLY_NOT_FULL_MATHEMATICAL_DOMAIN_COVERAGE",
            "SOURCE_PARITY_UNKNOWN_IS_NOT_UPGRADED_BY_BENCH_PASS",
            "QUERY_SAME_METHOD_VARIANTS_NOT_TWO_INDEPENDENT_METHODS",
            "NO_NEW_ALGORITHMS_NO_LONG_TERM_CANDIDATE_MAJORITY_COMPLETION",
            "NO_SYSTEM_DEVICE_KERNEL_OR_UNKNOWN_LENGTH_BOUNDED_MEMORY_STREAM_CLAIM",
            "INCONCLUSIVE_INFERENCE_IS_RETAINED_DESPITE_COMPLETED_MEASUREMENTS",
        ],
    }
    result["acceptance_id"] = stable_id("v32-current-scope-acceptance", result, version="v3")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path)
    parser.add_argument("--declaration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.evidence_root.resolve(), read(args.declaration))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(canonical_json_bytes(result) + b"\n")
    print(json.dumps({"status": result["status"], "acceptance_id": result["acceptance_id"]}))


if __name__ == "__main__":
    main()
