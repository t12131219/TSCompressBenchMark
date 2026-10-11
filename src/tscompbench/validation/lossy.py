from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

import numpy as np


class LossValidationError(ValueError):
    pass


def _astype(array: np.ndarray[Any], dtype: Any) -> np.ndarray[Any]:
    with np.errstate(all="ignore"):
        return array.astype(dtype, copy=False)


def _number(value: np.generic[Any] | float) -> str | None:
    numeric = np.longdouble(value)
    if np.isnan(numeric):
        return None
    if np.isposinf(numeric):
        return "POSITIVE_INFINITY"
    if np.isneginf(numeric):
        return "NEGATIVE_INFINITY"
    return np.format_float_positional(numeric, unique=True, trim="-")


@dataclass(frozen=True)
class ChannelLossMetrics:
    name: str
    element_count: int
    raw_violation_count: int | None
    numerical_violation_count: int | None
    mae: str | None
    rmse: str | None
    nrmse_range: str | None
    max_ae: str | None
    p50_ae: str | None
    p95_ae: str | None
    p99_ae: str | None
    bias: str | None
    psnr_range_db: str | None
    finite_pair_count: int
    matching_nonfinite_count: int
    nonfinite_mismatch_count: int
    quality_valid: bool
    quality_invalid_reason: str | None
    valid_element_count: int = 0
    null_element_count: int = 0
    error_comparison_method: str = "LONGDOUBLE_V1"
    metric_na_reasons: dict[str, str] | None = None
    time_weighted_rmse: str | None = None
    time_weighted_rmse_reason: str | None = None
    derivative_rmse: str | None = None
    derivative_rmse_reason: str | None = None
    temporal_fidelity: dict[str, Any] | None = None


@dataclass(frozen=True)
class LossValidationReport:
    error_bound_type: str
    error_aggregation_mode: str
    raw_violation_count: int | None
    numerical_violation_count: int | None
    element_count: int
    channels: tuple[ChannelLossMetrics, ...]
    time_weighted_rmse: str | None
    temporal_fidelity: dict[str, Any]
    temporal_fidelity_is_gate: bool = False
    error_bound: str | None = None
    relative_error_zero_threshold: str | None = None

    @property
    def nonfinite_mismatch_count(self) -> int:
        return sum(item.nonfinite_mismatch_count for item in self.channels)

    @property
    def finite_pair_count(self) -> int:
        return sum(item.finite_pair_count for item in self.channels)

    @property
    def matching_nonfinite_count(self) -> int:
        return sum(item.matching_nonfinite_count for item in self.channels)

    @property
    def quality_valid(self) -> bool:
        return bool(self.channels) and all(item.quality_valid for item in self.channels)

    @property
    def quality_invalid_reason(self) -> str | None:
        if self.nonfinite_mismatch_count:
            return "NONFINITE_VALUE_MISMATCH"
        if not self.channels:
            return "NO_FINITE_VALUE_PAIRS"
        return next(
            (item.quality_invalid_reason for item in self.channels if not item.quality_valid),
            None,
        )

    @property
    def bound_passed(self) -> bool | None:
        if self.error_bound_type == "NOT_APPLICABLE_UNBOUNDED_LOSSY":
            return None
        return self.raw_violation_count == 0

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.loss-validation.v3",
            "error_bound_type": self.error_bound_type,
            "error_bound": self.error_bound,
            "relative_error_zero_threshold": self.relative_error_zero_threshold,
            "error_aggregation_mode": self.error_aggregation_mode,
            "raw_violation_count": self.raw_violation_count,
            "numerical_violation_count": self.numerical_violation_count,
            "element_count": self.element_count,
            "finite_pair_count": self.finite_pair_count,
            "matching_nonfinite_count": self.matching_nonfinite_count,
            "nonfinite_mismatch_count": self.nonfinite_mismatch_count,
            "quality_valid": self.quality_valid,
            "quality_invalid_reason": self.quality_invalid_reason,
            "bound_passed": self.bound_passed,
            "channels": [item.__dict__ for item in self.channels],
            "time_weighted_rmse": self.time_weighted_rmse,
            "temporal_fidelity": self.temporal_fidelity,
            "temporal_fidelity_is_gate": self.temporal_fidelity_is_gate,
            "numeric_precision": {
                "method_version": "tscb.loss-metrics.v3.2",
                "longdouble_bits": int(np.finfo(np.longdouble).bits),
                "longdouble_mantissa_bits": int(np.finfo(np.longdouble).nmant + 1),
                "longdouble_epsilon": _number(np.finfo(np.longdouble).eps),
                "integer_bound_comparison": "EXACT_RATIONAL_V1",
                "descriptive_metrics": "LONGDOUBLE_V1",
            },
        }


