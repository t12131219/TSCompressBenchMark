"""Independent formal stream/query profiles over a frozen comparison GroupSpec."""

from __future__ import annotations

import hashlib
import itertools
import json
import statistics
import time
from dataclasses import asdict, dataclass, fields
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from types import SimpleNamespace

from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.routing import route_canonical_artifact
from tscompbench.execution.schedule import FrozenSchedule, build_schedule
from tscompbench.execution.workload_driver import measure_workload_object
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement.resource_lease import (
    ResourceLease,
    environment_gate,
    evaluate_environment,
)
from tscompbench.measurement.thread_monitor import thread_budget_evidence
from tscompbench.measurement.v32_protocol import MeasurementProtocol
from tscompbench.measurement.workloads import QueryRequest, build_query_workload
from tscompbench.runner import _replace_json, _write_or_verify_bytes, _write_or_verify_json
from tscompbench.storage import append_event

from .analysis import _description, _effect
from .decision import comparison_decision, validate_experiment_decision
from .models import ComparisonContract, CorpusSpec
from .runner import (
    _auxiliary_input,
    _comparison_content_sha256,
    control_plane_snapshot,
    evidence_document,
    prepare_comparison,
    validate_frozen_comparison,
    validate_qualification_evidence,
)


@dataclass(frozen=True)
class WorkloadProtocol:
    kind: str
    outer_sessions: int = 4
    pilot_pairs: int = 3
    warmup_count: int = 1
    block_rows: int = 65536
    query_count: int = 1000
    query_cache_policy: str = "REUSED_SESSION"
    seed: int = 20261010
    min_direction_ns: int = 1000
    max_trial_wall_ns: int = 30_000_000_000
    max_total_wall_ns: int = 3_600_000_000_000
    max_collector_fraction: str = "0.20"
    thread_monitor_interval_ns: int = 1_000_000
    clock: str = "PERF_COUNTER_NS"

    def __post_init__(self):
        if (
            self.clock != "PERF_COUNTER_NS"
            or self.kind not in {"STREAM", "QUERY"}
            or self.query_cache_policy
            not in {
                "REUSED_SESSION",
                "FRESH_SESSION_PER_QUERY",
            }
        ):
            raise ValueError("unsupported workload/cache policy")
        for key in (
            "outer_sessions",
            "pilot_pairs",
            "block_rows",
            "query_count",
            "min_direction_ns",
            "max_trial_wall_ns",
            "max_total_wall_ns",
            "thread_monitor_interval_ns",
        ):
            if type(getattr(self, key)) is not int or not 1 <= getattr(self, key) <= 2**63 - 1:
                raise ValueError("workload protocol needs positive finite integer " + key)
        if (
            self.outer_sessions < 2
            or self.pilot_pairs < 2
            or (type(self.warmup_count) is not int or self.warmup_count < 0)
        ):
            raise ValueError("workload requires independent repeated sessions and declared warmup")
        fraction = Decimal(self.max_collector_fraction)
        if not fraction.is_finite() or not 0 < fraction < 1:
            raise ValueError("collector threshold must be a decimal fraction")
        if (
            type(self.seed) is not int
            or self.seed < 0
            or self.thread_monitor_interval_ns < 1_000_000
        ):
            raise ValueError("workload requires a nonnegative seed and monitor interval >= 1ms")

    def to_document(self):
        return {
            "schema_version": "tscb.workload-protocol.v3.2",
            **asdict(self),
            "outer_unit": "INDEPENDENT_SPAWN_SESSION",
            "thread_observation": "SAMPLED_LOWER_BOUND",
            "os_cache_policy": "UNCONTROLLED",
            "stream_domain": "KNOWN_LENGTH_FIXED_BLOCK_ROWS_FINALIZED_FULL_OUTPUT",
            "query_latency_boundary": "API_AND_OWNED_COPY_FRESH_SESSION_COST_IF_SELECTED",
            "bytes_touched_scope": "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC",
            "p99_minimum_samples_per_session": 100,
            "stop_policy": "FIXED_SESSIONS_NO_AUTOMATIC_RETRY",
        }

    @property
    def protocol_id(self):
        return stable_id("workload-protocol-v32", self.to_document())


def _timing_calibration_policy(protocol):
    return {
        "clock": protocol.clock,
        "min_clock_signal_ratio": protocol.min_clock_signal_ratio,
        "max_harness_fraction": protocol.max_harness_fraction,
        "clock_tick_count": 256,
        "empty_harness_count": 33,
        "calibration_boundary": "DEVELOPMENT_WORKER_AFTER_WARMUP_BEFORE_MEASUREMENT",
        "empty_harness_boundary": "EMPTY_EXTERNAL_CLOCK_DISPATCH_DRIVER",
        "formal_signal_policy": "EACH_STREAM_DIRECTION_AND_EACH_QUERY_LATENCY",
        "threshold_source": "CONSERVATIVE_MAXIMUM_OVER_FROZEN_PILOT_WORKERS",
        "overhead_subtracted": False,
    }


def prepare_workload_comparison(
    bundle, output, root, datasets, codecs, *, run_set_id, protocol: WorkloadProtocol, resume=False
):
    run = prepare_comparison(
        bundle,
        output,
        root,
        datasets,
        codecs,
        run_set_id=run_set_id,
        resume=resume,
        decision_workload_protocol=protocol.to_document(),
    )
    for cell in run.cells.values():
        manifest = run.manifests[cell["codec_key"]]
        if (
            "SOURCE_REJECT_RAW" in cell["allowed_paths"]
            or not manifest.document["features"][
                "streaming" if protocol.kind == "STREAM" else "query"
            ]
        ):
            raise ValueError("workload cell lacks the declared native capability")
        if (
            protocol.kind == "STREAM"
            and cell["parameters"].get("block_size") != protocol.block_rows
        ):
            raise ValueError("freeze the same stream block_rows and native block_size")
    dataset_methods = {}
    for cell in run.cells.values():
        dataset_methods.setdefault(cell["dataset_id"], {})[
            cell["member_id"] + "/" + cell["config_label"]
        ] = cell["execution_job_id"]
    schedule = build_schedule(
        run_set_id=run_set_id,
        dataset_methods=dataset_methods,
        protocol_id=protocol.protocol_id,
        seed=protocol.seed,
        blocks=protocol.outer_sessions,
    )
    requests = {}
    dimensions = {}
    if protocol.kind == "QUERY":
        for dataset_id, artifact in run.artifacts.items():
            routed = route_canonical_artifact(
                artifact, BenchmarkTrack(run.contract.to_document()["track"])
            )
            if routed.n == 0 or routed.m == 0:
                raise ValueError("query profile cannot freeze empty logical inputs")
            dimensions[dataset_id] = {"n": routed.n, "m": routed.m}
            requests[dataset_id] = [
                r.to_document()
                for r in build_query_workload(
                    n=routed.n, m=routed.m, seed=protocol.seed, query_count=protocol.query_count
                )
            ]
    body = {
        "schema_version": "tscb.workload-plan.v3.2",
        "comparison_id": run.plan["comparison_id"],
        "decision_id": run.plan["decision_id"],
        "decision": run.plan["decision"],
        "group": run.group.to_document(),
        "protocol": protocol.to_document(),
        "protocol_id": protocol.protocol_id,
        "timing_calibration_policy": _timing_calibration_policy(run.protocol),
        "schedule": schedule.to_document(),
        "requests": requests,
        "request_dimensions": dimensions,
        "query_request_generation_boundary": "FROZEN_BEFORE_WORKER_MEASUREMENT",
        "fixed_cell_count": len(run.cells),
        "cells": list(run.cells.values()),
        "control_plane_sha256": control_plane_snapshot(root)["sha256"],
    }
    body = evidence_document(body)
    body["workload_id"] = stable_id("workload-comparison-v32", body)
    _write_or_verify_json(run.path / "workload_plan.json", body)
    return run, body


