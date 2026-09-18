from dataclasses import replace
from pathlib import Path

from tscompbench.codecs import (
    CodecManifest,
    CodecRegistry,
    DataDescriptor,
    SourceRegistry,
    negotiate,
)
from tscompbench.contracts import BenchmarkTrack, RunStatus, Topology, ValidityShape
from tscompbench.planning import build_comparability_keys, expand_sweep, resolve_execution

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _registry() -> CodecRegistry:
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    return CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)


def _descriptor() -> DataDescriptor:
    return DataDescriptor(
        dataset_id="v2:dataset:sha256:" + "0" * 64,
        track=BenchmarkTrack.VALUE,
        topology=Topology.SYNCHRONOUS_MTS,
        n=4,
        m=1,
        shape=(4,),
        dtype_vector=("<f8",),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=256,
        validity_shape=ValidityShape.NONE,
        timestamp_present=True,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )


def test_sweep_expands_defaults_and_preserves_invalid_parameter_points() -> None:
    manifest = _registry().get("oracle-direct")
    valid = expand_sweep(manifest, {"block_size": [256, 1024]})
    assert len(valid) == 2
    assert all(item.parameters["isa"] == "SCALAR" for item in valid)
    assert len({item.config_id for item in valid}) == 2
    other_seed = expand_sweep(
        manifest,
        {"block_size": [256]},
        framework_parameters={"benchmark_seed": 8},
    )[0]
    seeded = expand_sweep(
        manifest,
        {"block_size": [256]},
        framework_parameters={"benchmark_seed": 7},
    )[0]
    assert other_seed.config_id != seeded.config_id
    invalid = expand_sweep(manifest, {"unknown": [1, 2]})
    assert len(invalid) == 2
    assert all(item.status is RunStatus.SCHEMA_ERROR for item in invalid)


def test_runtime_fallback_changes_execution_path_hash(tmp_path) -> None:
    base = _registry().get("oracle-direct")
    document = dict(base.document)
    document["execution"] = dict(document["execution"])
    document["execution"]["isa"] = ["AVX512", "SCALAR"]
    document["execution"]["fallback_policy"] = "SCALAR_ALLOWED"
    manifest = CodecManifest(base.key, document, base.algorithm_id)
    compatibility = negotiate(manifest, _descriptor())
    config = expand_sweep(base, {})[0]
    artifact = tmp_path / "adapter.bin"
    artifact.write_bytes(b"frozen-adapter")
    environment = {
        "environment_id": "v2:environment:sha256:" + "1" * 64,
        "cpu": {"flags": ["avx2"], "affinity": [0]},
    }
    profile = {
        "threads": 1,
        "processes": 1,
        "runner_version": "test",
        "allocation_policy": "PER_REPETITION",
        "cache_policy": "WARM_INPUT",
        "state_policy": "RESET_PER_REPETITION",
        "gc_policy": "DISABLED_DURING_TIMING",
        "jit_policy": "NOT_APPLICABLE",
    }
    avx_config = replace(config, parameters={**config.parameters, "isa": "AVX512"})
    fallback = resolve_execution(
        manifest, avx_config, compatibility, environment, artifact_path=artifact, profile=profile
    )
    scalar = resolve_execution(
        manifest, config, compatibility, environment, artifact_path=artifact, profile=profile
    )
    assert fallback.actual_isa == "SCALAR"
    assert fallback.fallback_used is True
    assert fallback.execution_path_hash != scalar.execution_path_hash


def test_missing_execution_artifact_is_an_explicit_planning_result(tmp_path) -> None:
    manifest = _registry().get("lz4-frame")
    compatibility = negotiate(manifest, _descriptor())
    config = expand_sweep(manifest, {})[0]
    environment = {
        "environment_id": "v2:environment:sha256:" + "2" * 64,
        "cpu": {"flags": [], "affinity": [0]},
    }
    profile = {
        "threads": 1,
        "processes": 1,
        "runner_version": "test",
        "allocation_policy": "PER_REPETITION",
        "cache_policy": "WARM_INPUT",
        "state_policy": "RESET_PER_REPETITION",
        "gc_policy": "DISABLED_DURING_TIMING",
        "jit_policy": "NOT_APPLICABLE",
    }

    resolution = resolve_execution(
        manifest,
        config,
        compatibility,
        environment,
        artifact_path=tmp_path / "missing-adapter.so",
        profile=profile,
    )

    assert resolution.status is RunStatus.BUILD_UNAVAILABLE
    assert resolution.reason_code == "EXECUTION_ARTIFACT_MISSING"
    assert resolution.artifact_sha256 == "UNSPECIFIED"


