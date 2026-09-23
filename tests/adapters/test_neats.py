import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import NeatsAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.measurement.workloads import QueryRequest

ROOT = Path(__file__).resolve().parents[2]
ALGORITHMS = ("neats-lossless-i64", "leats-lossless-i64")


def codec(name: str) -> NeatsAdapter:
    sources = SourceRegistry(ROOT / "registry/sources")
    manifest = CodecRegistry(ROOT / "registry/codecs", sources).get(name)
    artifact = ROOT / manifest.document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip(f"build {name} first")
    return NeatsAdapter(artifact, manifest.document["adapter"], name)


def route(values: np.ndarray) -> RoutedInput:
    values = np.ascontiguousarray(values)
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:neats-test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=values.shape[0],
        m=1 if values.ndim == 1 else values.shape[1],
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ALGORITHMS)
@pytest.mark.parametrize("dtype", ["|i1", "<i2", "<i4", "<i8"])
@pytest.mark.parametrize("length", [1, 2, 3, 17, 128])
def test_signed_integer_roundtrip_boundaries(name, dtype, length):
    values = ((np.arange(length, dtype=np.int64) ** 2) % 101 - 50).astype(dtype)
    result = perform_roundtrip(
        codec(name), route(values), {"max_bpc": 16, "native_timing": True, "isa": "SCALAR"}
    )
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert result.encoded.ledger.model_bits > 0
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match
    assert result.encoded.native_encode_wall_ns is not None


@pytest.mark.parametrize("name", ALGORITHMS)
def test_matrix_and_native_random_access(name):
    rows = np.arange(96, dtype=np.int64)
    matrix = np.stack((rows - 60, (rows * rows) % 211 - 100, 3 * rows - 20), axis=1).astype("<i2")
    result = perform_roundtrip(codec(name), route(matrix), {"max_bpc": 16})
    assert result.decoded.buffers[0].array.tobytes() == matrix.tobytes()
    session = codec(name).create_session({"max_bpc": 16})
    try:
        query = session.query(result.encoded.stream, QueryRequest(7, 19, (0, 2)))
    finally:
        session.close()
    assert query.buffers[0].array.tobytes() == matrix[7:26, 0].tobytes()
    assert query.buffers[1].array.tobytes() == matrix[7:26, 2].tobytes()
    assert query.decoded_elements == 38
    assert query.bytes_touched == 2 * (
        len(result.encoded.stream) - 12 - struct.unpack_from("<I", result.encoded.stream, 8)[0]
    )


@pytest.mark.parametrize("name", ALGORITHMS)
def test_truncated_corrupt_and_trailing_frames_are_rejected(name):
    values = (np.arange(64, dtype=np.int64) - 20).astype("<i2")
    result = perform_roundtrip(codec(name), route(values), {"max_bpc": 16})
    session = codec(name).create_session({"max_bpc": 16})
    try:
        stream = result.encoded.stream
        corrupted = bytearray(stream)
        corrupted[-1] ^= 1
        for malformed in (stream[:-1], bytes(corrupted), stream + b"x"):
            with pytest.raises(ExecutionContractError):
                session.decompress(malformed)
        with pytest.raises(ExecutionContractError):
            session.query(stream, QueryRequest(63, 2, (0,)))
    finally:
        session.close()


def test_source_closure_patch_set_and_registry_identity_are_reproducible():
    source = json.loads(
        (ROOT / "registry/sources/neats-upstream-benchmark.artifact.json").read_text()
    )
    vendor = ROOT / source["identity"]["source_path"]
    files = sorted(path for path in vendor.rglob("*") if path.is_file())
    closure = hashlib.sha256()
    for path in files:
        closure.update(path.relative_to(vendor).as_posix().encode() + b"\0")
        closure.update(path.read_bytes())
    assert len(files) == source["identity"]["source_closure_file_count"] == 172
    assert closure.hexdigest() == source["identity"]["source_closure_sha256"]
    patch_lines = bytearray()
    for relative in source["build"]["patches"]:
        path = ROOT / relative
        patch_lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode())
        patch_lines.extend(b"  " + relative.encode() + b"\n")
    assert hashlib.sha256(patch_lines).hexdigest() == source["identity"]["patch_set_sha256"]
    sources = SourceRegistry(ROOT / "registry/sources")
    codecs = CodecRegistry(ROOT / "registry/codecs", sources)
    assert (
        codecs.get(ALGORITHMS[0]).source_artifact_id
        == codecs.get(ALGORITHMS[1]).source_artifact_id
    )
    card = json.loads((ROOT / "registry/onboarding/neats.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == codecs.get(
        ALGORITHMS[0]
    ).source_artifact_id
