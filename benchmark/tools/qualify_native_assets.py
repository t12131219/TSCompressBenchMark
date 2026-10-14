"""Reproducible native admission grid; this is correctness, never performance.

Each codec gets a fresh process. Successful cases prove only the recorded input,
configuration, binary and bridge; source-domain rejections remain separate rows.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from tsbench.bridges import create_bridge
from tsbench.build import artifact_path, build_codec
from tsbench.registry import Registry, SourceDomainError
from tsbench.runtime import loaded_runtime, preload_identity

ROOT = Path(__file__).resolve().parents[2]


def file_identity(path):
    return {'path':str(path.resolve(strict=True)),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def bridge_identity(root,bridge):
    paths=[root/'benchmark/src/tsbench/registry.py',
           root/'benchmark/src/tsbench/runtime.py',
           root/'benchmark/src/tsbench/errors.py',
           *sorted((root/'benchmark/src/tsbench/bridges').rglob('*.py'))]
    files={str(path.relative_to(root)):file_identity(path)['sha256'] for path in paths}
    canonical=json.dumps(files,sort_keys=True,separators=(',',':')).encode()
    return {'class':type(bridge).__module__+'.'+type(bridge).__qualname__,
            'files':files,'sha256':hashlib.sha256(canonical).hexdigest()}


def process_environment():
    return {'python':sys.version,'executable':sys.executable,
            'numpy':np.__version__,'platform':platform.platform(),
            'machine':platform.machine(),'LD_PRELOAD':os.environ.get('LD_PRELOAD',''),
            'pid':os.getpid(),'parent_pid':os.getppid()}


def values(spec,dtype,n):
    dtype = np.dtype(dtype)
    if spec.key in {'deepzip','dzip'}:
        return (np.arange(n)%4).astype(dtype)
    if spec.key in {'abba','fabba'}:
        return (np.sin(np.arange(n)/8)+np.arange(n)/10).astype(dtype)
    if dtype.kind == 'f':
        return ((np.arange(n)%17)/8).astype(dtype)
    if dtype.kind == 'i':
        return (np.arange(n)%33-16).astype(dtype)
    return (np.arange(n)%33).astype(dtype)


def codec_grid(root,key,build_root=None):
    root=Path(root).resolve()
    base=Path(build_root) if build_root is not None else Path('build/tsbench')
    base=(base if base.is_absolute() else root/base).resolve()
    reg=Registry(root);spec=reg.get(key)
    build_codec(root,key,build_root=base);bridge=create_bridge(root,key,build_root=base)
    records=[]
    artifact=artifact_path(root,key,build_root=base)
    build_path=artifact.parent/'build.json'
    build=json.loads(build_path.read_text())
    identity={'build_root':str(base),'build_id':build['build_id'],'artifact_sha256':build['artifact_sha256'],
              'artifact':file_identity(artifact),'build_record':file_identity(build_path),
              'build_identity_sha256':build['identity_sha256'],
              'codec_card':file_identity(root/'registry/codecs'/(key+'.json')),
              'bridge_identity':bridge_identity(root,bridge),
              'qualification_script':file_identity(Path(__file__)),
              'environment':process_environment()}
    try:
        identity['runtime']=loaded_runtime(build.get('runtime_dependencies',[]))
        if not identity['runtime'].get('implemented'):
            raise RuntimeError(identity['runtime'].get('reason','runtime evidence unavailable'))
        requested=os.environ.get('LD_PRELOAD','').replace(':',' ').split()
        identity['requested_preload_files']=preload_identity([value for value in requested if Path(value).is_absolute()])
    except Exception as error:
        return {'codec':key,'status':'error',**identity,'cases':[],
                'ok_cases':0,'source_rejections':0,'error_cases':1,
                'stage':'runtime_metadata','reason':str(error)}
    def case(name,array,params=None,expect_reject=False):
        resolved=reg.resolve_params(key,params)
        before=array.tobytes()
        record={'case':name,'codec':key,'dtype':array.dtype.str,'shape':list(array.shape),
                'params':resolved,'input_sha256':hashlib.sha256(before).hexdigest()}
        try:
            payload=bridge.encode(array,resolved)
            native_input=bridge.last_input_identity
            restored=bridge.decode(payload,array.dtype,array.shape,resolved)
            bitwise=before==restored.tobytes()
            with np.errstate(all='ignore'):
                max_abs=float(np.max(np.abs(array.astype(np.float64)-restored.astype(np.float64)))) if array.size else 0.
            if array.tobytes()!=before:
                raise AssertionError('encoder mutated input')
            if restored.dtype!=array.dtype or restored.shape!=array.shape:
                raise AssertionError('output descriptor differs')
            if expect_reject:
                raise AssertionError('a declared source-domain rejection was accepted')
            if spec.loss_mode=='LOSSLESS' and not bitwise:
                raise AssertionError('lossless byte comparison failed')
            if spec.loss_mode=='ERROR_BOUNDED_LOSSY' and (not np.isfinite(max_abs) or max_abs>float(resolved['error_bound'])):
                raise AssertionError('maximum absolute error exceeds requested bound')
            if spec.loss_mode=='UNBOUNDED_LOSSY' and not np.isfinite(restored).all():
                raise AssertionError('unbounded reconstruction contains nonfinite values')
            record.update(status='ok',payload_bytes=len(payload),bitwise_equal=bitwise,
                          max_absolute_error=max_abs,codec_input=native_input,
                          payload_sha256=hashlib.sha256(payload).hexdigest(),
                          decoded_sha256=hashlib.sha256(restored.tobytes()).hexdigest())
        except SourceDomainError as error:
            record.update(status='expected_source_rejection' if expect_reject else 'source_rejection',reason=str(error))
        except Exception as error:
            record.update(status=getattr(error,'status','error'),reason=str(error))
        records.append(record)
    for dtype in spec.dtypes:
        for n in (17,257):
            case('dtype-tail-'+str(n),values(spec,dtype,n))
        if 2 in spec.ranks:
            a=values(spec,dtype,17)
            case('matrix-columns-3',np.column_stack([a,a,a]))
        if spec.document['input'].get('min_n',0)==0:
            case('empty',values(spec,dtype,0))
    for rank in (3,4):
        if rank in spec.ranks:
            shape=(3,)*rank
            case('native-nd-rank-'+str(rank),values(spec,spec.dtypes[0],int(np.prod(shape))).reshape(shape))
    if key in {'sprintz-delta','sprintz-fire','sprintz-fire-huff0','sprintz-delta-u8','sprintz-fire-u8'}:
        for dtype in spec.dtypes:
            dtype=np.dtype(dtype);limits=np.iinfo(dtype)
            pattern=np.array([limits.min,limits.max,0,1,limits.max-1,limits.min+1],dtype=dtype)
            case('signed-or-high-bit-pattern-tail',np.resize(pattern,257))
            if 2 in spec.ranks:
                case('signed-or-high-bit-pattern-matrix',np.resize(pattern,257*3).reshape(257,3))
    if key=='simdcomp-u32':
        for isa,api in [('SSE4_1','LENGTH'),('SSE4_1','MASKED'),('SSE4_1','WITHOUTMASK'),('AVX2','MASKED'),('AVX2','WITHOUTMASK')]:
            for n in (0,17,127,128,129,255,256,257):
                case('isa-api-tail',values(spec,'<u4',n),{'isa':isa,'api':api})
            pattern=np.array([0,1,2**31,2**32-1],dtype='<u4')
            case('full-width-bit-pattern',np.resize(pattern,257),{'isa':isa,'api':api})
    if key=='deepzip':
        for model in spec.document['adapter']['models']:
            case('embedded-model-'+model,values(spec,'|u1',17),{'model_key':model})
        case('model-domain-rejection',np.array([0,1,4],dtype='u1'),expect_reject=True)
    if key=='dzip':
        case('combined-mode',values(spec,'|u1',17),{'mode':'COMBINED'})
        case('alphabet-nine-source-rejection',np.arange(9,dtype='u1'),expect_reject=True)
    if key in {'chimp','chimp128','elf','elf-plus','elf-star','self-star'}:
        for dtype in spec.dtypes:
            a=values(spec,dtype,17);a[3]=np.nan
            case('nan-source-domain-rejection',a,expect_reject=True)
    if key in {'neats-lossless-i64','leats-lossless-i64'}:
        for width in (16,32):
            case('max-bpc-'+str(width),values(spec,'<i8',257),{'max_bpc':width})
    if key.startswith('serf-') or key=='zfp-accuracy-1d':
        for dtype in spec.dtypes:
            a=np.sin(np.arange(257)/11).astype(dtype)
            case('quality-irregular-real-values',a,{'error_bound':'0.001'})
            case('quality-fine-bound',a,{'error_bound':'0.00001'})
    errors=[row for row in records if row['status'] not in {'ok','source_rejection','expected_source_rejection'}]
    return {'codec':key,'status':'error' if errors else 'ok',**identity,
            'supported_dtypes':list(spec.dtypes),
            'cases':records,'ok_cases':sum(row['status']=='ok' for row in records),
            'source_rejections':sum('source_rejection' in row['status'] for row in records),
            'error_cases':len(errors)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codec')
    parser.add_argument('--asset-root',type=Path,default=ROOT)
    parser.add_argument('--build-root',type=Path,
                        help='native build directory; relative paths are resolved under --asset-root (default: build/tsbench)')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args();root=args.asset_root.resolve()
    base=args.build_root if args.build_root is not None else Path('build/tsbench')
    base=(base if base.is_absolute() else root/base).resolve()
    if args.codec:
        print(json.dumps(codec_grid(root,args.codec,build_root=base),allow_nan=False,separators=(',',':')))
        return
    output=(args.output or base/'native_qualification_final.json').resolve()
    if output.exists():
        parser.error('refusing to overwrite existing qualification output: '+str(output))
    report={'schema_version':'tsbench.native-qualification.v1','scope':'recorded input/config/binary only; no upstream parity or universal-domain claim',
            'pass_kind':'qualification','bridge_files':{},'records':[],
            'execution':{'fresh_python_subprocess_per_codec':True,
                         'asset_root':str(root),'build_root':str(base),'output':str(output),
                         'parent_environment':process_environment(),
                         'qualification_script':file_identity(Path(__file__))}}
    for path in [root/'benchmark/src/tsbench/registry.py',*sorted((root/'benchmark/src/tsbench/bridges').glob('*.py'))]:
        report['bridge_files'][str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    try:
        with output.open('x') as stream:
            stream.write(json.dumps(report,indent=2,allow_nan=False)+'\n')
    except FileExistsError:
        parser.error('refusing to overwrite existing qualification output: '+str(output))
    for spec in Registry(root).list(include_reference=False):
        started=time.monotonic()
        command=[sys.executable,str(Path(__file__).resolve()),'--asset-root',str(root),
                 '--build-root',str(base),'--codec',spec.key]
        try:
            done=subprocess.run(command,capture_output=True,text=True,timeout=240)
            if done.returncode:
                row={'codec':spec.key,'status':'error','error':done.stderr[-8000:],'returncode':done.returncode}
            else:
                row=json.loads(done.stdout)
        except Exception as error:
            row={'codec':spec.key,'status':'error','error':str(error)}
        row['subprocess_command']=command
        row['elapsed_seconds']=round(time.monotonic()-started,3)
        report['records'].append(row)
        output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(spec.key,row['status'],'cases',row.get('ok_cases',0),'rejects',row.get('source_rejections',0),'errors',row.get('error_cases',0),'seconds',row['elapsed_seconds'],flush=True)
    print('COMPLETE',sum(row['status']=='ok' for row in report['records']),'/',len(report['records']),flush=True)


if __name__=='__main__':
    main()
