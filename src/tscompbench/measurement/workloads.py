from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import numpy as np


@dataclass(frozen=True)
class QueryRequest:
    start: int
    length: int
    channel_indices: tuple[int, ...]

    def to_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorkloadObservation:
    query: dict[str, Any]
    streaming: dict[str, Any]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.workload-observation.v2",
            "query": self.query,
            "streaming": self.streaming,
        }


@dataclass(frozen=True)
class QueryResult:
    buffers: tuple[Any, ...]
    decoded_elements: int
    bytes_touched: int


@dataclass(frozen=True)
class StreamPushResult:
    emitted: bytes
    state_bytes: int
    buffer_bytes: int
    checkpoint_bits: int = 0


def _percentile(values: list[int], fraction: Decimal) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = int((Decimal(len(ordered) - 1) * fraction).to_integral_value())
    return ordered[rank]


def execute_query_workload(
    *,
    adapter: Any,
    parameters: dict[str, Any],
    stream: bytes,
    routed: Any,
    requests: tuple[QueryRequest, ...],
    workload_id: str,
    index_bits: int,
) -> dict[str, Any]:
    """Run a pre-generated query set and verify every returned logical slice.

    Query generation is intentionally a separate call and therefore cannot enter the
    latency timer. An adapter session must expose ``query(stream, request)`` and return
    ``QueryResult``; full-decode wrappers cannot claim random-access support silently.
    """

    session = adapter.create_session(parameters)
    query = getattr(session, "query", None)
    if not callable(query):
        session.close()
        raise TypeError("query-capable manifest requires session.query")
    value_buffers = tuple(item for item in routed.buffers if str(item.name).startswith("value/"))
    if not value_buffers:
        value_buffers = tuple(item for item in routed.buffers if str(item.name) == "timestamp")
    latencies: list[int] = []
    decoded_elements = bytes_touched = requested_elements = requested_bytes = 0
    try:
        for request in requests:
            start = time.perf_counter_ns()
            result = query(stream, request)
            elapsed = time.perf_counter_ns() - start
            if not isinstance(result, QueryResult):
                raise TypeError("session.query must return QueryResult")
            matrix_buffer = (
                value_buffers[0]
                if len(value_buffers) == 1
                and np.asarray(value_buffers[0].array).ndim == 2
                and np.asarray(value_buffers[0].array).shape[1] == routed.m
                else None
            )
            expected = (
                tuple(
                    (matrix_buffer.name, matrix_buffer.array[:, index])
                    for index in request.channel_indices
                )
                if matrix_buffer is not None
                else tuple(
                    (value_buffers[index].name, value_buffers[index].array)
                    for index in request.channel_indices
                )
            )
            if len(result.buffers) != len(expected):
                raise ValueError("query returned the wrong projection width")
            for (wanted_name, wanted_array), observed in zip(
                expected, result.buffers, strict=True
            ):
                expected_array = wanted_array[request.start : request.start + request.length]
                observed_array = np.asarray(observed.array)
                if (
                    observed.name != wanted_name
                    or observed_array.shape != expected_array.shape
                    or observed_array.dtype != expected_array.dtype
                    or observed_array.tobytes(order="C") != expected_array.tobytes(order="C")
                ):
                    raise ValueError("query correctness check failed")
                requested_bytes += expected_array.nbytes
            requested_elements += request.length * len(expected)
            decoded_elements += result.decoded_elements
            bytes_touched += result.bytes_touched
            latencies.append(elapsed)
    finally:
        session.close()
    decode_amplification = (
        None
        if requested_elements == 0
        else format(Decimal(decoded_elements) / Decimal(requested_elements), ".17g")
    )
    read_amplification = (
        None
        if requested_bytes == 0
        else format(Decimal(bytes_touched) / Decimal(requested_bytes), ".17g")
    )
    return {
        "status": "PASS",
        "reason": "QUERY_PROTOCOL_EXECUTED_AND_VERIFIED",
        "workload_id": workload_id,
        "query_count": len(requests),
        "raw_latency_ns": tuple(latencies),
        "p50_latency_ns": _percentile(latencies, Decimal("0.50")),
        "p95_latency_ns": _percentile(latencies, Decimal("0.95")),
        "p99_latency_ns": _percentile(latencies, Decimal("0.99")),
        "decoded_elements": decoded_elements,
        "requested_elements": requested_elements,
        "bytes_touched": bytes_touched,
        "requested_logical_bytes": requested_bytes,
        "decode_amplification": decode_amplification,
        "read_amplification": read_amplification,
        "index_bits": index_bits,
        "correctness": "PASS_EXACT_SLICE",
    }


