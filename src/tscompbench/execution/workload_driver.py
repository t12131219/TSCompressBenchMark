"""Declared streaming and compressed-query workers with independent recovery."""

from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.adapters import create_adapter
from tscompbench.codecs import CodecManifest
from tscompbench.contracts import RunStatus
from tscompbench.measurement import ResourceSampler
from tscompbench.measurement.workloads import QueryResult, StreamPushResult
from tscompbench.validation import validate_common_correctness

from .isolation import run_isolated
from .preparation import prepare_execution_input
from .protocol import EncodedArtifact, LogicalBuffer, RoutedInput
from .recovery import (
    DecodeContext,
    bind_decode_context,
    decode_in_fresh_worker,
    restore_decoded_output,
)
from .repetition import _encode
from .routing import hash_logical_buffers, hash_reference_array


@dataclass(frozen=True)
class WorkloadObservation:
    status: str
    stream: bytes | None
    context: bytes | None
    document: dict[str, Any]


def _sampler(enabled: bool, raw_bytes: int) -> ResourceSampler:
    return ResourceSampler(
        requested_scope="PROCESS",
        memory_accounting_scope="PROCESS_RSS",
        counter_method="NOT_COLLECTED",
        energy_method="NOT_COLLECTED",
        allocated_logical_cpus=1,
        canonical_bytes=raw_bytes,
        enabled=enabled,
    )


def _adapter(root: Path, manifest: dict, key: str):
    return create_adapter(
        root, CodecManifest(key, manifest, "WORKLOAD_DEPENDENCY"), source_reject_fallback=False
    )


def _chunk(routed: RoutedInput, start: int, stop: int) -> RoutedInput:
    buffers = tuple(
        LogicalBuffer(b.name, b.array[start:stop], b.array[start:stop].nbytes * 8)
        for b in routed.buffers
    )
    timestamp = (
        None if routed.timestamp_reference is None else routed.timestamp_reference[start:stop]
    )
    return replace(
        routed,
        buffers=buffers,
        n=stop - start,
        canonical_raw_bits=sum(b.logical_bits for b in buffers),
        input_sha256=hash_logical_buffers(buffers),
        timestamp_reference=timestamp,
        validity_reference=None
        if routed.validity_reference is None
        else routed.validity_reference[start:stop],
        pairing_reference_sha256=hash_reference_array(timestamp),
    )


def _empty_timing_dispatch():
    """The empty external clock/dispatch boundary; codec work is never subtracted."""


def _timing_calibration(config):
    if not config.get("collect_timing_calibration", False):
        return None
    policy = config["timing_calibration_policy"]
    if policy["clock"] != "PERF_COUNTER_NS":
        raise ValueError("workload calibration requires the frozen monotonic clock")
    started = time.perf_counter_ns()
    info = time.get_clock_info("perf_counter")
    ticks = [time.perf_counter_ns() for _ in range(policy["clock_tick_count"] + 1)]
    harness = []
    for index in range(policy["empty_harness_count"]):
        before = time.perf_counter_ns()
        _empty_timing_dispatch()
        after = time.perf_counter_ns()
        harness.append({"index": index, "started_ns": before, "finished_ns": after})
    return {
        "schema_version": "tscb.workload-timing-calibration.v3.2",
        "worker_pid": os.getpid(),
        "started_ns": started,
        "finished_ns": time.perf_counter_ns(),
        "clock": {
            "name": policy["clock"],
            "implementation": info.implementation,
            "monotonic": info.monotonic,
            "adjustable": info.adjustable,
            "declared_resolution_ns": math.ceil(info.resolution * 1e9),
            "raw_tick_timestamps_ns": ticks,
        },
        "empty_harness_boundary": "EMPTY_EXTERNAL_CLOCK_DISPATCH_DRIVER",
        "empty_harness_samples": harness,
        "overhead_subtracted": False,
    }


