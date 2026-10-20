"""Direct model/records correctness using the central build, outside benchmarks."""
from __future__ import annotations

import ctypes as C
import json
import os
import struct
import subprocess
import sys
import tomllib

import numpy as np
import pytest

from tsbench.registry import Registry
from tsbench.build import artifact_path
from tsbench.bridges import create_bridge
from tsbench.runtime import loaded_runtime, worker_environment
from test_core_floats import ROOT, Config, Result, U8P, buffer, check, library

MODELS = ('abba', 'fabba', 'deepzip', 'dzip')
GORILLA = 'gorilla-prometheus-xor'
BITS = np.array([0, 1 << 63, 0x7ff0000000000000, 0xfff0000000000000,
                 0x7ff0000000000001, 0x7ff8123456781234, 1, 0xffffffffffffffff], dtype='<u8')
_DZIP_CHILD = 'TSBENCH_TEST_DZIP_RUNTIME_CHILD'
_DZIP_PROFILE = ROOT / 'benchmark/examples/dzip_runtime.toml'


def dzip_runtime_subprocess(request):
    """Run this exact case with the existing explicit DZip loader profile.

    NumPy may have already mapped Conda's older libstdc++ in the main pytest
    process. Select the declared runtime before child Python starts; changing
    LD_PRELOAD after CDLL/import would neither replace it nor test that profile.
    """
    profile = tomllib.loads(_DZIP_PROFILE.read_text())['profiles'][0]
    requested = profile['runtime_preload']
    assert profile['native_threads'] == 3 and requested
    request.node.user_properties.append(('dzip_runtime_profile', str(_DZIP_PROFILE)))
    request.node.user_properties.append(('dzip_runtime_preload', json.dumps(requested)))
    if os.environ.get(_DZIP_CHILD) == request.node.nodeid:
        assert artifact_path(ROOT, 'dzip').is_file(), 'central DZip build is required, not skipped'
        runtime = loaded_runtime()
        assert runtime['implemented'] and runtime['mechanism'] == '/proc/self/maps'
        mapped = {entry['path'] for entry in runtime['libraries']}
        from pathlib import Path
        assert {str(Path(path).resolve(strict=True)) for path in requested} <= mapped
        assert all(path in runtime['ld_preload'].replace(':', ' ').split() for path in requested)
        return False
    environment = worker_environment(dict(os.environ), profile)
    environment[_DZIP_CHILD] = request.node.nodeid
    # A parent's optional junit path must never be overwritten by this child.
    environment.pop('PYTEST_ADDOPTS', None)
    command = [sys.executable, '-m', 'pytest', '-q', '--rootdir', str(request.config.rootpath)]
    if request.config.inipath is not None:
        command.extend(['-c', str(request.config.inipath)])
    command.append(str(request.node.path) + '::' + request.node.nodeid.split('::', 1)[1])
    completed = subprocess.run(command,
                               cwd=ROOT, env=environment, capture_output=True, text=True,
                               timeout=120)
    assert completed.returncode == 0, completed.stdout + '\n' + completed.stderr
    assert '1 passed' in completed.stdout, completed.stdout + '\n' + completed.stderr
    return True


def configuration(key, count, params, model=None):
    dtype = 11 if key == GORILLA else 10 if key in ('abba', 'fabba') else 2
    shape = (count, 2) if key == GORILLA else (count,)
    return Config(1, dtype, len(shape), 0, (C.c_uint64 * 8)(*shape),
                  json.dumps(params, separators=(',', ':')).encode(),
                  None if model is None else str(model).encode())


def context(lib, key, count, params, model=None, decoder=False):
    handle = C.c_void_p()
    config = configuration(key, count, params, model)
    check(lib, lib.tsbench_core_create(C.byref(config), decoder, C.byref(handle)))
    return handle


