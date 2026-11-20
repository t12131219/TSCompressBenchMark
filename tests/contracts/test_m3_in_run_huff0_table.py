from collections import Counter

import pytest

from tsbench.application import m3_in_run_huff0_table as adapter, m3_primary_measurement_v12 as primary
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v12 import HUFF0, KEY, population


def test_shared_table_plan_keeps_fec1_separate_and_counts_both_stream_profiles():
    item={'work_item_id':'table','selection':KEY[0],'route':KEY[1],'applicability':'input_domain_matches','operation_config_id':'record'}
    fec={**item,'work_item_id':'fec','route':'huff0-reference'}
    base={i:{'status':'measurement_adapter_not_integrated'} for i in ('table','fec')}
    p=population([item,fec],base)
    assert p['table']['adapter']==HUFF0 and p['fec']==base['fec']
    result=primary.observe(None,{'measurement':{'population':p}},item,None,None,None,{'status':'failed'})
    assert result['status']=='functional_dependency_not_verified' and result['trials']==[]
    slots=list(adapter._schedule(p['table']['case_id']))
    assert len(slots)==len({s['path'] for s in slots})==24
    assert Counter((s['streams'],s['phase'],s['operation']) for s in slots)=={
        (m,p,o):n for m in (1,4) for p,n in [('warmup',1),('measured',3)] for o in ('train','encode','decode')}
    assert all({slots[i]['streams'],slots[i+1]['streams']}=={1,4} for i in range(0,len(slots),2))


def test_etb1_native_training_errors_are_retained_in_table_namespace(tmp_path):
    scratch=tmp_path/'scratch';scratch.mkdir()
    (scratch/'train.stdout').write_text('')
    (scratch/'train.stderr').write_text('trainer failed')
    refs=adapter._retain(tmp_path,'case','anchor',('train','encode'),lambda op:scratch/op if op=='encode' else scratch)
    doc={'status':'measurement_failed','reason':'training failed','trials':[],'failure_logs':refs}
    root=f'{adapter.FAILED}/case'
    adapter.failure.check(tmp_path,root,doc,('train','encode'))
    (tmp_path/refs[1]['path']).write_text('tampered')
    with pytest.raises(ContractError,match='SHA-256 mismatch'):
        adapter.failure.check(tmp_path,root,doc,('train','encode'))
