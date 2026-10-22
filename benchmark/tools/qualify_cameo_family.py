#!/usr/bin/env python3
"""CAMEO repaired-v1 release/Bench qualification. Correctness evidence, never performance."""
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
from tsbench.families import CAMEO_FAMILY
KEYS=tuple(CAMEO_FAMILY)
VENDOR=ROOT/'adapters/cameo_family/vendor/cameo_family'
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
    p=Registry(ROOT).resolve_params(key,overrides)
    c={k:(float(v) if Registry(ROOT).get(key).document['parameters']['properties'][k]['type']=='decimal-string' else v) for k,v in p.items() if k not in {'isa','native_timing'}}
    return {'algorithm':{'pmc-mean':'pmc','swing-connected':'swing'}.get(key,key),'values':a.tolist(),'config':c}
def call(command,requests,env=None):
    done=subprocess.run(list(map(str,command)),input=''.join(json.dumps(r,allow_nan=False)+'\n' for r in requests),text=True,capture_output=True,env=env,timeout=600)
    assert done.returncode==0,done.stderr[-5000:]
    responses=[json.loads(line) for line in done.stdout.split('\n') if line.strip()]
    assert len(responses)==len(requests),(done.stdout[-1000:],done.stderr[-1000:])
    assert all('error' not in x for x in responses),[x for x in responses if 'error' in x][:3]
    return responses
def profiles():
    for key in KEYS:yield key,{}
    for key in KEYS[:4]:yield key,{'error_bound':'.05','kappa':2}
    for key in KEYS[-2:]:yield key,{'fraction':'.25'}
    for key in ('pmc-mean','swing-connected','sim-piece'):yield key,{'error_bound':'.5'}
    for c in ({'backend':'fgc','threads':1},{'backend':'fgc','threads':3},{'backend':'fgc','threads':2,'kappa':2},{'criterion':'cr','error_bound':'3'},{'backend':'fgc','criterion':'cr','error_bound':'3'}):yield 'cameo',c
    for mode in ('bottom-up','python-bottom-up'):yield 'swab',{'mode':mode,'error_bound':'.1'}
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--cli',type=Path,required=True);ap.add_argument('--oracle',type=Path);ap.add_argument('--out',type=Path,default=ROOT/'docs/cameo_family_integration/qualification.json');args=ap.parse_args()
    data=[('sine',[3+np.sin(.49*i) for i in range(64)])]
    for path in sorted((VENDOR/'tests/data').glob('*.json')):
        for i,y in enumerate(json.loads(path.read_text())):data.append((path.stem+'-'+str(i),y))
    cases=[(ident,key,np.array(y,dtype='<f8'),p) for ident,y in data for key,p in profiles()]
    requests=[dict(request(k,a,p),operation='encode') for _,k,a,p in cases]
    refs=call([args.cli],requests)
    source=[]
    if args.oracle:
        env=dict(os.environ,CF_ORACLE_ROOT='oracle-repaired',OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='1')
        source=call(['/home/fzg/anaconda3/bin/python3.11','-S',args.oracle],[request(k,a,p) for _,k,a,p in cases],env)
    libs={k:load(k) for k in KEYS};bridges={k:create_bridge(ROOT,k) for k in KEYS};rows=[]
    for i,((ident,k,a,p),ref) in enumerate(zip(cases,refs)):
        frame=core(libs[k],a,p);assert frame==bytes(ref['frame']),(ident,k,'full-frame')
        recovered=core(libs[k],a,stream=frame);expected=np.array(ref['reconstructed'],dtype='<f8');assert recovered==expected.tobytes()
        assert bridges[k].encode(a,p)==frame
        assert bridges[k].decode(frame,a.dtype,a.shape,{}).tobytes()==recovered
        if source:np.testing.assert_allclose(expected,np.array(source[i]['reconstructed']),rtol=1e-10,atol=1e-10)
        rows.append({'dataset':ident,'codec':k,'params':p,'n':a.size,'input_sha256':hashlib.sha256(a.tobytes()).hexdigest(),'frame_sha256':hashlib.sha256(frame).hexdigest(),'frame_bytes':len(frame),'status':'PASS','fresh_repaired_source':bool(source)})
    # Independent cold CLI decodes Bench-owned streams (no encoder state/config).
    cold=call([args.cli],[{'operation':'decode','frame':r['frame']} for r in refs])
    for decoded,ref in zip(cold,refs):assert decoded['reconstructed']==ref['reconstructed']
    result={'scope':'Bench binding to repaired-v1; not original source or FORMAL performance','status':'PASS','case_count':len(rows),'value_count':sum(r['n'] for r in rows),'independent_cli':{'path':str(args.cli.resolve()),'sha256':hashlib.sha256(args.cli.read_bytes()).hexdigest()},'fresh_source_oracle':str(args.oracle),'cases':rows}
    args.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS',len(rows),result['value_count'])
if __name__=='__main__':main()
