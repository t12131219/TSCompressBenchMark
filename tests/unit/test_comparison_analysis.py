from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from tscompbench.comparison.analysis import AnalysisPolicy, analyze_comparison, trial_issues


def _experiment():
    policy = AnalysisPolicy(bootstrap_samples=200, primary_comparisons=(("a", "b"),))
    cells = []
    for member in ("a", "b"):
        for dataset in ("d1", "d2"):
            cells.append(
                {
                    "cell_id": member + dataset,
                    "member_id": member,
                    "method_id": member,
                    "dataset_id": dataset,
                    "config_label": "default",
                    "role": "CORE",
                    "expected_outcome": "PASS",
                    "canonical_raw_bits": 8000,
                    "execution_job_id": "job-" + member + dataset,
                    "public_projection_key": "projection-" + dataset,
                }
            )
    plan = {
        "schema_version": "tscb.comparison-execution-plan.v1",
        "cells": cells,
        "comparison_id": "comparison",
        "protocol_id": "new-protocol",
        "schedule_id": "s",
        "analysis_policy_id": policy.id,
        "planned_repetitions_per_cell": 4,
        "independent_real_source_count": 2,
        "pilot_eligible": True,
        "protocol": {
            "start_method": "spawn",
            "encode_min_ns": 1000,
            "decode_min_ns": 1000,
            "warmup_min_count": 1,
            "warmup_min_ns": 1,
        },
    }
    trials = []
    for cell in cells:
        for block in range(4):
            speed = 2 if cell["member_id"] == "a" else 1
            record = {
                "dataset_id": cell["dataset_id"],
                "run_id": cell["cell_id"] + str(block),
                "status": "PASS",
                "record_kind": "FORMAL_REPETITION",
                "eligibility": True,
                "correctness": {"status": "PASS"},
                "accounting": {
                    "canonical_raw_bits": 8000,
                    "serialized_bits": 700,
                    "external_side_information_bits": 300,
                    "final_bits": 1000,
                },
                "timing": {
                    "inner_iterations": 2,
                    "selected_encode_wall_ns": 2000 * speed,
                    "selected_decode_wall_ns": 2000 * speed,
                },
                "diagnostics": {
                    "threshold_protocol": "new-protocol",
                    "independent_recovery": {
                        "output_materialization": "OWNED_CANONICAL_BUFFERS",
                        "qualification": {
                            "start_method": "spawn",
                            "original_input_available": False,
                            "encoder_session_available": False,
                            "output_owned_in_worker": True,
                        },
                    },
                    "worker_lifecycle": {
                        "worker_exit_confirmed": True,
                        "worker_pid": 123,
                        "start_method": "spawn",
                        "exit_code": 0,
                    },
                    "worker_measurement": {
                        "warmup_worker_pid": 123,
                        "measurement_worker_pid": 123,
                        "warmup": {
                            "threshold_satisfied": True,
                            "completed_iterations": 1,
                            "elapsed_wall_ns": 100,
                        },
                    },
                },
            }
            trials.append(
                {
                    "schema_version": "tscb.comparison-trial.v1",
                    "cell_id": cell["cell_id"],
                    "trial_id": cell["cell_id"] + str(block),
                    "block_id": str(block),
                    "pair_id": cell["dataset_id"] + str(block),
                    "record": record,
                    "protocol_id": "new-protocol",
                    "schedule_id": "s",
                    "comparison_id": "comparison",
                    "execution_job_id": cell["execution_job_id"],
                    "public_projection_key": cell["public_projection_key"],
                    "lease_held": True,
                    "resource_lease_id": "lease",
                    "qualification_status": "PASS",
                    "environment_gate": {"eligible": True},
                    "artifacts_verified": True,
                    "formal_eligible": True,
                }
            )
    for cell in cells:
        cell.update(
            algorithm_id="algorithm-" + cell["member_id"],
            legacy_config_id="config-" + cell["member_id"],
            task_id="task-" + cell["cell_id"],
            execution_path_hash="execution-" + cell["cell_id"],
            input_sha256="input-" + cell["dataset_id"],
            track="VALUE",
        )
    by_id = {c["cell_id"]: c for c in cells}
    slots = []
    for index, trial in enumerate(trials):
        cell = by_id[trial["cell_id"]]
        trial.update(sequence_index=index, repetition_index=int(trial["block_id"]), round_index=0)
        trial["record"].update(
            {
                key: cell[ckey]
                for key, ckey in (
                    ("algorithm_id", "algorithm_id"),
                    ("config_id", "legacy_config_id"),
                    ("task_id", "task_id"),
                    ("execution_path_hash", "execution_path_hash"),
                    ("input_sha256", "input_sha256"),
                    ("track", "track"),
                )
            }
        )
        trial["record"]["repetition_index"] = trial["repetition_index"]
        slots.append(
            {
                "trial_id": trial["trial_id"],
                "pair_id": trial["pair_id"],
                "block_index": int(trial["block_id"]),
                "sequence_index": index,
                "repetition_index": trial["repetition_index"],
                "round_index": 0,
                "execution_job_id": trial["execution_job_id"],
                "dataset_id": cell["dataset_id"],
            }
        )
    plan["schedule"] = {"trials": slots}
    return plan, trials, policy