def execute_streaming_workload(
    *,
    adapter: Any,
    parameters: dict[str, Any],
    routed: Any,
    compatibility: Any,
    block_size: int,
) -> dict[str, Any]:
    """Drive an explicit streaming session and verify the finalized reconstruction."""

    if block_size < 1:
        raise ValueError("streaming block_size must be positive")
    create = getattr(adapter, "create_stream_session", None)
    if not callable(create):
        raise TypeError("streaming-capable manifest requires create_stream_session")
    session = create(parameters)
    push = getattr(session, "stream_push", None)
    finalize = getattr(session, "stream_finalize", None)
    decompress = getattr(session, "stream_decompress", None)
    accounting = getattr(session, "stream_accounting", None)
    if not all(callable(item) for item in (push, finalize, decompress, accounting)):
        session.close()
        raise TypeError("streaming session is missing a required lifecycle method")
    from tscompbench.contracts import RunStatus
    from tscompbench.execution.preparation import prepare_execution_input
    from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
    from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array
    from tscompbench.validation import validate_common_correctness

    latencies: list[int] = []
    encoded_parts: list[bytes] = []
    state_peak = buffer_peak = checkpoint_bits = 0
    first_output_latency: int | None = None
    stream_start = time.perf_counter_ns()
    try:
        for offset in range(0, routed.n, block_size):
            stop = min(routed.n, offset + block_size)
            buffers = tuple(
                LogicalBuffer(
                    item.name,
                    item.array[offset:stop],
                    item.array[offset:stop].nbytes * 8,
                )
                for item in routed.buffers
            )
            timestamp = (
                None
                if routed.timestamp_reference is None
                else routed.timestamp_reference[offset:stop]
            )
            chunk = RoutedInput(
                dataset_id=routed.dataset_id,
                track=routed.track,
                buffers=buffers,
                timestamp_reference=timestamp,
                validity_reference=(
                    None
                    if routed.validity_reference is None
                    else routed.validity_reference[offset:stop]
                ),
                n=stop - offset,
                m=routed.m,
                canonical_raw_bits=sum(item.logical_bits for item in buffers),
                input_sha256=hash_logical_buffers(buffers),
                segment_plan_id=routed.segment_plan_id,
                timestamp_unit=routed.timestamp_unit,
                timestamp_epoch=routed.timestamp_epoch,
                value_units=routed.value_units,
                pairing_reference_sha256=hash_reference_array(timestamp),
            )
            started = time.perf_counter_ns()
            prepared_chunk = prepare_execution_input(chunk, compatibility)
            result = push(prepared_chunk.codec_input)
            latency = time.perf_counter_ns() - started
            if not isinstance(result, StreamPushResult):
                raise TypeError("stream_push must return StreamPushResult")
            latencies.append(latency)
            encoded_parts.append(result.emitted)
            state_peak = max(state_peak, result.state_bytes)
            buffer_peak = max(buffer_peak, result.buffer_bytes)
            checkpoint_bits += result.checkpoint_bits
            if result.emitted and first_output_latency is None:
                first_output_latency = time.perf_counter_ns() - stream_start
        finalize_start = time.perf_counter_ns()
        tail = finalize()
        finalize_ns = time.perf_counter_ns() - finalize_start
        if not isinstance(tail, bytes):
            raise TypeError("stream_finalize must return bytes")
        encoded_parts.append(tail)
        stream = b"".join(encoded_parts)
        ledger = accounting(stream, routed)
        decoded = decompress(stream)
        correctness = validate_common_correctness(
            routed,
            decoded,
            compatibility,
            loss_mode=compatibility.effective_loss_mode,
            parameters=parameters,
            deterministic_match=None,
            input_immutable=True,
            canary_intact=True,
        )
        if correctness.status is not RunStatus.PASS:
            raise ValueError(
                f"stream reconstruction correctness check failed: {correctness.first_failure_stage}"
            )
        if ledger.checkpoint_bits != checkpoint_bits:
            raise ValueError("stream checkpoint telemetry does not match accounting")
    finally:
        session.close()
    return {
        "status": "PASS",
        "reason": "STREAM_PROTOCOL_EXECUTED_AND_VERIFIED",
        "block_size": block_size,
        "block_count": len(latencies),
        "first_output_latency_ns": first_output_latency,
        "raw_block_latency_ns": tuple(latencies),
        "p50_block_latency_ns": _percentile(latencies, Decimal("0.50")),
        "p95_block_latency_ns": _percentile(latencies, Decimal("0.95")),
        "p99_block_latency_ns": _percentile(latencies, Decimal("0.99")),
        "finalize_latency_ns": finalize_ns,
        "lookahead_elements": 0,
        "buffer_bytes": buffer_peak,
        "state_bytes": state_peak,
        "checkpoint_bits": checkpoint_bits,
        "final_bits": ledger.final_bits,
        "final_physical_bytes": ledger.final_physical_bytes,
        "correctness": "PASS_EXACT_STREAM_RECONSTRUCTION",
        "backpressure_policy": "CALLER_PACED_BLOCK_PUSH",
    }