def _stream_encode(adapter, original, compatibility, parameters, block_rows):
    started = time.perf_counter_ns()
    prepared = prepare_execution_input(original, compatibility)
    routed = prepared.codec_input
    if parameters.get("block_size") != block_rows:
        raise ValueError("stream block rows must equal the frozen native session block_size")
    before = hash_logical_buffers(original.buffers)
    session = adapter.create_stream_session(parameters)
    parts, pushes = [], []
    first_emitted = None
    state_peak = buffer_peak = checkpoints = 0
    try:
        session.stream_start(routed)
        for offset in range(0, routed.n, block_rows):
            chunk = _chunk(routed, offset, min(routed.n, offset + block_rows))
            call_start = time.perf_counter_ns()
            result = session.stream_push(chunk)
            finished = time.perf_counter_ns()
            if not isinstance(result, StreamPushResult):
                raise TypeError("stream_push must return StreamPushResult")
            parts.append(result.emitted)
            pushes.append(
                {
                    "offset": offset,
                    "rows": chunk.n,
                    "wall_ns": finished - call_start,
                    "emitted_bytes": len(result.emitted),
                }
            )
            if result.emitted and first_emitted is None:
                first_emitted = finished - started
            state_peak = max(state_peak, result.state_bytes)
            buffer_peak = max(buffer_peak, result.buffer_bytes)
            checkpoints += result.checkpoint_bits
        finalize_started = time.perf_counter_ns()
        tail = session.stream_finalize()
        finalize_ns = time.perf_counter_ns() - finalize_started
        if not isinstance(tail, bytes):
            raise TypeError("stream_finalize must return bytes")
        parts.append(tail)
        if tail and first_emitted is None:
            first_emitted = time.perf_counter_ns() - started
        limits = session.stream_limits()
        state_peak = max(state_peak, limits["state_bytes"])
        buffer_peak = max(buffer_peak, limits["buffer_bytes"])
        stream = b"".join(parts)
        ledger = session.stream_accounting(stream, routed)
        if ledger.checkpoint_bits != checkpoints:
            raise ValueError("stream checkpoint bits differ from the serialized ledger")
    finally:
        session.close()
    context = DecodeContext.from_routed(
        original, compatibility, adapter_id=adapter.adapter_id, parameters=parameters
    )
    artifact = bind_decode_context(
        EncodedArtifact(
            stream,
            len(stream) - len(tail),
            len(tail),
            len(stream),
            hashlib.sha256(stream).hexdigest(),
            ledger,
        ),
        context,
    )
    finished = time.perf_counter_ns()
    return artifact, {
        "encode_wall_ns": finished - started,
        "measured_started_ns": started,
        "measured_finished_ns": finished,
        "input_immutable": before
        == original.input_sha256
        == hash_logical_buffers(original.buffers),
        "blocks": pushes,
        "block_rows": block_rows,
        "known_total_rows": original.n,
        "finalize_wall_ns": finalize_ns,
        "first_emitted_byte_ns": first_emitted,
        "first_emitted_byte_semantics": "MAY_BE_CONTAINER_OR_CODEC_HEADER",
        "first_payload_byte_ns": None,
        "first_consumable_sample_ns": None,
        "online_consumption_status": "FINALIZED_FULL_OBJECT_ONLY",
        "lookahead_rows": 0,
        "state_peak_bytes": state_peak,
        "host_buffer_peak_bytes": buffer_peak,
        "host_input_residency": "COMPLETE_CANONICAL_OBJECT",
        "backpressure_policy": "CALLER_PACED_SYNCHRONOUS_PUSH",
        "unknown_length_supported": False,
        "forward_transform_container_and_context_cost_included": True,
    }


