"""Byte algorithms' direct APIs: complete output and independent recovery.

Single-operation correctness checks only; no codec is built by this module and
none of its timings constitute benchmark evidence.
"""
from __future__ import annotations

import bz2
import ctypes as C
import json
import lzma
from pathlib import Path
import random
import zlib

import numpy as np
import pytest

from tsbench.build import artifact_path
from tsbench.registry import Registry

ROOT = Path(__file__).resolve().parents[2]
CODECS = ('brotli-stream', 'bzip2-stream', 'deflate-zlib', 'xz-stream',
          'fse', 'huff0', 'lzsse2-raw', 'lzsse8-raw')
LENGTH_PREFIXED = ('lzss-raw', 'lzss-dipperstein-c', 'lzsse2-raw', 'lzsse8-raw')
U8P = C.POINTER(C.c_uint8)


class Config(C.Structure):
    _fields_ = [('version', C.c_uint32), ('dtype', C.c_uint32),
                ('rank', C.c_uint32), ('order', C.c_uint32),
                ('shape', C.c_uint64 * 8), ('parameters_json', C.c_char_p), ('model', C.c_char_p)]


class Result(C.Structure):
    _fields_ = [('data', U8P), ('size', C.c_size_t), ('capacity', C.c_size_t), ('owner', C.c_void_p)]


def library(key):
    path = artifact_path(ROOT, key)
    if not path.is_file():
        pytest.skip(f'centrally built codec unavailable: {key}')
    lib = C.CDLL(str(path))
    # A present artifact without the new symbols is a stale build, not a pass.
    lib.tsbench_core_version.restype = C.c_uint32
    assert lib.tsbench_core_version() == 1
    lib.tsbench_core_create.argtypes = [C.POINTER(Config), C.c_int, C.POINTER(C.c_void_p)]
    lib.tsbench_core_destroy.argtypes = [C.c_void_p]
    lib.tsbench_core_bound.argtypes = [C.c_void_p, U8P, C.c_size_t, C.POINTER(C.c_size_t)]
    for name in ('encode', 'decode'):
        getattr(lib, 'tsbench_core_' + name).argtypes = [C.c_void_p, U8P, C.c_size_t, U8P, C.c_size_t, C.POINTER(Result)]
    lib.tsbench_core_release.argtypes = [C.POINTER(Result)]
    lib.tsbench_core_error.argtypes = [C.c_void_p]
    lib.tsbench_core_error.restype = C.c_char_p
    return lib


def configuration(size, params, *, dtype=2, shape=None, order=0):
    encoded = json.dumps(params, sort_keys=True, separators=(',', ':')).encode()
    shape = (size,) if shape is None else shape
    return Config(1, dtype, len(shape), order, (C.c_uint64 * 8)(*shape), encoded, None)


def check(lib, status, handle=None):
    assert status == 0, (status, lib.tsbench_core_error(handle).decode())


def create(lib, config, decoder=False):
    handle = C.c_void_p()
    check(lib, lib.tsbench_core_create(C.byref(config), int(decoder), C.byref(handle)))
    return handle


def source_buffer(data):
    return (C.c_uint8 * max(1, len(data))).from_buffer_copy(data or b'\0')


def guarded_buffer(capacity):
    storage = (C.c_uint8 * (capacity + 32))()
    C.memset(storage, 0xa5, len(storage))
    pointer = C.cast(C.byref(storage, 16), U8P)
    return storage, pointer


def intact_guards(storage):
    assert bytes(storage[:16]) == bytes([0xa5]) * 16
    assert bytes(storage[-16:]) == bytes([0xa5]) * 16


def encode_many(lib, key, payloads, **geometry):
    assert len({len(data) for data in payloads}) == 1
    size = len(payloads[0])
    config = configuration(size, Registry(ROOT).resolve_params(key), **geometry)
    handle = create(lib, config)
    retained = []
    try:
        for data in payloads:
            source = source_buffer(data)
            bound = C.c_size_t()
            check(lib, lib.tsbench_core_bound(handle, source, size, C.byref(bound)), handle)
            assert bound.value > 0
            storage, destination = guarded_buffer(bound.value)
            result = Result()
            retained.append((storage, result))
            check(lib, lib.tsbench_core_encode(handle, source, size, destination, bound.value, C.byref(result)), handle)
            assert result.owner is None  # These native APIs write caller storage.
            assert C.cast(result.data, C.c_void_p).value == C.cast(destination, C.c_void_p).value
            assert 0 < result.size <= result.capacity == bound.value
            assert C.string_at(source, size) == data
            intact_guards(storage)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        # Every output remains independently readable after another encode and
        # after destruction of its producing context.
        return [C.string_at(result.data, result.size) for _, result in retained]
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        for _, result in retained:
            lib.tsbench_core_release(C.byref(result))


