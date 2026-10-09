from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.compatibility import apply_compatibility_plan, validate_prepared_input
from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import BenchmarkTrack, LossMode, RunStatus, Topology, ValidityShape
from tscompbench.execution.protocol import DecodedOutput, LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation.correctness import validate_common_correctness


ROOT = Path(__file__).resolve().parents[2]


def setup_case(key, values):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    descriptor = DataDescriptor(
        dataset_id="test:integer-lossy", track=BenchmarkTrack.VALUE, topology=Topology.UTS,
        n=values.size, m=1, shape=values.shape, dtype_vector=(values.dtype.str,),
        physical_layout="SOA_COLUMNS", endianness="little", alignment_bytes=1,
        canonical_raw_bits=values.nbytes * 8, validity_shape=ValidityShape.NONE,
        timestamp_present=False, preserve_order=True, has_duplicates=False,
        has_out_of_order=False, has_negative_delta=False,
    )
    plan = negotiate(registry.get(key), descriptor)
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    routed = RoutedInput(
        dataset_id=descriptor.dataset_id, track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=values.size, m=1,
        canonical_raw_bits=values.nbytes * 8, input_sha256=hash_logical_buffers(buffers),
    )
    return plan, routed


@pytest.mark.parametrize("key", ["abba", "fabba", "corad", "tristan"])
def test_unbounded_integer_cast_needs_no_absolute_bound(key):
    original = np.array([100, 200, 300, 400], dtype="<i8")
    plan, routed = setup_case(key, original)
    assert plan.effective_loss_mode is LossMode.UNBOUNDED_LOSSY
    prepared = apply_compatibility_plan(original, plan)
    validate_prepared_input(original, prepared, plan)
    decoded = DecodedOutput((LogicalBuffer("value/000000", prepared.logical_array + 0.2, 256),))
    result = validate_common_correctness(
        routed, decoded, plan, loss_mode=plan.effective_loss_mode, parameters={},
        deterministic_match=True, input_immutable=True, canary_intact=True,
    )
    assert result.status is RunStatus.PASS
    assert float(result.loss.channels[0].max_ae) == pytest.approx(0.2)
    wrong_dtype = DecodedOutput((LogicalBuffer("value/000000", original.copy(), 256),))
    assert validate_common_correctness(
        routed, wrong_dtype, plan, loss_mode=plan.effective_loss_mode, parameters={},
        deterministic_match=True, input_immutable=True, canary_intact=True,
    ).status is RunStatus.CORRECTNESS_FAIL


@pytest.mark.parametrize("key", [
    "maskedvbyte-u32", "delta-maskedvbyte-u32", "fast-differential-u32",
    "simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32",
    "simple9-u28", "simple9hacked-u28", "simple16-u28", "fastpfor-simple8b-rle-u32",
    "littleintpacker-pack32-u32", "littleintpacker-turbo-u32", "littleintpacker-sc-u32",
    "littleintpacker-bmi2-u32", "littleintpacker-horizontal-u32",
])
def test_integer_codec_roundtrip_after_lossless_widening_keeps_canonical_bits(key):
    from tscompbench.adapters.maskedvbyte import MaskedVByteAdapter
    from tscompbench.adapters.fast_differential import FastDifferentialAdapter
    from tscompbench.adapters.simdcomp import SIMDCompAdapter
    from tscompbench.adapters.fastpfor_simple import FastPFORSimpleAdapter
    from tscompbench.adapters.fastpfor_simple8b_rle import FastPFORSimple8bRLEAdapter
    from tscompbench.adapters.littleintpacker import LittleIntPackerAdapter
    from tscompbench.execution.preparation import prepare_execution_input
    from tscompbench.execution.repetition import perform_roundtrip

    original = np.arange(2048, dtype="<u2").astype("|u1")
    plan, routed = setup_case(key, original)
    assert plan.effective_loss_mode is LossMode.LOSSLESS
    prepared = prepare_execution_input(routed, plan)
    assert prepared.codec_input.canonical_raw_bits == original.nbytes * 8
    assert prepared.codec_input.buffers[0].logical_bits == original.size * 32
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(key)
    cls = (
        MaskedVByteAdapter if "maskedvbyte" in key else
        FastDifferentialAdapter if key == "fast-differential-u32" else
        SIMDCompAdapter if "simdcomp" in key else
        FastPFORSimple8bRLEAdapter if "simple8b-rle" in key else
        LittleIntPackerAdapter if "littleintpacker" in key else FastPFORSimpleAdapter
    )
    args = (ROOT / manifest.document["adapter"]["artifact_path"], manifest.document["adapter"])
    adapter = cls(*args) if cls is FastDifferentialAdapter else cls(*args, key)
    observation = perform_roundtrip(adapter, prepared.codec_input, {})
    assert observation.encoded.ledger.canonical_raw_bits == original.nbytes * 8
    assert observation.encoded.ledger.final_bits == len(observation.encoded.stream) * 8
    result = validate_common_correctness(
        routed, observation.decoded, plan, loss_mode=LossMode.LOSSLESS, parameters={},
        deterministic_match=observation.determinism_match,
        input_immutable=observation.input_immutable, canary_intact=observation.canary_intact,
    )
    assert result.status is RunStatus.PASS


