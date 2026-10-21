"""Two independent offline source copies -> bit-for-bit artifact comparison."""
from pathlib import Path
import shutil,subprocess,json,hashlib,os,argparse,time
P=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',default='/tmp/abba-family-offline-reproduction');args=ap.parse_args();root=Path(args.root);root.mkdir(exist_ok=True);records=[];artifacts=[]
 for index in [1,2]:
  source=root/f'copy-{index}';source.mkdir(exist_ok=True)
  for name in ['src','include','vendor','tools','tests']:
   shutil.copytree(P/name,source/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','fuzz-corpus'))
  shutil.copy2(P/'CMakeLists.txt',source/'CMakeLists.txt');build=root/f'build-{index}';env=dict(os.environ,SOURCE_DATE_EPOCH='1789776000',LC_ALL='C',TZ='UTC');commands=[['cmake','-S',str(source),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release'],['cmake','--build',str(build),'-j3'],['ctest','--test-dir',str(build),'--output-on-failure']]
  for n,cmd in enumerate(commands):
   r=subprocess.run(cmd,capture_output=True,text=True,env=env);log=P/f'validation/reproduce-{index}-{n}.log';log.write_text(r.stdout+r.stderr);records.append({'command':cmd,'exit':r.returncode,'log':str(log.relative_to(P))});r.check_returncode()
  artifacts.append({name:sha(build/name) for name in ['libabba_family.so','libabba_family_static.a','libaf_ckmeans.a','libaf_byte_zlib.a','libaf_byte_zstd.a','libaf_byte_bz2.a','xz-build/src/liblzma/.libs/liblzma.a','abba_family_cli','af_native_tests','af_benchmark']})
 differences=[name for name in artifacts[0] if artifacts[0][name]!=artifacts[1][name]];report={'status':'PASS' if not differences else 'NOT_YET_REPRODUCIBLE','definition':'Two independent source/build absolute paths, identical frozen tools/flags/env, no downloads or host codec dependencies','artifacts':artifacts,'differences':differences,'steps':records};(P/'validation/build-reproducibility.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],differences)
 if differences:raise SystemExit(1)
if __name__=='__main__':main()
