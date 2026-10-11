"""Cold independent objects: fresh encode/decode spawn through owned parent outputs."""

from __future__ import annotations

import hashlib
import math
import os
import random
import resource
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.codecs import CodecManifest, CompatibilityPlan
from tscompbench.contracts import RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement import ResourceSampler
from tscompbench.measurement.contracts import decimal_rate
from tscompbench.measurement.thread_monitor import thread_budget_evidence, unobserved_threads
from tscompbench.measurement.v32_protocol import (
    MeasurementProtocol,
    _pilot_metrics,
    decimal_observations,
)
from tscompbench.validation import validate_common_correctness

from .isolation import IsolatedCallResult, run_isolated
from .preparation import prepare_execution_input
from .protocol import (
    DecodedOutput,
    EncodedArtifact,
    ExecutionContractError,
    LogicalBuffer,
    RoutedInput,
)
from .recovery import DecodeContext, bind_decode_context, decode_in_fresh_worker
from .repetition import _encode
from .routing import hash_logical_buffers, hash_reference_array

_BOUNDARY = "SPAWN_THROUGH_PARENT_OWNED_OUTPUT_MATERIALIZATION"


class ColdDriverError(ValueError):
    pass


@dataclass(frozen=True)
class ColdWorkerResources:
    collector_enabled: bool
    allocated_logical_cpus: int
    canonical_bytes: int


def _sampler(options: ColdWorkerResources) -> ResourceSampler:
    return ResourceSampler(
        requested_scope="PROCESS",
        memory_accounting_scope="PROCESS_RSS",
        counter_method="NOT_COLLECTED",
        energy_method="NOT_COLLECTED",
        allocated_logical_cpus=options.allocated_logical_cpus,
        canonical_bytes=options.canonical_bytes,
        enabled=options.collector_enabled,
    )


def _finish_worker_resources(sampler: ResourceSampler) -> dict[str, Any]:
    observation = sampler.stop(time.perf_counter_ns()).to_document()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "collector_enabled": sampler.enabled,
        "function_boundary": observation,
        "cumulative_fresh_child": {
            "user_seconds": format(Decimal(str(usage.ru_utime)), "f"),
            "system_seconds": format(Decimal(str(usage.ru_stime)), "f"),
            "total_seconds": format(
                Decimal(str(usage.ru_utime)) + Decimal(str(usage.ru_stime)), "f"
            ),
            "peak_rss_bytes": int(usage.ru_maxrss) * 1024,
            "scope": "FRESH_CHILD_CUMULATIVE_STARTUP_IMPORT_THROUGH_PRE_IPC_RESULT_SNAPSHOT",
            "payload_pickle_and_exit_cpu_included": False,
        },
        "pss_uss_scope": "FUNCTION_EXIT_BOUNDARY_NOT_STARTUP_HIGH_WATER",
    }


@dataclass(frozen=True)
class ColdEncoded:
    encoded: EncodedArtifact
    resources: dict[str, Any]
    codec_input_bytes: int
    input_immutable: bool
    canary_intact: bool
    worker_pid: int
    function_started_ns: int
    function_finished_ns: int


@dataclass(frozen=True)
class ColdDecoded:
    decoded: DecodedOutput
    resources: dict[str, Any]
    recovery: dict[str, Any]
    worker_pid: int
    function_started_ns: int
    function_finished_ns: int


def _cold_encode_worker(
    project_root: Path,
    manifest_document: dict[str, Any],
    codec_key: str,
    algorithm_id: str,
    routed: RoutedInput,
    compatibility: CompatibilityPlan,
    parameters: dict[str, Any],
    options: ColdWorkerResources,
    source_reject_fallback: bool,
) -> ColdEncoded:
    from tscompbench.adapters.factory import create_adapter

    started = time.perf_counter_ns()
    sampler = _sampler(options)
    sampler.start(started)
    manifest = CodecManifest(codec_key, manifest_document, algorithm_id)
    adapter = create_adapter(
        project_root, manifest, source_reject_fallback=source_reject_fallback
    )
    before = hash_logical_buffers(routed.buffers)
    pairing = hash_reference_array(routed.timestamp_reference)
    context = DecodeContext.from_routed(
        routed,
        compatibility,
        adapter_id=adapter.adapter_id,
        parameters=parameters,
    )
    prepared = prepare_execution_input(
        routed,
        compatibility,
        max_abs_error=parameters.get("error_bound"),
    )
    artifact, _, _, immutable, canary = _encode(adapter, prepared.codec_input, parameters)
    artifact = bind_decode_context(artifact, context)
    resource_evidence = _finish_worker_resources(sampler)
    return ColdEncoded(
        artifact,
        resource_evidence,
        sum(buffer.array.nbytes for buffer in prepared.codec_input.buffers),
        immutable
        and before == routed.input_sha256 == hash_logical_buffers(routed.buffers)
        and pairing == hash_reference_array(routed.timestamp_reference),
        canary,
        os.getpid(),
        started,
        time.perf_counter_ns(),
    )


