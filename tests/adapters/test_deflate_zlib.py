from __future__ import annotations

import hashlib
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import DeflateZlibAdapter
from tscompbench.adapters.deflate_zlib import _PREFIX, DeflateZlibSession
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = PROJECT_ROOT / "build/adapters/deflate_zlib/release/libtscb_deflate_zlib.so"


def _adapter_and_manifest():
    if not LIBRARY.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", "deflate-zlib", "--profile", "release"],
            cwd=PROJECT_ROOT, check=True,
        )
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("deflate-zlib")
    return DeflateZlibAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n=4):
    bits = np.resize(np.asarray([
        0, 0x8000000000000000, 0x7FF0000000000000, 0xFFF0000000000000,
        0x7FF8000000000001, 0x7FF8000000000123, 1, 0x3FF0000000000001,
    ], dtype="<u8"), n)
    arrays = (bits.view("<f8"), bits[::-1].copy().view("<f8"))
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate(arrays)
    )
    return RoutedInput(
        dataset_id="dataset:deflate-adapter", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=n, m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


def _chunk(routed, start, stop):
    buffers = tuple(
        LogicalBuffer(
            item.name,
            item.array[start:stop],
            item.array[start:stop].nbytes * 8,
        )
        for item in routed.buffers
    )
    return RoutedInput(
        dataset_id=routed.dataset_id,
        track=routed.track,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=stop - start,
        m=routed.m,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )
def test_multiple_buffers_ieee_bits_envelope_and_external_decoder():
    adapter, _ = _adapter_and_manifest()
    routed = _route(8)
    result = perform_roundtrip(adapter, routed, {})
    for item in routed.buffers:
        assert result.decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
    header, stream = DeflateZlibSession._parse_container(result.encoded.stream)
    payload = b"".join(item.array.tobytes() for item in routed.buffers)
    assert zlib.decompress(stream) == payload
    assert int.from_bytes(stream[-4:], "big") == zlib.adler32(payload)
    ledger = result.encoded.ledger
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert ledger.container_bits == (_PREFIX.size + 2) * 8
    assert ledger.checksum_bits == 32
    assert ledger.value_bits == (len(stream) - 6) * 8
    assert ledger.accounting_method == "EXACT_TSCB_CONTAINER_ZLIB_ENVELOPE_AND_DEFLATE_LENGTH"
    assert header["schema_version"] == "tscb.deflate-zlib-container.v1"
    assert result.encoded.finalize_bytes > 0
    assert result.determinism_match and result.input_immutable and result.canary_intact


@pytest.mark.parametrize("level", range(10))
@pytest.mark.parametrize("window", [9, 15])
@pytest.mark.parametrize("n", [0, 1, 2, 65537])
def test_bound_tails_and_parameter_extremes(level, window, n):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(
        adapter, _route(n), {"compression_level": level, "window_bits": window}
    )
    _, stream = DeflateZlibSession._parse_container(result.encoded.stream)
    assert stream[0] >> 4 == window - 8
    assert result.determinism_match and result.canary_intact


def test_framework_boundary_suite():
    adapter, manifest = _adapter_and_manifest()
    report = run_boundary_suite(
        adapter, manifest, BenchmarkTrack.VALUE,
        {"block_size": 8, "compression_level": 6, "window_bits": 15, "isa": "SCALAR"},
    )
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize("n", [0, 1, 2, 7, 8, 9, 17])
@pytest.mark.parametrize("block_size", [1, 8])
def test_native_streaming_session_preserves_state_across_blocks(n, block_size):
    adapter, _ = _adapter_and_manifest()
    routed = _route(n)
    before = tuple(item.array.tobytes() for item in routed.buffers)
    session = adapter.create_stream_session(
        {
            "compression_level": 6,
            "window_bits": 15,
            "stream_decode_chunk_bytes": 3,
            "block_size": block_size,
        }
    )
    parts = []
    try:
        session.stream_start(routed)
        states = []
        for start in range(0, n, block_size):
            result = session.stream_push(_chunk(routed, start, min(n, start + block_size)))
            parts.append(result.emitted)
            states.append(result.state_bytes)
            assert result.buffer_bytes == 0
            assert result.checkpoint_bits == 0
        parts.append(session.stream_finalize())
        stream = b"".join(parts)
        header, zlib_stream = DeflateZlibSession._parse_container(stream)
        assert zlib.decompress(zlib_stream) == DeflateZlibSession._serialized_payload(
            routed, header
        )
        decoded = session.stream_decompress(stream)
        observed = tuple(
            decoded.by_name()[item.name].array.tobytes() for item in routed.buffers
        )
        assert observed == before
        ledger = session.stream_accounting(stream, routed)
        assert ledger.final_bits == len(stream) * 8
        assert header["buffers"][0]["shape"] == [n]
        assert all(value > 0 for value in states)
        with pytest.raises(ExecutionContractError):
            session.stream_finalize()
        with pytest.raises(ExecutionContractError):
            session.stream_push(_chunk(routed, 0, 0))
    finally:
        session.close()
    assert tuple(item.array.tobytes() for item in routed.buffers) == before


@pytest.mark.parametrize("mutation", ["truncated", "checksum", "trailing"])
def test_streaming_decoder_rejects_nonexact_stream(mutation):
    adapter, _ = _adapter_and_manifest()
    routed = _route(9)
    session = adapter.create_stream_session(
        {"stream_decode_chunk_bytes": 2, "block_size": 4}
    )
    try:
        session.stream_start(routed)
        first = session.stream_push(_chunk(routed, 0, 4)).emitted
        second = session.stream_push(_chunk(routed, 4, 8)).emitted
        third = session.stream_push(_chunk(routed, 8, 9)).emitted
        stream = first + second + third + session.stream_finalize()
        _, zlib_stream = DeflateZlibSession._parse_container(stream)
        prefix = stream[: -len(zlib_stream)]
        altered = {
            "truncated": zlib_stream[:-1],
            "checksum": zlib_stream[:-1] + bytes([zlib_stream[-1] ^ 1]),
            "trailing": zlib_stream + b"x",
        }[mutation]
        with pytest.raises(ExecutionContractError):
            session.stream_decompress(prefix + altered)
    finally:
        session.close()


def test_streaming_lifecycle_requires_start_and_complete_declared_rows():
    adapter, _ = _adapter_and_manifest()
    routed = _route(4)
    session = adapter.create_stream_session({"block_size": 2})
    try:
        with pytest.raises(ExecutionContractError):
            session.stream_finalize()
        session.stream_start(routed)
        session.stream_push(_chunk(routed, 0, 2))
        with pytest.raises(ExecutionContractError):
            session.stream_finalize()
        with pytest.raises(ExecutionContractError):
            session.stream_start(routed)
    finally:
        session.close()


def test_streaming_incompressible_multiblock_pending_output_bound():
    rng = np.random.default_rng(20260923)
    arrays = tuple(rng.integers(0, 256, size=8192, dtype=np.uint8) for _ in range(3))
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate(arrays)
    )
    routed = RoutedInput(
        dataset_id="dataset:deflate-streaming-high-entropy",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=8192,
        m=3,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )
    adapter, _ = _adapter_and_manifest()
    session = adapter.create_stream_session({"block_size": 128})
    parts = []
    try:
        session.stream_start(routed)
        for start in range(0, routed.n, 128):
            parts.append(session.stream_push(_chunk(routed, start, start + 128)).emitted)
        parts.append(session.stream_finalize())
        stream = b"".join(parts)
        decoded = session.stream_decompress(stream)
        assert all(
            decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
            for item in routed.buffers
        )
    finally:
        session.close()


