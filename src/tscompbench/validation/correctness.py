from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.codecs import CompatibilityPlan
from tscompbench.contracts import AdapterOperationKind, LossMode, RunStatus
from tscompbench.execution.protocol import DecodedOutput, EncodedArtifact, RoutedInput
from tscompbench.execution.recovery import DecodeContext, restore_decoded_output

from .lossy import (
    LossValidationError,
    LossValidationReport,
    profile_unbounded_loss,
    validate_error_bound,
)
from .task_validators import TaskValidationError, TaskValidationRequest, validate_registered_task


@dataclass(frozen=True)
class CorrectnessReport:
    status: RunStatus
    first_failure_stage: str | None
    checks: tuple[str, ...]
    diagnostics: dict[str, Any]
    loss: LossValidationReport | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.correctness-report.v2",
            "status": self.status,
            "first_failure_stage": self.first_failure_stage,
            "checks": self.checks,
            "diagnostics": self.diagnostics,
            "loss": None if self.loss is None else self.loss.to_document(),
        }


def _value_validity(original: RoutedInput) -> dict[str, np.ndarray[Any]] | None:
    mask = original.validity_reference
    if mask is None:
        return None
    values = {item.name: item.array for item in original.buffers if item.name.startswith("value/")}
    if not values:
        return None
    if mask.dtype != np.bool_:
        raise TaskValidationError("validity must be a boolean logical mask")
    result: dict[str, np.ndarray[Any]] = {}
    for index, (name, value) in enumerate(values.items()):
        if mask.shape == value.shape and len(values) == 1:
            selected = mask
        elif mask.shape == (original.n,):
            selected = np.broadcast_to(
                mask.reshape((original.n,) + (1,) * (value.ndim - 1)), value.shape
            )
        elif (
            len(values) > 1
            and mask.shape == (original.n, len(values))
            and value.shape == (original.n,)
        ):
            selected = mask[:, index]
        else:
            raise TaskValidationError(
                "validity mapping requires an explicit compatible row/cell shape"
            )
        result[name] = selected
    return result


