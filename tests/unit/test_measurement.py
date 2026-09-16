from pathlib import Path

import numpy as np
import pytest

from tscompbench.accounting import AccountingLedger
from tscompbench.adapters import OracleAdapter
from tscompbench.codecs import CompatibilityPlan, DataDescriptor
from tscompbench.configuration import ConfigurationError, load_experiment_config
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    Topology,
    ValidityShape,
)
from tscompbench.execution import (
    DecodedOutput,
    LogicalBuffer,
    RoutedInput,
    hash_logical_buffers,
)
from tscompbench.execution.repetition import perform_measured_roundtrip, perform_warmup
from tscompbench.measurement import (
    MeasurementPolicy,
    QueryResult,
    StreamPushResult,
    build_query_workload,
    execute_query_workload,
    execute_streaming_workload,
)


def _route() -> RoutedInput:
    values = np.arange(16, dtype="<i8")
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="v2:dataset:test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


def _compatibility(route: RoutedInput) -> CompatibilityPlan:
    descriptor = DataDescriptor(
        dataset_id=route.dataset_id,
        track=route.track,
        topology=Topology.UTS,
        n=route.n,
        m=route.m,
        shape=(route.n,),
        dtype_vector=("<i8",),
        physical_layout="ROW_MAJOR_CONTIG",
        endianness="little",
        alignment_bytes=8,
        canonical_raw_bits=route.canonical_raw_bits,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
        timestamp_unit="NOT_APPLICABLE",
        timestamp_epoch="NOT_APPLICABLE",
    )
    return CompatibilityPlan.create(
        status=CapabilityStatus.DIRECT_SUPPORTED,
        reason_code="DIRECT_MATCH",
        missing_capabilities=(),
        input_descriptor=descriptor,
        output_descriptor=descriptor.identity_document(),
        operations=(),
        effective_loss_mode=LossMode.LOSSLESS,
    )


def _policy(**overrides) -> MeasurementPolicy:
    values = {
        "measurement_mode": "QUALIFICATION",
        "timing_scope": "PIPELINE",
        "resource_scope": "PROCESS",
        "memory_accounting_scope": "PROCESS_RSS",
        "counter_method": "NOT_COLLECTED",
        "energy_method": "NOT_COLLECTED",
        "sampling_policy": "PROCESS_BOUNDARY",
        "allocation_policy": "PER_REPETITION",
        "cache_policy": "WARM_INPUT",
        "state_policy": "RESET_PER_REPETITION",
        "gc_policy": "DISABLED_DURING_TIMING",
        "jit_policy": "NOT_APPLICABLE",
        "warmup_min_count": 2,
        "warmup_min_seconds": "0",
        "repetitions": 1,
        "min_repetition_seconds": "0.002",
        "max_inner_iterations": 10000,
        "iteration_semantics": "INDEPENDENT_OBJECT",
        "threads": 1,
        "processes": 1,
        "query_workload": False,
        "streaming_workload": False,
        "query_count": 20,
        "seed": 7,
    }
    values.update(overrides)
    return MeasurementPolicy(**values)


def test_formal_profile_enforces_normative_warmup_repetition_and_duration(tmp_path) -> None:
    invalid = tmp_path / "invalid.toml"
    invalid.write_text(
        """schema_version = "2.0"
datasets = ["national_illness"]
[profile]
measurement_mode = "FORMAL"
warmup_min_count = 2
warmup_min_seconds = "0.5"
repetitions = 10
min_repetition_seconds = "1"
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="warmup_min_count"):
        load_experiment_config(invalid)

    profile = load_experiment_config(
        Path("configs/experiments/performance-evaluation-smoke.toml")
    ).profile
    assert profile.measurement_mode == "FORMAL"
    assert profile.warmup_min_count >= 3
    assert profile.repetitions >= 10


def test_measured_repetition_reuses_layer3_lifecycle_and_records_scope_resources() -> None:
    route = _route()
    policy = _policy()
    warmup = perform_warmup(OracleAdapter(), route, _compatibility(route), {}, policy)
    observation = perform_measured_roundtrip(
        OracleAdapter(), route, _compatibility(route), {}, policy
    )

    assert warmup.completed_iterations >= 2
    assert warmup.threshold_satisfied
    assert observation.timing.inner_iterations > 1
    assert observation.timing.min_duration_satisfied
    assert observation.timing.pipeline_encode_wall_ns >= observation.timing.core_encode_wall_ns
    assert observation.timing.pipeline_decode_wall_ns >= observation.timing.core_decode_wall_ns
    assert observation.resources.actual_scope == "PROCESS"
    assert observation.resources.scope_availability == "AVAILABLE"
    assert observation.resources.counter_observation["values"] is None
    assert observation.resources.energy_observation["joules"] is None
    assert observation.encoded.finalize_bytes > 0


def test_query_matrix_is_seeded_and_covers_point_full_and_projection_widths() -> None:
    first = build_query_workload(n=1000, m=9, seed=11, query_count=25)
    second = build_query_workload(n=1000, m=9, seed=11, query_count=25)
    assert first == second
    assert {item.length for item in first} == {1, 16, 100, 1000}
    assert {len(item.channel_indices) for item in first} == {1, 2, 4, 8, 9}


def test_query_engine_times_only_pregenerated_requests_and_checks_exact_slices() -> None:
    route = _route()

    class Session:
        def query(self, stream, request):
            source = route.buffers[0]
            selected = source.array[request.start : request.start + request.length]
            return QueryResult(
                buffers=(LogicalBuffer(source.name, selected, selected.nbytes * 8),),
                decoded_elements=selected.size,
                bytes_touched=selected.nbytes,
            )

        def close(self):
            return None

    class Adapter:
        def create_session(self, parameters):
            return Session()

    requests = build_query_workload(n=route.n, m=1, seed=5, query_count=5)
    result = execute_query_workload(
        adapter=Adapter(),
        parameters={},
        stream=b"encoded",
        routed=route,
        requests=requests,
        workload_id="query:test",
        index_bits=64,
    )
    assert result["status"] == "PASS"
    assert result["query_count"] == len(requests)
    assert result["decode_amplification"] == "1"
    assert result["read_amplification"] == "1"
    assert result["index_bits"] == 64


def test_streaming_engine_drives_blocks_finalizes_accounts_and_verifies_output() -> None:
    route = _route()

    class Session:
        def stream_push(self, chunk):
            raw = chunk.buffers[0].array.tobytes()
            return StreamPushResult(raw, state_bytes=8, buffer_bytes=len(raw))

        def stream_finalize(self):
            return b""

        def stream_accounting(self, stream, routed):
            return AccountingLedger.create(
                track=routed.track,
                canonical_raw_bits=routed.canonical_raw_bits,
                final_physical_bytes=len(stream),
                value_bits=len(stream) * 8,
            )

        def stream_decompress(self, stream):
            array = np.frombuffer(stream, dtype="<i8").copy()
            return DecodedOutput((LogicalBuffer("value/000000", array, array.nbytes * 8),))

        def close(self):
            return None

    class Adapter:
        def create_stream_session(self, parameters):
            return Session()

    result = execute_streaming_workload(
        adapter=Adapter(),
        parameters={},
        routed=route,
        compatibility=_compatibility(route),
        block_size=5,
    )
    assert result["status"] == "PASS"
    assert result["block_count"] == 4
    assert result["state_bytes"] == 8
    assert result["final_bits"] == route.canonical_raw_bits
    assert result["correctness"] == "PASS_EXACT_STREAM_RECONSTRUCTION"