def _absolute_bound(
    original: np.ndarray[Any],
    *,
    error_bound_type: str,
    error_bound: np.longdouble,
    zero_threshold: np.longdouble,
    range_override: np.longdouble | None = None,
) -> np.ndarray[Any]:
    kind = error_bound_type.upper()
    original_ld = _astype(original, np.longdouble)
    if kind in {"ABS", "ABSOLUTE"}:
        return np.full(original.shape, np.longdouble(error_bound), dtype=np.longdouble)
    if kind in {"RANGE_REL", "RANGE_RELATIVE"}:
        if range_override is not None:
            scale = range_override
        else:
            finite_values = original_ld[np.isfinite(original_ld)]
            scale = (
                np.max(finite_values) - np.min(finite_values)
                if finite_values.size
                else np.longdouble(0)
            )
        return np.full(original.shape, np.longdouble(error_bound) * scale, dtype=np.longdouble)
    if kind in {"POINTWISE_REL", "POINTWISE_RELATIVE"}:
        scale = np.maximum(np.abs(original_ld), np.longdouble(zero_threshold))
        return np.longdouble(error_bound) * scale
    raise LossValidationError(f"unsupported pointwise error bound type: {error_bound_type}")


def _signed_difference(
    original: np.ndarray[Any], reconstructed: np.ndarray[Any]
) -> np.ndarray[Any]:
    if not np.issubdtype(original.dtype, np.integer):
        return _astype(reconstructed, np.longdouble) - _astype(original, np.longdouble)
    result = np.empty(original.shape, dtype=np.longdouble)
    for index in np.ndindex(original.shape):
        value = reconstructed[index]
        if not np.isfinite(value):
            result[index] = np.nan
            continue
        after = (
            Fraction(int(value))
            if np.issubdtype(reconstructed.dtype, np.integer)
            else Fraction(*value.as_integer_ratio())
        )
        difference = after - int(original[index])
        result[index] = np.longdouble(difference.numerator) / np.longdouble(difference.denominator)
    return result


def _time_metrics(
    metrics: ChannelLossMetrics,
    original: np.ndarray[Any],
    reconstructed: np.ndarray[Any],
    error: np.ndarray[Any],
    valid: np.ndarray[Any],
    timestamp: np.ndarray[Any] | None,
) -> ChannelLossMetrics:
    reason: str | None = None
    if not metrics.quality_valid:
        reason = metrics.quality_invalid_reason
    elif not np.all(valid):
        reason = "NULL_SAMPLE_PRESENT"
    elif metrics.finite_pair_count != metrics.element_count:
        reason = "NONFINITE_SAMPLE_PRESENT"
    elif original.ndim != 1:
        reason = "EXPLICIT_TIME_AXIS_REQUIRED"
    elif original.size < 2:
        reason = "INSUFFICIENT_TIME_SAMPLES"
    elif timestamp is None:
        reason = "TIMESTAMP_UNAVAILABLE"
    elif timestamp.ndim != 1 or timestamp.shape != original.shape:
        reason = "TIMESTAMP_SHAPE_MISMATCH"
    elif not np.all(np.isfinite(timestamp)):
        reason = "NONFINITE_TIMESTAMP"
    if reason is None:
        if np.issubdtype(timestamp.dtype, np.integer):
            delta = np.array(
                [int(b) - int(a) for a, b in zip(timestamp[:-1], timestamp[1:], strict=True)],
                dtype=np.longdouble,
            )
        else:
            delta = np.diff(_astype(timestamp, np.longdouble))
        if np.any(delta == 0):
            reason = "DUPLICATE_TIMESTAMP"
        elif np.any(delta < 0):
            reason = "OUT_OF_ORDER_TIMESTAMP"
        elif not np.all(np.isfinite(delta)):
            reason = "NONFINITE_TIMESTAMP_DELTA"
    if reason is not None:
        return replace(
            metrics,
            time_weighted_rmse_reason=reason,
            derivative_rmse_reason=reason,
            temporal_fidelity={"status": "NOT_APPLICABLE", "reason": reason, "warnings": []},
        )
    weights = np.empty(original.size, dtype=np.longdouble)
    weights[0], weights[-1] = delta[0] / 2, delta[-1] / 2
    weights[1:-1] = (delta[:-1] + delta[1:]) / 2
    signed = _signed_difference(original, reconstructed)
    derivative = np.diff(signed) / delta
    temporal: dict[str, Any] = {
        "status": "PROFILED_NOT_A_GATE",
        "warnings": [],
        "derivative_basis": "VALUE_PER_TIMESTAMP_UNIT",
        "derivative_rmse": _number(np.sqrt(np.mean(derivative * derivative))),
    }
    for label, values in (("original", original), ("reconstructed", reconstructed)):
        value_ld = _astype(values, np.longdouble)
        left, right = value_ld[:-1], value_ld[1:]
        centered_left, centered_right = left - np.mean(left), right - np.mean(right)
        denominator = np.sqrt(np.sum(centered_left**2) * np.sum(centered_right**2))
        temporal[f"lag1_acf_{label}"] = (
            _number(np.sum(centered_left * centered_right) / denominator) if denominator else None
        )
        if not denominator:
            temporal[f"lag1_acf_{label}_reason"] = "ZERO_VARIANCE_OR_INSUFFICIENT_PAIRS"
    return replace(
        metrics,
        time_weighted_rmse=_number(np.sqrt(np.sum(weights * error * error) / np.sum(weights))),
        derivative_rmse=temporal["derivative_rmse"],
        temporal_fidelity=temporal,
    )


