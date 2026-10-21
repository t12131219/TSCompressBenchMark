#!/usr/bin/env python3
"""ABBA release/Bench qualification. Correctness evidence, never performance."""
from pathlib import Path
import argparse
import ctypes as C
import hashlib
import json
import os
import struct
import subprocess
import sys
import numpy as np
from tsbench.build import artifact_path
from tsbench.registry import Registry
from tsbench.bridges import create_bridge
ROOT=Path(__file__).resolve().parents[2]
KEYS=('abba','fabba','qabba')
VENDOR=ROOT/'adapters/abba_family/vendor/abba_family'
class Config(C.Structure):
    _fields_=[('version',C.c_uint32),('dtype',C.c_uint32),('rank',C.c_uint32),('order',C.c_uint32),('shape',C.c_uint64*8),('parameters_json',C.c_char_p),('model',C.c_char_p)]
class Result(C.Structure):
    _fields_=[('data',C.c_void_p),('size',C.c_size_t),('capacity',C.c_size_t),('owner',C.c_void_p)]
def load(key):
    lib=C.CDLL(str(artifact_path(ROOT,key)))
    lib.tsbench_core_create.argtypes=[C.POINTER(Config),C.c_int,C.POINTER(C.c_void_p)]
    lib.tsbench_core_destroy.argtypes=[C.c_void_p]
    lib.tsbench_core_bound.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    lib.tsbench_core_validate_input.argtypes=[C.c_void_p,C.c_void_p,C.c_size_t]
    for op in ('encode','decode'):getattr(lib,'tsbench_core_'+op).argtypes=[C.c_void_p,C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(Result)]
    lib.tsbench_core_release.argtypes=[C.POINTER(Result)]
    lib.tsbench_core_error.argtypes=[C.c_void_p];lib.tsbench_core_error.restype=C.c_char_p
    return lib
def checked(lib,rc,h=None):assert rc==0,(rc,lib.tsbench_core_error(h))
def create(lib,a,params=None,decoder=False):
    h=C.c_void_p();cfg=Config(1,10,a.ndim,0,(C.c_uint64*8)(*a.shape),json.dumps(params or {}).encode(),None)
    checked(lib,lib.tsbench_core_create(C.byref(cfg),decoder,C.byref(h)));return h
def core(lib,a,params=None,stream=None):
    h=create(lib,a,params if stream is None else {},stream is not None);r=Result();data=a.tobytes() if stream is None else stream
    try:
        if stream is None:
            checked(lib,lib.tsbench_core_validate_input(h,data,len(data)),h);size=C.c_size_t();checked(lib,lib.tsbench_core_bound(h,data,len(data),C.byref(size)),h)
        checked(lib,getattr(lib,'tsbench_core_encode' if stream is None else 'tsbench_core_decode')(h,data,len(data),None,0,C.byref(r)),h)
        assert r.owner and r.size<=r.capacity
        checked(lib,lib.tsbench_core_destroy(h));h=None
        return C.string_at(r.data,r.size)
    finally:
        if h:lib.tsbench_core_destroy(h)
        lib.tsbench_core_release(C.byref(r))
def request(key,a,overrides=None):
    p=Registry(ROOT).resolve_params(key,overrides);c={'max_len':p['max_len']}
    if key=='abba':c.update(tol=[float(p['compression_tolerance']),float(p['digitization_tolerance'])],scl=float(p['scl']),min_k=p['min_k'],max_k=p['max_k'],norm=p['norm'],c_method=p['clustering'].lower(),weighted=p['weighted'],symmetric=p['symmetric'],seed=True)
    elif key=='fabba':c.update(tol=float(p['tolerance']),alpha=float(p['alpha']),scl=float(p['scl']),sorting=p['sorting'],source_backend=p['source_backend'],n_jobs=1)
    else:
        for k in ('alpha','sample_rate','scale_length'):c[k]=float(p[k])
        for k in ('digitizer','sorting','n_symbols','bits_for_len','bits_for_inc','max_iter','random_state','symbol_codec'):c[k]=p[k]
        c.update(tol=float(p['tolerance']),n_jobs=1)
    return {'algorithm':key,'values':a.tolist(),'config':c}
def call(command,requests,env=None):
    done=subprocess.run(list(map(str,command)),input=''.join(json.dumps(r,allow_nan=False)+'\n' for r in requests),text=True,capture_output=True,env=env,timeout=600)
    assert done.returncode==0,done.stderr[-5000:]
    responses=[json.loads(line) for line in done.stdout.split('\n') if line.strip()];assert len(responses)==len(requests),(done.stdout[-1000:],done.stderr[-1000:])
    assert all(x.get('ok') for x in responses),[x for x in responses if not x.get('ok')][:3]
    return [x['result'] for x in responses]
