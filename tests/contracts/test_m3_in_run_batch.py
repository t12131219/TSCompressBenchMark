import pytest

from tsbench.application import m3_column_batch as column
from tsbench.application import m3_column_batch_timing as timing
from tsbench.application import m3_in_run_batch as adapter
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v2 import FIXED, population
from tsbench.planner.m3_in_run_measurement_v3 import COLUMN, extend_population


def _item(key, selection, route, applicability='input_domain_matches'):
    return {'work_item_id': key, 'selection': selection, 'route': route, 'applicability': applicability,
            'operation_config_id': 'frozen-operation'}


def test_column_population_preserves_fixed_other_and_unavailable_decisions():
    items = [_item('common', 9, 'decode-backends'), _item('auto', 9, 'auto-batch'),
             _item('batch', 85, 'batch'), _item('stream', 85, 'packet-stream'),
             _item('fixed', 40, 'zstd-baseline'), _item('outside', 9, 'auto-batch', 'outside_declared_domain')]
    previous = population(items, {(40, 'zstd-baseline')})
    next_ = extend_population(items, previous, column.ROUTES)
    assert all(next_[k]['adapter'] == COLUMN for k in ('common', 'auto', 'batch'))
    assert len({next_[k]['case_id'] for k in ('common', 'auto', 'batch')}) == 3
    assert {k: next_[k] for k in ('stream', 'fixed', 'outside')} == {k: previous[k] for k in ('stream', 'fixed', 'outside')}
    assert next_['fixed']['adapter'] == FIXED
    with pytest.raises(ContractError, match='overlapping'):
        extend_population(items, next_, column.ROUTES)


def test_common_frame_backends_keep_slots_even_when_anchor_fails(tmp_path, monkeypatch):
    item = _item('common', 9, 'decode-backends')
    frozen = extend_population([item], population([item], set()), column.ROUTES)
    backends = list(column.ROUTES[9, 'decode-backends'][1])
    case = {**frozen['common'], 'decode_backends': backends}
    plan = {'measurement': {'population': frozen, 'environment': {'cpu': 0},
                            'column_batch': {'runtime': {}, 'operations': {'decode-backends': ['encode', *backends]}}}}
    row = {'status': 'verified'}
    monkeypatch.setattr(adapter, '_case', lambda *args: case)

    def unavailable(*args, **kwargs):
        raise OSError('worker unavailable')

    monkeypatch.setattr(adapter, 'stage_recovery', unavailable)
    result = adapter.measure(None, plan, item, {}, tmp_path, tmp_path, row)
    assert result['status'] == 'measurement_failed' and result['anchors'] is None
    trials = result['trials']
    assert len(trials) == 12
    for n in range(4):
        assert {t['slot'] for t in trials if t['round'] == n} == {'encode', *backends}
    assert all(t['status'] == 'not_run_after_measurement_failure' for t in trials)
    assert result['summary'] is adapter.recompute(plan, item, row, {}, tmp_path, result, set()) is None
    trials.pop()
    with pytest.raises(ContractError, match='direction coverage'):
        adapter.recompute(plan, item, row, {}, tmp_path, result, set())


def test_common_frame_decoder_cannot_use_other_group_mounts():
    case = {'case_id': 'a' * 64, 'decode_backends': list(column.ROUTES[9, 'decode-backends'][1])}
    t = next(t for t in timing._schedule(case) if t['slot'] == 'falp-auto')
    wire = {'g00000.bin': {'bytes': 2, 'sha256': 'a' * 64}}
    raw = {'g00000.bin': {'bytes': 8, 'sha256': 'b' * 64}}
    substituted = {'g00000.bin': {'bytes': 2, 'sha256': 'c' * 64}}
    row = {**t, 'case_id': case['case_id'], 'status': 'measured_as_declared', 'product': raw,
           'process': {'operation': 'decode', 'status': 'completed', 'returncode': 0, 'reason': '',
                       'session_id': 'fresh', 'input_mounts': substituted}, 'native': {}}
    with pytest.raises(ContractError, match='trial resources or results'):
        timing._validate(case, 0, t, row, raw, wire, set())