def test_frame_profiles_compare_directly_while_raw_and_brotli_remain_separate(
    tmp_path,
) -> None:
    registry = _registry()
    artifact = tmp_path / "adapter.bin"
    artifact.write_bytes(b"test-native-adapter")
    environment = {
        "environment_id": "v2:environment:sha256:" + "3" * 64,
        "cpu": {"flags": [], "affinity": [0]},
    }
    profile = {
        "measurement_mode": "FORMAL",
        "timing_scope": "PIPELINE",
        "resource_scope": "PROCESS",
        "memory_accounting_scope": "PROCESS_RSS",
        "counter_method": "NOT_COLLECTED",
        "energy_method": "NOT_COLLECTED",
        "sampling_policy": "PROCESS_BOUNDARY",
        "threads": 1,
        "processes": 1,
        "device": "CPU",
        "runner_version": "test",
        "allocation_policy": "PER_REPETITION",
        "cache_policy": "WARM_INPUT",
        "state_policy": "RESET_PER_REPETITION",
        "gc_policy": "DISABLED_DURING_TIMING",
        "jit_policy": "NOT_APPLICABLE",
        "warmup_min_count": 3,
        "warmup_min_seconds": "0.5",
        "repetitions": 10,
        "min_repetition_seconds": "1",
        "iteration_semantics": "INDEPENDENT_OBJECT",
        "query_workload": False,
        "query_count": 1,
        "streaming_workload": False,
    }
    key_sets = []
    execution_paths = []
    for manifest_key in ("lz4-frame", "zstd-frame", "snappy-raw", "brotli-stream"):
        manifest = registry.get(manifest_key)
        compatibility = negotiate(manifest, _descriptor())
        config = expand_sweep(manifest, {})[0]
        execution = resolve_execution(
            manifest,
            config,
            compatibility,
            environment,
            artifact_path=artifact,
            profile=profile,
        )
        key_sets.append(
            build_comparability_keys(
                manifest,
                _descriptor(),
                config,
                compatibility,
                execution,
                profile=profile,
            )
        )
        execution_paths.append(execution.execution_path_hash)
        assert config.parameters["native_timing"] is True
        disabled = expand_sweep(manifest, {"native_timing": [False]})[0]
        assert disabled.status is RunStatus.PLANNED
        assert disabled.config_id != config.config_id
        disabled_keys = build_comparability_keys(
            manifest, _descriptor(), disabled, compatibility, execution, profile=profile
        )
        assert disabled_keys.semantic_key == key_sets[-1].semantic_key
        assert disabled_keys.execution_key != key_sets[-1].execution_key
        assert disabled_keys.resource_key != key_sets[-1].resource_key

    assert key_sets[0].semantic_key == key_sets[1].semantic_key
    assert key_sets[0].execution_key == key_sets[1].execution_key
    assert key_sets[0].resource_key == key_sets[1].resource_key
    assert execution_paths[0] != execution_paths[1]
    assert key_sets[2].semantic_key != key_sets[0].semantic_key
    assert key_sets[2].execution_key != key_sets[0].execution_key
    assert key_sets[2].resource_key != key_sets[0].resource_key
    assert execution_paths[2] not in execution_paths[:2]
    assert key_sets[3].semantic_key not in {item.semantic_key for item in key_sets[:3]}
    assert key_sets[3].execution_key not in {item.execution_key for item in key_sets[:3]}
    assert key_sets[3].resource_key not in {item.resource_key for item in key_sets[:3]}
    assert execution_paths[3] not in execution_paths[:3]
