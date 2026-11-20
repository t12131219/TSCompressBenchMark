from collections import Counter

import pytest

from tsbench.application import m3_in_run_lzbench as adapter, m3_primary_measurement_v10 as primary
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v10 import LZBENCH, ROUTES, population


def test_lzbench_population_preserves_conditional_and_selection_boundaries():
    items = [{'work_item_id':str(n),'selection':sel,'route':route,'operation_config_id':'config','applicability':domain}
             for n,(sel,route,domain) in enumerate([*( (*key,'input_domain_matches') for key in sorted(ROUTES)),
                                                   (39,'xz-workers','condition_not_triggered'),
                                                   (80,'xz-session','input_domain_matches')])]
    base = {i['work_item_id']:{'status':'measurement_adapter_not_integrated' if i['applicability']=='input_domain_matches'
                              else 'condition_not_triggered'} for i in items}
    pop = population(items,base)
    assert Counter(p['status'] for p in pop.values()) == {'scheduled':4,'condition_not_triggered':1,'measurement_adapter_not_integrated':1}
    assert pop == population(items[::-1],base) and pop['4'] == base['4'] and pop['5'] == base['5']
    with pytest.raises(ContractError,match='overlapping'):
        population(items,pop)
    out = primary.observe(None,{'measurement':{'population':pop}},items[0],None,None,None,{'status':'failed'})
    assert out == {**pop['0'],'status':'functional_dependency_not_verified','reason':'failed','trials':[],'timing_admitted':False}


@pytest.mark.parametrize('lanes',[('session',),('0','2'),('synchronous','1','2')])
def test_lzbench_matched_randomized_whole_file_schedule(lanes):
    case = {'case_id':'same-run','variants':dict.fromkeys(lanes)}
    slots = list(adapter._schedule(case))
    assert len(slots) == len({s['path'] for s in slots}) == 8*len(lanes)
    assert Counter((s['phase'],s['direction'],s['lane']) for s in slots) == {
        (phase,d,lane):n for phase,n in [('warmup',1),('measured',3)] for d in ('encode','decode') for lane in lanes}
    for i in range(0,len(slots),2*len(lanes)):
        assert [s['lane'] for s in slots[i:i+len(lanes)]] == [s['lane'] for s in slots[i+len(lanes):i+2*len(lanes)]]
    assert slots == list(adapter._schedule(case))


def test_lzbench_no_trials_after_anchor_failure_and_no_unmatched_cpu_budget(tmp_path,monkeypatch):
    case = {'case_id':'d','variants':{'session':{}},'family':'session'}
    item = {'work_item_id':'item'}; prescribed = {'case_id':'d','adapter':LZBENCH,'status':'scheduled'}
    plan = {'measurement':{'population':{'item':prescribed},'environment':{'cpu':4}}}
    monkeypatch.setattr(adapter,'_case',lambda *a:case)
    snaps = {'affinity':[4],'cpus':{'4':{}}}
    result = {**prescribed,'status':'measurement_failed','reason':'setup failed','timing_admitted':False,'anchors':None,
              'failure_logs':[],'trials':[{**s,'status':'not_run_after_measurement_failure','reason':'setup failed'}
                                          for s in adapter._schedule(case)],
              'cpu_budget':[4],'resource_before':snaps,'resource_after':snaps}
    assert adapter.recompute(None,plan,item,None,tmp_path,None,result,set()) is None
    with pytest.raises(ContractError,match='resource identity'):
        adapter.recompute(None,plan,item,None,tmp_path,None,{**result,'cpu_budget':[4,6]},set())
    with pytest.raises(ContractError,match='trial denominator'):
        adapter.recompute(None,plan,item,None,tmp_path,None,{**result,'trials':[]},set())
