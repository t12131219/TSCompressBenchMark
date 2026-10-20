"""Qualify the safe-v1 binding against complete native objects and failure contracts."""
from __future__ import annotations

import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import numpy as np
import pytest

from test_core_floats import ROOT, Result, U8P, buffer, check, configuration, context, decode, encode, library
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import byte_buffer
from tsbench.build import artifact_path
from tsbench.registry import CodecError, Registry


@pytest.fixture(scope='module')
def reference():
    path = Path(os.environ.get('TSBENCH_ALP_REFERENCE', ROOT / 'build/alp-safe-v1-integration/standalone/libalp_port.so'))
    if not path.is_file():
        pytest.skip('independently built frozen ALP reference unavailable')
    lib = C.CDLL(str(path))
    lib.alp_port_bound.argtypes = [C.c_uint64, C.c_uint8, C.c_uint8, C.POINTER(C.c_size_t)]
    lib.alp_port_encode.argtypes = [C.c_void_p, C.c_uint64, C.c_uint8, C.c_uint8, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    lib.alp_port_decode.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_size_t,
                                  C.POINTER(C.c_size_t), C.POINTER(C.c_size_t), C.POINTER(C.c_uint64),
                                  C.POINTER(C.c_uint8), C.POINTER(C.c_uint8)]
    return lib


