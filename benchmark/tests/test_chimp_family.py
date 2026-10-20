"""Chimp family binding qualification, independent CLI and actual native batches."""
from __future__ import annotations
import ctypes as C
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import numpy as np
import pytest
from test_core_floats import ROOT, Result, U8P, buffer, check, configuration, context, decode, encode, library
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import byte_buffer
from tsbench.build import artifact_path
from tsbench.registry import CodecError, Registry, SourceDomainError, UnsupportedError

LOSSLESS = ('chimp','chimp32','chimp128','chimpn','chimp128-no-index','chimpn32')
FILTERS = ('pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized')
KEYS = LOSSLESS + FILTERS
MID = dict(zip(KEYS,(1,2,3,3,4,5,7,8,9,10)))

@pytest.fixture(scope='module')
def reference():
    cli=ROOT/'build/chimp-family-integration/reference/chimp_cli'
    if not cli.is_file():pytest.skip('independently built frozen CLI unavailable')
    proc=subprocess.Popen([str(cli),'server'],stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    def call(mode,method,data,count,n=128,eps=.1):
        proc.stdin.write(struct.pack('<IIIfII',mode,method,n,eps,count,len(data))+data);proc.stdin.flush()
        status,length=struct.unpack('<II',proc.stdout.read(8));out=proc.stdout.read(length)
        assert len(out)==length
        assert status==0,out.decode(errors='replace')
        return out
    yield call
    proc.stdin.close();assert proc.wait(timeout=10)==0

def sample(key,n=257):
    return np.asarray((np.arange(n)%257-128)/8,dtype=Registry(ROOT).get(key).dtypes[0])
def words(array):
    return array.view('<u4').astype('<u8').tobytes() if array.itemsize==4 else array.tobytes()
def points(array):
    result=np.empty(array.size,dtype=[('t','<i8'),('v','<f4')]);result['t']=np.arange(array.size);result['v']=array;return result.tobytes()
def frames(stream):
    at=0;out=[]
    while at<len(stream):
        assert stream[at:at+4]==b'CFP1'
        size=36+struct.unpack_from('<Q',stream,at+24)[0]
        frame=stream[at:at+size];assert zlib.crc32(frame[:-4])==struct.unpack_from('<I',frame,len(frame)-4)[0]
        out.append(frame);at+=size
    assert at==len(stream)
    return out

@pytest.mark.parametrize('key',LOSSLESS)
@pytest.mark.parametrize('count',[0,1,2,127,128,129,1023,1024,1025,2049])
def test_native_exact_bytes_and_both_cold_decoders(reference,key,count):
    a=sample(key,count);lib=library(key);stream=encode(lib,key,a,{'block_size':1048576})
    expected=reference(3,MID[key],words(a),count)
    assert stream==expected and decode(lib,a,expected)==a.tobytes()
    assert reference(4,MID[key],stream,count)==words(a)
    frames(stream)

@pytest.mark.parametrize('key',['chimpn','chimpn32'])
@pytest.mark.parametrize('history',[1,4,16,128,1024,65536])
def test_history_ring_wrap_and_explicit_configuration(reference,key,history):
    a=np.resize(sample(key,133),2051);lib=library(key)
    stream=encode(lib,key,a,{'history':history,'block_size':1048576})
    assert stream==reference(3,MID[key],words(a),len(a),history)
    assert decode(lib,a,stream)==a.tobytes()

@pytest.mark.parametrize('key',LOSSLESS)
def test_ieee_words_and_eof_transactional_rejection(key):
    a=sample(key);width=a.itemsize
    bits=([0,0x80000000,1,0x80000001,0x7f800000,0xff800000,0x7fc00042,0x7f800001,0xffc00000,0x7f7fffff]
          if width==4 else [0,0x8000000000000000,1,0x8000000000000001,0x7ff0000000000000,0xfff0000000000000,0x7ff8000000000042,0x7ff0000000000001,0xfff8000000000000,0x7fefffffffffffff])
    a=np.resize(np.array(bits,dtype='<u4' if width==4 else '<u8'),1025).view(a.dtype)
    lib=library(key);before=a.tobytes();stream=encode(lib,key,a,{'block_size':127});assert decode(lib,a,stream)==before and a.tobytes()==before
    bad=np.array([0x7fc00000 if width==4 else 0x7ff8000000000000],dtype='<u4' if width==4 else '<u8').view(a.dtype)
    h=context(lib,configuration(bad,{}));r=Result();src=buffer(bad.tobytes());dst=buffer(b'\xa5'*4096)
    try:
        assert lib.tsbench_core_encode(h,src,bad.nbytes,dst,len(dst),C.byref(r))==2
        assert not r.size and not r.owner and bytes(dst)==b'\xa5'*4096
    finally:lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)
    with pytest.raises(SourceDomainError):create_bridge(ROOT,key).encode(bad)

