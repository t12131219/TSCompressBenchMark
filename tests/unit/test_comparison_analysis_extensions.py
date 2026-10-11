from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_comparison_analysis import _experiment

from tscompbench.comparison.analysis import analyze_comparison
from tscompbench.comparison.analysis_extensions import augment_analysis

ROOT = Path(__file__).resolve().parents[2]


def experiment():
    plan, trials, policy = _experiment()
    for cell in plan["cells"]:
        cell.update(
            loss_mode="LOSSLESS",
            parameters={},
            guarantee={"kind": "LOSSLESS", "original_domain_total": True, "unit": "BITWISE"},
        )
    for trial in trials:
        trial["record"]["resources"] = {
            "actual_scope": "PROCESS",
            "peak_process_rss_bytes": 100,
        }
    corpus = json.loads((ROOT / "tests/fixtures/comparison/byte_bundle.json").read_text())["corpus"]
    for index, row in enumerate(corpus["datasets"]):
        row["dataset_id"] = f"d{index + 1}"
    return plan, trials, policy, corpus


def add_quality(plan, trials, *, mode="UNBOUNDED_LOSSY"):
    for cell in plan["cells"]:
        cell["loss_mode"] = mode
        cell["parameters"] = {"error_bound_type": "ABSOLUTE", "error_bound": "0.1"}
        cell["guarantee"] = {
            "kind": "PROVEN_BOUND" if mode == "ERROR_BOUNDED_LOSSY" else "UNBOUNDED",
            "original_domain_total": mode == "ERROR_BOUNDED_LOSSY",
            "metric": "MAXAE_V1" if mode == "ERROR_BOUNDED_LOSSY" else None,
            "threshold": "0.1" if mode == "ERROR_BOUNDED_LOSSY" else None,
            "unit": "ORIGINAL_VALUE_UNITS",
        }
    for trial in trials:
        trial["record"]["correctness"]["loss"] = {
            "schema_version": "tscb.loss-validation.v3",
            "quality_valid": True,
            "error_bound_type": "ABSOLUTE",
            "error_bound": "0.1",
            "bound_passed": True,
            "raw_violation_count": 0,
            "nonfinite_mismatch_count": 0,
            "channels": [
                {
                    "name": "value/000000",
                    "quality_valid": True,
                    "rmse": "0.03",
                    "max_ae": "0.05",
                    "finite_pair_count": 100,
                    "nonfinite_mismatch_count": 0,
                },
                {
                    "name": "value/000001",
                    "quality_valid": True,
                    "rmse": "0.04",
                    "max_ae": "0.06",
                    "finite_pair_count": 100,
                    "nonfinite_mismatch_count": 0,
                },
            ],
        }


def extensions(plan, trials, policy, corpus):
    analysis = analyze_comparison(plan, trials, policy)
    return augment_analysis(analysis, plan, trials, corpus)


def test_original_domain_quality_points_preserve_parameters_and_guarantees():
    plan, trials, policy, corpus = experiment()
    add_quality(plan, trials)
    ext = extensions(plan, trials, policy, corpus)
    points = ext["quality_curve"]["points"]
    assert all(point["quality_curve_eligible"] for point in points)
    assert all(point["parameters"]["error_bound"] == "0.1" for point in points)
    assert all(point["guarantee"]["kind"] == "UNBOUNDED" for point in points)
    assert all(point["fixed_error_ranking_eligible"] is False for point in points)
    assert points[0]["quality"]["original_domain_max_ae"] == "0.06"
    assert float(points[0]["quality"]["original_domain_rmse"]) == pytest.approx(0.035355339)
    assert len(points[0]["quality"]["ranking_metrics"]) == 4
    assert "RMSE_V1:value/000000" in ext["pareto"][0]["objectives_minimized"]


def test_native_api_cost_excludes_context_without_hiding_full_recovery_cost():
    plan, trials, policy, corpus = experiment()
    plan["contract"] = {"cost_boundary": "NATIVE_COMPONENT"}
    for cell in plan["cells"]:
        cell["cost_boundary"] = "NATIVE_COMPONENT"
    for trial in trials:
        ledger = trial["record"]["accounting"]
        ledger["serialized_bits"] = 400 if trial["cell_id"].startswith("a") else 800
        ledger["external_side_information_bits"] = 1000 - ledger["serialized_bits"]
    analysis = analyze_comparison(plan, trials, policy)
    ext = augment_analysis(analysis, plan, trials, corpus)
    a = next(row for row in analysis["matrix"] if row["cell_id"] == "ad1")
    assert a["final_bits"]["mean"] == 1000
    assert a["comparison_cost_bits"]["mean"] == 400
    assert a["size_ratio"] == 0.05
    point = next(row for row in ext["quality_curve"]["points"] if row["cell_id"] == "ad1")
    assert point["metrics"]["observations"]["final_bits"]["mean"] == "1000"
    assert point["metrics"]["objectives"]["api_serialized_bits"] == "400"
    assert "final_bits" not in point["metrics"]["objectives"]
    assert ext["pareto"][0]["objectives_minimized"][0] == "api_serialized_bits"
    assert ext["source_balanced"]["aggregates"][0]["source_balanced_size_ratio"] == "0.05"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "POSITIVE_INFINITY", None])
