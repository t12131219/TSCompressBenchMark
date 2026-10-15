from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
root=Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
base=root/'build/gorilla-installed-check-final'
base.mkdir(exist_ok=False)
commands=[]
def invoke(args,env=None):
    command=[sys.executable,*args];done=subprocess.run(command,cwd=base,env=env,capture_output=True,text=True,timeout=180)
    commands.append({'command':command,'returncode':done.returncode,'stdout':done.stdout,'stderr':done.stderr})
    if done.returncode: raise RuntimeError(done.stderr)
    return done.stdout
assets=base/'assets'
for name in ['adapters/gorilla_prometheus_xor','native/include']:
    shutil.copytree(root/name,assets/name)
(assets/'registry/codecs').mkdir(parents=True)
shutil.copy2(root/'registry/codecs/gorilla-prometheus-xor.json',assets/'registry/codecs')
invoke(['-m','pip','wheel','--no-deps','--no-build-isolation',str(root/'benchmark'),'--wheel-dir',str(base/'wheels')])
wheel=next((base/'wheels').glob('tsbench*.whl'))
invoke(['-m','pip','install','--no-deps','--no-index','--target',str(base/'site'),str(wheel)])
env={**os.environ,'PYTHONPATH':str(base/'site')}
built=json.loads(invoke(['-m','tsbench','build','gorilla-prometheus-xor','--asset-root',str(assets)],env))[0]
assert built['status']=='ok'
program='''
from pathlib import Path
import json,numpy as np,tsbench
from tsbench.data import TimeSeriesObject
from tsbench.schemes import ObjectScheme
base=Path.cwd();assets=base/'assets'
t=np.array([-2**63,-1,0,2**63-1],dtype='<i8')
v=np.array([0,2**63,0x7ff0000000000001,0x7ff8123456781234],dtype='<u8').view('<f8')
o=TimeSeriesObject({'T':t,'V':v},{'roles':{'T':'T','V':'V'},'time_unit':'ms'})
w=ObjectScheme({'codec':'gorilla-prometheus-xor'},asset_root=assets).encode_once(o)
(base/'object.tsb').write_bytes(w.wire)
np.savez(base/'expected.npz',T=t,V=v)
print(json.dumps({'package':tsbench.__file__,'wire_bytes':len(w.wire)}))
'''
encoded=json.loads(invoke(['-c',program],env));assert Path(encoded['package']).is_relative_to(base/'site')
runtime=base/'decoder-assets'
(runtime/'registry/codecs').mkdir(parents=True)
shutil.copy2(assets/'registry/codecs/gorilla-prometheus-xor.json',runtime/'registry/codecs')
index=json.loads((assets/'build/tsbench/gorilla-prometheus-xor.index.json').read_text())
binpath=Path(index['artifact']);target=runtime/'build/tsbench/installed/gorilla-prometheus-xor'
target.mkdir(parents=True)
shutil.copy2(binpath,target/binpath.name);shutil.copy2(binpath.parent/'build.json',target/'build.json')
(runtime/'build/tsbench/gorilla-prometheus-xor.index.json').write_text(json.dumps({'artifact':str(target/binpath.name),'build_record':str(target/'build.json'),'build_id':built['build_id']}))
# Remove encoder source assets before a new decoder starts.
shutil.rmtree(assets)
invoke(['-m','tsbench','decode',str(base/'object.tsb'),str(base/'decoded'),'--asset-root',str(runtime)],env)
import numpy as np
metadata=json.loads((base/'decoded/object.json').read_text())
with np.load(base/'expected.npz') as expected:
    for name,file in metadata['components'].items():
        actual=np.load(base/'decoded'/file)
        assert actual.dtype==expected[name].dtype and actual.shape==expected[name].shape
        assert actual.tobytes()==expected[name].tobytes()
files=[]
for source in sorted((root/'benchmark/src/tsbench').rglob('*.py')):
    installed=base/'site/tsbench'/source.relative_to(root/'benchmark/src/tsbench')
    assert source.read_bytes()==installed.read_bytes()
    files.append({'path':str(source.relative_to(root)),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
record={'schema':'tsbench.gorilla-installed-verification/1','passed':True,'wheel':str(wheel.relative_to(root)),'wheel_sha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'installed_files':files,'fresh_native_build':built,'encoder_source_assets_removed_before_decode':True,'decoder_only_wire_and_installed_binary_card_runtime':True,'encoded':encoded,'commands':commands,'scope':'same host, isolated installation and source-free wire-only new interpreter; no third-party or physical second machine claim'}
(root/'docs/gorilla_integration/installed_verification.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print('PASS installed wheel, fresh Gorilla build, source-free independent decoder,',len(files),'matching Python files')
