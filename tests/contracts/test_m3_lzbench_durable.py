"""An explicit text ingress/ownership boundary, not a sum of unrelated timing runs."""
from copy import deepcopy

import pytest

from tsbench.application import m3_lzbench_durable as durable
from tsbench.assets import ContractError, digest
from tests.contracts.test_m3_lzbench_corpus_clock import fixture


def test_encode_scope_requires_actual_ingress_validation_and_sync():
    case, trial, clock, process, path, output = fixture()
    original = {'file': {'bytes': 1501, 'sha256': 'a' * 64, 'path': 'one.csv'}}
    row = {**trial, 'clock': clock, 'process': process, 'controller_cpu_ns': 1200,
           'source_original': original['file'], 'output': output, 'logs': [], 'wall_ns': {
               'ingress_stage_wall_ns': 600, 'ingress_validation_wall_ns': 100,
               'staged_to_synced_wall_ns': path['source_to_synced_output_wall_ns'],
               'output_fsync_wall_ns': path['output_fsync_wall_ns'],
               'output_validation_wall_ns': 150, 'verified_durable_wall_ns': 2260,
           }}
    durable._validate(case, trial, row, original, set())
    broken = deepcopy(row)
    broken['wall_ns']['ingress_stage_wall_ns'] = None
    with pytest.raises(ContractError, match='wall time misses ingress'):
        durable._validate(case, trial, broken, original, set())
    broken = deepcopy(row)
    broken['wall_ns']['verified_durable_wall_ns'] = 2100
    with pytest.raises(ContractError, match='wall time misses ingress'):
        durable._validate(case, trial, broken, original, set())


def test_detached_decode_requires_shared_xz_frame_without_original():
    case, trial, clock, process, path, output = fixture('1', 'decode')
    original = {'file': {'bytes': 1501, 'sha256': 'a' * 64, 'path': 'one.csv'}}
    row = {**trial, 'clock': clock, 'process': process, 'controller_cpu_ns': 50,
           'source_original': None, 'output': output, 'logs': [], 'wall_ns': {
               'ingress_stage_wall_ns': None, 'ingress_validation_wall_ns': None,
               'staged_to_synced_wall_ns': path['source_to_synced_output_wall_ns'],
               'output_fsync_wall_ns': path['output_fsync_wall_ns'],
               'output_validation_wall_ns': 150, 'verified_durable_wall_ns': 1510,
           }}
    durable._validate(case, trial, row, original, set())
    with pytest.raises(ContractError, match='decode read the original'):
        durable._validate(case, trial, {**row, 'source_original': original['file']}, original, set())
    with pytest.raises(ContractError, match='fixed input mount'):
        mount = {'object': case['variants']['1']['frame']}
        durable._validate(case, trial, {**row, 'process': {**process, 'input_mounts': mount}}, original, set())


def test_encode_reopens_text_and_bills_only_v_without_substituting_reference(tmp_path, monkeypatch):
    from tsbench.corpus_ingress import PARTITIONS, axis_contract, fingerprint

    source = tmp_path / 'source.csv'
    source.write_bytes(b'date,a,b\n2020-01-01 00:00:00,1,-0.0\n2020-01-01 00:00:01,2,3\n2020-01-01 00:00:02,3,4\n')
    entry = {'id': 'probe', 'source_cluster': 'probe', 'columns': ['date', 'a', 'b'], 'value_count': 2, 'rows': 3,
             'axis': axis_contract('civil_iso_seconds'), 'values_dtype': '<f8',
             'file': {'path': source.name, 'sha256': digest(source), 'bytes': source.stat().st_size},
             'parser': {'format': 'utf8_delimited_physical_rows_v1', 'separator': ',', 'decimal': '.',
                        'timestamp': 'civil_iso_seconds', 'missing': 'reject_empty_preserve_finite'},
             'partitions': [{'name': n, 'start': i, 'end': i + 1} for i, n in enumerate(PARTITIONS)]}
    entry.update(fingerprint(tmp_path, entry))
    run = tmp_path / 'run'
    run.mkdir()
    anchor = run / 'fixed.frame'
    anchor.write_bytes(b'known fixed codec frame')
    case = {'source': {'bytes': 48, 'sha256': entry['canonical']['values_sha256']},
            'variants': {'session': {'frame': durable.artifact(anchor), 'decode_anchor': 'session'}}}
    called = []

    def call(run, plan, case, place, staged, op, lane):
        assert op == 'encode' and lane == 'session'
        assert durable.artifact(staged) == case['source']
        assert staged != source and staged != anchor
        p = place / 'frame.bin'
        p.write_bytes(anchor.read_bytes())
        called.append(staged)
        return p, {}, {}, {'source_to_synced_output_wall_ns': 1, 'output_fsync_wall_ns': 1}, []

    monkeypatch.setattr(durable, '_call', call)
    monkeypatch.setattr(durable, '_validate', lambda *a: None)
    item = {'direction': 'encode', 'lane': 'session', 'path': 'first'}
    result, _ = durable._trial(tmp_path, run, {}, case, item, entry, {'session': anchor}, set())
    assert result['source_original'] == entry['file']
    assert result['wall_ns']['ingress_stage_wall_ns'] > 0 and len(called) == 1
    source.write_bytes(source.read_bytes().replace(b',1,-0.0', b',9,-0.0'))
    with pytest.raises(ContractError, match='differ|digest|hash'):
        durable._trial(tmp_path, run, {}, case, {**item, 'path': 'second'}, entry, {'session': anchor}, set())
    assert len(called) == 1
