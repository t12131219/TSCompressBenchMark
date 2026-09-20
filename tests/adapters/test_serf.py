import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.serf import SerfAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import validate_error_bound

ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = {
    "block_size": 17,
    "error_bound_type": "ABSOLUTE",
    "error_bound": "0.001",
    "adjust_digit": 0,
    "native_timing": True,
    "isa": "SCALAR",
}


def codec(name: str) -> SerfAdapter:
    document = json.loads((ROOT / "registry/codecs" / f"{name}.json").read_text())
    artifact = ROOT / document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip(f"build {name} first")
    return SerfAdapter(artifact, document["adapter"], name)


def parameters(name: str, **updates):
    result = dict(PARAMETERS)
    if name == "serf-qt":
        result.pop("adjust_digit")
    result.update(updates)
    return result


def route(values: np.ndarray) -> RoutedInput:
    values = np.ascontiguousarray(values)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:serf-test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=len(values),
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ["serf-qt", "serf-xor"])
@pytest.mark.parametrize("dtype", ["<f4", "<f8"])
@pytest.mark.parametrize("length", [0, 1, 2, 16, 17, 18, 33, 34, 35])
def test_block_boundaries_obey_strict_absolute_error(name, dtype, length):
    values = np.linspace(-10, 10, length, dtype=dtype)
    result = perform_roundtrip(codec(name), route(values), parameters(name))
    report = validate_error_bound(
        {"value/000000": values},
        {"value/000000": result.decoded.buffers[0].array},
        error_bound_type="ABSOLUTE",
        error_bound="0.001",
    )
    assert report.raw_violation_count == 0
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match


@pytest.mark.parametrize("name", ["serf-qt", "serf-xor"])
@pytest.mark.parametrize("dtype", ["<f4", "<f8"])
def test_nonfinite_and_ieee_edge_values_use_charged_exact_exception_block(name, dtype):
    if dtype == "<f8":
        bits = np.asarray(
            [
                0,
                0x8000000000000000,
                0x7FF0000000000000,
                0xFFF0000000000000,
                0x0000000000000001,
                0x8000000000000001,
                0x7FF8000000001234,
            ],
            dtype="<u8",
        )
        values = bits.view("<f8")
    else:
        bits = np.asarray(
            [0, 0x80000000, 0x7F800000, 0xFF800000, 1, 0x80000001, 0x7FC01234],
            dtype="<u4",
        )
        values = bits.view("<f4")
    result = perform_roundtrip(codec(name), route(values), parameters(name))
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()


@pytest.mark.parametrize("name", ["serf-qt", "serf-xor"])
def test_truncated_trailing_and_mutated_frames_are_rejected(name):
    result = perform_roundtrip(
        codec(name), route(np.linspace(-2, 2, 35, dtype="<f8")), parameters(name)
    )
    stream = result.encoded.stream
    header_size = struct.unpack_from("<I", stream, 8)[0]
    payload_offset = 12 + header_size
    mutated = bytearray(stream)
    mutated[payload_offset + 8] ^= 1
    session = codec(name).create_session(parameters(name))
    try:
        for malformed in (stream[:-1], stream + b"x", bytes(mutated)):
            with pytest.raises(ExecutionContractError):
                session.decompress(malformed)
    finally:
        session.close()


@pytest.mark.parametrize("name", ["serf-qt", "serf-xor"])
def test_two_dimensional_input_preserves_all_columns_within_bound(name):
    matrix = np.column_stack(
        (
            np.linspace(-3, 3, 35, dtype="<f8"),
            np.sin(np.arange(35, dtype="<f8")),
            np.full(35, 7.5, dtype="<f8"),
        )
    )
    matrix.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", matrix, matrix.nbytes * 8),)
    routed = RoutedInput(
        dataset_id="dataset:serf-matrix",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=35,
        m=3,
        canonical_raw_bits=matrix.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )
    result = perform_roundtrip(codec(name), routed, parameters(name))
    restored = result.decoded.buffers[0].array
    assert restored.shape == matrix.shape
    assert np.max(np.abs(matrix.astype(np.longdouble) - restored.astype(np.longdouble))) <= 0.001


@pytest.mark.parametrize("name", ["serf-qt", "serf-xor"])
def test_zero_error_bound_is_explicitly_rejected(name):
    with pytest.raises(ExecutionContractError, match="unregistered Serf execution parameters"):
        codec(name).create_session(parameters(name, error_bound="0"))


def test_source_closure_patch_set_and_registry_identity_are_reproducible():
    source_path = ROOT / "registry/sources/serf-upstream-benchmark.artifact.json"
    source = json.loads(source_path.read_text())
    vendor = ROOT / source["identity"]["source_path"]
    files = sorted(path for path in vendor.rglob("*") if path.is_file())
    closure = hashlib.sha256()
    for path in files:
        closure.update(path.relative_to(vendor).as_posix().encode() + b"\0")
        closure.update(path.read_bytes())
    assert len(files) == source["identity"]["source_closure_file_count"] == 35
    assert closure.hexdigest() == source["identity"]["source_closure_sha256"]

    patch_lines = bytearray()
    for relative in source["build"]["patches"]:
        path = ROOT / relative
        patch_lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        patch_lines.extend(b"  " + relative.encode() + b"\n")
    assert hashlib.sha256(patch_lines).hexdigest() == source["identity"]["patch_set_sha256"]

    sources = SourceRegistry(ROOT / "registry/sources")
    codecs = CodecRegistry(ROOT / "registry/codecs", sources)
    assert codecs.get("serf-qt").source_artifact_id == codecs.get("serf-xor").source_artifact_id

    card = json.loads((ROOT / "registry/onboarding/serf.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == codecs.get(
        "serf-qt"
    ).source_artifact_id
