from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


class LossValidationError(ValueError):
    pass


def _astype(array: np.ndarray[Any], dtype: Any) -> np.ndarray[Any]:
    with np.errstate(all="ignore"):
        return array.astype(dtype, copy=False)


def _number(value: np.generic[Any] | float) -> str | None:
    numeric = float(value)
    if np.isnan(numeric):
        return None
    if np.isposinf(numeric):
        return "POSITIVE_INFINITY"
    if np.isneginf(numeric):
        return "NEGATIVE_INFINITY"
    return format(numeric, ".17g")


@dataclass(frozen=True)
class ChannelLossMetrics:
    name: str
    element_count: int
    raw_violation_count: int
    numerical_violation_count: int
    mae: str | None
    rmse: str | None
    nrmse_range: str | None
    max_ae: str | None
    p50_ae: str | None
    p95_ae: str | None
    p99_ae: str | None
    bias: str | None
    psnr_range_db: str | None


@dataclass(frozen=True)
class LossValidationReport:
    error_bound_type: str
    error_aggregation_mode: str
    raw_violation_count: int
    numerical_violation_count: int
    element_count: int
    channels: tuple[ChannelLossMetrics, ...]
    time_weighted_rmse: str | None
    temporal_fidelity: dict[str, Any]
    temporal_fidelity_is_gate: bool = False

    @property
    def bound_passed(self) -> bool:
        return self.raw_violation_count == 0

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.loss-validation.v2",
            "error_bound_type": self.error_bound_type,
            "error_aggregation_mode": self.error_aggregation_mode,
            "raw_violation_count": self.raw_violation_count,
            "numerical_violation_count": self.numerical_violation_count,
            "element_count": self.element_count,
            "bound_passed": self.bound_passed,
            "channels": [item.__dict__ for item in self.channels],
            "time_weighted_rmse": self.time_weighted_rmse,
            "temporal_fidelity": self.temporal_fidelity,
            "temporal_fidelity_is_gate": self.temporal_fidelity_is_gate,
        }


def _absolute_bound(
    original: np.ndarray[Any],
    *,
    error_bound_type: str,
    error_bound: float,
    zero_threshold: float,
    range_override: np.longdouble | None = None,
) -> np.ndarray[Any]:
    kind = error_bound_type.upper()
    finite = _astype(original, np.longdouble)
    if kind in {"ABS", "ABSOLUTE"}:
        return np.full(original.shape, np.longdouble(error_bound), dtype=np.longdouble)
    if kind in {"RANGE_REL", "RANGE_RELATIVE"}:
        if range_override is not None:
            scale = range_override
        elif original.size == 0:
            scale = np.longdouble(0)
        else:
            scale = np.max(finite) - np.min(finite)
        return np.full(original.shape, np.longdouble(error_bound) * scale, dtype=np.longdouble)
    if kind in {"POINTWISE_REL", "POINTWISE_RELATIVE"}:
        scale = np.maximum(np.abs(finite), np.longdouble(zero_threshold))
        return np.longdouble(error_bound) * scale
    raise LossValidationError(f"unsupported pointwise error bound type: {error_bound_type}")


