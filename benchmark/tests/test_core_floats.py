"""Direct typed floating APIs: full output, physical layout and fresh recovery.

These are single-operation correctness checks, never performance evidence.
Use the centrally built artifact; this module does not compile any codec.
"""
from __future__ import annotations

import ctypes as C
import json
from pathlib import Path

import numpy as np
import pytest

from tsbench.build import artifact_path
from tsbench.registry import Registry

ROOT = Path(__file__).resolve().parents[2]
LOSSLESS = ('alp', 'alp-rd', 'chimp', 'chimp128', 'elf', 'elf-plus', 'elf-star', 'self-star')
BOUNDED = ('serf-qt', 'serf-xor', 'zfp-accuracy-1d')
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
    if hasattr(lib, 'tsbench_core_validate_input'):
        lib.tsbench_core_validate_input.argtypes = [C.c_void_p, U8P, C.c_size_t]
    return lib


def configuration(array, parameters, order='C'):
    encoded = json.dumps(parameters, sort_keys=True, separators=(',', ':')).encode()
    dtype_code = {('f', 4): 9, ('f', 8): 10, ('i', 1): 1, ('i', 2): 3,
                  ('i', 4): 5, ('i', 8): 7, ('u', 1): 2, ('u', 2): 4}[array.dtype.kind, array.dtype.itemsize]
    return Config(1, dtype_code, array.ndim, int(order == 'F'),
                  (C.c_uint64 * 8)(*array.shape), encoded, None)


def check(lib, code, context=None):
    assert code == 0, (code, lib.tsbench_core_error(context).decode())


def context(lib, config, decoder=False):
    handle = C.c_void_p()
    check(lib, lib.tsbench_core_create(C.byref(config), decoder, C.byref(handle)))
    return handle


def buffer(data):
    return (C.c_uint8 * max(1, len(data))).from_buffer_copy(data or b'\0')


def encode(lib, key, array, params=None, order='C'):
    parameters = Registry(ROOT).resolve_params(key, params)
    handle = context(lib, configuration(array, parameters, order))
    payload = array.tobytes(order=order)
    source = buffer(payload)
    size = C.c_size_t()
    result = Result()
    try:
        if hasattr(lib, 'tsbench_core_validate_input'):
            check(lib, lib.tsbench_core_validate_input(handle, source, len(payload)), handle)
        check(lib, lib.tsbench_core_bound(handle, source, len(payload), C.byref(size)), handle)
        destination = (C.c_uint8 * max(1, size.value))()
        check(lib, lib.tsbench_core_encode(handle, source, len(payload), destination, size.value, C.byref(result)), handle)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        # Owned vectors must survive their producing context. Caller storage is
        # also still live here, independently of its now-destroyed context.
        output = C.string_at(result.data, result.size)
        assert 0 < len(output) <= size.value
        return output
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))


def decode(lib, array, stream, order='C'):
    # Decoder receives no encoder parameters, tolerance, model or block size.
    handle = context(lib, configuration(array, {}, order), decoder=True)
    source = buffer(stream)
    output = (C.c_uint8 * max(1, array.nbytes))()
    result = Result()
    try:
        check(lib, lib.tsbench_core_decode(handle, source, len(stream), output, array.nbytes, C.byref(result)), handle)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        return C.string_at(result.data, result.size)
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))


