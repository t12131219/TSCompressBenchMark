from pathlib import Path

from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import BenchmarkTrack, RunStatus, Topology, ValidityShape
from tscompbench.planning import expand_sweep, resolve_execution

ROOT = Path(__file__).resolve().parents[2]


def test_sse41_supported_missing_no_scalar_fallback_and_parameter_identity(tmp_path):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("lzsse8-raw")
    descriptor = DataDescriptor(
        dataset_id="dataset:test",
        track=BenchmarkTrack.VALUE,
        topology=Topology.UTS,
        n=4,
        m=1,
        shape=(4,),
        dtype_vector=("<f8",),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=256,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    compatibility = negotiate(manifest, descriptor)
    configuration = expand_sweep(manifest, {})[0]
    assert configuration.parameters["compression_level"] == 12
    assert configuration.parameters["native_timing"] is True
    assert manifest.algorithm_id != registry.get("lzss-raw").algorithm_id
    assert expand_sweep(manifest, {"compression_level": [1]})[0].status is RunStatus.SCHEMA_ERROR
    assert expand_sweep(manifest, {"isa": ["SCALAR"]})[0].status is RunStatus.SCHEMA_ERROR
    artifact = tmp_path / "binary"
    artifact.write_bytes(b"fixture")
    profile = dict(
        threads=1,
        processes=1,
        runner_version="test",
        allocation_policy="PER_REPETITION",
        cache_policy="WARM_INPUT",
        state_policy="RESET_PER_REPETITION",
        gc_policy="DISABLED_DURING_TIMING",
        jit_policy="NOT_APPLICABLE",
    )
    resolutions = []
    for flags in (["sse4_1"], []):
        environment = {
            "environment_id": "environment:test",
            "cpu": {"flags": flags, "affinity": [0]},
        }
        resolutions.append(
            resolve_execution(
                manifest,
                configuration,
                compatibility,
                environment,
                artifact_path=artifact,
                profile=profile,
            )
        )
    supported, missing = resolutions
    assert supported.status is RunStatus.PLANNED and supported.actual_isa == "SSE4_1"
    assert missing.status is RunStatus.ISA_UNSUPPORTED and missing.actual_isa == "NOT_EXECUTED"
    assert not missing.fallback_used
    assert supported.execution_path_hash != missing.execution_path_hash
