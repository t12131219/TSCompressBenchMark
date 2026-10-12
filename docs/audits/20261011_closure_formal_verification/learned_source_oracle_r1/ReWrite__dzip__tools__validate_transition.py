"""Check source CuDNN checkpoints -> canonical CPU graph -> full native codecs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from validate_nn import tensors

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--build',type=Path,required=True)
    parser.add_argument('--native-training',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);records=[];commands=[]
    def run(label,command):
        p=subprocess.run([str(x) for x in command],capture_output=True,timeout=1800)
        log=out/(label+'.log');log.write_bytes(p.stdout+p.stderr)
        commands.append(dict(command=[str(x) for x in command],exit_code=p.returncode,log=str(log.relative_to(ROOT)),log_sha256=sha(log)))
        assert p.returncode==0,p.stderr.decode(errors='replace')
    try:
        for name in ['ETTh1','exchange_rate','weather']:
            source=ROOT/'validation/source-bootstrap-schedule'/name
            expected=source/'best.dzn';h5=source/'input_biGRU_jump';cpu=out/(name+'-cpu.dzn');converted=out/(name+'-converted.dzn')
            run(name+'-import',[args.build/'dzip_nn_cli','import',h5,'bootstrap',0,cpu])
            run(name+'-convert',[args.build/'dzip_nn_cli','codec-model',expected,'bootstrap',0,converted])
            assert cpu.read_bytes()==converted.read_bytes(),'CuDNN import and graph conversion differ'
            assert all(a[:3]==b[:3] and np.array_equal(a[3],b[3]) for a,b in zip(tensors(expected),tensors(cpu))),'conversion changes canonical kernels'
            training_report=json.loads((args.native_training/'report.json').read_text())
            assert training_report['status']=='PASS','native training qualification must pass'
            native_trained=args.native_training/name/'best.dzn'
            assert native_trained.is_file(),'explicit native-trained checkpoint missing'
            profiles=[('source_trained',expected),('native_trained',native_trained)]
            for trained_label,model in profiles:
                for mode in ['bootstrap','combined']:
                    stem=name+'-'+trained_label+'-'+mode;model_cpu=out/(stem+'.dzn');encoded=out/(stem+'.frame');decoded=out/(stem+'.decoded')
                    run(stem+'-model',[args.build/'dzip_nn_cli','codec-model',model,mode,0,model_cpu])
                    run(stem+'-encode',[args.build/'dzip_cli','encode',mode,model_cpu,source/'normalized.txt',encoded])
                    run(stem+'-decode',[args.build/'dzip_cli','decode',encoded,decoded])
                    assert decoded.read_bytes()==(source/'normalized.txt').read_bytes(),'trained full codec roundtrip differs'
                    records.append(dict(dataset=name,training=trained_label,mode=mode,status='PASS',source_h5_sha256=sha(h5),
                                        trained_graph_sha256=sha(model),codec_model_sha256=sha(model_cpu),input_sha256=sha(source/'normalized.txt'),
                                        frame_sha256=sha(encoded),final_bits=encoded.stat().st_size*8))
        result=dict(status='PASS',cases=records,commands=commands)
    except Exception as e:result=dict(status='FAIL',error=str(e),cases=records,commands=commands)
    result.update(driver_sha256=sha(Path(__file__)),binaries={p:sha(args.build/p) for p in ['dzip_nn_cli','dzip_cli']},
                  source_files={str(p.relative_to(ROOT)):sha(p) for d in ['src','include'] for p in (ROOT/d).glob('*') if p.is_file()},
                  limitation='Native/source trained-weight numerical parity remains a separate gate; successful roundtrip does not waive failed tolerances.')
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(dict(status=result['status'],cases=len(records),error=result.get('error'))))
    raise SystemExit(0 if result['status']=='PASS' else 1)
if __name__=='__main__':main()
