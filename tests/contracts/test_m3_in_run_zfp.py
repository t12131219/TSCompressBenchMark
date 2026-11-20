from collections import Counter
from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_zfp as zfp, m3_primary_measurement_v7 as dispatch
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v7 import ZFP, population


def test_zfp_population_and_rounds_distinguish_field_profiles_and_array_ops():
    routes = ['field-baseline', 'field-modes', 'openmp-encode', 'fixed-rate-array']
    items = [dict(selection=31, work_item_id=r, operation_config_id='config', route=r, applicability='input_domain_matches')
             for r in routes]
    items.append({**items[-1], 'work_item_id': 'outside', 'applicability': 'outside_declared_domain'})
    base = dict.fromkeys(routes, {'status': 'measurement_adapter_not_integrated'}) | {'outside': {'status': 'outside_declared_domain'}}
    result = population(items, base, routes)
    assert all(result[r]['adapter'] == ZFP for r in routes) and result['outside'] == base['outside']
    for route, operations in zip(routes, (2,2,6,3), strict=True):
        cid = result[route]['case_id']; slots = list(zfp.schedule(cid, route))
        assert slots == list(zfp.schedule(cid, route)) and len(slots) == len({s['path'] for s in slots}) == operations*4
        for n in range(4):
            assert sum(s['repeat'] == n for s in slots) == operations
            assert {s['phase'] for s in slots if s['repeat'] == n} == ({'warmup'} if not n else {'measure'})


def test_array_quality_rejected_is_measured_as_diagnostic_only(monkeypatch):
    item = {'work_item_id': 'w', 'route': 'fixed-rate-array'}
    plan = {'measurement': {'population': {'w': {'status': 'scheduled', 'adapter': ZFP}}}}
    monkeypatch.setattr(zfp, 'observe', lambda *a: a[-1]['status'])
    assert dispatch.observe(None, plan, item, {}, {}, None, {'status': 'quality_rejected'}) == 'quality_rejected'
    assert dispatch.observe(None, plan, item, {}, {}, None, {'status': 'failed'})['status'] == 'functional_dependency_not_verified'


def test_zfp_failed_anchor_keeps_nested_stderr_and_all_operation_slots(tmp_path, monkeypatch):
    run, work = tmp_path/'run', tmp_path/'work'; run.mkdir(); work.mkdir()
    cid = 'b'*64; item = {'work_item_id': 'w', 'route': 'fixed-rate-array'}; row = {'status': 'quality_rejected'}
    plan = {'measurement': {'population': {'w': {'status': 'scheduled', 'adapter': ZFP, 'case_id': cid}},
                            'environment': {'cpu': 0}, 'zfp': {'array': {'runtime': {}}}}}
    monkeypatch.setattr(zfp, '_case', lambda *a: {})
    monkeypatch.setattr(zfp, 'stage_recovery', lambda *a, **kw: None)

    def failed(*args):
        out = args[-1]/'reopen-initial'; out.mkdir()
        (out/'native.stderr').write_text('test setup failure')
        raise ContractError(f'see {out}/native.stderr')

    monkeypatch.setattr(zfp.array, '_prepare', failed)
    doc = zfp.measure(None, plan, item, {}, run, row, work)
    assert doc['status'] == 'measurement_failed' and doc['summary'] is None
    assert Counter(x['status'] for x in doc['trials']) == {'not_run_after_measurement_failure': 12}
    ref, = doc['failure_logs']; retained = run/ref['path']
    assert retained.read_text() == 'test setup failure' and str(work) not in doc['reason']
    assert zfp.recompute(None, plan, item, {}, run, row, doc, set()) is None
    changed = deepcopy(doc); changed['trials'].pop()
    with pytest.raises(ContractError, match='denominator'):
        zfp.recompute(None, plan, item, {}, run, row, changed, set())
    retained.write_text('changed')
    with pytest.raises(ContractError):
        zfp.recompute(None, plan, item, {}, run, row, doc, set())
