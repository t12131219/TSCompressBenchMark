from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections.abc import Mapping, Sequence
from decimal import Decimal


def percentile(values: Sequence[float], probability: float) -> float:
    """Return a linearly interpolated percentile on a sorted finite sample."""

    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 <= probability <= 1:
        raise ValueError("percentile probability must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) for value in ordered):
        raise ValueError("statistics require finite values")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _bootstrap_median_ci(
    values: Sequence[float],
    *,
    samples: int,
    confidence_level: Decimal,
    seed_material: str,
) -> tuple[float, float]:
    if samples < 1:
        raise ValueError("bootstrap samples must be positive")
    if not Decimal("0") < confidence_level < Decimal("1"):
        raise ValueError("confidence level must be between zero and one")
    ordered = tuple(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0], ordered[0]
    seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
    generator = random.Random(seed)
    medians = [
        statistics.median(generator.choices(ordered, k=len(ordered))) for _ in range(samples)
    ]
    alpha = (Decimal(1) - confidence_level) / Decimal(2)
    return (
        percentile(medians, float(alpha)),
        percentile(medians, float(Decimal(1) - alpha)),
    )


def descriptive_statistics(
    values: Sequence[int | float],
    *,
    bootstrap_samples: int,
    confidence_level: Decimal,
    seed_material: str,
) -> dict[str, int | float | None]:
    """Compute the V2 robust statistics; CI95 is a bootstrap median interval."""

    numeric = tuple(float(value) for value in values)
    if not numeric:
        raise ValueError("descriptive statistics require at least one observation")
    if any(not math.isfinite(value) for value in numeric):
        raise ValueError("statistics require finite values")
    mean = statistics.fmean(numeric)
    standard_deviation = statistics.stdev(numeric) if len(numeric) > 1 else 0.0
    ci_low, ci_high = _bootstrap_median_ci(
        numeric,
        samples=bootstrap_samples,
        confidence_level=confidence_level,
        seed_material=seed_material,
    )
    return {
        "n": len(numeric),
        "median": statistics.median(numeric),
        "p25": percentile(numeric, 0.25),
        "p75": percentile(numeric, 0.75),
        "mean": mean,
        "sd": standard_deviation,
        "cv": None if mean == 0 else standard_deviation / abs(mean),
        "ci_low": ci_low,
        "ci_high": ci_high,
    }


def pareto_front(
    candidates: Mapping[str, Mapping[str, float]],
    directions: Mapping[str, str],
) -> tuple[set[str], dict[str, tuple[str, ...]]]:
    """Return non-dominated IDs and the IDs that dominate every candidate."""

    if not directions:
        raise ValueError("pareto analysis requires at least one objective")
    if set(directions.values()) - {"MIN", "MAX"}:
        raise ValueError("objective direction must be MIN or MAX")
    objective_names = tuple(directions)
    for candidate_id, metrics in candidates.items():
        if set(metrics) != set(objective_names):
            raise ValueError(f"candidate {candidate_id} has a different objective set")
        if any(not math.isfinite(float(value)) for value in metrics.values()):
            raise ValueError(f"candidate {candidate_id} has a non-finite objective")

    def no_worse(left: Mapping[str, float], right: Mapping[str, float], name: str) -> bool:
        return left[name] <= right[name] if directions[name] == "MIN" else left[name] >= right[name]

    def strictly_better(left: Mapping[str, float], right: Mapping[str, float], name: str) -> bool:
        return left[name] < right[name] if directions[name] == "MIN" else left[name] > right[name]

    dominated_by: dict[str, tuple[str, ...]] = {}
    ids = tuple(sorted(candidates))
    for candidate_id in ids:
        dominators: list[str] = []
        for other_id in ids:
            if other_id == candidate_id:
                continue
            left = candidates[other_id]
            right = candidates[candidate_id]
            if all(no_worse(left, right, name) for name in objective_names) and any(
                strictly_better(left, right, name) for name in objective_names
            ):
                dominators.append(other_id)
        dominated_by[candidate_id] = tuple(dominators)
    front = {candidate_id for candidate_id, dominators in dominated_by.items() if not dominators}
    return front, dominated_by


def rank_values(values: Mapping[str, float], *, direction: str) -> dict[str, int]:
    """Dense exact ranking. Missing values must be filtered by the caller."""

    if direction not in {"MIN", "MAX"}:
        raise ValueError("rank direction must be MIN or MAX")
    if any(not math.isfinite(float(value)) for value in values.values()):
        raise ValueError("ranking requires finite values")
    ordered_values = sorted(set(values.values()), reverse=direction == "MAX")
    rank_by_value = {value: index + 1 for index, value in enumerate(ordered_values)}
    return {candidate_id: rank_by_value[value] for candidate_id, value in values.items()}


def decimal_divide(numerator: int | float, denominator: int | float) -> str | None:
    if denominator == 0:
        return None
    return format(Decimal(str(numerator)) / Decimal(str(denominator)), ".17g")