def test_paired_analysis_uses_outer_blocks_and_fixed_workload():
    plan, trials, policy = _experiment()
    result = analyze_comparison(plan, trials, policy)
    assert result["status"] == "CORE_COMPLETE"
    assert result["coverage"]["core_expected_pass_cells"] == 4
    effect = result["paired_comparisons"][0]["directions"]["encode"]
    assert effect["estimate"] == 2
    assert effect["paired_blocks"] == 4
    assert effect["confidence_interval"] == [2, 2]
    assert effect["family_size"] == 4
    assert effect["status"] == "SECOND_MEMBER_FASTER"
    assert result["corpus_aggregates"][0]["directions"]["encode"]["semantic_mb_per_second"] == 500.0
    assert result == analyze_comparison(plan, trials, policy)


def test_missing_cell_keeps_denominator_and_blocks_core_aggregate():
    plan, trials, policy = _experiment()
    partial = [t for t in trials if t["cell_id"] != "ad2"]
    result = analyze_comparison(plan, partial, policy)
    assert result["status"] == "CORE_INCOMPLETE"
    assert result["coverage"]["planned_cells"] == 4
    assert result["coverage"]["planned_core_raw_bits"] == 32000
    assert result["corpus_aggregates"][0]["directions"] is None
    assert result["core_gaps"] == [{"cell_id": "ad2", "status": "NOT_RUN"}]


@pytest.mark.parametrize("record_state", ["null", "missing", "empty"])
def test_stopped_cold_trials_keep_fixed_denominator_and_never_qualify(record_state):
    plan, trials, policy = _experiment()
    plan["protocol"]["profile"] = "COLD_PROCESS"
    for trial in trials:
        trial["status"] = "STOPPED"
        if record_state == "missing":
            del trial["record"]
        else:
            trial["record"] = None if record_state == "null" else {}
    original = copy.deepcopy((plan, trials))

    issues = trial_issues(trials[0], plan["cells"][0], plan)
    assert "FORMAL_EXECUTION_NOT_PASS" in issues
    assert "COLD_EVIDENCE_MISSING_OR_INVALID" in issues
    result = analyze_comparison(plan, trials, policy)

    assert result["status"] == "CORE_INCOMPLETE"
    assert result["coverage"] == {
        "planned_cells": 4,
        "terminal_cells": 4,
        "core_expected_pass_cells": 4,
        "core_planned_cells": 4,
        "core_formal_complete_cells": 0,
        "planned_core_raw_bits": 32000,
        "formal_complete_core_raw_bits": 0,
    }
    assert len(result["matrix"]) == len(plan["cells"])
    assert len(result["core_gaps"]) == 4
    assert all(row["planned_process_count"] == 4 for row in result["matrix"])
    assert all(row["eligible_process_count"] == 0 for row in result["matrix"])
    assert all(row["status"] == "NO_ELIGIBLE_FORMAL" for row in result["matrix"])
    assert all(row["formal_complete"] is False for row in result["matrix"])
    assert all(row["final_bits"] is None for row in result["matrix"])
    assert all(row["directions"] is None for row in result["matrix"])
    assert len(result["exclusions"]) == len(trials) == 16
    assert all(item["status"] == "STOPPED" for item in result["exclusions"])
    assert all(
        "COLD_EVIDENCE_MISSING_OR_INVALID" in item["issues"]
        and "FORMAL_EXECUTION_NOT_PASS" in item["issues"]
        for item in result["exclusions"]
    )
    assert all(item["status"] == "CORE_INCOMPLETE" for item in result["corpus_aggregates"])
    assert all(item["fixed_raw_bits"] == 16000 for item in result["corpus_aggregates"])
    assert all(item["directions"] is None for item in result["corpus_aggregates"])
    assert all(item["size_ratio"] is None for item in result["corpus_aggregates"])
    assert (plan, trials) == original