def validate_workload_plan(plan, base, bundle, root):
    protocol = WorkloadProtocol(
        **{f.name: plan["protocol"][f.name] for f in fields(WorkloadProtocol)}
    )
    schedule = FrozenSchedule.from_document(plan["schedule"])
    closure = json.loads((root / "control_plane.json").read_text())
    environment = json.loads((root / "environment.json").read_text())
    decision = comparison_decision(
        bundle,
        environment_id=environment["environment_id"],
        control_plane_sha256=closure["sha256"],
        workload_protocol=protocol.to_document(),
    )
    validate_experiment_decision(root, plan, decision)
    if (
        plan["workload_id"]
        != stable_id(
            "workload-comparison-v32", {k: v for k, v in plan.items() if k != "workload_id"}
        )
        or plan["protocol"] != protocol.to_document()
        or plan["protocol_id"] != protocol.protocol_id
        or plan["timing_calibration_policy"]
        != _timing_calibration_policy(MeasurementProtocol.from_document(bundle["protocol"]))
        or plan["comparison_id"] != base["comparison_id"]
        or plan["decision_id"] != base.get("decision_id")
        or base.get("decision_workload_protocol") != protocol.to_document()
        or plan["group"] != bundle["group"]
        or plan["cells"] != base["cells"]
        or plan["fixed_cell_count"] != len(base["cells"])
        or plan["control_plane_sha256"] != closure["sha256"]
        or schedule.protocol_id != protocol.protocol_id
        or schedule.run_set_id != base["schedule"]["run_set_id"]
        or schedule.blocks != protocol.outer_sessions
        or schedule.seed != protocol.seed
        or schedule.rounds_per_block != 1
        or schedule.max_retries != 0
    ):
        raise ValueError("frozen workload plan/protocol/base/schedule identity differs")
    methods = {}
    for cell in base["cells"]:
        methods.setdefault(cell["dataset_id"], {})[
            cell["member_id"] + "/" + cell["config_label"]
        ] = cell["execution_job_id"]
    expected = build_schedule(
        run_set_id=schedule.run_set_id,
        dataset_methods=methods,
        protocol_id=protocol.protocol_id,
        seed=protocol.seed,
        blocks=protocol.outer_sessions,
    )
    if expected.to_document() != schedule.to_document():
        raise ValueError("workload paired schedule differs from fixed matrix")
    if protocol.kind == "QUERY":
        if set(plan["requests"]) != set(methods) or set(plan["request_dimensions"]) != set(methods):
            raise ValueError("query request corpus differs from frozen cells")
        for dataset, dims in plan["request_dimensions"].items():
            if dims["n"] < 1 or dims["m"] < 1:
                raise ValueError("empty query dimensions")
            wanted = evidence_document(
                [
                    r.to_document()
                    for r in build_query_workload(
                        n=dims["n"],
                        m=dims["m"],
                        seed=protocol.seed,
                        query_count=protocol.query_count,
                    )
                ]
            )
            if plan["requests"][dataset] != wanted:
                raise ValueError("frozen query requests differ from declared generation")
    elif plan["requests"] or plan["request_dimensions"]:
        raise ValueError("stream profile contains query requests")
    return protocol


def _requests(routed, config, saved=None):
    if config["kind"] != "QUERY":
        return ()
    if saved is not None:
        return tuple(
            QueryRequest(r["start"], r["length"], tuple(r["channel_indices"])) for r in saved
        )
    return build_query_workload(
        n=routed.n, m=routed.m, seed=config["seed"], query_count=config["query_count"]
    )


def _measure(
    run,
    cell,
    routed,
    task,
    plan,
    *,
    enabled,
    deadline,
    saved_requests=None,
    collect_timing_calibration=False,
):
    resources = run.contract.to_document()["resources"]
    return measure_workload_object(
        run.project_root,
        run.manifests[cell["codec_key"]],
        routed,
        task.compatibility,
        cell["parameters"],
        plan["protocol"],
        _requests(routed, plan["protocol"], saved_requests),
        cpus=run.bundle["cpu_affinity"],
        memory_bytes=resources["memory_limit_bytes"],
        threads=resources["threads"],
        deadline_ns=deadline,
        enabled=enabled,
        timing_calibration_policy=plan["timing_calibration_policy"],
        collect_timing_calibration=collect_timing_calibration,
    )


def _directions(document):
    if document.get("status") != "PASS":
        return {}
    if document["kind"] == "STREAM":
        return {
            "encode": document["encode"]["encode_wall_ns"],
            "decode": document["recovery"]["decode_wall_ns"],
        }
    return {"query": sum(s["wall_ns"] for s in document["query"]["query_samples"])}


def _timing_directions(document):
    if document.get("status") != "PASS":
        return {}
    if document["kind"] == "STREAM":
        return {"encode": document["encode"], "decode": document["recovery"]}
    return {"query": document["query"]}


def _timing_samples(document, direction):
    if direction == "query":
        return [s["wall_ns"] for s in document["query_samples"]]
    return [document[direction + "_wall_ns"]]


