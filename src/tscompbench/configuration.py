from __future__ import annotations

import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DataPreparationConfig:
    characterization_mode: str
    characterization_sample_rows: int | None
    write_canonical: bool


@dataclass(frozen=True)
class ReportingConfig:
    bootstrap_samples: int
    confidence_level: str
    ranking_policy: str
    tie_method: str
    coverage_policy: str

    def as_document(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class BenchmarkProfile:
    profile_id: str
    measurement_mode: str
    timing_scope: str
    resource_scope: str
    memory_accounting_scope: str
    counter_method: str
    energy_method: str
    sampling_policy: str
    threads: int
    processes: int
    cpu_affinity: tuple[int, ...] | None
    device: str
    allocation_policy: str
    cache_policy: str
    state_policy: str
    gc_policy: str
    jit_policy: str
    timeout_seconds: int
    memory_limit_bytes: int
    warmup_min_count: int
    warmup_min_seconds: str
    repetitions: int
    min_repetition_seconds: str
    max_inner_iterations: int
    iteration_semantics: str
    query_workload: bool
    streaming_workload: bool
    query_count: int

    @property
    def qualification_repetitions(self) -> int:
        """Compatibility alias for Layer-3 callers predating the Layer-4 profile."""

        return self.repetitions

    def as_document(self) -> dict[str, Any]:
        document = {key: value for key, value in self.__dict__.items() if key != "profile_id"}
        if self.cpu_affinity is not None:
            document["cpu_affinity"] = list(self.cpu_affinity)
        return document


@dataclass(frozen=True)
class ExperimentConfig:
    schema_version: str
    datasets: tuple[str, ...]
    algorithms: tuple[str, ...]
    tracks: tuple[str, ...]
    seed: int
    data_preparation: DataPreparationConfig
    profile: BenchmarkProfile
    reporting: ReportingConfig
    sweep: dict[str, tuple[Any, ...]]
    canonical_document: dict[str, Any]
    experiment_config_id: str


_TOP_LEVEL = {
    "schema_version",
    "datasets",
    "algorithms",
    "tracks",
    "seed",
    "data_preparation",
    "profile",
    "reporting",
    "sweep",
}
_DATA_PREPARATION = {
    "characterization_mode",
    "characterization_sample_rows",
    "write_canonical",
}
_PROFILE = {
    "measurement_mode",
    "timing_scope",
    "resource_scope",
    "memory_accounting_scope",
    "counter_method",
    "energy_method",
    "sampling_policy",
    "threads",
    "processes",
    "cpu_affinity",
    "device",
    "allocation_policy",
    "cache_policy",
    "state_policy",
    "gc_policy",
    "jit_policy",
    "timeout_seconds",
    "memory_limit_bytes",
    "qualification_repetitions",
    "warmup_min_count",
    "warmup_min_seconds",
    "repetitions",
    "min_repetition_seconds",
    "max_inner_iterations",
    "iteration_semantics",
    "query_workload",
    "streaming_workload",
    "query_count",
}
_REPORTING = {
    "bootstrap_samples",
    "confidence_level",
    "ranking_policy",
    "tie_method",
    "coverage_policy",
}


def _decimal_string(raw: Any, *, label: str, minimum: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ConfigurationError(f"{label} must be a decimal string")
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ConfigurationError(f"{label} must be a decimal string") from error
    if not value.is_finite() or value < Decimal(minimum):
        raise ConfigurationError(f"{label} must be >= {minimum}")
    return format(value, "f")


def _string_array(raw: Any, *, label: str, allow_empty: bool) -> tuple[str, ...]:
    if (
        not isinstance(raw, list)
        or (not allow_empty and not raw)
        or not all(isinstance(item, str) and item for item in raw)
    ):
        qualifier = "" if allow_empty else " non-empty"
        raise ConfigurationError(f"{label} must be a{qualifier} string array")
    if len(set(raw)) != len(raw):
        raise ConfigurationError(f"{label} must not contain duplicates")
    return tuple(raw)


def _load_profile(raw: Any) -> BenchmarkProfile:
    if not isinstance(raw, dict):
        raise ConfigurationError("profile must be a table")
    unknown = set(raw) - _PROFILE
    if unknown:
        raise ConfigurationError(f"unknown profile fields: {sorted(unknown)}")
    if "qualification_repetitions" in raw and "repetitions" in raw:
        raise ConfigurationError(
            "profile cannot set both qualification_repetitions and repetitions"
        )
    measurement_mode = raw.get("measurement_mode", "QUALIFICATION")
    if measurement_mode not in {"QUALIFICATION", "FORMAL"}:
        raise ConfigurationError("profile.measurement_mode must be QUALIFICATION or FORMAL")
    values: dict[str, Any] = {
        "measurement_mode": measurement_mode,
        "timing_scope": raw.get("timing_scope", "PIPELINE"),
        "resource_scope": raw.get("resource_scope", "PROCESS"),
        "memory_accounting_scope": raw.get("memory_accounting_scope", "PROCESS_RSS"),
        "counter_method": raw.get("counter_method", "NOT_COLLECTED"),
        "energy_method": raw.get("energy_method", "NOT_COLLECTED"),
        "sampling_policy": raw.get("sampling_policy", "PROCESS_BOUNDARY"),
        "threads": raw.get("threads", 1),
        "processes": raw.get("processes", 1),
        "cpu_affinity": raw.get("cpu_affinity"),
        "device": raw.get("device", "CPU"),
        "allocation_policy": raw.get("allocation_policy", "PER_REPETITION"),
        "cache_policy": raw.get("cache_policy", "WARM_INPUT"),
        "state_policy": raw.get("state_policy", "RESET_PER_REPETITION"),
        "gc_policy": raw.get("gc_policy", "DISABLED_DURING_TIMING"),
        "jit_policy": raw.get("jit_policy", "NOT_APPLICABLE"),
        "timeout_seconds": raw.get("timeout_seconds", 120),
        "memory_limit_bytes": raw.get("memory_limit_bytes", 4 * 1024**3),
        "warmup_min_count": raw.get("warmup_min_count", 3 if measurement_mode == "FORMAL" else 0),
        "warmup_min_seconds": _decimal_string(
            raw.get("warmup_min_seconds", "0.5" if measurement_mode == "FORMAL" else "0"),
            label="profile.warmup_min_seconds",
            minimum="0",
        ),
        "repetitions": raw.get(
            "repetitions",
            raw.get(
                "qualification_repetitions",
                10 if measurement_mode == "FORMAL" else 1,
            ),
        ),
        "min_repetition_seconds": _decimal_string(
            raw.get("min_repetition_seconds", "1" if measurement_mode == "FORMAL" else "0"),
            label="profile.min_repetition_seconds",
            minimum="0",
        ),
        "max_inner_iterations": raw.get("max_inner_iterations", 1_000_000),
        "iteration_semantics": raw.get("iteration_semantics", "INDEPENDENT_OBJECT"),
        "query_workload": raw.get("query_workload", False),
        "streaming_workload": raw.get("streaming_workload", False),
        "query_count": raw.get("query_count", 1000),
    }
    for field in (
        "threads",
        "processes",
        "timeout_seconds",
        "memory_limit_bytes",
        "warmup_min_count",
        "repetitions",
        "max_inner_iterations",
        "query_count",
    ):
        if (
            not isinstance(values[field], int)
            or isinstance(values[field], bool)
            or values[field] < (0 if field == "warmup_min_count" else 1)
        ):
            qualifier = "non-negative" if field == "warmup_min_count" else "positive"
            raise ConfigurationError(f"profile.{field} must be a {qualifier} integer")
    if values["iteration_semantics"] not in {
        "INDEPENDENT_OBJECT",
        "CONTINUOUS_STREAM",
    }:
        raise ConfigurationError(
            "profile.iteration_semantics must be INDEPENDENT_OBJECT or CONTINUOUS_STREAM"
        )
    for field in ("query_workload", "streaming_workload"):
        if not isinstance(values[field], bool):
            raise ConfigurationError(f"profile.{field} must be boolean")
    enum_fields = {
        "timing_scope": {"CORE", "PIPELINE", "E2E"},
        "resource_scope": {
            "PROCESS",
            "PROCESS_TREE_CGROUP",
            "DEVICE",
            "SYSTEM_E2E",
        },
        "memory_accounting_scope": {
            "PROCESS_RSS",
            "CGROUP_PEAK",
            "DEVICE_VRAM",
        },
        "allocation_policy": {"PER_REPETITION", "PREALLOCATED"},
        "cache_policy": {"WARM_INPUT", "COLD_INPUT"},
        "state_policy": {"RESET_PER_REPETITION", "STEADY_STATE_REUSE"},
        "gc_policy": {"DISABLED_DURING_TIMING", "ENABLED"},
    }
    for field, allowed in enum_fields.items():
        if values[field] not in allowed:
            raise ConfigurationError(f"profile.{field} must be one of {sorted(allowed)}")
    unsupported_policy = {
        "allocation_policy": "PER_REPETITION",
        "cache_policy": "WARM_INPUT",
        "state_policy": "RESET_PER_REPETITION",
    }
    for field, supported in unsupported_policy.items():
        if values[field] != supported:
            raise ConfigurationError(
                f"profile.{field}={values[field]} is not implemented; "
                f"use {supported} instead of silently changing the timing boundary"
            )
    if values["jit_policy"] != "NOT_APPLICABLE":
        raise ConfigurationError(
            "only jit_policy=NOT_APPLICABLE is implemented in the current runner"
        )
    required_memory_scope = {
        "PROCESS": "PROCESS_RSS",
        "PROCESS_TREE_CGROUP": "CGROUP_PEAK",
        "DEVICE": "DEVICE_VRAM",
    }.get(values["resource_scope"])
    if (
        required_memory_scope is not None
        and values["memory_accounting_scope"] != required_memory_scope
    ):
        raise ConfigurationError(
            "profile.memory_accounting_scope does not match resource_scope: "
            f"expected {required_memory_scope}"
        )
    if measurement_mode == "FORMAL":
        if values["warmup_min_count"] < 3:
            raise ConfigurationError("FORMAL profile requires warmup_min_count >= 3")
        if Decimal(values["warmup_min_seconds"]) < Decimal("0.5"):
            raise ConfigurationError("FORMAL profile requires warmup_min_seconds >= 0.5")
        if values["repetitions"] < 10:
            raise ConfigurationError("FORMAL profile requires repetitions >= 10")
        minimum = Decimal(values["min_repetition_seconds"])
        if minimum < Decimal("1") or minimum > Decimal("3"):
            raise ConfigurationError("FORMAL profile requires min_repetition_seconds in [1, 3]")
        if Decimal(values["timeout_seconds"]) <= max(
            minimum, Decimal(values["warmup_min_seconds"])
        ):
            raise ConfigurationError(
                "FORMAL profile timeout_seconds must exceed warmup and repetition minima"
            )
    affinity = values["cpu_affinity"]
    if affinity is not None:
        if (
            not isinstance(affinity, list)
            or not affinity
            or not all(
                isinstance(item, int) and not isinstance(item, bool) and item >= 0
                for item in affinity
            )
        ):
            raise ConfigurationError("profile.cpu_affinity must be a non-empty integer array")
        if len(set(affinity)) != len(affinity):
            raise ConfigurationError("profile.cpu_affinity must not contain duplicates")
        values["cpu_affinity"] = tuple(affinity)
    profile_identity = dict(values)
    return BenchmarkProfile(profile_id=stable_id("profile", profile_identity), **values)


def _load_sweep(raw: Any) -> dict[str, tuple[Any, ...]]:
    if not isinstance(raw, dict):
        raise ConfigurationError("sweep must be a table")
    result: dict[str, tuple[Any, ...]] = {}
    for key, values in raw.items():
        if not isinstance(key, str) or not key or not isinstance(values, list) or not values:
            raise ConfigurationError("each sweep field must be a non-empty array")
        for value in values:
            if isinstance(value, float) or not isinstance(value, (str, int, bool)):
                raise ConfigurationError(
                    f"sweep.{key} values must be strings/integers/booleans; decimals use strings"
                )
        result[key] = tuple(values)
    return result


def _load_reporting(raw: Any) -> ReportingConfig:
    if not isinstance(raw, dict):
        raise ConfigurationError("reporting must be a table")
    unknown = set(raw) - _REPORTING
    if unknown:
        raise ConfigurationError(f"unknown reporting fields: {sorted(unknown)}")
    bootstrap_samples = raw.get("bootstrap_samples", 2000)
    if (
        not isinstance(bootstrap_samples, int)
        or isinstance(bootstrap_samples, bool)
        or bootstrap_samples < 100
    ):
        raise ConfigurationError("reporting.bootstrap_samples must be an integer >= 100")
    confidence_level = _decimal_string(
        raw.get("confidence_level", "0.95"),
        label="reporting.confidence_level",
        minimum="0.5",
    )
    if Decimal(confidence_level) >= Decimal(1):
        raise ConfigurationError("reporting.confidence_level must be < 1")
    values = {
        "bootstrap_samples": bootstrap_samples,
        "confidence_level": confidence_level,
        "ranking_policy": raw.get("ranking_policy", "PER_METRIC_WITHIN_COMPARABILITY_GROUP"),
        "tie_method": raw.get("tie_method", "DENSE_EXACT"),
        "coverage_policy": raw.get("coverage_policy", "PUBLISH_SEPARATELY_NO_SCORE"),
    }
    expected = {
        "ranking_policy": "PER_METRIC_WITHIN_COMPARABILITY_GROUP",
        "tie_method": "DENSE_EXACT",
        "coverage_policy": "PUBLISH_SEPARATELY_NO_SCORE",
    }
    for field, supported in expected.items():
        if values[field] != supported:
            raise ConfigurationError(
                f"reporting.{field}={values[field]} is not implemented; use {supported}"
            )
    return ReportingConfig(**values)


def load_experiment_config(path: Path) -> ExperimentConfig:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConfigurationError(f"cannot read experiment config: {error}") from error
    unknown = set(raw) - _TOP_LEVEL
    missing = {"schema_version", "datasets"} - set(raw)
    if unknown or missing:
        raise ConfigurationError(
            f"config fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    if raw["schema_version"] != "2.0":
        raise ConfigurationError("only experiment schema_version 2.0 is supported")
    datasets = _string_array(raw["datasets"], label="datasets", allow_empty=False)
    algorithms = _string_array(raw.get("algorithms", []), label="algorithms", allow_empty=True)
    tracks = _string_array(raw.get("tracks", ["VALUE"]), label="tracks", allow_empty=False)
    if set(tracks) - {"TIMESTAMP", "VALUE", "SYSTEM"}:
        raise ConfigurationError("tracks may contain only TIMESTAMP, VALUE, or SYSTEM")
    seed = raw.get("seed", 20260910)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ConfigurationError("seed must be a non-negative integer")
    preparation = raw.get("data_preparation", {})
    if not isinstance(preparation, dict):
        raise ConfigurationError("data_preparation must be a table")
    preparation_unknown = set(preparation) - _DATA_PREPARATION
    if preparation_unknown:
        raise ConfigurationError(f"unknown data_preparation fields: {sorted(preparation_unknown)}")
    mode = preparation.get("characterization_mode", "exact")
    if mode not in {"exact", "sampled"}:
        raise ConfigurationError("characterization_mode must be exact or sampled")
    sample_rows = preparation.get("characterization_sample_rows")
    if mode == "sampled":
        if not isinstance(sample_rows, int) or isinstance(sample_rows, bool) or sample_rows < 2:
            raise ConfigurationError(
                "sampled characterization requires characterization_sample_rows >= 2"
            )
    elif sample_rows is not None:
        raise ConfigurationError("characterization_sample_rows is only valid when mode is sampled")
    write_canonical = preparation.get("write_canonical", True)
    if not isinstance(write_canonical, bool):
        raise ConfigurationError("write_canonical must be boolean")
    if not write_canonical:
        raise ConfigurationError("Layer 1 requires write_canonical=true")

    profile = _load_profile(raw.get("profile", {}))
    reporting = _load_reporting(raw.get("reporting", {}))
    sweep = _load_sweep(raw.get("sweep", {}))

    canonical_document = {
        "schema_version": "2.0",
        "datasets": list(datasets),
        "algorithms": list(algorithms),
        "tracks": list(tracks),
        "seed": seed,
        "data_preparation": {
            "characterization_mode": mode,
            "characterization_sample_rows": sample_rows,
            "write_canonical": write_canonical,
        },
        "profile": profile.as_document(),
        "reporting": reporting.as_document(),
        "sweep": {key: list(value) for key, value in sorted(sweep.items())},
    }
    return ExperimentConfig(
        schema_version="2.0",
        datasets=datasets,
        algorithms=algorithms,
        tracks=tracks,
        seed=seed,
        data_preparation=DataPreparationConfig(
            characterization_mode=mode,
            characterization_sample_rows=sample_rows,
            write_canonical=write_canonical,
        ),
        profile=profile,
        reporting=reporting,
        sweep=sweep,
        canonical_document=canonical_document,
        experiment_config_id=stable_id("experiment-config", canonical_document),
    )
