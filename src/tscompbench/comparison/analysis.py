"""Read-only analysis of a frozen V3 comparison and its actual paired trials.

This module never invokes a codec or promotes historical v2 observations. The
sampling population is the frozen corpus on the measured host, not all sources.
"""

from __future__ import annotations

import hashlib
import itertools
import statistics
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.ids import canonical_json_bytes, stable_id


@dataclass(frozen=True)
class AnalysisPolicy:
    schema_version: str = "tscb.analysis-policy.v1"
    estimand: str = "FIXED_CORPUS_PAIRED_PROCESS_TIME_RATIO"
    confidence_level: str = "0.95"
    bootstrap_samples: int = 4000
    seed: int = 20261010
    resampling_unit: str = "SCHEDULE_BLOCK"
    corpus_weighting: str = "FIXED_WORKLOAD"
    time_estimator: str = "MEAN_PROCESS_TIME_PER_OBJECT"
    multiplicity_policy: str = "BONFERRONI_FAMILYWISE_INTERVALS"
    minimum_paired_blocks: int = 4
    minimum_practical_effect: str = "0.02"
    target_relative_ci_half_width: str = "0.10"
    missing_policy: str = "KEEP_FIXED_DENOMINATOR_NO_CORE_AGGREGATE"
    primary_comparisons: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        supported = {
            "schema_version": "tscb.analysis-policy.v1",
            "estimand": "FIXED_CORPUS_PAIRED_PROCESS_TIME_RATIO",
            "resampling_unit": "SCHEDULE_BLOCK",
            "corpus_weighting": "FIXED_WORKLOAD",
            "time_estimator": "MEAN_PROCESS_TIME_PER_OBJECT",
            "multiplicity_policy": "BONFERRONI_FAMILYWISE_INTERVALS",
            "missing_policy": "KEEP_FIXED_DENOMINATOR_NO_CORE_AGGREGATE",
        }
        for key, value in supported.items():
            if getattr(self, key) != value:
                raise ValueError(f"unsupported {key}: {getattr(self, key)}")
        for key in (
            "confidence_level",
            "minimum_practical_effect",
            "target_relative_ci_half_width",
        ):
            value = getattr(self, key)
            try:
                number = Decimal(value) if isinstance(value, str) else Decimal("NaN")
            except InvalidOperation as error:
                raise ValueError(f"invalid {key}") from error
            if not number.is_finite() or not 0 < number < 1:
                raise ValueError(f"{key} must be a finite decimal string in (0,1)")
        if type(self.bootstrap_samples) is not int or self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be an integer >= 100")
        if type(self.minimum_paired_blocks) is not int or self.minimum_paired_blocks < 2:
            raise ValueError("at least two paired blocks are required")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        pairs = self.primary_comparisons
        if any(
            len(p) != 2 or p[0] == p[1] or not all(isinstance(s, str) and s for s in p)
            for p in pairs
        ):
            raise ValueError("primary comparisons must contain distinct member IDs")
        if len({tuple(sorted(p)) for p in pairs}) != len(pairs):
            raise ValueError("duplicate primary comparison")

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> AnalysisPolicy:
        if not isinstance(document, dict):
            raise ValueError("analysis policy must be a document")
        unknown = set(document) - set(cls.__dataclass_fields__)
        if unknown or document.get("schema_version") != "tscb.analysis-policy.v1":
            raise ValueError(f"invalid analysis policy version/fields: {sorted(unknown)}")
        values = dict(document)
        if "primary_comparisons" in values:
            if not isinstance(values["primary_comparisons"], list):
                raise ValueError("primary_comparisons must be an array")
            values["primary_comparisons"] = tuple(tuple(p) for p in values["primary_comparisons"])
        return cls(**values)

    def to_document(self) -> dict[str, Any]:
        return {**asdict(self), "primary_comparisons": [list(p) for p in self.primary_comparisons]}

    @property
    def id(self) -> str:
        return stable_id("analysis-policy", self.to_document())