def encode_all(lib, key, count, inputs, params, model=None):
    handle = context(lib, key, count, params, model)
    results = []
    try:
        for data in inputs:
            source = buffer(data)
            if key in MODELS:
                lib.tsbench_core_validate_input.argtypes = [C.c_void_p, U8P, C.c_size_t]
                check(lib, lib.tsbench_core_validate_input(handle, source, len(data)), handle)
            bound = C.c_size_t()
            check(lib, lib.tsbench_core_bound(handle, source, len(data), C.byref(bound)), handle)
            result = Result()
            results.append(result)
            # All five encode paths transfer native storage. No ABI output copy
            # or caller output allocation is needed to obtain the complete frame.
            check(lib, lib.tsbench_core_encode(handle, source, len(data), None,
                                              bound.value, C.byref(result)), handle)
            assert result.owner and 0 < result.size <= bound.value
            assert result.capacity >= result.size
            assert bytes(source)[:len(data)] == data
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        # Inspect every retained owner after destroying the producing context.
        return [C.string_at(result.data, result.size) for result in results]
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        for result in results:
            lib.tsbench_core_release(C.byref(result))


def decode(lib, key, count, stream, expected_bytes):
    # Intentionally no model filename or encoder parameters in this context.
    handle = context(lib, key, count, {}, decoder=True)
    source = buffer(stream)
    output = buffer(b'\xa5' * (expected_bytes + 16))
    result = Result()
    try:
        check(lib, lib.tsbench_core_decode(handle, source, len(stream), output,
                                          expected_bytes, C.byref(result)), handle)
        assert bool(result.owner) == (key != GORILLA)
        check(lib, lib.tsbench_core_destroy(handle))
        handle = None
        restored = C.string_at(result.data, result.size)
        assert result.size == expected_bytes
        assert bytes(output[expected_bytes:]) == b'\xa5' * 16
        if key != GORILLA:
            assert bytes(output) == b'\xa5' * (expected_bytes + 16)
        return restored
    finally:
        if handle is not None:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))


@pytest.mark.parametrize('key', ['abba', 'fabba'])
@pytest.mark.parametrize('count', [2, 17])
def test_symbolic_complete_native_model_restores_grid_with_no_encoder_state(key, count):
    lib = library(key)
    values = np.arange(count, dtype='<f8') / 8
    params = Registry(ROOT).resolve_params(key, {'max_len': 4})
    stream = encode_all(lib, key, count, [values.tobytes()], params)[0]
    assert stream[:4] == (b'ABBA' if key == 'abba' else b'FABB')
    assert int.from_bytes(stream[8:16], 'little') == count
    symbols, centers = struct.unpack_from('<II', stream, 16)
    header = 64 if key == 'abba' else 72
    assert symbols and centers and len(stream) == header + centers * 16 + symbols * 2 + 4
    restored = np.frombuffer(decode(lib, key, count, stream, values.nbytes), dtype='<f8')
    # This dyadic straight line is represented exactly; this is not a general
    # error guarantee for the empirical ABBA/fABBA algorithms.
    np.testing.assert_array_equal(restored, values)


_SYMBOLIC_PROFILES = [
    ('abba', {}),
    ('abba', {'compression_tolerance': '0', 'digitization_tolerance': '0',
              'max_len': 3, 'max_k': 4, 'norm': 1, 'clustering': 'INCREMENTAL'}),
    ('abba', {'compression_tolerance': '0.05', 'digitization_tolerance': '0.3',
              'max_len': 7, 'max_k': 8, 'norm': 2, 'scl': '1.5'}),
    ('abba', {'max_len': 31, 'norm': 1, 'clustering': 'INCREMENTAL', 'scl': '1'}),
    ('fabba', {}),
    ('fabba', {'tolerance': '0', 'alpha': '0', 'max_len': 3}),
    ('fabba', {'tolerance': '0.05', 'alpha': '0.25', 'max_len': 7, 'scl': '0.5'}),
    ('fabba', {'tolerance': '0.2', 'alpha': '0.5', 'max_len': 31, 'scl': '2'}),
]


