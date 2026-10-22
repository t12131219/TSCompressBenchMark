"""CAMEO-family binding: source domains, owned results, atomic C1 and V4 paths."""
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
spec=importlib.util.spec_from_file_location('qualify_cameo',ROOT/'benchmark/tools/qualify_cameo_family.py');q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)
KEYS=q.KEYS
@pytest.fixture(scope='module')
def reference():
    p=Path(os.environ.get('CAMEO_REFERENCE_CLI','/tmp/cameo-family-reference/cameo_cli'))
    assert p.is_file(),'Build independent cameo-family CLI first (see integration report)'
    return p

@pytest.mark.parametrize('key,params',list(q.profiles()))
def test_profiles_against_independent_release(reference,key,params):
    a=np.cumsum(np.random.default_rng(20261020).choice(np.array([-.5,.125,1.]),64)).astype('<f8')
    req=q.request(key,a,params);ref=q.call([reference],[dict(req,operation='encode')])[0];frame=bytes(ref['frame'])
    decoded=q.call([reference],[{'operation':'decode','frame':list(frame)}])[0];expected=np.array(decoded['reconstructed'],dtype='<f8');lib=q.load(key)
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
    for offset,value in [(12,11),(28,16),(36,16),(44,0),(52,0)]:
        b=bytearray(frame);struct.pack_into('<Q',b,offset,value);struct.pack_into('<Q',b,len(b)-8,zlib.crc32(b[:-8]));bads.append(bytes(b))
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
    bridge=create_bridge(ROOT,key);frame=bridge.encode(a);assert frame[:4]==b'CFM1'
    at=24;restored=[]
    for j in range(2):
        size=struct.unpack_from('<Q',frame,at)[0];at+=8;column=frame[at:at+size];at+=size
        ref=q.call([reference],[dict(q.request(key,a[:,j]),operation='encode')])[0];assert column==bytes(ref['frame'])
        restored.append(np.frombuffer(q.core(q.load(key),a[:,j],stream=column),dtype='<f8'))
    assert at==len(frame)-4 and zlib.crc32(frame[:-4])==struct.unpack_from('<I',frame,at)[0]
    assert bridge.decode(frame,a.dtype,a.shape,{}).tobytes()==np.column_stack(restored).tobytes()
    with pytest.raises(CodecError):bridge.decode(frame,a.dtype,(34,))
    with pytest.raises(CodecError):bridge.decode(frame,a.dtype,(17,1))

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
    frame=Path(row['artifact_path']).read_bytes();assert frame[:4]==b'CF01'
    assert row['codec_complete_bytes']==len(frame) and row['bits_per_value']==len(frame)*8/a.size


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
@pytest.mark.parametrize('key',KEYS)
def test_source_limits_params_and_empty_decoder(key):
    bridge=create_bridge(ROOT,key)
    for a in [np.array([0.,np.inf]),np.array([np.nan,1.]),np.zeros(0),np.zeros(131073)]:
        with pytest.raises(UnsupportedError):bridge.encode(a)
    for p in [{'unknown':True},{'isa':'AVX2'},{'native_timing':1}]:
        with pytest.raises(UnsupportedError):Registry(ROOT).resolve_params(key,p)
    lib=q.load(key);cfg=q.Config(1,10,1,0,(C.c_uint64*8)(17),b'{"unused":1}',None);h=C.c_void_p()
    assert lib.tsbench_core_create(C.byref(cfg),1,C.byref(h))!=0 and not h.value
    cfg.parameters_json=b'{}';cfg.model=b'free-model';assert lib.tsbench_core_create(C.byref(cfg),1,C.byref(h))!=0 and not h.value
    # Original 0/1/2 object extension is explicit; nonempty short objects round-trip.
    for n in [1,2]:
        a=np.arange(n,dtype='<f8')+.125;frame=bridge.encode(a);assert bridge.decode(frame,a.dtype,a.shape).size==n

