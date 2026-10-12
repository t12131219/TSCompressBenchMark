"""Native/source probability and actual online-Adam weight differential."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def tensors(path):
    raw=path.read_bytes();position=8
    def word():
        nonlocal position
        value=struct.unpack_from('<I',raw,position)[0];position+=4;return value
    context=word();alphabet=word();count=word();weights=[]
    for node in range(count):
        kind=word();activation=word();inputs=word()
        for _ in range(inputs):word()
        for index in range(word()):
            shape=[word() for _ in range(word())];n=int(np.prod(shape))
            weights.append((node,index,shape,np.frombuffer(raw,dtype='<f4',count=n,offset=position)))
            position+=4*n
    assert position==len(raw)
    return weights


def main():
    p=argparse.ArgumentParser();p.add_argument('--cli',type=Path,required=True)
    p.add_argument('--training-source',type=Path,default=ROOT/'validation/source-training/alphabet-2')
    p.add_argument('--output',type=Path,default=ROOT/'validation/native-nn')
    p.add_argument('--skip-probabilities',action='store_true');p.add_argument('--cuda',action='store_true');a=p.parse_args()
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=True);commands=[];cases=[]
    def run(label,args):
        start=time.monotonic();command=list(map(str,[a.cli,*args]));process=subprocess.run(command,capture_output=True,timeout=300)
        log=output/(label+'.log');log.write_bytes(process.stdout+process.stderr)
        commands.append(dict(command=command,exit_code=process.returncode,seconds=time.monotonic()-start,
                             log=str(log.relative_to(ROOT)),log_sha256=sha(log)))
        if process.returncode:raise RuntimeError(process.stderr.decode(errors='replace')[-1500:])
    try:
        for alphabet in ([] if a.skip_probabilities else [1,2,4,10,128]):
            source=ROOT/('validation/source-oracle/alphabet-'+str(alphabet))
            for profile in ['bootstrap','combined']:
                target=output/(str(alphabet)+'-'+profile+'.f32')
                run(str(alphabet)+'-'+profile,['predict',source/(profile+'.dzn'),source/'contexts.i32',target])
                expected=np.fromfile(source/(profile+'.probabilities.f32'),dtype='<f4');actual=np.fromfile(target,dtype='<f4')
                difference=np.abs(actual-expected);allowed=2e-6+2e-5*np.abs(expected)
                passed=actual.shape==expected.shape and bool(np.all(difference<=allowed))
                cases.append(dict(kind='probability',alphabet=alphabet,profile=profile,status='PASS' if passed else 'FAIL',
                    maximum_absolute_error=float(np.max(difference)),input_model_sha256=sha(source/(profile+'.dzn')),source_probability_sha256=sha(source/(profile+'.probabilities.f32'))))
                assert passed,'probability differential failed'
        source=a.training_source
        metadata=json.loads((source/'report.json').read_text())
        if a.cuda:
            assert metadata.get('profile')=='bootstrap_cudnn','CUDA validation requires the source bootstrap graph'
            assert a.skip_probabilities,'CPU constructor probability fixtures do not describe CuDNN models'
        tests=[('gradient',0)] if (source/'gradients.dzn').exists() else []
        tests.extend(('train',index+1) for index in range(len(metadata['steps'])))
        for operation,steps in tests:
            target=output/('trained-'+str(steps)+'.dzn')
            command='bootstrap-train' if metadata.get('profile')=='bootstrap_cudnn' else 'train'
            arguments=[operation if operation=='gradient' else command,source/'initial.dzn',source/'contexts.i32',source/'labels.i32',target]
            if a.cuda:arguments[0]='cuda-'+arguments[0]
            if operation=='train':arguments.append(steps)
            run(operation+'-'+str(steps),arguments)
            reference=source/('gradients.dzn' if operation=='gradient' else 'updated-'+str(steps-1)+'.dzn')
            source_weights=tensors(reference);native_weights=tensors(target)
            assert len(source_weights)==len(native_weights)
            mismatches=[];maximum=0
            for expected,actual in zip(source_weights,native_weights):
                assert expected[:3]==actual[:3]
                error=np.abs(expected[3]-actual[3]);allowed=2e-6+2e-4*np.abs(expected[3]);bad=int(np.sum(error>allowed))
                maximum=max(maximum,float(np.max(error)))
                if bad:mismatches.append(dict(node=expected[0],tensor=expected[1],outside_tolerance=bad,max_abs=float(np.max(error))))
            cases.append(dict(kind='raw_gradients' if operation=='gradient' else metadata.get('profile','online_adam')+'_weights',
                              steps=steps,alphabet=metadata['alphabet'],batch=metadata['batch'],status='FAIL' if mismatches else 'PASS',
                              maximum_absolute_error=maximum,mismatches=mismatches,
                              native_weight_sha256=sha(target),source_weight_sha256=sha(reference)))
        status='PASS' if all(c['status']=='PASS' for c in cases) else 'FAIL'
        report=dict(status=status,cases=cases,commands=commands)
    except Exception as error:report=dict(status='FAIL',error=str(error),cases=cases,commands=commands)
    report.update(backend='cuda_gru_cublas' if a.cuda else 'canonical_scalar',cli_sha256=sha(a.cli),source_files={str(path.relative_to(ROOT)):sha(path) for folder in ['src','include']
                  for path in sorted((ROOT/folder).rglob('*')) if path.is_file()},
                  driver_sha256=sha(Path(__file__)),tolerances='Frozen contract.md; no post-failure adjustment')
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(status=report['status'],cases=[dict(kind=c['kind'],status=c['status'],max_abs=c['maximum_absolute_error']) for c in cases],error=report.get('error'))))
    raise SystemExit(0 if report['status']=='PASS' else 1)


if __name__=='__main__':main()
