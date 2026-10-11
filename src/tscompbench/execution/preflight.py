from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tscompbench.adapters.compatibility import CompatibilityDomainError
from tscompbench.codecs import CodecManifest
from tscompbench.contracts import RunStatus
from tscompbench.datasets.canonical import CanonicalArtifact
from tscompbench.ids import canonical_json_bytes
from tscompbench.planning import BenchmarkTask
from tscompbench.preprocess.runtime import reviewed_pipeline_executor, validate_pipeline_stages
from tscompbench.validation import (
    BoundarySuiteReport,
    CorrectnessReport,
    InputValidationReport,
    run_boundary_suite,
    validate_common_correctness,
    validate_routed_input,
)

from .isolation import run_isolated
from .preparation import PreparedExecutionInput, prepare_execution_input
from .protocol import CodecAdapter
from .recovery import DecodeContext, bind_decode_context, decode_in_fresh_worker
from .repetition import RoundTripObservation, perform_roundtrip
from .routing import hash_logical_buffers, route_canonical_artifact


@dataclass(frozen=True)
class PreflightResult:
    status: RunStatus
    reason_code: str
    eligible_for_formal_repetitions: bool
    input_validation: InputValidationReport | None
    boundary: BoundarySuiteReport | None
    correctness: CorrectnessReport | None
    accounting: dict[str, Any] | None
    bitstream_sha256: str | None
    diagnostics: dict[str, Any]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.preflight-result.v2",
            "status": self.status,
            "reason_code": self.reason_code,
            "eligible_for_formal_repetitions": self.eligible_for_formal_repetitions,
            "input_validation": (
                None if self.input_validation is None else self.input_validation.to_document()
            ),
            "boundary": None if self.boundary is None else self.boundary.to_document(),
            "correctness": (None if self.correctness is None else self.correctness.to_document()),
            "accounting": self.accounting,
            "bitstream_sha256": self.bitstream_sha256,
            "diagnostics": self.diagnostics,
        }


