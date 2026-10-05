from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import (
    BrotliStreamAdapter,
    Bzip2StreamAdapter,
    Lz4FrameAdapter,
    XzStreamAdapter,
    ZstdFrameAdapter,
)
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_CASES = (
    ("lz4-frame", Lz4FrameAdapter),
    ("zstd-frame", ZstdFrameAdapter),
    ("brotli-stream", BrotliStreamAdapter),
    ("bzip2-stream", Bzip2StreamAdapter),
    ("xz-stream", XzStreamAdapter),
)


def _adapter(name: str, adapter_type):
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get(name)
    artifact = PROJECT_ROOT / manifest.document["adapter"]["artifact_path"]
    if not artifact.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", name, "--profile", "release"],
            cwd=PROJECT_ROOT,
            check=True,
        )
    return adapter_type(artifact, manifest.document["adapter"]), manifest


def _route(n: int) -> RoutedInput:
    first = np.arange(n, dtype="<i8")
    second = (np.arange(n, dtype="<f8") / 7).astype("<f8")
    for array in (first, second):
        array.flags.writeable = False
    buffers = (
        LogicalBuffer("value/000000", first, first.nbytes * 8),
        LogicalBuffer("value/000001", second, second.nbytes * 8),
    )
    return RoutedInput(
        dataset_id="dataset:native-streaming-contract",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=n,
        m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


def _chunk(routed: RoutedInput, start: int, stop: int) -> RoutedInput:
    buffers = tuple(
        LogicalBuffer(item.name, item.array[start:stop], item.array[start:stop].nbytes * 8)
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


@pytest.mark.parametrize(("name", "adapter_type"), _CASES)
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 9])
def test_native_streaming_roundtrip_and_lifecycle(name: str, adapter_type, n: int):
    adapter, _ = _adapter(name, adapter_type)
    routed = _route(n)
    before = tuple(item.array.tobytes() for item in routed.buffers)
    session = adapter.create_stream_session({"block_size": 4, "stream_decode_chunk_bytes": 1})
    try:
        session.stream_start(routed)
        parts = []
        for start in range(0, n, 4):
            pushed = session.stream_push(_chunk(routed, start, min(n, start + 4)))
            parts.append(pushed.emitted)
            assert pushed.state_bytes > 0
            assert pushed.buffer_bytes == 0
            assert pushed.checkpoint_bits == 0
        parts.append(session.stream_finalize())
        stream = b"".join(parts)
        decoded = session.stream_decompress(stream)
        assert (
            tuple(decoded.by_name()[item.name].array.tobytes() for item in routed.buffers)
            == before
        )
        assert session.stream_accounting(stream, routed).final_bits == len(stream) * 8
        with pytest.raises(ExecutionContractError):
            session.stream_finalize()
    finally:
        session.close()
    assert tuple(item.array.tobytes() for item in routed.buffers) == before


@pytest.mark.parametrize(("name", "adapter_type"), _CASES)
@pytest.mark.parametrize("mutation", ["truncated", "trailing"])
def test_native_streaming_decoder_rejects_nonexact_frame(name: str, adapter_type, mutation: str):
    adapter, _ = _adapter(name, adapter_type)
    routed = _route(9)
    session = adapter.create_stream_session({"block_size": 4, "stream_decode_chunk_bytes": 2})
    try:
        session.stream_start(routed)
        stream = b"".join(
            [
                session.stream_push(_chunk(routed, 0, 4)).emitted,
                session.stream_push(_chunk(routed, 4, 8)).emitted,
                session.stream_push(_chunk(routed, 8, 9)).emitted,
                session.stream_finalize(),
            ]
        )
        _, frame = session._owner._parse_container(stream)[:2]
        prefix = stream[: -len(frame)]
        altered = frame[:-1] if mutation == "truncated" else frame + b"x"
        with pytest.raises(ExecutionContractError):
            session.stream_decompress(prefix + altered)
    finally:
        session.close()