def _encode_worker(root, manifest, key, routed, compatibility, parameters, config, enabled):
    adapter = _adapter(root, manifest, key)
    # Every formal encoding worker performs its own declared warmup with fresh contexts.
    warmup_started = time.perf_counter_ns()
    for _ in range(config["warmup_count"]):
        if config["kind"] == "STREAM":
            _stream_encode(adapter, routed, compatibility, parameters, config["block_rows"])
        else:
            prepared = prepare_execution_input(routed, compatibility)
            _encode(adapter, prepared.codec_input, parameters)
    warmup_finished = time.perf_counter_ns()
    calibration = _timing_calibration(config)
    sampler = _sampler(enabled, (routed.canonical_raw_bits + 7) // 8)
    sampler.start(time.perf_counter_ns())
    if config["kind"] == "STREAM":
        artifact, metrics = _stream_encode(
            adapter, routed, compatibility, parameters, config["block_rows"]
        )
    else:
        started = time.perf_counter_ns()
        prepared = prepare_execution_input(routed, compatibility)
        artifact, _, _, immutable, canary = _encode(adapter, prepared.codec_input, parameters)
        context = DecodeContext.from_routed(
            routed, compatibility, adapter_id=adapter.adapter_id, parameters=parameters
        )
        artifact = bind_decode_context(artifact, context)
        finished = time.perf_counter_ns()
        metrics = {
            "encode_wall_ns": finished - started,
            "measured_started_ns": started,
            "measured_finished_ns": finished,
            "input_immutable": immutable,
            "canary_intact": canary,
        }
    return artifact, {
        **metrics,
        "resources": sampler.stop(time.perf_counter_ns()).to_document(),
        "worker_pid": os.getpid(),
        "warmup_count": config["warmup_count"],
        "warmup_started_ns": warmup_started,
        "warmup_finished_ns": warmup_finished,
        "timing_calibration": calibration,
    }


def _stream_decode_worker(root, manifest, key, context_bytes, stream, stream_sha, config, enabled):
    """No routed input, original arrays or encoder object are accepted here."""
    if hashlib.sha256(stream).hexdigest() != stream_sha:
        raise ValueError("stream checksum mismatch")
    context = DecodeContext(context_bytes)
    adapter = _adapter(root, manifest, key)
    if adapter.adapter_id != context.to_document()["adapter_id"]:
        raise ValueError("stream decoder differs from declared dependency")
    parameters = context.to_document()["parameters"]
    warmup_started = time.perf_counter_ns()
    for _ in range(config["warmup_count"]):
        warmup_session = adapter.create_stream_session(parameters)
        try:
            restore_decoded_output(warmup_session.stream_decompress(stream), context)
        finally:
            warmup_session.close()
    warmup_finished = time.perf_counter_ns()
    calibration = _timing_calibration(config)
    sampler = _sampler(enabled, (context.to_document()["canonical_raw_bits"] + 7) // 8)
    sampler.start(time.perf_counter_ns())
    started = time.perf_counter_ns()
    session = adapter.create_stream_session(parameters)
    try:
        decoded = restore_decoded_output(session.stream_decompress(stream), context)
    finally:
        session.close()
    finished = time.perf_counter_ns()
    elapsed = finished - started
    return decoded, {
        "decode_wall_ns": elapsed,
        "measured_started_ns": started,
        "measured_finished_ns": finished,
        "worker_pid": os.getpid(),
        "start_method": "spawn",
        "original_input_available": False,
        "encoder_session_available": False,
        "output_owned_in_worker": all(b.array.flags.owndata for b in decoded.buffers),
        "decode_context_sha256": context.sha256,
        "stream_sha256": stream_sha,
        "resources": sampler.stop(time.perf_counter_ns()).to_document(),
        "warmup_count": config["warmup_count"],
        "warmup_started_ns": warmup_started,
        "warmup_finished_ns": warmup_finished,
        "timing_calibration": calibration,
    }


def _query_worker(root, manifest, key, context_bytes, stream, routed, requests, config, enabled):
    if not requests:
        raise ValueError("query profile requires nonempty frozen requests")
    context = DecodeContext(context_bytes)
    adapter = _adapter(root, manifest, key)
    if adapter.adapter_id != context.to_document()["adapter_id"]:
        raise ValueError("query decoder identity mismatch")
    parameters = context.to_document()["parameters"]
    buffers = tuple(b for b in routed.buffers if b.name.startswith("value/"))
    session = None
    warmup_started = time.perf_counter_ns()
    if config["query_cache_policy"] == "REUSED_SESSION":
        session = adapter.create_session(parameters)
        for _ in range(config["warmup_count"]):
            session.query(stream, requests[0])
    warmup_finished = time.perf_counter_ns()
    calibration = _timing_calibration(config)
    sampler = _sampler(enabled, (routed.canonical_raw_bits + 7) // 8)
    sampler.start(time.perf_counter_ns())
    samples = []
    measured_started = time.perf_counter_ns()
    try:
        for request in requests:
            started = time.perf_counter_ns()
            fresh = config["query_cache_policy"] == "FRESH_SESSION_PER_QUERY"
            current = adapter.create_session(parameters) if fresh else session
            try:
                result = current.query(stream, request)
                if not isinstance(result, QueryResult):
                    raise TypeError("query must return QueryResult")
                owned = tuple(
                    LogicalBuffer(b.name, np.array(b.array, copy=True, order="C"), b.logical_bits)
                    for b in result.buffers
                )
                if (
                    type(result.decoded_elements) is not int
                    or result.decoded_elements < 0
                    or type(result.bytes_touched) is not int
                    or result.bytes_touched < 0
                ):
                    raise ValueError("query accounting requires nonnegative integer counts")
            finally:
                if fresh:
                    current.close()
            finished = time.perf_counter_ns()
            elapsed = finished - started
            expected = tuple(buffers[i] for i in request.channel_indices)
            if len(owned) != len(expected):
                raise ValueError("query projection width differs")
            requested_bytes = 0
            for actual, original in zip(owned, expected, strict=True):
                wanted = original.array[request.start : request.start + request.length]
                if (
                    actual.name != original.name
                    or actual.array.dtype != wanted.dtype
                    or (
                        actual.array.shape != wanted.shape
                        or actual.array.tobytes() != wanted.tobytes()
                    )
                ):
                    raise ValueError("query result differs from exact original slice")
                requested_bytes += wanted.nbytes
            samples.append(
                {
                    "request": request.to_document(),
                    "wall_ns": elapsed,
                    "started_ns": started,
                    "finished_ns": finished,
                    "decoded_elements": result.decoded_elements,
                    "bytes_touched": result.bytes_touched,
                    "requested_bytes": requested_bytes,
                    "requested_elements": request.length * len(expected),
                }
            )
    finally:
        if session is not None:
            session.close()
    measured_finished = time.perf_counter_ns()
    return {
        "query_samples": samples,
        "query_cache_policy": config["query_cache_policy"],
        "parse_index_checksum_cost_policy": "INCLUDED_IN_EACH_QUERY_API_AS_IMPLEMENTED",
        "parsed_index_cache_proven": False,
        "os_cache_policy": "UNCONTROLLED",
        "bytes_touched_scope": "LOGICAL_FRAME_ESTIMATE_NOT_HARDWARE_TRAFFIC",
        "decoded_elements_scope": "ADAPTER_REPORTED_ELEMENTS_NOT_NATIVE_INTERMEDIATE_OPERATIONS",
        "output_materialization": "OWNED_QUERY_BUFFERS",
        "validation_boundary": "AFTER_EACH_QUERY_TIMER",
        "resources": sampler.stop(time.perf_counter_ns()).to_document(),
        "worker_pid": os.getpid(),
        "warmup_started_ns": warmup_started,
        "warmup_finished_ns": warmup_finished,
        "warmup_count": config["warmup_count"] if session is not None else 0,
        "measured_started_ns": measured_started,
        "measured_finished_ns": measured_finished,
        "resource_boundary": "QUERY_SEQUENCE_INCLUDING_TIMER_EXCLUDED_SLICE_VALIDATION",
        "timing_calibration": calibration,
    }


def measure_workload_object(
    root,
    manifest,
    routed,
    compatibility,
    parameters,
    config,
    requests,
    *,
    cpus,
    memory_bytes,
    threads,
    deadline_ns,
    enabled=True,
    timing_calibration_policy=None,
    collect_timing_calibration=False,
):
    config = {
        **config,
        "timing_calibration_policy": timing_calibration_policy,
        "collect_timing_calibration": collect_timing_calibration,
    }
    calls = []

    def invoke(function, *args):
        call = run_isolated(
            function,
            *args,
            timeout_seconds=config["max_trial_wall_ns"] / 1e9,
            memory_limit_bytes=memory_bytes,
            cpu_affinity=tuple(cpus),
            start_method="spawn",
            deadline_ns=deadline_ns,
            thread_monitor_interval_ns=config["thread_monitor_interval_ns"] if enabled else None,
        )
        calls.append(call.lifecycle_document())
        if call.status is not RunStatus.PASS:
            raise RuntimeError(f"{call.status.value}: {call.exception_type}: {call.message}")
        return call.value

    started = time.perf_counter_ns()
    try:
        artifact, encode = invoke(
            _encode_worker,
            root,
            manifest.document,
            manifest.key,
            routed,
            compatibility,
            parameters,
            config,
            enabled,
        )
        if config["kind"] == "STREAM":
            decoded, recovery = invoke(
                _stream_decode_worker,
                root,
                manifest.document,
                manifest.key,
                artifact.recovery_context,
                artifact.stream,
                artifact.stream_sha256,
                config,
                enabled,
            )
            query = None
        else:
            decoded, recovery = invoke(
                decode_in_fresh_worker,
                root,
                manifest.document,
                manifest.key,
                artifact.recovery_context,
                artifact.stream,
                artifact.stream_sha256,
                False,
            )
            query = invoke(
                _query_worker,
                root,
                manifest.document,
                manifest.key,
                artifact.recovery_context,
                artifact.stream,
                routed,
                requests,
                config,
                enabled,
            )
        correctness = validate_common_correctness(
            routed,
            decoded,
            compatibility,
            loss_mode=compatibility.effective_loss_mode,
            parameters=parameters,
            deterministic_match=None,
            input_immutable=encode["input_immutable"],
            canary_intact=encode.get("canary_intact", True),
            decoded_is_restored=True,
        )
        from tscompbench.measurement.thread_monitor import thread_budget_evidence

        excess = any(
            thread_budget_evidence(c["thread_observation"], thread_budget=threads)[
                "observed_excess"
            ]
            for c in calls
        )
        status = (
            "PASS"
            if correctness.status is RunStatus.PASS and not excess
            else ("OVERSUBSCRIBED" if excess else correctness.status.value)
        )
        return WorkloadObservation(
            status,
            artifact.stream,
            artifact.recovery_context,
            {
                "schema_version": "tscb.workload-observation.v3.2",
                "status": status,
                "kind": config["kind"],
                "collector_enabled": enabled,
                "started_ns": started,
                "finished_ns": time.perf_counter_ns(),
                "lifecycles": calls,
                "encode": encode,
                "query": query,
                "recovery": recovery,
                "correctness": correctness.to_document(),
                "accounting": artifact.ledger.to_document(),
                "bitstream_sha256": artifact.stream_sha256,
                "context_sha256": hashlib.sha256(artifact.recovery_context).hexdigest(),
                "context_document": DecodeContext(artifact.recovery_context).to_document(),
                "measurement_boundary": "WORKER_LOCAL_SESSION_API_THROUGH_OWNED_OUTPUT",
            },
        )
    except (RuntimeError, ValueError, TypeError) as error:
        return WorkloadObservation(
            "FAILED",
            None,
            None,
            {
                "schema_version": "tscb.workload-observation.v3.2",
                "status": "FAILED",
                "kind": config["kind"],
                "collector_enabled": enabled,
                "started_ns": started,
                "finished_ns": time.perf_counter_ns(),
                "lifecycles": calls,
                "exception_type": type(error).__name__,
                "reason": str(error),
            },
        )
