from __future__ import annotations

import copy
import os
import time
from dataclasses import replace

import pytest

from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement.v32_protocol import (
    MeasurementProtocol,
    MeasurementProtocolError,
    decimal_observations,
    run_pilot,
)


def protocol(**kwargs):
    return MeasurementProtocol(
        "STEADY_PROCESS",
        3,
        2_000_000,
        2_000_000,
        1_000_000_000,
        5_000_000_000,
        pilot_repetitions=3,
        **kwargs,
    )


def workload():
    started = time.perf_counter_ns()
    time.sleep(0.001)
    middle = time.perf_counter_ns()
    time.sleep(0.001)
    finished = time.perf_counter_ns()
    return {"encode_ns": middle - started, "decode_ns": finished - middle}


def collector_workload():
    return workload()


def disturbed_collector():
    started = time.perf_counter_ns()
    time.sleep(0.006)
    middle = time.perf_counter_ns()
    time.sleep(0.006)
    return {"encode_ns": middle - started, "decode_ns": time.perf_counter_ns() - middle}


def empty_harness():
    return None


_probe_calls = 0


def hangs_after_completed_probe():
    global _probe_calls
    _probe_calls += 1
    if _probe_calls >= 3:
        time.sleep(5)
    return workload()


def pilot(p, callback=workload, collector=collector_workload):
    return run_pilot(
        p,
        callback,
        development_corpus_id="development-source",
        test_corpus_id="frozen-test-source",
        harness_probe=empty_harness,
        collector_enabled_probe=collector,
    )


def test_protocol_identity_is_frozen_and_float_free():
    p = protocol()
    assert MeasurementProtocol.from_document(p.to_document()) == p
    assert canonical_json_bytes(p.to_document())
    assert replace(p, decode_min_ns=3_000_000).protocol_id != p.protocol_id
    for change in ({"protocol_id": "forged"}, {"hidden_threshold": 0}):
        forged = p.to_document() | change
        with pytest.raises(MeasurementProtocolError):
            MeasurementProtocol.from_document(forged)
    assert decimal_observations({"ratio": 0.1, "nested": [0.2]}) == {
        "ratio": "0.1",
        "nested": ["0.2"],
    }
    for value in (float("nan"), float("inf")):
        with pytest.raises(MeasurementProtocolError):
            decimal_observations({"bad": value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("encode_min_ns", 0),
        ("decode_min_ns", float("inf")),
        ("outer_repetitions", True),
        ("max_trial_wall_ns", 4_000_000),
        ("max_total_wall_ns", 1),
        ("warmup_min_count", 1_000_001),
        ("max_retries", 11),
        ("confidence_level", 0.95),
        ("max_noise_cv", "NaN"),
        ("max_collector_fraction", "1"),
        ("max_throttle_ratio", "1.1"),
        ("require_environment_observations", 1),
        ("start_method", "fork"),
        ("worker_initial_state", "FORK_SNAPSHOT"),
    ],
)
def test_degenerate_budgets_and_implicit_state_are_rejected(field, value):
    with pytest.raises(MeasurementProtocolError):
        replace(protocol(), **{field: value})


def test_cold_profile_requires_real_startup_boundary_without_warmup():
    p = replace(
        protocol(),
        profile="COLD_PROCESS",
        warmup_min_count=0,
        cold_start_boundary="SPAWN_THROUGH_OUTPUT_MATERIALIZATION",
        cache_policy="OS_CACHE_UNCONTROLLED",
    )
    assert p.profile == "COLD_PROCESS"
    with pytest.raises(MeasurementProtocolError):
        replace(p, warmup_min_count=1)
    with pytest.raises(MeasurementProtocolError):
        replace(p, cold_start_boundary=None)


def test_precision_only_uses_frozen_outer_looks_and_adjusted_confidence():
    p = replace(
        protocol(),
        stop_mode="PRECISION_PREDECLARED",
        min_outer_repetitions=2,
        precision_checkpoints=(2, 3),
        precision_relative_halfwidth="0.05",
        sequential_method="BONFERRONI_LOOKS",
        max_noise_cv="0.1",
    )
    evidence = {
        "method": "BONFERRONI_LOOKS",
        "confidence_level": "0.975",
        "sample_unit": "OUTER_PROCESS_OR_SCHEDULE_BLOCK",
        "sample_count": 2,
        "relative_halfwidth": "0.02",
    }
    assert (
        p.stop_decision(
            completed_outer=2,
            elapsed_ns=100,
            precision_evidence=evidence,
            noise_cv="0.01",
        )["reason"]
        == "PRECISION_REACHED"
    )
    assert (
        p.stop_decision(
            completed_outer=2,
            elapsed_ns=p.max_total_wall_ns,
            precision_evidence=evidence,
            noise_cv="0.01",
        )["reason"]
        == "INCONCLUSIVE"
    )
    assert (
        p.stop_decision(
            completed_outer=2,
            elapsed_ns=100,
            precision_evidence=evidence,
            noise_cv="0.2",
        )["reason"]
        == "CONTINUE"
    )
    for altered in (
        evidence | {"confidence_level": "0.95"},
        evidence | {"sample_unit": "INNER_ITERATION"},
        evidence | {"relative_halfwidth": "NaN"},
        evidence | {"relative_halfwidth": 0.02},
    ):
        with pytest.raises(MeasurementProtocolError):
            p.stop_decision(completed_outer=2, elapsed_ns=100, precision_evidence=altered)
    with pytest.raises(MeasurementProtocolError):
        p.stop_decision(completed_outer=1, elapsed_ns=100, precision_evidence=evidence)
    with pytest.raises(MeasurementProtocolError):
        replace(p, precision_checkpoints=([],))
    with pytest.raises(MeasurementProtocolError):
        p.stop_decision(completed_outer=2, elapsed_ns=100, noise_cv="NaN")


