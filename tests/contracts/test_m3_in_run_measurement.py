from copy import deepcopy

import pytest

from tsbench.application.m3_in_run_measurement import recompute, unavailable
from tsbench.application.m3_pbepla_grouped_timing import schedule
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement import ADAPTER, build_population


def work(n,selection=87,route='pbepla-replay',domain='input_domain_matches'):
    return {'work_item_id':f'w{n}','selection':selection,'route':route,'applicability':domain,
            'canonical_object_id':'obj','operation_config_id':'operation','input':{'pbepla_contract':{}}}


def test_all_work_including_unimplemented_has_explicit_timing_disposition():
    items=[work(1),work(2,selection=40,route='zstd-baseline'),work(3,domain='outside_declared_domain')]
    pop=build_population(items)
    assert pop['w1']['adapter']==ADAPTER and pop['w1']['status']=='scheduled'
    assert pop['w2']=={'status':'measurement_adapter_not_integrated'}
    assert pop['w3']=={'status':'outside_declared_domain'}
    assert pop==build_population(reversed(items))
    row={'work_item_id':'w1','status':'quality_rejected'}
    doc=unavailable(pop['w1'],row['status'])
    assert recompute(items[0],row,{'population':pop},doc,set()) is None
    with pytest.raises(ContractError):
        recompute(items[0],row,{'population':pop},{**doc,'status':'measured_and_verified'},set())


def test_failed_same_run_anchor_cannot_synthesize_or_omit_a_direction():
    i=work(1); pop=build_population([i]); b=pop['w1']
    row={**i,'status':'verified','reason':'','dataset_id':'source','evidence':{'units':[]}}
    reason='anchor unavailable'
    trials=[{**t,'case_id':b['case_id'],'reason':reason,'status':'not_run_after_measurement_failure'} for t in schedule(b)]
    assert len(trials)==16 and len({t['operation'] for t in trials})==4
    doc={**b,'status':'measurement_failed','reason':reason,'timing_admitted':False,'trials':trials}
    clock={'population':pop,'environment':{'cpu':0}}
    assert recompute(i,row,clock,doc,set()) is None
    bad=deepcopy(doc); bad['trials'][0]['operation']='wrong'
    with pytest.raises(ContractError,match='slot differs'):
        recompute(i,row,clock,bad,set())
