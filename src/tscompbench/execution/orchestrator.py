from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from tscompbench.codecs import CodecManifest
from tscompbench.contracts import RunStatus
from tscompbench.datasets.canonical import CanonicalArtifact
from tscompbench.ids import stable_id
from tscompbench.measurement import (
    MeasurementPolicy,
    WarmupObservation,
    WorkloadObservation,
    build_query_workload,
    execute_query_workload,
    execute_streaming_workload,
    unavailable_workloads,
)
from tscompbench.planning import BenchmarkTask
from tscompbench.storage import RunRecord
from tscompbench.validation import validate_common_correctness

from .isolation import run_isolated
from .preflight import PreflightResult, preflight_task
from .protocol import CodecAdapter
from .repetition import (
    MeasuredRoundTripObservation,
    perform_measured_roundtrip,
    perform_warmup,
)
from .routing import hash_logical_buffers


@dataclass(frozen=True)
class TaskExecutionResult:
    preflight: PreflightResult
    records: tuple[RunRecord, ...]
    bitstreams: tuple[tuple[str, bytes], ...]
    warmup: WarmupObservation | None = None


def _base_record(
    task: BenchmarkTask,
    *,
    run_set_id: str,
    record_kind: str,
    repetition_index: int | None,
    status: RunStatus,
    reason_code: str,
    benchmark_eligible: bool,
    **values: Any,
) -> RunRecord:
    return RunRecord.create(
        run_set_id=run_set_id,
        task_id=task.task_id,
        dataset_id=task.dataset_id,
        algorithm_id=task.algorithm_id,
        config_id=task.config_id,
        execution_path_hash=task.execution.execution_path_hash,
        semantic_comparability_key=task.comparability.semantic_key,
        execution_comparability_key=task.comparability.execution_key,
        resource_profile_key=task.comparability.resource_key,
        track=task.track,
        record_kind=record_kind,
        repetition_index=repetition_index,
        status=status,
        reason_code=reason_code,
        benchmark_eligible=benchmark_eligible,
        **values,
    )


def _worker_failure_status(
    status: RunStatus, exception_type: str | None, message: str | None
) -> RunStatus:
    if exception_type == "OutputCapacityError":
        return RunStatus.HARNESS_CAPACITY_ERROR
    if exception_type == "MemoryError":
        return RunStatus.OOM
    if message and "max_inner_iterations" in message:
        return RunStatus.RESOURCE_PRESSURE
    return status


