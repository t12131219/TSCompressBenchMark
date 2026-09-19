from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    RunStatus,
    Topology,
    ValidityShape,
)
from tscompbench.planning import expand_sweep, resolve_execution

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["sprintz-delta-u8", "sprintz-fire-u8"])
def test_u8_direct_float_rejected_and_composite_isa(name, tmp_path):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(name)
    descriptor = DataDescriptor(
        dataset_id="dataset:test", track=BenchmarkTrack.VALUE, topology=Topology.UTS,
        n=128, m=1, shape=(128,), dtype_vector=("|u1",),
        physical_layout="ROW_MAJOR_CONTIG", endianness="little", alignment_bytes=1,
        canonical_raw_bits=1024, validity_shape=ValidityShape.NONE,
        timestamp_present=False, preserve_order=False, has_duplicates=False,
        has_out_of_order=False, has_negative_delta=False,
    )
    compatible = negotiate(manifest, descriptor)
    assert compatible.status is CapabilityStatus.DIRECT_SUPPORTED
    bad = negotiate(manifest, DataDescriptor(**{**descriptor.__dict__, "dtype_vector": ("<f8",)}))
    assert bad.status is not CapabilityStatus.DIRECT_SUPPORTED
    config = expand_sweep(manifest, {})[0]
    assert config.parameters["isa"] == "AVX2_BMI2_LZCNT"
    assert expand_sweep(manifest, {"isa": ["AVX2"]})[0].status is RunStatus.SCHEMA_ERROR
    artifact = tmp_path / "binary"
    artifact.write_bytes(b"fixture")
    profile = dict(
        threads=1, processes=1, runner_version="test",
        allocation_policy="PER_REPETITION", cache_policy="WARM_INPUT",
        state_policy="RESET_PER_REPETITION", gc_policy="DISABLED_DURING_TIMING",
        jit_policy="NOT_APPLICABLE",
    )
    statuses = []
    for flags in (["avx2", "bmi2", "abm"], ["avx2", "abm"], ["avx2", "bmi2"]):
        statuses.append(resolve_execution(
            manifest, config, compatible,
            {"environment_id": "environment:test", "cpu": {"flags": flags, "affinity": [0]}},
            artifact_path=artifact, profile=profile,
        ).status)
    assert statuses == [RunStatus.PLANNED, RunStatus.ISA_UNSUPPORTED, RunStatus.ISA_UNSUPPORTED]