@pytest.mark.parametrize('key',KEYS)
def test_c1_columns_independent_complete_frames_and_shape(reference,key):
    a=np.column_stack((sample(key,259),sample(key,259)[::-1]))
    params={'epsilon':'0.125'} if key in FILTERS else {'block_size':127}
    bridge=create_bridge(ROOT,key);before=a.tobytes();stream=bridge.encode(a,{**params,'native_timing':True})
    assert stream[:4]==b'CFS1' and bridge.last_native_ns is not None
    at=16
    for col in a.T:
        size=struct.unpack_from('<Q',stream,at)[0];at+=8;column=stream[at:at+size];at+=size
        chunks=frames(column)
        for i,frame in enumerate(chunks):
            block=col if key in FILTERS else col[i*127:(i+1)*127]
            expected=reference(6 if key in FILTERS else 3,MID[key],points(block) if key in FILTERS else words(block),len(block),eps=.125 if key in FILTERS else .1)
            assert frame==expected
    assert at==len(stream)
    restored=bridge.decode(stream,a.dtype,a.shape,params)
    if key in LOSSLESS:assert restored.tobytes()==before
    else:assert np.max(np.abs(restored.astype('f8')-a.astype('f8')))<=.125
    assert a.tobytes()==before
    with pytest.raises(CodecError):bridge.decode(stream,a.dtype,(2,259),params)

@pytest.mark.parametrize('key',KEYS)
def test_owned_results_malformed_frames_and_failure_atomicity(key):
    a=sample(key);params={'epsilon':'.125'} if key in FILTERS else {}
    lib=library(key);stream=encode(lib,key,a,params);h=context(lib,configuration(a,{}),True);r=Result();out=buffer(b'\xa5'*a.nbytes)
    bad_count=bytearray(stream);struct.pack_into('<Q',bad_count,16,a.size+1)
    wrong_method=bytearray(stream);wrong_method[5]=6
    bad_grid=bytearray(stream)
    if key in FILTERS:
        struct.pack_into('<q',bad_grid,32,1);struct.pack_into('<I',bad_grid,len(bad_grid)-4,zlib.crc32(bad_grid[:-4]))
    try:
        for bad in [stream[:7],stream[:-1],stream+b'X',stream[:-1]+bytes([stream[-1]^1]),bytes(bad_count),bytes(wrong_method)]+([bytes(bad_grid)] if key in FILTERS else []):
            src=buffer(bad);assert lib.tsbench_core_decode(h,src,len(bad),out,a.nbytes,C.byref(r))!=0
            assert not r.size and not r.owner and bytes(out)==b'\xa5'*a.nbytes
        src=buffer(stream);check(lib,lib.tsbench_core_decode(h,src,len(stream),None,0,C.byref(r)),h)
        assert r.owner and r.size==a.nbytes
        lib.tsbench_core_destroy(h);h=None
        assert C.string_at(r.data,r.size)==decode(lib,a,stream)
    finally:
        if h:lib.tsbench_core_destroy(h)
        lib.tsbench_core_release(C.byref(r));lib.tsbench_core_release(C.byref(r))