def profiles():
    profiles=[('abba',{}),('fabba',{}),('qabba',{})]
    profiles += [('abba',{'clustering':mode,'norm':norm,'scl':s,'weighted':weighted,'symmetric':sym,'max_len':7}) for mode in ['KMEANS','INCREMENTAL'] for norm in [1,2] for s in ['0','1'] for weighted,sym in [(False,True),(True,False)]]
    profiles += [('fabba',{'sorting':s,'source_backend':b,'alpha':alpha,'scl':scl,'max_len':7}) for s in ['lexi','1-norm','2-norm','norm','pca'] for b in ['python','cython'] for alpha,scl in [('0','0'),('.5','1')]]
    profiles += [('qabba',{'digitizer':d,'sorting':s,'bits_for_len':bl,'bits_for_inc':bi,'n_symbols':2,'max_len':7}) for d in ['agg','kmeans','f-kmeans'] for s in ['norm','pca'] for bl,bi in [(8,16),(32,33),(63,64)]]
    profiles += [('qabba',{'symbol_codec':c,'max_len':5}) for c in ['none','fixed','huffman','lzw','zlib','gzip','bz2','lzma','zstd']]
    return profiles

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cli',type=Path,required=True);ap.add_argument('--oracle',type=Path);ap.add_argument('--oracle-python',default='/home/fzg/anaconda3/bin/python3.11');ap.add_argument('--out',type=Path,default=ROOT/'docs/abba_family_integration/qualification.json');args=ap.parse_args()
    cases=[]
    for name in ['ECG5000','Chinatown','Coffee','shared-float64']:
        for i,row in enumerate(json.loads((VENDOR/f'tests/data/{name}.json').read_text())):
            for key in KEYS:cases.append((f'{name}-{i}',key,np.array(row,dtype='<f8'),{}))
    rng=np.random.default_rng(20261020)
    a=np.cumsum(rng.choice(np.array([-.5,.125,1.]),65)).astype('<f8')
    for i,(key,p) in enumerate(profiles()):cases.append((f'profile-{i}',key,a,p))
    # The documented old/new incremental mismatch, now evaluated against source.
    cases.append(('old-incremental-counterexample','abba',np.array([0.,1.,0.]*12),{'clustering':'INCREMENTAL'}))
    reqs=[request(k,a,p) for _,k,a,p in cases]
    reference=call([args.cli],[dict(r,operation='encode') for r in reqs])
    frames=[bytes.fromhex(r['container_hex']) for r in reference]
    decoded=call([args.cli],[{'operation':'decode','container_hex':f.hex()} for f in frames])
    source=call([args.oracle_python,args.oracle],reqs) if args.oracle else None
    records=[];libs={k:load(k) for k in KEYS};bridges={k:create_bridge(ROOT,k) for k in KEYS}
    for i,((name,key,a,p),req,frame,ref) in enumerate(zip(cases,reqs,frames,decoded)):
        before=a.tobytes();expected=np.array(ref['reconstructed'],dtype='<f8')
        if source:
            np.testing.assert_allclose(expected,np.array(source[i]['reconstructed'],dtype='<f8'),atol=1e-10,rtol=1e-10)
        if len(expected)!=len(a):
            h=create(libs[key],a,p);r=Result()
            try:
                assert libs[key].tsbench_core_encode(h,before,len(before),None,0,C.byref(r))==2
                assert not r.size and not r.owner
            finally:libs[key].tsbench_core_destroy(h)
            from tsbench.registry import SourceDomainError
            try:bridges[key].encode(a,p)
            except SourceDomainError:pass
            else:raise AssertionError('grid-changing source input was accepted')
            records.append({'case':name,'key':key,'source_request':req,'samples':len(a),'reconstructed_samples':len(expected),'status':'EXPECTED_UNSUPPORTED','reason':'SOURCE_RECONSTRUCTED_LENGTH_DIFFERS_FROM_GRID'})
            continue
        actual=core(libs[key],a,p)
        assert actual==frame,(name,key,'full frame differs')
        restored=core(libs[key],a,stream=frame);expected=np.array(ref['reconstructed'],dtype='<f8')
        assert len(expected)==len(a),(name,key,'source reconstructed grid changes')
        assert restored==expected.tobytes()
        assert bridges[key].encode(a,p)==frame
        assert bridges[key].decode(frame,a.dtype,a.shape,{}).tobytes()==restored
        if source:
            s=np.array(source[i]['reconstructed'],dtype='<f8');np.testing.assert_allclose(expected,s,atol=1e-10,rtol=1e-10)
        assert a.tobytes()==before
        records.append({'case':name,'key':key,'params':Registry(ROOT).resolve_params(key,p),'source_request':req,'input_sha256':hashlib.sha256(before).hexdigest(),'samples':len(a),'frame_bytes':len(frame),'frame_sha256':hashlib.sha256(frame).hexdigest(),'restored_sha256':hashlib.sha256(restored).hexdigest(),'ledger':{'header':20,'metadata':struct.unpack_from('<I',frame,8)[0],'payload':struct.unpack_from('<Q',frame,12)[0],'crc':4},'status':'PASS'})
    report={'status':'PASS','cases':len(records),'samples':sum(r['samples'] for r in records),'passed':sum(r['status']=='PASS' for r in records),'expected_unsupported':sum(r['status']=='EXPECTED_UNSUPPORTED' for r in records),'source_oracle':str(args.oracle) if args.oracle else None,'reference_cli':{'path':str(args.cli),'sha256':hashlib.sha256(args.cli.read_bytes()).hexdigest()},'builds':{k:json.loads(artifact_path(ROOT,k).with_name('build.json').read_text())['build_id'] for k in KEYS},'results':records}
    args.out.write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k not in ['results','builds']})
if __name__=='__main__':main()