def validate_common_correctness(
    original: RoutedInput,
    decoded: DecodedOutput,
    compatibility: CompatibilityPlan,
    *,
    loss_mode: LossMode,
    parameters: dict[str, Any],
    deterministic_match: bool | None,
    input_immutable: bool,
    canary_intact: bool,
    decode_context: DecodeContext | None = None,
    decoded_is_restored: bool = False,
    null_recovery_contract: str = "BITWISE",
    task_validator_id: str | None = None,
    validation_contract: dict[str, Any] | None = None,
    encoded_artifact: EncodedArtifact | None = None,
) -> CorrectnessReport:
    checks: list[str] = []
    diagnostics: dict[str, Any] = {}
    expected = {item.name: item for item in original.buffers}
    if null_recovery_contract not in {"BITWISE", "SEMANTIC"}:
        return CorrectnessReport(RunStatus.CORRECTNESS_FAIL, "NULL_RECOVERY_CONTRACT", (), {})
    try:
        value_validity = _value_validity(original)
    except TaskValidationError as error:
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL, "VALIDITY_MAPPING", (), {"message": str(error)}
        )
    try:
        observed = decoded.by_name()
    except Exception as error:
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL,
            "DECODED_BUFFER_IDENTITY",
            tuple(checks),
            {"message": str(error)},
        )
    if loss_mode is LossMode.SUMMARY_ONLY:
        if not input_immutable or not canary_intact:
            return CorrectnessReport(
                RunStatus.MEMORY_SAFETY_FAIL,
                "SUMMARY_INPUT_OR_OUTPUT_SAFETY",
                tuple(checks),
                {},
            )
        if deterministic_match is False:
            return CorrectnessReport(RunStatus.NONDETERMINISTIC, "DETERMINISM", (), {})
        if task_validator_id is None:
            return CorrectnessReport(
                RunStatus.UNSUPPORTED,
                "OUTPUT_PROPERTY_VALIDATOR_UNAVAILABLE",
                ("INPUT_IMMUTABILITY", "OUTPUT_CANARY"),
                {"summary_buffer_names": tuple(observed)},
            )
        try:
            result = validate_registered_task(
                task_validator_id,
                str(loss_mode),
                TaskValidationRequest(
                    {
                        name: item.array
                        for name, item in expected.items()
                        if name.startswith("value/")
                    },
                    {name: item.array for name, item in observed.items()},
                    validation_contract or {},
                    encoded_artifact,
                    original.timestamp_reference,
                    value_validity,
                    original.canonical_raw_bits,
                ),
            )
        except (TaskValidationError, LossValidationError) as error:
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "OUTPUT_PROPERTY_VALIDATOR_CONTRACT",
                (),
                {"message": str(error)},
            )
        return CorrectnessReport(
            RunStatus.PASS if result.passed else RunStatus.CORRECTNESS_FAIL,
            result.reason,
            ("INPUT_IMMUTABILITY", "OUTPUT_CANARY", *result.checks),
            {"task_validator_id": task_validator_id, **result.diagnostics},
            result.loss,
        )
    if tuple(expected) != tuple(observed):
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL,
            "CHANNEL_ENTITY_FEATURE_ORDER",
            tuple(checks),
            {"expected": tuple(expected), "observed": tuple(observed)},
        )
    checks.append("CHANNEL_ENTITY_FEATURE_ORDER")

    if not decoded_is_restored:
        if compatibility.operations and decode_context is None:
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "DECODE_CONTEXT_REQUIRED",
                tuple(checks),
                {},
            )
        if decode_context is not None:
            try:
                observed = restore_decoded_output(decoded, decode_context).by_name()
            except Exception as error:
                return CorrectnessReport(
                    RunStatus.CORRECTNESS_FAIL,
                    "DECODE_CONTEXT_RESTORE",
                    tuple(checks),
                    {"message": str(error)},
                )

    restored: dict[str, np.ndarray[Any]] = {}
    for name, expected_buffer in expected.items():
        actual = observed[name].array
        if actual.shape != expected_buffer.array.shape:
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "DECODED_LENGTH_SHAPE",
                tuple(checks),
                {"buffer": name, "expected": expected_buffer.array.shape, "actual": actual.shape},
            )
        restored[name] = actual
    checks.append("DECODED_LENGTH_SHAPE")

    timestamp_names = [name for name in expected if name == "timestamp"]
    for name in timestamp_names:
        if expected[name].array.dtype.str != restored[name].dtype.str or (
            expected[name].array.tobytes(order="C") != restored[name].tobytes(order="C")
        ):
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "TIMESTAMP_EXACT_ORDER_UNIT_EPOCH",
                tuple(checks),
                {"buffer": name},
            )
    checks.append("TIMESTAMP_EXACT_ORDER_UNIT_EPOCH")

    value_names = [name for name in expected if name.startswith("value/")]
    validity_names = [name for name in expected if name == "validity"]
    if value_names and original.validity_reference is not None and not validity_names:
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL, "VALIDITY_OUTPUT_REQUIRED", tuple(checks), {}
        )
    for name in validity_names:
        if expected[name].array.dtype != restored[name].dtype or expected[name].array.tobytes(
            order="C"
        ) != restored[name].tobytes(order="C"):
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL, "VALIDITY_EXACT", tuple(checks), {"buffer": name}
            )
    checks.append("VALIDITY_EXACT")
    if loss_mode is LossMode.LOSSLESS:
        for name in value_names:
            wanted = expected[name].array
            actual = restored[name]
            if actual.dtype != wanted.dtype:
                return CorrectnessReport(
                    RunStatus.CORRECTNESS_FAIL,
                    "VALUE_DTYPE",
                    tuple(checks),
                    {"buffer": name, "expected": wanted.dtype.str, "actual": actual.dtype.str},
                )
            if null_recovery_contract == "SEMANTIC" and value_validity is not None:
                wanted, actual = wanted[value_validity[name]], actual[value_validity[name]]
            if wanted.tobytes(order="C") != actual.tobytes(order="C"):
                stage = (
                    "FLOAT_IEEE_BITS"
                    if np.issubdtype(wanted.dtype, np.floating)
                    else "INTEGER_EXACT_SIGNEDNESS_OVERFLOW"
                )
                return CorrectnessReport(
                    RunStatus.CORRECTNESS_FAIL,
                    stage,
                    tuple(checks),
                    {"buffer": name},
                )
        checks.extend(("INTEGER_EXACT_SIGNEDNESS_OVERFLOW", "FLOAT_IEEE_BITS"))

    if (
        null_recovery_contract == "BITWISE"
        and value_validity is not None
        and loss_mode is not LossMode.LOSSLESS
    ):
        for name in value_names:
            invalid = ~value_validity[name]
            if expected[name].array[invalid].tobytes() != restored[name][invalid].tobytes():
                return CorrectnessReport(
                    RunStatus.CORRECTNESS_FAIL, "NULL_PAYLOAD_BITS", tuple(checks), {"buffer": name}
                )

    row_counts = {int(array.shape[0]) for array in restored.values() if array.ndim}
    if row_counts and row_counts != {original.n}:
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL,
            "T_V_PAIRING",
            tuple(checks),
            {"row_counts": sorted(row_counts), "expected_n": original.n},
        )
    checks.extend(("T_V_PAIRING", "REBUILD_PROTOCOL"))

    if deterministic_match is False:
        return CorrectnessReport(
            RunStatus.NONDETERMINISTIC,
            "DETERMINISM",
            tuple(checks),
            {"message": "adapter declared deterministic but streams differed"},
        )
    if deterministic_match is not None:
        checks.append("DETERMINISM")
    if not input_immutable:
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL,
            "INPUT_IMMUTABILITY",
            tuple(checks),
            {},
        )
    checks.append("INPUT_IMMUTABILITY")
    if not canary_intact:
        return CorrectnessReport(
            RunStatus.MEMORY_SAFETY_FAIL,
            "OUTPUT_CANARY",
            tuple(checks),
            {},
        )
    checks.append("OUTPUT_CANARY")

    loss: LossValidationReport | None = None
    if loss_mode is LossMode.ERROR_BOUNDED_LOSSY:
        loss = validate_error_bound(
            {name: expected[name].array for name in value_names},
            {name: restored[name] for name in value_names},
            error_bound_type=str(parameters.get("error_bound_type", "ABSOLUTE")),
            error_bound=str(parameters.get("error_bound", "0")),
            error_aggregation_mode=str(parameters.get("error_aggregation_mode", "PER_CHANNEL")),
            relative_error_zero_threshold=str(parameters.get("relative_error_zero_threshold", "0")),
            timestamp=original.timestamp_reference,
            validity=value_validity,
        )
        checks.append("LOSS_ERROR_BOUND")
        if not loss.bound_passed:
            return CorrectnessReport(
                RunStatus.BOUND_VIOLATION,
                "LOSS_ERROR_BOUND",
                tuple(checks),
                {"raw_violation_count": loss.raw_violation_count},
                loss,
            )
    elif loss_mode is LossMode.UNBOUNDED_LOSSY:
        for name in value_names:
            converted_dtype = expected[name].array.dtype
            index = tuple(expected).index(name)
            for operation in compatibility.operations:
                if operation.kind in {
                    AdapterOperationKind.EXACT_WIDEN,
                    AdapterOperationKind.LOSSY_CAST,
                }:
                    converted_dtype = np.dtype(operation.after_descriptor["dtype_vector"][index])
            if converted_dtype != restored[name].dtype:
                return CorrectnessReport(
                    RunStatus.CORRECTNESS_FAIL,
                    "LOSSY_FINITE_DTYPE",
                    tuple(checks),
                    {"buffer": name},
                )
        loss = profile_unbounded_loss(
            {name: expected[name].array for name in value_names},
            {name: restored[name] for name in value_names},
            timestamp=original.timestamp_reference,
            validity=value_validity,
        )
        if loss.nonfinite_mismatch_count:
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "NONFINITE_VALUE_MISMATCH",
                tuple(checks),
                {"nonfinite_mismatch_count": loss.nonfinite_mismatch_count},
                loss,
            )
        checks.append("LOSS_QUALITY_PROFILE_NO_ERROR_GUARANTEE")
    elif loss_mode is LossMode.RATE_CONTROLLED_LOSSY:
        if task_validator_id is None:
            return CorrectnessReport(
                RunStatus.UNSUPPORTED,
                "RATE_VALIDATOR_UNAVAILABLE",
                tuple(checks),
                {"message": "actual rate and quality require a dedicated task validator"},
            )
        try:
            result = validate_registered_task(
                task_validator_id,
                str(loss_mode),
                TaskValidationRequest(
                    {name: expected[name].array for name in value_names},
                    {name: restored[name] for name in value_names},
                    validation_contract or {},
                    encoded_artifact,
                    original.timestamp_reference,
                    value_validity,
                    original.canonical_raw_bits,
                ),
            )
        except (TaskValidationError, LossValidationError) as error:
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "RATE_VALIDATOR_CONTRACT",
                tuple(checks),
                {"message": str(error)},
            )
        return CorrectnessReport(
            RunStatus.PASS if result.passed else RunStatus.CORRECTNESS_FAIL,
            result.reason,
            (*checks, *result.checks),
            {"task_validator_id": task_validator_id, **result.diagnostics},
            result.loss,
        )
    return CorrectnessReport(RunStatus.PASS, None, tuple(checks), diagnostics, loss)
