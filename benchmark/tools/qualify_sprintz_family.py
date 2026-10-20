#!/usr/bin/env python3
"""Bind the frozen native port to Bench and compare against a freshly built source oracle."""
from pathlib import Path
import ctypes as C
import hashlib
import json
import random
import struct
import subprocess
import tempfile
import gzip
import numpy as np
from tsbench.build import artifact_path
from tsbench.registry import Registry

ROOT=Path(__file__).resolve().parents[2]
VENDOR=ROOT/'adapters/sprintz_family/vendor/sprintz_family'
OUT=ROOT/'docs/sprintz_integration'
KEYS=('sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman')
class Config(C.Structure):
    _fields_=[('version',C.c_uint32),('dtype',C.c_uint32),('rank',C.c_uint32),('order',C.c_uint32),('shape',C.c_uint64*8),('parameters_json',C.c_char_p),('model',C.c_char_p)]
class Result(C.Structure):
    _fields_=[('data',C.POINTER(C.c_uint8)),('size',C.c_size_t),('capacity',C.c_size_t),('owner',C.c_void_p)]
class SzConfig(C.Structure):
    _fields_=[(k,C.c_uint32) for k in ('width','predictor','huffman','path','ndims')]
def config(a,params=None):
    dtype={('u',1):2,('i',1):1,('u',2):4,('i',2):3,('f',4):9,('u',4):6}.get((a.dtype.kind,a.itemsize),0)
    return Config(1,dtype,a.ndim,0,(C.c_uint64*8)(*a.shape),json.dumps(params or {}).encode(),None)
def load(key):
    lib=C.CDLL(str(artifact_path(ROOT,key)))
    lib.tsbench_core_create.argtypes=[C.POINTER(Config),C.c_int,C.POINTER(C.c_void_p)]
    lib.tsbench_core_destroy.argtypes=[C.c_void_p]
    lib.tsbench_core_bound.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    for op in ('encode','decode'):
        getattr(lib,'tsbench_core_'+op).argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(Result)]
    lib.tsbench_core_release.argtypes=[C.POINTER(Result)]
    lib.tsbench_core_error.argtypes=[C.c_void_p];lib.tsbench_core_error.restype=C.c_char_p
    lib.sz_test_fail_allocation.argtypes=[C.c_int64]
    return lib
def checked(lib,rc,h=None):assert rc==0,(rc,lib.tsbench_core_error(h))
def create(lib,a,params=None,decoder=False):
    h=C.c_void_p();cfg=config(a,params);checked(lib,lib.tsbench_core_create(C.byref(cfg),decoder,C.byref(h)));return h
def core_encode(lib,a,params=None):
    h=create(lib,a,params);r=Result();n=C.c_size_t();data=a.tobytes()
    try:
        checked(lib,lib.tsbench_core_bound(h,data,len(data),C.byref(n)),h);out=C.create_string_buffer(n.value)
        checked(lib,lib.tsbench_core_encode(h,data,len(data),out,n.value,C.byref(r)),h)
        assert not r.owner and r.data and r.size<=n.value
        return C.string_at(r.data,r.size)
    finally:lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)
def core_decode(lib,a,stream):
    h=create(lib,a,decoder=True);r=Result();out=C.create_string_buffer(max(1,a.nbytes))
    try:
        checked(lib,lib.tsbench_core_decode(h,stream,len(stream),out,a.nbytes,C.byref(r)),h);assert not r.owner
        return C.string_at(r.data,r.size)
    finally:lib.tsbench_core_release(C.byref(r));lib.tsbench_core_destroy(h)
