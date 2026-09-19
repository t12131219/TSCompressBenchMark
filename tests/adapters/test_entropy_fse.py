import hashlib
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import EntropyAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]


def adapter(name):
    sources = SourceRegistry(ROOT / "registry/sources")
    manifest = CodecRegistry(ROOT / "registry/codecs", sources).get(name)
    artifact = ROOT / manifest.document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip(f"build {name} before testing")
    return EntropyAdapter(artifact, manifest.document["adapter"], name), manifest


def route(data):
    array = np.frombuffer(data, dtype=np.uint8).copy()
    array.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", array, array.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:entropy-test", track=BenchmarkTrack.VALUE,
        buffers=buffers, timestamp_reference=None, validity_reference=None,
        n=len(data), m=1, canonical_raw_bits=len(data) * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ["huff0", "fse"])
@pytest.mark.parametrize("length", [0, 1, 2, 7, 8, 9, 127, 128, 129, 65535, 65536, 65537, 131072])
@pytest.mark.parametrize("pattern", ["constant", "random"])
def test_roundtrip_and_exact_accounting(name, length, pattern):
    codec, _ = adapter(name)
    data = (bytes(length) if pattern == "constant"
            else np.random.default_rng(length).integers(0, 256, length, dtype=np.uint8).tobytes())
    result = perform_roundtrip(codec, route(data), {})
    assert result.decoded.by_name()["value/000000"].array.tobytes() == data
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact and result.determinism_match


@pytest.mark.parametrize("name", ["huff0", "fse"])
def test_boundary_suite_and_malformed_stream(name):
    codec, manifest = adapter(name)
    report = run_boundary_suite(codec, manifest, BenchmarkTrack.VALUE,
                                {"block_size": 128, "isa": "SCALAR"})
    assert report.passed, [item for item in report.observations if item.status != "PASS"]
    result = perform_roundtrip(codec, route(bytes(range(64)) * 4), {})
    session = codec.create_session({})
    try:
        for invalid in (result.encoded.stream[:-1], result.encoded.stream + b"x",
                        b"bad" + result.encoded.stream[3:]):
            with pytest.raises(ExecutionContractError):
                session.decompress(invalid)
    finally:
        session.close()


@pytest.mark.parametrize("name", ["huff0", "fse"])
def test_vendor_compressed_mode_and_timing(name):
    codec, _ = adapter(name)
    data = bytes([0, 1, 2, 3, 4]) * 200
    result = perform_roundtrip(codec, route(data), {})
    stream = result.encoded.stream
    mode_offset = 12 + struct.unpack_from("<I", stream, 8)[0]
    assert stream[mode_offset] == 2
    session = codec.create_session({})
    try:
        assert session.decompress(stream).by_name()["value/000000"].array.tobytes() == data
        with pytest.raises(ExecutionContractError):
            session.decompress(stream + b"x")
    finally:
        session.close()


def test_huff0_rejects_fse_rle_mode():
    codec, _ = adapter("huff0")
    stream = bytearray(perform_roundtrip(codec, route(b"x" * 100), {}).encoded.stream)
    mode_offset = 12 + struct.unpack_from("<I", stream, 8)[0]
    stream[mode_offset] = 1
    stream[mode_offset + 9:] = b"x"
    session = codec.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(bytes(stream))
    finally:
        session.close()


def test_vendored_benchmark_closure_digest():
    vendor = ROOT / "adapters/entropy_fse/vendor"
    files = sorted((vendor / "lib").iterdir()) + [vendor / "LICENSE"]
    listing = b"".join(
        hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii")
        + b"  adapters/entropy_fse/vendor/"
        + path.relative_to(vendor).as_posix().encode("ascii")
        + b"\n"
        for path in files
    )
    assert len(files) == 16
    assert hashlib.sha256(listing).hexdigest() == (
        "af5899be99f7f09551bed864832f9b80be2069a4bb8798b30486296e4d17aa8a"
    )
