"""GPU lifecycle/schedule contracts without pretending mocks are CUDA evidence."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

from tsbench import gpu
from tsbench.bridges import cuszp
from tsbench.data import TimeSeriesObject, fingerprint
from tsbench.records import append, write_json


def object_fixture(dtype='<f4', n=33):
    return TimeSeriesObject({'V': np.arange(1, n + 1, dtype=dtype)},
                            {'roles': {'V': 'V'}, 'topology': 'UTS', 'task': 'values',
                             'masked_value_policy': 'preserve_all_bits'})


def config_fixture(tmp_path):
    path = tmp_path / 'input.npy'
    np.save(path, object_fixture().components['V'])
    return gpu.resolve({'schema': 'tsbench.gpu-experiment/1', 'name': 'unit',
                        'datasets': [{'id': 'input', 'format': 'npy', 'path': str(path)}],
                        'methods': [{'id': 'fixed', 'codec': gpu.KEY, 'error_bound': '0.1'}],
                        'task': {'fidelity': 'bounded_abs', 'error_bound': '0.1'},
                        'execution': {'sessions': 3, 'rounds': 7, 'warmup_objects': 0},
                        'profile': {'device': 'cuda', 'device_index': 0}}, tmp_path)


@pytest.mark.parametrize('path,value', [
    (('methods', 0, 'error_bound'), True), (('task', 'error_bound'), False),
    (('task', 'relative_floor'), True), (('profile', 'device_index'), True),
    (('execution', 'rounds'), True), (('profile', 'native_threads'), 2),
    (('boundaries',), ['device_resident', 'device_resident']),
])
def test_gpu_config_rejects_ambiguous_requests(tmp_path, path, value):
    config = config_fixture(tmp_path)
    # Internal resolution fields are not user grammar.
    config = {key: value for key, value in config.items() if not key.startswith('_')}
    for method in config['methods']:
        method.pop('_requested_error_bound', None)
    current = config
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(ValueError):
        gpu.resolve(config, tmp_path)


def test_explicit_unenforceable_vram_limit_rejects_before_native_import():
    with pytest.raises(ValueError, match='requested VRAM limit cannot be enforced'):
        gpu.apply_profile({'device_index': 0, 'vram_limit_mb': 1024})


@pytest.mark.parametrize('values', [np.array([-0.0], dtype='<f4'), np.array([np.nan], dtype='<f8'),
                                   np.array([np.nextafter(np.float32(0), np.float32(1))]),
                                   np.array([1e30], dtype='<f8')])
def test_gpu_domain_does_not_silently_transform_special_or_out_of_range(values):
    original = TimeSeriesObject({'V': values}, {'roles': {'V': 'V'}, 'topology': 'UTS'})
    before = fingerprint(original)
    with pytest.raises(ValueError, match='unsupported:'):
        gpu.capability(original, {'error_bound': 0.01}, {'fidelity': 'bounded_abs', 'error_bound': '0.01'})
    assert fingerprint(original) == before


class FakeOwner:
    def __init__(self, kind, events, metadata, value, info=None):
        self.kind, self.events, self.metadata, self.value = kind, events, metadata, value
        self.info = info or {'payload_bytes': 1024, 'device_event_ms': 0.03,
                             'owned_allocation_peak_bytes': 2048}
        self.closed = False
        events.append(kind + '.create')

    def materialize(self):
        assert not self.closed
        self.events.append(self.kind + '.materialize')
        return self.value

    def close(self):
        assert not self.closed
        self.closed = True
        self.events.append(self.kind + '.close')


def mock_backend(monkeypatch):
    """Mock ownership; no tests here constitute codec correctness evidence."""
    events, sessions = [], []
    info = {'payload_bytes': 1024, 'device_event_ms': 0.03, 'owned_allocation_peak_bytes': 2048}
    def encoded(metadata):
        payload = bytes(((metadata['count'] + 32767) // 32768) * 1024)
        return cuszp.Encoded(cuszp.pack(payload, metadata['dtype'], metadata['count'], metadata['error_bound']), info)
    class Session:
        def __init__(self, dtype, count, error_bound, device, library):
            self.metadata = {'dtype': np.dtype(dtype).str, 'count': int(count),
                             'error_bound': cuszp.canonical_error_bound(dtype, error_bound), 'device': device}
            self.closed = False
            self.number = len(sessions)
            sessions.append(self)
            events.append(f'session{self.number}.create')
        def __enter__(self):
            return self
        def __exit__(self, *error):
            self.closed = True
            events.append(f'session{self.number}.close')
        def encode_host(self, array):
            assert not self.closed
            events.append('host.encode')
            return encoded(self.metadata)
        def encode_device(self, original):
            assert not self.closed and not original.closed
            events.append('device.encode.completed')
            return FakeOwner('payload', events, {**self.metadata, 'payload_bytes': 1024}, encoded(self.metadata), info)
        def decode_host(self, wire):
            assert not self.closed
            metadata, _ = cuszp.unpack(wire)
            assert all(metadata[key] == self.metadata[key] for key in ('dtype', 'count', 'error_bound'))
            events.append('host.decode')
            return np.arange(1, metadata['count'] + 1, dtype=metadata['dtype']), info
        def decode_device(self, payload):
            assert not self.closed and not payload.closed
            assert all(payload.metadata[key] == self.metadata[key] for key in ('dtype', 'count', 'error_bound'))
            events.append('device.decode.completed')
            return FakeOwner('decoded', events, self.metadata,
                             np.arange(1, self.metadata['count'] + 1, dtype=self.metadata['dtype']), info)
    def prepare(array, bound, device, library):
        return FakeOwner('input', events, {'count': array.size}, array.copy())
    def install(wire, device, library):
        metadata, _ = cuszp.unpack(wire)
        return FakeOwner('installed', events, metadata, wire)
    monkeypatch.setattr(cuszp, 'Session', Session)
    monkeypatch.setattr(cuszp, 'prepare_device_input', prepare)
    monkeypatch.setattr(cuszp, 'install_device_payload', install)
    return events, sessions


@pytest.mark.parametrize('boundary', ['host_to_host', 'device_resident'])
def test_completed_lifecycle_and_decoder_config_derive_from_wire(monkeypatch, boundary):
    events, sessions = mock_backend(monkeypatch)
    original = object_fixture()
    before = fingerprint(original)
    row, wire = gpu.measure_object(original, {'error_bound': 0.1},
                                   {'fidelity': 'bounded_abs', 'error_bound': '0.1'},
                                   boundary, object(), 0, expected_fingerprint=before,
                                   on_stage=lambda stage: events.append('stage.' + stage))
    assert row['status'] == 'ok' and row['verification']['input_unchanged']
    assert fingerprint(original) == before
    assert len(sessions) == 2 and all(session.closed for session in sessions)
    metadata = gpu.unpack_object(wire)[2]
    assert sessions[1].metadata['error_bound'] == metadata['error_bound']
    assert metadata['error_bound'] < 0.1  # downward f32 canonicalization
    assert row['stored_bytes'] == len(wire) and row['header_bytes'] + row['payload_bytes'] == len(wire)
    assert row['encode_ns'] > 0 and row['decode_ns'] > 0
    if boundary == 'device_resident':
        assert events.index('session0.close') < events.index('payload.materialize')
        assert events.index('session1.close') < events.index('decoded.materialize')
        assert events.index('input.create') < events.index('stage.encode')
        assert events.index('installed.create') < events.index('stage.decode')
        assert events.index('device.encode.completed') < events.index('session0.close')
        assert events.index('device.decode.completed') < events.index('session1.close')
        assert row['verification']['prepared_device_input_unchanged']
        assert row['device_live_artifact']['descriptor_constructed_inside_encode_clock']
        descriptor = row['device_live_artifact']['host_recovery_descriptor']
        assert descriptor['schema'] == original.schema and descriptor['count'] == 33
        assert descriptor['codec_effective_absolute_tolerance'] == metadata['error_bound']
        assert descriptor['payload_location'] == 'device' and descriptor['metadata_location'] == 'host'
        assert row['boundary_costs']['prepare_device_input_ns'] > 0
        assert row['boundary_costs']['install_device_payload_ns'] > 0
    else:
        assert row['boundary_costs'] == {}


def test_self_describing_wire_checked_before_cuda(monkeypatch):
    original = object_fixture()
    native = cuszp.Encoded(cuszp.pack(bytes(1024), '<f4', 33, 0.125), {})
    wire = gpu.pack_object(native, gpu.live_descriptor(original, native.metadata))
    schema, name, metadata, _, _ = gpu.unpack_object(wire)
    assert schema == original.schema and name == 'V' and metadata['count'] == 33
    from tsbench.artifact import read_bundle_prefix, pack_bundle
    descriptor, body = read_bundle_prefix(wire)
    descriptor['components'][0]['shape'] = [34]
    malicious = pack_bundle(descriptor, body)
    monkeypatch.setattr(cuszp, 'Session', lambda *args: pytest.fail('CUDA constructor must not run'))
    with pytest.raises(ValueError, match='differs from native typed wire'):
        gpu.decode_wire(malicious, object(), 0)


def test_real_subprocess_bad_frame_fails_before_library_load(tmp_path):
    wire = tmp_path / 'bad.tsb'
    wire.write_bytes(b'bad GPU frame')
    profile = tmp_path / 'profile.json'
    write_json(profile, {'device_index': 0})
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(gpu.__file__).resolve().parent.parent)
    done = subprocess.run([sys.executable, '-m', 'tsbench.gpu', 'decode', str(wire), str(tmp_path / 'decoded'),
                           '--asset-root', str(tmp_path / 'absent-root'), '--build-root', str(tmp_path / 'absent-build'),
                           '--profile', str(profile)], capture_output=True, timeout=10, env=env)
    assert done.returncode == 2
    result = json.loads(done.stderr.splitlines()[-1])
    assert result['status'] == 'error' and result['reason'] == 'truncated prefix'
    assert result['stage'] == 'wire_only_decode' and not (tmp_path / 'decoded').exists()


def report_fixture(tmp_path, terminals):
    case = {'case_id': 'case', 'block_id': 'block', 'dataset_id': 'data', 'method_id': 'method',
            'boundary': 'device_resident', 'status': 'ready', 'raw_bytes': 132}
    schedule = [{'case_id': 'case', 'block_id': 'block', 'session': 0, 'round': number,
                 'sequence': 0, 'attempt': 0} for number in (0, 1)]
    write_json(tmp_path / 'manifest.json', {'run_id': 'id', 'pass_kind': 'formal', 'cases': [case], 'schedule': schedule,
                                           'execution_source_unchanged': True, 'native_execution_source_unchanged': True})
    for number in terminals:
        slot = {**schedule[0], 'round': number}
        append(tmp_path / 'observations.jsonl', {'event': 'terminal', 'run_id': 'id', **slot, 'status': 'ok',
                                               'encode_ns': 100, 'decode_ns': 150, 'raw_bytes': 132,
                                               'stored_bytes': 1000, 'bits_per_value': 240,
                                               'verification': {'passed': True, 'max_abs': 0.01}})
    return gpu.generate(tmp_path)


@pytest.mark.parametrize('terminals', [[0, 0], [0, 2], [0]])
def test_report_requires_exact_schedule_and_never_summarizes_partial_success(tmp_path, terminals):
    result = report_fixture(tmp_path, terminals)
    assert not result['complete_success'] and not result['schedule_integrity']['complete']
    assert result['cases'][0]['encode_ns_median'] is None
    assert result['cases'][0]['compression_ratio_median'] is None


def test_complete_report_keeps_separate_boundary(tmp_path):
    result = report_fixture(tmp_path, [0, 1])
    assert result['complete_success'] and result['schedule_integrity']['complete']
    assert result['cases'][0]['encode_ns_median'] == 100
    assert result['cases'][0]['boundary'] == 'device_resident'


def test_adapter_release_evidence_is_not_driver_peak_claim():
    before = dict(live_bytes=0, allocations=1, releases=1, streams_created=0, streams_released=0,
                  events_created=0, events_released=0)
    after = dict(live_bytes=0, allocations=5, releases=5, streams_created=2, streams_released=2,
                 events_created=4, events_released=4)
    assert gpu.resources_released(before, after)
    after['events_released'] = 3
    assert not gpu.resources_released(before, after)
    assert 'not a sampled VRAM peak' in gpu.ALLOCATION_SCOPE


def test_native_cuda_failure_and_timeout_forbid_automatic_recovery():
    assert gpu.device_unsafe(gpu.classify_error(cuszp.GPUError(4, 'CUDA failed'), 'decode'))
    assert gpu.device_unsafe({'status': 'timeout'})
    assert gpu.device_unsafe({'status': 'crash'})
    assert not gpu.device_unsafe(gpu.classify_error(cuszp.GPUError(2, 'domain rejected'), 'prepare'))


def test_parent_cuda_failure_closes_worker_and_marks_every_remaining_slot(monkeypatch, tmp_path):
    config = config_fixture(tmp_path)
    config['execution'].update(sessions=2, rounds=2)
    requests, closed = [], []
    effective, provenance = {'gpu': 'fake'}, gpu._source_identity(root=config['_asset_root'])
    class Channel:
        def request(self, command, timeout, on_event=None):
            requests.append(command['op'])
            if command['op'] == 'init':
                return {'status': 'ok', 'effective_profile': effective, 'execution_provenance': provenance}
            if command['op'] == 'prepare':
                from tsbench.data import load_dataset, project, object_id
                obj = project(load_dataset(command['dataset'], config['_base_dir']), config['task'])
                return {'status': 'ok', 'raw_object_id': object_id(obj), 'implementation_id': 'fake',
                        'capability': {}, 'effective_profile': effective}
            if command['op'] == 'qualify':
                return {'status': 'ok', 'independent_recovery': {'passed': True}}
            if command['op'] == 'trial':
                return {'status': 'error', 'native_status': 4, 'device_recovery_confirmed': False,
                        'stage': 'encode', 'reason': 'real CUDA class of failure mocked for scheduler'}
            pytest.fail('unexpected operation ' + command['op'])
        def close(self):
            closed.append(True)
    monkeypatch.setattr(gpu, '_worker', lambda *args: Channel())
    monkeypatch.setattr('tsbench.environment.capture', lambda *args: {'snapshot': 'fake'})
    output = gpu.run(config, tmp_path / 'run')
    rows = [json.loads(line) for line in (output / 'observations.jsonl').read_text().splitlines()]
    planned = [row for row in rows if row['event'] == 'planned']
    terminal = [row for row in rows if row['event'] == 'terminal']
    assert len(planned) == len(terminal) == 8
    assert terminal[0]['status'] == 'error'
    assert all(row['status'] == 'not_run' and row['reason'] == 'device_recovery_unconfirmed' for row in terminal[1:])
    assert requests.count('trial') == 1 and requests.count('init') == 2 and len(closed) == 2
    result = json.loads((output / 'summary.json').read_text())
    assert result['schedule_integrity']['complete'] and not result['complete_success']


@pytest.mark.parametrize('parent_exits', [False, True])
def test_real_process_group_timeout_cleans_independent_decoder_descendant(tmp_path, parent_exits):
    """A new decoder interpreter must not escape a dead/timed-out leader."""
    pid_file = tmp_path / 'decoder.pid'
    program = ("import json,subprocess,sys,time\n"
               "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'])\n"
               "open(sys.argv[1],'w').write(str(child.pid))\n"
               "print(json.dumps({'event':'stage','stage':'qualification.wire_only_decode'}),flush=True)\n" +
               ("sys.exit(3)\n" if parent_exits else "time.sleep(30)\n"))
    worker = gpu.GPUWorkerProcess(tmp_path / 'worker.log',
                                  command=[sys.executable, '-c', program, str(pid_file)])
    try:
        result = worker.request({'op': 'qualify'}, 0.5)
        assert result['status'] in {'timeout', 'crash'}
        assert pid_file.is_file()
        pid = int(pid_file.read_text())
    finally:
        worker.close()
    # The container's init may retain a zombie briefly; it has no CUDA context.
    active = True
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        status = Path('/proc') / str(pid) / 'status'
        if not status.exists() or '\nState:\tZ ' in status.read_text():
            active = False
            break
        time.sleep(0.01)
    assert not active


def test_generated_grid_preserves_decimal_request_and_native_numeric_bounds(tmp_path):
    output = gpu.prepare_grid(tmp_path / 'prepared')
    config = gpu.load(output / 'gpu-abs-0p01.toml')
    assert type(config['methods'][0]['error_bound']) is float
    assert config['methods'][0]['_requested_error_bound'] == '0.01'
    assert config['task']['error_bound'] == '0.01'
    from tsbench.data import load_dataset, project
    accepted = []
    for dataset in config['datasets']:
        original = project(load_dataset(dataset, config['_base_dir']), config['task'])
        support = gpu.capability(original, config['methods'][0], config['task'])
        assert support['supported'] and support['codec_effective_absolute_tolerance'] <= 0.01
        accepted.append((support['dtype'], support['count']))
    assert set(accepted) == {(dtype, n) for dtype in ('<f4', '<f8') for n in (33, 32769, 1048576)}
    freeze = json.loads((output / 'preparation.json').read_text())
    assert not freeze['gpu_work_executed'] and all(item['planned_trials'] == 252 for item in freeze['configs'])


def test_report_rejects_foreign_run_and_changed_execution_source(tmp_path):
    report_fixture(tmp_path, [0, 1])
    rows = [json.loads(line) for line in (tmp_path / 'observations.jsonl').read_text().splitlines()]
    rows[0]['run_id'] = 'foreign'
    (tmp_path / 'observations.jsonl').write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    result = gpu.generate(tmp_path)
    assert result['schedule_integrity']['foreign_run_terminal_indices'] == [0]
    assert result['cases'][0]['encode_ns_median'] is None
    rows[0]['run_id'] = 'id'
    (tmp_path / 'observations.jsonl').write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['execution_source_unchanged'] = False
    write_json(tmp_path / 'manifest.json', manifest)
    result = gpu.generate(tmp_path)
    assert result['schedule_integrity']['complete'] and not result['complete_success']
    assert result['cases'][0]['decode_ns_median'] is None
