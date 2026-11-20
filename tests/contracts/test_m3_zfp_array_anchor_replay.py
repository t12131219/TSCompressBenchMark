"""Validate detached grouped array replay with a simulated boundary, no native worker."""
from pathlib import Path
from struct import pack
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import verify_m3_zfp_array_anchors as audit
from tsbench.application.m3_zfp import array_evidence
from tsbench.assets import ContractError, canonical_bytes


@pytest.mark.parametrize('issue, error', [(None, None), ('known-rejection', None), ('mount', 'fresh archive-only'),
                                         ('reuse', 'fresh archive-only'), ('bad-values', 'quality differs')])
def test_reopen_both_archives_and_preserve_original_domain_quality(tmp_path, monkeypatch, issue, error):
    array = audit.array
    n = 13
    values = [float(x) for x in range(n)]
    updated = values.copy()
    updated[1], updated[3:7] = values[-1], values[:4]
    raw, restored = (pack('<13d', *x) for x in (values, updated))
    before, after = bytes(64), b'\1' * 32 + bytes(32)
    initial = pack('<13d', 1, *values[1:]) if issue == 'known-rejection' else raw
    record = {**array_evidence(raw, before, after, initial, restored),
              'config': array._config(n), 'column': 0, 'row_range': [0, n], 'logical_input_bytes': len(raw),
              'input': array._stamp(raw), 'before_frame': array._stamp(before), 'after_frame': array._stamp(after),
              'restored': array._stamp(restored), 'exact_mutated_reference': array._stamp(restored)}
    case = {'units': [record], 'rows': n, 'columns': 1, 'logical_bytes': len(raw), 'native_frame_bytes': len(before)}
    raw_path = tmp_path / 'raw.zar'

    def write(path, tag, data):
        head = array.HEAD.pack(tag, 1, 1, n)
        rate = array.RATES.pack(18, 32) if tag == array.WIRE else b''
        path.write_bytes(head + rate + array.WINDOW.pack(0, 0, n) + data)
        return path

    write(raw_path, array.RAW, raw)
    archives = {role: write(tmp_path / f'{role}.zag', array.WIRE, frame)
                for role, frame in zip(array.ARCHIVE_ROLES, (before, after), strict=True)}
    recovered = {'initial': initial, 'updated': restored}
    setup = {'archives': {k: audit._ref(tmp_path, v) for k, v in archives.items()},
             'recovery': {k: {'quality': array._quality_proof(case, k), 'product': array._stamp(
                 write(tmp_path / f'{k}-expected', array.VALUES, v).read_bytes())} for k, v in recovered.items()}}

    def call(run, binding, c, place, op, source):
        role = op.removeprefix('reopen_')
        assert c == case and source == archives[role] and source != raw_path
        place.mkdir()
        result = write(place / 'values', array.VALUES, recovered[role])
        if issue == 'bad-values' and role == 'initial':
            write(result, array.VALUES, restored)
        logs = [place / name for name in ('native.stdout', 'native.stderr')]
        meta = {'column': 0, 'row_start': 0, **record['config'],
                **{k: {'process_cpu_ns': 0, 'wall_ns': 1} for k in array.PHASES[op]}}
        logs[0].write_bytes(canonical_bytes(meta) + b'\n')
        logs[1].write_bytes(b'')
        mounts = {role: array._stamp(source.read_bytes())}
        if issue == 'mount':
            mounts['raw'] = array._stamp(raw)
        return {'values': result}, {'returncode': 0, 'session_id': 'same' if issue == 'reuse' else role,
                                    'input_mounts': mounts}, logs

    monkeypatch.setattr(array, '_call', call)
    sessions = set()
    if error:
        with pytest.raises(ContractError, match=error):
            audit.reopened(tmp_path, {}, case, setup, raw_path, archives, tmp_path, sessions)
    else:
        out = audit.reopened(tmp_path, {}, case, setup, raw_path, archives, tmp_path, sessions)
        assert sessions == set(array.ARCHIVE_ROLES)
        assert out['updated']['product'] == setup['recovery']['updated']['product']
        assert out['initial']['input_mounts'] == {'initial': array._stamp(archives['initial'].read_bytes())}
        assert out['initial']['quality']['rejected_windows'] == (1 if issue == 'known-rejection' else 0)


def test_missing_anchors_are_not_reported_as_quality_pass(tmp_path):
    item = dict(dataset_id='test', work_item_id='id', canonical_object_id='input', operation_config_id='config',
                input={'size_estimate': {'input_units': 7}})
    facts = {'case_id': 'case', 'adapter': 'adapter'}
    plan = {'measurement': {'population': {'id': facts}}}
    row = {'status': 'failed', 'reason': 'bad input', 'measurement': {**facts, 'timing_admitted': False,
           'status': 'functional_dependency_not_verified', 'reason': 'failed'}}
    out = audit.replay_case(tmp_path, plan, tmp_path, item, {}, row, {}, tmp_path, set())
    assert out['replay_status'] == 'no_anchor' and out['quality_rejected_windows'] is None
    assert out['planned_windows'] == 7 and out['compared_windows'] == 0
    row['measurement'].update(status='measured_and_verified', reason=None)
    with pytest.raises(ContractError, match='missing anchors'):
        audit.replay_case(tmp_path, plan, tmp_path, item, {}, row, {}, tmp_path, set())
