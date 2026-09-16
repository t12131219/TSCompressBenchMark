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
from tscompbench.planning import expand_sweep, resolve_execution

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