def _cold_decode_worker(
    project_root: Path,
    manifest_document: dict[str, Any],
    codec_key: str,
    context_bytes: bytes,
    stream: bytes,
    stream_sha256: str,
    options: ColdWorkerResources,
    source_reject_fallback: bool,
) -> ColdDecoded:
    """Its signature deliberately has no original input, adapter or encoder state."""
    started = time.perf_counter_ns()
    sampler = _sampler(options)
    sampler.start(started)
    decoded, recovery = decode_in_fresh_worker(
        project_root,
        manifest_document,
        codec_key,
        context_bytes,
        stream,
        stream_sha256,
        source_reject_fallback,
    )
    resource_evidence = _finish_worker_resources(sampler)
    return ColdDecoded(
        decoded, resource_evidence, recovery, os.getpid(), started, time.perf_counter_ns()
    )


def _owned_parent_decoded(decoded: DecodedOutput) -> DecodedOutput:
    buffers = []
    for item in decoded.buffers:
        owned = np.array(item.array, copy=True, order="C")
        owned.flags.writeable = False
        buffers.append(LogicalBuffer(item.name, owned, item.logical_bits))
    return DecodedOutput(tuple(buffers))


@dataclass(frozen=True)
class ColdTimingObservation:
    encode_ns: int
    decode_ns: int
    canonical_bytes: int
    codec_input_bytes: int
    rows: int
    value_elements: int
    child_cumulative_cpu_ns: int
    minimum_duration_satisfied: bool

    @property
    def inner_iterations(self) -> int:
        return 1

    @property
    def selected_encode_wall_ns(self) -> int:
        return self.encode_ns

    @property
    def selected_decode_wall_ns(self) -> int:
        return self.decode_ns

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.cold-timing-observation.v3.2",
            "timing_scope": "PIPELINE",
            "timing_boundary": _BOUNDARY,
            "profile": "COLD_PROCESS",
            "clock": "PERF_COUNTER_NS",
            "e2e_input_mode": "CANONICAL_MEMORY_PICKLED_TO_FRESH_ENCODER",
            "iteration_semantics": "INDEPENDENT_OBJECT",
            "inner_iterations": 1,
            "selected_encode_wall_ns": self.encode_ns,
            "selected_decode_wall_ns": self.decode_ns,
            "selected_wall_ns": self.encode_ns + self.decode_ns,
            "selected_process_cpu_ns": self.child_cumulative_cpu_ns,
            "selected_cpu_scope": (
                "TWO_FRESH_CHILD_CUMULATIVE_PRE_IPC_SNAPSHOTS_PARENT_CPU_SEPARATE"
            ),
            "core_encode_wall_ns": None,
            "core_decode_wall_ns": None,
            "native_encode_wall_ns": None,
            "native_decode_wall_ns": None,
            "native_timing_enabled": False,
            "canonical_bytes_per_iteration": self.canonical_bytes,
            "codec_input_bytes_per_iteration": self.codec_input_bytes,
            "rows_per_iteration": self.rows,
            "value_elements_per_iteration": self.value_elements,
            "semantic_encode_mb_per_second": decimal_rate(
                self.canonical_bytes, self.encode_ns, scale=10**6
            ),
            "semantic_decode_mb_per_second": decimal_rate(
                self.canonical_bytes, self.decode_ns, scale=10**6
            ),
            "codec_input_encode_mb_per_second": decimal_rate(
                self.codec_input_bytes, self.encode_ns, scale=10**6
            ),
            "codec_input_decode_mb_per_second": decimal_rate(
                self.codec_input_bytes, self.decode_ns, scale=10**6
            ),
            "min_duration_satisfied": self.minimum_duration_satisfied,
            "startup_import_adapter_loading_included": True,
            "parent_input_pickle_result_ipc_materialization_and_worker_exit_included": True,
            "os_cache_cleared": False,
        }


