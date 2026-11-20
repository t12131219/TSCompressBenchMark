"""A full-ledger CORAD projection cannot drop frozen rows or replace failures."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from verify_m3_corad import ROUTES, _select_full
from tsbench.assets import ContractError, canonical_bytes


def data(tmp_path):
    other = {'work_item_id':'other','dataset_id':'ds-0','selection':7,'route':'tv','operation':'codec',
             'applicability':'input_domain_matches'}
    items = [other]+[
        {'work_item_id':f'{route}/{ds}','dataset_id':f'ds-{ds}','selection':selection,'route':route,
         'operation':'codec','applicability':'input_domain_matches' if ds<13 else 'outside_declared_domain'}
        for ds in range(23) for selection,route in sorted(ROUTES)]
    selection,route = sorted(ROUTES)[0]
    checks = [{'obligation_id':str(i),'selection':selection,'route':route,'kind':'required','check':f'check-{i}'}
              for i in range(17)]
    plan = {'work_items':items,'obligations':checks}
    rows = [{**w,'status':('quality_rejected' if i==1 else 'verified') if w['applicability']=='input_domain_matches'
             else w['applicability']} for i,w in enumerate(items)]
    rows.append({'entry_kind':'specialized_product','selection':selection,'route':route,'status':'verified'})
    rows.extend({'entry_kind':'specialized_obligation',**o,'status':'verified'} for o in checks)
    path = tmp_path/'ledger.jsonl'
    def stage(data):
        path.write_bytes(b''.join(canonical_bytes(x)+b'\n' for x in data))
    stage(rows)
    return plan,items,checks,path,rows,stage


def test_projection_only_consumes_corpus_and_obligation_rows(tmp_path):
    plan,items,checks,path,_,_ = data(tmp_path)
    wanted,actual,obligations = _select_full(plan,path)
    assert wanted==items[1:] and len(actual)==69 and len(obligations)==len(checks)==17
    assert actual[0]['status']=='quality_rejected'
    assert sum(r['status']=='outside_declared_domain' for r in actual)==30


def test_projection_rejects_a_partial_ledger_even_if_all_corad_rows_remain(tmp_path):
    plan,_,_,path,rows,stage = data(tmp_path)
    stage(rows[1:])
    with pytest.raises(ContractError,match='out of order'):
        _select_full(plan,path)
    stage(rows[:-1])
    with pytest.raises(ContractError,match='omits frozen'):
        _select_full(plan,path)
