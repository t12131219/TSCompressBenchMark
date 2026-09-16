from __future__ import annotations

import hashlib
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from itertools import product
from typing import Any

import numpy as np

from .models import CanonicalDataset, DatasetContractError


@dataclass(frozen=True)
class CharacterizationProfile:
    mode: str = "exact"
    sample_rows: int | None = None
    seed: int = 20260910
    acf_lags: tuple[int, ...] = (1, 10)

    def __post_init__(self) -> None:
        if self.mode not in {"exact", "sampled"}:
            raise ValueError("characterization mode must be exact or sampled")
        if self.mode == "sampled" and (self.sample_rows is None or self.sample_rows < 2):
            raise ValueError("sampled characterization requires sample_rows >= 2")
        if any(lag < 1 for lag in self.acf_lags):
            raise ValueError("ACF lags must be positive")


def _entropy_from_counts(counts: np.ndarray[Any]) -> float:
    probabilities = counts.astype(np.float64) / counts.sum()
    return float(-np.sum(probabilities * np.log2(probabilities)))


def _acf(values: np.ndarray[Any], lag: int) -> float | None:
    if values.size <= lag:
        return None
    left = values[:-lag]
    right = values[lag:]
    valid = np.isfinite(left) & np.isfinite(right)
    if int(valid.sum()) < 2:
        return None
    left = left[valid].astype(np.float64, copy=False)
    right = right[valid].astype(np.float64, copy=False)
    left_centered = left - left.mean()
    right_centered = right - right.mean()
    denominator = math.sqrt(float(np.dot(left_centered, left_centered))) * math.sqrt(
        float(np.dot(right_centered, right_centered))
    )
    if denominator == 0:
        return None
    return float(np.dot(left_centered, right_centered) / denominator)


def _sample_rows(values: np.ndarray[Any], indices: np.ndarray[Any] | None) -> np.ndarray[Any]:
    return values if indices is None else values[indices]


def _bit_patterns(values: np.ndarray[Any]) -> np.ndarray[Any]:
    contiguous = np.ascontiguousarray(values)
    if np.issubdtype(contiguous.dtype, np.floating):
        return contiguous.view(np.dtype(f"<u{contiguous.dtype.itemsize}"))
    if np.issubdtype(contiguous.dtype, np.integer):
        return contiguous.view(np.dtype(f"<u{contiguous.dtype.itemsize}"))
    raise DatasetContractError(f"unsupported characterization dtype: {values.dtype.str}")


def _value_statistics(
    name: str,
    values: np.ndarray[Any],
    *,
    row_indices: np.ndarray[Any] | None,
    lags: tuple[int, ...],
    metric_mode: str,
) -> dict[str, Any]:
    selected = _sample_rows(values, row_indices)
    floating = np.issubdtype(selected.dtype, np.floating)
    if floating:
        nan_count = int(np.isnan(selected).sum())
        positive_inf_count = int(np.isposinf(selected).sum())
        negative_inf_count = int(np.isneginf(selected).sum())
        negative_zero_count = int(((selected == 0) & np.signbit(selected)).sum())
        finite = selected[np.isfinite(selected)]
    else:
        nan_count = positive_inf_count = negative_inf_count = negative_zero_count = 0
        finite = selected
    finite64 = finite.astype(np.float64, copy=False)
    if finite.size:
        quantiles = np.quantile(finite64, [0.01, 0.5, 0.99])
        minimum = float(np.min(finite64))
        maximum = float(np.max(finite64))
        mean = float(np.mean(finite64))
        std = float(np.std(finite64))
        p01, p50, p99 = (float(value) for value in quantiles)
    else:
        minimum = maximum = mean = std = p01 = p50 = p99 = None
    patterns = _bit_patterns(selected)
    _, counts = np.unique(patterns, return_counts=True)
    unique_count = int(counts.size)
    adjacent_repeat_count = int(np.count_nonzero(patterns[1:] == patterns[:-1]))
    total = int(selected.size)
    return {
        "name": name,
        "dtype": selected.dtype.str,
        "metric_mode": metric_mode,
        "observed_count": total,
        "min": minimum,
        "mean": mean,
        "std": std,
        "max": maximum,
        "range": None if minimum is None else maximum - minimum,
        "p01": p01,
        "p50": p50,
        "p99": p99,
        "unique_count": unique_count,
        "unique_ratio": None if total == 0 else unique_count / total,
        "adjacent_repeat_count": adjacent_repeat_count,
        "adjacent_repeat_ratio": None if total < 2 else adjacent_repeat_count / (total - 1),
        "value_entropy_bits": _entropy_from_counts(counts) if total else None,
        "nan_count": nan_count,
        "positive_inf_count": positive_inf_count,
        "negative_inf_count": negative_inf_count,
        "negative_zero_count": negative_zero_count,
        "nan_ratio": None if total == 0 else nan_count / total,
        "inf_ratio": None if total == 0 else (positive_inf_count + negative_inf_count) / total,
        "acf": {str(lag): _acf(selected, lag) for lag in lags},
    }


def _iter_value_channels(dataset: CanonicalDataset) -> Iterator[tuple[str, np.ndarray[Any]]]:
    if len(dataset.values) > 1:
        for item in dataset.values:
            yield item.name, item.array
        return
    item = dataset.values[0]
    array = item.array
    if array.ndim == 1:
        yield item.name, array
        return
    trailing_shape = array.shape[1:]
    for coordinates in product(*(range(size) for size in trailing_shape)):
        suffix = ",".join(str(value) for value in coordinates)
        yield f"{item.name}[{suffix}]", array[(slice(None), *coordinates)]