@dataclass(frozen=True)
class ColdResourceObservation:
    encode: dict[str, Any]
    decode: dict[str, Any]
    parent: dict[str, Any]

    def to_document(self) -> dict[str, Any]:
        children = [self.encode["cumulative_fresh_child"], self.decode["cumulative_fresh_child"]]
        user = sum((Decimal(child["user_seconds"]) for child in children), Decimal(0))
        system = sum((Decimal(child["system_seconds"]) for child in children), Decimal(0))
        swaps = [
            direction["function_boundary"]["swap_observed"]
            for direction in (self.encode, self.decode)
        ]
        return {
            "schema_version": "tscb.cold-resource-observation.v3.2",
            "requested_scope": "PROCESS",
            "actual_scope": "TWO_SEQUENTIAL_FRESH_WORKERS_AND_PARENT_SEPARATELY_REPORTED",
            "scope_availability": "PARTIAL",
            "memory_accounting_scope": "PROCESS_RSS",
            "peak_process_rss_bytes": max(child["peak_rss_bytes"] for child in children),
            "peak_scope": (
                "MAX_SEQUENTIAL_CHILD_PRE_IPC_RSS_HIGH_WATER_NOT_PARENT_PROCESS_TREE_OR_EXIT"
            ),
            "process_user_seconds": format(user, "f"),
            "process_system_seconds": format(system, "f"),
            "process_total_seconds": format(user + system, "f"),
            "encode_total_seconds": children[0]["total_seconds"],
            "decode_total_seconds": children[1]["total_seconds"],
            "cpu_scope": "CHILD_CUMULATIVE_PRE_IPC_SNAPSHOTS_STARTUP_IMPORT_INCLUDED",
            "swap_observed": True
            if True in swaps
            else False
            if all(value is False for value in swaps)
            else None,
            "swap_observation_scope": "SYSTEM_VMSTAT_HOST_BOUNDARIES_NOT_CODEC_ATTRIBUTION",
            "encode": self.encode,
            "decode": self.decode,
            "parent": self.parent,
            "concurrent_worker_processes": 1,
            "fresh_worker_processes_per_object": 2,
            "hard_rss_limit": False,
            "hard_process_tree_limit": False,
        }


@dataclass(frozen=True)
class MeasuredColdObservation:
    status: RunStatus
    reason: str
    encoded: EncodedArtifact | None
    decoded: DecodedOutput | None
    timing: ColdTimingObservation | None
    resources: ColdResourceObservation | None
    correctness: Any | None
    input_immutable: bool
    canary_intact: bool
    diagnostics: dict[str, Any]
    determinism_match: bool | None = None
    lifecycle_trace: tuple[str, ...] = (
        "ENCODE_FRESH_SPAWN",
        "FINALIZE_AND_CHARGE_PERSISTED_CONTEXT",
        "ENCODER_EXITED",
        "DECODE_FRESH_SPAWN_WITHOUT_INPUT",
        "OWNED_PARENT_OUTPUT_MATERIALIZED",
        "DECODER_EXITED",
    )

    def to_document(self) -> dict[str, Any]:
        return decimal_observations(
            {
                "schema_version": "tscb.cold-object-observation.v3.2",
                "status": self.status.value,
                "reason": self.reason,
                "accounting": None if self.encoded is None else self.encoded.ledger.to_document(),
                "bitstream_sha256": None if self.encoded is None else self.encoded.stream_sha256,
                "timing": None if self.timing is None else self.timing.to_document(),
                "resources": None if self.resources is None else self.resources.to_document(),
                "correctness": None if self.correctness is None else self.correctness.to_document(),
                "input_immutable": self.input_immutable,
                "canary_intact": self.canary_intact,
                "determinism_match": self.determinism_match,
                "lifecycle_trace": list(self.lifecycle_trace),
                "diagnostics": self.diagnostics,
            }
        )


def _validate_cold(protocol: MeasurementProtocol) -> None:
    if (
        protocol.profile != "COLD_PROCESS"
        or protocol.timing_scope != "PIPELINE"
        or protocol.start_method != "spawn"
        or protocol.max_inner_iterations != 1
        or protocol.warmup_min_count
        or protocol.warmup_min_ns
    ):
        raise ColdDriverError(
            "cold driver requires COLD_PROCESS PIPELINE spawn, no warmup and exactly one object"
        )


def _call_failure(call: IsolatedCallResult) -> RunStatus:
    if call.status is RunStatus.PASS:
        return RunStatus.CRASHED
    return {
        "SourceDomainError": RunStatus.UNSUPPORTED,
        "OutputCapacityError": RunStatus.HARNESS_CAPACITY_ERROR,
        "MemoryError": RunStatus.OOM,
    }.get(call.exception_type or "", call.status)


def _direction_lifecycle(
    call: IsolatedCallResult, finished_ns: int, threads: int
) -> dict[str, Any]:
    observation = call.thread_observation or unobserved_threads(call.worker_pid)
    return {
        **call.lifecycle_document(),
        "parent_owned_materialization_finished_ns": finished_ns,
        "selected_parent_wall_ns": finished_ns - call.parent_started_ns,
        "thread_budget_evidence": thread_budget_evidence(observation, thread_budget=threads),
        "boundary": _BOUNDARY,
    }


