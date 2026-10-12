"""Validate actual current-closure performance lanes and retain every gap.

Existing production validators recheck qualification/pilot/raw/identity/cost
evidence. P2 reporting also performs its declared independent decoder audit;
no performance is measured here and no upstream source parity is inferred.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from audit_v32_completion import (  # noqa: E402
    check_resume,
    fully_observed_codecs,
    validate_cost_evidence,
    validate_lane,
    validate_reference_evidence,
)
from run_frozen_queue import manifest  # noqa: E402

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
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan_path, runs, output = args.plan.resolve(), args.runs.resolve(), args.output.resolve()
    if output.exists() or not all(p.is_relative_to(ROOT) for p in (plan_path, runs, output)):
        parser.error("retain old evidence and choose a new project output")
    plan, queue, snapshot = (
        read(plan_path),
        read(runs / "queue_result.json"),
        read(runs / "input_snapshot.json"),
    )
    lanes = plan["lanes"]
    before = manifest(plan_path, lanes)
    assert before == snapshot["files"], "current project inputs differ from execution snapshot"
    control = control_plane_snapshot(ROOT)
    assert control == snapshot["control_plane"]
    assert queue["input_snapshot_unchanged"] is True
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    observed, rows = set(), []
    for lane in lanes:
        name, kind = lane["run_set_id"], lane["kind"]
        path = runs / name
        row = {"lane": name, "kind": kind, "status": "NOT_VERIFIED"}
        try:
            attempt = next(item for item in queue["results"] if item["lane"] == name)
            assert attempt["input_snapshot_unchanged"] is True
            row["attempt_exit_code"] = attempt["exit_code"]
            if attempt["exit_code"]:
                raise ValueError("lane driver did not complete; inspect retained attempt log")
            raw = (
                path
                / {
                    "comparison": "comparison_trials.jsonl",
                    "workload": "workload_trials.jsonl",
                    "pipeline": "trials.jsonl",
                }[kind]
            )
            raw_before = sha(raw)
            if kind == "comparison":
                assert read(path / "control_plane.json") == control
                validate_lane(name, read(path / "bundle.json"))
                run = prepare_comparison(
                    path / "bundle.json",
                    path.parent,
                    ROOT,
                    datasets,
                    codecs,
                    run_set_id=name,
                    resume=True,
                )
                validate_qualification_evidence(run, read(path / "qualification.json"))
                validate_comparison_pilots(run, read(path / "pilot.json"))
                report = report_comparison(path)
                analysis = read(path / "analysis.json")
                assert report["status"] == "CORE_COMPLETE"
                assert analysis["raw_sha256"] == raw_before
                assert analysis["distinct_core_methods"] >= 2
                assert analysis["independent_real_source_count"] >= 2
                coverage = analysis["coverage"]
                assert (
                    coverage["core_expected_pass_cells"] == coverage["core_formal_complete_cells"]
                )
                assert (
                    coverage["planned_core_raw_bits"] == coverage["formal_complete_core_raw_bits"]
                )
                observed.update(fully_observed_codecs(run.corpus, analysis))
                analysis_file = path / "analysis.json"
            elif kind == "workload":
                assert read(path / "control_plane.json") == control
                workload = read(path / "workload_plan.json")
                assert workload["protocol"]["kind"] == ("STREAM" if name == "stream" else "QUERY")
                if name != "stream":
                    assert workload["protocol"]["query_cache_policy"] == (
                        "FRESH_SESSION_PER_QUERY" if name == "query-fresh" else "REUSED_SESSION"
                    )
                assert read(path / "execution_plan.json")["independent_real_source_count"] >= 2
                report = report_workload_comparison(path)
                assert report["status"] == "PROFILE_COMPLETE"
                analysis_file = path / "workload_analysis.json"
            else:
                report = report_pipeline_comparison(path)
                assert report["status"] == "COMPLETE"
                assert (
                    report["expected_trials"]
                    == report["recorded_trials"]
                    == report["eligible_trials"]
                )
                p2 = read(path / "plan.json")
                assert {d["dataset_key"] for d in p2["datasets"]} == {
                    "etth1_f32",
                    "weather_f32",
                    "etth1_mixed_nd_tv_validity",
                    "weather_mixed_nd_tv_validity",
                }
                assert len({c["method_id"] for c in p2["cells"]}) >= 2
                analysis_file = path / "report.json"
            assert sha(raw) == raw_before
            check_resume(path, raw, report["status"], decoder_audit=kind == "pipeline")
            row.update(
                status="VERIFIED_CURRENT_FORMAL_LANE",
                raw=ref(raw),
                analysis=ref(analysis_file),
                report_status=report["status"],
                auxiliary_cost=validate_cost_evidence(path, kind),
                uncompressed_reference=validate_reference_evidence(path, kind),
                qualification=ref(path / "qualification.json"),
                resume=ref(path / "resume_verification.json"),
            )
        except Exception as error:
            row.update(status="NOT_VERIFIED", error_type=type(error).__name__, error=str(error))
        rows.append(row)
    stable = before == manifest(plan_path, lanes) and control == control_plane_snapshot(ROOT)
    assert stable, "inputs changed during audit"
    active = set(read(ROOT / "registry/algorithm_scope.json")["registered_codecs"])
    primitives = {
        key
        for key in active
        if codecs.get(key).document["classification"]["object_level"] == "P0_PRIMITIVE"
    }
    missing = sorted(active - primitives - observed)
    complete = (
        len(rows) == 16
        and not missing
        and all(row["status"] == "VERIFIED_CURRENT_FORMAL_LANE" for row in rows)
    )
    document = {
        "schema_version": "tscb.current-formal-evidence-audit.v1",
        "status": "CURRENT_DECLARED_FORMAL_SCOPE_VERIFIED"
        if complete
        else "CURRENT_FORMAL_SCOPE_HAS_GAPS",
        "plan": ref(plan_path),
        "queue_result": ref(runs / "queue_result.json"),
        "driver": ref(Path(__file__)),
        "input_snapshot_unchanged": stable,
        "lanes": rows,
        "two_independent_real_source_complete_codecs": sorted(observed),
        "missing_two_source_formal_codecs": missing,
        "separate_primitive_entries": sorted(primitives),
        "performance_remeasured_by_audit": False,
        "codec_execution_by_audit": "P2_REPORT_INDEPENDENT_DECODER_ONLY",
        "full_upstream_parity_granted": False,
        "all_N_G_CAP_gates_granted": False,
        "claim_boundary": (
            "Frozen existing CPU corpora, legal domains and declared profiles only; "
            "statistical INCONCLUSIVE remains and does not grant algorithm superiority."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(canonical_json_bytes(document) + b"\n")
    print(
        json.dumps(
            {
                "status": document["status"],
                "verified_lanes": sum(r["status"] == "VERIFIED_CURRENT_FORMAL_LANE" for r in rows),
                "missing_formal_codecs": missing,
            }
        ),
        flush=True,
    )
    raise SystemExit(0 if complete else 1)


if __name__ == "__main__":
    main()
