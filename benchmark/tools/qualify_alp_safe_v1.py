#!/usr/bin/env python3
"""Fresh Bench-binding differential against an independently built frozen release.

Validation only, never FORMAL performance. Requires the central Bench build and
an independent CMake build of adapters/alp/vendor/alp_safe_v1 (including CLI).
"""
from __future__ import annotations
import argparse
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import zlib

from tsbench.build import artifact_path
from tsbench.bridges import create_bridge

ROOT = Path(__file__).resolve().parents[2]
U8P = C.POINTER(C.c_uint8)
class Config(C.Structure):
    _fields_ = [('version',C.c_uint32),('dtype',C.c_uint32),('rank',C.c_uint32),('order',C.c_uint32),
                ('shape',C.c_uint64*8),('parameters_json',C.c_char_p),('model',C.c_char_p)]
class Result(C.Structure):
    _fields_ = [('data',U8P),('size',C.c_size_t),('capacity',C.c_size_t),('owner',C.c_void_p)]

def sha(data): return hashlib.sha256(data).hexdigest()
def buffer(raw): return (C.c_uint8*max(1,len(raw))).from_buffer_copy(raw or b'\0')
def load(path, direct=False):
    lib=C.CDLL(str(path))
    lib.alp_port_bound.argtypes=[C.c_uint64,C.c_uint8,C.c_uint8,C.POINTER(C.c_size_t)]
    lib.alp_port_encode.argtypes=[C.c_void_p,C.c_uint64,C.c_uint8,C.c_uint8,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    lib.alp_port_decode.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t),C.POINTER(C.c_size_t),C.POINTER(C.c_uint64),C.POINTER(C.c_uint8),C.POINTER(C.c_uint8)]
    if direct:
        lib.tsbench_core_create.argtypes=[C.POINTER(Config),C.c_int,C.POINTER(C.c_void_p)]
        lib.tsbench_core_destroy.argtypes=[C.c_void_p]
        for name in ['encode','decode']:
            getattr(lib,'tsbench_core_'+name).argtypes=[C.c_void_p,U8P,C.c_size_t,U8P,C.c_size_t,C.POINTER(Result)]
        lib.tsbench_core_release.argtypes=[C.POINTER(Result)]
        lib.tsbench_core_error.argtypes=[C.c_void_p];lib.tsbench_core_error.restype=C.c_char_p
    return lib

def ref_encode(lib,raw,width,method):
    bound=C.c_size_t();used=C.c_size_t();n=len(raw)//width
    assert lib.alp_port_bound(n,width,method,C.byref(bound))==0
    source=buffer(raw);output=(C.c_uint8*bound.value)()
    assert lib.alp_port_encode(source,n,width,method,output,len(output),C.byref(used))==0
    return bytes(output[:used.value])

def ref_decode(lib,frame,raw):
    source=buffer(frame);output=buffer(b'\xa5'*len(raw))
    used,consumed,count,width,method=C.c_size_t(),C.c_size_t(),C.c_uint64(),C.c_uint8(),C.c_uint8()
    assert lib.alp_port_decode(source,len(frame),output,len(raw),C.byref(used),C.byref(consumed),C.byref(count),C.byref(width),C.byref(method))==0
    assert bytes(output[:used.value])==raw and consumed.value==len(frame)

