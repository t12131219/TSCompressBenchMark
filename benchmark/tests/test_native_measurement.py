"""Real compiled native batches and the validation which admits their results.

These short correctness runs do not supply performance evidence. The fixture
builds only the independent driver and uses already installed codec binaries.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

import numpy as np
import pytest

from tsbench import native
from tsbench.build import artifact_path
from tsbench.config import DEFAULT_EXECUTION, DEFAULT_PROFILE, DEFAULT_TASK
from tsbench.data import TimeSeriesObject, fingerprint
from tsbench.errors import BenchError, ValidationError
from tsbench.registry import CodecError, Registry

ROOT = Path(__file__).resolve().parents[2]
CODECS = ('zstd-frame', 'lz4-frame', 'snappy-raw', 'lzsse2-raw')


@pytest.fixture(scope='module')
def native_build(tmp_path_factory):
    if not shutil.which(os.environ.get('CXX', 'g++')):
        pytest.skip('C++ compiler unavailable')
    directory = tmp_path_factory.mktemp('native-measurement-build')
    record = native.ensure_driver(ROOT, directory)
    # Copy only indices. Their artifacts/build records remain the exact locally
    # installed binaries, so tests neither rebuild nor substitute a codec.
    for key in CODECS:
        index = ROOT / 'build/tsbench' / f'{key}.index.json'
        if index.is_file():
            shutil.copy2(index, directory / index.name)
    return directory, record


def object_with(array):
    return TimeSeriesObject({'V': array}, {'roles': {'V': 'V'}, 'masked_value_policy': 'preserve_all_bits'})


def measurement(native_build, key='raw-store', *, mode='prepared', boundary='native_core', array=None):
    directory, _ = native_build
    if key != 'raw-store' and not artifact_path(ROOT, key, build_root=directory).is_file():
        pytest.skip(f'installed native codec unavailable: {key}')
    original = object_with(np.arange(257, dtype='<f8') / 8 if array is None else array)
    method = {'id': key, 'codec': key, 'params': Registry(ROOT).resolve_params(key)}
    task = {**DEFAULT_TASK, 'boundary': boundary, 'lifecycle': mode}
    execution = {**DEFAULT_EXECUTION, 'native_loops': 3, 'native_warmup_loops': 2,
                 'native_batch_memory_mb': 32, 'timeout_s': 30}
    support = native.capability(method, original, task, DEFAULT_PROFILE, ROOT, directory)
    assert support['supported'], support
    handle = native.NativeMeasurement(method, task, execution, support, ROOT, directory)
    handle.prepare(original)
    return handle, original


@pytest.mark.parametrize('key', ['raw-store', 'zstd-frame', 'lz4-frame', 'snappy-raw'])
@pytest.mark.parametrize('mode', ['prepared', 'fresh_request'])
def test_compiled_batches_validate_every_warmup_and_measurement(native_build, tmp_path, key, mode):
    handle, original = measurement(native_build, key, mode=mode)
    before = fingerprint(original)
    row, wire = handle.measure(original, independent=True, artifact_dir=tmp_path / 'products')
    assert row['status'] == 'ok' and wire == b''
    assert row['verification']['passed'] and row['verification']['validated_operations'] == 5
    products = row['native_products']
    assert [(item['phase'], item['index']) for item in products] == [
        ('warmup', 0), ('warmup', 1), ('measurement', 0), ('measurement', 1), ('measurement', 2)]
    assert all(item['verification']['passed'] for item in products)
    assert row['loops'] == 3 and row['native_batch']['warmup_iterations'] == 2
    assert row['native_batch']['python_inside_batch_clock'] is False
    assert row['native_batch']['native_loop_batch'] is True
    assert row['native_batch']['clock'] == 'CLOCK_MONOTONIC'
    assert row['native_batch']['clock_resolution_ns'] > 0
    assert row['encode_batch_ns'] > 0 and row['decode_batch_ns'] > 0
    assert row['encode_ns'] * 3 == pytest.approx(row['encode_batch_ns'])
    assert row['decode_ns'] * 3 == pytest.approx(row['decode_batch_ns'])
    assert row['native_batch']['retained_output_release_outside_timing'] is True
    assert row['native_batch']['caller_pages_pretouched'] is (mode == 'prepared')
    assert row['native_batch']['mode'] == mode
    assert row['native_batch']['native_internal_memory_known'] is False
    assert row['native_batch']['caller_memory_bytes'] <= 32 * 1024**2
    assert row['native_batch']['affinity_cpus']
    assert row['native_batch']['rlimit_as'] is not None
    assert row['independent_recovery']['passed']
    assert row['independent_recovery']['decoder_pid'] != row['native_batch']['process_pid']
    assert row['native_batch']['process_pid'] != os.getpid()
    assert row['native_runtime']['implemented'] and row['native_runtime']['libraries']
    assert row['raw_bytes'] == original.components['V'].nbytes
    assert row['codec_input_bytes'] == row['raw_bytes']
    assert row['value_count'] == original.components['V'].size
    assert row['codec_complete_bytes'] == row['native_output_bytes']
    assert row['bits_per_value'] == row['codec_complete_bytes'] * 8 / row['value_count']
    assert row['framework_management_bytes_in_codec_size'] == 0
    assert row['framework_management_bytes'] > 0
    payload = Path(row['artifact_path']).read_bytes()
    assert len(payload) == row['codec_complete_bytes']
    assert fingerprint(original) == before
    if key == 'raw-store':
        assert payload == original.components['V'].tobytes()
    if key == 'lz4-frame':
        assert all(size > 0 for size in row['native_batch']['finalize_sizes'])


@pytest.mark.parametrize('phase', ['', 'warmup-'])
def test_middle_restored_product_failure_cannot_be_hidden_by_last_result(native_build, monkeypatch, phase):
    handle, original = measurement(native_build)
    checked = native.checked_driver

    def corrupt_middle(command, timeout):
        result = checked(command, timeout)
        if '--probe' not in command and '--decode-only' not in command:
            directory = Path(command[command.index('--result-dir') + 1])
            path = directory / f'{phase}restored-000001.bin'
            data = bytearray(path.read_bytes())
            data[0] ^= 1
            path.write_bytes(data)
        return result

    monkeypatch.setattr(native, 'checked_driver', corrupt_middle)
    row, _ = handle.measure(original)
    assert row['status'] == 'error' and not row['verification']['passed']
    assert row['verification']['validated_operations'] == 5
    assert row['native_products'][-1]['verification']['passed']
    failed = [item for item in row['native_products'] if not item['verification']['passed']]
    assert [(item['phase'], item['index']) for item in failed] == [('warmup' if phase else 'measurement', 1)]


def test_actual_driver_input_mutation_is_rejected(native_build, monkeypatch):
    handle, original = measurement(native_build)
    checked = native.checked_driver

    def mutate_real_input_evidence(command, timeout):
        result = checked(command, timeout)
        if '--probe' not in command:
            directory = Path(command[command.index('--result-dir') + 1])
            path = directory / 'input-after.bin'
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
        return result

    monkeypatch.setattr(native, 'checked_driver', mutate_real_input_evidence)
    with pytest.raises(ValidationError, match='input buffer was modified'):
        handle.measure(original)


@pytest.mark.parametrize('mode', ['prepared', 'fresh_request'])
def test_memory_budget_counts_all_retained_outputs_before_allocation(native_build, tmp_path, mode):
    _, record = native_build
    source = tmp_path / 'input.bin'
    source.write_bytes(bytes(range(256)))
    output = tmp_path / 'results'
    command = [record['binary'], '--abi', 'raw', '--codec', 'raw-store', '--input', str(source),
               '--output-bytes', '256', '--loops', '3', '--warmup', '2', '--mode', mode,
               '--memory-bytes', '1024', '--result-dir', str(output)]
    with pytest.raises(BenchError, match='budget'):
        native.checked_driver(command, 30)
    assert not list(output.glob('payload-*.bin'))
    assert not list(output.glob('restored-*.bin'))


def test_direct_core_cannot_bypass_source_dtype_constraints(native_build):
    directory, _ = native_build
    original = object_with(np.arange(17, dtype='u1'))
    task = {**DEFAULT_TASK, 'boundary': 'native_core', 'lifecycle': 'prepared'}
    support = native.capability({'id': 'chimp', 'codec': 'chimp'}, original, task, DEFAULT_PROFILE, ROOT, directory)
    assert support['supported'] is False
    assert support['status'] == 'unsupported'
    assert support['reason']
    assert 'driver' not in support


@pytest.mark.parametrize('length', [0, 1, 257])
def test_c1_batch_includes_real_finish_and_independent_decode(native_build, tmp_path, length):
    handle, original = measurement(native_build, 'zstd-frame', boundary='native_api',
                                   array=(np.arange(length) % 251).astype(np.uint8))
    row, _ = handle.measure(original, independent=True, artifact_dir=tmp_path / 'products')
    assert row['status'] == 'ok' and row['verification']['validated_operations'] == 5
    assert row['native_batch']['native_api_internal_work_included'] is True
    assert all(tail > 0 for tail in row['native_batch']['finalize_sizes'])
    assert row['native_batch']['output_sizes'] == [
        head + tail for head, tail in zip(row['native_batch']['head_sizes'], row['native_batch']['finalize_sizes'])]
    assert row['independent_recovery']['passed']
    payload = Path(row['artifact_path']).read_bytes()
    # A real decoder rejects the exact complete stream when its final tail is
    # removed. This checks finalization, beyond a renamed reporting field.
    if length:
        from tsbench.bridges import create_bridge
        bridge = create_bridge(ROOT, 'zstd-frame', build_root=native_build[0])
        with pytest.raises(CodecError):
            bridge.decode(payload[:-1], original.components['V'].dtype, original.components['V'].shape,
                          handle.method['params'])


def test_abi_only_size_stays_unknown_without_reviewed_output_parser(native_build):
    handle, original = measurement(native_build, 'lzsse2-raw', boundary='native_api',
                                   array=(np.arange(257) % 251).astype(np.uint8))
    row, _ = handle.measure(original)
    assert row['status'] == 'ok' and row['native_output_bytes'] > 0
    assert row['codec_complete_bytes'] is None
    assert row['stored_bytes'] is None and row['bits_per_value'] is None
    assert row['codec_complete_bytes_null_reason']


def test_decoder_only_accepts_core_stream_without_encoder_configuration(native_build, tmp_path):
    handle, original = measurement(native_build, 'zstd-frame')
    row, _ = handle.measure(original, loops=1, warmup=0, artifact_dir=tmp_path / 'products')
    config = tmp_path / 'decoder.json'
    config.write_text('{}')
    directory = tmp_path / 'fresh-decoder'
    result = native.checked_driver([
        native_build[1]['binary'], '--abi', 'zstd', '--codec', 'zstd-frame',
        '--library', handle.support['library_path'], '--input', row['artifact_path'],
        '--config-file', str(config), '--output-bytes', str(original.components['V'].nbytes),
        '--decode-only', '--loops', '1', '--warmup', '0', '--result-dir', str(directory)], 30)
    assert result['decode_only'] and result['encode_batch_ns'] == 0
    assert result['process_pid'] != row['native_batch']['process_pid']
    assert (directory / 'restored-000000.bin').read_bytes() == original.components['V'].tobytes()
    assert (directory / 'input-after.bin').read_bytes() == Path(row['artifact_path']).read_bytes()
    assert not list(directory.glob('payload-*.bin'))


def test_runtime_probe_loads_native_symbols_without_input_or_operations(native_build, tmp_path):
    directory = tmp_path / 'probe'
    result = native.checked_driver([native_build[1]['binary'], '--abi', 'raw', '--codec', 'raw-store',
                                    '--probe', '--result-dir', str(directory)], 30)
    assert result['probe_only'] and result['stage'] == 'probe_complete'
    assert result['iterations'] == 0 and result['warmup_iterations'] == 0
    assert result['encode_batch_ns'] == result['decode_batch_ns'] == 0
    assert (directory / 'runtime_maps.txt').is_file()
    assert native.mapped_runtime(result, directory)['libraries']
    assert not list(directory.glob('*.bin'))


def test_missing_direct_symbol_is_unsupported_without_abi_fallback(native_build, tmp_path):
    library = artifact_path(ROOT, 'lz4-frame', build_root=native_build[0])
    if not library.is_file():
        pytest.skip('installed LZ4 codec unavailable')
    # An LZ4-only shared library cannot provide the required Zstd direct API.
    # Loading failure must keep its reason; no adapter ABI fallback is allowed.
    with pytest.raises(BenchError) as caught:
        native.checked_driver([
            native_build[1]['binary'], '--abi', 'zstd', '--codec', 'zstd-frame',
            '--library', str(library), '--probe', '--result-dir', str(tmp_path / 'probe')], 30)
    assert caught.value.status == 'unsupported'
    assert caught.value.stage == 'native.load_symbol'
    assert caught.value.native_batch['native_status'] == 2
    assert 'unavailable native codec symbol: ZSTD_createCCtx' in str(caught.value)


def test_core_input_identity_uses_same_logical_descriptor_across_apis(native_build):
    directory, _ = native_build
    key='brotli-stream'
    index=ROOT/'build/tsbench'/f'{key}.index.json'
    if not index.is_file():pytest.skip('build Brotli direct core first')
    shutil.copy2(index,directory/index.name)
    first,obj=measurement(native_build,'raw-store')
    second,_=measurement(native_build,key,array=obj.components['V'])
    a,_=first.measure(obj,loops=1,warmup=0)
    b,_=second.measure(obj,loops=1,warmup=0)
    assert a['codec_input_id']==b['codec_input_id']
    assert a['native_input']['dtype']=='|u1'
    assert b['native_input']['dtype']=='<f8'
    assert a['raw_bytes']==b['raw_bytes']==obj.components['V'].nbytes