def build_query_workload(
    *, n: int, m: int, seed: int, query_count: int
) -> tuple[QueryRequest, ...]:
    """Pre-generate the standard point/range × projection matrix outside timers."""

    if n < 0 or m < 0 or query_count < 1:
        raise ValueError("query dimensions/count are invalid")
    if n == 0 or m == 0:
        return ()
    rng = random.Random(seed)
    lengths = tuple(dict.fromkeys(min(n, value) for value in (1, 16, 100, 1000, n)))
    widths = tuple(dict.fromkeys(min(m, value) for value in (1, 2, 4, 8, m)))
    matrix = [(length, width) for length in lengths for width in widths]
    requests: list[QueryRequest] = []
    for index in range(max(query_count, len(matrix))):
        length, width = matrix[index % len(matrix)]
        start = rng.randrange(0, n - length + 1)
        channels = tuple(sorted(rng.sample(range(m), width)))
        requests.append(QueryRequest(start, length, channels))
    return tuple(requests)


def unavailable_workloads(
    *,
    features: dict[str, Any],
    query_requested: bool,
    streaming_requested: bool,
    query_workload_id: str | None,
) -> WorkloadObservation:
    query_capable = bool(features.get("query") or features.get("random_access"))
    streaming_capable = bool(features.get("streaming"))
    query_status = (
        "NOT_REQUESTED"
        if not query_requested
        else "PENDING_EXECUTION"
        if query_capable
        else "UNSUPPORTED"
    )
    streaming_status = (
        "NOT_REQUESTED"
        if not streaming_requested
        else "PENDING_EXECUTION"
        if streaming_capable
        else "UNSUPPORTED"
    )
    return WorkloadObservation(
        query={
            "status": query_status,
            "reason": (
                "PROFILE_DISABLED"
                if not query_requested
                else "CODEC_CAPABILITY_FALSE"
                if not query_capable
                else "WORKLOAD_EXECUTION_NOT_COMPLETED"
            ),
            "workload_id": query_workload_id,
            "latency_ns": None,
            "decode_amplification": None,
            "read_amplification": None,
            "bytes_touched": None,
            "correctness": None,
        },
        streaming={
            "status": streaming_status,
            "reason": (
                "PROFILE_DISABLED"
                if not streaming_requested
                else "CODEC_CAPABILITY_FALSE"
                if not streaming_capable
                else "WORKLOAD_EXECUTION_NOT_COMPLETED"
            ),
            "first_output_latency_ns": None,
            "block_latency_ns": None,
            "lookahead_elements": None,
            "buffer_bytes": None,
            "state_bytes": None,
            "checkpoint_bits": None,
            "reset_overhead_ns": None,
            "backpressure_policy": None,
        },
    )
