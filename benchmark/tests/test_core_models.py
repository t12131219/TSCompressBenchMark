"""NeaTS/LeaTS direct native persistence and original typed physical bytes."""
import ctypes as C

import numpy as np
import pytest

from tsbench.registry import Registry

from test_core_floats import ROOT, Result, buffer, configuration, context, decode, encode, library


@pytest.mark.parametrize('key', ['neats-lossless-i64', 'leats-lossless-i64'])
@pytest.mark.parametrize('dtype', ['i1', '<i2', '<i4', '<i8'])
@pytest.mark.parametrize('order', ['C', 'F'])
@pytest.mark.parametrize('max_bpc', [16, 32])
def test_model_serialization_restores_original_width_and_layout(key, dtype, order, max_bpc):
    lib = library(key)
    values = ((np.arange(69, dtype=np.int64) ** 2 + 7) % 101 - 50).reshape(23, 3)
    array = np.array(values, dtype=dtype, order=order)
    stream = encode(lib, key, array, {'max_bpc': max_bpc}, order)
    assert stream[:4] == (b'NDC1' if key.startswith('neats') else b'LDC1')
    assert stream[4] == array.dtype.itemsize
    assert int.from_bytes(stream[5:13], 'little', signed=True) == int(array.min())
    assert stream[13] == max_bpc
    # Native persisted count is the full physical stream, including every column.
    assert int.from_bytes(stream[14:18], 'little') == array.size
    assert decode(lib, array, stream, order) == array.tobytes(order=order)


@pytest.mark.parametrize('key', ['neats-lossless-i64', 'leats-lossless-i64'])
def test_signed_normalization_span_rejection_is_explicit(key):
    lib = library(key)
    array = np.array([np.iinfo(np.int64).min, np.iinfo(np.int64).max], dtype='<i8')
    handle = context(lib, configuration(array, Registry(ROOT).resolve_params(key)))
    source = buffer(array.tobytes())
    output = (C.c_uint8 * 65536)()
    result = Result()
    try:
        assert lib.tsbench_core_encode(handle, source, array.nbytes, output, len(output), C.byref(result)) == 2
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', ['neats-lossless-i64', 'leats-lossless-i64'])
@pytest.mark.parametrize('count', [0, 65537])
def test_physical_model_stream_source_limits(key, count):
    lib = library(key)
    array = np.empty(count, dtype='<i8')
    config = configuration(array, Registry(ROOT).resolve_params(key))
    handle = C.c_void_p()
    assert lib.tsbench_core_create(C.byref(config), 0, C.byref(handle)) == 2
    assert handle.value is None


@pytest.mark.parametrize('key', ['neats-lossless-i64', 'leats-lossless-i64'])
def test_model_count_is_checked_before_native_load(key):
    lib = library(key)
    array = np.arange(15, dtype='<i8') - 7
    stream = bytearray(encode(lib, key, array))
    stream[14:18] = (array.size + 1).to_bytes(4, 'little')
    source = buffer(bytes(stream))
    output = (C.c_uint8 * array.nbytes)()
    result = Result()
    handle = context(lib, configuration(array, {}), decoder=True)
    try:
        assert lib.tsbench_core_decode(handle, source, len(stream), output, array.nbytes, C.byref(result)) == 1
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)
