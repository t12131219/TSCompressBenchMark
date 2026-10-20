"""Native Sprintz replacement: bytes, recovery configuration, resources and ABI."""
from pathlib import Path
import ctypes as C
import hashlib
import importlib.util
import json
import struct
import numpy as np
import pytest
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import byte_buffer
from tsbench.registry import CodecError, Registry, UnsupportedError

ROOT=Path(__file__).resolve().parents[2]
_spec=importlib.util.spec_from_file_location('sprintz_qualification',ROOT/'benchmark/tools/qualify_sprintz_family.py')
q=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(q)
KEYS=q.KEYS
@pytest.fixture(scope='module')
def reference():return q.reference()

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('dtype',['|u1','|i1','<u2','<i2'])
@pytest.mark.parametrize('dims',[1,2,3,4,8,17,128])
def test_complete_bytes_both_decoders_and_dtype_bits(reference,key,dtype,dims):
    a=(np.arange(33*dims,dtype=np.uint64)*181+32751).astype(dtype).reshape(33,dims)
    lib=q.load(key);raw=a.tobytes();encoded=q.core_encode(lib,a)
    c=q.SzConfig(a.itemsize*8,int('fire' in key),int('huffman' in key),0,dims)
    assert encoded==q.wrap(c,raw,q.ref_encode(reference,c,raw))
    assert q.core_decode(lib,a,encoded)==raw
    assert q.ref_decode(reference,c,encoded[24:],len(raw))==(0,raw)
    bridge=create_bridge(ROOT,key)
    assert bridge.encode(a)==encoded
    assert bridge.decode(encoded,a.dtype,a.shape).tobytes()==raw
    assert raw==a.tobytes()

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('width',[1,2])
@pytest.mark.parametrize('path',range(6))
def test_explicit_paths_and_cold_decoder_without_encoder_parameters(reference,key,width,path):
    a=(np.arange(1025)*7%251).astype('|u1' if width==1 else '<u2');fire='fire' in key
    supported=not (path in (3,4) and fire or path==5 and (width==2 or not fire))
    lib=q.load(key)
    if not supported:
        with pytest.raises((AssertionError,UnsupportedError)):q.core_encode(lib,a,{'path':path})
        return
    stream=q.core_encode(lib,a,{'path':path});c=q.SzConfig(width*8,int(fire),int('huffman' in key),path,1)
    assert stream[7]==path and stream[24:]==q.ref_encode(reference,c,a.tobytes())
    assert q.core_decode(lib,a,stream)==a.tobytes()
    bridge=create_bridge(ROOT,key)
    assert bridge.decode(stream,a.dtype,a.shape,{}).tobytes()==a.tobytes()

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('width',[1,2])
@pytest.mark.parametrize('count',[0,1,2,127,128,129,255,256,257])
def test_short_empty_and_tail(key,width,count):
    a=np.arange(count).astype('|u1' if width==1 else '<u2');lib=q.load(key)
    stream=q.core_encode(lib,a);assert q.core_decode(lib,a,stream)==a.tobytes()

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('width',[1,2])
@pytest.mark.parametrize('pattern',['zero','random'])
def test_64kib_limit_and_rejection_without_implicit_chunking(key,width,pattern):
    rng=np.random.default_rng(171017);a=(rng.integers(0,256,65536,dtype='u1') if pattern=='random' else np.zeros(65536,dtype='u1')).view('|u1' if width==1 else '<u2');lib=q.load(key)
    stream=q.core_encode(lib,a);assert q.core_decode(lib,a,stream)==a.tobytes()
    with pytest.raises(AssertionError):q.core_encode(lib,np.append(a,a[:1]))
    with pytest.raises(UnsupportedError):create_bridge(ROOT,key).encode(np.append(a,a[:1]))

@pytest.mark.parametrize('key',KEYS)
def test_capacity_retry_state_failure_and_caller_storage(key):
    a=np.arange(1025,dtype='<u2');lib=q.load(key);stream=q.core_encode(lib,a);source=a.tobytes();h=q.create(lib,a);r=q.Result()
    try:
        out=C.create_string_buffer(b'\xa5'*len(stream),len(stream))
        assert lib.tsbench_core_encode(h,source,len(source),out,len(stream)-1,C.byref(r))==3
        assert not r.size and not r.owner and out.raw==b'\xa5'*len(stream)
        q.checked(lib,lib.tsbench_core_encode(h,source,len(source),out,len(stream),C.byref(r)),h)
        assert out.raw==stream and not r.owner
        lib.tsbench_core_destroy(h);h=None
        assert C.string_at(r.data,r.size)==stream
    finally:
        if h:lib.tsbench_core_destroy(h)
        lib.tsbench_core_release(C.byref(r));lib.tsbench_core_release(C.byref(r))
    bridge=create_bridge(ROOT,key);params=Registry(ROOT).resolve_params(key);blob=bridge._input(a,params);sb=C.create_string_buffer(blob);src=byte_buffer(sb,capacity=len(blob),used=len(blob));ob=C.create_string_buffer(b'\xcc'*len(stream),len(stream));dst=byte_buffer(ob,capacity=len(stream)-1)
    with bridge._session(params,'encode') as handle:
        assert bridge.lib.tscb_compress(handle,C.byref(src),C.byref(dst))==3
        assert not dst.used_bytes and ob.raw==b'\xcc'*len(stream)
        dst.capacity_bytes=len(stream);assert bridge.lib.tscb_compress(handle,C.byref(src),C.byref(dst))==0
        assert bridge.lib.tscb_compress(handle,C.byref(src),C.byref(dst))!=0
        finish=byte_buffer(C.create_string_buffer(1),capacity=0)
        assert bridge.lib.tscb_finalize(handle,C.byref(finish))==0
        assert bridge.lib.tscb_finalize(handle,C.byref(finish))!=0
        assert bridge.lib.tscb_reset(handle,0)==0
        assert bridge.lib.tscb_finalize(handle,C.byref(finish))!=0

