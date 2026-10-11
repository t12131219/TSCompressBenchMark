from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, fields
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
    measurement_protocol_id: str = "LEGACY_V2"
    encode_min_ns: int | None = None
    decode_min_ns: int | None = None
    worker_start_method: str | None = None
    resource_collector_enabled: bool = True
    thread_monitor_interval_ns: int | None = None

    def __post_init__(self) -> None:
        if self.thread_monitor_interval_ns is not None and (
            type(self.thread_monitor_interval_ns) is not int
            or not 1_000_000 <= self.thread_monitor_interval_ns <= 2**63 - 1
        ):
            raise ValueError("thread monitor interval must be a finite integer >= 1ms")

    @classmethod
    def from_profile(cls, profile: Any, *, seed: int) -> MeasurementPolicy:
        values = {
            field.name: getattr(profile, field.name)
            for field in fields(cls)
            if field.name != "seed" and (hasattr(profile, field.name) or field.default is MISSING)
        }
        return cls(**values, seed=seed)

    @property
    def warmup_min_ns(self) -> int:
        return int(Decimal(self.warmup_min_seconds) * Decimal(1_000_000_000))

    @property
    def repetition_min_ns(self) -> int:
        return int(Decimal(self.min_repetition_seconds) * Decimal(1_000_000_000))

    def duration_satisfied(self, encode_ns: int, decode_ns: int, e2e_ns: int) -> bool:
        """Each reported direction must reach the configured measurement duration."""
        minimum = self.repetition_min_ns
        return (
            encode_ns >= (minimum if self.encode_min_ns is None else self.encode_min_ns)
            and decode_ns >= (minimum if self.decode_min_ns is None else self.decode_min_ns)
            and (self.timing_scope != "E2E" or e2e_ns >= minimum)
        )

    def to_document(self) -> dict[str, Any]:
        values = asdict(self)
        if self.measurement_protocol_id == "LEGACY_V2":
            for key in (
                "measurement_protocol_id",
                "encode_min_ns",
                "decode_min_ns",
                "worker_start_method",
                "resource_collector_enabled",
                "thread_monitor_interval_ns",
            ):
                values.pop(key)
        return {
            "schema_version": "tscb.measurement-policy.v2"
            if self.measurement_protocol_id == "LEGACY_V2"
            else "tscb.measurement-policy.v3",
            **values,
            "minimum_duration_boundary": "PER_SELECTED_DIRECTION_WITH_E2E_V1",
        }


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
    native_encode_wall_ns: int | None = None
    native_decode_wall_ns: int | None = None
    native_encode_mb_per_second: str | None = None
    native_decode_mb_per_second: str | None = None
    native_timing_enabled: bool = False
    native_timing_boundary: str | None = None
    native_timing_clock: str | None = None
    native_input_bytes_per_iteration: int | None = None
    pipeline_stage_timings: dict[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.timing-observation.v2", **asdict(self)}


def decimal_rate(numerator: int, elapsed_ns: int, *, scale: int = 1) -> str | None:
    if elapsed_ns <= 0 or numerator < 0:
        return None
    value = Decimal(numerator) * Decimal(1_000_000_000)
    value /= Decimal(elapsed_ns) * Decimal(scale)
    return format(value, ".17g")
