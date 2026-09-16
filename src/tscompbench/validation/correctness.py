from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.codecs import CompatibilityPlan
from tscompbench.contracts import AdapterOperationKind, LossMode, RunStatus
from tscompbench.execution.protocol import DecodedOutput, RoutedInput

from .lossy import LossValidationReport, validate_error_bound


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


def _restore_adapter_view(
    original: np.ndarray[Any], decoded: np.ndarray[Any], plan: CompatibilityPlan
) -> np.ndarray[Any]:
    result = decoded
    for operation in reversed(plan.operations):
        if operation.kind is AdapterOperationKind.TRANSPOSE_COPY and result.ndim >= 2:
            result = result.T
        elif operation.kind is AdapterOperationKind.ENDIANNESS_CONVERSION:
            result = result.byteswap().view(result.dtype.newbyteorder())
        elif operation.kind in {
            AdapterOperationKind.EXACT_WIDEN,
            AdapterOperationKind.LOSSY_CAST,
        }:
            result = result.astype(original.dtype, copy=False)
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
) -> CorrectnessReport:
    checks: list[str] = []
    diagnostics: dict[str, Any] = {}
    expected = {item.name: item for item in original.buffers}
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
        return CorrectnessReport(
            RunStatus.PASS,
            None,
            ("SUMMARY_TRACK_CONFIRMED", "INPUT_IMMUTABILITY", "OUTPUT_CANARY"),
            {
                "reconstruction": "NOT_APPLICABLE_SUMMARY_ONLY",
                "summary_buffer_names": tuple(observed),
            },
        )
    if tuple(expected) != tuple(observed):
        return CorrectnessReport(
            RunStatus.CORRECTNESS_FAIL,
            "CHANNEL_ENTITY_FEATURE_ORDER",
            tuple(checks),
            {"expected": tuple(expected), "observed": tuple(observed)},
        )
    checks.append("CHANNEL_ENTITY_FEATURE_ORDER")

    restored: dict[str, np.ndarray[Any]] = {}
    for name, expected_buffer in expected.items():
        actual = observed[name].array
        actual = _restore_adapter_view(expected_buffer.array, actual, compatibility)
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
        if not np.array_equal(expected[name].array, restored[name]):
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "TIMESTAMP_EXACT_ORDER_UNIT_EPOCH",
                tuple(checks),
                {"buffer": name},
            )
    checks.append("TIMESTAMP_EXACT_ORDER_UNIT_EPOCH")

    value_names = [name for name in expected if name.startswith("value/")]
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

    validity_names = [name for name in expected if name == "validity"]
    for name in validity_names:
        if expected[name].array.tobytes(order="C") != restored[name].tobytes(order="C"):
            return CorrectnessReport(
                RunStatus.CORRECTNESS_FAIL,
                "VALIDITY_EXACT",
                tuple(checks),
                {"buffer": name},
            )
    checks.append("VALIDITY_EXACT")

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
    elif loss_mode is LossMode.RATE_CONTROLLED_LOSSY:
        diagnostics["rate_gate"] = "DEFERRED_TO_RATE_PROFILE_WITH_ACTUAL_FINAL_BITS"
        checks.append("RATE_TARGET_RECORDED")
    return CorrectnessReport(RunStatus.PASS, None, tuple(checks), diagnostics, loss)
