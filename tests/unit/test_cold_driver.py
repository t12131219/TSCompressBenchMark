from __future__ import annotations

import copy
import inspect
import os
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import BenchmarkTrack, RunStatus, Topology, ValidityShape
from tscompbench.execution import LogicalBuffer, RoutedInput, hash_logical_buffers
from tscompbench.execution.cold_driver import (
    ColdDriverError,
    ColdPilotProbe,
    _cold_decode_worker,
    measure_cold_object,
    run_cold_pilot,
    validate_cold_pilot_evidence,
)
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement.v32_protocol import MeasurementProtocol

ROOT = Path(__file__).resolve().parents[2]


def cold_protocol(**changes):
    defaults = {
        "warmup_min_count": 0,
        "max_inner_iterations": 1,
        "cache_policy": "OS_CACHE_UNCONTROLLED",
        "cold_start_boundary": "SPAWN_THROUGH_OUTPUT_MATERIALIZATION",
        "pilot_repetitions": 3,
        "max_collector_fraction": "0.99",
    }
    defaults.update(changes)
    return MeasurementProtocol(
        "COLD_PROCESS", 3, 1_000_000, 1_000_000, 5_000_000_000, 30_000_000_000, **defaults
    )


@pytest.fixture
def cold_case(monkeypatch):
    # Imports occur before the child's function boundary, and count toward its budget.
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(key, "1")
    array = np.arange(9, dtype="<f4")
    array.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", array, array.nbytes * 8),)
    routed = RoutedInput(
        "cold-development",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        9,
        1,
        array.nbytes * 8,
        hash_logical_buffers(buffers),
    )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("oracle-lossless-adapter")
    descriptor = DataDescriptor(
        routed.dataset_id,
        routed.track,
        Topology.UTS,
        9,
        1,
        (9,),
        ("<f4",),
        "SOA_COLUMNS",
        "little",
        8,
        array.nbytes * 8,
        ValidityShape.NONE,
        False,
        True,
        False,
        False,
        False,
    )
    cpus = tuple(sorted(os.sched_getaffinity(0)))
    return ColdPilotProbe(
        ROOT,
        manifest,
        routed,
        negotiate(manifest, descriptor),
        {},
        cpus,
        256 * 1024**2,
        threads=len(cpus),
    )


def measure(case, protocol=None, **kwargs):
    return measure_cold_object(
        case.project_root,
        case.manifest,
        case.routed,
        case.compatibility,
        case.parameters,
        protocol or cold_protocol(),
        logical_cpus=case.logical_cpus,
        memory_limit_bytes=case.memory_limit_bytes,
        threads=case.threads,
        **kwargs,
    )