def _cold_trial_issues(
    trial: dict[str, Any], cell: dict[str, Any], plan: dict[str, Any]
) -> list[str]:
    """Recheck actual cold direction boundaries; never accept relabeled steady evidence."""
    from tscompbench.execution.cold_driver import ColdResourceObservation
    from tscompbench.measurement.thread_monitor import thread_budget_evidence

    issues = []
    record = trial["record"]
    diagnostics = record.get("diagnostics") or {}
    timing = record.get("timing") or {}
    resources = record.get("resources") or {}
    recovery = diagnostics.get("independent_recovery") or {}
    boundary = "SPAWN_THROUGH_PARENT_OWNED_OUTPUT_MATERIALIZATION"
    try:
        observation = diagnostics["cold_observation"]
        expected_resources = ColdResourceObservation(
            resources["encode"], resources["decode"], resources["parent"]
        ).to_document()
        expected_fallback = "SOURCE_REJECT_RAW" in cell["allowed_paths"]
        if (
            observation["schema_version"] != "tscb.cold-object-observation.v3.2"
            or observation["status"] != record["status"]
            or observation["timing"] != timing
            or observation["resources"] != resources
            or observation["accounting"] != record["accounting"]
            or observation["correctness"] != record["correctness"]
            or observation["bitstream_sha256"] != record["bitstream_sha256"]
            or observation["input_immutable"] is not True
            or observation["canary_intact"] is not True
            or resources != expected_resources
            or resources["swap_observed"] is True
            or diagnostics["profile"] != "COLD_PROCESS"
            or diagnostics["warmup_count"] != 0
            or diagnostics["inner_iterations"] != 1
            or diagnostics["development_only"] is not False
            or diagnostics["collector_enabled"] is not True
            or diagnostics["source_reject_fallback"] != expected_fallback
            or diagnostics["measurement_boundary"] != boundary
            or timing["schema_version"] != "tscb.cold-timing-observation.v3.2"
            or timing["profile"] != "COLD_PROCESS"
            or timing["timing_boundary"] != boundary
            or timing["inner_iterations"] != 1
            or timing["min_duration_satisfied"] is not True
            or timing["selected_wall_ns"]
            != timing["selected_encode_wall_ns"] + timing["selected_decode_wall_ns"]
            or timing["canonical_bytes_per_iteration"] != (cell["canonical_raw_bits"] + 7) // 8
            or timing["startup_import_adapter_loading_included"] is not True
            or timing["parent_input_pickle_result_ipc_materialization_and_worker_exit_included"]
            is not True
            or timing["os_cache_cleared"] is not False
            or recovery["qualification_evidence_scope"] != "SAME_MEASURED_COLD_DECODE_WORKER"
            or recovery["parent_output_owned"] is not True
            or diagnostics["same_object_correctness_and_measurement"] is not True
        ):
            issues.append("COLD_OBJECT_BOUNDARY_OR_VALIDATION_INVALID")
        lifecycles = [
            diagnostics["encode_worker_lifecycle"],
            diagnostics["decode_worker_lifecycle"],
        ]
        pids = []
        for direction, lifecycle in zip(("encode", "decode"), lifecycles, strict=True):
            pid = lifecycle["worker_pid"]
            pids.append(pid)
            selected = timing[f"selected_{direction}_wall_ns"]
            if (
                type(pid) is not int
                or pid <= 0
                or pid == lifecycle["parent_pid"]
                or lifecycle["start_method"] != "spawn"
                or lifecycle["worker_exit_confirmed"] is not True
                or lifecycle["exit_code"] != 0
                or lifecycle["boundary"] != boundary
                or lifecycle["selected_parent_wall_ns"] != selected
                or lifecycle["parent_owned_materialization_finished_ns"]
                - lifecycle["parent_started_ns"]
                != selected
                or not trial["started_ns"]
                <= lifecycle["parent_started_ns"]
                <= lifecycle["parent_finished_ns"]
                <= lifecycle["parent_owned_materialization_finished_ns"]
                <= trial["finished_ns"]
                or resources[direction]["collector_enabled"] is not True
                or resources[direction]["function_boundary"]["actual_scope"] != "PROCESS"
                or resources[direction]["function_boundary"]["scope_availability"] != "AVAILABLE"
                or lifecycle["thread_budget_evidence"]
                != thread_budget_evidence(
                    lifecycle["thread_observation"], thread_budget=cell["resources"]["threads"]
                )
                or lifecycle["thread_budget_evidence"]["observed_excess"]
                or any(
                    value is not None and value > cell["resources"]["threads"]
                    for value in (
                        resources[direction]["function_boundary"]["thread_count_before"],
                        resources[direction]["function_boundary"]["thread_count_after"],
                    )
                )
            ):
                issues.append("COLD_FRESH_DIRECTION_LIFECYCLE_INVALID")
        if (
            pids[0] == pids[1]
            or lifecycles[0]["parent_owned_materialization_finished_ns"]
            > lifecycles[1]["parent_started_ns"]
            or lifecycles[0]["absolute_deadline_ns"] != lifecycles[1]["absolute_deadline_ns"]
            or lifecycles[0]["absolute_deadline_ns"] != diagnostics["absolute_trial_deadline_ns"]
            or recovery["qualification"]["worker_pid"] != pids[1]
            or recovery["qualification"]["decode_context_sha256"] != recovery["context_sha256"]
            or recovery["qualification"]["stream_sha256"] != record["bitstream_sha256"]
        ):
            issues.append("COLD_WORKER_REUSE_DEADLINE_OR_RECOVERY_INVALID")
        if diagnostics["resource_budget"] != {
            "threads": cell["resources"]["threads"],
            "logical_cpus": trial["resource_lease"]["logical_cpus"],
            "memory_limit_bytes": cell["resources"]["memory_limit_bytes"],
            "max_concurrent_worker_processes": 1,
        }:
            issues.append("COLD_RESOURCE_BUDGET_MISMATCH")
    except KeyError, TypeError, ValueError, ArithmeticError:
        issues.append("COLD_EVIDENCE_MISSING_OR_INVALID")
    return list(dict.fromkeys(issues))


