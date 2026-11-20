from collections import Counter

import pytest

from tsbench.application import m3_in_run_corad as adapter, m3_primary_measurement_v13 as primary
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v13 import CORAD, ROUTES, population


def test_corad_final_population_preserves_quality_terminal_and_domain(monkeypatch):
    items=[{'work_item_id':route,'selection':sel,'route':route,'applicability':'input_domain_matches','operation_config_id':'test'}
           for sel,route in sorted(ROUTES)]
    domain={**items[0],'work_item_id':'excluded','applicability':'outside_declared_domain'}
    base={i['work_item_id']:{'status':'measurement_adapter_not_integrated'} for i in items}
    base['excluded']={'status':'outside_declared_domain'}
    pop=population([*items,domain],base)
    assert all(pop[i['work_item_id']]['adapter']==CORAD for i in items) and pop['excluded']==base['excluded']
    plan={'measurement':{'population':pop}}
    monkeypatch.setattr(adapter,'observe',lambda *args:args[-1]['status'])
    for i in items:
        assert primary.observe(None,plan,i,None,None,None,{'status':'quality_rejected'})=='quality_rejected'
        assert primary.observe(None,plan,i,None,None,None,{'status':'failed'})['status']=='functional_dependency_not_verified'
    with pytest.raises(ContractError,match='overlapping'):
        population(items,pop)


@pytest.mark.parametrize('route', [adapter.INFERENCE,adapter.C,adapter.SOURCE])
def test_corad_whole_decision_schedule_does_not_count_frames_as_repeats(route):
    slots=list(adapter.schedule(route,'case'))
    assert slots==list(adapter.schedule(route,'case')) and len(slots)==len({s['path'] for s in slots})
    ops=('encode','decode') if route==adapter.INFERENCE else ('train',)
    assert Counter((t['phase'],t['direction']) for t in slots)=={
        (phase,op):n for phase,n in [('warmup',1),('measured',3)] for op in ops}


def test_timed_source_bridge_executes_exact_source_and_does_not_set_seed():
    raw=b"# original source\nprint('example Source payload')\n"
    wrapped=adapter.timed_bridge(raw)
    assert repr(raw).encode() in wrapped
    assert b'DictionaryLearning.fit = _measured' in wrapped and b'random_state' not in wrapped
    compile(wrapped,'timed-bridge.py','exec')


def test_inference_summary_keeps_fractional_rates_and_counts_whole_rounds():
    item={'dataset_id':'probe','route':adapter.INFERENCE,'operation_config_id':'fixed'}
    cases=[{'producer':p,'raw':b'12345678','evaluation':{'frame_accounting':dict.fromkeys(adapter.BILL,4),
            'status':'quality_rejected'}} for p in adapter.TRAINERS for _ in range(2)]
    measured=[]
    for op,call in [('encode','corad_model_encode'),('decode','corad_decode')]:
        for elapsed in (1000,2000,3000):
            proc={'process_wall_ns':elapsed+5,'child_usage':{'user_cpu_ns':2,'system_cpu_ns':1,'maxrss_bytes':4096}}
            unit={'wall_ns':elapsed+15,'processes':{op:proc}}
            obs={op:{'calls':[{'call':call,'wall_ns':elapsed,'cpu_ns':1}]}}
            measured.append(({'direction':op,'units':[unit]*len(cases),'controller_cpu_ns':20,
                              'whole_verified_durable_wall_ns':len(cases)*(elapsed+15)},[obs]*len(cases)))
    summary=adapter._summary(item,{'status':'quality_rejected'},cases,measured)
    basis=summary['sample_basis']
    assert summary['qualified_performance_samples']==0 and summary['diagnostic_only']
    for op,call in [('encode','corad_model_encode'),('decode','corad_decode')]:
        for producer in adapter.TRAINERS:
            scope=summary['directions'][op][producer]
            rate=scope['native_mib_s']
            assert rate=={'count':3,'min':pytest.approx(16e9/(6000*(1<<20))),
                          'median':pytest.approx(16e9/(4000*(1<<20))),
                          'max':pytest.approx(16e9/(2000*(1<<20))),'sample_basis':basis}
            assert scope[f'{call}_wall_ns']['sum']==12000
            assert scope[f'{call}_wall_ns']['sample_basis']==basis
            assert scope['verified_durable_mib_s']['median']<rate['median']
    with pytest.raises(ContractError,match='throughput'):
        adapter._round_distribution('native_mib_s',[1.0,float('inf'),2.0],basis)
    with pytest.raises(ContractError,match='metric observations'):
        adapter._round_distribution('native_wall_ns',[1,1.5,2],basis)