def test_cold_directions_rebuild_and_exit_with_paid_owned_recovery(cold_case):
    result = measure(cold_case, cold_protocol(thread_monitor_interval_ns=1_000_000))
    assert result.status is RunStatus.PASS, result.to_document()
    document = result.to_document()
    canonical_json_bytes(document)
    diagnostics = document["diagnostics"]
    encode = diagnostics["encode_worker_lifecycle"]
    decode = diagnostics["decode_worker_lifecycle"]
    assert len({os.getpid(), encode["worker_pid"], decode["worker_pid"]}) == 3
    assert encode["worker_exit_confirmed"] and decode["worker_exit_confirmed"]
    assert encode["exit_code"] == decode["exit_code"] == 0
    assert encode["absolute_deadline_ns"] == decode["absolute_deadline_ns"]
    assert encode["parent_owned_materialization_finished_ns"] <= decode["parent_started_ns"]
    for direction, lifecycle in (("encode", encode), ("decode", decode)):
        assert lifecycle["start_method"] == "spawn"
        assert lifecycle["selected_parent_wall_ns"] >= (
            lifecycle["parent_finished_ns"] - lifecycle["parent_started_ns"]
        )
        assert lifecycle["thread_observation"]["samples"]
        assert lifecycle["thread_budget_evidence"]["strict_high_water_verified"] is False
        resources = document["resources"][direction]
        assert resources["collector_enabled"] is True
        assert resources["pss_uss_scope"] == "FUNCTION_EXIT_BOUNDARY_NOT_STARTUP_HIGH_WATER"
        cumulative = resources["cumulative_fresh_child"]
        assert cumulative["payload_pickle_and_exit_cpu_included"] is False
        assert "STARTUP_IMPORT" in cumulative["scope"]
        assert Decimal(cumulative["total_seconds"]) >= Decimal(
            resources["function_boundary"]["process_total_seconds"]
        )
    timing = document["timing"]
    assert timing["inner_iterations"] == 1 and diagnostics["warmup_count"] == 0
    assert timing["startup_import_adapter_loading_included"] is True
    assert timing["os_cache_cleared"] is False
    assert timing["core_encode_wall_ns"] is None and timing["native_decode_wall_ns"] is None
    assert document["determinism_match"] is None
    assert document["resources"]["hard_rss_limit"] is False
    assert "CHILDREN_EXCLUDED" in document["resources"]["parent"]["scope"]
    recovery = diagnostics["independent_recovery"]
    qualification = recovery["qualification"]
    assert qualification["worker_pid"] == decode["worker_pid"]
    assert qualification["original_input_available"] is False
    assert qualification["encoder_session_available"] is False
    assert recovery["qualification_evidence_scope"] == "SAME_MEASURED_COLD_DECODE_WORKER"
    output = result.decoded.buffers[0].array
    assert output.dtype == np.dtype("<f4")
    assert output.tobytes() == cold_case.routed.buffers[0].array.tobytes()
    assert output.flags.owndata and output.flags.c_contiguous and not output.flags.writeable
    assert not np.shares_memory(output, cold_case.routed.buffers[0].array)
    accounting = document["accounting"]
    assert accounting["external_side_information_bits"] >= recovery["required_external_bits"] > 0
    assert accounting["final_bits"] == (
        accounting["serialized_bits"] + accounting["external_side_information_bits"]
    )
    decoder_arguments = inspect.signature(_cold_decode_worker).parameters
    assert not {
        "routed", "compatibility", "adapter", "encoder", "parameters"
    } & decoder_arguments.keys()


def test_cold_never_batches_short_object_to_reach_direction_minimum(cold_case):
    protocol = replace(cold_protocol(), encode_min_ns=1_500_000_000, decode_min_ns=1_500_000_000)
    result = measure(cold_case, protocol)
    assert result.status is RunStatus.INCOMPARABLE
    assert result.reason == "COLD_SINGLE_OBJECT_BELOW_FROZEN_DIRECTION_MINIMUM"
    assert result.timing.inner_iterations == 1
    assert result.diagnostics["warmup_count"] == 0


def test_expired_common_deadline_never_launches_encode_or_decode(cold_case):
    result = measure(cold_case, trial_deadline_ns=time.perf_counter_ns() - 1)
    assert result.status is RunStatus.TIMEOUT
    assert result.diagnostics["encode_worker_lifecycle"]["worker_launched"] is False
    assert result.diagnostics["decode_worker_lifecycle"] is None
    assert result.diagnostics["failed_direction"] == "encode"


@pytest.mark.parametrize("changes", [{"timing_scope": "CORE"}, {"max_inner_iterations": 2}])
def test_cold_driver_rejects_other_timing_and_batching(cold_case, changes):
    with pytest.raises(ColdDriverError):
        measure(cold_case, cold_protocol(**changes))


def test_formal_collector_cannot_be_overridden_and_invalid_cpu_budget_rejected(cold_case):
    with pytest.raises(ColdDriverError, match="collector override"):
        measure(cold_case, collector_enabled=False)
    with pytest.raises(ColdDriverError, match="unique"):
        measure(replace(cold_case, logical_cpus=(1, 1)))
    with pytest.raises(ColdDriverError, match="unique"):
        measure(replace(cold_case, logical_cpus=(True,)))