@pytest.mark.parametrize(
    "change,reason",
    [
        ("legacy", "LEGACY_THRESHOLD_EVIDENCE"),
        ("resource", "RESOURCE_LEASE_MISSING"),
        ("recovery", "FRESH_RECOVERY_NOT_PASS"),
        ("accounting", "FINAL_BITS_NOT_CLOSED"),
        ("warmup", "WORKER_WARMUP_NOT_MET"),
        ("pilot", "PILOT_NOT_QUALIFIED"),
    ],
)
def test_eligibility_boolean_cannot_override_raw_evidence(change, reason):
    plan, trials, _ = _experiment()
    trial = copy.deepcopy(trials[0])
    if change == "legacy":
        trial["record"]["diagnostics"]["threshold_protocol"] = "LEGACY_V2"
    elif change == "resource":
        trial["lease_held"] = False
    elif change == "recovery":
        trial["record"]["diagnostics"]["independent_recovery"]["qualification"][
            "original_input_available"
        ] = True
    elif change == "accounting":
        trial["record"]["accounting"]["final_bits"] += 1
    elif change == "warmup":
        trial["record"]["diagnostics"]["worker_measurement"]["warmup"]["threshold_satisfied"] = (
            False
        )
    else:
        plan["pilot_eligible"] = False
    assert reason in trial_issues(trial, plan["cells"][0], plan)


def test_unpaired_trials_do_not_invent_pairing():
    plan, trials, policy = _experiment()
    for t in trials:
        if t["cell_id"].startswith("b"):
            t["block_id"] = str(int(t["block_id"]) + 10)
    result = analyze_comparison(plan, trials, policy)
    assert result["paired_comparisons"][0]["directions"]["encode"]["status"] == "INCONCLUSIVE"
    assert result["paired_comparisons"][0]["directions"]["encode"]["paired_blocks"] == 0


def test_pairing_intersects_process_slots_before_averaging_rounds_within_blocks():
    plan, original, policy = _experiment()
    plan["planned_repetitions_per_cell"] = 8
    expanded = []
    slots = []
    for base in original:
        for round_index in range(2):
            trial = copy.deepcopy(base)
            trial["trial_id"] += "-round" + str(round_index)
            trial["pair_id"] += "-round" + str(round_index)
            trial["round_index"] = round_index
            trial["repetition_index"] = int(trial["block_id"]) * 2 + round_index
            trial["sequence_index"] = len(slots)
            record = trial["record"]
            record["repetition_index"] = trial["repetition_index"]
            # The unmatched first method's slow round must never enter a paired mean.
            value = 2_000_000 if round_index == 0 else 2000 if trial["cell_id"][0] == "a" else 4000
            record["timing"].update(selected_encode_wall_ns=value, selected_decode_wall_ns=value)
            slots.append(
                {
                    "trial_id": trial["trial_id"],
                    "pair_id": trial["pair_id"],
                    "block_index": int(trial["block_id"]),
                    "sequence_index": trial["sequence_index"],
                    "repetition_index": trial["repetition_index"],
                    "round_index": round_index,
                    "execution_job_id": trial["execution_job_id"],
                    "dataset_id": record["dataset_id"],
                }
            )
            if round_index == 1 or trial["cell_id"][0] == "a":
                expanded.append(trial)
    plan["schedule"]["trials"] = slots
    result = analyze_comparison(plan, expanded, policy)
    effect = result["paired_comparisons"][0]["directions"]["encode"]
    assert effect["paired_process_slots"] == 4
    assert effect["paired_blocks"] == 4
    assert effect["estimate"] == 0.5
    assert result["status"] == "CORE_INCOMPLETE"