def _failure(
    status: RunStatus,
    reason: str,
    *,
    input_validation: InputValidationReport | None = None,
    boundary: BoundarySuiteReport | None = None,
    correctness: CorrectnessReport | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> PreflightResult:
    return PreflightResult(
        status,
        reason,
        False,
        input_validation,
        boundary,
        correctness,
        None,
        None,
        diagnostics or {},
    )


def _source_gate(source: dict[str, Any]) -> tuple[RunStatus, str] | None:
    availability = source.get("availability")
    if availability is not None and availability != "AVAILABLE":
        return RunStatus.SOURCE_INCOMPLETE, f"SOURCE_{availability}"
    license_record = source.get("license", {})
    license_status = license_record.get("status")
    if source.get("kind") != "BUILTIN_HARNESS" and license_status is None:
        return RunStatus.LICENSE_RESTRICTED, "LICENSE_STATUS_UNSPECIFIED"
    if license_status == "BLOCKED":
        return RunStatus.LICENSE_RESTRICTED, "LICENSE_BLOCKED"
    if license_status not in {None, "RUN_ALLOWED", "REDISTRIBUTION_RESTRICTED"}:
        return RunStatus.LICENSE_RESTRICTED, f"LICENSE_{license_status}"
    return None


def preflight_task(
    task: BenchmarkTask,
    manifest: CodecManifest,
    source: dict[str, Any],
    artifact: CanonicalArtifact,
    adapter: CodecAdapter,
    parameters: dict[str, Any],
    *,
    cpu_affinity: tuple[int, ...] | None = None,
    deadline_ns: int | None = None,
    capture_directory: Path | None = None,
) -> tuple[PreflightResult, PreparedExecutionInput | None]:
    if deadline_ns is not None and (type(deadline_ns) is not int or deadline_ns <= 0):
        raise ValueError("preflight deadline must be a positive PERF_COUNTER_NS integer")
    if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
        return _failure(
            RunStatus.TIMEOUT,
            "TRIAL_DEADLINE_EXHAUSTED_BEFORE_PREFLIGHT",
            diagnostics={"absolute_deadline_ns": deadline_ns, "worker_launched": False},
        ), None
    if task.status not in {RunStatus.PLANNED, RunStatus.ADAPTER_LOSSY_ROUTED}:
        return _failure(task.status, task.reason_code), None
    source_failure = _source_gate(source)
    if source_failure is not None:
        return _failure(*source_failure), None
    if not task.execution.artifact_sha256 or task.execution.artifact_sha256 == "UNSPECIFIED":
        return _failure(RunStatus.BUILD_UNAVAILABLE, "EXECUTION_ARTIFACT_UNRESOLVED"), None
    if adapter.adapter_id != task.execution.adapter_id:
        return _failure(
            RunStatus.BUILD_UNAVAILABLE,
            "RUNTIME_ADAPTER_ID_MISMATCH",
            diagnostics={
                "planned_adapter_id": task.execution.adapter_id,
                "runtime_adapter_id": adapter.adapter_id,
            },
        ), None
    if not reviewed_pipeline_executor(manifest.document, adapter, task.preprocess, parameters):
        return _failure(
            RunStatus.INCOMPARABLE,
            "PREPROCESS_EXECUTOR_NOT_REGISTERED",
            diagnostics={"preprocess_plan_id": task.preprocess.preprocess_plan_id},
        ), None
    try:
        routed = route_canonical_artifact(artifact, task.track)
        input_validation = validate_routed_input(routed, task)
        max_abs_error = (
            parameters.get("error_bound")
            if task.compatibility.status.value == "ADAPTER_LOSSY"
            else None
        )
        prepared = prepare_execution_input(routed, task.compatibility, max_abs_error=max_abs_error)
    except CompatibilityDomainError as error:
        return _failure(
            RunStatus.UNSUPPORTED,
            error.reason_code,
            diagnostics={"error_type": type(error).__name__, "message": str(error)},
        ), None
    except Exception as error:
        return _failure(
            RunStatus.SCHEMA_ERROR,
            "INPUT_OR_ADAPTER_VALIDATION_FAILED",
            diagnostics={"error_type": type(error).__name__, "message": str(error)},
        ), None

    timeout = float(task.resource_limits["timeout_seconds"])
    memory_limit = int(task.resource_limits["memory_limit_bytes"])
    stage_evidence = None
    if task.preprocess.stages:
        stage_call = run_isolated(
            validate_pipeline_stages,
            adapter,
            prepared.codec_input,
            parameters,
            timeout_seconds=timeout,
            memory_limit_bytes=memory_limit,
            cpu_affinity=cpu_affinity,
            deadline_ns=deadline_ns,
        )
        if stage_call.status is not RunStatus.PASS:
            stage_status = {
                "SourceDomainError": RunStatus.UNSUPPORTED,
                "MemoryError": RunStatus.OOM,
                "PreprocessContractError": RunStatus.CORRECTNESS_FAIL,
            }.get(stage_call.exception_type or "", stage_call.status)
            return _failure(
                stage_status,
                "SOURCE_DOMAIN_UNSUPPORTED"
                if stage_call.exception_type == "SourceDomainError"
                else "PREPROCESS_STAGE_VALIDATION_FAILED",
                input_validation=input_validation,
                diagnostics={
                    "exception_type": stage_call.exception_type,
                    "message": stage_call.message,
                    "exit_code": stage_call.exit_code,
                    "limit_method": stage_call.limit_method,
                    "worker_lifecycle": stage_call.lifecycle_document(),
                },
            ), prepared
        stage_evidence = stage_call.value
    boundary_call = run_isolated(
        run_boundary_suite,
        adapter,
        manifest,
        task.track,
        parameters,
        timeout_seconds=timeout,
        memory_limit_bytes=memory_limit,
        cpu_affinity=cpu_affinity,
        deadline_ns=deadline_ns,
    )
    if boundary_call.status is not RunStatus.PASS:
        return _failure(
            boundary_call.status,
            "BOUNDARY_WORKER_FAILED",
            input_validation=input_validation,
            diagnostics={
                "exception_type": boundary_call.exception_type,
                "message": boundary_call.message,
                "exit_code": boundary_call.exit_code,
                "limit_method": boundary_call.limit_method,
                "worker_lifecycle": boundary_call.lifecycle_document(),
            },
        ), prepared
    boundary = boundary_call.value
    if not isinstance(boundary, BoundarySuiteReport) or not boundary.passed:
        reasons = (
            set()
            if not isinstance(boundary, BoundarySuiteReport)
            else {item.reason for item in boundary.observations if item.status != "PASS"}
        )
        boundary_status = RunStatus.CORRECTNESS_FAIL
        if any(
            "OutputCapacityError" in reason or "BOUND_MINUS_ONE_MEMORY_CONTRACT_FAILED" in reason
            for reason in reasons
        ):
            boundary_status = RunStatus.HARNESS_CAPACITY_ERROR
        elif "BOUND_VIOLATION" in reasons:
            boundary_status = RunStatus.BOUND_VIOLATION
        elif "NONDETERMINISTIC" in reasons:
            boundary_status = RunStatus.NONDETERMINISTIC
        elif any("CANARY" in reason or "MEMORY" in reason for reason in reasons):
            boundary_status = RunStatus.MEMORY_SAFETY_FAIL
        return _failure(
            boundary_status,
            "BOUNDARY_SAFETY_DRY_RUN_FAILED",
            input_validation=input_validation,
            boundary=boundary if isinstance(boundary, BoundarySuiteReport) else None,
        ), prepared

    call = run_isolated(
        perform_roundtrip,
        adapter,
        prepared.codec_input,
        parameters,
        timeout_seconds=timeout,
        memory_limit_bytes=memory_limit,
        cpu_affinity=cpu_affinity,
        deadline_ns=deadline_ns,
    )
    if call.status is not RunStatus.PASS:
        exception_status = {
            "OutputCapacityError": RunStatus.HARNESS_CAPACITY_ERROR,
            "MemoryError": RunStatus.OOM,
            "SourceDomainError": RunStatus.UNSUPPORTED,
        }.get(call.exception_type or "", call.status)
        return _failure(
            exception_status,
            "SOURCE_DOMAIN_UNSUPPORTED"
            if call.exception_type == "SourceDomainError"
            else "MINIMAL_ROUNDTRIP_WORKER_FAILED",
            input_validation=input_validation,
            boundary=boundary,
            diagnostics={
                "exception_type": call.exception_type,
                "message": call.message,
                "exit_code": call.exit_code,
                "limit_method": call.limit_method,
                "worker_lifecycle": call.lifecycle_document(),
            },
        ), prepared
    observation = call.value
    if not isinstance(observation, RoundTripObservation):
        return _failure(
            RunStatus.CRASHED,
            "INVALID_WORKER_RESULT",
            input_validation=input_validation,
            boundary=boundary,
        ), prepared
    correctness = validate_common_correctness(
        prepared.original,
        observation.decoded,
        task.compatibility,
        loss_mode=task.compatibility.effective_loss_mode,
        parameters=parameters,
        deterministic_match=observation.determinism_match,
        input_immutable=(
            observation.input_immutable
            and hash_logical_buffers(prepared.original.buffers) == prepared.original.input_sha256
        ),
        canary_intact=observation.canary_intact,
        decode_context=DecodeContext.from_routed(
            prepared.original,
            task.compatibility,
            adapter_id=adapter.adapter_id,
            parameters=parameters,
        ),
    )
    if correctness.status is not RunStatus.PASS:
        return PreflightResult(
            correctness.status,
            correctness.first_failure_stage or "CORRECTNESS_FAILED",
            False,
            input_validation,
            boundary,
            correctness,
            observation.encoded.ledger.to_document(),
            observation.encoded.stream_sha256,
            {},
        ), prepared
    context = DecodeContext.from_routed(
        prepared.original,
        task.compatibility,
        adapter_id=adapter.adapter_id,
        parameters=parameters,
    )
    encoded = bind_decode_context(observation.encoded, context)
    captured = {}
    if capture_directory is not None:
        capture_directory.mkdir(parents=True, exist_ok=True)
        references = {}
        for name, payload in (("stream.bin", encoded.stream), ("context.json", context.serialized)):
            target = capture_directory / name
            # An earlier attempt is evidence, even if its decoder later failed.
            # Never replace its bytes with a new qualification observation.
            with target.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            references["stream" if name == "stream.bin" else "context"] = {
                "path": str(target.resolve()),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        captured = {
            **references,
            "binding": {
                "task_id": task.task_id,
                "dataset_id": task.dataset_id,
                "algorithm_id": task.algorithm_id,
                "config_id": task.config_id,
                "execution_path_hash": task.execution.execution_path_hash,
                "track": task.track.value,
                "input_sha256": prepared.original.input_sha256,
                "canonical_raw_bits": prepared.original.canonical_raw_bits,
                "adapter_id": adapter.adapter_id,
                "parameters": parameters,
            },
        }
        with (capture_directory / "binding.json").open("xb") as handle:
            handle.write(canonical_json_bytes(captured) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    cold_call = run_isolated(
        decode_in_fresh_worker,
        Path(__file__).resolve().parents[3],
        manifest.document,
        manifest.key,
        context.serialized,
        encoded.stream,
        encoded.stream_sha256,
        type(adapter).__name__ == "SourceRejectCompositeAdapter",
        timeout_seconds=timeout,
        memory_limit_bytes=memory_limit,
        cpu_affinity=cpu_affinity,
        start_method="spawn",
        deadline_ns=deadline_ns,
    )
    if cold_call.status is not RunStatus.PASS:
        return _failure(
            cold_call.status,
            "INDEPENDENT_RECOVERY_WORKER_FAILED",
            input_validation=input_validation,
            boundary=boundary,
            correctness=correctness,
            diagnostics={
                "exception_type": cold_call.exception_type,
                "message": cold_call.message,
                "worker_lifecycle": cold_call.lifecycle_document(),
                "qualification_artifacts": captured,
                "independent_recovery_worker_lifecycle": cold_call.lifecycle_document(),
            },
        ), prepared
    cold_decoded, recovery_evidence = cold_call.value
    cold_correctness = validate_common_correctness(
        prepared.original,
        cold_decoded,
        task.compatibility,
        loss_mode=task.compatibility.effective_loss_mode,
        parameters=parameters,
        deterministic_match=None,
        input_immutable=True,
        canary_intact=True,
        decoded_is_restored=True,
    )
    if cold_correctness.status is not RunStatus.PASS:
        return _failure(
            cold_correctness.status,
            "INDEPENDENT_RECOVERY_VALIDATION_FAILED",
            input_validation=input_validation,
            boundary=boundary,
            correctness=cold_correctness,
            diagnostics={
                "independent_recovery": recovery_evidence,
                "qualification_artifacts": captured,
                "independent_recovery_worker_lifecycle": cold_call.lifecycle_document(),
            },
        ), prepared
    if deadline_ns is not None and time.perf_counter_ns() >= deadline_ns:
        return _failure(
            RunStatus.TIMEOUT,
            "TRIAL_DEADLINE_EXHAUSTED_DURING_PREFLIGHT_VALIDATION",
            input_validation=input_validation,
            boundary=boundary,
            correctness=cold_correctness,
            diagnostics={
                "absolute_deadline_ns": deadline_ns,
                "independent_recovery": recovery_evidence,
                "qualification_artifacts": captured,
                "independent_recovery_worker_lifecycle": cold_call.lifecycle_document(),
                "deadline_scope": "SHARED_PREFLIGHT_AND_REPETITION_WALL_BOUNDARY",
            },
        ), prepared
    return (
        PreflightResult(
            RunStatus.PASS,
            "PREFLIGHT_PASS",
            True,
            input_validation,
            boundary,
            correctness,
            encoded.ledger.to_document(),
            observation.encoded.stream_sha256,
            {
                "worker_limit_method": call.limit_method,
                "preprocess_stage_validation": stage_evidence,
                "independent_recovery": recovery_evidence,
                "qualification_artifacts": captured,
                "independent_recovery_worker_lifecycle": cold_call.lifecycle_document(),
            },
        ),
        prepared,
    )