def measure_cold_object(
    project_root: Path,
    manifest: CodecManifest,
    routed: RoutedInput,
    compatibility: CompatibilityPlan,
    parameters: dict[str, Any],
    protocol: MeasurementProtocol,
    *,
    logical_cpus: tuple[int, ...],
    memory_limit_bytes: int,
    threads: int = 1,
    trial_deadline_ns: int | None = None,
    collector_enabled: bool | None = None,
    development_only: bool = False,
    source_reject_fallback: bool = False,
) -> MeasuredColdObservation:
    """Measure one independent cold object; failures preserve actual direction lifecycle."""
    _validate_cold(protocol)
    if (
        type(logical_cpus) is not tuple
        or not logical_cpus
        or any(type(cpu) is not int or cpu < 0 for cpu in logical_cpus)
        or len(set(logical_cpus)) != len(logical_cpus)
    ):
        raise ColdDriverError("cold worker needs unique non-negative allocated logical CPUs")
    if type(threads) is not int or threads < 1 or threads > len(logical_cpus):
        raise ColdDriverError("cold worker thread budget exceeds allocated CPUs")
    if type(memory_limit_bytes) is not int or memory_limit_bytes < 1:
        raise ColdDriverError("cold worker needs a positive declared memory budget")
    if type(development_only) is not bool:
        raise ColdDriverError("development_only must be boolean")
    if type(source_reject_fallback) is not bool:
        raise ColdDriverError("source_reject_fallback must be boolean")
    enabled = (
        protocol.collector_mode == "ENABLED" if collector_enabled is None else collector_enabled
    )
    if type(enabled) is not bool or (
        not development_only and enabled != (protocol.collector_mode == "ENABLED")
    ):
        raise ColdDriverError("collector override is only allowed for matched development probes")
    started = time.perf_counter_ns()
    deadline = started + protocol.max_trial_wall_ns
    if trial_deadline_ns is not None:
        if type(trial_deadline_ns) is not int or trial_deadline_ns <= 0:
            raise ColdDriverError("cold deadline must be a positive PERF_COUNTER_NS integer")
        deadline = min(deadline, trial_deadline_ns)
    canonical_bytes = (routed.canonical_raw_bits + 7) // 8
    options = ColdWorkerResources(enabled, len(logical_cpus), canonical_bytes)
    parent_sampler = _sampler(options)
    parent_sampler.start(started)
    interval = protocol.thread_monitor_interval_ns if enabled else None
    diagnostics: dict[str, Any] = {
        "profile": "COLD_PROCESS",
        "threshold_protocol": protocol.protocol_id,
        "warmup_count": 0,
        "inner_iterations": 1,
        "absolute_trial_deadline_ns": deadline,
        "collector_enabled": enabled,
        "development_only": development_only,
        "source_reject_fallback": source_reject_fallback,
        "measurement_boundary": _BOUNDARY,
        "os_cache_policy": "OS_CACHE_UNCONTROLLED",
        "encode_worker_lifecycle": None,
        "decode_worker_lifecycle": None,
        "same_object_correctness_and_measurement": True,
        "validation_outside_direction_timing": True,
        "parent_started_ns": started,
        "resource_budget": {
            "threads": threads,
            "logical_cpus": list(logical_cpus),
            "memory_limit_bytes": memory_limit_bytes,
            "max_concurrent_worker_processes": 1,
        },
    }
    call = run_isolated(
        _cold_encode_worker,
        project_root,
        manifest.document,
        manifest.key,
        manifest.algorithm_id,
        routed,
        compatibility,
        parameters,
        options,
        source_reject_fallback,
        timeout_seconds=protocol.max_trial_wall_ns / 1e9,
        memory_limit_bytes=memory_limit_bytes,
        cpu_affinity=logical_cpus,
        start_method="spawn",
        thread_monitor_interval_ns=interval,
        deadline_ns=deadline,
    )
    encode_finished = time.perf_counter_ns()
    diagnostics["encode_worker_lifecycle"] = _direction_lifecycle(call, encode_finished, threads)
    if call.status is not RunStatus.PASS or not isinstance(call.value, ColdEncoded):
        parent_sampler.stop(time.perf_counter_ns())
        diagnostics.update(
            exception_type=call.exception_type, message=call.message, failed_direction="encode"
        )
        return MeasuredColdObservation(
            _call_failure(call),
            "COLD_ENCODE_WORKER_FAILED",
            None,
            None,
            None,
            None,
            None,
            False,
            False,
            diagnostics,
        )
    encoding = call.value
    encoded = replace(
        encoding.encoded,
        stream=memoryview(encoding.encoded.stream).tobytes(),
        recovery_context=memoryview(encoding.encoded.recovery_context).tobytes(),
    )
    if hashlib.sha256(encoded.stream).hexdigest() != encoded.stream_sha256:
        raise ExecutionContractError("cold parent stream differs from worker finalized bytes")
    encode_finished = time.perf_counter_ns()
    diagnostics["encode_worker_lifecycle"] = _direction_lifecycle(call, encode_finished, threads)
    context = DecodeContext(encoded.recovery_context)
    call = run_isolated(
        _cold_decode_worker,
        project_root,
        manifest.document,
        manifest.key,
        context.serialized,
        encoded.stream,
        encoded.stream_sha256,
        options,
        source_reject_fallback,
        timeout_seconds=protocol.max_trial_wall_ns / 1e9,
        memory_limit_bytes=memory_limit_bytes,
        cpu_affinity=logical_cpus,
        start_method="spawn",
        thread_monitor_interval_ns=interval,
        deadline_ns=deadline,
    )
    decode_finished = time.perf_counter_ns()
    diagnostics["decode_worker_lifecycle"] = _direction_lifecycle(call, decode_finished, threads)
    if call.status is not RunStatus.PASS or not isinstance(call.value, ColdDecoded):
        parent_sampler.stop(time.perf_counter_ns())
        diagnostics.update(
            exception_type=call.exception_type, message=call.message, failed_direction="decode"
        )
        return MeasuredColdObservation(
            _call_failure(call),
            "COLD_DECODE_WORKER_FAILED",
            encoded,
            None,
            None,
            None,
            None,
            encoding.input_immutable,
            encoding.canary_intact,
            diagnostics,
        )
    decoding = call.value
    decoded = _owned_parent_decoded(decoding.decoded)
    decode_finished = time.perf_counter_ns()
    diagnostics["decode_worker_lifecycle"] = _direction_lifecycle(call, decode_finished, threads)
    diagnostics["independent_recovery"] = {
        "protocol": "PERSISTED_DECODE_CONTEXT_V1",
        "context_sha256": context.sha256,
        "context_document": context.to_document(),
        "required_external_bits": len(context.serialized) * 8,
        "output_materialization": "OWNED_CANONICAL_BUFFERS",
        "qualification": decoding.recovery,
        "qualification_evidence_scope": "SAME_MEASURED_COLD_DECODE_WORKER",
        "parent_output_owned": all(buffer.array.flags.owndata for buffer in decoded.buffers),
    }
    parent_resources = parent_sampler.stop(decode_finished).to_document()
    parent_resources["scope"] = (
        "SUPERVISING_PARENT_DELTA_CPU_LIFETIME_RSS_AND_BOUNDARIES_CHILDREN_EXCLUDED"
    )
    resources = ColdResourceObservation(encoding.resources, decoding.resources, parent_resources)
    cpu_ns = int(
        sum(
            (
                Decimal(item["cumulative_fresh_child"]["total_seconds"])
                for item in (encoding.resources, decoding.resources)
            ),
            Decimal(0),
        )
        * 10**9
    )
    encode_ns = diagnostics["encode_worker_lifecycle"]["selected_parent_wall_ns"]
    decode_ns = diagnostics["decode_worker_lifecycle"]["selected_parent_wall_ns"]
    minimum_satisfied = encode_ns >= protocol.encode_min_ns and decode_ns >= protocol.decode_min_ns
    timing = ColdTimingObservation(
        encode_ns,
        decode_ns,
        canonical_bytes,
        encoding.codec_input_bytes,
        routed.n,
        routed.n * max(1, routed.m) if routed.track.value in {"VALUE", "SYSTEM"} else 0,
        cpu_ns,
        minimum_satisfied,
    )
    correctness = validate_common_correctness(
        routed,
        decoded,
        compatibility,
        loss_mode=compatibility.effective_loss_mode,
        parameters=parameters,
        deterministic_match=None,
        input_immutable=encoding.input_immutable,
        canary_intact=encoding.canary_intact,
        decoded_is_restored=True,
    )
    status = correctness.status
    reason = (
        "COLD_OBJECT_PASS"
        if status is RunStatus.PASS
        else correctness.first_failure_stage or "COLD_CORRECTNESS_FAILED"
    )
    if status is RunStatus.PASS and not minimum_satisfied:
        status, reason = RunStatus.INCOMPARABLE, "COLD_SINGLE_OBJECT_BELOW_FROZEN_DIRECTION_MINIMUM"
    if status is RunStatus.PASS and resources.to_document()["swap_observed"] is True:
        status, reason = RunStatus.RESOURCE_PRESSURE, "SYSTEM_SWAP_OBSERVED_DURING_COLD_OBJECT"
    if status is RunStatus.PASS and any(
        diagnostics[key]["thread_budget_evidence"]["observed_excess"]
        or any(
            value is not None and value > threads
            for value in (
                direction["function_boundary"]["thread_count_before"],
                direction["function_boundary"]["thread_count_after"],
            )
        )
        for key, direction in (
            ("encode_worker_lifecycle", encoding.resources),
            ("decode_worker_lifecycle", decoding.resources),
        )
    ):
        status, reason = RunStatus.OVERSUBSCRIBED, "COLD_OBSERVED_THREADS_EXCEED_FROZEN_BUDGET"
    if time.perf_counter_ns() >= deadline:
        status, reason = RunStatus.TIMEOUT, "COLD_TRIAL_DEADLINE_EXHAUSTED"
    diagnostics["parent_finished_ns"] = time.perf_counter_ns()
    return MeasuredColdObservation(
        status,
        reason,
        encoded,
        decoded,
        timing,
        resources,
        correctness,
        encoding.input_immutable,
        encoding.canary_intact,
        diagnostics,
    )


