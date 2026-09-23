import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.zfp import ZfpAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import validate_error_bound

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = {
    "mode": "FIXED_ACCURACY",
    "error_bound_type": "ABSOLUTE",
    "error_bound": "0.001",
    "dimensionality": "1D_PER_COLUMN",
    "header": "FULL",
    "backend": "SERIAL",
    "native_timing": True,
    "isa": "SCALAR",
}


def codec() -> ZfpAdapter:
    document = json.loads((ROOT / "registry/codecs/zfp-accuracy-1d.json").read_text())
    artifact = ROOT / document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip("build zfp-accuracy-1d first")
    return ZfpAdapter(artifact, document["adapter"])


def route(values: np.ndarray) -> RoutedInput:
    values = np.ascontiguousarray(values)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:zfp-test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=len(values),
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("dtype", ["<f4", "<f8"])
@pytest.mark.parametrize("length", [0, 1, 2, 3, 4, 5, 7, 8, 9, 17])
def test_1d_block_boundaries_obey_requested_absolute_error(dtype, length):
    values = np.linspace(-10, 10, length, dtype=dtype)
    result = perform_roundtrip(codec(), route(values), PARAMETERS)
    report = validate_error_bound(
        {"value/000000": values},
        {"value/000000": result.decoded.buffers[0].array},
        error_bound_type="ABSOLUTE",
        error_bound="0.001",
    )
    assert report.raw_violation_count == 0
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match


@pytest.mark.parametrize("dtype", ["<f4", "<f8"])
def test_ieee_exception_column_is_exact_and_fully_charged(dtype):
    if dtype == "<f8":
        bits = np.asarray(
            [0, 0x8000000000000000, 1, 0x7FF0000000000000, 0xFFF0000000000000,
             0x7FF8000000001234],
            dtype="<u8",
        )
    else:
        bits = np.asarray(
            [0, 0x80000000, 1, 0x7F800000, 0xFF800000, 0x7FC01234],
            dtype="<u4",
        )
    values = bits.view(dtype)
    result = perform_roundtrip(codec(), route(values), PARAMETERS)
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    header_size = struct.unpack_from("<I", result.encoded.stream, 8)[0]
    frame = result.encoded.stream[12 + header_size :]
    assert frame[38] == 1


def test_requested_and_actual_tolerance_are_recorded_and_match_native_frame():
    result = perform_roundtrip(
        codec(), route(np.linspace(-2, 2, 9, dtype="<f8")), PARAMETERS
    )
    header_size = struct.unpack_from("<I", result.encoded.stream, 8)[0]
    descriptor = json.loads(result.encoded.stream[12 : 12 + header_size])
    frame = result.encoded.stream[12 + header_size :]
    requested, actual = struct.unpack_from("<dd", frame, 18)
    assert descriptor["requested_error_bound"] == "0.001"
    assert descriptor["actual_error_bound_hex"] == actual.hex()
    assert actual == 0.0009765625
    assert actual <= requested == 0.001


def test_truncated_trailing_and_mutated_frames_are_rejected():
    result = perform_roundtrip(
        codec(), route(np.linspace(-2, 2, 17, dtype="<f8")), PARAMETERS
    )
    stream = result.encoded.stream
    header_size = struct.unpack_from("<I", stream, 8)[0]
    payload_offset = 12 + header_size
    mutated = bytearray(stream)
    mutated[payload_offset + 10] ^= 1
    session = codec().create_session(PARAMETERS)
    try:
        for malformed in (stream[:-1], stream + b"x", bytes(mutated)):
            with pytest.raises(ExecutionContractError):
                session.decompress(malformed)
    finally:
        session.close()


def test_two_dimensional_input_preserves_all_columns_within_bound():
    matrix = np.column_stack(
        (
            np.linspace(-3, 3, 17, dtype="<f8"),
            np.sin(np.arange(17, dtype="<f8")),
            np.full(17, 7.5, dtype="<f8"),
        )
    )
    matrix.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", matrix, matrix.nbytes * 8),)
    routed = RoutedInput(
        dataset_id="dataset:zfp-matrix",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=17,
        m=3,
        canonical_raw_bits=matrix.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )
    result = perform_roundtrip(codec(), routed, PARAMETERS)
    restored = result.decoded.buffers[0].array
    assert restored.shape == matrix.shape
    assert np.max(np.abs(matrix.astype(np.longdouble) - restored.astype(np.longdouble))) <= 0.001


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("error_bound", "0"),
        ("mode", "FIXED_RATE"),
        ("dimensionality", "NATIVE_ND"),
        ("backend", "CUDA"),
        ("header", "NONE"),
    ],
)
def test_unregistered_modes_are_rejected(key, value):
    parameters = dict(PARAMETERS)
    parameters[key] = value
    with pytest.raises(ExecutionContractError, match="unregistered zfp execution parameters"):
        codec().create_session(parameters)


def test_source_closure_registry_and_onboarding_identity_are_reproducible():
    source_path = ROOT / "registry/sources/zfp-upstream-benchmark.artifact.json"
    source = json.loads(source_path.read_text())
    vendor = ROOT / source["identity"]["source_path"]
    files = sorted(path for path in vendor.rglob("*") if path.is_file())
    closure = hashlib.sha256()
    for path in files:
        closure.update(path.relative_to(vendor).as_posix().encode() + b"\0")
        closure.update(path.read_bytes())
    assert len(files) == source["identity"]["source_closure_file_count"] == 94
    assert closure.hexdigest() == source["identity"]["source_closure_sha256"]

    sources = SourceRegistry(ROOT / "registry/sources")
    codecs = CodecRegistry(ROOT / "registry/codecs", sources)
    manifest = codecs.get("zfp-accuracy-1d")
    card = json.loads((ROOT / "registry/onboarding/zfp.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == manifest.source_artifact_id