def trial_issues(trial: dict[str, Any], cell: dict[str, Any], plan: dict[str, Any]) -> list[str]:
    """Recheck the raw evidence; a saved eligibility flag is insufficient."""
    issues: list[str] = []
    record = trial.get("record") or {}
    if trial.get("schema_version") != "tscb.comparison-trial.v1":
        issues.append("TRIAL_VERSION_INVALID")
    for key in ("execution_job_id", "public_projection_key", "cell_id"):
        if trial.get(key) != cell.get(key):
            issues.append(key.upper() + "_MISMATCH")
    for key in ("protocol_id", "schedule_id", "comparison_id"):
        if trial.get(key) != plan.get(key):
            issues.append(key.upper() + "_MISMATCH")
    scheduled = {s["trial_id"]: s for s in plan.get("schedule", {}).get("trials", [])}
    slot = scheduled.get(trial.get("scheduled_trial_id", trial.get("trial_id")))
    if slot is None:
        issues.append("UNPLANNED_TRIAL")
    else:
        try:
            block_index = int(trial.get("block_id", ""))
        except ValueError, TypeError, OverflowError:
            block_index = None
        actual = {
            "trial_id": trial.get("trial_id"),
            "pair_id": trial.get("pair_id"),
            "block_index": block_index,
            "sequence_index": trial.get("sequence_index"),
            "repetition_index": trial.get("repetition_index"),
            "round_index": trial.get("round_index"),
            "execution_job_id": trial.get("execution_job_id"),
            "dataset_id": record.get("dataset_id"),
        }
        if any(slot.get(key) != value for key, value in actual.items()):
            issues.append("SCHEDULE_SLOT_MISMATCH")
    if record.get("dataset_id") != cell["dataset_id"]:
        issues.append("DATASET_MISMATCH")
    for record_key, cell_key in (
        ("algorithm_id", "algorithm_id"),
        ("config_id", "legacy_config_id"),
        ("task_id", "task_id"),
        ("execution_path_hash", "execution_path_hash"),
        ("input_sha256", "input_sha256"),
        ("track", "track"),
    ):
        if not cell.get(cell_key) or record.get(record_key) != cell[cell_key]:
            issues.append(record_key.upper() + "_MISMATCH")
    if record.get("repetition_index") != trial.get("repetition_index"):
        issues.append("REPETITION_IDENTITY_MISMATCH")
    if record.get("status") != "PASS" or record.get("record_kind") != "FORMAL_REPETITION":
        issues.append("FORMAL_EXECUTION_NOT_PASS")
    correctness = record.get("correctness") or {}
    if correctness.get("status") != "PASS":
        issues.append("CORRECTNESS_NOT_PASS")
    if cell.get("loss_mode") == "ERROR_BOUNDED_LOSSY":
        loss = correctness.get("loss") or {}
        guarantee = cell.get("guarantee") or {}
        parameters = cell.get("parameters") or {}
        try:
            actual_bound = Decimal(loss.get("error_bound", "NaN"))
            promised_bound = Decimal(guarantee.get("threshold", "NaN"))
            configured_bound = Decimal(parameters.get("error_bound", "NaN"))
            bound_matches = (
                actual_bound.is_finite()
                and actual_bound == promised_bound == configured_bound
                and actual_bound > 0
            )
        except InvalidOperation, TypeError, ValueError:
            bound_matches = False
        if (
            loss.get("schema_version") != "tscb.loss-validation.v3"
            or loss.get("error_bound_type") not in {"ABS", "ABSOLUTE"}
            or loss.get("error_bound_type") != parameters.get("error_bound_type")
            or not bound_matches
            or loss.get("bound_passed") is not True
            or loss.get("raw_violation_count") != 0
            or loss.get("quality_valid") is not True
            or loss.get("nonfinite_mismatch_count") != 0
            or guarantee.get("metric") != "MAXAE_V1"
            or guarantee.get("unit") != "ORIGINAL_VALUE_UNITS"
            or guarantee.get("original_domain_total") is not True
        ):
            issues.append("FROZEN_ORIGINAL_DOMAIN_ERROR_GUARANTEE_NOT_VERIFIED")
    ledger = record.get("accounting") or {}
    if ledger.get("canonical_raw_bits") != cell["canonical_raw_bits"]:
        issues.append("RAW_BITS_MISMATCH")
    if any(
        type(ledger.get(k)) is not int or ledger[k] < 0
        for k in ("final_bits", "serialized_bits", "external_side_information_bits")
    ):
        issues.append("ACCOUNTING_MISSING")
    elif (
        ledger["final_bits"] != ledger["serialized_bits"] + ledger["external_side_information_bits"]
    ):
        issues.append("FINAL_BITS_NOT_CLOSED")
    diagnostics = record.get("diagnostics") or {}
    recovery = diagnostics.get("independent_recovery") or {}
    qualification = recovery.get("qualification") or {}
    if (
        trial.get("qualification_status") != "PASS"
        or qualification.get("start_method") != "spawn"
        or qualification.get("original_input_available") is not False
        or qualification.get("encoder_session_available") is not False
        or qualification.get("output_owned_in_worker") is not True
    ):
        issues.append("FRESH_RECOVERY_NOT_PASS")
    if recovery.get("output_materialization") != "OWNED_CANONICAL_BUFFERS":
        issues.append("OUTPUT_NOT_MATERIALIZED")
    cold = plan["protocol"].get("profile") == "COLD_PROCESS"
    if cold:
        issues.extend(_cold_trial_issues(trial, cell, plan))
        lifecycles = [
            diagnostics.get("encode_worker_lifecycle") or {},
            diagnostics.get("decode_worker_lifecycle") or {},
        ]
    else:
        worker = diagnostics.get("worker_measurement") or {}
        lifecycle = diagnostics.get("worker_lifecycle") or {}
        lifecycles = [lifecycle]
        if not lifecycle.get("worker_exit_confirmed") or lifecycle.get("exit_code") != 0:
            issues.append("WORKER_NOT_EXITED")
        if worker.get("measurement_worker_pid") != lifecycle.get("worker_pid") or worker.get(
            "warmup_worker_pid"
        ) != lifecycle.get("worker_pid"):
            issues.append("WORKER_PID_MISMATCH")
        if lifecycle.get("start_method") != plan["protocol"]["start_method"]:
            issues.append("WORKER_START_METHOD_MISMATCH")
        warmup = worker.get("warmup") or {}
        if (
            not warmup.get("threshold_satisfied")
            or warmup.get("completed_iterations", -1) < plan["protocol"]["warmup_min_count"]
            or warmup.get("elapsed_wall_ns", -1) < plan["protocol"]["warmup_min_ns"]
        ):
            issues.append("WORKER_WARMUP_NOT_MET")
    if diagnostics.get("threshold_protocol") != plan["protocol_id"]:
        issues.append("LEGACY_THRESHOLD_EVIDENCE")
    if not trial.get("lease_held") or not trial.get("resource_lease_id"):
        issues.append("RESOURCE_LEASE_MISSING")
    if not trial.get("environment_gate", {}).get("eligible", False):
        issues.append("ENVIRONMENT_GATE_FAILED")
    if plan["protocol"].get("schema_version") == "tscb.measurement-protocol.v3.2":
        from tscompbench.measurement.resource_lease import evaluate_environment
        from tscompbench.measurement.thread_monitor import thread_budget_evidence
        from tscompbench.measurement.v32_protocol import MeasurementProtocol

        protocol = MeasurementProtocol.from_document(plan["protocol"])
        lease = trial.get("resource_lease") or {}
        gate = trial.get("environment_gate") or {}
        try:
            expected_gate = evaluate_environment(gate["after"], protocol, before=gate["before"])
            expected_lease_id = stable_id(
                "resource-lease-v32",
                {
                    k: lease[k]
                    for k in (
                        "run_set_id",
                        "owner_pid",
                        "acquired_ns",
                        "logical_cpus",
                        "threads",
                        "processes",
                        "memory_limit_bytes",
                        "numa_nodes",
                        "lock_path",
                    )
                },
            )
            resources = cell.get("resources") or lease
            if (
                not expected_gate["eligible"]
                or any(gate.get(k) != v for k, v in expected_gate.items())
                or lease.get("status") != "HELD"
                or lease.get("lease_id") != expected_lease_id
                or lease.get("lease_id") != trial.get("resource_lease_id")
                or lease["threads"] != resources["threads"]
                or lease["processes"] != resources["processes"]
                or lease["memory_limit_bytes"] != resources["memory_limit_bytes"]
                or lease["boundary"] != gate["before"]
                or gate["after"]["monotonic_ns"] < gate["before"]["monotonic_ns"]
            ):
                issues.append("RESOURCE_BOUNDARY_EVIDENCE_MISMATCH")
            for lifecycle in lifecycles:
                thread_evidence = thread_budget_evidence(
                    lifecycle.get("thread_observation"),
                    thread_budget=resources["threads"] * resources["processes"],
                )
                if thread_evidence["observed_excess"]:
                    issues.append("OBSERVED_THREAD_BUDGET_EXCEEDED")
                if protocol.thread_monitor_interval_ns is not None and (
                    thread_evidence["status"] == "UNKNOWN"
                    or lifecycle.get("thread_observation", {}).get("requested_interval_ns")
                    != protocol.thread_monitor_interval_ns
                    or lifecycle.get("thread_observation", {}).get("worker_pid")
                    != lifecycle.get("worker_pid")
                ):
                    issues.append("DECLARED_THREAD_COLLECTOR_NOT_VERIFIED")
        except ValueError, KeyError, TypeError, AttributeError:
            issues.append("RESOURCE_BOUNDARY_EVIDENCE_MISSING_OR_INVALID")
    if not plan.get("pilot_eligible"):
        issues.append("PILOT_NOT_QUALIFIED")
    if not trial.get("artifacts_verified"):
        issues.append("RECOVERY_ARTIFACTS_NOT_VERIFIED")
    timing = record.get("timing") or {}
    if plan["protocol"].get("schema_version") == "tscb.measurement-protocol.v3.2":
        contract = plan.get("contract") or {}
        native_api = contract.get("mode") == "COMMON_NATIVE_API"
        expected_scope = "CORE" if native_api else "PIPELINE"
        if (
            plan["protocol"]["timing_scope"] != expected_scope
            or timing.get("timing_scope") != expected_scope
            or (native_api and plan["protocol"]["profile"] != "STEADY_PROCESS")
        ):
            issues.append("FROZEN_TIMING_BOUNDARY_MISMATCH")
        if native_api and (
            contract.get("timing_boundary") != "CORE_API"
            or contract.get("cost_boundary") != "NATIVE_COMPONENT"
            or contract.get("workload") != "API_COMPONENT"
            or "SOURCE_REJECT_RAW" in cell.get("allowed_paths", [])
            or any(
                timing.get(f"selected_{direction}_wall_ns")
                != timing.get(f"core_{direction}_wall_ns")
                for direction in ("encode", "decode")
            )
        ):
            issues.append("COMMON_NATIVE_API_COMPONENT_BOUNDARY_NOT_VERIFIED")
        if (
            not native_api
            and not cold
            and any(
                timing.get(f"selected_{direction}_wall_ns")
                != timing.get(f"pipeline_{direction}_wall_ns")
                for direction in ("encode", "decode")
            )
        ):
            issues.append("COMPLETE_OBJECT_PIPELINE_BOUNDARY_NOT_VERIFIED")
    for direction in ("encode", "decode"):
        value = timing.get(f"selected_{direction}_wall_ns")
        if type(value) is not int or value < plan["protocol"][f"{direction}_min_ns"]:
            issues.append(direction.upper() + "_BUDGET_NOT_MET")
    if type(timing.get("inner_iterations")) is not int or timing["inner_iterations"] < 1:
        issues.append("INNER_ITERATIONS_INVALID")
    if not record.get("eligibility"):
        issues.append("EXECUTION_RESOURCE_ELIGIBILITY_FAILED")
    if trial.get("formal_eligible") is not True:
        issues.append("TRIAL_NOT_ELIGIBLE")
    return issues