@pytest.mark.parametrize("delta,expected", [(0.0001, RunStatus.PASS), (0.01, RunStatus.BOUND_VIOLATION)])
def test_bounded_integer_reconstruction_is_compared_before_integer_truncation(delta, expected):
    original = np.array([100, 200], dtype="<i8")
    plan, routed = setup_case("serf-qt", original)
    decoded = DecodedOutput((LogicalBuffer("value/000000", original.astype("<f8") - delta, 128),))
    result = validate_common_correctness(
        routed, decoded, plan, loss_mode=LossMode.ERROR_BOUNDED_LOSSY,
        parameters={"error_bound": "0.001"}, deterministic_match=True,
        input_immutable=True, canary_intact=True,
    )
    assert result.status is expected
    assert float(result.loss.channels[0].max_ae) == pytest.approx(delta)


def test_bounded_cast_still_requires_a_bound():
    original = np.array([100, 200], dtype="<i8")
    plan, _ = setup_case("serf-qt", original)
    prepared = apply_compatibility_plan(original, plan)
    with pytest.raises(ValueError, match="declared error bound"):
        validate_prepared_input(original, prepared, plan)


@pytest.mark.parametrize("key", ["abba", "fabba", "corad"])
@pytest.mark.parametrize("dtype", ["<i2", "|u1"])
def test_rewrite_roundtrip_after_widening_preserves_original_denominator(key, dtype):
    from tscompbench.adapters.completed_rewrites import CompletedRewriteAdapter
    from tscompbench.execution.preparation import prepare_execution_input
    from tscompbench.execution.repetition import perform_roundtrip

    original = np.array([1, 3, 2, 6, 8, 7, 10, 12] * 10, dtype=dtype)
    plan, routed = setup_case(key, original)
    prepared = prepare_execution_input(routed, plan)
    assert prepared.codec_input.buffers[0].array.dtype.str == "<f8"
    assert prepared.codec_input.canonical_raw_bits == original.nbytes * 8
    assert prepared.codec_input.buffers[0].logical_bits == original.size * 64
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(key)
    adapter = CompletedRewriteAdapter(
        ROOT / manifest.document["adapter"]["artifact_path"], manifest.document["adapter"], key
    )
    observation = perform_roundtrip(adapter, prepared.codec_input, {})
    ledger = observation.encoded.ledger
    assert ledger.canonical_raw_bits == original.nbytes * 8
    assert ledger.final_bits == len(observation.encoded.stream) * 8
    result = validate_common_correctness(
        routed, observation.decoded, plan, loss_mode=plan.effective_loss_mode, parameters={},
        deterministic_match=observation.determinism_match,
        input_immutable=observation.input_immutable, canary_intact=observation.canary_intact,
    )
    assert result.status is RunStatus.PASS