@pytest.mark.parametrize('key,overrides', _SYMBOLIC_PROFILES)
@pytest.mark.parametrize('count', [2, 17, 65])
def test_symbolic_encode_only_matches_original_native_complete_bytes(key, overrides, count):
    lib = library(key)
    params = Registry(ROOT).resolve_params(key, overrides)
    values = ((np.arange(count, dtype=np.int64) % 7) - 3).astype('<f8') / 8
    raw = values.tobytes()
    direct = encode_all(lib, key, count, [raw], params)[0]
    # RW's native binding still calls the original encode -> transform path,
    # including its unused reconstructed vector. Compare the native stream,
    # before Python adds any RW collection framing.
    original = create_bridge(ROOT, key)
    config = original._config(count, params)
    capacity = original._call('bound', raw, config)
    reference = original._call('encode', raw, config, capacity)
    assert direct == reference
    # Recovery/quality is a separate operation after encoding. The new entry
    # must preserve every native header, parameter, center, symbol and CRC.
    restored = decode(lib, key, count, direct, values.nbytes)
    reference_restored = original._call('decode', reference, capacity=values.nbytes)
    assert restored == reference_restored
    assert np.isfinite(np.frombuffer(restored, dtype='<f8')).all()
    assert values.tobytes() == raw


@pytest.mark.parametrize('lanes,count', [(1, 0), (1, 7), (3, 70)])
def test_deepzip_full_portable_model_is_in_stream_and_external_file_can_disappear(tmp_path, lanes, count):
    key = 'deepzip'
    lib = library(key)
    params = Registry(ROOT).resolve_params(key, {'lanes': lanes})
    record = Registry(ROOT).get(key).document['adapter']['models'][params['model_key']]
    model_bytes = (ROOT / record['path']).read_bytes()
    copied_model = tmp_path / 'model.dzm'
    copied_model.write_bytes(model_bytes)
    values = (np.arange(count) % 4).astype('u1')
    stream = encode_all(lib, key, count, [values.tobytes()], params, copied_model)[0]
    copied_model.unlink()
    assert stream[:8] == b'DZCPP001'
    assert int.from_bytes(stream[16:24], 'little') == count
    assert int.from_bytes(stream[24:28], 'little') == lanes
    alphabet = int.from_bytes(stream[28:32], 'little')
    model_size = int.from_bytes(stream[32:40], 'little')
    assert model_size == len(model_bytes)
    assert stream[44 + alphabet:44 + alphabet + model_size] == model_bytes
    assert len(stream) > 44 + alphabet + model_size
    assert decode(lib, key, count, stream, values.nbytes) == values.tobytes()


@pytest.mark.parametrize('mode', ['BOOTSTRAP', 'COMBINED'])
def test_dzip_recreates_input_dependent_model_per_operation_and_serializes_it(mode, request):
    if dzip_runtime_subprocess(request):
        return
    key = 'dzip'
    lib = library(key)
    params = Registry(ROOT).resolve_params(key, {'mode': mode, 'model_seed': 7})
    # Same prepared context, different actual alphabet. A cached first-input
    # model would reject or incorrectly encode the second operation.
    inputs = [b'\x07\x0b\x07\x0b', b'\x01\x05\x09\x0d']
    streams = encode_all(lib, key, 4, inputs, params)
    for raw, stream, alphabet in zip(inputs, streams, [2, 4]):
        assert stream[:8] == b'DZCP0001'
        assert stream[8] == int(mode == 'COMBINED')
        assert int.from_bytes(stream[10:12], 'little') == alphabet
        assert int.from_bytes(stream[12:20], 'little') == len(raw)
        raw_model, stored_model, payload = struct.unpack_from('<QQQ', stream, 20)
        assert raw_model > 0 and stored_model > 0 and payload > 0
        assert len(stream) == 44 + alphabet + stored_model + payload + 4
        assert decode(lib, key, 4, stream, len(raw)) == raw


