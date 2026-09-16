from pathlib import Path

import numpy as np

from tscompbench.adapters import OracleAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.datasets.canonical import CanonicalArtifact
from tscompbench.execution import (
    LogicalBuffer,
    RoutedInput,
    hash_logical_buffers,
    perform_roundtrip,
    route_canonical_artifact,
)
from tscompbench.execution.isolation import run_isolated
from tscompbench.validation import run_boundary_suite, validate_error_bound

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _route(values: np.ndarray, *, track: BenchmarkTrack = BenchmarkTrack.VALUE) -> RoutedInput:
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="v2:dataset:test",
        track=track,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


def test_track_routing_never_leaks_timestamp_into_value_and_requires_system_segment() -> None:
    timestamp = np.asarray([10, 20], dtype="<i8").tobytes()
    values = np.asarray([1.0, 2.0], dtype="<f8").tobytes()
    artifact = CanonicalArtifact(
        path=Path("unused"),
        sha256="0" * 64,
        metadata={
            "dataset_id": "v2:dataset:test",
            "logical_descriptor": {
                "n_rows": 2,
                "value_shape": [2],
                "timestamp": {"unit": "s", "epoch": "UNIX"},
                "value_columns": [{"unit": "unitless"}],
            },
            "accounting": {
                "timestamp_raw_bits": 128,
                "value_raw_bits": 128,
                "validity_raw_bits": 0,
                "canonical_raw_bits": 256,
            },
            "buffers": [
                {
                    "name": "timestamp",
                    "dtype": "<i8",
                    "shape": [2],
                    "logical_bits": 128,
                },
                {
                    "name": "value/000000",
                    "dtype": "<f8",
                    "shape": [2],
                    "logical_bits": 128,
                },
            ],
        },
        buffers={"timestamp": timestamp, "value/000000": values},
    )
    timestamp_route = route_canonical_artifact(artifact, BenchmarkTrack.TIMESTAMP)
    value_route = route_canonical_artifact(artifact, BenchmarkTrack.VALUE)
    system_route = route_canonical_artifact(artifact, BenchmarkTrack.SYSTEM)
    assert [item.name for item in timestamp_route.buffers] == ["timestamp"]
    assert [item.name for item in value_route.buffers] == ["value/000000"]
    assert [item.name for item in system_route.buffers] == [
        "timestamp",
        "value/000000",
    ]
    assert system_route.segment_plan_id is not None


def test_oracle_requires_finalize_and_accounts_real_written_bytes() -> None:
    values = np.asarray([0.0, -0.0, np.nan, np.inf], dtype="<f8")
    result = perform_roundtrip(OracleAdapter(), _route(values), {})
    assert result.encoded.finalize_bytes > 0
    assert result.encoded.ledger.final_physical_bytes == len(result.encoded.stream)
    assert result.encoded.ledger.value_bits == values.nbytes * 8
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert result.input_immutable and result.canary_intact


def test_loss_gate_uses_raw_violation_as_hard_failure_and_numerical_as_diagnostic() -> None:
    original = {"value/000000": np.asarray([0.0, 1.0, 2.0], dtype="<f8")}
    inside = {"value/000000": np.asarray([0.0, 1.05, 1.95], dtype="<f8")}
    outside = {"value/000000": np.asarray([0.0, 1.2, 2.0], dtype="<f8")}
    accepted = validate_error_bound(
        original, inside, error_bound_type="ABSOLUTE", error_bound="0.1"
    )
    rejected = validate_error_bound(
        original, outside, error_bound_type="ABSOLUTE", error_bound="0.1"
    )
    assert accepted.bound_passed
    assert rejected.raw_violation_count == 1
    assert not rejected.bound_passed
    assert rejected.temporal_fidelity_is_gate is False


def test_mts_global_and_per_channel_range_bounds_are_not_conflated() -> None:
    original = {
        "value/000000": np.asarray([0.0, 1.0], dtype="<f8"),
        "value/000001": np.asarray([0.0, 1000.0], dtype="<f8"),
    }
    reconstructed = {
        "value/000000": np.asarray([0.0, 1.5], dtype="<f8"),
        "value/000001": np.asarray([0.0, 1000.0], dtype="<f8"),
    }
    per_channel = validate_error_bound(
        original,
        reconstructed,
        error_bound_type="RANGE_REL",
        error_bound="0.001",
        error_aggregation_mode="PER_CHANNEL",
    )
    global_matrix = validate_error_bound(
        original,
        reconstructed,
        error_bound_type="RANGE_REL",
        error_bound="0.001",
        error_aggregation_mode="GLOBAL_MATRIX",
    )
    assert not per_channel.bound_passed
    assert global_matrix.bound_passed


def test_boundary_suite_covers_capacity_special_values_layout_and_stream_edges() -> None:
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources).get("oracle-direct")
    report = run_boundary_suite(OracleAdapter(), manifest, BenchmarkTrack.VALUE, {"block_size": 8})
    assert report.passed
    assert report.required_case_count >= 30
    reasons = {item.reason for item in report.observations}
    assert "BOUND_MINUS_ONE_REJECTED" in reasons


def test_worker_isolation_classifies_timeout_and_oom() -> None:
    route = _route(np.arange(4, dtype="<i8"))
    timeout = run_isolated(
        perform_roundtrip,
        OracleAdapter(delay_seconds=0.2),
        route,
        {},
        timeout_seconds=0.02,
    )
    oom = run_isolated(
        perform_roundtrip,
        OracleAdapter(mode="OOM"),
        route,
        {},
        timeout_seconds=1,
    )
    assert timeout.status is RunStatus.TIMEOUT
    assert oom.status is RunStatus.OOM
