"""Replay the original non-codec loader counterexample without altering it."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
ORIGINAL = Path('/tmp/tscb-runtime-resolution-repro-20261011-TjbV3Y')
OUT = Path(__file__).resolve().parent / 'runtime_resolution_replay_v1.json'
CHILD = '''
import ctypes,json,sys
from pathlib import Path
from tscompbench.adapters.build_evidence import verified_build_dependencies
from tscompbench.adapters.runtime_evidence import verified_runtime_dependencies
root=Path(sys.argv[1]); artifact=root/'artifacts/release/libtoy_wrapper.so'
adapter={'factory':'TOY_NATIVE_CTYPES_V1'}
try:
    paths=verified_build_dependencies(root,artifact,'toy-native',adapter)
    lib=ctypes.CDLL(str(artifact)); lib.toy_entry.restype=ctypes.c_int
    verified_runtime_dependencies(root,artifact,adapter,loaded=True)
    print(json.dumps({'status':'PASS','value':lib.toy_entry(),'support_count':len(paths)}))
except Exception as error:
    print(json.dumps({'status':'REJECTED','error':str(error)}))
'''

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

watched = [ORIGINAL / relative for relative in (
    'artifacts/release/libtoy_wrapper.so', 'artifacts/release/build-record.json',
    'artifacts/release/compile-command.json', 'recorded-runtime/libtoy_runtime.so',
    'result.json', 'repro.py', 'check_load.py',
)]
before = {str(path): digest(path) for path in watched}
observations=[]
for selection in ('recorded-runtime','alternative-runtime'):
    environment={**os.environ,'PYTHONPATH':str(ROOT/'src'),'LD_LIBRARY_PATH':str(ORIGINAL/selection)}
    environment.pop('LD_PRELOAD',None); environment.pop('LD_AUDIT',None)
    result=subprocess.run([sys.executable,'-c',CHILD,str(ORIGINAL)],check=True,capture_output=True,text=True,env=environment)
    observations.append({'selection':selection,**json.loads(result.stdout)})
after={str(path):digest(path) for path in watched}
passed=before==after and observations[0].get('value')==11 and observations[1]['status']=='REJECTED'
report={'status':'PASS' if passed else 'FAIL','scope':'REPLAY_ORIGINAL_THREE_NON_CODEC_DSOS_WITH_ACTUAL_PRE_POST_LOADER_GATE_NOT_CODEC_PARITY','observations':observations,'original_inputs_preserved':before==after,'original_input_hashes':before,'driver_sha256':digest(Path(__file__)),'runtime_gate_sha256':digest(ROOT/'src/tscompbench/adapters/runtime_evidence.py')}
with OUT.open('x') as stream: stream.write(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
if not passed: raise SystemExit(1)