def test_invalid_quality_never_enters_frontier_or_becomes_zero(bad):
    plan, trials, policy, corpus = experiment()
    add_quality(plan, trials)
    trials[0]["record"]["correctness"]["loss"]["channels"][0]["rmse"] = bad
    ext = extensions(plan, trials, policy, corpus)
    point = next(point for point in ext["quality_curve"]["points"] if point["cell_id"] == "ad1")
    assert point["quality"]["status"] == "INVALID_OR_MISSING"
    assert point["quality"]["original_domain_rmse"] is None
    assert point["quality_curve_eligible"] is False
    assert "ad1" not in ext["pareto"][0]["frontier_cell_ids"]
    assert ext["pareto"][0]["full_universe_frontier"] is False


def test_proven_bound_curve_point_does_not_grant_fixed_error_protocol_ranking():
    plan, trials, policy, corpus = experiment()
    add_quality(plan, trials, mode="ERROR_BOUNDED_LOSSY")
    plan["fidelity"] = {"kind": "QUALITY_CURVE"}
    ext = extensions(plan, trials, policy, corpus)
    assert all(p["declared_guarantee_verified_in_cell"] for p in ext["quality_curve"]["points"])
    assert all(not p["fixed_error_ranking_eligible"] for p in ext["quality_curve"]["points"])
    plan["fidelity"] = {"kind": "FIXED_ERROR"}
    ext = extensions(plan, trials, policy, corpus)
    assert all(p["fixed_error_ranking_eligible"] for p in ext["quality_curve"]["points"])


def test_lossless_reference_and_actual_four_objective_frontier_are_explicit():
    plan, trials, policy, corpus = experiment()
    ext = extensions(plan, trials, policy, corpus)
    assert ext["pareto"][0]["frontier_cell_ids"] == ["bd1"]
    assert ext["pareto"][0]["dominated_by"] == {"ad1": ["bd1"]}
    assert ext["pareto"][0]["full_universe_frontier"] is True
    assert ext["quality_curve"]["points"][0]["quality"]["reference_only"] is True
    assert ext["quality_curve"]["points"][0]["quality_curve_eligible"] is False
    for trial in trials:
        if trial["cell_id"] == "bd1":
            trial["record"]["resources"]["actual_scope"] = "WORKER_SUBSET"
    ext = extensions(plan, trials, policy, corpus)
    assert ext["pareto"][0]["full_universe_frontier"] is False
    missing = ext["pareto"][0]["unavailable"][0]
    assert missing["status"] == "N/A"
    assert missing["missing_metrics"] == ["process_rss_bytes"]


def test_source_groups_collapse_shared_windows_and_preserve_missing_source_denominator():
    plan, trials, policy, corpus = experiment()
    corpus["datasets"][1]["source"]["family"] = corpus["datasets"][0]["source"]["family"]
    ext = extensions(plan, trials, policy, corpus)
    assert ext["source_balanced"]["independent_source_count"] == 1
    assert ext["source_balanced"]["aggregates"][0]["planned_cells"] == 2
    plan, trials, policy, corpus = experiment()
    trials = [trial for trial in trials if trial["cell_id"] != "ad2"]
    ext = extensions(plan, trials, policy, corpus)
    aggregate = ext["source_balanced"]["aggregates"][0]
    assert aggregate["planned_source_groups"] == 2
    assert aggregate["complete_source_groups"] == 1
    assert aggregate["status"] == "INCOMPLETE"
    assert aggregate["source_balanced_size_ratio"] is None
    assert ext["coverage_matrices"]["fixed_planned_cells"] == 4
    assert all(len(view) == 4 for view in ext["coverage_matrices"]["views"].values())
    assert (
        ext["coverage_matrices"]["views"]["SourceCapabilityMatrix"][0]["claim_status"] == "UNKNOWN"
    )


def test_extensions_recheck_raw_binding_and_never_mutate_inputs():
    plan, trials, policy, corpus = experiment()
    analysis = analyze_comparison(plan, trials, policy)
    originals = copy.deepcopy((analysis, plan, trials, corpus))
    first = augment_analysis(analysis, plan, trials, corpus)
    assert first == augment_analysis(analysis, plan, trials, corpus)
    assert (analysis, plan, trials, corpus) == originals
    changed = copy.deepcopy(trials)
    changed[0]["record"]["timing"]["selected_encode_wall_ns"] = 99999
    with pytest.raises(ValueError, match="raw observations differ"):
        augment_analysis(analysis, plan, changed, corpus)
    del analysis["audited_trials_sha256"]
    changed[0]["record"]["dataset_id"] = "other-source"
    ext = augment_analysis(analysis, plan, changed, corpus)
    assert ext["audit_issues"]
    assert ext["quality_curve"]["points"][0]["formal_complete"] is False
