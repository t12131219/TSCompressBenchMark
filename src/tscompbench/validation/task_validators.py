"""Independent validators for output-property and rate contracts.

Registering a validator establishes an executable task specification. It does
not register a codec, establish its source fidelity, or qualify its performance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from typing import Any

import numpy as np

from tscompbench.execution.protocol import EncodedArtifact

from .lossy import LossValidationReport, profile_unbounded_loss, validate_error_bound


class TaskValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TaskValidationRequest:
    originals: dict[str, np.ndarray[Any]]
    outputs: dict[str, np.ndarray[Any]]
    contract: dict[str, Any]
    encoded_artifact: EncodedArtifact | None = None
    timestamp: np.ndarray[Any] | None = None
    validity: dict[str, np.ndarray[Any]] | None = None
    canonical_raw_bits: int | None = None


@dataclass(frozen=True)
class TaskValidationResult:
    passed: bool
    reason: str | None
    checks: tuple[str, ...]
    diagnostics: dict[str, Any]
    loss: LossValidationReport | None = None


@dataclass(frozen=True)
class TaskValidatorSpec:
    validator_id: str
    loss_mode: str
    contract_version: str
    validate: Callable[[TaskValidationRequest], TaskValidationResult]


_VALIDATORS: dict[str, TaskValidatorSpec] = {}


def register_task_validator(spec: TaskValidatorSpec) -> None:
    if not spec.validator_id or not spec.contract_version or not callable(spec.validate):
        raise TaskValidationError("validator identity, contract version, and callable are required")
    if spec.loss_mode not in {"SUMMARY_ONLY", "RATE_CONTROLLED_LOSSY"}:
        raise TaskValidationError(
            "only independent summary and rate task validators are registered here"
        )
    if spec.validator_id in _VALIDATORS:
        raise TaskValidationError(f"validator already registered: {spec.validator_id}")
    _VALIDATORS[spec.validator_id] = spec


def validate_registered_task(
    validator_id: str,
    loss_mode: str,
    request: TaskValidationRequest,
) -> TaskValidationResult:
    spec = _VALIDATORS.get(validator_id)
    if spec is None:
        raise TaskValidationError(f"unknown task validator: {validator_id}")
    if spec.loss_mode != loss_mode:
        raise TaskValidationError("validator loss mode differs from the declared task")
    if request.contract.get("schema_version") != spec.contract_version:
        raise TaskValidationError("validator contract version differs from the frozen task")
    result = spec.validate(request)
    if not isinstance(result, TaskValidationResult):
        raise TaskValidationError("validator must return TaskValidationResult")
    return result


def _fraction(value: Any) -> Fraction:
    try:
        if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
            return Fraction(int(value))
        if isinstance(value, (float, np.floating)):
            return Fraction(*value.as_integer_ratio())
        return Fraction(str(value))
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as error:
        raise TaskValidationError("contract numbers must be finite") from error


def _nonnegative(value: Any) -> Fraction:
    result = _fraction(value)
    if result < 0:
        raise TaskValidationError("contract budgets and tolerances must be nonnegative")
    return result


def _valid_values(request: TaskValidationRequest, name: str) -> np.ndarray[Any]:
    if name not in request.originals:
        raise TaskValidationError(f"unknown input property channel: {name}")
    values = request.originals[name]
    if request.validity is None:
        return values.reshape(-1)
    if set(request.validity) != set(request.originals):
        raise TaskValidationError("validity channel identities differ")
    mask = request.validity[name]
    if mask.dtype != np.bool_ or mask.shape != values.shape:
        raise TaskValidationError("validity masks must be boolean and shape matched")
    return values[mask]


def _scalar_summary(request: TaskValidationRequest) -> TaskValidationResult:
    if set(request.contract) != {"schema_version", "properties"}:
        raise TaskValidationError("summary contract contains missing or unknown fields")
    properties = request.contract["properties"]
    if not isinstance(properties, list) or not properties:
        raise TaskValidationError("summary contract requires a nonempty property list")
    expected_outputs: set[str] = set()
    failures: list[dict[str, Any]] = []
    for item in properties:
        if set(item) != {"input", "output", "operation", "absolute_tolerance"}:
            raise TaskValidationError("summary property fields are incomplete or unknown")
        name, output_name, operation = item["input"], item["output"], item["operation"]
        if output_name in expected_outputs:
            raise TaskValidationError("duplicate summary output property")
        expected_outputs.add(output_name)
        values = _valid_values(request, name)
        tolerance = _nonnegative(item["absolute_tolerance"])
        if operation == "COUNT":
            expected = Fraction(values.size)
        else:
            if operation not in {"MIN", "MAX", "SUM", "MEAN"}:
                raise TaskValidationError(f"unsupported independent summary property: {operation}")
            if not values.size or not np.all(np.isfinite(values)):
                raise TaskValidationError("numeric summary requires nonempty finite valid samples")
            exact = [_fraction(value) for value in values]
            if operation == "MIN":
                expected = min(exact)
            elif operation == "MAX":
                expected = max(exact)
            else:
                expected = sum(exact, Fraction(0))
                if operation == "MEAN":
                    expected /= len(exact)
        actual = request.outputs.get(output_name)
        if actual is None or actual.size != 1:
            failures.append({"output": output_name, "reason": "SCALAR_OUTPUT_REQUIRED"})
        elif abs(_fraction(actual.reshape(-1)[0]) - expected) > tolerance:
            failures.append({"output": output_name, "reason": "SUMMARY_PROPERTY_MISMATCH"})
    if set(request.outputs) != expected_outputs:
        failures.append({"reason": "SUMMARY_OUTPUT_IDENTITIES_DIFFER"})
    return TaskValidationResult(
        not failures,
        "SUMMARY_PROPERTY_MISMATCH" if failures else None,
        ("INDEPENDENT_OUTPUT_PROPERTY_VALIDATOR",),
        {"property_count": len(properties), "failures": failures},
    )


def _ceil(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _rate_budget(request: TaskValidationRequest) -> TaskValidationResult:
    required = {
        "schema_version",
        "accounting_layer",
        "denominator",
        "target_bits_per_value",
        "rounding",
        "block_size_values",
        "tolerance_bits",
        "constraint",
        "quality",
    }
    if set(request.contract) != required:
        raise TaskValidationError("rate contract contains missing or unknown fields")
    contract = request.contract
    artifact = request.encoded_artifact
    if artifact is None:
        raise TaskValidationError("actual encoded artifact is required for rate validation")
    ledger = artifact.ledger
    if sha256(artifact.stream).hexdigest() != artifact.stream_sha256:
        raise TaskValidationError("actual encoded stream digest differs")
    if (
        request.canonical_raw_bits is not None
        and ledger.canonical_raw_bits != request.canonical_raw_bits
    ):
        raise TaskValidationError("encoded ledger original denominator differs")
    if set(request.originals) != set(request.outputs) or any(
        value.shape != request.outputs[name].shape for name, value in request.originals.items()
    ):
        return TaskValidationResult(False, "RATE_RECONSTRUCTION_SHAPE", (), {})
    if contract["denominator"] == "ALL_VALUE_SLOTS":
        denominator = sum(value.size for value in request.originals.values())
    elif contract["denominator"] == "VALID_VALUE_SLOTS":
        denominator = sum(_valid_values(request, name).size for name in request.originals)
    else:
        raise TaskValidationError("unsupported frozen rate denominator")
    if not denominator:
        raise TaskValidationError("rate is not applicable to a zero value denominator")
    if contract["accounting_layer"] == "PAYLOAD_BITS":
        actual_bits = (
            ledger.timestamp_bits
            + ledger.value_bits
            + ledger.shared_bits
            + ledger.unallocated_shared_bits
        )
    elif contract["accounting_layer"] == "FINAL_BITS":
        actual_bits = ledger.final_bits
    else:
        raise TaskValidationError("rate accounting layer must be PAYLOAD_BITS or FINAL_BITS")
    target = _nonnegative(contract["target_bits_per_value"])
    tolerance = _nonnegative(contract["tolerance_bits"])
    block_size = contract["block_size_values"]
    if not isinstance(block_size, int) or isinstance(block_size, bool) or block_size < 1:
        raise TaskValidationError("rate block size must be a positive integer")
    budget = target * denominator
    if contract["rounding"] == "CEIL_TOTAL":
        budget = Fraction(_ceil(budget))
    elif contract["rounding"] == "CEIL_PER_BLOCK":
        blocks, tail = divmod(denominator, block_size)
        budget = Fraction(
            blocks * _ceil(target * block_size) + (_ceil(target * tail) if tail else 0)
        )
    elif contract["rounding"] != "NONE":
        raise TaskValidationError("unsupported rate block rounding")
    if contract["constraint"] == "MAXIMUM":
        rate_passed = actual_bits <= budget + tolerance
    elif contract["constraint"] == "TARGET_WITH_TOLERANCE":
        rate_passed = abs(actual_bits - budget) <= tolerance
    else:
        raise TaskValidationError("rate constraint must be MAXIMUM or TARGET_WITH_TOLERANCE")
    quality = contract["quality"]
    if quality == {"type": "PROFILE_ONLY"}:
        loss = profile_unbounded_loss(
            request.originals,
            request.outputs,
            timestamp=request.timestamp,
            validity=request.validity,
        )
        quality_passed = not loss.nonfinite_mismatch_count
    elif (
        isinstance(quality, dict)
        and set(quality)
        == {
            "type",
            "error_bound_type",
            "error_bound",
            "relative_error_zero_threshold",
            "error_aggregation_mode",
        }
        and quality["type"] == "ERROR_BOUND"
    ):
        loss = validate_error_bound(
            request.originals,
            request.outputs,
            error_bound_type=quality["error_bound_type"],
            error_bound=quality["error_bound"],
            relative_error_zero_threshold=quality["relative_error_zero_threshold"],
            error_aggregation_mode=quality["error_aggregation_mode"],
            timestamp=request.timestamp,
            validity=request.validity,
        )
        quality_passed = bool(loss.bound_passed)
    else:
        raise TaskValidationError(
            "rate quality policy must declare PROFILE_ONLY or a complete ERROR_BOUND"
        )
    diagnostics = {
        "actual_accounted_bits": actual_bits,
        "denominator_value_count": denominator,
        "actual_bits_per_value_exact": str(Fraction(actual_bits, denominator)),
        "budget_bits_exact": str(budget),
        "rate_passed": rate_passed,
        "quality_passed": quality_passed,
        "final_bits": ledger.final_bits,
        "artifact_physical_bits": len(artifact.stream) * 8,
        "required_external_bits": ledger.external_side_information_bits,
        "accounting_layer": contract["accounting_layer"],
        "rounding": contract["rounding"],
    }
    reason = (
        "RATE_BUDGET_VIOLATION"
        if not rate_passed
        else "RATE_QUALITY_VIOLATION"
        if not quality_passed
        else None
    )
    return TaskValidationResult(
        rate_passed and quality_passed,
        reason,
        ("ACTUAL_ARTIFACT_RATE", "RATE_RECONSTRUCTION_QUALITY"),
        diagnostics,
        loss,
    )


register_task_validator(
    TaskValidatorSpec(
        "tscb.validator.summary-scalars.v1",
        "SUMMARY_ONLY",
        "tscb.summary-property-contract.v1",
        _scalar_summary,
    )
)
register_task_validator(
    TaskValidatorSpec(
        "tscb.validator.rate-budget.v1",
        "RATE_CONTROLLED_LOSSY",
        "tscb.rate-contract.v1",
        _rate_budget,
    )
)