@pytest.mark.parametrize('key', MODELS)
def test_independent_model_decoder_rejects_encoder_parameters_and_external_model(key, request):
    if key == 'dzip' and dzip_runtime_subprocess(request):
        return
    lib = library(key)
    for params, model in [({'unused': 1}, None), ({}, 'unavailable-model-file')]:
        config = configuration(key, 2, params, model)
        handle = C.c_void_p()
        assert lib.tsbench_core_create(C.byref(config), 1, C.byref(handle)) == 1
        assert handle.value is None


@pytest.mark.parametrize('key', ['abba', 'fabba', 'deepzip'])
def test_input_admission_rejects_domains_outside_algorithm_contract(key):
    lib = library(key)
    registry = Registry(ROOT)
    params = registry.resolve_params(key)
    model = None
    if key == 'deepzip':
        record = registry.get(key).document['adapter']['models'][params['model_key']]
        model = ROOT / record['path']
        raw = b'\0\xff'
    else:
        raw = np.array([0., np.inf], dtype='<f8').tobytes()
    handle = context(lib, key, 2, params, model)
    source = buffer(raw)
    lib.tsbench_core_validate_input.argtypes = [C.c_void_p, U8P, C.c_size_t]
    try:
        assert lib.tsbench_core_validate_input(handle, source, len(raw)) == 2
    finally:
        lib.tsbench_core_destroy(handle)


def golden_chunks(path, magic, records=False):
    data = path.read_bytes()
    assert data[:4] == magic
    count = int.from_bytes(data[4:8], 'little')
    position, result = 8, []
    for _ in range(count):
        size = int.from_bytes(data[position:position + 4], 'little')
        position += 4
        size *= 16 if records else 1
        result.append(data[position:position + size])
        position += size
    assert position == len(data)
    return result


@pytest.mark.parametrize('path', ['canonical', 'optimized'])
def test_gorilla_direct_matches_all_archived_upstream_complete_streams(path):
    lib = library(GORILLA)
    base = ROOT / 'adapters/gorilla_prometheus_xor/vendor/gorilla/tests/golden'
    inputs = golden_chunks(base / 'input.bin', b'GRI1', True)
    outputs = golden_chunks(base / 'expected_output.bin', b'GRS1')
    assert len(inputs) == len(outputs) == 36
    for raw, expected in zip(inputs, outputs):
        stream = encode_all(lib, GORILLA, len(raw) // 16, [raw], {'path': path})[0]
        assert stream == expected
        assert decode(lib, GORILLA, len(raw) // 16, stream, len(raw)) == raw


@pytest.mark.parametrize('path', ['canonical', 'optimized'])
@pytest.mark.parametrize('count', [0, 1, 2, 7, 65535])
def test_gorilla_direct_joint_bits_extreme_timestamps_and_count_boundaries(path, count):
    lib = library(GORILLA)
    timestamps = np.resize(np.array([-2**63, 2**63 - 1, 0, -1, 0, 0, 7, 2], dtype='<i8'), count)
    values = np.resize(BITS, count)
    pairs = np.column_stack((timestamps.view('<u8'), values)).astype('<u8')
    raw = pairs.tobytes()
    stream = encode_all(lib, GORILLA, count, [raw], {'path': path})[0]
    assert int.from_bytes(stream[:2], 'big') == count
    assert decode(lib, GORILLA, count, stream, count * 16) == raw


def test_gorilla_direct_over_count_and_wrong_header_rejected():
    lib = library(GORILLA)
    config = configuration(GORILLA, 65536, {'path': 'canonical'})
    handle = C.c_void_p()
    assert lib.tsbench_core_create(C.byref(config), 0, C.byref(handle)) == 2
    assert handle.value is None
    handle = context(lib, GORILLA, 1, {}, decoder=True)
    source = buffer(b'\0\0')
    output = buffer(b'\xa5' * 32)
    result = Result()
    try:
        assert lib.tsbench_core_decode(handle, source, 2, output, 16, C.byref(result)) == 1
        assert bytes(output) == b'\xa5' * 32
    finally:
        lib.tsbench_core_release(C.byref(result))
        lib.tsbench_core_destroy(handle)