def test_malformed_block_is_audited_instead_of_crashing_report():
    plan, trials, _ = _experiment()
    trials[0]["block_id"] = {"not": "an index"}
    assert "SCHEDULE_SLOT_MISMATCH" in trial_issues(trials[0], plan["cells"][0], plan)


def test_declared_fixed_error_budget_requires_matching_actual_validator_evidence():
    plan, trials, _ = _experiment()
    cell = plan["cells"][0]
    cell.update(
        loss_mode="ERROR_BOUNDED_LOSSY",
        parameters={"error_bound_type": "ABS", "error_bound": "0.001"},
        guarantee={
            "metric": "MAXAE_V1",
            "threshold": "0.001",
            "unit": "ORIGINAL_VALUE_UNITS",
            "original_domain_total": True,
        },
    )
    loss = {
        "schema_version": "tscb.loss-validation.v3",
        "error_bound_type": "ABS",
        "error_bound": "0.001",
        "bound_passed": True,
        "raw_violation_count": 0,
        "quality_valid": True,
        "nonfinite_mismatch_count": 0,
    }
    trials[0]["record"]["correctness"]["loss"] = loss
    reason = "FROZEN_ORIGINAL_DOMAIN_ERROR_GUARANTEE_NOT_VERIFIED"
    assert reason not in trial_issues(trials[0], cell, plan)
    loss["error_bound"] = "1.0"
    assert reason in trial_issues(trials[0], cell, plan)


def test_core_rejections_do_not_remove_cells_or_claim_second_source_completion():
    plan, trials, policy = _experiment()
    for cell in plan["cells"]:
        if cell["dataset_id"] == "d2":
            cell["expected_outcome"] = "REJECT"
    result = analyze_comparison(plan, [t for t in trials if t["cell_id"].endswith("d1")], policy)
    assert result["status"] == "CORE_INCOMPLETE"
    assert result["coverage"]["planned_core_raw_bits"] == 32000
    assert result["coverage"]["core_planned_cells"] == 4
    assert len(result["core_gaps"]) == 2


@pytest.mark.parametrize(
    "field", ["algorithm_id", "config_id", "task_id", "execution_path_hash", "repetition_index"]
)
def test_record_cannot_use_a_different_execution_identity(field):
    plan, trials, _ = _experiment()
    trial = copy.deepcopy(trials[0])
    trial["record"][field] = "some-other-execution"
    assert trial_issues(trial, plan["cells"][0], plan)


def test_pair_labels_must_come_from_actual_frozen_schedule():
    plan, trials, policy = _experiment()
    for trial in trials:
        if trial["cell_id"].startswith("b"):
            trial["pair_id"] = "different-pair-" + trial["pair_id"]
    result = analyze_comparison(plan, trials, policy)
    assert result["status"] == "CORE_INCOMPLETE"
    assert any("SCHEDULE_SLOT_MISMATCH" in e["issues"] for e in result["exclusions"])


def test_duplicate_observations_and_policy_drift_are_rejected():
    plan, trials, policy = _experiment()
    with pytest.raises(ValueError, match="duplicate TrialID"):
        analyze_comparison(plan, trials + [trials[0]], policy)
    with pytest.raises(ValueError, match="differs"):
        analyze_comparison(plan, trials, replace(policy, seed=3))
    with pytest.raises(ValueError, match="fields"):
        AnalysisPolicy.from_document({**policy.to_document(), "posthoc_weights": [1, 0]})