def _description(values: list[float]) -> dict[str, Any]:
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "standard_deviation": statistics.stdev(values) if len(values) > 1 else None,
        "minimum": min(values),
        "maximum": max(values),
        "p95": float(np.quantile(values, 0.95)),
    }


def _effect(
    a: dict[str, float], b: dict[str, float], policy: AnalysisPolicy, family_size: int, label: str
) -> dict[str, Any]:
    blocks = sorted(set(a) & set(b))
    if len(blocks) < policy.minimum_paired_blocks:
        return {
            "status": "INCONCLUSIVE",
            "reason": "INSUFFICIENT_PAIRED_BLOCKS",
            "paired_blocks": len(blocks),
            "estimate": None,
            "confidence_interval": None,
        }
    av = np.array([a[k] for k in blocks], dtype=np.float64)
    bv = np.array([b[k] for k in blocks], dtype=np.float64)
    if (
        not np.all(np.isfinite(av))
        or not np.all(np.isfinite(bv))
        or np.any(av <= 0)
        or np.any(bv <= 0)
    ):
        raise ValueError("paired times must be positive and finite")
    # Same block indices for both methods. Inner iterations are never resampled.
    salt = int(hashlib.sha256(label.encode()).hexdigest()[:16], 16)
    rng = np.random.default_rng(policy.seed ^ salt)
    indices = rng.integers(0, len(blocks), size=(policy.bootstrap_samples, len(blocks)))
    boot = np.mean(av[indices], axis=1) / np.mean(bv[indices], axis=1)
    alpha = (1 - float(policy.confidence_level)) / max(1, family_size)
    lower, upper = (float(v) for v in np.quantile(boot, [alpha / 2, 1 - alpha / 2]))
    estimate = float(np.mean(av) / np.mean(bv))
    width = (upper - lower) / (2 * estimate)
    precision = width <= float(policy.target_relative_ci_half_width)
    threshold = float(policy.minimum_practical_effect)
    decision = "INCONCLUSIVE"
    if precision and lower > 1 + threshold:
        decision = "SECOND_MEMBER_FASTER"
    elif precision and upper < 1 / (1 + threshold):
        decision = "FIRST_MEMBER_FASTER"
    elif precision and lower >= 1 / (1 + threshold) and upper <= 1 + threshold:
        decision = "WITHIN_REGISTERED_PRACTICAL_MARGIN"
    return {
        "status": decision,
        "estimate": estimate,
        "confidence_interval": [lower, upper],
        "paired_blocks": len(blocks),
        "block_ids": blocks,
        "bootstrap_samples": policy.bootstrap_samples,
        "confidence_level": policy.confidence_level,
        "family_size": family_size,
        "interval_policy": policy.multiplicity_policy,
        "relative_ci_half_width": width,
        "precision_achieved": precision,
        "resampling_unit": policy.resampling_unit,
        "estimand": "RATIO_OF_MEAN_PROCESS_TIMES_FIRST_OVER_SECOND",
        "inference_scope": "RUN_NOISE_ON_FROZEN_CORPUS_AND_HOST",
    }


