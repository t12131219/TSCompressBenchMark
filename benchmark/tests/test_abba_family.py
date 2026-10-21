"""ABBA-family binding: source domains, owned results, atomic C1 and V4 paths."""
from pathlib import Path
import ctypes as C
import hashlib
import os
import importlib.util
import json
import struct
import zlib
import numpy as np
import pytest
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import byte_buffer
from tsbench.registry import CodecError,Registry,UnsupportedError,SourceDomainError
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('qualify_abba',ROOT/'benchmark/tools/qualify_abba_family.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
KEYS=q.KEYS
@pytest.fixture(scope='module')
def reference():
    p=Path(os.environ.get('ABBA_REFERENCE_CLI','/tmp/abba-family-reference/abba_family_cli'))
    assert p.is_file(),'Build independent abba-family CLI first (see integration report)'
    return p

@pytest.mark.parametrize('key,params',q.profiles())
def test_profiles_against_independent_release(reference,key,params):
    a=np.cumsum(np.random.default_rng(20261020).choice(np.array([-.5,.125,1.]),65)).astype('<f8')
    req=q.request(key,a,params);ref=q.call([reference],[dict(req,operation='encode')])[0];frame=bytes.fromhex(ref['container_hex'])
    decoded=q.call([reference],[{'operation':'decode','container_hex':frame.hex()}])[0];expected=np.array(decoded['reconstructed'],dtype='<f8');lib=q.load(key)
    if len(expected)!=len(a):
        with pytest.raises(SourceDomainError):create_bridge(ROOT,key).encode(a,params)
    else:
        assert q.core(lib,a,params)==frame
        assert q.core(lib,a,stream=frame)==expected.tobytes()
        assert create_bridge(ROOT,key).decode(frame,a.dtype,a.shape,{}).tobytes()==expected.tobytes()

@pytest.mark.parametrize('key',KEYS)
def test_owned_storage_survives_context_replacement_and_destroy(key):
    lib=q.load(key);a=np.arange(17,dtype='<f8')/8;h=q.create(lib,a);results=[]
    try:
        for x in [a,a[::-1].copy(),a]:
            r=q.Result();q.checked(lib,lib.tsbench_core_encode(h,x.tobytes(),x.nbytes,None,0,C.byref(r)),h);results.append(r)
        lib.tsbench_core_destroy(h);h=None
        frames=[C.string_at(r.data,r.size) for r in results];assert frames[0]==frames[2] and frames[0]!=frames[1]
        for frame,x in zip(frames,[a,a[::-1].copy(),a]):assert np.isfinite(np.frombuffer(q.core(lib,a,stream=frame),dtype='<f8')).all()
    finally:
        if h:lib.tsbench_core_destroy(h)
        for r in results:lib.tsbench_core_release(C.byref(r));assert not r.owner

@pytest.mark.parametrize('key',KEYS)
def test_c1_capacity_failure_does_not_commit_or_consume_state(key):
    a=np.arange(17,dtype='<f8')/8;bridge=create_bridge(ROOT,key);frame=bridge.encode(a);params=Registry(ROOT).resolve_params(key)
    data=bridge._input(a,params);src_store=C.create_string_buffer(data,len(data));src=byte_buffer(src_store,capacity=len(data),used=len(data));out_store=C.create_string_buffer(b'\xa5'*len(frame),len(frame));out=byte_buffer(out_store,capacity=len(frame)-1)
    with bridge._session(params,'encode') as h:
        assert bridge.lib.tscb_compress(h,C.byref(src),C.byref(out))==3
        assert out.used_bytes==0 and out_store.raw==b'\xa5'*len(frame)
        out.capacity_bytes=len(frame);assert bridge.lib.tscb_compress(h,C.byref(src),C.byref(out))==0
        assert out_store.raw==frame
        assert bridge.lib.tscb_compress(h,C.byref(src),C.byref(out))!=0
        tail=byte_buffer(C.create_string_buffer(1),capacity=0)
        assert bridge.lib.tscb_finalize(h,C.byref(tail))==0 and tail.used_bytes==0
        assert bridge.lib.tscb_finalize(h,C.byref(tail))!=0
        assert bridge.lib.tscb_reset(h,0)==0
        assert bridge.lib.tscb_finalize(h,C.byref(tail))!=0
    # Decode short capacity is also atomic and retryable on the same decoder.
    fs=C.create_string_buffer(frame,len(frame));src=byte_buffer(fs,capacity=len(frame),used=len(frame));ds=C.create_string_buffer(b'\xcc'*a.nbytes,a.nbytes);out=byte_buffer(ds,capacity=a.nbytes-1)
    with bridge._session(params,'decode') as h:
        assert bridge.lib.tscb_decompress(h,C.byref(src),C.byref(out))==3
        assert not out.used_bytes and ds.raw==b'\xcc'*a.nbytes
        out.capacity_bytes=a.nbytes;assert bridge.lib.tscb_decompress(h,C.byref(src),C.byref(out))==0
        assert out.used_bytes==a.nbytes

@pytest.mark.parametrize('key',KEYS)
def test_malformed_cross_algorithm_and_checksum_valid_geometry_reject_atomically(key):
    a=np.arange(17,dtype='<f8');lib=q.load(key);frame=q.core(lib,a);h=q.create(lib,a,decoder=True);r=q.Result();out=C.create_string_buffer(b'\xa5'*a.nbytes,a.nbytes)
    bads=[frame[:4],frame[:19],frame[:-1],frame+b'x']
    for at in [0,4,8,12,20,len(frame)-1]:
        b=bytearray(frame);b[at]^=1;bads.append(bytes(b))
    n=struct.unpack_from('<I',frame,8)[0];m=json.loads(frame[20:20+n]);m['sample_counts']=[16];text=json.dumps(m,separators=(',',':'),ensure_ascii=False).encode();b=frame[:8]+struct.pack('<I',len(text))+frame[12:20]+text+frame[20+n:-4];bads.append(b+struct.pack('<I',zlib.crc32(b)))
    other=next(k for k in KEYS if k!=key);bads.append(q.core(q.load(other),a))
    try:
        for b in bads:
            assert lib.tsbench_core_decode(h,b,len(b),out,a.nbytes,C.byref(r))!=0
            assert not r.size and not r.owner and out.raw==b'\xa5'*a.nbytes
    finally:lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('order',['C','F'])
def test_matrix_container_independent_columns_and_shape(reference,key,order):
    a=np.array(np.column_stack((np.arange(17)/8,np.arange(17)[::-1]/4)),dtype='<f8',order=order)
    bridge=create_bridge(ROOT,key);frame=bridge.encode(a);assert frame[:4]==b'AFM1'
    at=24;restored=[]
    for j in range(2):
        size=struct.unpack_from('<Q',frame,at)[0];at+=8;column=frame[at:at+size];at+=size
        ref=q.call([reference],[dict(q.request(key,a[:,j]),operation='encode')])[0];assert column==bytes.fromhex(ref['container_hex'])
        restored.append(np.frombuffer(q.core(q.load(key),a[:,j],stream=column),dtype='<f8'))
    assert at==len(frame)-4 and zlib.crc32(frame[:-4])==struct.unpack_from('<I',frame,at)[0]
    assert bridge.decode(frame,a.dtype,a.shape,{}).tobytes()==np.column_stack(restored).tobytes()
    with pytest.raises(CodecError):bridge.decode(frame,a.dtype,(34,))
    with pytest.raises(CodecError):bridge.decode(frame,a.dtype,(17,1))

@pytest.mark.parametrize('key',KEYS)
def test_explicit_finite_resource_and_parameter_scope(key):
    bridge=create_bridge(ROOT,key)
    for a in [np.array([0.,np.inf]),np.array([np.nan,1.]),np.zeros(1),np.zeros(1048577)]:
        with pytest.raises(UnsupportedError):bridge.encode(a)
    for p in [{'unknown':True},{'isa':'AVX2'},{'n_jobs':2},{'tolerance':'NaN'},{'max_len':0}]:
        with pytest.raises(UnsupportedError):Registry(ROOT).resolve_params(key,p)
    lib=q.load(key);a=np.arange(17,dtype='<f8');cfg=q.Config(1,10,1,0,(C.c_uint64*8)(17),b'{"unused":1}',None);h=C.c_void_p()
    assert lib.tsbench_core_create(C.byref(cfg),1,C.byref(h))==1 and not h.value
    cfg.parameters_json=b'{}';cfg.model=b'free-model';assert lib.tsbench_core_create(C.byref(cfg),1,C.byref(h))!=0 and not h.value


def test_qabba_grid_change_rejected_before_producing_frame(reference):
    a=((np.arange(17)%7)-3).astype('<f8')/8
    result=q.call([reference],[q.request('qabba',a)])[0];assert len(result['reconstructed'])!=len(a)
    lib=q.load('qabba');h=q.create(lib,a);r=q.Result()
    try:
        assert lib.tsbench_core_encode(h,a.tobytes(),a.nbytes,None,0,C.byref(r))==2
        assert not r.size and not r.owner
    finally:lib.tsbench_core_destroy(h)
    with pytest.raises(SourceDomainError,match='SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID'):create_bridge(ROOT,'qabba').encode(a)

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('boundary',['native_core','native_api'])
@pytest.mark.parametrize('lifecycle',['prepared','fresh_request'])
def test_v4_products_cold_recovery_and_physical_bits(tmp_path,key,boundary,lifecycle):
    from tsbench import native
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
    from tsbench.data import TimeSeriesObject
    native.ensure_driver(ROOT,ROOT/'build/tsbench');a=np.arange(65,dtype='<f8')/8;obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'id':key,'codec':key};task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle,'fidelity':'empirical_quality'}
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
    measurement=native.NativeMeasurement(method,task,{**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'timeout_s':60},support,ROOT,ROOT/'build/tsbench');measurement.prepare(obj)
    row,wire=measurement.measure(obj,independent=True,artifact_dir=tmp_path)
    assert row['status']=='ok' and wire==b'' and row['verification']['passed'] and row['independent_recovery']['passed']
    assert row['verification']['validated_operations']==3
    frame=Path(row['artifact_path']).read_bytes();assert frame[:4]==b'AFS1'
    assert row['codec_complete_bytes']==len(frame) and row['bits_per_value']==len(frame)*8/a.size


