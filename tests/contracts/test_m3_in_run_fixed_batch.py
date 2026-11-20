from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_fixed_batch as adapter
from tsbench.application.m3_column_batch_timing import _schedule
from tsbench.application.m3_fixed_batch_corpus import ROUTES
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement import ADAPTER as PBEPLA
from tsbench.planner.m3_in_run_measurement_v2 import FIXED, population


def work(key, selection, route, applicability='input_domain_matches'):
    return {'work_item_id': key, 'selection': selection, 'route': route,
            'operation_config_id': 'frozen-cfg', 'applicability': applicability}


def test_new_population_only_adds_the_four_fixed_batch_routes():
    items = [*(work(str(n), *key) for n, key in enumerate(ROUTES)),
             work('pbepla', 87, 'pbepla-replay'), work('alp', 9, 'decode-backends'),
             work('outside', 40, 'zstd-baseline', 'outside_declared_domain')]
    result = population(items, ROUTES)
    assert len({result[str(i)]['case_id'] for i in range(4)}) == 4
    assert all(result[str(i)]['adapter'] == FIXED for i in range(4))
    assert result['pbepla']['adapter'] == PBEPLA
    assert result['alp']['status'] == 'measurement_adapter_not_integrated'
    assert result['outside'] == {'status': 'outside_declared_domain'}


def test_anchor_failure_keeps_all_frozen_slots_and_cannot_claim_a_trial(tmp_path, monkeypatch):
    item = work('work', 40, 'zstd-baseline')
    rows = population([item], ROUTES)
    plan = {'measurement': {'population': rows, 'fixed_batch': {'runtime': {}}, 'environment': {'cpu': 0}}}
    row = {**item, 'status': 'verified'}
    monkeypatch.setattr(adapter, '_case', lambda *_: {**rows['work'], 'decode_backends': ['default']})

    def fail(*_, **__):
        raise OSError('missing worker')

    monkeypatch.setattr(adapter, 'stage_recovery', fail)
    got = adapter.measure(None, plan, item, {}, tmp_path, tmp_path, row)
    assert got['status'] == 'measurement_failed' and got['anchors'] is None and got['summary'] is None
    assert len(got['trials']) == 8 and {r['status'] for r in got['trials']} == {'not_run_after_measurement_failure'}
    assert adapter.recompute(plan, item, row, {}, tmp_path, got, set()) is None
    for mutation in ('missing', 'invented'):
        bad = deepcopy(got)
        if mutation == 'missing':
            bad['trials'].pop()
        else:
            bad['trials'][0]['status'] = 'measurement_failed'
        with pytest.raises(ContractError):
            adapter.recompute(plan, item, row, {}, tmp_path, bad, set())


def test_failure_in_trial_preserves_prior_independent_observation(tmp_path, monkeypatch):
    item = work('work', 39, 'xz-baseline')
    rows = population([item], ROUTES)
    case = {**rows['work'], 'decode_backends': ['default']}
    plan = {'measurement': {'population': rows, 'fixed_batch': {'runtime': {}}, 'environment': {'cpu': 0}}}
    row = {**item, 'status': 'verified'}
    monkeypatch.setattr(adapter, '_case', lambda *_: case)
    monkeypatch.setattr(adapter, 'stage_recovery', lambda *_, **__: None)
    monkeypatch.setattr(adapter, '_create_anchors', lambda *_: ({}, {'raw': {}, 'wire': {}}))
    monkeypatch.setattr(adapter, '_read_anchors', lambda *_: ({}, {}, {}))
    monkeypatch.setattr(adapter.timing, '_validate', lambda *_, **__: None)
    first = next(_schedule(case))

    def trial(*args):
        slot = args[-3]
        if slot != first:
            raise ContractError('independent worker stopped')
        return {**slot, 'case_id': case['case_id'], 'status': 'measured_as_declared'}

    monkeypatch.setattr(adapter, '_trial', trial)
    got = adapter.measure(None, plan, item, {}, tmp_path, tmp_path, row)
    assert [r['status'] for r in got['trials']] == ['measured_as_declared', 'measurement_failed'] + [
        'not_run_after_measurement_failure'] * 6
    assert got['summary'] is None and adapter.recompute(plan, item, row, {}, tmp_path, got, set()) is None
    got['trials'][-1]['status'] = 'measured_as_declared'
    with pytest.raises(ContractError):
        adapter.recompute(plan, item, row, {}, tmp_path, got, set())
