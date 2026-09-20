from __future__ import annotations

import gc
import hashlib
import resource
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from tscompbench.codecs import CompatibilityPlan
from tscompbench.measurement import (
    MeasurementPolicy,
    ResourceSampler,
    WarmupObservation,
)
from tscompbench.measurement import (
    TimingObservation as PerformanceTimingObservation,
)
from tscompbench.measurement.contracts import decimal_rate

from .preparation import prepare_execution_input
from .protocol import (
    CodecAdapter,
    DecodedOutput,
    EncodedArtifact,
    ExecutionContractError,
    RoutedInput,
)
from .routing import hash_logical_buffers, hash_reference_array

_CANARY = bytes.fromhex("a55ac33c966969963cc35aa5") * 3


def _native_timing(session: Any, parameters: dict[str, Any]) -> tuple[int, int] | None:
    if not parameters.get("native_timing", True):
        return None
    query = getattr(session, "native_timing", None)
    if query is None:
        return None
    timing = query()
    if timing is not None and (
        not isinstance(timing, tuple)
        or len(timing) != 2
        or any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in timing
        )
    ):
        raise ExecutionContractError("native timing must contain two non-negative integer totals")
    return timing


@dataclass(frozen=True)
class TimingObservation:
    encode_wall_ns: int
    decode_wall_ns: int
    encode_process_cpu_ns: int
    decode_process_cpu_ns: int
    native_encode_wall_ns: int | None = None
    native_decode_wall_ns: int | None = None

    def to_document(self) -> dict[str, int | None]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class ResourceObservation:
    process_user_seconds: str
    process_system_seconds: str
    peak_rss_kib: int
    scope: str = "CURRENT_PROCESS_QUALIFICATION"

    def to_document(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class RoundTripObservation:
    encoded: EncodedArtifact
    decoded: DecodedOutput
    timing: TimingObservation
    resources: ResourceObservation
    input_immutable: bool
    canary_intact: bool
    determinism_match: bool | None
    lifecycle_trace: tuple[str, ...]


@dataclass(frozen=True)
class MeasuredRoundTripObservation:
    encoded: EncodedArtifact
    decoded: DecodedOutput
    timing: PerformanceTimingObservation
    resources: Any
    input_immutable: bool
    canary_intact: bool
    determinism_match: bool | None
    lifecycle_trace: tuple[str, ...]


def _encode(
    adapter: CodecAdapter,
    routed: RoutedInput,
    parameters: dict[str, Any],
    *,
    capacity_override: int | None = None,
) -> tuple[EncodedArtifact, int, int, bool, bool]:
    session = adapter.create_session(parameters)
    try:
        bound = session.output_bound(routed)
        if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
            raise ExecutionContractError("output_bound must return a non-negative integer")
        capacity = bound if capacity_override is None else capacity_override
        if capacity < 0:
            raise ExecutionContractError("output capacity cannot be negative")
        storage = bytearray(capacity + len(_CANARY))
        storage[capacity:] = _CANARY
        before = hash_logical_buffers(routed.buffers)
        pairing_before = hash_reference_array(routed.timestamp_reference)
        wall_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        updated = session.compress_update(routed, memoryview(storage)[:capacity])
        if not isinstance(updated, int) or updated < 0 or updated > capacity:
            raise ExecutionContractError("compress_update returned an invalid used length")
        finalized = session.finalize(memoryview(storage)[updated:capacity])
        if not isinstance(finalized, int) or finalized < 0 or updated + finalized > capacity:
            raise ExecutionContractError("finalize returned an invalid used length")
        cpu_ns = time.process_time_ns() - cpu_start
        wall_ns = time.perf_counter_ns() - wall_start
        native_timing = _native_timing(session, parameters)
        stream = bytes(storage[: updated + finalized])
        ledger = session.accounting(stream, routed)
        artifact = EncodedArtifact(
            stream=stream,
            update_bytes=updated,
            finalize_bytes=finalized,
            output_capacity_bytes=capacity,
            stream_sha256=hashlib.sha256(stream).hexdigest(),
            ledger=ledger,
            native_encode_wall_ns=None if native_timing is None else native_timing[0],
        )
        return (
            artifact,
            wall_ns,
            cpu_ns,
            before == hash_logical_buffers(routed.buffers)
            and pairing_before == hash_reference_array(routed.timestamp_reference)
            and pairing_before == routed.pairing_reference_sha256,
            bytes(storage[capacity:]) == _CANARY,
        )
    finally:
        session.close()


def perform_roundtrip(
    adapter: CodecAdapter,
    routed: RoutedInput,
    parameters: dict[str, Any],
    *,
    verify_determinism: bool = True,
) -> RoundTripObservation:
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    artifact, encode_wall, encode_cpu, input_immutable, canary_intact = _encode(
        adapter, routed, parameters
    )
    session = adapter.create_session(parameters)
    try:
        wall_start = time.perf_counter_ns()
        cpu_start = time.process_time_ns()
        decoded = session.decompress(artifact.stream)
        decode_cpu = time.process_time_ns() - cpu_start
        decode_wall = time.perf_counter_ns() - wall_start
        native_decode = _native_timing(session, parameters)
    finally:
        session.close()
    # The resource sample belongs to this qualification repetition only.  A
    # deterministic re-encode is a validation probe, not part of its measured
    # encode/decode resource observation.
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    deterministic_match: bool | None = None
    if verify_determinism and adapter.deterministic:
        repeated, _, _, repeated_input_immutable, repeated_canary = _encode(
            adapter, routed, parameters
        )
        deterministic_match = repeated.stream == artifact.stream
        input_immutable = input_immutable and repeated_input_immutable
        canary_intact = canary_intact and repeated_canary
    return RoundTripObservation(
        encoded=artifact,
        decoded=decoded,
        timing=TimingObservation(
            encode_wall, decode_wall, encode_cpu, decode_cpu,
            artifact.native_encode_wall_ns,
            None if native_decode is None else native_decode[1],
        ),
        resources=ResourceObservation(
            process_user_seconds=format(
                max(0.0, usage_after.ru_utime - usage_before.ru_utime), ".17g"
            ),
            process_system_seconds=format(
                max(0.0, usage_after.ru_stime - usage_before.ru_stime), ".17g"
            ),
            peak_rss_kib=int(usage_after.ru_maxrss),
        ),
        input_immutable=input_immutable,
        canary_intact=canary_intact,
        determinism_match=deterministic_match,
        lifecycle_trace=(
            "CONTEXT_CREATED",
            "COMPRESS_UPDATE",
            "FINALIZE",
            "ACCOUNTING",
            "DECOMPRESS_INDEPENDENT_CONTEXT",
            "CONTEXT_DESTROYED",
        ),
    )


def _usage_pair() -> tuple[Decimal, Decimal]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return Decimal(str(usage.ru_utime)), Decimal(str(usage.ru_stime))


def _usage_delta(
    before: tuple[Decimal, Decimal], after: tuple[Decimal, Decimal]
) -> tuple[Decimal, Decimal]:
    return max(Decimal(0), after[0] - before[0]), max(Decimal(0), after[1] - before[1])


def _measure_reverse_adapter(
    original: RoutedInput,
    decoded: DecodedOutput,
    compatibility: CompatibilityPlan,
) -> None:
    """Materialize declared inverse adapter work without changing validation evidence."""

    by_name = decoded.by_name()
    for expected in original.buffers:
        current = by_name[expected.name].array
        for operation in reversed(compatibility.operations):
            kind = operation.kind.value
            if kind == "TRANSPOSE_COPY" and current.ndim >= 2:
                current = current.T
            elif kind == "ENDIANNESS_CONVERSION":
                current = current.byteswap().view(current.dtype.newbyteorder())
            elif kind in {"EXACT_WIDEN", "LOSSY_CAST"}:
                current = current.astype(expected.array.dtype, copy=False)
        # A consumer-visible scalar read prevents a lazy backend from deferring work.
        if current.size:
            current.reshape(-1)[-1].item()


def perform_warmup(
    adapter: CodecAdapter,
    routed: RoutedInput,
    compatibility: CompatibilityPlan,
    parameters: dict[str, Any],
    policy: MeasurementPolicy,
) -> WarmupObservation:
    if policy.iteration_semantics != "INDEPENDENT_OBJECT":
        raise ExecutionContractError(
            "CONTINUOUS_STREAM requires a streaming-capable adapter protocol"
        )
    count = 0
    start = time.perf_counter_ns()
    elapsed = 0
    while count < policy.warmup_min_count or elapsed < policy.warmup_min_ns:
        prepared = prepare_execution_input(routed, compatibility)
        result = perform_roundtrip(
            adapter, prepared.codec_input, parameters, verify_determinism=False
        )
        _measure_reverse_adapter(routed, result.decoded, compatibility)
        count += 1
        elapsed = time.perf_counter_ns() - start
        if count >= policy.max_inner_iterations:
            break
    satisfied = count >= policy.warmup_min_count and elapsed >= policy.warmup_min_ns
    if not satisfied:
        raise ExecutionContractError("warmup thresholds exceeded max_inner_iterations")
    return WarmupObservation(
        completed_iterations=count,
        elapsed_wall_ns=elapsed,
        required_min_count=policy.warmup_min_count,
        required_min_wall_ns=policy.warmup_min_ns,
        iteration_semantics=policy.iteration_semantics,
        threshold_satisfied=True,
    )


def perform_measured_roundtrip(
    adapter: CodecAdapter,
    routed: RoutedInput,
    compatibility: CompatibilityPlan,
    parameters: dict[str, Any],
    policy: MeasurementPolicy,
) -> MeasuredRoundTripObservation:
    """Execute one formal repetition, including any min-duration inner loop.

    Every inner iteration is a fresh, independently finalized object. The final
    iteration supplies the correctness/accounting evidence; deterministic adapters are
    also checked across all streams produced inside this same formal repetition.
    """

    if policy.iteration_semantics != "INDEPENDENT_OBJECT":
        raise ExecutionContractError(
            "CONTINUOUS_STREAM requires a streaming-capable adapter protocol"
        )
    canonical_bytes = (routed.canonical_raw_bits + 7) // 8
    sampler = ResourceSampler(
        requested_scope=policy.resource_scope,
        memory_accounting_scope=policy.memory_accounting_scope,
        counter_method=policy.counter_method,
        energy_method=policy.energy_method,
        allocated_logical_cpus=policy.threads * policy.processes,
        canonical_bytes=canonical_bytes,
    )
    start_wall = time.perf_counter_ns()
    sampler.start(start_wall)
    core_encode = core_decode = pipeline_encode = pipeline_decode = e2e = 0
    native_encode: int | None = 0
    native_decode: int | None = 0
    encode_cpu = decode_cpu = 0
    encode_user = encode_system = Decimal(0)
    decode_user = decode_system = Decimal(0)
    iterations = 0
    first_stream: bytes | None = None
    all_streams_match = True
    codec_input_bytes = 0
    last_artifact: EncodedArtifact | None = None
    last_decoded: DecodedOutput | None = None
    input_immutable = True
    canary_intact = True
    gc_was_enabled = gc.isenabled()
    if policy.gc_policy == "DISABLED_DURING_TIMING" and gc_was_enabled:
        gc.disable()
    try:
        while True:
            e2e_start = time.perf_counter_ns()
            encode_phase_usage = _usage_pair()
            pipeline_start = time.perf_counter_ns()
            prepared = prepare_execution_input(routed, compatibility)
            codec_input_bytes = sum(item.array.nbytes for item in prepared.codec_input.buffers)
            artifact, enc_wall, enc_cpu, immutable, canary = _encode(
                adapter, prepared.codec_input, parameters
            )
            encode_phase_end = time.perf_counter_ns()
            encode_phase_delta = _usage_delta(encode_phase_usage, _usage_pair())

            decode_phase_usage = _usage_pair()
            decode_pipeline_start = time.perf_counter_ns()
            session = adapter.create_session(parameters)
            try:
                decode_core_start = time.perf_counter_ns()
                decode_cpu_start = time.process_time_ns()
                decoded = session.decompress(artifact.stream)
                dec_cpu = time.process_time_ns() - decode_cpu_start
                dec_wall = time.perf_counter_ns() - decode_core_start
                native_dec = _native_timing(session, parameters)
            finally:
                session.close()
            _measure_reverse_adapter(routed, decoded, compatibility)
            decode_phase_end = time.perf_counter_ns()
            decode_phase_delta = _usage_delta(decode_phase_usage, _usage_pair())

            core_encode += enc_wall
            core_decode += dec_wall
            # Never publish partial native totals as if they covered every inner iteration.
            native_encode = (
                None if native_encode is None or artifact.native_encode_wall_ns is None
                else native_encode + artifact.native_encode_wall_ns
            )
            native_decode = (
                None if native_decode is None or native_dec is None
                else native_decode + native_dec[1]
            )
            pipeline_encode += encode_phase_end - pipeline_start
            pipeline_decode += decode_phase_end - decode_pipeline_start
            e2e += decode_phase_end - e2e_start
            encode_cpu += enc_cpu
            decode_cpu += dec_cpu
            encode_user += encode_phase_delta[0]
            encode_system += encode_phase_delta[1]
            decode_user += decode_phase_delta[0]
            decode_system += decode_phase_delta[1]
            input_immutable = input_immutable and immutable
            canary_intact = canary_intact and canary
            if first_stream is None:
                first_stream = artifact.stream
            elif adapter.deterministic and artifact.stream != first_stream:
                all_streams_match = False
            last_artifact = artifact
            last_decoded = decoded
            iterations += 1
            selected = {
                "CORE": core_encode + core_decode,
                "PIPELINE": pipeline_encode + pipeline_decode,
                "E2E": e2e,
            }[policy.timing_scope]
            if selected >= policy.repetition_min_ns:
                break
            if iterations >= policy.max_inner_iterations:
                raise ExecutionContractError(
                    "formal repetition min duration exceeded max_inner_iterations"
                )
    finally:
        if policy.gc_policy == "DISABLED_DURING_TIMING" and gc_was_enabled:
            gc.enable()
    end_wall = time.perf_counter_ns()
    resources = sampler.stop(end_wall).with_phase_cpu(
        encode_user_seconds=encode_user,
        encode_system_seconds=encode_system,
        decode_user_seconds=decode_user,
        decode_system_seconds=decode_system,
    )
    if last_artifact is None or last_decoded is None or iterations < 1:
        raise ExecutionContractError("formal repetition produced no observation")
    selected_wall = {
        "CORE": core_encode + core_decode,
        "PIPELINE": pipeline_encode + pipeline_decode,
        "E2E": e2e,
    }[policy.timing_scope]
    selected_encode = core_encode if policy.timing_scope == "CORE" else pipeline_encode
    selected_decode = core_decode if policy.timing_scope == "CORE" else pipeline_decode
    selected_cpu = (
        encode_cpu + decode_cpu
        if policy.timing_scope == "CORE"
        else int(
            (encode_user + encode_system + decode_user + decode_system) * Decimal(1_000_000_000)
        )
    )
    value_elements = routed.n * max(1, routed.m) if routed.track.value in {"VALUE", "SYSTEM"} else 0
    timing = PerformanceTimingObservation(
        timing_scope=policy.timing_scope,
        e2e_input_mode="CANONICAL_MEMORY_ROUTED_VIEW",
        iteration_semantics=policy.iteration_semantics,
        inner_iterations=iterations,
        selected_wall_ns=selected_wall,
        selected_encode_wall_ns=selected_encode,
        selected_decode_wall_ns=selected_decode,
        selected_process_cpu_ns=selected_cpu,
        core_encode_wall_ns=core_encode,
        core_decode_wall_ns=core_decode,
        pipeline_encode_wall_ns=pipeline_encode,
        pipeline_decode_wall_ns=pipeline_decode,
        e2e_wall_ns=e2e,
        encode_process_cpu_ns=encode_cpu,
        decode_process_cpu_ns=decode_cpu,
        canonical_bytes_per_iteration=canonical_bytes,
        codec_input_bytes_per_iteration=codec_input_bytes,
        rows_per_iteration=routed.n,
        value_elements_per_iteration=value_elements,
        semantic_encode_mb_per_second=decimal_rate(
            canonical_bytes * iterations, selected_encode, scale=1_000_000
        ),
        semantic_decode_mb_per_second=decimal_rate(
            canonical_bytes * iterations, selected_decode, scale=1_000_000
        ),
        codec_input_encode_mb_per_second=decimal_rate(
            codec_input_bytes * iterations, selected_encode, scale=1_000_000
        ),
        codec_input_decode_mb_per_second=decimal_rate(
            codec_input_bytes * iterations, selected_decode, scale=1_000_000
        ),
        rows_per_second=decimal_rate(routed.n * iterations, selected_wall),
        timestamps_per_second=(
            decimal_rate(routed.n * iterations, selected_wall)
            if routed.track.value in {"TIMESTAMP", "SYSTEM"}
            else None
        ),
        value_elements_per_second=(
            None
            if value_elements == 0
            else decimal_rate(value_elements * iterations, selected_wall)
        ),
        min_duration_satisfied=selected_wall >= policy.repetition_min_ns,
        native_encode_wall_ns=native_encode,
        native_decode_wall_ns=native_decode,
        native_encode_mb_per_second=(
            None if native_encode is None else decimal_rate(
                codec_input_bytes * iterations, native_encode, scale=1_000_000
            )
        ),
        native_decode_mb_per_second=(
            None if native_decode is None else decimal_rate(
                codec_input_bytes * iterations, native_decode, scale=1_000_000
            )
        ),
        native_timing_enabled=bool(parameters.get("native_timing", True)),
        native_timing_boundary=(
            str(getattr(adapter, "native_timing_boundary", "CODEC_API_ONLY_V1"))
            if native_encode is not None or native_decode is not None
            else None
        ),
        native_timing_clock=(
            "CLOCK_MONOTONIC" if native_encode is not None or native_decode is not None else None
        ),
    )
    deterministic_match = (
        None
        if not adapter.deterministic
        else all_streams_match and first_stream == last_artifact.stream
    )
    return MeasuredRoundTripObservation(
        encoded=last_artifact,
        decoded=last_decoded,
        timing=timing,
        resources=resources,
        input_immutable=input_immutable,
        canary_intact=canary_intact,
        determinism_match=deterministic_match,
        lifecycle_trace=(
            "RESOURCE_MONITOR_STARTED",
            "ADAPTER_PREPARE_PER_INNER_ITERATION",
            "CONTEXT_CREATED_PER_INNER_ITERATION",
            "COMPRESS_UPDATE",
            "FINALIZE",
            "ACCOUNTING",
            "DECOMPRESS_INDEPENDENT_CONTEXT",
            "REVERSE_ADAPTER_CONSUMED",
            "RESOURCE_MONITOR_STOPPED",
        ),
    )