@pytest.mark.parametrize(
    "mutation", ["truncated", "trailing", "concatenated", "checksum", "header"]
)
def test_independent_decoder_rejects_nonexact_or_corrupt_streams(mutation):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(adapter, _route(), {})
    container = result.encoded.stream
    _, stream = DeflateZlibSession._parse_container(container)
    prefix = container[:-len(stream)]
    altered = {
        "truncated": stream[:-1], "trailing": stream + b"x",
        "concatenated": stream + stream,
        "checksum": stream[:-1] + bytes([stream[-1] ^ 1]),
        "header": bytes([stream[0] ^ 1]) + stream[1:],
    }[mutation]
    session = adapter.create_session({})
    try:
        assert session.decompress(container).by_name()["value/000000"].array.shape == (4,)
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + altered)
    finally:
        session.close()


@pytest.mark.parametrize("parameters", [
    {"compression_level": -1}, {"compression_level": 10},
    {"window_bits": 8}, {"window_bits": 16},
])
def test_invalid_parameters_rejected(parameters):
    adapter, _ = _adapter_and_manifest()
    with pytest.raises(ExecutionContractError):
        adapter.create_session(parameters)


def test_vendored_closure_digest():
    root = PROJECT_ROOT / "adapters/deflate_zlib/vendor/zlib"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == 48
    assert digest.hexdigest() == "90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0"