def analyze_comparison(
    plan: dict[str, Any],
    trials: list[dict[str, Any]],
    policy: AnalysisPolicy,
    *,
    raw_file_sha256: str | None = None,
    artifact_audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if plan.get("schema_version") != "tscb.comparison-execution-plan.v1":
        raise ValueError("unsupported execution plan")
    if plan.get("analysis_policy_id") != policy.id:
        raise ValueError("analysis policy differs from frozen plan")
    cells = {c["cell_id"]: c for c in plan["cells"]}
    if len(cells) != len(plan["cells"]):
        raise ValueError("duplicate frozen comparison cell")
    seen: set[str] = set()
    selected: dict[str, dict[str, Any]] = {}
    exclusions: list[dict[str, Any]] = []
    terminal_cells: set[str] = set()
    for trial in trials:
        identity = trial["trial_id"]
        if identity in seen:
            raise ValueError("duplicate TrialID")
        seen.add(identity)
        cell = cells.get(trial["cell_id"])
        if cell is None:
            raise ValueError("trial references an unplanned cell")
        terminal_cells.add(cell["cell_id"])
        issues = trial_issues(trial, cell, plan)
        if issues:
            exclusions.append(
                {
                    "trial_id": identity,
                    "cell_id": cell["cell_id"],
                    "issues": issues,
                    "status": (trial.get("record") or {}).get(
                        "status", trial.get("status", "NOT_RUN")
                    ),
                }
            )
            continue
        pair_key = cell["cell_id"] + "/" + trial["pair_id"]
        if pair_key in selected:
            raise ValueError("multiple eligible attempts for the same cell/pair")
        selected[pair_key] = trial
    by_cell: dict[str, list[dict[str, Any]]] = {key: [] for key in cells}
    for trial in selected.values():
        by_cell[trial["cell_id"]].append(trial)
    matrix: list[dict[str, Any]] = []
    pair_times: dict[str, dict[str, dict[str, tuple[str, float]]]] = {}
    expected_n = plan["planned_repetitions_per_cell"]
    for key, cell in cells.items():
        records = by_cell[key]
        completed = len(records) == expected_n
        row = {
            **cell,
            "terminal": key in terminal_cells,
            "eligible_process_count": len(records),
            "planned_process_count": expected_n,
            "formal_complete": completed,
            "status": "FORMAL_COMPLETE"
            if completed
            else "PARTIAL"
            if records
            else "NO_ELIGIBLE_FORMAL"
            if key in terminal_cells
            else "NOT_RUN",
            "run_ids": [t["record"]["run_id"] for t in records],
            "trial_ids": [t["trial_id"] for t in records],
        }
        if records:
            bits = [t["record"]["accounting"]["final_bits"] for t in records]
            row["final_bits"] = _description(bits)
            cost_metric = (
                "serialized_bits"
                if plan.get("contract", {}).get("cost_boundary") == "NATIVE_COMPONENT"
                else "final_bits"
            )
            costs = [t["record"]["accounting"][cost_metric] for t in records]
            row["comparison_cost_metric"] = cost_metric
            row["comparison_cost_bits"] = _description(costs)
            row["size_deterministic"] = len(set(costs)) == 1
            row["size_ratio"] = (
                statistics.fmean(costs) / cell["canonical_raw_bits"]
                if cell["canonical_raw_bits"]
                else None
            )
            row["inner_iterations_total"] = sum(
                t["record"]["timing"]["inner_iterations"] for t in records
            )
            row["directions"] = {}
            pair_times[key] = {}
            for direction in ("encode", "decode"):
                values = [
                    t["record"]["timing"][f"selected_{direction}_wall_ns"]
                    / t["record"]["timing"]["inner_iterations"]
                    for t in records
                ]
                row["directions"][direction] = {
                    **_description(values),
                    "unit": "ns_per_independent_object",
                    "semantic_mb_per_second": cell["canonical_raw_bits"]
                    / 8
                    * 1000
                    / statistics.fmean(values),
                }
                pair_times[key][direction] = {
                    t["pair_id"]: (str(t["block_id"]), value)
                    for t, value in zip(records, values, strict=True)
                }
        else:
            row.update(
                {
                    "final_bits": None,
                    "size_ratio": None,
                    "directions": None,
                    "missing_reason": "NO_ELIGIBLE_OBSERVATIONS",
                }
            )
        matrix.append(row)
    primary = {tuple(sorted(p)) for p in policy.primary_comparisons}
    comparisons: list[dict[str, Any]] = []
    candidates = [
        (a, b)
        for a, b in itertools.combinations(cells.values(), 2)
        if a["dataset_id"] == b["dataset_id"]
        and a["public_projection_key"] == b["public_projection_key"]
        and a["member_id"] != b["member_id"]
    ]
    family_size = max(
        1,
        sum(tuple(sorted((a["member_id"], b["member_id"]))) in primary for a, b in candidates) * 2,
    )
    for a, b in candidates:
        preregistered = tuple(sorted((a["member_id"], b["member_id"]))) in primary
        entry = {
            "first_cell_id": a["cell_id"],
            "second_cell_id": b["cell_id"],
            "dataset_id": a["dataset_id"],
            "first_member_id": a["member_id"],
            "second_member_id": b["member_id"],
            "inference_role": "PREREGISTERED" if preregistered else "EXPLORATORY",
            "fixed_raw_bits": a["canonical_raw_bits"],
            "directions": {},
        }
        for direction in ("encode", "decode"):
            first = pair_times.get(a["cell_id"], {}).get(direction, {})
            second = pair_times.get(b["cell_id"], {}).get(direction, {})
            paired_ids = sorted(set(first) & set(second))
            grouped_first: dict[str, list[float]] = {}
            grouped_second: dict[str, list[float]] = {}
            for pair_id in paired_ids:
                block, first_value = first[pair_id]
                second_block, second_value = second[pair_id]
                if block != second_block:
                    raise ValueError("paired schedule slots disagree on block identity")
                grouped_first.setdefault(block, []).append(first_value)
                grouped_second.setdefault(block, []).append(second_value)
            entry["directions"][direction] = _effect(
                {k: statistics.fmean(v) for k, v in grouped_first.items()},
                {k: statistics.fmean(v) for k, v in grouped_second.items()},
                policy,
                family_size if preregistered else 1,
                a["cell_id"] + b["cell_id"] + direction,
            )
            entry["directions"][direction]["paired_process_slots"] = len(paired_ids)
            entry["directions"][direction]["pair_ids"] = paired_ids
        comparisons.append(entry)
    core = [row for row in matrix if row["role"] == "CORE"]
    gaps = [
        {
            "cell_id": row["cell_id"],
            "status": row["status"]
            if row["expected_outcome"] == "PASS"
            else "CORE_EXPECTATION_NOT_PASS",
        }
        for row in core
        if not row["formal_complete"] or row["expected_outcome"] != "PASS"
    ]
    methods = {row.get("method_equivalence_class", row["method_id"]) for row in core}
    complete = (
        bool(core) and not gaps and len(methods) >= 2 and plan["independent_real_source_count"] >= 2
    )
    corpus_aggregates = []
    for member, config in sorted({(r["member_id"], r["config_label"]) for r in core}):
        rows = [r for r in core if (r["member_id"], r["config_label"]) == (member, config)]
        all_complete = all(r["formal_complete"] and r["expected_outcome"] == "PASS" for r in rows)
        total_bits = sum(r["canonical_raw_bits"] for r in rows)
        aggregate = {
            "member_id": member,
            "config_label": config,
            "core_cell_count": len(rows),
            "complete_cell_count": sum(r["formal_complete"] for r in rows),
            "fixed_raw_bits": total_bits,
            "status": "COMPLETE" if all_complete else "CORE_INCOMPLETE",
            "directions": None,
            "size_ratio": None,
        }
        if all_complete:
            aggregate["size_ratio"] = (
                sum(r["comparison_cost_bits"]["mean"] for r in rows) / total_bits
                if total_bits
                else None
            )
            aggregate["directions"] = {
                d: {
                    "semantic_mb_per_second": total_bits
                    / 8
                    * 1000
                    / sum(r["directions"][d]["mean"] for r in rows),
                    "time_estimator": policy.time_estimator,
                }
                for d in ("encode", "decode")
            }
        corpus_aggregates.append(aggregate)
    report = {
        "schema_version": "tscb.comparison-analysis.v1",
        "comparison_id": plan["comparison_id"],
        "analysis_policy_id": policy.id,
        "analysis_policy": policy.to_document(),
        "audited_trials_sha256": hashlib.sha256(
            b"".join(canonical_json_bytes(t) + b"\n" for t in trials)
        ).hexdigest(),
        "status": "CORE_COMPLETE" if complete else "CORE_INCOMPLETE",
        "core_gaps": gaps,
        "distinct_core_methods": len(methods),
        "independent_real_source_count": plan["independent_real_source_count"],
        "coverage": {
            "planned_cells": len(cells),
            "terminal_cells": len(terminal_cells),
            "core_expected_pass_cells": sum(r["expected_outcome"] == "PASS" for r in core),
            "core_planned_cells": len(core),
            "core_formal_complete_cells": len(core) - len(gaps),
            "planned_core_raw_bits": sum(r["canonical_raw_bits"] for r in core),
            "formal_complete_core_raw_bits": sum(
                r["canonical_raw_bits"] for r in core if r["formal_complete"]
            ),
        },
        "matrix": matrix,
        "paired_comparisons": comparisons,
        "corpus_aggregates": corpus_aggregates,
        "exclusions": exclusions,
        "conclusion_scope": "FROZEN_CORPUS_AND_HOST_ONLY",
        "legacy_records_promoted": False,
    }
    report["raw_sha256"] = raw_file_sha256 or report["audited_trials_sha256"]
    report["artifact_audit"] = artifact_audit
    report["analysis_implementation"] = {
        "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "numpy_version": np.__version__,
        "python_version": sys.version,
    }
    report["analysis_id"] = stable_id(
        "comparison-analysis",
        {
            "plan_sha256": hashlib.sha256(canonical_json_bytes(plan)).hexdigest(),
            "raw_sha256": report["raw_sha256"],
            "audited_trials_sha256": report["audited_trials_sha256"],
            "artifact_audit": artifact_audit,
            "policy_id": policy.id,
            "implementation": report["analysis_implementation"],
        },
    )
    return report
