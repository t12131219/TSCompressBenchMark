from __future__ import annotations

import ctypes
import importlib
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import (
    BrotliStreamAdapter,
    DeflateZlibAdapter,
    Lz4FrameAdapter,
    Lzsse2RawAdapter,
    Lzsse8RawAdapter,
    LzssRawAdapter,
    SnappyRawAdapter,
    XzStreamAdapter,
    ZstdFrameAdapter,
)
from tscompbench.adapters.native_timing import NativeTimingProbe, _NativeTiming
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _route(n: int) -> RoutedInput:
    values = np.arange(n, dtype="<i8")
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:native-timing", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=n, m=1,
        canonical_raw_bits=values.nbytes * 8, input_sha256=hash_logical_buffers(buffers),
    )


@pytest.fixture(params=[
    ("lz4_frame", Lz4FrameAdapter), ("zstd_frame", ZstdFrameAdapter),
    ("snappy_raw", SnappyRawAdapter),
    ("brotli_stream", BrotliStreamAdapter),
    ("deflate_zlib", DeflateZlibAdapter),
    ("xz_stream", XzStreamAdapter),
    ("lzss_raw", LzssRawAdapter),
    ("lzsse8_raw", Lzsse8RawAdapter),
    ("lzsse2_raw", Lzsse2RawAdapter),
])
def adapter(request):
    directory, factory = request.param
    path = PROJECT_ROOT / f"build/adapters/{directory}/release/libtscb_{directory}.so"
    if not path.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", directory.replace("_", "-"),
             "--profile", "release"], cwd=PROJECT_ROOT, check=True,
        )
    return factory(path, {})


@pytest.mark.parametrize("n", [0, 1, 32769])
def test_native_roundtrip_timings_preserve_stream_and_stay_inside_core(adapter, n):
    route = _route(n)
    level = 12 if isinstance(adapter, (Lzsse2RawAdapter, Lzsse8RawAdapter)) else 1
    parameters = {"compression_level": level,
                  "content_checksum": False}
    baseline = perform_roundtrip(adapter, route, {**parameters, "native_timing": False})
    measured = perform_roundtrip(adapter, route, parameters)
    assert baseline.encoded.stream == measured.encoded.stream
    assert baseline.timing.native_encode_wall_ns is None
    assert baseline.timing.native_decode_wall_ns is None
    assert 0 < measured.timing.native_encode_wall_ns <= measured.timing.encode_wall_ns
    assert 0 < measured.timing.native_decode_wall_ns <= measured.timing.decode_wall_ns
    assert measured.determinism_match


def test_native_counter_query_finalize_decode_and_reset(adapter):
    level = 12 if isinstance(adapter, (Lzsse2RawAdapter, Lzsse8RawAdapter)) else 1
    parameters = {"compression_level": level,
                  "content_checksum": False, "native_timing": True}
    # Streaming codecs finish here; one-shot codecs only acknowledge completion.
    route = _route(16)
    session = adapter.create_session(parameters)
    try:
        assert session.native_timing() == (0, 0)
        storage = bytearray(session.output_bound(route))
        updated = session.compress_update(route, memoryview(storage))
        before = session.native_timing()
        finalized = session.finalize(memoryview(storage)[updated:])
        after = session.native_timing()
        assert after[0] >= before[0] > 0
        if not isinstance(
            adapter,
            (SnappyRawAdapter, XzStreamAdapter, LzssRawAdapter, Lzsse2RawAdapter, Lzsse8RawAdapter),
        ):
            assert after[0] > before[0]
        else:
            assert after[0] == before[0]
        assert after[1] == 0
        assert session.native_timing() == after
        with pytest.raises(ExecutionContractError):
            session.finalize(memoryview(storage))
        assert session.native_timing() == after
        stream = bytes(storage[:updated + finalized])
        session.decompress(stream)
        first_decode = session.native_timing()
        session.decompress(stream)
        assert session.native_timing()[1] > first_decode[1] > 0
        library = session._native.library
        library.tscb_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        library.tscb_reset.restype = ctypes.c_uint32
        assert library.tscb_reset(session._handle, 0) == 0
        assert session.native_timing() == (0, 0)
        timing = _NativeTiming(ctypes.sizeof(_NativeTiming), 99, 0, 0)
        assert library.tscb_get_native_timing(session._handle, ctypes.byref(timing)) == 6
    finally:
        session.close()


def test_optional_probe_supports_old_library():
    assert NativeTimingProbe(object(), ctypes.c_void_p(), enabled=True).read() is None
    assert NativeTimingProbe(object(), ctypes.c_void_p(), enabled=False).read() is None


def test_native_query_after_session_close_is_rejected(adapter):
    session = adapter.create_session({"native_timing": True})
    session.close()
    session.close()
    with pytest.raises(ExecutionContractError, match="after session close"):
        session.native_timing()


def test_failed_native_decode_keeps_codec_boundary_and_counter(adapter):
    session = adapter.create_session({"native_timing": True, "content_checksum": False})
    try:
        module = importlib.import_module(type(session).__module__)
        compressed = bytearray(b"invalid")
        output = bytearray(128)
        source_array = (ctypes.c_ubyte * len(compressed)).from_buffer(compressed)
        output_array = (ctypes.c_ubyte * len(output)).from_buffer(output)
        source = module._buffer(ctypes.addressof(source_array),
                                capacity=len(compressed), used=len(compressed))
        destination = module._buffer(ctypes.addressof(output_array), capacity=128, used=0)
        status = session._native.library.tscb_decompress(
            session._handle, ctypes.byref(source), ctypes.byref(destination)
        )
        assert status != 0
        timing = session.native_timing()
        assert timing[0] == 0
        if isinstance(
            adapter,
            (SnappyRawAdapter, XzStreamAdapter, LzssRawAdapter, Lzsse2RawAdapter, Lzsse8RawAdapter),
        ):
            # Length/validity prechecks reject this stream before native decoding.
            assert timing[1] == 0
        else:
            assert timing[1] > 0
    finally:
        session.close()


def test_native_clock_failure_overflow_and_abi_size(tmp_path):
    executable = tmp_path / "native-timing-smoke"
    subprocess.run([
        os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-I", str(PROJECT_ROOT / "native/include"),
        str(PROJECT_ROOT / "tests/native/native_timing_smoke.c"), "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