def _reidentify(document):
    body = {key: value for key, value in document.items() if key != "pilot_id"}
    return {**body, "pilot_id": stable_id("cold-measurement-pilot-v32", body)}


def test_real_cold_pilot_matches_collectors_and_revalidates_evidence(cold_case):
    protocol = cold_protocol(thread_monitor_interval_ns=1_000_000)
    document = run_cold_pilot(
        protocol, cold_case, development_corpus_id="dev", test_corpus_id="test"
    )
    assert document["status"] == "PASS", document
    assert len(document["raw"]) == 6
    validated = validate_cold_pilot_evidence(protocol, document)
    assert validated["eligible"], validated
    for raw in document["raw"]:
        enabled = raw["collector"] == "ENABLED"
        assert raw["inner_iterations"] == 1
        for direction in ("encode", "decode"):
            observation = raw["observation"]
            assert observation["resources"][direction]["collector_enabled"] == enabled
            monitoring = observation["diagnostics"][f"{direction}_worker_lifecycle"][
                "thread_observation"
            ]
            assert monitoring["status"] == ("OBSERVED" if enabled else "NOT_OBSERVED")
    tampered = copy.deepcopy(document)
    tampered["raw"][0]["observation"]["diagnostics"]["independent_recovery"][
        "qualification"
    ]["original_input_available"] = True
    rejected = validate_cold_pilot_evidence(protocol, _reidentify(tampered))
    assert not rejected["eligible"]
    assert "COLD_PILOT_INDEPENDENT_OWNED_RECOVERY_OR_COST_INVALID" in rejected["reasons"]
    tampered = copy.deepcopy(document)
    tampered["direction_median_ns_per_object"]["encode_ns"] = "0"
    with pytest.raises(ColdDriverError, match="admission gates"):
        validate_cold_pilot_evidence(protocol, _reidentify(tampered))


def test_cold_pilot_requires_separate_development_corpus(cold_case):
    with pytest.raises(ColdDriverError, match="separate"):
        run_cold_pilot(
            cold_protocol(), cold_case, development_corpus_id="same", test_corpus_id="same"
        )


def test_cold_alp_source_fallback_requires_explicit_recipe_and_fresh_decode(cold_case):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("alp")
    if not (ROOT / manifest.document["adapter"]["artifact_path"]).is_file():
        pytest.skip("ALP binary is unavailable")
    values = np.random.default_rng(20260920).integers(0, 2**64, 4096, dtype="<u8").view("<f8")
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    routed = RoutedInput(
        "cold-alp-source-domain",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        len(values),
        1,
        values.nbytes * 8,
        hash_logical_buffers(buffers),
    )
    descriptor = DataDescriptor(
        routed.dataset_id,
        routed.track,
        Topology.UTS,
        len(values),
        1,
        values.shape,
        ("<f8",),
        "SOA_COLUMNS",
        "little",
        8,
        values.nbytes * 8,
        ValidityShape.NONE,
        False,
        True,
        False,
        False,
        False,
    )
    case = replace(
        cold_case, manifest=manifest, routed=routed, compatibility=negotiate(manifest, descriptor)
    )
    rejected = measure(case)
    assert rejected.status is RunStatus.UNSUPPORTED
    assert rejected.diagnostics["exception_type"] == "SourceDomainError"
    assert rejected.diagnostics["decode_worker_lifecycle"] is None
    accepted = measure(case, source_reject_fallback=True)
    assert accepted.status is RunStatus.PASS, accepted.to_document()
    assert accepted.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert accepted.diagnostics["source_reject_fallback"] is True
    assert accepted.diagnostics["independent_recovery"]["qualification"][
        "original_input_available"
    ] is False