def reference():
    lib=C.CDLL(str(ROOT/'build/sprintz-family-integration/reference/libsprintz.so'))
    lib.sz_bound.argtypes=[C.POINTER(SzConfig),C.c_size_t,C.POINTER(C.c_size_t)]
    lib.sz_encode.argtypes=[C.POINTER(SzConfig),C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    lib.sz_decode.argtypes=[C.POINTER(SzConfig),C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    return lib
def ref_encode(lib,c,raw):
    n=C.c_size_t();assert lib.sz_bound(C.byref(c),len(raw),C.byref(n))==0;out=C.create_string_buffer(n.value);made=C.c_size_t();assert lib.sz_encode(C.byref(c),raw,len(raw),out,n.value,C.byref(made))==0;return out.raw[:made.value]
def ref_decode(lib,c,stream,n):
    out=C.create_string_buffer(max(1,n));made=C.c_size_t();rc=lib.sz_decode(C.byref(c),stream,len(stream),n,out,n,C.byref(made));return rc,out.raw[:made.value]
def wrap(c,raw,payload):return struct.pack('<4sBBBBHHIII',b'SZF1',c.width//8,c.predictor,c.huffman,c.path,c.ndims,0,len(raw),len(payload),0)+payload

def main():
    OUT.mkdir(exist_ok=True);libs={k:load(k) for k in KEYS};ref=reference();rng=random.Random(171017);rows=[]
    oracle=ROOT/'build/sprintz-family-integration/baseline/sprintz_oracle'
    with tempfile.TemporaryDirectory(prefix='bench-sprintz-') as td:
        t=Path(td)
        for bits in (8,16):
          for fire in (0,1):
           for huff in (0,1):
            key=KEYS[fire+2*huff];lib=libs[key]
            for dims in (1,2,3,4,5,8,17,32,128):
             for path in range(6):
              if (path==2 and dims>(4 if bits==8 else 2)) or (path in (3,4) and fire) or (path==5 and (bits!=8 or not fire)):continue
              for pattern in ('random','zero','ramp'):
               raw=bytes(rng.randrange(256) if pattern=='random' else 0 if pattern=='zero' else i//17%256 for i in range(1025*(bits//8)))
               c=SzConfig(bits,fire,huff,path,dims);expected=ref_encode(ref,c,raw)
               # Standalone admits incomplete rows; Bench matrices are complete.
               # For this evidence feed SZI1 flat count+ndims through C1, then
               # use a complete-prefix matrix for the direct ABI independently.
               from tsbench.bridges import create_bridge
               from tsbench.bridges.c_abi_v1 import byte_buffer
               bridge=create_bridge(ROOT,key);params=Registry(ROOT).resolve_params(key,{'path':path});input_blob=struct.pack('<4sBBHQ',b'SZI1',bits//8,0,dims,1025)+raw
               sb=C.create_string_buffer(input_blob);src=byte_buffer(sb,capacity=len(input_blob),used=len(input_blob));ob=C.create_string_buffer(400000);dst=byte_buffer(ob,capacity=len(ob));
               with bridge._session(params,'encode') as handle:
                bridge._check(bridge.lib.tscb_compress(handle,C.byref(src),C.byref(dst)),handle,'compress')
               encoded=ob.raw[:dst.used_bytes];assert encoded==wrap(c,raw,expected)
               a=np.frombuffer(raw,dtype='|u1' if bits==8 else '<u2')[:1025//dims*dims].reshape(-1,dims)
               direct=core_encode(lib,a,{'path':path});assert core_decode(lib,a,direct)==a.tobytes();assert direct[24:]==ref_encode(ref,c,a.tobytes())
               rc,decoded=ref_decode(ref,c,encoded[24:],len(raw));assert rc==0 and decoded==raw
               (t/'in').write_bytes(raw)
               def call(op,payload):
                (t/'source').write_bytes(payload)
                q=subprocess.run([str(oracle),op,*map(str,(bits,fire,huff,path,dims)),str(t/'source'),str(t/'result'),str(len(raw))],capture_output=True);assert q.returncode==0,q.stderr
                return (t/'result').read_bytes()
               original=call('enc',raw);same=original==expected;rc,recovered=ref_decode(ref,c,original,len(raw));repaired=bits==16 and not huff and not same
               if repaired:
                assert call('enc16plus',raw)==expected and rc!=0
                truncated=wrap(c,raw,original);ib=C.create_string_buffer(truncated);ibuf=byte_buffer(ib,capacity=len(truncated),used=len(truncated));obad=C.create_string_buffer(b'\xa5'*len(raw),len(raw));obuf=byte_buffer(obad,capacity=len(raw))
                with bridge._session({},'decode') as handle:
                 assert bridge.lib.tscb_decompress(handle,C.byref(ibuf),C.byref(obuf))!=0
                assert obuf.used_bytes==0 and obad.raw==b'\xa5'*len(raw)
               else:assert same and rc==0 and recovered==raw
               assert call('dec',expected)==raw
               rows.append({'key':key,'config':[bits,fire,huff,path,dims],'pattern':pattern,'input_sha256':hashlib.sha256(raw).hexdigest(),'frame_sha256':hashlib.sha256(encoded).hexdigest(),'source_byte_identical':same,'source_16b_truncation_repair':repaired,'direct_complete_rows':a.shape[0],'raw_bytes':len(raw),'status':'PASS'})
    # Frozen golden inputs, real integer counts and canonical source payloads.
    data_rows=[]
    for row in json.loads((VENDOR/'tests/data/canonical_manifest.json').read_text())+[{**json.loads((VENDOR/'tests/data/real_manifest.json').read_text()),'key':'national_illness_counts','payload_file':'tests/data/national_illness_counts.u16le','dtype':'<u2','ndims':3}]:
        raw=(VENDOR/row['payload_file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['payload_sha256'];a=np.frombuffer(raw,dtype=row['dtype']);dims=row['ndims'];a=a.reshape(-1,dims)
        for key in KEYS:
            encoded=core_encode(libs[key],a);assert core_decode(libs[key],a,encoded)==raw
            c=SzConfig(a.itemsize*8,int('fire' in key),int('huffman' in key),0,dims);assert encoded[24:]==ref_encode(ref,c,raw)
            data_rows.append({'key':key,'input':row['key'],'raw_bytes':len(raw),'frame_bytes':len(encoded),'payload_sha256':row['payload_sha256'],'status':'PASS'})
    with gzip.open(OUT/'source-cases.jsonl.gz','wt') as f:
        for r in rows:f.write(json.dumps(r,sort_keys=True)+'\n')
    summary={'status':'PASS','scope':'fresh unmodified source oracle + independent release build + Bench C1/direct binding','source_cases':len(rows),'source_byte_identical':sum(r['source_byte_identical'] for r in rows),'source_16b_truncation_repairs':sum(r['source_16b_truncation_repair'] for r in rows),'source_truncated_streams_rejected':sum(r['source_16b_truncation_repair'] for r in rows),'canonical_real_cases':len(data_rows),'data_cases':data_rows,'oracle_sha256':hashlib.sha256(oracle.read_bytes()).hexdigest(),'release':json.loads((ROOT/'adapters/sprintz_family/FROZEN_SOURCES.json').read_text())['release_sha256']}
    (OUT/'source-qualification.json').write_text(json.dumps(summary,indent=2)+'\n');print({k:v for k,v in summary.items() if k!='data_cases'})
if __name__=='__main__':main()