def _timestamp_statistics(timestamp: np.ndarray[Any] | None) -> dict[str, Any]:
    if timestamp is None:
        return {"present": False, "reason": "TIMESTAMP_ORIGIN_NONE"}
    n = int(timestamp.size)
    result: dict[str, Any] = {
        "present": True,
        "count": n,
        "min": None if n == 0 else int(timestamp.min()),
        "max": None if n == 0 else int(timestamp.max()),
    }
    if n < 2:
        result.update(
            {
                "delta_count": 0,
                "delta_min": None,
                "delta_mean": None,
                "delta_std": None,
                "delta_median": None,
                "delta_cv": None,
                "duplicate_count": 0,
                "out_of_order_count": 0,
                "negative_delta_count": 0,
                "gap_count": 0,
                "regularity_ratio": None,
                "delta_entropy_bits": None,
                "dod": None,
            }
        )
        return result
    deltas_exact = np.array(
        [int(timestamp[index]) - int(timestamp[index - 1]) for index in range(1, n)],
        dtype=object,
    )
    deltas = np.asarray([float(value) for value in deltas_exact], dtype=np.float64)
    delta_median = float(np.median(deltas))
    delta_mean = float(np.mean(deltas))
    delta_std = float(np.std(deltas))
    unique_delta, delta_counts = np.unique(deltas_exact, return_counts=True)
    duplicate_count = int(np.count_nonzero(deltas == 0))
    negative_count = int(np.count_nonzero(deltas < 0))
    positive_baseline = delta_median if delta_median > 0 else None
    gap_count = (
        0 if positive_baseline is None else int(np.count_nonzero(deltas > 1.5 * positive_baseline))
    )
    result.update(
        {
            "delta_count": int(deltas.size),
            "delta_min": int(min(deltas_exact)),
            "delta_mean": delta_mean,
            "delta_std": delta_std,
            "delta_median": delta_median,
            "delta_cv": None if delta_mean == 0 else delta_std / abs(delta_mean),
            "duplicate_count": duplicate_count,
            "duplicate_ratio": duplicate_count / deltas.size,
            "out_of_order_count": negative_count,
            "out_of_order_ratio": negative_count / deltas.size,
            "negative_delta_count": negative_count,
            "gap_count": gap_count,
            "gap_ratio": gap_count / deltas.size,
            "regularity_ratio": int(np.count_nonzero(deltas == delta_median)) / deltas.size,
            "delta_entropy_bits": _entropy_from_counts(delta_counts),
            "delta_unique_count": int(unique_delta.size),
        }
    )
    if deltas.size < 2:
        result["dod"] = None
        return result
    dod_exact = np.array(
        [
            int(deltas_exact[index]) - int(deltas_exact[index - 1])
            for index in range(1, deltas.size)
        ],
        dtype=object,
    )
    absolute_dod = np.asarray([abs(float(value)) for value in dod_exact], dtype=np.float64)
    _, dod_counts = np.unique(dod_exact, return_counts=True)
    result["dod"] = {
        "count": int(dod_exact.size),
        "zero_count": int(np.count_nonzero(absolute_dod == 0)),
        "zero_ratio": int(np.count_nonzero(absolute_dod == 0)) / dod_exact.size,
        "abs_p50": float(np.quantile(absolute_dod, 0.50)),
        "abs_p95": float(np.quantile(absolute_dod, 0.95)),
        "abs_p99": float(np.quantile(absolute_dod, 0.99)),
        "entropy_bits": _entropy_from_counts(dod_counts),
    }
    return result


def characterize(
    dataset: CanonicalDataset,
    profile: CharacterizationProfile | None = None,
) -> dict[str, Any]:
    profile = profile or CharacterizationProfile()
    content_hash_before = dataset.content_sha256()
    if profile.mode == "sampled" and profile.sample_rows is not None:
        sample_count = min(profile.sample_rows, dataset.n_rows)
        generator = np.random.default_rng(profile.seed)
        row_indices = np.sort(generator.choice(dataset.n_rows, sample_count, replace=False))
    else:
        row_indices = None
        sample_count = dataset.n_rows
    channels = [
        _value_statistics(
            name,
            values,
            row_indices=row_indices,
            lags=profile.acf_lags,
            metric_mode=profile.mode,
        )
        for name, values in _iter_value_channels(dataset)
    ]
    content_hash_after = dataset.content_sha256()
    if content_hash_before != content_hash_after:
        raise DatasetContractError("characterization modified canonical data")
    return {
        "schema_version": "tscb.dataset-characterization.v2",
        "dataset_id": dataset.dataset_id,
        "canonical_content_sha256": content_hash_before,
        "profile": {
            **asdict(profile),
            "acf_lags": list(profile.acf_lags),
            "observed_rows": sample_count,
            "total_rows": dataset.n_rows,
            "sampling_indices_sha256": None
            if row_indices is None
            else hashlib.sha256(row_indices.astype("<i8").tobytes()).hexdigest(),
        },
        "integrity": {
            "n_rows": dataset.n_rows,
            "value_shape": dataset.logical_descriptor["value_shape"],
            "timestamp_present": dataset.timestamp is not None,
            "validity_present": dataset.validity is not None,
            "canonical_raw_bits": dataset.canonical_raw_bits,
        },
        "timestamp": _timestamp_statistics(dataset.timestamp),
        "value": {
            "channel_count": len(channels),
            "channels": channels,
            "high_cost_metrics": {
                "psd": "NOT_COMPUTED",
                "seasonality": "NOT_COMPUTED",
                "derivative": "NOT_COMPUTED",
                "extrema": "NOT_COMPUTED",
            },
        },
        "read_only_verified": True,
        "characterizer": "tscompbench.datasets.characterize.v1",
    }
