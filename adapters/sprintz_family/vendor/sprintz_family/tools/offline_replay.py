#!/usr/bin/env python3
from pathlib import Path
import subprocess,tempfile,shutil,json,hashlib,argparse,sys
p=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser();ap.add_argument('--report',default='offline-replay.json');a=ap.parse_args();results=[]
with tempfile.TemporaryDirectory(prefix='sprintz-offline-') as td:
 t=Path(td);root=t/'root';port=root/'ReWrite/sprintz-family';source=root/'Source/sprintz-family'
 shutil.copytree(p,port,ignore=shutil.ignore_patterns('build*','install','__pycache__'))
 shutil.copytree(p.parent.parent/'Source/sprintz-family',source)
 # Replay the actual patch against a separate pristine copy and compare every file.
 shutil.copytree(source/'upstream/core',t/'patch-core')
 def run(cmd,cwd=None):
  q=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True);results.append({'command':list(map(str,cmd)),'exit':q.returncode,'stdout':q.stdout[-3000:],'stderr':q.stderr[-3000:]});q.check_returncode();return q
 run(['patch','-p1','-i',port/'patches/native-safety.patch'],t/'patch-core')
 for f in (port/'vendor/core').iterdir():
  if f.is_file():assert f.read_bytes()==(t/'patch-core'/f.name).read_bytes(),f
 run([sys.executable,port/'tools/extract_oracle.py'])
 run(['cmake','-S',port,'-B',port/'build','-DCMAKE_BUILD_TYPE=Release'])
 run(['cmake','--build',port/'build','-j4'])
 run(['ctest','--test-dir',port/'build','--output-on-failure'])
 run(['cmake','-S',port,'-B',port/'build-baseline','-DSZ_CORE='+str(source/'upstream/core'),'-DCMAKE_BUILD_TYPE=Release'])
 run(['cmake','--build',port/'build-baseline','--target','sprintz_oracle','-j4'])
 run([sys.executable,port/'tools/verify.py','--frozen-data'])
 run([sys.executable,port/'tools/replay_frozen.py'])
 run([sys.executable,port/'tools/install_consumer.py'])
(p/'evidence'/a.report).write_text(json.dumps({'status':'PASS','network_used':False,'clean_copied_tree':True,'patch_replay':'PASS','results':results},indent=2)+'\n')
print('offline clean build, patch replay, differential, frozen datasets and consumers PASS')