@dataclass(frozen=True)
class ColdPilotProbe:
    project_root: Path
    manifest: CodecManifest
    routed: RoutedInput
    compatibility: CompatibilityPlan
    parameters: dict[str, Any]
    logical_cpus: tuple[int, ...]
    memory_limit_bytes: int
    threads: int = 1
    source_reject_fallback: bool = False

    def measure(
        self, protocol: MeasurementProtocol, *, collector_enabled: bool, deadline_ns: int
    ) -> MeasuredColdObservation:
        return measure_cold_object(
            self.project_root,
            self.manifest,
            self.routed,
            self.compatibility,
            self.parameters,
            protocol,
            logical_cpus=self.logical_cpus,
            memory_limit_bytes=self.memory_limit_bytes,
            threads=self.threads,
            trial_deadline_ns=deadline_ns,
            collector_enabled=collector_enabled,
            development_only=True,
            source_reject_fallback=self.source_reject_fallback,
        )


def run_cold_pilot(
    protocol: MeasurementProtocol,
    probe: ColdPilotProbe,
    *,
    development_corpus_id: str,
    test_corpus_id: str,
) -> dict[str, Any]:
    """Match the two-direction cold driver without an extra monitored supervisor worker."""
    _validate_cold(protocol)
    if not development_corpus_id or not test_corpus_id or development_corpus_id == test_corpus_id:
        raise ColdDriverError("cold pilot needs a separate development corpus")
    started = time.perf_counter_ns()
    deadline = started + protocol.max_total_wall_ns
    info = time.get_clock_info("perf_counter")
    previous = time.perf_counter_ns()
    ticks = []
    for _ in range(1000):
        current = time.perf_counter_ns()
        if current > previous:
            ticks.append(current - previous)
        previous = current
    clock = {
        "name": protocol.clock,
        "monotonic": info.monotonic,
        "declared_resolution_ns": math.ceil(info.resolution * 10**9),
        "observed_positive_quantum_ns": max(
            1, math.ceil(info.resolution * 10**9), min(ticks) if ticks else 0
        ),
    }
    raw = []
    harness = []
    failure = None
    rng = random.Random(protocol.pilot_seed)
    for index in range(protocol.pilot_repetitions):
        h_start = time.perf_counter_ns()
        time.perf_counter_ns()
        harness.append(time.perf_counter_ns() - h_start)
        modes = ["DISABLED", "ENABLED"]
        rng.shuffle(modes)
        for mode in modes:
            trial_started = time.perf_counter_ns()
            if trial_started >= deadline:
                failure = "PILOT_WALL_BUDGET_EXHAUSTED"
                break
            observation = probe.measure(
                protocol, collector_enabled=mode == "ENABLED", deadline_ns=deadline
            )
            finished = time.perf_counter_ns()
            if observation.timing is None or observation.status is not RunStatus.PASS:
                failure = observation.reason
                raw.append(
                    {
                        "index": index,
                        "collector": mode,
                        "status": observation.status.value,
                        "started_ns": trial_started,
                        "finished_ns": finished,
                        "observation": observation.to_document(),
                    }
                )
                break
            raw.append(
                {
                    "index": index,
                    "collector": mode,
                    "status": observation.status.value,
                    "started_ns": trial_started,
                    "finished_ns": finished,
                    "call_wall_ns": finished - trial_started,
                    "inner_iterations": 1,
                    "encode_ns": observation.timing.encode_ns,
                    "decode_ns": observation.timing.decode_ns,
                    "observation": observation.to_document(),
                }
            )
        if failure:
            break
    successful = [item for item in raw if item["status"] == "PASS"]
    complete = len(successful) == protocol.pilot_repetitions * 2
    if time.perf_counter_ns() >= deadline:
        failure = failure or "PILOT_WALL_BUDGET_EXHAUSTED"
    metrics = _pilot_metrics(
        protocol, successful, harness, clock, complete=complete, failure=failure
    )
    document = decimal_observations(
        {
            "schema_version": "tscb.cold-measurement-pilot.v3.2",
            "protocol_id": protocol.protocol_id,
            "development_corpus_id": development_corpus_id,
            "test_corpus_id": test_corpus_id,
            "raw": raw,
            "harness_probe_wall_ns": harness,
            "clock": clock,
            **metrics,
            "failure": failure,
            "started_ns": started,
            "finished_ns": time.perf_counter_ns(),
            "warmup_count": 0,
            "driver": "TWO_FRESH_SPAWN_DIRECTIONS_PER_INDEPENDENT_OBJECT",
            "probe_identity": {
                "dataset_id": probe.routed.dataset_id,
                "algorithm_id": probe.manifest.algorithm_id,
                "codec_key": probe.manifest.key,
                "parameters": probe.parameters,
                "logical_cpus": list(probe.logical_cpus),
                "threads": probe.threads,
                "memory_limit_bytes": probe.memory_limit_bytes,
                "source_reject_fallback": probe.source_reject_fallback,
            },
            "harness_boundary": "PARENT_EXTERNAL_CLOCK_PAIR_NOT_PROCESS_STARTUP_BASELINE",
            "parent_thread_monitor_target": "ACTUAL_ENCODE_AND_DECODE_CHILDREN_ENABLED_MODE_ONLY",
            "overhead_subtracted": False,
            "outer_independence_increased_by_calibration": False,
        }
    )
    return {**document, "pilot_id": stable_id("cold-measurement-pilot-v32", document)}