def _timing_calibration_metrics(document, policy, lifecycle):
    """Recompute resolution and empty dispatch costs from worker-local raw evidence."""
    reasons = []
    try:
        calibration = document["timing_calibration"]
        clock = calibration["clock"]
        ticks = clock["raw_tick_timestamps_ns"]
        harness = calibration["empty_harness_samples"]
        resolution = clock["declared_resolution_ns"]
        if (
            calibration["schema_version"] != "tscb.workload-timing-calibration.v3.2"
            or calibration["worker_pid"] != document["worker_pid"]
            or calibration["worker_pid"] != lifecycle["worker_pid"]
            or clock["name"] != policy["clock"]
            or clock["monotonic"] is not True
            or type(resolution) is not int
            or resolution < 1
            or not isinstance(clock["implementation"], str)
            or not clock["implementation"]
            or type(clock["adjustable"]) is not bool
            or len(ticks) != policy["clock_tick_count"] + 1
            or len(harness) != policy["empty_harness_count"]
            or any(type(t) is not int for t in ticks)
            or any(a > b for a, b in zip(ticks, ticks[1:], strict=False))
            or calibration["empty_harness_boundary"] != policy["empty_harness_boundary"]
            or calibration["overhead_subtracted"] is not False
            or not lifecycle["parent_started_ns"]
            <= document["warmup_started_ns"]
            <= document["warmup_finished_ns"]
            <= calibration["started_ns"]
            <= ticks[0]
            <= ticks[-1]
            <= harness[0]["started_ns"]
            <= calibration["finished_ns"]
            <= document["measured_started_ns"]
            <= document["measured_finished_ns"]
            <= lifecycle["parent_finished_ns"]
        ):
            reasons.append("PILOT_CLOCK_HARNESS_PROVENANCE_INVALID")
        elapsed = []
        previous = ticks[-1]
        for index, sample in enumerate(harness):
            if (
                sample["index"] != index
                or type(sample["started_ns"]) is not int
                or type(sample["finished_ns"]) is not int
                or not previous
                <= sample["started_ns"]
                < sample["finished_ns"]
                <= calibration["finished_ns"]
            ):
                reasons.append("PILOT_CLOCK_HARNESS_PROVENANCE_INVALID")
            elapsed.append(Decimal(sample["finished_ns"] - sample["started_ns"]))
            previous = sample["finished_ns"]
        positive = [b - a for a, b in zip(ticks, ticks[1:], strict=False) if b > a]
        if not positive or not elapsed:
            raise ValueError("clock has no positive ticks or harness samples")
        quantum = max(resolution, min(positive))
        median = statistics.median(elapsed)
        signal = quantum * policy["min_clock_signal_ratio"]
        harness_signal = int(
            (median / Decimal(policy["max_harness_fraction"])).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        return {
            "eligible": not reasons,
            "reasons": sorted(set(reasons)),
            "clock_quantum_ns": quantum,
            "empty_harness_median_ns": format(median, "f"),
            "clock_signal_minimum_ns": signal,
            "harness_signal_minimum_ns": harness_signal,
        }
    except KeyError, TypeError, ValueError, IndexError, ArithmeticError:
        return {
            "eligible": False,
            "reasons": ["PILOT_CLOCK_HARNESS_RAW_EVIDENCE_MISSING_OR_INVALID"],
        }


def _timing_signal_issues(observation, thresholds, member, label):
    reasons = []
    for direction, document in _timing_directions(observation).items():
        wanted = [
            t
            for t in thresholds
            if (t["member_id"], t["config_label"], t["direction"]) == (member, label, direction)
        ]
        if len(wanted) != 1:
            reasons.append("WORKLOAD_FROZEN_TIMING_THRESHOLD_MISSING")
        elif any(v < wanted[0]["minimum_signal_ns"] for v in _timing_samples(document, direction)):
            reasons.append("WORKLOAD_DIRECTION_OR_QUERY_BELOW_CALIBRATED_SIGNAL")
    return reasons


def pilot_workload_comparison(run, plan, datasets):
    validate_workload_plan(plan, run.plan, run.bundle, run.path)
    if control_plane_snapshot(run.project_root)["sha256"] != plan["control_plane_sha256"]:
        raise ValueError("source changed after workload freeze")
    resources = run.contract.to_document()["resources"]
    config = plan["protocol"]
    representatives = {(c["member_id"], c["config_label"]): c for c in run.cells.values()}
    raw = []
    deadline = time.perf_counter_ns() + config["max_total_wall_ns"]
    with ResourceLease(
        run_set_id=run.schedule.run_set_id + "-workload-pilot",
        logical_cpus=run.bundle["cpu_affinity"],
        threads=resources["threads"],
        memory_limit_bytes=resources["memory_limit_bytes"],
    ) as lease:
        for cell in representatives.values():
            task, artifact = _auxiliary_input(
                run, datasets, run.bundle["development_dataset"], cell
            )
            routed = route_canonical_artifact(artifact, task.track)
            for pair in range(config["pilot_pairs"]):
                modes = [False, True] if (pair + config["seed"]) % 2 else [True, False]
                for enabled in modes:
                    before = lease.to_document()
                    observed = _measure(
                        run,
                        cell,
                        routed,
                        task,
                        plan,
                        enabled=enabled,
                        deadline=min(
                            deadline, time.perf_counter_ns() + config["max_trial_wall_ns"]
                        ),
                        collect_timing_calibration=True,
                    )
                    artifact_name = stable_id(
                        "workload-pilot-artifact",
                        {
                            "workload_id": plan["workload_id"],
                            "member_id": cell["member_id"],
                            "config_label": cell["config_label"],
                            "pair": pair,
                            "enabled": enabled,
                        },
                    ).rsplit(":", 1)[-1]
                    if observed.stream is not None:
                        _write_or_verify_bytes(
                            run.path / "workload_pilot_artifacts" / (artifact_name + ".bin"),
                            observed.stream,
                        )
                        _write_or_verify_bytes(
                            run.path
                            / "workload_pilot_artifacts"
                            / (artifact_name + ".decode.json"),
                            observed.context,
                        )
                    raw.append(
                        {
                            "member_id": cell["member_id"],
                            "config_label": cell["config_label"],
                            "pair": pair,
                            "collector_enabled": enabled,
                            "artifact_name": artifact_name,
                            "environment_gate": evidence_document(
                                environment_gate(run.protocol, before, lease.to_document())
                            ),
                            "development_content_id": _comparison_content_sha256(
                                run, artifact.metadata
                            ),
                            "observation": evidence_document(observed.document),
                        }
                    )
    body = {
        "schema_version": "tscb.workload-pilot.v3.2",
        "workload_id": plan["workload_id"],
        "decision_id": plan["decision_id"],
        "decision": plan["decision"],
        "test_corpus_id": run.corpus.id,
        "raw": raw,
    }
    body["validation"] = validate_workload_pilot(run, plan, body)
    body["status"] = "PASS" if body["validation"]["eligible"] else "INCONCLUSIVE"
    body["pilot_id"] = stable_id("workload-pilot-v32", body)
    _write_or_verify_json(run.path / "workload_pilot.json", body)
    return body


def validate_workload_pilot(run, plan, pilot):
    config = plan["protocol"]
    expected = {
        (c["member_id"], c["config_label"], pair, mode)
        for c in run.cells.values()
        for pair in range(config["pilot_pairs"])
        for mode in (False, True)
    }
    raw = pilot["raw"]
    actual = [(r["member_id"], r["config_label"], r["pair"], r["collector_enabled"]) for r in raw]
    reasons = []
    if (
        pilot.get("workload_id") != plan["workload_id"]
        or pilot.get("test_corpus_id") != run.corpus.id
    ):
        reasons.append("PILOT_FROZEN_COMPARISON_MISMATCH")
    if set(actual) != expected or len(actual) != len(expected):
        reasons.append("PILOT_FIXED_MEMBER_PAIR_COVERAGE_MISMATCH")
    test_content = {c["logical_content_id"] for c in run.cells.values()}
    if any(r["development_content_id"] in test_content for r in raw):
        reasons.append("PILOT_DEVELOPMENT_OVERLAPS_TEST")
    fractions, calibration_metrics, threshold_map = [], [], {}
    for row in raw:
        reasons.extend(_environment_issues(row, run.protocol))
        directions = _directions(row["observation"])
        if not directions or min(directions.values()) < config["min_direction_ns"]:
            reasons.append("PILOT_DIRECTION_SIGNAL_OR_RECOVERY_FAILED")
        reasons.extend(
            _observation_issues(
                row["observation"],
                config,
                run.contract.to_document()["resources"]["threads"],
                row["collector_enabled"],
            )
        )
        for direction, document in _timing_directions(row["observation"]).items():
            call_index = {"encode": 0, "decode": 1, "query": 2}[direction]
            try:
                metrics = _timing_calibration_metrics(
                    document,
                    plan["timing_calibration_policy"],
                    row["observation"]["lifecycles"][call_index],
                )
            except KeyError, TypeError, IndexError:
                metrics = {
                    "eligible": False,
                    "reasons": ["PILOT_CLOCK_HARNESS_RAW_EVIDENCE_MISSING_OR_INVALID"],
                }
            reasons.extend(metrics["reasons"])
            record = {
                "member_id": row["member_id"],
                "config_label": row["config_label"],
                "pair": row["pair"],
                "collector_enabled": row["collector_enabled"],
                "direction": direction,
                **metrics,
            }
            calibration_metrics.append(record)
            if not metrics["eligible"]:
                continue
            samples = _timing_samples(document, direction)
            if not samples or any(type(v) is not int or v <= 0 for v in samples):
                reasons.append("PILOT_DIRECTION_SIGNAL_OR_RECOVERY_FAILED")
                continue
            minimum = min(samples)
            record["minimum_observed_signal_ns"] = minimum
            record["minimum_clock_signal_ratio"] = format(
                Decimal(minimum) / Decimal(metrics["clock_quantum_ns"]), "f"
            )
            record["empty_harness_fraction_of_minimum_signal"] = format(
                Decimal(metrics["empty_harness_median_ns"]) / Decimal(minimum), "f"
            )
            if minimum < metrics["clock_signal_minimum_ns"]:
                reasons.append("PILOT_DIRECTION_OR_QUERY_BELOW_CLOCK_SIGNAL")
            if minimum < metrics["harness_signal_minimum_ns"]:
                reasons.append("PILOT_EMPTY_HARNESS_FRACTION_EXCEEDS_FROZEN_THRESHOLD")
            key = (row["member_id"], row["config_label"], direction)
            threshold_map[key] = max(
                threshold_map.get(key, config["min_direction_ns"]),
                metrics["clock_signal_minimum_ns"],
                metrics["harness_signal_minimum_ns"],
            )
        try:
            stream = (
                run.path / "workload_pilot_artifacts" / (row["artifact_name"] + ".bin")
            ).read_bytes()
            context = (
                run.path / "workload_pilot_artifacts" / (row["artifact_name"] + ".decode.json")
            ).read_bytes()
            if (
                hashlib.sha256(stream).hexdigest() != row["observation"]["bitstream_sha256"]
                or hashlib.sha256(context).hexdigest() != row["observation"]["context_sha256"]
            ):
                reasons.append("PILOT_SAVED_RECOVERY_DEPENDENCY_CHANGED")
        except OSError, KeyError:
            reasons.append("PILOT_SAVED_RECOVERY_DEPENDENCY_MISSING")
    for member, label in sorted({(c["member_id"], c["config_label"]) for c in run.cells.values()}):
        disabled = [
            _directions(r["observation"])
            for r in raw
            if r["member_id"] == member
            and r["config_label"] == label
            and not r["collector_enabled"]
        ]
        enabled = [
            _directions(r["observation"])
            for r in raw
            if r["member_id"] == member and r["config_label"] == label and r["collector_enabled"]
        ]
        if disabled and enabled and all(disabled + enabled):
            for direction in disabled[0]:
                baseline = statistics.median(r[direction] for r in disabled)
                observed = statistics.median(r[direction] for r in enabled)
                fraction = abs(Decimal(observed) - Decimal(baseline)) / Decimal(baseline)
                fractions.append(
                    {"member_id": member, "direction": direction, "fraction": format(fraction, "f")}
                )
                if fraction > Decimal(config["max_collector_fraction"]):
                    reasons.append("PILOT_COLLECTOR_DISTURBANCE_EXCEEDS_FROZEN_THRESHOLD")
    thresholds = [
        {
            "member_id": member,
            "config_label": label,
            "direction": direction,
            "minimum_signal_ns": value,
        }
        for (member, label, direction), value in sorted(threshold_map.items())
    ]
    for row in raw:
        reasons.extend(
            _timing_signal_issues(
                row["observation"], thresholds, row["member_id"], row["config_label"]
            )
        )
    return {
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "collector_fractions": fractions,
        "timing_calibration_metrics": calibration_metrics,
        "timing_thresholds": thresholds,
        "overhead_subtracted": False,
    }


def _read_raw(path):
    if not path.exists():
        return []
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise ValueError("interrupted workload raw append")
    rows = [json.loads(line) for line in payload.splitlines()]
    if len({r["trial_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate workload trial identity")
    return rows


def _environment_issues(row, protocol):
    try:
        gate = row["environment_gate"]
        wanted = evaluate_environment(gate["after"], protocol, before=gate["before"])
        if not wanted["eligible"] or any(gate.get(k) != v for k, v in wanted.items()):
            return ["WORKLOAD_ENVIRONMENT_GATE_INVALID"]
    except KeyError, TypeError, ValueError:
        return ["WORKLOAD_ENVIRONMENT_EVIDENCE_MISSING"]
    return []


def _observation_issues(observation, config, threads, enabled):
    reasons = []
    if observation.get("status") != "PASS":
        return ["WORKLOAD_OBSERVATION_NOT_PASS"]
    try:
        calls = observation["lifecycles"]
        wanted = 2 if config["kind"] == "STREAM" else 3
        recovery = observation["recovery"]
        context = canonical_json_bytes(observation["context_document"])
        ledger = observation["accounting"]
        if (
            observation["kind"] != config["kind"]
            or observation["collector_enabled"] != enabled
            or len(calls) != wanted
            or len({c["worker_pid"] for c in calls}) != wanted
            or observation["correctness"]["status"] != "PASS"
            or observation["encode"]["input_immutable"] is not True
            or recovery["original_input_available"] is not False
            or recovery["encoder_session_available"] is not False
            or recovery["output_owned_in_worker"] is not True
            or recovery["worker_pid"] != calls[1]["worker_pid"]
            or hashlib.sha256(context).hexdigest() != observation["context_sha256"]
            or ledger["external_side_information_bits"] != len(context) * 8
            or ledger["final_bits"] != ledger["serialized_bits"] + len(context) * 8
            or recovery["decode_context_sha256"] != observation["context_sha256"]
            or recovery["stream_sha256"] != observation["bitstream_sha256"]
            or observation["encode"]["warmup_count"] != config["warmup_count"]
        ):
            reasons.append("WORKLOAD_CONTEXT_COST_CORRECTNESS_OR_WARMUP_INVALID")
        prior_end = observation["started_ns"]
        for call in calls:
            monitoring = call["thread_observation"]
            if (
                call["start_method"] != "spawn"
                or not call["worker_exit_confirmed"]
                or call["exit_code"] != 0
                or not prior_end
                <= call["parent_started_ns"]
                <= call["parent_finished_ns"]
                <= observation["finished_ns"]
                or call["absolute_deadline_ns"] != calls[0]["absolute_deadline_ns"]
                or (
                    enabled
                    and (
                        monitoring["worker_pid"] != call["worker_pid"]
                        or monitoring["requested_interval_ns"]
                        != config["thread_monitor_interval_ns"]
                        or monitoring["status"] != "OBSERVED"
                        or not monitoring["samples"]
                    )
                )
                or thread_budget_evidence(monitoring, thread_budget=threads)["observed_excess"]
            ):
                reasons.append("WORKLOAD_FRESH_LIFECYCLE_COLLECTOR_OR_THREADS_INVALID")
            prior_end = call["parent_finished_ns"]
        measured = [observation["encode"]]
        measured.append(
            observation["recovery"] if config["kind"] == "STREAM" else observation["query"]
        )
        for direction in measured:
            resources = direction["resources"]
            if (
                resources["actual_scope"] != ("PROCESS" if enabled else "PROCESS_CPU_ONLY")
                or resources["scope_availability"] != ("AVAILABLE" if enabled else "NOT_COLLECTED")
                or resources["swap_observed"] is True
                or any(
                    v is not None and v > threads
                    for v in (resources["thread_count_before"], resources["thread_count_after"])
                )
            ):
                reasons.append("WORKLOAD_PROCESS_RESOURCE_COLLECTOR_INVALID")
            call_index = 0 if direction is observation["encode"] else wanted - 1
            call = calls[call_index]
            if (
                direction["worker_pid"] != call["worker_pid"]
                or not call["parent_started_ns"]
                <= direction["warmup_started_ns"]
                <= direction["warmup_finished_ns"]
                <= direction["measured_started_ns"]
                <= direction["measured_finished_ns"]
                <= call["parent_finished_ns"]
            ):
                reasons.append("WORKLOAD_MEASUREMENT_WARMUP_OR_WORKER_BOUNDARY_INVALID")
        if config["kind"] == "STREAM":
            stream = observation["encode"]
            rows = observation["context_document"]["buffers"][0]["shape"][0]
            blocks = stream["blocks"]
            if (
                stream["block_rows"] != config["block_rows"]
                or stream["known_total_rows"] != rows
                or [(b["offset"], b["rows"]) for b in blocks]
                != [
                    (offset, min(config["block_rows"], rows - offset))
                    for offset in range(0, rows, config["block_rows"])
                ]
                or stream["first_consumable_sample_ns"] is not None
                or stream["first_payload_byte_ns"] is not None
                or stream["online_consumption_status"] != "FINALIZED_FULL_OBJECT_ONLY"
                or recovery["warmup_count"] != config["warmup_count"]
            ):
                reasons.append("STREAM_KNOWN_LENGTH_BLOCK_OR_OUTPUT_BOUNDARY_INVALID")
        else:
            query = observation["query"]
            wanted_warmup = (
                config["warmup_count"] if config["query_cache_policy"] == "REUSED_SESSION" else 0
            )
            if (
                query["query_cache_policy"] != config["query_cache_policy"]
                or query["warmup_count"] != wanted_warmup
                or query["parsed_index_cache_proven"] is not False
                or query["bytes_touched_scope"] != "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC"
                or query["output_materialization"] != "OWNED_QUERY_BUFFERS"
                or any(
                    type(s["wall_ns"]) is not int
                    or s["wall_ns"] <= 0
                    or s["wall_ns"] != s["finished_ns"] - s["started_ns"]
                    or not query["measured_started_ns"]
                    <= s["started_ns"]
                    < s["finished_ns"]
                    <= query["measured_finished_ns"]
                    or any(
                        type(s[k]) is not int or s[k] < 0
                        for k in (
                            "decoded_elements",
                            "bytes_touched",
                            "requested_bytes",
                            "requested_elements",
                        )
                    )
                    or s["requested_elements"]
                    != s["request"]["length"] * len(s["request"]["channel_indices"])
                    for s in query["query_samples"]
                )
                or not query["query_samples"]
                or query["decoded_elements_scope"]
                != "ADAPTER_REPORTED_ELEMENTS_NOT_NATIVE_INTERMEDIATE_OPERATIONS"
                or query["resource_boundary"]
                != "QUERY_SEQUENCE_INCLUDING_TIMER_EXCLUDED_SLICE_VALIDATION"
            ):
                reasons.append("QUERY_CACHE_MATERIALIZATION_OR_LATENCY_INVALID")
            import numpy as np

            value_buffers = [
                b
                for b in observation["context_document"]["buffers"]
                if b["name"].startswith("value/")
            ]
            for sample in query["query_samples"]:
                request = sample["request"]
                expected_bytes = sum(
                    np.dtype(value_buffers[i]["dtype"]).itemsize * request["length"]
                    for i in request["channel_indices"]
                )
                if expected_bytes != sample["requested_bytes"]:
                    reasons.append("QUERY_REQUESTED_BYTES_DIFFER_FROM_ORIGINAL_SCHEMA")
    except KeyError, TypeError, ValueError, IndexError:
        reasons.append("WORKLOAD_OBSERVATION_EVIDENCE_MISSING")
    return sorted(set(reasons))


def execute_workload_comparison(run, plan, pilot):
    import fcntl
    import os

    validate_workload_plan(plan, run.plan, run.bundle, run.path)
    validate_qualification_evidence(run, json.loads((run.path / "qualification.json").read_text()))
    validation = validate_workload_pilot(run, plan, pilot)
    body = {k: v for k, v in pilot.items() if k != "pilot_id"}
    if (
        not validation["eligible"]
        or pilot.get("validation") != validation
        or pilot["pilot_id"] != (stable_id("workload-pilot-v32", body))
    ):
        raise ValueError("workload pilot is not qualified from retained raw evidence")
    if control_plane_snapshot(run.project_root)["sha256"] != plan["control_plane_sha256"]:
        raise ValueError("source changed after workload freeze")
    descriptor = os.open(run.path / ".workload.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        raw_path = run.path / "workload_trials.jsonl"
        existing = _read_raw(raw_path)
        completed = {r["trial_id"] for r in existing}
        schedule = FrozenSchedule.from_document(plan["schedule"])
        cells = {c["execution_job_id"]: c for c in plan["cells"]}
        event_path = run.path / "workload_events.jsonl"
        events = (
            [json.loads(line) for line in event_path.read_text().splitlines()]
            if event_path.exists()
            else []
        )
        attempted = {
            e["payload"]["trial_id"] for e in events if e["event_type"] == "WORKLOAD_STARTED"
        }
        unresolved = attempted - completed
        config = plan["protocol"]
        budget_path = run.path / "workload_budget.json"
        prior = json.loads(budget_path.read_text())["used_ns"] if budget_path.exists() else 0
        started_run = time.perf_counter_ns()
        resources = run.contract.to_document()["resources"]
        stopped = {r["cell_id"] for r in existing if r["observation"]["status"] != "PASS"}
        with ResourceLease(
            run_set_id=run.schedule.run_set_id + "-workload",
            logical_cpus=run.bundle["cpu_affinity"],
            threads=resources["threads"],
            memory_limit_bytes=resources["memory_limit_bytes"],
        ) as lease:
            for slot in schedule.trials:
                if slot.trial_id in completed:
                    continue
                cell = cells[slot.job_id]
                used = prior + time.perf_counter_ns() - started_run
                if used >= config["max_total_wall_ns"]:
                    break
                before = lease.to_document()
                deadline = time.perf_counter_ns() + min(
                    config["max_trial_wall_ns"], config["max_total_wall_ns"] - used
                )
                _replace_json(
                    budget_path,
                    {
                        "used_ns": min(
                            config["max_total_wall_ns"], used + config["max_trial_wall_ns"]
                        ),
                        "status": "CONSERVATIVE_PENDING_ATTEMPT",
                    },
                )
                append_event(event_path, "WORKLOAD_STARTED", {"trial_id": slot.trial_id})
                if unresolved or cell["cell_id"] in stopped:
                    document = {"status": "STOPPED", "reason": "NO_AUTOMATIC_RETRY_AFTER_FAILURE"}
                    observed = None
                else:
                    task = run.tasks[cell["cell_id"]]
                    routed = route_canonical_artifact(run.artifacts[cell["dataset_id"]], task.track)
                    observed = _measure(
                        run,
                        cell,
                        routed,
                        task,
                        plan,
                        enabled=True,
                        deadline=deadline,
                        saved_requests=plan["requests"].get(cell["dataset_id"]),
                    )
                    document = observed.document
                gate = environment_gate(run.protocol, before, lease.to_document())
                row = {
                    **slot.to_document(),
                    "schema_version": "tscb.workload-trial.v3.2",
                    "cell_id": cell["cell_id"],
                    "workload_id": plan["workload_id"],
                    "resource_lease": before,
                    "environment_gate": evidence_document(gate),
                    "observation": evidence_document(document),
                }
                if observed is not None and observed.stream is not None:
                    name = slot.trial_id.rsplit(":", 1)[-1]
                    _write_or_verify_bytes(
                        run.path / "workload_artifacts" / (name + ".bin"), observed.stream
                    )
                    _write_or_verify_bytes(
                        run.path / "workload_artifacts" / (name + ".decode.json"), observed.context
                    )
                if document["status"] != "PASS":
                    stopped.add(cell["cell_id"])
                with raw_path.open("ab") as handle:
                    handle.write(canonical_json_bytes(row) + b"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                _replace_json(
                    budget_path,
                    {
                        "used_ns": prior + time.perf_counter_ns() - started_run,
                        "status": "ACTUAL_ACTIVE_EXECUTOR_WALL",
                    },
                )
        return report_workload_comparison(run.path)
    finally:
        os.close(descriptor)


def _audit(row, cell, plan, root, timing_thresholds):
    reasons = _observation_issues(
        row["observation"], plan["protocol"], cell["resources"]["threads"], True
    )
    observation = row["observation"]
    if observation.get("status") != "PASS":
        return ["WORKLOAD_NOT_PASS"]
    reasons.extend(
        _timing_signal_issues(
            observation, timing_thresholds, cell["member_id"], cell["config_label"]
        )
    )
    try:
        reasons.extend(
            _environment_issues(
                row,
                MeasurementProtocol.from_document(
                    json.loads((root / "bundle.json").read_text())["protocol"]
                ),
            )
        )
        lease = row["resource_lease"]
        lease_id = stable_id(
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
        if (
            lease["lease_id"] != lease_id
            or lease["run_set_id"] != plan["schedule"]["run_set_id"] + "-workload"
            or any(
                lease[k] != cell["resources"][k]
                for k in ("threads", "processes", "memory_limit_bytes")
            )
            or lease["boundary"] != row["environment_gate"]["before"]
        ):
            reasons.append("WORKLOAD_RESOURCE_LEASE_INVALID")
        name = row["trial_id"].rsplit(":", 1)[-1]
        stream = (root / "workload_artifacts" / (name + ".bin")).read_bytes()
        context = (root / "workload_artifacts" / (name + ".decode.json")).read_bytes()
        ledger = observation["accounting"]
        recovery = observation["recovery"]
        if (
            hashlib.sha256(stream).hexdigest() != observation["bitstream_sha256"]
            or hashlib.sha256(context).hexdigest() != observation["context_sha256"]
            or json.loads(context) != observation["context_document"]
            or ledger["serialized_bits"] != len(stream) * 8
            or ledger["external_side_information_bits"] != len(context) * 8
            or ledger["final_bits"] != (len(stream) + len(context)) * 8
            or ledger["canonical_raw_bits"] != cell["canonical_raw_bits"]
            or recovery["original_input_available"] is not False
            or recovery["encoder_session_available"] is not False
            or recovery["output_owned_in_worker"] is not True
            or recovery["decode_context_sha256"] != observation["context_sha256"]
            or recovery["stream_sha256"] != observation["bitstream_sha256"]
            or observation["correctness"]["status"] != "PASS"
            or observation["collector_enabled"] is not True
            or not row["environment_gate"]["eligible"]
            or row["resource_lease"]["status"] != "HELD"
        ):
            reasons.append("SAVED_COST_RECOVERY_OR_ENVIRONMENT_INVALID")
        calls = observation["lifecycles"]
        wanted = 2 if plan["protocol"]["kind"] == "STREAM" else 3
        if len(calls) != wanted or len({c["worker_pid"] for c in calls}) != wanted:
            reasons.append("INDEPENDENT_WORKER_COUNT_INVALID")
        for call in calls:
            monitoring = call["thread_observation"]
            if (
                call["start_method"] != "spawn"
                or not call["worker_exit_confirmed"]
                or call["exit_code"] != 0
                or monitoring["worker_pid"] != call["worker_pid"]
                or monitoring["requested_interval_ns"]
                != plan["protocol"]["thread_monitor_interval_ns"]
                or thread_budget_evidence(monitoring, thread_budget=cell["resources"]["threads"])[
                    "observed_excess"
                ]
            ):
                reasons.append("WORKER_LIFECYCLE_OR_THREAD_BUDGET_INVALID")
        if recovery["worker_pid"] != calls[1]["worker_pid"]:
            reasons.append("RECOVERY_WORKER_MISMATCH")
        if observation["kind"] == "QUERY":
            query = observation["query"]
            if (
                [s["request"] for s in query["query_samples"]]
                != plan["requests"][cell["dataset_id"]]
                or query["query_cache_policy"] != plan["protocol"]["query_cache_policy"]
                or query["bytes_touched_scope"] != "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC"
                or query["output_materialization"] != "OWNED_QUERY_BUFFERS"
                or {k: observation["context_document"][k] for k in ("n", "m")}
                != plan["request_dimensions"][cell["dataset_id"]]
            ):
                reasons.append("QUERY_REQUEST_OR_CACHE_OR_MATERIALIZATION_INVALID")
        if min(_directions(observation).values()) < plan["protocol"]["min_direction_ns"]:
            reasons.append("WORKLOAD_DIRECTION_BELOW_FROZEN_MINIMUM")
    except OSError, KeyError, TypeError, ValueError:
        reasons.append("WORKLOAD_EVIDENCE_MISSING_OR_INVALID")
    return reasons


def _query_session_report(row, cell, root):
    query = row["observation"]["query"]
    samples = query["query_samples"]
    latency = sorted(s["wall_ns"] for s in samples)
    totals = {
        key: sum(s[key] for s in samples)
        for key in ("bytes_touched", "decoded_elements", "requested_bytes", "requested_elements")
    }
    ledger = row["observation"]["accounting"]
    name = row["trial_id"].rsplit(":", 1)[-1]
    manifest_path = Path("codecs") / (cell["codec_key"] + ".json")
    manifest = json.loads((root / manifest_path).read_text())
    source_path = Path("sources") / (
        manifest["identity"]["source_artifact_id"].rsplit(":", 1)[-1] + ".json"
    )
    cost = {}
    for field in ("index_bits", "checkpoint_bits"):
        allocated = ledger[field]
        cost[field] = allocated if allocated > 0 else None
        cost[field + "_availability"] = (
            "AVAILABLE" if allocated > 0 else "NOT_SEPARATELY_IDENTIFIED"
        )
        cost[field + "_reason"] = (
            "EXACT_LEDGER_PHYSICAL_COMPONENT"
            if allocated > 0
            else "NO_INDEPENDENT_PHYSICAL_ALLOCATION_WHOLE_SERIALIZED_FRAME_IS_CHARGED"
        )
        cost["ledger_allocated_" + field] = allocated
    dependencies = [
        {
            "role": "COMPLETE_SERIALIZED_MODEL_INDEX_FRAME",
            "path": str(Path("workload_artifacts") / (name + ".bin")),
            "sha256": row["observation"]["bitstream_sha256"],
            "bits": ledger["serialized_bits"],
            "charged_in_final_bits": True,
        },
        {
            "role": "DECODE_CONTEXT",
            "path": str(Path("workload_artifacts") / (name + ".decode.json")),
            "sha256": row["observation"]["context_sha256"],
            "bits": ledger["external_side_information_bits"],
            "charged_in_final_bits": True,
        },
    ]
    for role, path in (
        ("DECODER_MANIFEST", manifest_path),
        ("DECODER_SOURCE_ARTIFACT", source_path),
    ):
        dependencies.append(
            {
                "role": role,
                "path": str(path),
                "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest(),
                "bits": None,
                "charged_in_final_bits": False,
                "cost_policy": "REGISTERED_EXECUTABLE_SOFTWARE_DEPENDENCY_OUTSIDE_DATA_OBJECT_BITS",
            }
        )
    return {
        "trial_id": row["trial_id"],
        "query_count": len(samples),
        "p50_ns": latency[int((len(latency) - 1) * 0.5)],
        "p95_ns": latency[int((len(latency) - 1) * 0.95)],
        "p99_ns": latency[int((len(latency) - 1) * 0.99)] if len(latency) >= 100 else None,
        "p99_availability": "AVAILABLE" if len(latency) >= 100 else "INSUFFICIENT_SAMPLES",
        **totals,
        "read_amplification": format(
            Decimal(totals["bytes_touched"]) / Decimal(totals["requested_bytes"]), ".17g"
        )
        if totals["requested_bytes"]
        else None,
        "read_amplification_availability": "AVAILABLE"
        if totals["requested_bytes"]
        else "UNDEFINED",
        "read_amplification_reason": "LOGICAL_FRAME_ESTIMATE"
        if totals["requested_bytes"]
        else "ZERO_REQUESTED_BYTES",
        "decode_amplification": format(
            Decimal(totals["decoded_elements"]) / Decimal(totals["requested_elements"]), ".17g"
        )
        if totals["requested_elements"]
        else None,
        "decode_amplification_availability": "AVAILABLE"
        if totals["requested_elements"]
        else "UNDEFINED",
        "decode_amplification_reason": "ADAPTER_REPORTED_DECODED_ELEMENTS"
        if totals["requested_elements"]
        else "ZERO_REQUESTED_ELEMENTS",
        "bytes_touched_scope": query["bytes_touched_scope"],
        "decoded_elements_scope": query["decoded_elements_scope"],
        "query_cache_policy": query["query_cache_policy"],
        "resource_boundary": query["resource_boundary"],
        "output_materialization": query["output_materialization"],
        "index_checkpoint_cost": {
            **cost,
            "accounting_method": ledger["accounting_method"],
            "model_bits": ledger["model_bits"],
            "serialized_bits": ledger["serialized_bits"],
            "external_side_information_bits": ledger["external_side_information_bits"],
            "final_bits": ledger["final_bits"],
            "independent_index_object_claimed": False,
        },
        "decoder_dependencies": dependencies,
    }


def report_workload_comparison(root: Path):
    run_plan = json.loads((root / "execution_plan.json").read_text())
    bundle = json.loads((root / "bundle.json").read_text())
    validate_frozen_comparison(root, bundle, run_plan)
    plan = json.loads((root / "workload_plan.json").read_text())
    validate_workload_plan(plan, run_plan, bundle, root)
    frozen_run = SimpleNamespace(
        path=root,
        plan=run_plan,
        bundle=bundle,
        cells={c["cell_id"]: c for c in run_plan["cells"]},
        contract=ComparisonContract.from_document(bundle["contract"]),
        corpus=CorpusSpec.from_document(bundle["corpus"]),
        protocol=MeasurementProtocol.from_document(bundle["protocol"]),
    )
    validate_qualification_evidence(
        frozen_run, json.loads((root / "qualification.json").read_text())
    )
    pilot = json.loads((root / "workload_pilot.json").read_text())
    pilot_validation = validate_workload_pilot(frozen_run, plan, pilot)
    if (
        not pilot_validation["eligible"]
        or pilot["validation"] != pilot_validation
        or pilot["pilot_id"]
        != stable_id("workload-pilot-v32", {k: v for k, v in pilot.items() if k != "pilot_id"})
    ):
        raise ValueError("retained workload pilot is not qualified")
    raw_path = root / "workload_trials.jsonl"
    rows = _read_raw(raw_path)
    cells = {c["cell_id"]: c for c in plan["cells"]}
    schedule = {s["trial_id"]: s for s in plan["schedule"]["trials"]}
    selected, exclusions = {}, []
    for row in rows:
        if row["trial_id"] not in schedule or row["cell_id"] not in cells:
            raise ValueError("unplanned workload trial")
        slot = schedule[row["trial_id"]]
        issues = _audit(
            row, cells[row["cell_id"]], plan, root, pilot_validation["timing_thresholds"]
        )
        if (
            any(row.get(k) != v for k, v in slot.items())
            or row["workload_id"] != plan["workload_id"]
        ):
            issues.append("WORKLOAD_SCHEDULE_MISMATCH")
        if issues:
            exclusions.append({"trial_id": row["trial_id"], "reasons": issues})
        else:
            selected.setdefault(row["cell_id"], []).append(row)
    matrix, times = [], {}
    for cell in plan["cells"]:
        observations = selected.get(cell["cell_id"], [])
        directions = {}
        for direction in (
            ("encode", "decode") if plan["protocol"]["kind"] == "STREAM" else ("query",)
        ):
            values = [_directions(r["observation"])[direction] for r in observations]
            directions[direction] = _description(values) if values else None
            times[cell["cell_id"], direction] = {
                str(r["block_index"]): value for r, value in zip(observations, values, strict=True)
            }
        query_sessions = []
        if plan["protocol"]["kind"] == "QUERY":
            for row in observations:
                query_sessions.append(_query_session_report(row, cell, root))
        matrix.append(
            {
                **cell,
                "eligible_sessions": len(observations),
                "complete": len(observations) == plan["protocol"]["outer_sessions"],
                "directions": directions,
                "query_sessions": query_sessions,
                "final_bits": _description(
                    [r["observation"]["accounting"]["final_bits"] for r in observations]
                )
                if observations
                else None,
            }
        )
    from .analysis import AnalysisPolicy

    policy = AnalysisPolicy.from_document(bundle["analysis_policy"])
    pairs = []
    family_size = sum(
        1
        for a, b in itertools.combinations(plan["cells"], 2)
        if a["dataset_id"] == b["dataset_id"] and a["member_id"] != b["member_id"]
    )
    family_size *= 2 if plan["protocol"]["kind"] == "STREAM" else 1
    for first, second in itertools.combinations(plan["cells"], 2):
        if first["dataset_id"] != second["dataset_id"] or first["member_id"] == second["member_id"]:
            continue
        for direction in (
            ("encode", "decode") if plan["protocol"]["kind"] == "STREAM" else ("query",)
        ):
            pairs.append(
                {
                    "first": first["cell_id"],
                    "second": second["cell_id"],
                    "direction": direction,
                    "unit": "INDEPENDENT_SESSION_BLOCK",
                    **_effect(
                        times[first["cell_id"], direction],
                        times[second["cell_id"], direction],
                        policy,
                        max(1, family_size),
                        first["cell_id"] + second["cell_id"] + direction,
                    ),
                }
            )
    method_count = len({c["method_equivalence_class"] for c in plan["cells"]})
    complete = all(c["complete"] for c in matrix)
    body = {
        "schema_version": "tscb.workload-analysis.v3.2",
        "workload_id": plan["workload_id"],
        "decision_id": plan["decision_id"],
        "decision": plan["decision"],
        "status": "PROFILE_COMPLETE" if complete else "PROFILE_INCOMPLETE",
        "coverage": {
            "planned_cells": len(matrix),
            "complete_cells": sum(c["complete"] for c in matrix),
        },
        "distinct_methods": method_count,
        "independent_real_source_count": run_plan["independent_real_source_count"],
        "multiple_comparison_family_size": family_size,
        "core_storage_ratio_final_over_raw": format(
            Decimal(
                sum(
                    statistics.median(
                        r["observation"]["accounting"]["final_bits"]
                        for r in selected[cell["cell_id"]]
                    )
                    for cell in plan["cells"]
                )
            )
            / Decimal(sum(c["canonical_raw_bits"] for c in plan["cells"])),
            "f",
        )
        if complete
        else None,
        "inference_scope": "METHOD_COMPARISON"
        if method_count >= 2
        else "IMPLEMENTATION_VARIANT_STUDY",
        "matrix": matrix,
        "paired_comparisons": pairs,
        "exclusions": exclusions,
        "raw_sha256": hashlib.sha256(
            raw_path.read_bytes() if raw_path.exists() else b""
        ).hexdigest(),
        "uncertainty_resampling_unit": "INDEPENDENT_SESSION_SCHEDULE_BLOCK",
        "first_emitted_byte_is_first_sample": False,
        "timing_calibration_policy": plan["timing_calibration_policy"],
        "timing_thresholds": pilot_validation["timing_thresholds"],
        "timing_overhead_subtracted": False,
    }
    body = evidence_document(body)
    body["analysis_id"] = stable_id("workload-analysis-v32", body)
    _replace_json(root / "workload_analysis.json", body)
    import html

    page = '<!doctype html><meta charset="utf-8"><title>Declared workload profile</title>'
    page += "<h1>" + html.escape(plan["protocol"]["kind"]) + " " + body["status"] + "</h1>"
    page += (
        "<p>" + html.escape(body["inference_scope"]) + ". Fixed cells: " + str(len(matrix)) + "</p>"
    )
    page += (
        "<p>Query bytes touched are logical frame estimates; first emitted bytes may be headers. "
    )
    page += "Uncertainty uses independent sessions; no cache clearing is claimed.</p>"
    page += "<pre>" + html.escape(json.dumps(body, indent=2)) + "</pre>"
    page += '<a href="workload_trials.jsonl">Immutable raw</a> '
    page += '<a href="workload_plan.json">Frozen protocol and requests</a>'
    page += ' <a href="experiment_decision.json">Pre-measurement decision contract</a>'
    page += ' <a href="uncompressed_reference.json">Independent size reference (not FORMAL)</a>'
    page += ' <a href="uncompressed_reference.md">Reference boundaries</a>'
    (root / "workload_report.html").write_text(page)
    return {
        k: body[k]
        for k in ("status", "analysis_id", "coverage", "distinct_methods", "inference_scope")
    }
