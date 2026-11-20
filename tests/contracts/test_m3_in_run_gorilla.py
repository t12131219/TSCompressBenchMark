from collections import Counter
from copy import deepcopy

import pytest

from tsbench.application import m3_in_run_gorilla as timing
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v4 import GORILLA, population


def item(key, route, state='input_domain_matches', selection=7):
    return {'work_item_id':key, 'route':route, 'selection':selection, 'applicability':state,
            'operation_config_id':'contract'}


def test_gorilla_freeze_does_not_change_other_or_outside_decisions():
    items = [item('a','append-resume'),item('b','tv-batch'),item('c','iterator'),
             item('d','iterator','outside_declared_domain'),item('e','not-integrated',selection=5)]
    base = {i['work_item_id']:{'status':'measurement_adapter_not_integrated'} for i in items}
    base['d']['status'] = 'outside_declared_domain'
    f = population(items,base,timing.clock.CLOCKS)
    assert {x for x,r in f.items() if r['status']=='scheduled'} == {'a','b','c'}
    assert all(f[x]['adapter']==GORILLA for x in ('a','b','c'))
    assert f['d']==base['d'] and f['e']==base['e']
    assert len({f[x]['case_id'] for x in ('a','b','c')})==3


def test_gorilla_all_matched_direction_rounds_and_frozen_seed():
    case='a'*64
    for route,d in timing.clock.CLOCKS.items():
        slots=list(timing.schedule(case,route))
        assert slots == list(timing.schedule(case,route))
        assert Counter(t['direction'] for t in slots)==dict.fromkeys(d,4)
        for i in range(4):
            assert {s['direction'] for s in slots if s['round']==i}==d.keys()
            assert {s['phase'] for s in slots if s['round']==i}==({'warmup'} if i==0 else {'measured'})
    assert [s['direction'] for s in timing.schedule(case,'append-resume')]!=list(timing.clock.CLOCKS['append-resume'])*4


def test_gorilla_anchor_failure_preserves_all_snapshot_slots(tmp_path,monkeypatch):
    i=item('a','append-resume');f=population([i],{'a':{'status':'measurement_adapter_not_integrated'}},timing.clock.CLOCKS)
    plan={'measurement':{'population':f,'gorilla':{},'environment':{'cpu':0}}}
    row={'status':'verified'}

    def fail(*args):
        raise ContractError('missing current anchor')

    monkeypatch.setattr(timing,'_case',fail)
    result=timing.measure(None,plan,i,{},tmp_path,tmp_path,row)
    assert result['status']=='measurement_failed' and result['summary'] is None and result['anchors'] is None
    assert len(result['trials'])==12 and {t['status'] for t in result['trials']}=={'not_run_after_measurement_failure'}
    for mutation in ('omit','fabricate'):
        bad=deepcopy(result)
        if mutation=='omit':
            bad['trials'].pop()
        else:
            bad['trials'][0]['status']='measurement_failed'
        with pytest.raises(ContractError):
            timing.recompute(None,plan,i,row,{},tmp_path,bad,set())