def _channel_metrics(
    name: str,
    original: np.ndarray[Any],
    reconstructed: np.ndarray[Any],
    bound: np.ndarray[Any],
) -> tuple[ChannelLossMetrics, np.ndarray[Any]]:
    if original.shape != reconstructed.shape:
        raise LossValidationError(f"lossy output shape mismatch for {name}")
    original_ld = _astype(original, np.longdouble)
    reconstructed_ld = _astype(reconstructed, np.longdouble)
    matching_nonfinite = (~np.isfinite(original_ld)) & (
        (np.isnan(original_ld) & np.isnan(reconstructed_ld))
        | (np.isposinf(original_ld) & np.isposinf(reconstructed_ld))
        | (np.isneginf(original_ld) & np.isneginf(reconstructed_ld))
    )
    finite = np.isfinite(original_ld) & np.isfinite(reconstructed_ld)
    error = np.zeros(original.shape, dtype=np.longdouble)
    error[finite] = np.abs(reconstructed_ld[finite] - original_ld[finite])
    mismatch = ~(finite | matching_nonfinite)
    error[mismatch] = np.longdouble(np.inf)
    raw = error > bound

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
    numerical = error > (bound + tolerance)
    finite_error = error[np.isfinite(error)]
    if finite_error.size:
        mae_value = np.mean(finite_error)
        rmse_value = np.sqrt(np.mean(finite_error * finite_error))
        max_value = np.max(finite_error)
        percentiles = np.percentile(finite_error, [50, 95, 99])
        with np.errstate(all="ignore"):
            bias_value = (
                np.mean((reconstructed_ld - original_ld)[finite]) if np.any(finite) else np.nan
            )
    else:
        mae_value = rmse_value = max_value = bias_value = np.nan
        percentiles = (np.nan, np.nan, np.nan)
    finite_original = original_ld[np.isfinite(original_ld)]
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
) -> LossValidationReport:
    if set(originals) != set(reconstructed):
        raise LossValidationError("lossy reconstruction buffer names differ")
    bound_value = float(error_bound)
    zero_threshold = float(relative_error_zero_threshold)
    if bound_value < 0 or zero_threshold < 0:
        raise LossValidationError("error bounds and zero threshold must be non-negative")
    aggregation = error_aggregation_mode.upper()
    if aggregation not in {"GLOBAL_MATRIX", "PER_CHANNEL", "PER_ELEMENT_SCALE"}:
        raise LossValidationError(f"unsupported error aggregation mode: {error_aggregation_mode}")
    global_range: np.longdouble | None = None
    if aggregation == "GLOBAL_MATRIX" and error_bound_type.upper() in {
        "RANGE_REL",
        "RANGE_RELATIVE",
    }:
        finite_parts = [
            _astype(value, np.longdouble).reshape(-1)[
                np.isfinite(_astype(value, np.longdouble).reshape(-1))
            ]
            for value in originals.values()
        ]
        nonempty = [value for value in finite_parts if value.size]
        if nonempty:
            global_min = min(np.min(value) for value in nonempty)
            global_max = max(np.max(value) for value in nonempty)
            global_range = np.longdouble(global_max - global_min)
    channels: list[ChannelLossMetrics] = []
    errors: list[np.ndarray[Any]] = []
    for name in originals:
        original = originals[name]
        restored = reconstructed[name]
        bound = _absolute_bound(
            original,
            error_bound_type=error_bound_type,
            error_bound=bound_value,
            zero_threshold=zero_threshold,
            range_override=global_range,
        )
        metrics, error = _channel_metrics(name, original, restored, bound)
        channels.append(metrics)
        errors.append(error.reshape(-1))

    twrmse: str | None = None
    if timestamp is not None and len(errors) == 1 and originals:
        error = errors[0]
        if timestamp.size == error.size and timestamp.size > 1:
            delta = np.diff(timestamp.astype(np.longdouble))
            if np.all(delta > 0):
                weights = np.empty(timestamp.size, dtype=np.longdouble)
                weights[0] = delta[0] / 2
                weights[-1] = delta[-1] / 2
                if timestamp.size > 2:
                    weights[1:-1] = (delta[:-1] + delta[1:]) / 2
                twrmse = _number(np.sqrt(np.sum(weights * error * error) / np.sum(weights)))

    temporal: dict[str, Any] = {"status": "NOT_EVALUATED", "warnings": []}
    if len(errors) == 1 and errors[0].size > 2 and np.all(np.isfinite(errors[0])):
        original = _astype(next(iter(originals.values())), np.float64).reshape(-1)
        restored = _astype(next(iter(reconstructed.values())), np.float64).reshape(-1)
        if np.all(np.isfinite(original)) and np.all(np.isfinite(restored)):
            derivative_error = np.diff(restored) - np.diff(original)
            with np.errstate(all="ignore"):
                temporal = {
                    "status": "PROFILED_NOT_A_GATE",
                    "lag1_acf_original": _number(np.corrcoef(original[:-1], original[1:])[0, 1]),
                    "lag1_acf_reconstructed": _number(
                        np.corrcoef(restored[:-1], restored[1:])[0, 1]
                    ),
                    "derivative_rmse": _number(np.sqrt(np.mean(derivative_error**2))),
                    "warnings": [],
                }
    return LossValidationReport(
        error_bound_type=error_bound_type,
        error_aggregation_mode=error_aggregation_mode,
        raw_violation_count=sum(item.raw_violation_count for item in channels),
        numerical_violation_count=sum(item.numerical_violation_count for item in channels),
        element_count=sum(item.element_count for item in channels),
        channels=tuple(channels),
        time_weighted_rmse=twrmse,
        temporal_fidelity=temporal,
    )