@pytest.mark.parametrize('key', LOSSLESS + BOUNDED)
@pytest.mark.parametrize('dtype', ['<f4', '<f8'])
@pytest.mark.parametrize('order', ['C', 'F'])
def test_physical_typed_stream_tail_and_independent_recovery(key, dtype, order):
    if key in {'chimp', 'chimp128'} and dtype == '<f4':
        key = 'chimp32' if key == 'chimp' else 'chimpn32'
    lib = library(key)
    array = np.array(np.arange(771).reshape(257, 3) / 8, dtype=dtype, order=order)
    params = {'error_bound': '0.01'} if key in BOUNDED else {}
    # Several blocks plus a short final block, including odd and non-vector
    # lengths. ZFP's four-value padding and ALP's 1024 values stay internal.
    if key not in {'alp', 'alp-rd', 'zfp-accuracy-1d'}:
        params['block_size'] = 127
    stream = encode(lib, key, array, params, order)
    restored = decode(lib, array, stream, order)
    assert len(restored) == array.nbytes
    if key in LOSSLESS or key in {'chimp32', 'chimpn32'}:
        assert restored == array.tobytes(order=order)
    else:
        values = np.frombuffer(restored, dtype=dtype)
        original = np.frombuffer(array.tobytes(order=order), dtype=dtype)
        assert np.max(np.abs(values.astype(np.float64) - original.astype(np.float64))) <= 0.01
    assert not stream.startswith((b'TAI1', b'RWI1', b'RWF1', b'SRI1', b'ZFI1', b'ZFA1'))
    if key in {'alp', 'alp-rd'}:
        assert stream[:8] == b'ALPRW001'
        assert stream[8:10] == bytes([array.dtype.itemsize, int(key == 'alp-rd')])
        assert int.from_bytes(stream[12:20], 'little') == array.size
    if key in {'serf-qt', 'serf-xor'}:
        assert int.from_bytes(stream[8:12], 'little') == 1  # one physical scalar stream
    if key in {'serf-qt', 'serf-xor'}:
        assert stream[:4] == (b'SQC1' if key == 'serf-qt' else b'SXC1')
    if key.startswith('chimp'):
        assert stream.startswith(b'CFP1') and stream.count(b'CFP1') >= 2


@pytest.mark.parametrize('key', LOSSLESS + ('serf-qt', 'serf-xor'))
def test_empty_native_stream_has_complete_representation(key):
    lib = library(key)
    array = np.empty(0, dtype='<f8')
    stream = encode(lib, key, array)
    assert decode(lib, array, stream) == b''
    if key in {'serf-qt', 'serf-xor'}:
        assert len(stream) == 48  # complete recovery header, no optional FNV footer


@pytest.mark.parametrize('key', ['chimp', 'chimp128', 'elf', 'elf-plus', 'elf-star', 'self-star'])
def test_source_nan_domain_rejection_is_not_raw_fallback(key):
    lib = library(key)
    array = np.array([1., np.nan, 2.], dtype='<f8')
    handle = context(lib, configuration(array, Registry(ROOT).resolve_params(key)))
    source = buffer(array.tobytes())
    output = (C.c_uint8 * 65536)()
    result = Result()
    try:
        assert lib.tsbench_core_encode(handle, source, array.nbytes, output, len(output), C.byref(result)) == 2
        assert result.size == 0
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('value', [np.nan, np.inf, -0., np.nextafter(0., 1.)])
def test_zfp_special_values_return_unsupported(value):
    key = 'zfp-accuracy-1d'
    lib = library(key)
    array = np.array([1., value], dtype='<f8')
    handle = context(lib, configuration(array, Registry(ROOT).resolve_params(key)))
    source = buffer(array.tobytes())
    try:
        assert lib.tsbench_core_validate_input(handle, source, array.nbytes) == 2
    finally:
        lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', LOSSLESS + BOUNDED)
def test_truncated_native_frame_rejected(key):
    lib = library(key)
    array = np.arange(31, dtype='<f8') / 8
    stream = encode(lib, key, array)
    handle = context(lib, configuration(array, {}), decoder=True)
    source = buffer(stream[:7])
    output = (C.c_uint8 * array.nbytes)()
    result = Result()
    try:
        assert lib.tsbench_core_decode(handle, source, 7, output, array.nbytes, C.byref(result)) != 0
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)


def test_zfp_effective_accuracy_is_read_from_full_header():
    from tsbench.quality_metadata import zfp_core_quality
    key = 'zfp-accuracy-1d'
    lib = library(key)
    array = np.arange(31, dtype='<f8') / 8
    stream = encode(lib, key, array, {'error_bound': '0.01'})
    part = {'dtype': '<f8', 'shape': [31], 'params': {'error_bound': '0.01'}}
    quality = zfp_core_quality(stream, part, artifact_path(ROOT, key))
    assert quality['native_format'] == 'ZFP_HEADER_FULL'
    assert quality['codec_effective_absolute_tolerance'] == 0.0078125
    assert quality['codec_effective_tolerance_source'] == 'zfp_read_header + zfp_stream_accuracy'
    with pytest.raises(ValueError, match='exceeds configured request'):
        zfp_core_quality(stream, {**part, 'params': {'error_bound': '0.001'}}, artifact_path(ROOT, key))
