from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_whole as whole
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v6 import WHOLE, population


def test_whole_population_only_adds_eligible_routes_and_matched_direction_rounds():
    cases = [('a', 19, 'fire-batch', 'input_domain_matches'),
             ('b', 29, 'huff0-reference', 'input_domain_matches'),
             ('c', 4, 'selfstar-batch', 'input_domain_matches'),
             ('d', 4, 'selfstar-incremental', 'input_domain_matches'),
             ('e', 4, 'selfstar-incremental', 'condition_not_triggered'),
             ('f', 19, 'query', 'input_domain_matches')]
    items = [dict(work_item_id=k, selection=s, route=r, applicability=a, operation_config_id='locked')
             for k, s, r, a in cases]
    base = {k: {'status': 'measurement_adapter_not_integrated' if a == 'input_domain_matches' else a} for k, _, _, a in cases}
    keys = {(s, r) for _, s, r, _ in cases[:4]}
    result = population(items, base, keys)
    assert {k for k, v in result.items() if v.get('adapter') == WHOLE} == set('abcd')
    assert result['e'] == base['e'] and result['f'] == base['f']
    with pytest.raises(ContractError, match='overlapping'):
        population(items, result, keys)
    for k in 'abcd':
        schedule = list(whole.schedule(result[k]['case_id']))
        assert schedule == list(whole.schedule(result[k]['case_id'])) and len(schedule) == 8
        for i in range(4):
            assert {s['operation'] for s in schedule if s['round'] == i} == {'encode', 'decode'}
            assert {s['phase'] for s in schedule if s['round'] == i} == ({'warmup'} if not i else {'measured'})


def test_whole_anchor_failure_retains_original_worker_log(tmp_path, monkeypatch):
    run, work = tmp_path/'run', tmp_path/'work'
    run.mkdir(); work.mkdir()
    item = {'work_item_id': 'work', 'route': 'fire-batch'}
    case = 'a'*64
    plan = {'measurement': {'population': {'work': {'adapter': WHOLE, 'case_id': case}},
                            'environment': {'cpu': 0}, 'whole': {'abi': {'runtime': {}}}}}
    row = {'status': 'verified'}
    monkeypatch.setattr(whole, '_case', lambda *a: {'driver': 'abi'})
    monkeypatch.setattr(whole, 'stage_recovery', lambda *a, **kw: None)

    def fail(*args):
        native = args[-1]/'encode'
        native.mkdir(parents=True)
        (native/'encode.stdout').write_text('')
        (native/'encode.stderr').write_text('sandbox failure')
        raise ContractError('native anchor failed')

    monkeypatch.setattr(whole, '_anchor', fail)
    doc = whole.measure(None, plan, item, row, {}, run, work)
    assert doc['status'] == 'measurement_failed' and doc['summary'] is None
    assert len(doc['trials']) == 8
    assert all(t['status'] == 'not_run_after_measurement_failure' for t in doc['trials'])
    path = run/doc['failure_logs'][1]['path']
    assert path.read_text() == 'sandbox failure'
    assert whole.recompute(None, plan, item, row, {}, run, doc, set()) is None
    wrong = deepcopy(doc)
    wrong['trials'][0]['direction'] = 'wrong'
    with pytest.raises(ContractError, match='schedule differs'):
        whole.recompute(None, plan, item, row, {}, run, wrong, set())
    path.write_text('tampered')
    with pytest.raises(ContractError):
        whole.recompute(None, plan, item, row, {}, run, doc, set())