@pytest.mark.parametrize('key',KEYS)
def test_malformed_identity_geometry_and_reserved_are_rejected_atomically(key):
    a=np.arange(257*3,dtype='<u2').reshape(257,3);lib=q.load(key);stream=q.core_encode(lib,a);h=q.create(lib,a,decoder=True);r=q.Result();out=C.create_string_buffer(b'\xa5'*a.nbytes,a.nbytes)
    mutations=[stream[:7],stream[:23],stream[:-1],stream+b'x']
    for offset,value in [(4,4),(5,1-stream[5]),(6,1-stream[6]),(7,99),(8,129),(10,1),(12,0),(20,1)]:
        b=bytearray(stream);b[offset]=value;mutations.append(bytes(b))
    try:
        for bad in mutations:
            assert lib.tsbench_core_decode(h,bad,len(bad),out,a.nbytes,C.byref(r))!=0
            assert not r.size and not r.owner and out.raw==b'\xa5'*a.nbytes
        q.checked(lib,lib.tsbench_core_decode(h,stream,len(stream),out,a.nbytes,C.byref(r)),h)
        assert out.raw==a.tobytes()
    finally:lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)
    with pytest.raises(CodecError):create_bridge(ROOT,key).decode(stream,a.dtype,(771,))

@pytest.mark.parametrize('key',KEYS)
def test_native_allocation_failure_maps_to_error_without_output(key):
    a=np.arange(1025,dtype='<u2');lib=q.load(key);h=q.create(lib,a);r=q.Result();out=C.create_string_buffer(b'\xa5'*20000,20000)
    try:
        lib.sz_test_fail_allocation(0)
        assert lib.tsbench_core_encode(h,a.tobytes(),a.nbytes,out,len(out),C.byref(r))!=0
        assert not r.size and out.raw==b'\xa5'*len(out)
    finally:lib.sz_test_fail_allocation(-1);lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)
    assert q.core_decode(lib,a,q.core_encode(lib,a))==a.tobytes()

@pytest.mark.parametrize('key',KEYS)
def test_profile_and_parameter_whitelist(key):
    lib=q.load(key)
    for a,params in [(np.zeros(10,dtype='<f4'),{}),(np.zeros(10,dtype='<u4'),{}),(np.zeros((1,129),dtype='u1'),{}),(np.zeros((2,3),dtype='<u2'),{'path':2}),(np.zeros(17,dtype='u1'),{'unknown':1})]:
        with pytest.raises(AssertionError):q.core_encode(lib,a,params)
    with pytest.raises(UnsupportedError):Registry(ROOT).resolve_params(key,{'block_size':128})

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('boundary',['native_core','native_api'])
@pytest.mark.parametrize('lifecycle',['prepared','fresh_request'])
@pytest.mark.parametrize('dtype',['|u1','<i2'])
def test_v4_products_cold_recovery_and_accounting(tmp_path,key,boundary,lifecycle,dtype):
    from tsbench import native
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
    from tsbench.data import TimeSeriesObject
    native.ensure_driver(ROOT,ROOT/'build/tsbench');a=(np.arange(771)*17).astype(dtype).reshape(257,3);obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'id':key,'codec':key,'params':{'path':1}};task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle}
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
    m=native.NativeMeasurement(method,task,{**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'timeout_s':60},support,ROOT,ROOT/'build/tsbench');m.prepare(obj)
    row,wire=m.measure(obj,independent=True,artifact_dir=tmp_path)
    assert row['status']=='ok' and wire==b'' and row['verification']['passed'] and row['independent_recovery']['passed']
    assert row['verification']['validated_operations']==3 and all(p['verification']['passed'] for p in row['native_products'])
    frame=Path(row['artifact_path']).read_bytes();assert frame[:4]==b'SZF1' and frame[7]==1
    assert row['codec_complete_bytes']==len(frame) and row['bits_per_value']==len(frame)*8/a.size


def test_all_old_sprintz_assets_removed_and_release_unchanged():
    assert not (ROOT/'adapters/sprintz').exists()
    for key in ('sprintz-delta-u8','sprintz-fire-u8','sprintz-fire-huff0'):
        assert not (ROOT/'registry/codecs'/f'{key}.json').exists()
        with pytest.raises(UnsupportedError):Registry(ROOT).get(key)
    lock=json.loads((ROOT/'adapters/sprintz_family/FROZEN_SOURCES.json').read_text());assert not lock['consumed_core_modified']
    for row in lock['files']:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256']