@pytest.mark.parametrize('key',KEYS[:4])
def test_acf_resource_worker_and_quality_admission(key):
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE
    from tsbench.data import TimeSeriesObject
    from tsbench.schemes import capability
    a=np.sin(np.arange(64)*.13).astype('<f8');obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'id':key,'codec':key,'params':{'threads':3}}
    task={**DEFAULT_TASK,'boundary':'object_memory','lifecycle':'independent_object','fidelity':'empirical_quality'}
    support=capability(method,obj,task,{**DEFAULT_PROFILE,'native_threads':3},ROOT)
    assert support['supported'] and support['effective_native_threads']==3
    assert not capability(method,obj,task,DEFAULT_PROFILE,ROOT)['supported']
    assert not capability(method,obj,{**task,'fidelity':'bounded_abs'},DEFAULT_PROFILE,ROOT)['supported']
    bridge=create_bridge(ROOT,key)
    for n,p in [(3,{}),(8,{}),(64,{'kappa':3}),(64,{'nlags':32}),(4096,{})]:
        with pytest.raises(UnsupportedError):bridge.encode(np.arange(n,dtype='<f8'),p)

@pytest.mark.parametrize('key',['dft','dwt-dct-ii'])
@pytest.mark.parametrize('fraction',['-1','.0','1','1.5'])
def test_transform_python_slicing_and_dct_zero_fraction(reference,key,fraction):
    a=np.sin(np.arange(17)*.3).astype('<f8');p={'fraction':fraction};frame=q.core(q.load(key),a,p)
    ref=q.call([reference],[dict(q.request(key,a,p),operation='encode')])[0];assert frame==bytes(ref['frame'])
    if key=='dwt-dct-ii' and float(fraction)==0:assert not np.frombuffer(q.core(q.load(key),a,stream=frame),dtype='<f8').any()

def test_scalar_dct_and_zero_tolerance_scope(reference):
    a=np.sin(np.arange(32)*.49).astype('<f8');p={'transform':'scalar'}
    frame=q.core(q.load('dwt-dct-ii'),a,p);ref=q.call([reference],[dict(q.request('dwt-dct-ii',a,p),operation='encode')])[0];assert frame==bytes(ref['frame'])
    with pytest.raises(UnsupportedError):create_bridge(ROOT,'sim-piece').encode(a,{'error_bound':'0'})
    with pytest.raises(UnsupportedError):create_bridge(ROOT,'swab').encode(a,{'window_fraction':'.0001'})
    with pytest.raises(UnsupportedError):create_bridge(ROOT,'cameo').encode(a,{'criterion':'cr','error_bound':'1.5'})


def test_frozen_release_members_and_active_identities():
    from tsbench.families import CAMEO_FAMILY
    lock=json.loads((ROOT/'adapters/cameo_family/FROZEN_SOURCES.json').read_text())
    for row in lock['files']:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256']
    assert len(CAMEO_FAMILY)==10
    assert Registry(ROOT).get('cameo').document['identity']['display_name'].startswith('CAMEO / SIP')
    assert Registry(ROOT).get('pmc-mr').key!='pmc-mean'
    assert Registry(ROOT).get('swing-filter').key!='swing-connected'
    for key in KEYS:assert Registry(ROOT).get(key).isa==('NATIVE_DISPATCH',)

@pytest.mark.parametrize('key',KEYS)
def test_source_overflow_rejects_without_committing(key):
    a=np.array([1e308,-1e308]*16,dtype='<f8')
    try:
        payload=create_bridge(ROOT,key).encode(a)
    except UnsupportedError:
        return
    restored=create_bridge(ROOT,key).decode(payload,a.dtype,a.shape)
    assert np.isfinite(restored).all()

@pytest.mark.parametrize('key',KEYS)
def test_production_symbol_and_runtime_isolation(key):
    import subprocess
    from tsbench.build import artifact_path
    path=artifact_path(ROOT,key)
    defined=subprocess.check_output(['nm','-D','--defined-only',str(path)],text=True)
    names=[line.split()[-1] for line in defined.splitlines() if line.split()]
    assert names and all(n.startswith(('tscb_','tsbench_core_')) for n in names)
    runtime=subprocess.check_output(['ldd',str(path)],text=True)
    assert 'libgomp' in runtime
    assert not any(x in runtime.lower() for x in ['gfortran','quadmath','libpython','libopenblas','not found'])

@pytest.mark.parametrize('key',['sim-piece','pmc-mean','swing-connected','dft','dwt-dct-ii'])
def test_released_sample_ceiling_for_linear_or_fft_paths(key):
    a=np.full(131072,.125,dtype='<f8');lib=q.load(key);frame=q.core(lib,a)
    restored=np.frombuffer(q.core(lib,a,stream=frame),dtype='<f8')
    assert restored.size==a.size and np.isfinite(restored).all()