def test_old_assets_removed_and_release_hashes_unchanged():
    assert not (ROOT/'adapters/completed_rewrites/vendor/abba').exists()
    assert not (ROOT/'adapters/completed_rewrites/vendor/fabba').exists()
    assert not list((ROOT/'adapters/completed_rewrites/patches').glob('*abba*'))
    lock=json.loads((ROOT/'adapters/abba_family/FROZEN_SOURCES.json').read_text())
    for row in lock['files']:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256']

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('order',['C','F'])
@pytest.mark.parametrize('channelwise',[False,True])
@pytest.mark.parametrize('chunk',[None,17])
def test_object_wire_in_new_decoder_process(tmp_path,key,order,channelwise,chunk):
    import os,subprocess,sys
    from tsbench.data import TimeSeriesObject
    from tsbench.schemes import ObjectScheme,decode_once
    a=np.array(np.column_stack((np.arange(34)/8,np.arange(34)[::-1]/4)),dtype='<f8',order=order)
    obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}});method={'id':key,'codec':key,'channelwise':channelwise}
    if chunk:method['chunk_rows']=chunk
    scheme=ObjectScheme(method,ROOT,ROOT/'build/tsbench');scheme.prepare(obj);encoded=scheme.encode_once(obj);restored=decode_once(encoded,ROOT,ROOT/'build/tsbench')
    wire=tmp_path/'object.tsb';wire.write_bytes(encoded.wire);out=tmp_path/'restored'
    done=subprocess.run([sys.executable,'-m','tsbench','decode',str(wire),str(out),'--asset-root',str(ROOT),'--build-root',str(ROOT/'build/tsbench')],capture_output=True,text=True,timeout=60)
    assert done.returncode==0,done.stderr
    meta=json.loads((out/'object.json').read_text());cold=np.load(out/meta['components']['V'],allow_pickle=False)
    assert cold.dtype==a.dtype and cold.shape==a.shape and cold.flags.f_contiguous==(order=='F')
    assert cold.tobytes()==restored.components['V'].tobytes()
    assert np.isfinite(cold).all()


@pytest.mark.parametrize('name',['tolerance','alpha','sample_rate'])
def test_qabba_positive_decimal_underflow_is_explicit_unsupported(name):
    with pytest.raises(UnsupportedError,match='underflows binary64'):
        Registry(ROOT).resolve_params('qabba',{name:'1e-9999'})
