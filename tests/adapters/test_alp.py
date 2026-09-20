import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import AlpAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers

ROOT = Path(__file__).resolve().parents[2]


def codec(name: str) -> AlpAdapter:
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(name)
    artifact = ROOT / manifest.document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip(f"build {name} first")
    return AlpAdapter(artifact, manifest.document["adapter"], name)


def route(values: np.ndarray) -> RoutedInput:
    values = np.ascontiguousarray(values)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:alp-test", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=len(values), m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ["alp", "alp-rd"])
@pytest.mark.parametrize("dtype", ["<f4", "<f8"])
@pytest.mark.parametrize("length", [0, 1, 2, 1023, 1024, 1025, 102399, 102400, 102401])
def test_vector_and_rowgroup_boundaries_are_bit_exact(name, dtype, length):
    values = (np.arange(length, dtype=np.float64) / 10).astype(dtype)
    result = perform_roundtrip(codec(name), route(values), {})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match
    assert result.encoded.native_encode_wall_ns is not None


@pytest.mark.parametrize("name", ["alp", "alp-rd"])
def test_ieee_special_values_preserve_payload_bits(name):
    values = np.arange(2048, dtype="<f8") / 10
    bits = values.view("<u8")
    bits[[3, 20, 40, 60, 80, 100, 120]] = [
        0x8000000000000000, 0x7FF0000000000000, 0xFFF0000000000000,
        0x0000000000000001, 0x8000000000000001,
        0x7FF8000000000001, 0x7FF8000000001234,
    ]
    result = perform_roundtrip(codec(name), route(values), {})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()


@pytest.mark.parametrize("name", ["alp", "alp-rd"])
def test_truncated_and_trailing_native_frames_are_rejected(name):
    values = np.arange(1025, dtype="<f8") / 10
    result = perform_roundtrip(codec(name), route(values), {})
    session = codec(name).create_session({})
    try:
        stream = result.encoded.stream
        header_size = struct.unpack_from("<I", stream, 8)[0]
        assert len(stream) > 12 + header_size + 24
        for malformed in (stream[:-1], stream + b"x"):
            with pytest.raises(ExecutionContractError):
                session.decompress(malformed)
    finally:
        session.close()


def test_forced_alp_never_silently_executes_alp_rd():
    rng = np.random.default_rng(20260920)
    values = rng.integers(0, 2**64, 4096, dtype="<u8").view("<f8")
    with pytest.raises(ExecutionContractError, match=r"failed \(2\)"):
        perform_roundtrip(codec("alp"), route(values), {})


def test_two_dimensional_input_is_not_reduced_to_first_column():
    matrix = (np.arange(3075, dtype=np.float64) / 100).reshape(1025, 3)
    matrix.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", matrix, matrix.nbytes * 8),)
    routed = RoutedInput(
        dataset_id="dataset:alp-matrix", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=1025, m=3,
        canonical_raw_bits=matrix.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )
    result = perform_roundtrip(codec("alp-rd"), routed, {})
    assert result.decoded.buffers[0].array.tobytes() == matrix.tobytes()