@pytest.mark.parametrize('key',KEYS)
def test_c1_capacity_retry_reset_finalize_and_corruption(key):
    a=sample(key);params=Registry(ROOT).resolve_params(key,{'epsilon':'.125'} if key in FILTERS else {})
    bridge=create_bridge(ROOT,key);lib=bridge.lib;expected=bridge.encode(a,params);raw=bridge._input(a,params)
    srcbuf=C.create_string_buffer(raw,len(raw));src=byte_buffer(srcbuf,capacity=len(raw),used=len(raw));dstbuf=C.create_string_buffer(b'\xa5'*len(expected),len(expected));dst=byte_buffer(dstbuf,capacity=len(expected)-1)
    with bridge._session(params,'encode') as h:
        assert lib.tscb_compress(h,C.byref(src),C.byref(dst))==3
        assert not dst.used_bytes and dstbuf.raw==b'\xa5'*len(expected)
        dst.capacity_bytes=len(expected);bridge._check(lib.tscb_compress(h,C.byref(src),C.byref(dst)),h,'compress');assert dstbuf.raw==expected
        assert lib.tscb_compress(h,C.byref(src),C.byref(dst))!=0
        finishbuf=C.create_string_buffer(1);finish=byte_buffer(finishbuf,capacity=0)
        assert lib.tscb_finalize(h,C.byref(finish))==0 and not finish.used_bytes
        assert lib.tscb_finalize(h,C.byref(finish))!=0
        assert lib.tscb_reset(h,0)==0 and lib.tscb_finalize(h,C.byref(finish))!=0
    for bad in [expected[:-1],expected+b'X',expected[:-1]+bytes([expected[-1]^1])]:
        srcbuf=C.create_string_buffer(bad,len(bad));src=byte_buffer(srcbuf,capacity=len(bad),used=len(bad));outbuf=C.create_string_buffer(b'\xa5'*a.nbytes,a.nbytes);out=byte_buffer(outbuf,capacity=a.nbytes)
        with bridge._session(params,'decode') as h:
            assert lib.tscb_decompress(h,C.byref(src),C.byref(out))!=0
            assert not out.used_bytes and outbuf.raw==b'\xa5'*a.nbytes

@pytest.mark.parametrize('key,values,eps',[
    ('swing-filter',[.1,.2,.3,-.1,-.2,-.3],'.1'),
    ('swing-filter-disjoint-quantized',[1.],'.01')])
def test_known_source_quality_failures_are_preserved_and_strictly_rejected(reference,key,values,eps):
    a=np.asarray(values,dtype='<f4');bridge=create_bridge(ROOT,key)
    with pytest.raises(SourceDomainError,match='absolute error bound'):bridge.encode(a,{'epsilon':eps})
    lib=library(key);compatible=encode(lib,key,a,{'epsilon':eps,'quality_mode':'compatible'})
    assert compatible==reference(3,MID[key],points(a),len(a),eps=float(eps))
    restored=np.frombuffer(decode(lib,a,compatible),dtype='<f4')
    assert not np.isfinite(restored).all() or np.max(np.abs(restored.astype('f8')-a.astype('f8')))>np.float32(eps)

@pytest.mark.parametrize('key',FILTERS)
def test_nonfinite_dtype_count_and_quality_domain(key):
    bridge=create_bridge(ROOT,key)
    with pytest.raises(UnsupportedError):bridge.encode(sample(key).astype('<f8'))
    with pytest.raises(SourceDomainError):bridge.encode(np.array([1,np.inf],dtype='<f4'))
    with pytest.raises(UnsupportedError):bridge.encode(sample(key),{'epsilon':'-1'})
    with pytest.raises(UnsupportedError):bridge.encode(sample(key),{'epsilon':'1e-1000'})
    if key in FILTERS[1:]:
        with pytest.raises(UnsupportedError):bridge.encode(np.empty(0,dtype='<f4'))
    if key=='swing-filter':
        with pytest.raises(UnsupportedError):bridge.encode(np.ones(1,dtype='<f4'))

@pytest.mark.parametrize('key,params',[('chimpn',{'history':3}),('chimpn32',{'history':0}),('chimp',{'history':128}),('chimp128',{'history':64}),('chimp',{'unknown':1}),('swing-filter',{'block_size':2})])
def test_parameter_whitelist_at_python_and_native_boundary(key,params):
    with pytest.raises(UnsupportedError):Registry(ROOT).resolve_params(key,params)
    lib=library(key);h=C.c_void_p();cfg=configuration(sample(key),params)
    assert lib.tsbench_core_create(C.byref(cfg),0,C.byref(h))!=0 and not h.value


def test_alias_and_dtype_migration_are_explicit():
    a=sample('chimp128',2051)
    assert encode(library('chimp128'),'chimp128',a)==encode(library('chimpn'),'chimpn',a,{'history':128})
    for key in ('chimp','chimp128','chimpn','chimp128-no-index'):
        with pytest.raises(UnsupportedError):create_bridge(ROOT,key).encode(a.astype('<f4'))