def recover_many(lib, streams, size, **geometry):
    # No encoder parameters, external model or hidden encoder context.
    handle = create(lib, configuration(size, {}, **geometry), decoder=True)
    retained = []
    try:
        for stream in streams:
            source = source_buffer(stream)
            storage, destination = guarded_buffer(size)
            result = Result()
            retained.append((storage, result))
            check(lib, lib.tsbench_core_decode(handle, source, len(stream), destination, size, C.byref(result)), handle)
            assert result.size == size and result.owner is None
            assert C.string_at(source, len(stream)) == stream
            intact_guards(storage)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        return [C.string_at(result.data, result.size) for _, result in retained]
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        for _, result in retained:
            lib.tsbench_core_release(C.byref(result))


@pytest.mark.parametrize('key', CODECS)
@pytest.mark.parametrize('size', [0, 1, 31, 257, 4099])
def test_direct_complete_outputs_independent_recovery_and_workspace_reset(key, size):
    lib = library(key)
    data = (bytes(range(256)) * ((size + 255) // 256))[:size]
    other = bytes([0x20]) * size
    streams = encode_many(lib, key, [data, other, data])
    assert recover_many(lib, streams, size) == [data, other, data]
    assert streams[0] == streams[2]
    if key in LENGTH_PREFIXED:
        assert all(int.from_bytes(stream[:8], 'little') == size for stream in streams)
        if size == 0:
            assert streams == [bytes(8)] * 3
    if key in {'fse', 'huff0'}:
        assert all(int.from_bytes(stream[1:9], 'little') == size for stream in streams)
    if key == 'bzip2-stream':
        assert all(stream.startswith(b'BZh') for stream in streams)
        assert [bz2.decompress(stream) for stream in streams] == [data, other, data]
    if key == 'deflate-zlib':
        assert [zlib.decompress(stream) for stream in streams] == [data, other, data]
    if key == 'xz-stream':
        assert all(stream.startswith(b'\xfd7zXZ\x00') and stream[6:8] == b'\0\0' for stream in streams)
        assert [lzma.decompress(stream) for stream in streams] == [data, other, data]


@pytest.mark.parametrize('key', CODECS)
@pytest.mark.parametrize('order', ['C', 'F'])
def test_typed_physical_layout_has_no_added_padding_or_abi_envelope(key, order):
    lib = library(key)
    array = np.array(np.arange(771).reshape(257, 3) / 8, dtype='<f8', order=order)
    data = array.tobytes(order=order)
    geometry = {'dtype': 10, 'shape': array.shape, 'order': int(order == 'F')}
    streams = encode_many(lib, key, [data], **geometry)
    assert recover_many(lib, streams, array.nbytes, **geometry) == [data]
    assert not streams[0].startswith((b'ABI1', b'TSCB', b'LSI1', b'LS2I', b'LS8I'))


@pytest.mark.parametrize('key', ['fse', 'huff0'])
def test_entropy_raw_rle_and_model_stream_modes_are_all_complete(key):
    lib = library(key)
    data = [bytes(range(256)) * 16, bytes([0x73]) * 4096,
            (bytes([0, 0, 0, 0, 1, 1, 2]) * 586)[:4096]]
    streams = encode_many(lib, key, data)
    assert [stream[0] for stream in streams] == [0, 1, 2]
    assert len(streams[0]) == 9 + 4096 and len(streams[1]) == 10
    assert 10 < len(streams[2]) < 4096 + 9
    assert recover_many(lib, streams, 4096) == data


@pytest.mark.parametrize('key', ['lzsse2-raw', 'lzsse8-raw'])
def test_lzsse_native_raw_and_optimal_parse_streams(key):
    lib = library(key)
    rng = random.Random(20261015)
    raw = bytes(rng.randrange(256) for _ in range(8192))
    compressible = (bytes(range(64)) * 128)
    streams = encode_many(lib, key, [raw, compressible])
    assert len(streams[0]) == 8 + len(raw)
    assert len(streams[1]) < 8 + len(compressible)
    assert recover_many(lib, streams, len(raw)) == [raw, compressible]


@pytest.mark.parametrize('key', CODECS)
def test_output_capacity_failure_is_not_a_successful_measurement(key):
    lib = library(key)
    data = bytes(range(31))
    source = source_buffer(data)
    handle = create(lib, configuration(len(data), Registry(ROOT).resolve_params(key)))
    result = Result()
    try:
        assert lib.tsbench_core_encode(handle, source, len(data), None, 0, C.byref(result)) == 3
        assert result.size == 0 and not result.data
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', CODECS)
def test_truncated_complete_header_is_rejected_without_native_prepass(key):
    lib = library(key)
    data = bytes(range(31))
    stream = encode_many(lib, key, [data])[0]
    source = source_buffer(stream[:1])
    storage, destination = guarded_buffer(len(data))
    handle = create(lib, configuration(len(data), {}), decoder=True)
    result = Result()
    try:
        assert lib.tsbench_core_decode(handle, source, 1, destination, len(data), C.byref(result)) != 0
        assert result.size == 0
        intact_guards(storage)
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)
