"""Direct SIMDComp format and buffer correctness; never performance evidence.

Use the centrally built library. No compiler or benchmark is invoked here.
"""
from __future__ import annotations

import ctypes as C
import json

import numpy as np
import pytest

from tsbench.registry import Registry
from test_core_floats import ROOT, Config, Result, U8P, buffer, check, library

KEY = 'simdcomp-u32'
ROUTES = [('SSE4_1', 'LENGTH'), ('SSE4_1', 'MASKED'),
          ('SSE4_1', 'WITHOUTMASK'), ('AVX2', 'MASKED'), ('AVX2', 'WITHOUTMASK')]
EXTENTS = [(0, 0), (1, 32), (127, 1), (128, 0), (129, 31),
           (255, 32), (256, 1), (257, 0), (513, 31)]


def config(array, params):
    return Config(1, 6, 1, 0, (C.c_uint64 * 8)(array.size),
                  json.dumps(params, separators=(',', ':')).encode(), None)


def context(lib, array, params, decoder=False):
    handle = C.c_void_p()
    configuration = config(array, params)
    code = lib.tsbench_core_create(C.byref(configuration), decoder, C.byref(handle))
    reason = lib.tsbench_core_error(None).decode()
    if code == 2 and 'requires the declared SSE4.1/AVX2 path' in reason:
        pytest.skip(reason)
    check(lib, code)
    return handle


def encode(lib, array, route, offset=0):
    params = Registry(ROOT).resolve_params(KEY, dict(zip(('isa', 'api'), route)))
    handle = context(lib, array, params)
    raw = array.tobytes()
    storage = buffer(b'\xa5' * offset + raw + b'\xa5')
    source = C.cast(C.byref(storage, offset), U8P)
    bound = C.c_size_t()
    result = Result()
    try:
        check(lib, lib.tsbench_core_bound(handle, source, len(raw), C.byref(bound)), handle)
        destination = buffer(b'\xa5' * (bound.value + offset + 1))
        output = C.cast(C.byref(destination, offset), U8P)
        check(lib, lib.tsbench_core_encode(handle, source, len(raw), output,
                                          bound.value, C.byref(result)), handle)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        stream = C.string_at(result.data, result.size)
        assert result.owner is None
        assert 0 < len(stream) <= bound.value
        assert bytes(storage) == b'\xa5' * offset + raw + b'\xa5'
        assert bytes(destination[:offset]) == b'\xa5' * offset
        assert destination[-1] == 0xa5
        return stream
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))


def decode(lib, array, stream, offset=0, capacity=None):
    # No encoder API, ISA or precomputed widths are supplied to this context.
    handle = context(lib, array, {}, decoder=True)
    source = buffer(stream)
    destination = buffer(b'\xa5' * (array.nbytes + offset + 1))
    output = C.cast(C.byref(destination, offset), U8P)
    result = Result()
    try:
        lib.tsbench_core_validate.argtypes = [C.c_void_p, U8P, C.c_size_t]
        code = lib.tsbench_core_validate(handle, source, len(stream))
        if code == 0:
            code = lib.tsbench_core_decode(handle, source, len(stream), output,
                                           array.nbytes if capacity is None else capacity,
                                           C.byref(result))
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        restored = C.string_at(result.data, result.size) if code == 0 else None
        assert bytes(destination[:offset]) == b'\xa5' * offset
        assert destination[-1] == 0xa5
        return code, restored, bytes(destination[offset:offset + array.nbytes])
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))


@pytest.mark.parametrize('route', ROUTES)
@pytest.mark.parametrize('count,width', EXTENTS)
def test_direct_blocks_widths_and_empty_parameter_recovery(route, count, width):
    lib = library(KEY)
    mask = (1 << width) - 1
    array = ((np.arange(count, dtype=np.uint64) * 2654435761) & mask).astype('<u4')
    if count:
        array[-1] = mask  # exercise the declared high bit, including uint32 max
    stream = encode(lib, array, route)
    assert int.from_bytes(stream[:4], 'little') == count
    assert stream[4] == int(route[0] == 'AVX2')
    assert not stream.startswith(b'SBP1')
    block = 256 if route[0] == 'AVX2' else 128
    cursor = 5
    for start in range(0, count, block):
        values = array[start:start + block]
        actual_width = int(values.max()).bit_length()
        assert stream[cursor] == actual_width
        # SIMDComp uses four interleaved 32-bit lanes for the SSE tail.
        # Width 32 is the native absolute-byte path, without tail lane padding.
        if actual_width == 32:
            packed = values.size * 4
        elif block == 256 and values.size == 256:
            packed = actual_width * 32
        else:
            packed = (((values.size + 3) // 4 * actual_width + 31) // 32) * 16
        cursor += 1 + packed
    assert cursor == len(stream)
    code, restored, _ = decode(lib, array, stream)
    assert code == 0 and restored == array.tobytes()


@pytest.mark.parametrize('route', ROUTES)
def test_direct_unaligned_buffers_and_capacity(route):
    lib = library(KEY)
    array = (np.arange(259, dtype=np.uint32) * 1301).astype('<u4')
    stream = encode(lib, array, route, offset=1)
    code, restored, _ = decode(lib, array, stream, offset=1)
    assert code == 0 and restored == array.tobytes()
    code, restored, untouched = decode(lib, array, stream, offset=1, capacity=array.nbytes - 1)
    assert code == 3 and restored is None and untouched == b'\xa5' * array.nbytes


@pytest.mark.parametrize('damage', ['header', 'count', 'profile', 'width', 'payload', 'trailing'])
def test_direct_invalid_stream_is_rejected_before_native_unpack(damage):
    lib = library(KEY)
    array = (np.arange(257, dtype=np.uint32) * 1301).astype('<u4')
    stream = bytearray(encode(lib, array, ('SSE4_1', 'LENGTH')))
    if damage == 'header':
        stream = stream[:4]
    elif damage == 'count':
        stream[:4] = (array.size + 1).to_bytes(4, 'little')
    elif damage == 'profile':
        stream[4] = 2
    elif damage == 'width':
        stream[5] = 33
    elif damage == 'payload':
        del stream[-1]
    else:
        stream += b'\0'
    code, restored, untouched = decode(lib, array, bytes(stream))
    assert code == 1 and restored is None
    assert untouched == b'\xa5' * array.nbytes


def test_direct_avx_length_unsupported_and_decoder_parameters_rejected():
    lib = library(KEY)
    array = np.arange(4, dtype='<u4')
    params = Registry(ROOT).resolve_params(KEY, {'isa': 'AVX2', 'api': 'MASKED'})
    params['api'] = 'LENGTH'  # bypass the Python gate to exercise native rejection
    configuration = config(array, params)
    handle = C.c_void_p()
    assert lib.tsbench_core_create(C.byref(configuration), 0, C.byref(handle)) == 2
    assert handle.value is None
    configuration = config(array, {'isa': 'SSE4_1'})
    assert lib.tsbench_core_create(C.byref(configuration), 1, C.byref(handle)) == 1
    assert handle.value is None
