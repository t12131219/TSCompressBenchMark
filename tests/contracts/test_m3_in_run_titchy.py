from collections import Counter
from copy import deepcopy
from hashlib import sha256

import pytest

from tsbench.application import m3_in_run_titchy as t
from tsbench.assets import ContractError
from tsbench.planner.m3_in_run_measurement_v8 import TITCHY, population


def test_titchy_population_does_not_add_or_relabel_batch():
    routes = (*t.grouped.ROUTES, 'batch')
    items = [dict(selection=85, route=r, work_item_id=r, applicability='input_domain_matches', operation_config_id='conf')
             for r in routes]
    base = {r:{'status':'measurement_adapter_not_integrated'} for r in routes}
    base['batch'] = {'status':'scheduled','adapter':'already_bound'}
    result = population(items, base, {(85,r) for r in t.grouped.ROUTES})
    assert result['batch'] == base['batch'] and all(result[r]['adapter'] == TITCHY for r in t.grouped.ROUTES)
    assert len({result[r]['case_id'] for r in t.grouped.ROUTES}) == 3
    for r in t.grouped.ROUTES:
        slots = list(t.timing.schedule(result[r]))
        assert slots == list(t.timing.schedule(result[r])) and len(slots) == 8
        for rnd in range(4):
            assert {x['direction'] for x in slots if x['round'] == rnd} == {'encode','decode'}


def test_access_projects_original_bits_from_manifest_not_batch_row(tmp_path, monkeypatch):
    data = bytes(8) + b'\x01\x00\x00\x00\x00\x00\xf8\x7f'
    item = {'selection':85,'route':'batch-range','dataset_id':'data','work_item_id':'w','operation_config_id':'cfg',
            'canonical_object_id':'o','input':{'row_ranges':[{'object_id':'o','partition':'full','start':0,'end':2}],
            'value_column_range':[0,1], 'representation':'u64_bitcast_per_f64_column','skipped_row_ranges':[],
            'full_extent_of_file_rows_and_value_columns':True,'slice_extent':{'max_per_unit':65536},
            'size_estimate':{'input_units':1,'native_input_bytes_one_pass':16}}}
    row = {'status':'verified','evidence':{'driver':'titchy-access-control/1','columns':1,'input_bytes':16,'artifact_bytes':12,
            'units':[{'column':0,'row_range':[0,2],'logical_input_bytes':16,'sha256':'a'*64,'artifact_bytes':12,
                      'header_bytes':4,'index_bytes':2,'dictionary_and_payload_bytes':6,
                      'encode':{'wall_ns':1,'rows':2},'access':{'range':[0,1],'wall_ns':2}}]}}
    entry = {'file':{'path':'source.csv'}, 'value_count':1, 'rows':2, 'canonical':{'object_id':'o'}}

    def stage(root, e, folder):
        assert e == entry
        folder.mkdir(); path = folder/'column'; path.write_bytes(data)
        return [path]

    monkeypatch.setattr(t.grouped,'stage_columns',stage)
    case, paths = t._case(None,item,row,entry,'b'*64,tmp_path)
    unit, = case['units']
    assert unit['original'] == {'bytes':16,'sha256':sha256(data).hexdigest()}
    assert unit['parts']['wire'] == {'bytes':12,'sha256':'a'*64}
    assert unit['native'] == {'encode':{'rows':2},'decode':{'range':[0,1]}}
    assert next(iter(paths.values())).read_bytes() == data
    work = tmp_path/'case2'; work.mkdir()
    wrong = deepcopy(row); wrong['evidence']['units'][0]['row_range'][1] = 1
    with pytest.raises(ContractError,match='consume the frozen units'):
        t._case(None,item,wrong,entry,'b'*64,work)


def test_titchy_preserves_failed_native_anchor_log(tmp_path, monkeypatch):
    run, work = tmp_path/'run', tmp_path/'work'; run.mkdir(); work.mkdir()
    cid = 'b'*64; item = {'work_item_id':'w','route':'packet-stream'}; row = {'status':'verified'}
    plan = {'measurement':{'population':{'w':{'status':'scheduled','adapter':TITCHY,'case_id':cid}},
                           'environment':{'cpu':0},'titchy_grouped':{'runtime':{}}}}
    monkeypatch.setattr(t,'_case',lambda *a: ({},{}))
    monkeypatch.setattr(t,'stage_recovery',lambda *a,**kw: None)

    def fail(*args):
        path = args[-1]; path.mkdir()
        (path/'encode.stdout').write_text('')
        (path/'encode.stderr').write_text('simulated setup problem')
        raise ContractError('simulated setup problem')

    monkeypatch.setattr(t.grouped,'invoke',fail)
    doc = t.measure(None,plan,item,{},run,row,work)
    assert doc['status'] == 'measurement_failed' and doc['summary'] is None
    assert Counter(x['status'] for x in doc['trials']) == {'not_run_after_measurement_failure':8}
    path = run/doc['failure_logs'][-1]['path']
    assert path.read_text() == 'simulated setup problem'
    assert t.recompute(None,plan,item,{},run,row,doc,set()) is None
    path.write_text('modified')
    with pytest.raises(ContractError):
        t.recompute(None,plan,item,{},run,row,doc,set())