def test_real_spawned_pilot_retains_same_worker_conditioning_and_raw_probes():
    result = pilot(protocol(max_collector_fraction="0.8"))
    assert result["status"] == "PASS", result["reasons"]
    assert result["lifecycle"]["start_method"] == "spawn"
    assert result["lifecycle"]["worker_pid"] != os.getpid()
    assert result["lifecycle"]["worker_exit_confirmed"]
    assert len(result["raw"]) == 6
    assert {r["worker_pid"] for r in result["raw"]} == {result["warmup"]["worker_pid"]}
    assert result["warmup"]["finished_ns"] <= min(r["started_ns"] for r in result["raw"])
    assert result["recommended_inner_iterations"] >= 1
    assert result["overhead_subtracted"] is False
    assert canonical_json_bytes(result)


def test_pilot_rejects_real_collector_disturbance_and_unfunded_calibration():
    result = pilot(protocol(), collector=disturbed_collector)
    assert "COLLECTOR_DISTURBANCE_EXCEEDS_REGISTERED_THRESHOLD" in result["reasons"]
    low_iterations = replace(
        protocol(collector_mode="DISABLED"),
        max_inner_iterations=1,
        encode_min_ns=100_000_000,
        decode_min_ns=100_000_000,
    )
    result = pilot(low_iterations, collector=None)
    assert "CALIBRATION_EXCEEDS_INNER_ITERATION_BUDGET" in result["reasons"]


def test_hanging_callback_is_bounded_and_completed_probe_survives():
    p = replace(protocol(collector_mode="DISABLED"), max_trial_wall_ns=200_000_000)
    started = time.monotonic()
    result = pilot(p, callback=hangs_after_completed_probe, collector=None)
    assert time.monotonic() - started < 3
    assert result["status"] == "INCONCLUSIVE"
    assert "PILOT_CALLBACK_WALL_BUDGET_EXHAUSTED" in result["reasons"]
    assert len(result["raw"]) == 1
    assert result["lifecycle"]["worker_exit_confirmed"]
    assert canonical_json_bytes(result)


def test_pilot_does_not_use_test_corpus_or_omit_enabled_collector_probe():
    with pytest.raises(MeasurementProtocolError):
        run_pilot(
            protocol(),
            workload,
            development_corpus_id="same",
            test_corpus_id="same",
            harness_probe=empty_harness,
            collector_enabled_probe=collector_workload,
        )
    with pytest.raises(MeasurementProtocolError):
        pilot(protocol(), collector=None)
    bad = copy.deepcopy(protocol().to_document())
    bad["profile"] = {"bad": True}
    with pytest.raises(MeasurementProtocolError):
        MeasurementProtocol.from_document(bad)


def test_recomputed_pilot_rejects_changed_gates_and_worker_evidence():
    from tscompbench.ids import stable_id
    from tscompbench.measurement.v32_protocol import validate_pilot_evidence

    p = protocol(max_collector_fraction="0.8", thread_monitor_interval_ns=1_000_000)
    result = pilot(p)
    assert result["status"] == "PASS", result["reasons"]
    assert validate_pilot_evidence(p, result)["eligible"]
    assert result["parent_thread_monitor"]["classification"] == "INSTRUMENTED_SAMPLED_LOWER_BOUND"
    assert all(
        "COLLECTOR_ENABLED" in sample["phase"]
        for sample in result["parent_thread_monitor"]["samples"]
    )
    for mutate in (
        lambda d: d["lifecycle"].update(worker_exit_confirmed=False),
        lambda d: d["warmup"].update(count=0),
        lambda d: d["parent_thread_monitor"].update(requested_interval_ns=2_000_000),
    ):
        forged = copy.deepcopy(result)
        mutate(forged)
        forged.pop("pilot_id")
        forged["pilot_id"] = stable_id("measurement-pilot-v32", forged)
        try:
            validation = validate_pilot_evidence(p, forged)
        except MeasurementProtocolError:
            continue
        assert not validation["eligible"]
    forged = copy.deepcopy(result)
    forged["noise_cv"]["encode_ns"] = "0"
    forged.pop("pilot_id")
    forged["pilot_id"] = stable_id("measurement-pilot-v32", forged)
    with pytest.raises(MeasurementProtocolError):
        validate_pilot_evidence(p, forged)


def aggregate_base_probe():
    first, second = workload(), workload()
    return {key: first[key] + second[key] for key in first} | {"inner_iterations": 2}


def aggregate_slow_collector_probe():
    started = time.perf_counter_ns()
    time.sleep(0.002)
    middle = time.perf_counter_ns()
    time.sleep(0.002)
    return {
        "encode_ns": middle - started,
        "decode_ns": time.perf_counter_ns() - middle,
        "inner_iterations": 1,
    }


def test_pilot_normalizes_calibrated_totals_so_equal_budgets_cannot_hide_slowdown():
    from tscompbench.measurement.v32_protocol import validate_pilot_evidence

    p = protocol(max_collector_fraction="0.3")
    result = pilot(p, callback=aggregate_base_probe, collector=aggregate_slow_collector_probe)
    assert result["status"] == "INCONCLUSIVE"
    assert "COLLECTOR_DISTURBANCE_EXCEEDS_REGISTERED_THRESHOLD" in result["reasons"]
    assert result["recommended_inner_iterations"] >= 2
    assert not validate_pilot_evidence(p, result)["eligible"]