def reference_encode(lib, raw, width, method):
    source = buffer(raw)
    bound, used = C.c_size_t(), C.c_size_t()
    assert lib.alp_port_bound(len(raw) // width, width, method, C.byref(bound)) == 0
    target = (C.c_uint8 * bound.value)()
    assert lib.alp_port_encode(source, len(raw) // width, width, method, target, bound.value, C.byref(used)) == 0
    return bytes(target[:used.value])


def reference_decode(lib, stream, raw):
    source, target = buffer(stream), buffer(b'\xcc' * len(raw))
    used, consumed, count, width, method = C.c_size_t(), C.c_size_t(), C.c_uint64(), C.c_uint8(), C.c_uint8()
    assert lib.alp_port_decode(source, len(stream), target, len(raw), C.byref(used), C.byref(consumed),
                               C.byref(count), C.byref(width), C.byref(method)) == 0
    assert bytes(target[:used.value]) == raw and consumed.value == len(stream)


def branches(stream):
    """Independent full-frame accounting; RAW has no representation."""
    assert stream[:8] == b'ALPRW001'
    width, method = stream[8:10]
    count, payload, crc = struct.unpack_from('<QQI', stream, 12)
    assert payload == len(stream) - 32
    assert crc == zlib.crc32(stream[:28] + stream[32:])
    at, schemes = 32, []
    for start in range(0, count, 102400):
        scheme, right, left, dictionary, logical = struct.unpack_from('<BBBBI', stream, at)
        assert scheme in (1, 2) and (method == 0 or scheme == 1)
        assert logical == min(count - start, 102400)
        schemes.append(scheme)
        at += 32
        for _ in range(0, logical, 1024):
            n, exceptions, bw, factor, exponent, zero, base = struct.unpack_from('<HHBBBBQ', stream, at)
            assert 0 < n <= 1024
            at += 16 + ((right + left) * 128 + exceptions * 4 if scheme == 1 else bw * 128 + exceptions * (2 + width))
    assert at == len(stream)
    return schemes


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
@pytest.mark.parametrize('dtype', ['<f4', '<f8'])
@pytest.mark.parametrize('count', [0, 1, 2, 31, 1023, 1024, 1025, 2049, 102399, 102400, 102401])
def test_native_bytes_and_bidirectional_decode(reference, key, dtype, count):
    array = np.asarray((np.arange(count) % 10007 - 5000) / 100, dtype=dtype)
    before = array.tobytes()
    lib = library(key)
    stream = encode(lib, key, array)
    expected = reference_encode(reference, before, array.itemsize, int(key == 'alp-rd'))
    assert stream == expected
    assert decode(lib, array, expected) == before
    reference_decode(reference, stream, before)
    assert array.tobytes() == before
    branches(stream)


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
@pytest.mark.parametrize('dtype', ['<f4', '<f8'])
def test_ieee_bits_and_adaptive_rd_are_supported(reference, key, dtype):
    bits = ([0, 0x80000000, 0x7f800000, 0xff800000, 0x7fc00042, 0x7f800001, 1, 0x80000001, 0x7f7fffff]
            if dtype == '<f4' else [0, 0x8000000000000000, 0x7ff0000000000000, 0xfff0000000000000,
                                     0x7ff8000000000042, 0x7ff0000000000001, 1, 0x8000000000000001, 0x7fefffffffffffff])
    array = np.resize(np.array(bits, dtype='<u4' if dtype == '<f4' else '<u8'), 2049).view(dtype)
    raw = array.tobytes()
    lib = library(key)
    stream = encode(lib, key, array)
    assert stream == reference_encode(reference, raw, array.itemsize, int(key == 'alp-rd'))
    assert decode(lib, array, stream) == raw
    assert branches(stream) == [1]


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
@pytest.mark.parametrize('dtype', ['<f4', '<f8'])
def test_c1_columns_are_complete_reference_objects(reference, key, dtype):
    bridge = create_bridge(ROOT, key)
    array = np.array(np.arange(2050).reshape(1025, 2) / 100, dtype=dtype)
    array[5, 1] = np.inf
    raw = array.tobytes()
    stream = bridge.encode(array, {'native_timing': True})
    assert bridge.last_native_ns is not None
    assert stream[:4] == b'APS1'
    assert struct.unpack_from('<BBHQ', stream, 4) == (array.itemsize, 0, 2, 1025)
    at = 16
    for column in array.T:
        size = struct.unpack_from('<Q', stream, at)[0]
        frame = stream[at + 8:at + 8 + size]
        assert frame == reference_encode(reference, column.tobytes(), array.itemsize, int(key == 'alp-rd'))
        branches(frame)
        at += 8 + size
    assert at == len(stream)
    assert bridge.decode(stream, dtype, array.shape).tobytes() == raw
    assert array.tobytes() == raw
    with pytest.raises(CodecError):
        create_bridge(ROOT, 'alp-rd' if key == 'alp' else 'alp').decode(stream, dtype, array.shape)


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
def test_failure_atomicity_capacity_crc_geometry_and_retry(key):
    lib = library(key)
    array = np.arange(1025, dtype='<f8') / 100
    stream = encode(lib, key, array)
    handle = context(lib, configuration(array, {}), decoder=True)
    output = buffer(b'\xa5' * array.nbytes)
    result = Result()
    corrupt = bytearray(stream); corrupt[-1] ^= 1
    wrong_shape = bytearray(stream); struct.pack_into('<Q', wrong_shape, 12, array.size - 1)
    try:
        for value in [bytes(corrupt), bytes(wrong_shape), stream[:-1], stream + b'\0', b'ALP1' + stream[4:]]:
            source = buffer(value)
            assert lib.tsbench_core_decode(handle, source, len(value), output, array.nbytes, C.byref(result)) != 0
            assert not result.size and not result.owner and bytes(output) == b'\xa5' * array.nbytes
        source = buffer(stream)
        assert lib.tsbench_core_decode(handle, source, len(stream), output, array.nbytes - 1, C.byref(result)) == 3
        assert bytes(output) == b'\xa5' * array.nbytes
        check(lib, lib.tsbench_core_decode(handle, source, len(stream), output, array.nbytes, C.byref(result)), handle)
        assert bytes(output) == array.tobytes()
    finally:
        lib.tsbench_core_release(C.byref(result)); lib.tsbench_core_destroy(handle)
    handle = context(lib, configuration(array, Registry(ROOT).resolve_params(key)))
    source = buffer(array.tobytes()); output = buffer(b'\xa5' * len(stream))
    try:
        assert lib.tsbench_core_encode(handle, source, array.nbytes, output, len(stream) - 1, C.byref(result)) == 3
        assert not result.size and bytes(output) == b'\xa5' * len(stream)
        check(lib, lib.tsbench_core_encode(handle, source, array.nbytes, output, len(stream), C.byref(result)), handle)
        assert bytes(output) == stream
    finally:
        lib.tsbench_core_release(C.byref(result)); lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
def test_unaligned_input_output_and_overlap_rejection(key):
    lib = library(key)
    array = np.arange(31, dtype='<f8') / 8
    expected = encode(lib, key, array)
    source, output = buffer(b'X' + array.tobytes()), buffer(b'X' + b'\xa5' * len(expected))
    src = C.cast(C.byref(source, 1), U8P); dst = C.cast(C.byref(output, 1), U8P)
    handle = context(lib, configuration(array, {})); result = Result()
    try:
        assert lib.tsbench_core_encode(handle, src, array.nbytes, src, array.nbytes, C.byref(result)) != 0
        assert bytes(source[1:]) == array.tobytes()
        check(lib, lib.tsbench_core_encode(handle, src, array.nbytes, dst, len(expected), C.byref(result)), handle)
        assert bytes(output[1:]) == expected and output[0] == ord('X')
    finally:
        lib.tsbench_core_release(C.byref(result)); lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
@pytest.mark.parametrize('params', [{'unknown': 1}, {'isa': 'AVX2'}, {'native_timing': 1}])
def test_direct_parameter_rejection(key, params):
    lib = library(key); handle = C.c_void_p()
    assert lib.tsbench_core_create(C.byref(configuration(np.arange(1, dtype='<f8'), params)), 0, C.byref(handle)) != 0
    assert not handle.value


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
def test_c1_atomic_failure_and_reset_lifecycle(key):
    bridge = create_bridge(ROOT, key); lib = bridge.lib
    array = np.arange(62, dtype='<f8').reshape(31, 2) / 8
    params = Registry(ROOT).resolve_params(key)
    raw = bridge._input(array, params)
    source_storage = C.create_string_buffer(raw, len(raw))
    source = byte_buffer(source_storage, capacity=len(raw), used=len(raw))
    expected = bridge.encode(array)
    output_storage = C.create_string_buffer(b'\xa5' * len(expected), len(expected))
    output = byte_buffer(output_storage, capacity=len(expected) - 1)
    with bridge._session(params, 'encode') as handle:
        assert lib.tscb_compress(handle, C.byref(source), C.byref(output)) == 3
        assert output.used_bytes == 0 and output_storage.raw == b'\xa5' * len(expected)
        output.capacity_bytes = len(expected)
        bridge._check(lib.tscb_compress(handle, C.byref(source), C.byref(output)), handle, 'compress')
        assert output_storage.raw == expected
        assert lib.tscb_compress(handle, C.byref(source), C.byref(output)) != 0
        finish_storage = C.create_string_buffer(1); finish = byte_buffer(finish_storage, capacity=0)
        bridge._check(lib.tscb_finalize(handle, C.byref(finish)), handle, 'finalize')
        assert finish.used_bytes == 0 and lib.tscb_finalize(handle, C.byref(finish)) != 0
        bridge._check(lib.tscb_reset(handle, 0), handle, 'reset')
        assert lib.tscb_finalize(handle, C.byref(finish)) != 0
    for corrupt in [expected[:-1], expected + b'\0', expected[:-1] + bytes([expected[-1] ^ 1])]:
        storage = C.create_string_buffer(corrupt, len(corrupt))
        source = byte_buffer(storage, capacity=len(corrupt), used=len(corrupt))
        target = C.create_string_buffer(b'\xa5' * array.nbytes, array.nbytes)
        destination = byte_buffer(target, capacity=array.nbytes)
        with bridge._session(params, 'decode') as handle:
            assert lib.tscb_decompress(handle, C.byref(source), C.byref(destination)) != 0
            assert destination.used_bytes == 0 and target.raw == b'\xa5' * array.nbytes


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
def test_resource_dtype_model_and_fp_refusals(key):
    lib = library(key); array = np.arange(1, dtype='<f8')
    configs = [configuration(array, {}) for _ in range(3)]
    configs[0].shape[0] = 16777217
    configs[1].dtype = 7
    configs[2].model = b'external-model'
    for config in configs:
        handle = C.c_void_p()
        assert lib.tsbench_core_create(C.byref(config), 0, C.byref(handle)) == 2
        assert not handle.value
    # FE_DOWNWARD is 0x400 on the current x86_64 qualification host.
    import platform
    if platform.machine() == 'x86_64':
        fenv = C.CDLL('libm.so.6')
        previous = fenv.fegetround()
        handle = context(lib, configuration(array, {})); source = buffer(array.tobytes())
        output = buffer(b'\xa5' * 65536); result = Result()
        try:
            assert fenv.fesetround(0x400) == 0
            assert lib.tsbench_core_encode(handle, source, array.nbytes, output, len(output), C.byref(result)) == 2
            assert result.size == 0 and bytes(output) == b'\xa5' * len(output)
        finally:
            assert fenv.fesetround(previous) == 0
            lib.tsbench_core_release(C.byref(result)); lib.tsbench_core_destroy(handle)


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
def test_new_process_decodes_without_encoder_parameters(tmp_path, key):
    array = np.arange(1025, dtype='<f8') / 100
    path = tmp_path / 'native.alp'; path.write_bytes(encode(library(key), key, array))
    out = tmp_path / 'decoded.raw'
    code = '''
import ctypes as c,sys
lib=c.CDLL(sys.argv[1]);data=open(sys.argv[2],'rb').read();out=c.create_string_buffer(8200)
lib.alp_port_decode.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t),c.POINTER(c.c_uint64),c.POINTER(c.c_uint8),c.POINTER(c.c_uint8)]
used,consumed,n,d,m=c.c_size_t(),c.c_size_t(),c.c_uint64(),c.c_uint8(),c.c_uint8()
assert lib.alp_port_decode(data,len(data),out,len(out),c.byref(used),c.byref(consumed),c.byref(n),c.byref(d),c.byref(m))==0
assert consumed.value==len(data) and n.value==1025 and d.value==8
open(sys.argv[3],'wb').write(out.raw[:used.value])
'''
    subprocess.run([sys.executable, '-c', code, str(artifact_path(ROOT, key)), str(path), str(out)], check=True)
    assert out.read_bytes() == array.tobytes()


@pytest.mark.parametrize('key', ['alp', 'alp-rd'])
@pytest.mark.parametrize('boundary', ['native_core', 'native_api'])
@pytest.mark.parametrize('mode', ['prepared', 'fresh_request'])
def test_v4_batches_validate_all_products_and_independent_recovery(tmp_path, key, boundary, mode):
    from tsbench import native
    from tsbench.config import DEFAULT_EXECUTION, DEFAULT_PROFILE, DEFAULT_TASK
    from tsbench.data import TimeSeriesObject
    native.ensure_driver(ROOT, ROOT / 'build/tsbench')
    array = np.arange(2050, dtype='<f8').reshape(1025, 2) / 100
    array[5, 1] = np.inf
    obj = TimeSeriesObject({'V': array}, {'roles': {'V': 'V'}, 'masked_value_policy': 'preserve_all_bits'})
    method = {'id': key, 'codec': key, 'params': Registry(ROOT).resolve_params(key)}
    task = {**DEFAULT_TASK, 'boundary': boundary, 'lifecycle': mode}
    execution = {**DEFAULT_EXECUTION, 'native_loops': 2, 'native_warmup_loops': 1,
                 'native_batch_memory_mb': 32, 'timeout_s': 60}
    support = native.capability(method, obj, task, DEFAULT_PROFILE, ROOT, ROOT / 'build/tsbench')
    assert support['supported'], support
    measurement = native.NativeMeasurement(method, task, execution, support, ROOT, ROOT / 'build/tsbench')
    measurement.prepare(obj)
    row, wire = measurement.measure(obj, independent=True, artifact_dir=tmp_path / 'products')
    assert row['status'] == 'ok' and wire == b''
    assert row['verification']['passed'] and row['verification']['validated_operations'] == 3
    assert row['independent_recovery']['passed'] and row['independent_recovery']['decoder_process']
    assert len(row['native_products']) == 3
    assert all(x['verification']['passed'] for x in row['native_products'])
    payload = Path(row['artifact_path']).read_bytes()
    assert payload.startswith(b'ALPRW001' if boundary == 'native_core' else b'APS1')
    if boundary == 'native_core':
        assert row['codec_complete_bytes'] == len(payload)
        assert row['bits_per_value'] == len(payload) * 8 / array.size


def test_frozen_consumption_files_match_release_lock():
    lock = json.loads((ROOT / 'adapters/alp/FROZEN_SOURCES.json').read_text())
    assert not lock['consumed_core_modified']
    for row in lock['files']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']


def test_build_refuses_a_changed_frozen_source_before_compilation(tmp_path, monkeypatch):
    from tsbench import _native_recipes as recipes
    adapter = tmp_path / 'adapters/alp'; adapter.mkdir(parents=True)
    source = adapter / 'changed.cpp'; source.write_text('changed source')
    (adapter / 'FROZEN_SOURCES.json').write_text(json.dumps({'files': [
        {'path': 'adapters/alp/changed.cpp', 'sha256': hashlib.sha256(b'original source').hexdigest()}]}))
    monkeypatch.setattr(recipes, 'PROJECT_ROOT', tmp_path)
    with pytest.raises(RuntimeError, match='frozen ALP safe-v1 source changed'):
        recipes._alp_command(tmp_path / 'lib.so', 'release', 'alp')


def test_same_name_legacy_library_cannot_satisfy_new_registry(monkeypatch):
    from tsbench.bridges import c_abi_v1
    class LegacyLibrary:
        value = b'{"algorithm":"alp","scheme":"FORCED_DECIMAL_ALP_NO_RD_FALLBACK"}'
        def tscb_get_manifest_json(self, pointer, length):
            C.cast(pointer, C.POINTER(C.c_char_p))[0] = self.value
            C.cast(length, C.POINTER(C.c_uint64))[0] = len(self.value)
            return 0
    monkeypatch.setattr(c_abi_v1, 'load_library', lambda *_: LegacyLibrary())
    with pytest.raises(CodecError, match='stale ALP library'):
        c_abi_v1.CAbiBridge(Registry(ROOT).get('alp'), Path('legacy.so'), 'legacy')