def _channel_metrics(
    name: str,
    original: np.ndarray[Any],
    reconstructed: np.ndarray[Any],
    bound: np.ndarray[Any],
    *,
    valid: np.ndarray[Any],
    error_bound_type: str,
    exact_bound: Fraction,
    exact_zero_threshold: Fraction,
    exact_range: Fraction | None,
) -> tuple[ChannelLossMetrics, np.ndarray[Any]]:
    if original.shape != reconstructed.shape:
        raise LossValidationError(f"lossy output shape mismatch for {name}")
    original_ld = _astype(original, np.longdouble)
    reconstructed_ld = _astype(reconstructed, np.longdouble)
    matching_nonfinite = (
        valid
        & (~np.isfinite(original_ld))
        & (
            (np.isnan(original_ld) & np.isnan(reconstructed_ld))
            | (np.isposinf(original_ld) & np.isposinf(reconstructed_ld))
            | (np.isneginf(original_ld) & np.isneginf(reconstructed_ld))
        )
    )
    finite = valid & np.isfinite(original_ld) & np.isfinite(reconstructed_ld)
    error = np.zeros(original.shape, dtype=np.longdouble)
    error[finite] = np.abs(reconstructed_ld[finite] - original_ld[finite])
    mismatch = valid & ~(finite | matching_nonfinite)
    error[mismatch] = np.longdouble(np.inf)
    # Special-value mismatches are violations even when a relative scale is
    # nonfinite. They must not disappear in NaN comparisons or ULP diagnostics.
    raw = mismatch | (finite & (error > bound))
    exact_integer = np.issubdtype(original.dtype, np.integer)
    if exact_integer:
        # Python integers and exact float ratios preserve all i64/u64 bits even
        # on platforms where longdouble is only binary64. Decimal bounds retain
        # their declared value; the ULP diagnostic below never changes this gate.
        finite_original = [int(value) for value in original[valid].reshape(-1)]
        channel_range = (
            Fraction(max(finite_original) - min(finite_original))
            if finite_original
            else Fraction(0)
        )
        for index in np.ndindex(original.shape):
            if not finite[index]:
                continue
            before = Fraction(int(original[index]))
            after_value = reconstructed[index]
            after = (
                Fraction(int(after_value))
                if np.issubdtype(reconstructed.dtype, np.integer)
                else Fraction(*after_value.as_integer_ratio())
            )
            difference = abs(after - before)
            kind = error_bound_type.upper()
            if kind in {"ABS", "ABSOLUTE"}:
                exact_limit = exact_bound
            elif kind in {"RANGE_REL", "RANGE_RELATIVE"}:
                exact_limit = exact_bound * (
                    exact_range if exact_range is not None else channel_range
                )
            else:
                exact_limit = exact_bound * max(abs(before), exact_zero_threshold)
            raw[index] = difference > exact_limit
            error[index] = np.longdouble(difference.numerator) / np.longdouble(
                difference.denominator
            )

    original64 = _astype(original, np.float64)
    reconstructed64 = _astype(reconstructed, np.float64)
    bound64 = _astype(bound, np.float64)
    with np.errstate(over="ignore", invalid="ignore"):
        ulp = np.maximum.reduce(
            [
                np.abs(np.spacing(original64)),
                np.abs(np.spacing(reconstructed64)),
                np.abs(np.spacing(bound64)),
            ]
        )
    tolerance = (8.0 * ulp).astype(np.longdouble)
    numerical = mismatch | (finite & (error > (bound + tolerance)))
    finite_error = error[finite]
    mismatch_count = int(np.count_nonzero(mismatch))
    if mismatch_count:
        quality_invalid_reason = "NONFINITE_VALUE_MISMATCH"
    elif not finite_error.size:
        quality_invalid_reason = "NO_FINITE_VALUE_PAIRS"
    elif not np.all(np.isfinite(finite_error)):
        quality_invalid_reason = "NONFINITE_NUMERIC_ERROR"
    else:
        quality_invalid_reason = None
    if quality_invalid_reason is None:
        mae_value = np.mean(finite_error)
        rmse_value = np.sqrt(np.mean(finite_error * finite_error))
        max_value = np.max(finite_error)
        percentiles = np.percentile(finite_error, [50, 95, 99])
        with np.errstate(all="ignore"):
            bias_value = (
                np.mean(_signed_difference(original, reconstructed)[finite])
                if np.any(finite)
                else np.nan
            )
    else:
        mae_value = rmse_value = max_value = bias_value = np.nan
        percentiles = (np.nan, np.nan, np.nan)
    finite_original = original_ld[valid & np.isfinite(original_ld)]
    data_range = (
        np.max(finite_original) - np.min(finite_original) if finite_original.size else np.nan
    )
    if not np.isfinite(data_range) or data_range == 0:
        nrmse = None
        psnr = None
    elif rmse_value == 0:
        nrmse = "0"
        psnr = "POSITIVE_INFINITY"
    else:
        nrmse = _number(rmse_value / data_range)
        psnr = _number(20 * np.log10(data_range / rmse_value))
    na_reasons = (
        {
            "nrmse_range": "ZERO_OR_NONFINITE_RANGE",
            "psnr_range_db": "ZERO_OR_NONFINITE_RANGE",
        }
        if not np.isfinite(data_range) or data_range == 0
        else {}
    )
    if error_bound_type.upper() in {"POINTWISE_REL", "POINTWISE_RELATIVE"} and (
        exact_zero_threshold == 0 and np.any(valid & (original == 0))
    ):
        na_reasons["pointwise_relative_error_ratio"] = "ZERO_RELATIVE_DENOMINATOR"
    return (
        ChannelLossMetrics(
            name=name,
            element_count=int(original.size),
            raw_violation_count=int(np.count_nonzero(raw)),
            numerical_violation_count=int(np.count_nonzero(numerical)),
            mae=_number(mae_value),
            rmse=_number(rmse_value),
            nrmse_range=nrmse,
            max_ae=_number(max_value),
            p50_ae=_number(percentiles[0]),
            p95_ae=_number(percentiles[1]),
            p99_ae=_number(percentiles[2]),
            bias=_number(bias_value),
            psnr_range_db=psnr,
            finite_pair_count=int(np.count_nonzero(finite)),
            matching_nonfinite_count=int(np.count_nonzero(matching_nonfinite)),
            nonfinite_mismatch_count=mismatch_count,
            quality_valid=quality_invalid_reason is None,
            quality_invalid_reason=quality_invalid_reason,
            valid_element_count=int(np.count_nonzero(valid)),
            null_element_count=int(original.size - np.count_nonzero(valid)),
            error_comparison_method="EXACT_RATIONAL_V1" if exact_integer else "LONGDOUBLE_V1",
            metric_na_reasons=na_reasons,
        ),
        error,
    )