def direct(lib,raw,width,frame,decoder):
    config=Config(1,9 if width==4 else 10,1,0,(C.c_uint64*8)(len(raw)//width),b'{}',None)
    context=C.c_void_p();result=Result()
    assert lib.tsbench_core_create(C.byref(config),decoder,C.byref(context))==0
    source=buffer(frame if decoder else raw)
    size=len(raw) if decoder else len(frame)
    output=(C.c_uint8*max(1,size))()
    try:
        status=getattr(lib,'tsbench_core_decode' if decoder else 'tsbench_core_encode')(context,source,len(frame) if decoder else len(raw),output,size,C.byref(result))
        assert status==0,(status,lib.tsbench_core_error(context))
        assert not result.owner and result.size==size
        return bytes(output[:result.size])
    finally:
        lib.tsbench_core_release(C.byref(result));lib.tsbench_core_destroy(context)

def branches(frame):
    n=struct.unpack_from('<Q',frame,12)[0];width=frame[8];at=32;counts={'ALP':0,'ALP_RD':0,'RAW':0}
    assert struct.unpack_from('<I',frame,28)[0]==zlib.crc32(frame[:28]+frame[32:])
    assert struct.unpack_from('<Q',frame,20)[0]==len(frame)-32
    for start in range(0,n,102400):
        scheme,right,left,ds,group=struct.unpack_from('<BBBBI',frame,at);at+=32
        assert scheme in (1,2)
        counts['ALP_RD' if scheme==1 else 'ALP']+=(group+1023)//1024
        for _ in range(0,group,1024):
            logical,ec,bw,fac,exp,zero,base=struct.unpack_from('<HHBBBBQ',frame,at)
            at+=16+((right+left)*128+ec*4 if scheme==1 else bw*128+ec*(2+width))
    assert at==len(frame)
    return counts

def main():
    p=argparse.ArgumentParser();p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--reference-build',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    prep_path=ROOT/'adapters/alp/vendor/alp_safe_v1/tools/verify.py'
    spec=importlib.util.spec_from_file_location('frozen_alp_input_selection',prep_path)
    prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
    reference_path=args.reference_build.resolve()/'libalp_port.so';reference=load(reference_path)
    report={'schema':'tsbench.alp-binding-qualification/1','evidence_kind':'fresh Bench binding vs independently built frozen safe-v1 release; not unmodified-upstream parity',
            'reference':{'path':str(reference_path),'sha256':sha(reference_path.read_bytes())},'selection_driver_sha256':sha(prep_path.read_bytes()),
            'frozen_sources_sha256':sha((ROOT/'adapters/alp/FROZEN_SOURCES.json').read_bytes()),'libraries':{},'cases':[],'cold_process_decodes':0}
    libraries={}
    for key in ['alp','alp-rd']:
        path=artifact_path(ROOT,key);libraries[key]=load(path,True)
        report['libraries'][key]={'path':str(path),'sha256':sha(path.read_bytes())}
    for name,dtype,raw,metadata in [*prep.fixtures(),*prep.corpus(args.corpus.resolve())]:
        width=4 if dtype=='f32' else 8
        directory=args.out/name;directory.mkdir();input_path=directory/'input.raw';input_path.write_bytes(raw)
        for method,key in enumerate(['alp','alp-rd']):
            expected=ref_encode(reference,raw,width,method)
            actual=direct(libraries[key],raw,width,expected,False)
            assert actual==expected,name
            assert direct(libraries[key],raw,width,expected,True)==raw,name
            ref_decode(reference,actual,raw)
            frame_path=directory/(key+'.frame');frame_path.write_bytes(actual)
            if metadata['kind']=='synthetic':
                restored=directory/(key+'.cold-restored')
                subprocess.run([str(args.reference_build.resolve()/'alp_cli'),'decode',dtype,key,str(frame_path),str(restored),'1'],check=True,capture_output=True)
                assert restored.read_bytes()==raw;restored.unlink();report['cold_process_decodes']+=1
            # C1's one-column container must contain exactly the same complete frame.
            import numpy as np
            array=np.frombuffer(raw,dtype='<f4' if width==4 else '<f8')
            bridge=create_bridge(ROOT,key);column=bridge.encode(array)
            assert column[:4]==b'APS1' and struct.unpack_from('<Q',column,16)[0]==len(actual) and column[24:]==actual
            assert bridge.decode(column,array.dtype,array.shape).tobytes()==raw
            report['cases'].append({'case':name,'dtype':dtype,'method':key,'count':len(raw)//width,
                                    'input_sha256':sha(raw),'frame_sha256':sha(actual),'frame_bytes':len(actual),'FinalBits':8*len(actual),
                                    'c1_bytes':len(column),'c1_sha256':sha(column),'branches':branches(actual),'status':'PASS',
                                    'byte_identical':True,'bidirectional_decode':True,'c1_roundtrip':True,**metadata})
        print(name,'PASS',flush=True)
    report['case_count']=len(report['cases']);report['processed_values']=sum(x['count'] for x in report['cases']);report['status']='PASS'
    (args.out/'qualification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ['status','case_count','processed_values','cold_process_decodes']}))
if __name__=='__main__':main()
