from collections import Counter

import pytest

from tsbench.application import m3_in_run_sprintz_query as adapter, m3_primary_measurement_v11 as primary
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v11 import SPRINTZ, population


def test_sprintz_counts_native_query_only_and_keeps_all_operations():
    base = {s:{'status':'measurement_adapter_not_integrated'} for s in ('query','batch')}
    items = [{'work_item_id':i,'route':r,'selection':19,'applicability':'input_domain_matches','operation_config_id':'plan'}
             for i,r in [('query','query'),('batch','fire-batch')]]
    pop = population(items,base)
    assert pop['query']['adapter'] == SPRINTZ and pop['batch'] == base['batch']
    assert population(items[::-1],base) == pop and base['query']['status'] == 'measurement_adapter_not_integrated'
    assert primary.observe(None,{'measurement':{'population':pop}},items[0],None,None,None,
                           {'status':'hardware_pending'})['status'] == 'functional_dependency_not_verified'
    slots = list(adapter._schedule(pop['query']['case_id']))
    assert len(slots) == 12 and len({s['path'] for s in slots}) == 12
    assert Counter((s['operation'],s['phase']) for s in slots) == {
        (op,phase):n for op in ('encode','decode','query') for phase,n in [('warmup',1),('measured',3)]}


def test_query_failure_logs_can_be_verified_without_reporting_a_sample(tmp_path):
    work = tmp_path/'work'; work.mkdir()
    (work/'query.stdout').write_text('partial result')
    (work/'query.stderr').write_text('query failed')
    cid = 'case'
    refs = adapter._logs(tmp_path,cid,'trial','query',work)
    assert [r['path'].rsplit('/',1)[-1] for r in refs] == ['native.stdout','native.stderr']
    doc = {'status':'measurement_failed','reason':'query failed','trials':[{'direction':'query','status':'measurement_failed'}],
           'failure_logs':refs}
    adapter.failure.check(tmp_path,f'{adapter.FAILED}/{cid}',doc,('encode',))
    with pytest.raises(ContractError,match='unexpected M3 failure log paths'):
        adapter.failure.check(tmp_path,f'{adapter.FAILED}/{cid}',{**doc,'trials':[{'direction':'decode','status':'measurement_failed'}]},('encode',))
