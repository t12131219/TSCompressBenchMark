from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MeasurementPolicy:
    measurement_mode: str
    timing_scope: str
    resource_scope: str
    memory_accounting_scope: str
    counter_method: str
    energy_method: str
    sampling_policy: str
    allocation_policy: str
    cache_policy: str
    state_policy: str
    gc_policy: str
    jit_policy: str
    warmup_min_count: int
    warmup_min_seconds: str
    repetitions: int
    min_repetition_seconds: str
    max_inner_iterations: int
    iteration_semantics: str
    threads: int
    processes: int
    query_workload: bool
    streaming_workload: bool
    query_count: int
    seed: int

    @classmethod
    def from_profile(cls, profile: Any, *, seed: int) -> MeasurementPolicy:
        return cls(
            **{name: getattr(profile, name) for name in cls.__dataclass_fields__ if name != "seed"},
            seed=seed,
        )

    @property
    def warmup_min_ns(self) -> int:
        return int(Decimal(self.warmup_min_seconds) * Decimal(1_000_000_000))

    @property
    def repetition_min_ns(self) -> int:
        return int(Decimal(self.min_repetition_seconds) * Decimal(1_000_000_000))

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.measurement-policy.v2", **asdict(self)}


@dataclass(frozen=True)
class WarmupObservation:
    completed_iterations: int
    elapsed_wall_ns: int
    required_min_count: int
    required_min_wall_ns: int
    iteration_semantics: str
    threshold_satisfied: bool

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.warmup-observation.v2", **asdict(self)}


@dataclass(frozen=True)
class TimingObservation:
    timing_scope: str
    e2e_input_mode: str
    iteration_semantics: str
    inner_iterations: int
    selected_wall_ns: int
    selected_encode_wall_ns: int
    selected_decode_wall_ns: int
    selected_process_cpu_ns: int
    core_encode_wall_ns: int
    core_decode_wall_ns: int
    pipeline_encode_wall_ns: int
    pipeline_decode_wall_ns: int
    e2e_wall_ns: int
    encode_process_cpu_ns: int
    decode_process_cpu_ns: int
    canonical_bytes_per_iteration: int
    codec_input_bytes_per_iteration: int
    rows_per_iteration: int
    value_elements_per_iteration: int
    semantic_encode_mb_per_second: str | None
    semantic_decode_mb_per_second: str | None
    codec_input_encode_mb_per_second: str | None
    codec_input_decode_mb_per_second: str | None
    rows_per_second: str | None
    timestamps_per_second: str | None
    value_elements_per_second: str | None
    min_duration_satisfied: bool

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.timing-observation.v2", **asdict(self)}


def decimal_rate(numerator: int, elapsed_ns: int, *, scale: int = 1) -> str | None:
    if elapsed_ns <= 0 or numerator < 0:
        return None
    value = Decimal(numerator) * Decimal(1_000_000_000)
    value /= Decimal(elapsed_ns) * Decimal(scale)
    return format(value, ".17g")
