"""Qualify self-contained codec and record source raw-stream experiments honestly."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cli',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'validation/native-codec');args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True);commands=[];cases=[]
    def run(label,command):
        command=list(map(str,[args.cli,*command]));start=time.monotonic();p=subprocess.run(command,capture_output=True,timeout=600)
        log=output/(label+'.log');log.write_bytes(p.stdout+p.stderr)
        commands.append(dict(command=command,exit_code=p.returncode,seconds=time.monotonic()-start,log=str(log.relative_to(ROOT)),log_sha256=sha(log)))
        assert p.returncode==0,p.stderr.decode(errors='replace')[-2000:]
    try:
        for alphabet in [2,4]:
            source=ROOT/('validation/source-oracle/alphabet-'+str(alphabet))
            for length in [65,191,192,193,321]:
                fixture=source/('length-'+str(length));input_path=fixture/'input.txt'
                for profile in ['bootstrap','combined']:
                    name=f'{alphabet}-{length}-{profile}';model=source/(profile+'.dzn');frame=output/(name+'.dzcp');decoded=output/(name+'.decoded')
                    run(name+'-encode',['encode',profile,model,input_path,frame]);run(name+'-decode',['decode',frame,decoded])
                    assert decoded.read_bytes()==input_path.read_bytes()
                    raw=output/(name+'.raw');raw_decoded=output/(name+'.symbols.i32')
                    run(name+'-raw-encode',['encode-raw',profile,model,input_path,raw])
                    run(name+'-raw-source-decode',['decode-raw',profile,model,length,fixture/(profile+'.dzip'),raw_decoded])
                    symbols=np.load(fixture/'input.npy').reshape(-1)
                    got=np.fromfile(raw_decoded,dtype='<i4')
                    cases.append(dict(alphabet=alphabet,length=length,profile=profile,status='PASS',
                        input_sha256=sha(input_path),model_sha256=sha(model),frame_sha256=sha(frame),frame_bytes=frame.stat().st_size,
                        source_raw_equal=raw.read_bytes()==(fixture/(profile+'.dzip')).read_bytes(),
                        native_decode_source_raw_exact=bool(np.array_equal(symbols,got)),
                        caveat='Source raw cross-decode experiments do not change the frozen SEMANTIC target; native numerical profile is explicit.'))
        result=dict(status='PASS',cases=cases,commands=commands)
    except Exception as error:result=dict(status='FAIL',error=str(error),cases=cases,commands=commands)
    result.update(cli_sha256=sha(args.cli),driver_sha256=sha(Path(__file__)),
                  source_files={str(path.relative_to(ROOT)):sha(path) for folder in ['src','include'] for path in sorted((ROOT/folder).rglob('*')) if path.is_file()})
    (output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(status=result['status'],cases=len(cases),source_raw_equal=sum(c['source_raw_equal'] for c in cases),
                         native_decode_source_raw_exact=sum(c['native_decode_source_raw_exact'] for c in cases),error=result.get('error'))))
    raise SystemExit(0 if result['status']=='PASS' else 1)


if __name__=='__main__':main()
