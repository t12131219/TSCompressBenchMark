#!/usr/bin/env python3
"""Extract, hash-check, build and exercise a release without the original tree."""
import argparse,hashlib,json,pathlib,subprocess,tarfile,tempfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    a=argparse.ArgumentParser();a.add_argument('archive',type=pathlib.Path);a.add_argument('--out',type=pathlib.Path,required=True);args=a.parse_args()
    archive=args.archive.resolve();manifest=json.loads(archive.with_suffix(archive.suffix+'.manifest.json').read_text())
    if sha(archive)!=manifest['sha256']:raise RuntimeError('archive hash mismatch')
    report={'archive':str(archive),'archive_sha256':sha(archive),'commands':[],'status':'RUNNING'}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    def run(argv,cwd=None):
        p=subprocess.run([str(x) for x in argv],cwd=cwd,capture_output=True,text=True)
        report['commands'].append({'argv':[str(x) for x in argv],'cwd':str(cwd),'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
        if p.returncode:raise RuntimeError(report['commands'][-1])
    try:
        with tempfile.TemporaryDirectory(prefix='alp-archive-') as td:
            clean=pathlib.Path(td)
            with tarfile.open(archive,'r:gz') as t:
                for m in t.getmembers():
                    if pathlib.Path(m.name).is_absolute() or '..' in pathlib.Path(m.name).parts or not m.isfile():raise RuntimeError('unexpected member')
                t.extractall(clean)
            for f,h in manifest['files'].items():
                if sha(clean/f)!=h:raise RuntimeError('member mismatch '+f)
            report['members_verified']=len(manifest['files'])
            p=clean/'ReWrite/alp-cwida';b=clean/'build'
            production=[p/'CMakeLists.txt']+[f for d in ['include','src','vendor','tests','tools'] for f in (p/d).rglob('*') if f.is_file() and '__pycache__' not in f.parts]
            report['validated_source_files']={str(f.relative_to(p)):sha(f) for f in production}
            run(['cmake','-S',p,'-B',b,'-DCMAKE_BUILD_TYPE=Release','-DALP_PORT_ORACLE=ON','-DCMAKE_CXX_COMPILER=g++','-DCMAKE_C_COMPILER=gcc'])
            run(['cmake','--build',b,'-j4']);run(['ctest','--test-dir',b,'-V'])
            run(['python3',p/'tools/replay_patch.py'],cwd=p)
            run(['python3',p/'tools/verify.py','--out',clean/'synthetic','--cli',b/'alp_cli','--oracle',b/'alp_upstream_oracle'],cwd=p)
            report['synthetic_totals']=json.loads((clean/'synthetic/verification.json').read_text())['totals']
            prefix=clean/'installed';run(['cmake','--install',b,'--prefix',prefix])
            cli=prefix/'bin/alp_cli';run([cli,'info'],cwd=clean)
            raw=clean/'synthetic/synthetic_decimal_tail_f64/input.raw'
            run([cli,'encode','f64','alp',raw,clean/'cold.frame',1],cwd=clean)
            run([cli,'decode','f64','alp',clean/'cold.frame',clean/'cold.raw',1],cwd=clean)
            if (clean/'cold.raw').read_bytes()!=raw.read_bytes():raise RuntimeError('installed cold recovery')
            report['installed_cold_decode']='PASS'
            report['reproducible_installed_binaries']={}
            for rel in ['lib/libalp_port.so','bin/alp_cli']:
                current=ROOT/'dist/x86_64-portable'/rel;new=prefix/rel
                report['reproducible_installed_binaries'][rel]={'original_sha256':sha(current),'clean_sha256':sha(new),'byte_identical':sha(current)==sha(new)}
                if sha(current)!=sha(new):raise RuntimeError('reproducible release binary mismatch '+rel)
            report['status']='PASS'
    except Exception as e:
        report['status']='FAIL';report['error']=str(e)
    args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['commands','validated_source_files']}))
    return report['status']!='PASS'
if __name__=='__main__':raise SystemExit(main())