def _validate_cold_pilot(
    protocol: MeasurementProtocol, document: Mapping[str, Any]
) -> dict[str, Any]:
    _validate_cold(protocol)
    body = {key: value for key, value in document.items() if key != "pilot_id"}
    if (
        document.get("schema_version") != "tscb.cold-measurement-pilot.v3.2"
        or document.get("protocol_id") != protocol.protocol_id
        or document.get("pilot_id") != stable_id("cold-measurement-pilot-v32", body)
    ):
        raise ColdDriverError("cold pilot version, identity or bound protocol mismatch")
    if (
        not isinstance(document["development_corpus_id"], str)
        or not document["development_corpus_id"]
        or not isinstance(document["test_corpus_id"], str)
        or not document["test_corpus_id"]
        or document["development_corpus_id"] == document["test_corpus_id"]
    ):
        raise ColdDriverError("cold pilot development/test content must differ")
    raw = document["raw"]
    if not isinstance(raw, list):
        raise ColdDriverError("cold pilot raw samples must be retained")
    successful = []
    issues = []
    probe_identity = document["probe_identity"]
    for item in raw:
        if item["status"] != "PASS":
            issues.append("COLD_PILOT_ATTEMPT_FAILED")
            continue
        for key in ("encode_ns", "decode_ns", "call_wall_ns", "started_ns", "finished_ns"):
            if type(item[key]) is not int or item[key] <= 0:
                raise ColdDriverError("cold pilot direction/clock values must be positive integers")
        observation = item["observation"]
        timing = observation["timing"]
        diagnostics = observation["diagnostics"]
        lifecycles = [
            diagnostics["encode_worker_lifecycle"],
            diagnostics["decode_worker_lifecycle"],
        ]
        resources = observation["resources"]
        expected_resources = ColdResourceObservation(
            resources["encode"], resources["decode"], resources["parent"]
        ).to_document()
        if resources != expected_resources:
            raise ColdDriverError("cold cumulative child/parent resource projection was changed")
        if (
            observation["status"] != "PASS"
            or item["inner_iterations"] != 1
            or timing["inner_iterations"] != 1
            or timing["selected_encode_wall_ns"] != item["encode_ns"]
            or timing["selected_decode_wall_ns"] != item["decode_ns"]
            or item["finished_ns"] - item["started_ns"] != item["call_wall_ns"]
            or item["encode_ns"] + item["decode_ns"] > item["call_wall_ns"]
            or diagnostics["warmup_count"] != 0
            or diagnostics["inner_iterations"] != 1
            or diagnostics["threshold_protocol"] != protocol.protocol_id
            or diagnostics["collector_enabled"] != (item["collector"] == "ENABLED")
            or diagnostics["development_only"] is not True
            or diagnostics["source_reject_fallback"] != probe_identity["source_reject_fallback"]
            or diagnostics["resource_budget"]
            != {
                "threads": probe_identity["threads"],
                "logical_cpus": probe_identity["logical_cpus"],
                "memory_limit_bytes": probe_identity["memory_limit_bytes"],
                "max_concurrent_worker_processes": 1,
            }
            or not observation["input_immutable"]
            or not observation["canary_intact"]
            or observation["correctness"]["status"] != "PASS"
        ):
            issues.append("COLD_PILOT_OBJECT_BOUNDARY_OR_VALIDATION_INVALID")
        pids = []
        for direction, lifecycle, ns in zip(
            ("encode", "decode"), lifecycles, (item["encode_ns"], item["decode_ns"]), strict=True
        ):
            pid = lifecycle["worker_pid"]
            pids.append(pid)
            if (
                type(pid) is not int
                or pid <= 0
                or pid == lifecycle["parent_pid"]
                or lifecycle["start_method"] != "spawn"
                or not lifecycle["worker_exit_confirmed"]
                or lifecycle["exit_code"] != 0
                or lifecycle["parent_owned_materialization_finished_ns"]
                - lifecycle["parent_started_ns"]
                != ns
                or lifecycle["selected_parent_wall_ns"] != ns
                or lifecycle["boundary"] != _BOUNDARY
                or not item["started_ns"]
                <= lifecycle["parent_started_ns"]
                <= lifecycle["parent_finished_ns"]
                <= lifecycle["parent_owned_materialization_finished_ns"]
                <= item["finished_ns"]
            ):
                issues.append("COLD_PILOT_DIRECTION_FRESH_LIFECYCLE_INVALID")
            monitor = lifecycle["thread_observation"]
            enabled = item["collector"] == "ENABLED"
            interval = protocol.thread_monitor_interval_ns if enabled else None
            if interval is None:
                if monitor != unobserved_threads(pid):
                    issues.append("COLD_PILOT_UNDECLARED_THREAD_MONITOR")
            elif (
                monitor["requested_interval_ns"] != interval
                or monitor["status"] != "OBSERVED"
                or monitor["worker_pid"] != pid
                or monitor["classification"] != "INSTRUMENTED_SAMPLED_LOWER_BOUND"
                or monitor["captures_all_transient_threads"] is not False
                or not monitor["samples"]
            ):
                issues.append("COLD_PILOT_THREAD_MONITOR_NOT_MATCHED")
            budget = thread_budget_evidence(monitor, thread_budget=probe_identity["threads"])
            if lifecycle["thread_budget_evidence"] != budget or budget["observed_excess"]:
                issues.append("COLD_PILOT_THREAD_BUDGET_EXCEEDED_OR_CHANGED")
            if (
                resources[direction]["collector_enabled"] != enabled
                or resources[direction]["function_boundary"]["actual_scope"]
                != ("PROCESS" if enabled else "PROCESS_CPU_ONLY")
                or resources[direction]["function_boundary"]["scope_availability"]
                != ("AVAILABLE" if enabled else "NOT_COLLECTED")
            ):
                issues.append("COLD_PILOT_PROCESS_COLLECTOR_NOT_MATCHED")
        if (
            pids[0] == pids[1]
            or lifecycles[0]["parent_owned_materialization_finished_ns"]
            > lifecycles[1]["parent_started_ns"]
            or lifecycles[0]["absolute_deadline_ns"] != lifecycles[1]["absolute_deadline_ns"]
        ):
            issues.append("COLD_PILOT_DIRECTIONS_REUSE_WORKER_OR_DEADLINE")
        recovery = diagnostics["independent_recovery"]
        context_bytes = canonical_json_bytes(recovery["context_document"])
        qualification = recovery["qualification"]
        accounting = observation["accounting"]
        if (
            recovery["context_sha256"] != hashlib.sha256(context_bytes).hexdigest()
            or recovery["required_external_bits"] != len(context_bytes) * 8
            or qualification["decode_context_sha256"] != recovery["context_sha256"]
            or qualification["stream_sha256"] != observation["bitstream_sha256"]
            or qualification["worker_pid"] != pids[1]
            or qualification["start_method"] != "spawn"
            or qualification["original_input_available"] is not False
            or qualification["encoder_session_available"] is not False
            or qualification["output_owned_in_worker"] is not True
            or recovery["parent_output_owned"] is not True
            or accounting["external_side_information_bits"] < len(context_bytes) * 8
            or accounting["final_bits"]
            != accounting["serialized_bits"] + accounting["external_side_information_bits"]
            or accounting["serialized_bits"] != accounting["final_physical_bytes"] * 8
        ):
            issues.append("COLD_PILOT_INDEPENDENT_OWNED_RECOVERY_OR_COST_INVALID")
        successful.append(item)
    rng = random.Random(protocol.pilot_seed)
    expected = []
    for index in range(protocol.pilot_repetitions):
        modes = ["DISABLED", "ENABLED"]
        rng.shuffle(modes)
        expected.extend((index, mode) for mode in modes)
    complete = len(successful) == protocol.pilot_repetitions * 2
    if complete and [(item["index"], item["collector"]) for item in raw] != expected:
        issues.append("COLD_PILOT_PAIRED_ORDER_INVALID")
    clock = document["clock"]
    if (
        clock["name"] != protocol.clock
        or clock["monotonic"] is not True
        or type(clock["observed_positive_quantum_ns"]) is not int
        or clock["observed_positive_quantum_ns"] < max(1, clock["declared_resolution_ns"])
    ):
        raise ColdDriverError("cold pilot clock evidence is invalid")
    metrics = _pilot_metrics(
        protocol,
        successful,
        document["harness_probe_wall_ns"],
        clock,
        complete=complete,
        failure=document["failure"],
    )
    if any(document[key] != value for key, value in metrics.items()):
        raise ColdDriverError("cold pilot raw admission gates were changed")
    if (
        document["finished_ns"] - document["started_ns"] >= protocol.max_total_wall_ns
        or document["warmup_count"] != 0
        or document["overhead_subtracted"] is not False
        or document["outer_independence_increased_by_calibration"] is not False
    ):
        issues.append("COLD_PILOT_BUDGET_OR_BOUNDARY_INVALID")
    issues.extend(metrics["reasons"])
    return {
        "eligible": not issues,
        "status": "PASS" if not issues else "INCONCLUSIVE",
        "reasons": list(dict.fromkeys(issues)),
        "pilot_id": document["pilot_id"],
        "recomputed_metrics": metrics,
    }


def validate_cold_pilot_evidence(
    protocol: MeasurementProtocol,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild cold admission from actual fresh direction and resource evidence."""
    try:
        return _validate_cold_pilot(protocol, document)
    except ColdDriverError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise ColdDriverError(f"malformed cold pilot evidence: {error}") from error
