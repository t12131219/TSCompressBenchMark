from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.factory import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers

ROOT = Path(__file__).resolve().parents[2]


def routed(arrays):
    buffers = tuple(
        LogicalBuffer(f"value/{i}", array, array.nbytes * 8) for i, array in enumerate(arrays)
    )
    return RoutedInput(
        dataset_id="v3:dataset:typed-byte-stream-regression",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=arrays[0].shape[0],
        m=len(arrays),
        canonical_raw_bits=sum(buffer.logical_bits for buffer in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize(
    "key", ["lz4-frame", "zstd-frame", "brotli-stream", "deflate-zlib", "xz-stream"]
)
def test_independent_object_decoder_restores_multibuffer_stream_with_tail(key):
    sources = SourceRegistry(ROOT / "registry/sources")
    manifest = CodecRegistry(ROOT / "registry/codecs", sources).get(key)
    adapter = create_adapter(ROOT, manifest)
    arrays = [
        np.arange(10, dtype="<i2").reshape(5, 2),
        np.array([0, 2**63, 0x7FF8000000000123, 1, 0x7FF0000000000000], dtype="<u8").view("<f8"),
    ]
    for array in arrays:
        array.flags.writeable = False
    source = routed(arrays)
    parameters = {"block_size": 2, "stream_decode_chunk_bytes": 3}
    session = adapter.create_stream_session(parameters)
    try:
        session.stream_start(source)
        pieces = []
        for start in range(0, 5, 2):
            pieces.append(
                session.stream_push(routed([a[start : start + 2] for a in arrays])).emitted
            )
        pieces.append(session.stream_finalize())
        stream = b"".join(pieces)
        streamed = session.stream_decompress(stream)
        # A new independent decoder sees only the saved container, never the
        # original buffers or the stream encoder's layout/state.
        decoder = adapter.create_session(parameters)
        try:
            independent = decoder.decompress(stream)
        finally:
            decoder.close()
        for decoded in (streamed, independent):
            for expected, observed in zip(arrays, decoded.buffers, strict=True):
                assert observed.array.dtype == expected.dtype
                assert observed.array.shape == expected.shape
                assert observed.array.tobytes() == expected.tobytes()
                assert not observed.array.flags.writeable
    finally:
        session.close()
