from io import BytesIO

import pytest

from tsbench.application import m3_pbepla_grouped_timing as group
from tsbench.assets import ContractError
from tsbench.planner.m3_pbepla import REPLAY


def valid():
    return {'status':'verified','logical_input_bytes':8,'input_sha256':'original','layers':[
        {'bytes':32+k,'frame_sha256':str(k),'restored_sha256':str(k)*2} for k in group.LAYERS]}


def failed():
    return {'status':'failed','logical_input_bytes':8,'input_sha256':'failed','reason':'frozen native resolution limit'}


def test_failed_windows_stay_in_encode_but_cannot_inject_decode():
    case = {'units':[valid(),failed(),valid()]}
    assert [ix for ix,_ in next(group.groups(case))] == [0,1,2]
    dec = next(group.groups(case,layer=2))
    assert list(group._names(dec,2,inputs=True)) == [('0-2',0,{'bytes':34,'sha256':'2'}),('1-2',2,{'bytes':34,'sha256':'2'})]
    assert [ix for ix,_ in group._parts(case,2)] == [0,2]


def test_pack_replay_requires_ordinals_exact_bytes_and_closed_population(tmp_path):
    p = tmp_path/'layer.bin'
    packed = BytesIO()
    group._append(packed,4,b'ABC')
    data = packed.getvalue()
    p.write_bytes(data)
    want = [(4,group.br(b'ABC'))]
    assert list(group._read_pack(p,want)) == [b'ABC']
    p.write_bytes(data+b'\x00')
    with pytest.raises(ContractError,match='trailing'):
        list(group._read_pack(p,want))
    p.write_bytes(data)
    with pytest.raises(ContractError,match='ordinal'):
        list(group._read_pack(p,[(3,want[0][1])]))


def test_absent_prefix_slots_stay_unmeasured():
    c = {'units':[failed()],'case_id':'ff'*32,'route':REPLAY}
    t = {'operation':'restore-L1','round':1,'phase':'measured'}
    row = {**t,'case_id':c['case_id'],'status':'not_run_no_valid_prefix','groups':[],
           'durable_wall_ns':None,'fsync_wall_ns':None}
    assert group._validate_trial(c,2,t,row,set()) is None
    with pytest.raises(ContractError,match='cannot create measured latency'):
        group._validate_trial(c,2,t,{**row,'durable_wall_ns':0},set())


def test_replay_batch_validation_separate_from_native_replay_clock():
    case = {'route':REPLAY}
    unit = valid() | {'replay':{'native_passes':3}}
    units = [(0,unit)]
    parts = [('replay_encode',0,10),('batch_encode',0,8),*(('prefix_materialize',k,2) for k in group.LAYERS)]
    row = {'indices':[0],'cpu_endpoints':[2,2], 'process':{
        'status':'completed','returncode':0,'reason':'','operation':'replay','pid':5,'session_id':'fresh',
        'process_wall_ns':30,'child_usage':{'maxrss_bytes':1},'input_mounts':{n:v for n,_,v in group._names(units,inputs=True)}},
        'observations':[{'result':{'index':0,'status':'encoded','rows':1,'native_full_bytes':35,
                                   'replay':{'native_passes':3,'first_sink_ns':5}},
                         'clock':{'index':0,'native_calls':[{'part':k,'layer':i,'wall_ns':n,'result':0} for k,i,n in parts]}}],
        'outputs':{n:v for n,_,v in group._names(units)}}
    counts,sink = group._record(case,units,None,row,2,set())
    assert counts == {'replay_encode':10,'batch_validation_control':8,**{f'prefix_materialize_L{k}':2 for k in group.LAYERS}}
    assert sink == [5]