def execute_task(
    *,
    run_set_id: str,
    task: BenchmarkTask,
    manifest: CodecManifest,
    source: dict[str, Any],
    artifact: CanonicalArtifact,
    adapter: CodecAdapter,
    parameters: dict[str, Any],
    measurement_policy: MeasurementPolicy,
    repetitions: int = 1,
    repetition_indices: tuple[int, ...] | None = None,
    event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    record_callback: Callable[[RunRecord, bytes | None], None] | None = None,
) -> TaskExecutionResult:
    if repetitions < 1:
        raise ValueError("Layer 3 requires at least one formal qualification repetition")
    benchmark_eligible = (
        source.get("kind") != "BUILTIN_HARNESS" and measurement_policy.measurement_mode == "FORMAL"
    )
    preflight, prepared = preflight_task(
        task,
        manifest,
        source,
        artifact,
        adapter,
        parameters,
        cpu_affinity=task.execution.cpu_affinity,
    )
    if event_callback is not None:
        event_callback(
            "TASK_PREFLIGHT_PASS"
            if preflight.eligible_for_formal_repetitions
            else "TASK_PREFLIGHT_FAILED",
            {
                "task_id": task.task_id,
                "status": preflight.status,
                "reason_code": preflight.reason_code,
            },
        )
    if not preflight.eligible_for_formal_repetitions or prepared is None:
        record = _base_record(
            task,
            run_set_id=run_set_id,
            record_kind="DIAGNOSTIC",
            repetition_index=None,
            status=preflight.status,
            reason_code=preflight.reason_code,
            benchmark_eligible=False,
            input_sha256=(
                None
                if preflight.input_validation is None
                else preflight.input_validation.input_sha256
            ),
            bitstream_sha256=preflight.bitstream_sha256,
            correctness=preflight.correctness,
            diagnostics={"preflight": preflight.to_document()},
        )
        if record_callback is not None:
            record_callback(record, None)
        return TaskExecutionResult(preflight, (record,), (), None)

    if event_callback is not None:
        event_callback(
            "TASK_WARMING",
            {
                "task_id": task.task_id,
                "minimum_count": measurement_policy.warmup_min_count,
                "minimum_seconds": measurement_policy.warmup_min_seconds,
            },
        )
    warmup_call = run_isolated(
        perform_warmup,
        adapter,
        prepared.original,
        task.compatibility,
        parameters,
        measurement_policy,
        timeout_seconds=float(task.resource_limits["timeout_seconds"]),
        memory_limit_bytes=int(task.resource_limits["memory_limit_bytes"]),
        cpu_affinity=task.execution.cpu_affinity,
    )
    if warmup_call.status is not RunStatus.PASS or not isinstance(
        warmup_call.value, WarmupObservation
    ):
        status = _worker_failure_status(
            warmup_call.status, warmup_call.exception_type, warmup_call.message
        )
        record = _base_record(
            task,
            run_set_id=run_set_id,
            record_kind="DIAGNOSTIC",
            repetition_index=None,
            status=status,
            reason_code="WARMUP_FAILED",
            benchmark_eligible=False,
            input_sha256=prepared.original.input_sha256,
            diagnostics={
                "exception_type": warmup_call.exception_type,
                "message": warmup_call.message,
                "exit_code": warmup_call.exit_code,
                "limit_method": warmup_call.limit_method,
            },
        )
        if record_callback is not None:
            record_callback(record, None)
        return TaskExecutionResult(preflight, (record,), (), None)
    warmup = warmup_call.value
    if event_callback is not None:
        event_callback(
            "TASK_WARMUP_COMPLETED",
            {"task_id": task.task_id, **warmup.to_document()},
        )

    records: list[RunRecord] = []
    streams: list[tuple[str, bytes]] = []
    indices = tuple(range(repetitions)) if repetition_indices is None else repetition_indices
    if any(value < 0 for value in indices) or len(indices) != len(set(indices)):
        raise ValueError("repetition_indices must be unique non-negative integers")
    for repetition in indices:
        if event_callback is not None:
            event_callback(
                "REPETITION_RUNNING",
                {"task_id": task.task_id, "repetition_index": repetition},
            )
        call = run_isolated(
            perform_measured_roundtrip,
            adapter,
            prepared.original,
            task.compatibility,
            parameters,
            measurement_policy,
            timeout_seconds=float(task.resource_limits["timeout_seconds"]),
            memory_limit_bytes=int(task.resource_limits["memory_limit_bytes"]),
            cpu_affinity=task.execution.cpu_affinity,
        )
        if call.status is not RunStatus.PASS or not isinstance(
            call.value, MeasuredRoundTripObservation
        ):
            status = _worker_failure_status(call.status, call.exception_type, call.message)
            record = _base_record(
                task,
                run_set_id=run_set_id,
                record_kind="FORMAL_REPETITION",
                repetition_index=repetition,
                status=status,
                reason_code="FORMAL_REPETITION_WORKER_FAILED",
                benchmark_eligible=False,
                input_sha256=prepared.original.input_sha256,
                diagnostics={
                    "exception_type": call.exception_type,
                    "message": call.message,
                    "exit_code": call.exit_code,
                    "limit_method": call.limit_method,
                },
            )
            records.append(record)
            if record_callback is not None:
                record_callback(record, None)
            if event_callback is not None:
                event_callback(
                    "REPETITION_TERMINAL",
                    {
                        "task_id": task.task_id,
                        "repetition_index": repetition,
                        "status": status,
                    },
                )
            continue
        observation = call.value
        if event_callback is not None:
            event_callback(
                "REPETITION_VALIDATING",
                {"task_id": task.task_id, "repetition_index": repetition},
            )
        correctness = validate_common_correctness(
            prepared.original,
            observation.decoded,
            task.compatibility,
            loss_mode=task.compatibility.effective_loss_mode,
            parameters=parameters,
            deterministic_match=observation.determinism_match,
            input_immutable=(
                observation.input_immutable
                and hash_logical_buffers(prepared.original.buffers)
                == prepared.original.input_sha256
            ),
            canary_intact=observation.canary_intact,
        )
        status = correctness.status
        resource_reason: str | None = None
        if status is RunStatus.PASS and observation.resources.swap_observed is True:
            status = RunStatus.RESOURCE_PRESSURE
            resource_reason = "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
        observed_threads = observation.resources.thread_count_after
        thread_budget = measurement_policy.threads * measurement_policy.processes
        if (
            status is RunStatus.PASS
            and observed_threads is not None
            and observed_threads > thread_budget
        ):
            status = RunStatus.OVERSUBSCRIBED
            resource_reason = "OBSERVED_THREADS_EXCEED_FROZEN_BUDGET"
        if event_callback is not None:
            event_callback(
                "REPETITION_ACCOUNTING_VERIFIED",
                {
                    "task_id": task.task_id,
                    "repetition_index": repetition,
                    "final_bits": observation.encoded.ledger.final_bits,
                },
            )
        reason = (
            "FORMAL_REPETITION_PASS"
            if status is RunStatus.PASS
            else resource_reason or correctness.first_failure_stage or "FORMAL_VALIDATION_FAILED"
        )
        query_workload_id = None
        query_requests = ()
        if measurement_policy.query_workload:
            query_requests = build_query_workload(
                n=prepared.original.n,
                m=max(1, prepared.original.m),
                seed=measurement_policy.seed,
                query_count=measurement_policy.query_count,
            )
            query_workload_id = stable_id(
                "query-workload",
                {
                    "seed": measurement_policy.seed,
                    "requests": query_requests,
                    "dataset_id": prepared.original.dataset_id,
                },
            )
        workloads = unavailable_workloads(
            features=manifest.document["features"],
            query_requested=measurement_policy.query_workload,
            streaming_requested=measurement_policy.streaming_workload,
            query_workload_id=query_workload_id,
        )
        if (
            measurement_policy.query_workload
            and bool(
                manifest.document["features"].get("query")
                or manifest.document["features"].get("random_access")
            )
            and query_workload_id is not None
        ):
            query_call = run_isolated(
                execute_query_workload,
                adapter=adapter,
                parameters=parameters,
                stream=observation.encoded.stream,
                routed=prepared.original,
                requests=query_requests,
                workload_id=query_workload_id,
                index_bits=observation.encoded.ledger.index_bits,
                timeout_seconds=float(task.resource_limits["timeout_seconds"]),
                memory_limit_bytes=int(task.resource_limits["memory_limit_bytes"]),
                cpu_affinity=task.execution.cpu_affinity,
            )
            if query_call.status is RunStatus.PASS and isinstance(query_call.value, dict):
                query_document = query_call.value
            else:
                query_document = {
                    "status": query_call.status,
                    "reason": "QUERY_WORKER_FAILED",
                    "workload_id": query_workload_id,
                    "exception_type": query_call.exception_type,
                    "message": query_call.message,
                    "latency_ns": None,
                    "decode_amplification": None,
                    "read_amplification": None,
                    "correctness": None,
                }
                if status is RunStatus.PASS:
                    status = RunStatus.INCOMPARABLE
                    reason = "QUERY_WORKLOAD_FAILED"
            workloads = WorkloadObservation(
                query=query_document,
                streaming=workloads.streaming,
            )
        if measurement_policy.streaming_workload and bool(
            manifest.document["features"].get("streaming")
        ):
            streaming_call = run_isolated(
                execute_streaming_workload,
                adapter=adapter,
                parameters=parameters,
                routed=prepared.original,
                compatibility=task.compatibility,
                block_size=int(parameters.get("block_size", max(1, prepared.original.n))),
                timeout_seconds=float(task.resource_limits["timeout_seconds"]),
                memory_limit_bytes=int(task.resource_limits["memory_limit_bytes"]),
                cpu_affinity=task.execution.cpu_affinity,
            )
            if streaming_call.status is RunStatus.PASS and isinstance(streaming_call.value, dict):
                streaming_document = streaming_call.value
            else:
                streaming_document = {
                    "status": streaming_call.status,
                    "reason": "STREAMING_WORKER_FAILED",
                    "exception_type": streaming_call.exception_type,
                    "message": streaming_call.message,
                    "first_output_latency_ns": None,
                    "block_latency_ns": None,
                    "lookahead_elements": None,
                    "buffer_bytes": None,
                    "state_bytes": None,
                    "checkpoint_bits": None,
                    "reset_overhead_ns": None,
                    "backpressure_policy": None,
                }
                if status is RunStatus.PASS:
                    status = RunStatus.INCOMPARABLE
                    reason = "STREAMING_WORKLOAD_FAILED"
            workloads = WorkloadObservation(
                query=workloads.query,
                streaming=streaming_document,
            )
        record = _base_record(
            task,
            run_set_id=run_set_id,
            record_kind="FORMAL_REPETITION",
            repetition_index=repetition,
            status=status,
            reason_code=reason,
            benchmark_eligible=benchmark_eligible,
            input_sha256=prepared.original.input_sha256,
            bitstream_sha256=observation.encoded.stream_sha256,
            finalize_bytes=observation.encoded.finalize_bytes,
            timing=observation.timing.to_document(),
            resources=observation.resources.to_document(),
            workloads=workloads.to_document(),
            accounting=observation.encoded.ledger,
            correctness=correctness,
            diagnostics={
                "adapter_telemetry": prepared.telemetry.__dict__,
                "worker_limit_method": call.limit_method,
                "same_repetition_correctness_and_measurement": True,
                "measurement_policy": measurement_policy.to_document(),
                "resource_measurement_eligible": (
                    observation.resources.scope_availability == "AVAILABLE"
                ),
                "lifecycle_trace": observation.lifecycle_trace,
            },
        )
        records.append(record)
        streams.append((record.run_id, observation.encoded.stream))
        if record_callback is not None:
            record_callback(record, observation.encoded.stream)
        if event_callback is not None:
            event_callback(
                "REPETITION_TERMINAL",
                {
                    "task_id": task.task_id,
                    "repetition_index": repetition,
                    "status": status,
                    "run_id": record.run_id,
                },
            )
    return TaskExecutionResult(preflight, tuple(records), tuple(streams), warmup)