@pytest.mark.parametrize('key',KEYS)
@pytest.mark.parametrize('boundary',['native_core','native_api'])
@pytest.mark.parametrize('lifecycle',['prepared','fresh_request'])
def test_v4_native_products_and_independent_cold_recovery(tmp_path,key,boundary,lifecycle):
    from tsbench import native
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
    from tsbench.data import TimeSeriesObject
    native.ensure_driver(ROOT,ROOT/'build/tsbench')
    a=sample(key);obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'},'masked_value_policy':'preserve_all_bits'})
    params={'epsilon':'.125'} if key in FILTERS else {}
    method={'id':key,'codec':key,'params':params};task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle}
    if key in FILTERS:task.update(fidelity='bounded_abs',error_bound=.125)
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
    execution={**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'native_batch_memory_mb':16,'timeout_s':60}
    measurement=native.NativeMeasurement(method,task,execution,support,ROOT,ROOT/'build/tsbench');measurement.prepare(obj)
    row,wire=measurement.measure(obj,independent=True,artifact_dir=tmp_path/'products')
    assert row['status']=='ok' and wire==b'' and row['verification']['passed']
    assert row['verification']['validated_operations']==3 and row['independent_recovery']['passed']
    assert len(row['native_products'])==3 and all(x['verification']['passed'] for x in row['native_products'])
    payload=Path(row['artifact_path']).read_bytes();assert payload.startswith(b'CFP1' if boundary=='native_core' else b'CFS1')
    assert row['codec_complete_bytes']==len(payload) and row['bits_per_value']==len(payload)*8/a.size
    if key in FILTERS:
        q=row['codec_quality_metadata']['parts'];assert len(q)==3 and q[0]['codec_configured_epsilon']==.125


def test_compatible_mode_is_not_admitted_as_a_bound():
    from tsbench import native
    from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE
    from tsbench.data import TimeSeriesObject
    key='swing-filter';a=sample(key);obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
    method={'id':key,'codec':key,'params':{'quality_mode':'compatible'}}
    support=native.capability(method,obj,{**DEFAULT_TASK,'fidelity':'bounded_abs','error_bound':.1},DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench')
    assert not support['supported'] and 'empirical_quality' in support['reason']
    support=native.capability({**method,'params':{}},obj,{**DEFAULT_TASK,'fidelity':'range_relative','error_bound':.1},DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench')
    assert not support['supported'] and 'absolute or empirical' in support['reason']


def test_frozen_release_and_legacy_removal():
    lock=json.loads((ROOT/'adapters/chimp_family/FROZEN_SOURCES.json').read_text());assert not lock['consumed_core_modified']
    for row in lock['files']:assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256']
    assert not (ROOT/'adapters/rewrite_lossless/vendor/chimp').exists()
    old=json.loads((ROOT/'adapters/rewrite_lossless/FROZEN_APIS.json').read_text())
    assert 'chimp' not in old['algorithms'] and 'chimp128' not in old['algorithms']


def test_default_filter_quality_metadata_and_core_column_admission(tmp_path):
    from tsbench import native
    from tsbench.config import DEFAULT_TASK, DEFAULT_PROFILE, DEFAULT_EXECUTION
    from tsbench.data import TimeSeriesObject
    key='swing-filter';method={'id':key,'codec':key,'params':{}}
    task={**DEFAULT_TASK,'fidelity':'bounded_abs','error_bound':.125}
    matrix=TimeSeriesObject({'V':np.zeros((17,2),dtype='<f4')},{'roles':{'V':'V'}})
    support=native.capability(method,matrix,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench')
    assert not support['supported'] and 'one column' in support['reason']
    obj=TimeSeriesObject({'V':np.zeros(17,dtype='<f4')},{'roles':{'V':'V'}})
    support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported']
    measurement=native.NativeMeasurement(method,task,{**DEFAULT_EXECUTION,'native_loops':1,'native_warmup_loops':0},support,ROOT,ROOT/'build/tsbench')
    measurement.prepare(obj);row,_=measurement.measure(obj,independent=True,artifact_dir=tmp_path)
    q=row['codec_quality_metadata']['parts'][0]
    assert q['codec_configured_epsilon']==float(np.float32(.1)) and q['encoder_quality_mode']=='strict_abs'