def validate_error_bound(
    originals: dict[str, np.ndarray[Any]],
    reconstructed: dict[str, np.ndarray[Any]],
    *,
    error_bound_type: str,
    error_bound: str,
    error_aggregation_mode: str = "PER_CHANNEL",
    relative_error_zero_threshold: str = "0",
    timestamp: np.ndarray[Any] | None = None,
    validity: dict[str, np.ndarray[Any]] | None = None,
) -> LossValidationReport:
    if set(originals) != set(reconstructed):
        raise LossValidationError("lossy reconstruction buffer names differ")
    try:
        bound_value = np.longdouble(error_bound)
        zero_threshold = np.longdouble(relative_error_zero_threshold)
    except (ValueError, TypeError, OverflowError) as error:
        raise LossValidationError(
            "error bounds and zero threshold must be finite numbers"
        ) from error
    if not np.isfinite(bound_value) or not np.isfinite(zero_threshold):
        raise LossValidationError("error bounds and zero threshold must be finite numbers")
    if bound_value < 0 or zero_threshold < 0:
        raise LossValidationError("error bounds and zero threshold must be non-negative")
    exact_bound = Fraction(str(error_bound))
    exact_zero_threshold = Fraction(str(relative_error_zero_threshold))
    masks: dict[str, np.ndarray[Any]] = {}
    if validity is not None and set(validity) != set(originals):
        raise LossValidationError("validity buffer names differ from value channels")
    for name, value in originals.items():
        mask = (
            np.ones(value.shape, dtype=np.bool_) if validity is None else np.asarray(validity[name])
        )
        if mask.dtype != np.bool_ or mask.shape != value.shape:
            raise LossValidationError(f"validity mask must be boolean and match shape for {name}")
        masks[name] = mask
    aggregation = error_aggregation_mode.upper()
    if aggregation not in {"GLOBAL_MATRIX", "PER_CHANNEL", "PER_ELEMENT_SCALE"}:
        raise LossValidationError(f"unsupported error aggregation mode: {error_aggregation_mode}")
    global_range: np.longdouble | None = None
    exact_global_range: Fraction | None = None
    if aggregation == "GLOBAL_MATRIX" and error_bound_type.upper() in {
        "RANGE_REL",
        "RANGE_RELATIVE",
    }:
        finite_parts = [
            _astype(value, np.longdouble)[masks[name] & np.isfinite(value)]
            for name, value in originals.items()
        ]
        nonempty = [value for value in finite_parts if value.size]
        if nonempty:
            global_min = min(np.min(value) for value in nonempty)
            global_max = max(np.max(value) for value in nonempty)
            global_range = np.longdouble(global_max - global_min)
        exact_values = [
            Fraction(int(x))
            if np.issubdtype(value.dtype, np.integer)
            else Fraction(*x.as_integer_ratio())
            for name, value in originals.items()
            for x in value[masks[name] & np.isfinite(value)]
        ]
        exact_global_range = max(exact_values) - min(exact_values) if exact_values else Fraction(0)
    channels: list[ChannelLossMetrics] = []
    for name in originals:
        original = originals[name]
        restored = reconstructed[name]
        bound = _absolute_bound(
            original[masks[name]],
            error_bound_type=error_bound_type,
            error_bound=bound_value,
            zero_threshold=zero_threshold,
            range_override=global_range,
        )
        full_bound = np.zeros(original.shape, dtype=np.longdouble)
        full_bound[masks[name]] = bound
        metrics, error = _channel_metrics(
            name,
            original,
            restored,
            full_bound,
            valid=masks[name],
            error_bound_type=error_bound_type,
            exact_bound=exact_bound,
            exact_zero_threshold=exact_zero_threshold,
            exact_range=exact_global_range,
        )
        metrics = _time_metrics(metrics, original, restored, error, masks[name], timestamp)
        channels.append(metrics)

    twrmse = channels[0].time_weighted_rmse if len(channels) == 1 else None
    temporal = (
        channels[0].temporal_fidelity
        if len(channels) == 1
        else {
            "status": "PER_CHANNEL",
            "aggregation": "NO_IMPLICIT_CHANNEL_WEIGHTING",
            "channels": {item.name: item.temporal_fidelity for item in channels},
        }
    )
    return LossValidationReport(
        error_bound_type=error_bound_type,
        error_aggregation_mode=error_aggregation_mode,
        raw_violation_count=sum(item.raw_violation_count for item in channels),
        numerical_violation_count=sum(item.numerical_violation_count for item in channels),
        element_count=sum(item.element_count for item in channels),
        channels=tuple(channels),
        time_weighted_rmse=twrmse,
        temporal_fidelity=temporal,
        error_bound=str(error_bound),
        relative_error_zero_threshold=str(relative_error_zero_threshold),
    )


def profile_unbounded_loss(
    originals: dict[str, np.ndarray[Any]],
    reconstructed: dict[str, np.ndarray[Any]],
    *,
    timestamp: np.ndarray[Any] | None = None,
    validity: dict[str, np.ndarray[Any]] | None = None,
) -> LossValidationReport:
    """Measure approximation quality without claiming an error or rate guarantee."""
    report = validate_error_bound(
        originals,
        reconstructed,
        error_bound_type="ABS",
        error_bound="0",
        timestamp=timestamp,
        validity=validity,
    )
    return replace(
        report,
        error_bound_type="NOT_APPLICABLE_UNBOUNDED_LOSSY",
        error_bound=None,
        relative_error_zero_threshold=None,
        raw_violation_count=None,
        numerical_violation_count=None,
        channels=tuple(
            replace(c, raw_violation_count=None, numerical_violation_count=None)
            for c in report.channels
        ),
    )
