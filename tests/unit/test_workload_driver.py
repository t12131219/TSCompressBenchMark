import copy
import inspect
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.comparison.workload_runner import (
    WorkloadProtocol,
    _observation_issues,
    _query_session_report,
    _timing_calibration_metrics,
    _timing_signal_issues,
)
from tscompbench.contracts import BenchmarkTrack, Topology, ValidityShape
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.execution.workload_driver import _stream_decode_worker, measure_workload_object
from tscompbench.measurement.workloads import build_query_workload

ROOT = Path(__file__).resolve().parents[2]


def _case(key, dtype, n=19):
    values = np.arange(n, dtype=dtype)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    routed = RoutedInput(
        "dataset:workload",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        len(values),
        1,
        values.nbytes * 8,
        hash_logical_buffers(buffers),
    )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(key)
    descriptor = DataDescriptor(
        routed.dataset_id,
        routed.track,
        Topology.UTS,
        routed.n,
        1,
        values.shape,
        (dtype,),
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
    parameters = (
        {"block_size": 4, "stream_decode_chunk_bytes": 1}
        if manifest.document["features"]["streaming"]
        else {"max_bpc": 16}
    )
    return manifest, routed, negotiate(manifest, descriptor, parameters=parameters), parameters


@pytest.mark.parametrize(
    "key", ["deflate-zlib", "lz4-frame", "zstd-frame", "brotli-stream", "xz-stream"]
)
@pytest.mark.parametrize("n", [0, 8, 19])
def test_stream_real_native_session_fresh_recovery_and_tail(key, n, monkeypatch):
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(name, "1")
    manifest, routed, compatibility, parameters = _case(key, "<f4", n=n)
    config = WorkloadProtocol("STREAM", block_rows=4).to_document()
    observed = measure_workload_object(
        ROOT,
        manifest,
        routed,
        compatibility,
        parameters,
        config,
        (),
        cpus=tuple(sorted(os.sched_getaffinity(0))),
        memory_bytes=512 * 1024**2,
        threads=len(os.sched_getaffinity(0)),
        deadline_ns=time.perf_counter_ns() + 30_000_000_000,
    )
    assert observed.status == "PASS", observed.document
    document = observed.document
    assert [b["rows"] for b in document["encode"]["blocks"]] == [
        min(4, n - offset) for offset in range(0, n, 4)
    ]
    assert not _observation_issues(document, config, len(os.sched_getaffinity(0)), True)
    assert document["recovery"]["original_input_available"] is False
    assert document["recovery"]["output_owned_in_worker"] is True
    assert len({c["worker_pid"] for c in document["lifecycles"]}) == 2
    assert (
        document["accounting"]["final_bits"] == (len(observed.stream) + len(observed.context)) * 8
    )
    assert document["encode"]["first_payload_byte_ns"] is None
    assert document["encode"]["first_consumable_sample_ns"] is None
    assert (
        not {"routed", "adapter", "original"}
        & inspect.signature(_stream_decode_worker).parameters.keys()
    )


@pytest.mark.parametrize("key", ["neats-lossless-i64", "leats-lossless-i64"])
@pytest.mark.parametrize("policy", ["REUSED_SESSION", "FRESH_SESSION_PER_QUERY"])
def test_query_real_compressed_access_owned_slice_and_cache_policy(key, policy, monkeypatch):
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        monkeypatch.setenv(name, "1")
    manifest, routed, compatibility, parameters = _case(key, "<i2")
    config = WorkloadProtocol("QUERY", query_count=10, query_cache_policy=policy).to_document()
    requests = build_query_workload(n=routed.n, m=1, seed=0, query_count=10)
    observed = measure_workload_object(
        ROOT,
        manifest,
        routed,
        compatibility,
        parameters,
        config,
        requests,
        cpus=tuple(sorted(os.sched_getaffinity(0))),
        memory_bytes=512 * 1024**2,
        threads=len(os.sched_getaffinity(0)),
        deadline_ns=time.perf_counter_ns() + 30_000_000_000,
    )
    assert observed.status == "PASS", observed.document
    assert not _observation_issues(observed.document, config, len(os.sched_getaffinity(0)), True)
    query = observed.document["query"]
    assert [s["request"] for s in query["query_samples"]] == [r.to_document() for r in requests]
    assert query["query_cache_policy"] == policy
    assert query["bytes_touched_scope"] == "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC"
    assert query["parsed_index_cache_proven"] is False
    assert len({c["worker_pid"] for c in observed.document["lifecycles"]}) == 3


def _calibration_case():
    policy = {
        "clock": "PERF_COUNTER_NS",
        "clock_tick_count": 2,
        "empty_harness_count": 2,
        "empty_harness_boundary": "EMPTY_EXTERNAL_CLOCK_DISPATCH_DRIVER",
        "min_clock_signal_ratio": 100,
        "max_harness_fraction": "0.05",
    }
    document = {
        "worker_pid": 42,
        "warmup_started_ns": 2,
        "warmup_finished_ns": 3,
        "measured_started_ns": 10000,
        "measured_finished_ns": 20000,
        "timing_calibration": {
            "schema_version": "tscb.workload-timing-calibration.v3.2",
            "worker_pid": 42,
            "started_ns": 4,
            "finished_ns": 5000,
            "clock": {
                "name": "PERF_COUNTER_NS",
                "implementation": "fixture-monotonic-clock",
                "monotonic": True,
                "adjustable": False,
                "declared_resolution_ns": 1,
                "raw_tick_timestamps_ns": [10, 20, 40],
            },
            "empty_harness_boundary": "EMPTY_EXTERNAL_CLOCK_DISPATCH_DRIVER",
            "empty_harness_samples": [
                {"index": 0, "started_ns": 100, "finished_ns": 200},
                {"index": 1, "started_ns": 300, "finished_ns": 500},
            ],
            "overhead_subtracted": False,
        },
    }
    lifecycle = {"worker_pid": 42, "parent_started_ns": 1, "parent_finished_ns": 30000}
    return document, policy, lifecycle


def test_workload_calibration_recomputes_clock_and_empty_harness_thresholds():
    document, policy, lifecycle = _calibration_case()
    metrics = _timing_calibration_metrics(document, policy, lifecycle)
    assert metrics["eligible"], metrics
    assert metrics["clock_quantum_ns"] == 10
    assert metrics["clock_signal_minimum_ns"] == 1000
    assert metrics["empty_harness_median_ns"] == "150"
    assert metrics["harness_signal_minimum_ns"] == 3000
    document["timing_calibration"]["clock"]["declared_resolution_ns"] = 40
    assert (
        _timing_calibration_metrics(document, policy, lifecycle)["clock_signal_minimum_ns"] == 4000
    )


@pytest.mark.parametrize("fault", ["missing", "pid", "nonmonotonic", "ticks", "harness", "warmup"])
def test_workload_calibration_rejects_missing_or_changed_worker_raw_proof(fault):
    document, policy, lifecycle = _calibration_case()
    calibration = document["timing_calibration"]
    if fault == "missing":
        document["timing_calibration"] = None
    elif fault == "pid":
        calibration["worker_pid"] += 1
    elif fault == "nonmonotonic":
        calibration["clock"]["monotonic"] = False
    elif fault == "ticks":
        calibration["clock"]["raw_tick_timestamps_ns"].pop()
    elif fault == "harness":
        calibration["empty_harness_samples"][1]["index"] = 0
    else:
        document["warmup_finished_ns"] = 10001
    assert not _timing_calibration_metrics(document, policy, lifecycle)["eligible"]


def test_workload_query_signal_checks_each_latency_instead_of_sequence_total():
    observed = {
        "status": "PASS",
        "kind": "QUERY",
        "query": {"query_samples": [{"wall_ns": 10}, {"wall_ns": 1_000_000}]},
    }
    thresholds = [
        {
            "member_id": "native",
            "config_label": "fixed",
            "direction": "query",
            "minimum_signal_ns": 1000,
        }
    ]
    assert "WORKLOAD_DIRECTION_OR_QUERY_BELOW_CALIBRATED_SIGNAL" in _timing_signal_issues(
        observed, thresholds, "native", "fixed"
    )
    observed["query"]["query_samples"][0]["wall_ns"] = 1000
    assert not _timing_signal_issues(observed, thresholds, "native", "fixed")


def test_query_report_amplification_and_unallocated_index_cost_are_explicit(tmp_path):
    (tmp_path / "codecs").mkdir()
    (tmp_path / "sources").mkdir()
    (tmp_path / "codecs/native.json").write_text(
        json.dumps({"identity": {"source_artifact_id": "v2:source:sha256:fixture"}})
    )
    (tmp_path / "sources/fixture.json").write_text("{}\n")
    row = {
        "trial_id": "v2:trial:sha256:fixture",
        "observation": {
            "query": {
                "query_samples": [
                    {
                        "wall_ns": 100,
                        "bytes_touched": 100,
                        "decoded_elements": 10,
                        "requested_bytes": 20,
                        "requested_elements": 10,
                    }
                ],
                "bytes_touched_scope": "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC",
                "decoded_elements_scope": (
                    "ADAPTER_REPORTED_ELEMENTS_NOT_NATIVE_INTERMEDIATE_OPERATIONS"
                ),
                "query_cache_policy": "REUSED_SESSION",
                "resource_boundary": "QUERY_SEQUENCE_INCLUDING_TIMER_EXCLUDED_SLICE_VALIDATION",
                "output_materialization": "OWNED_QUERY_BUFFERS",
            },
            "accounting": {
                "index_bits": 0,
                "checkpoint_bits": 0,
                "model_bits": 40,
                "serialized_bits": 80,
                "external_side_information_bits": 20,
                "final_bits": 100,
                "accounting_method": "EXACT_SERIALIZED_MODEL_INDEX_FRAME_V1",
            },
            "bitstream_sha256": "a" * 64,
            "context_sha256": "b" * 64,
        },
    }
    report = _query_session_report(row, {"codec_key": "native"}, tmp_path)
    assert report["read_amplification"] == "5"
    assert report["decode_amplification"] == "1"
    cost = report["index_checkpoint_cost"]
    assert cost["index_bits"] is None and cost["checkpoint_bits"] is None
    assert cost["ledger_allocated_index_bits"] == 0
    assert (
        cost["index_bits_reason"]
        == "NO_INDEPENDENT_PHYSICAL_ALLOCATION_WHOLE_SERIALIZED_FRAME_IS_CHARGED"
    )
    assert (
        sum(d["bits"] for d in report["decoder_dependencies"] if d["charged_in_final_bits"]) == 100
    )
    empty = copy.deepcopy(row)
    sample = empty["observation"]["query"]["query_samples"][0]
    sample["requested_bytes"] = sample["requested_elements"] = 0
    report = _query_session_report(empty, {"codec_key": "native"}, tmp_path)
    assert report["read_amplification"] is None
    assert report["read_amplification_reason"] == "ZERO_REQUESTED_BYTES"
    assert report["decode_amplification"] is None
    assert report["decode_amplification_reason"] == "ZERO_REQUESTED_ELEMENTS"
