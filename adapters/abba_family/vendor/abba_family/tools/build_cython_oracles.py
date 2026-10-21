from pathlib import Path
import subprocess,sys,shutil,os,json
P=Path(__file__).resolve().parents[1];R=P.parents[1];extra=R/'Toolchains/abba-python-extra';records=[]
for a in ['fabba','qabba']:
 dest=P/'oracle-runtime'/a;shutil.copytree(R/'Source'/a/'upstream',dest,dirs_exist_ok=True)
 env=dict(os.environ,PYTHONPATH=str(R/'Toolchains/abba-build-extra/setuptools/_vendor')+os.pathsep+str(R/'Toolchains/abba-build-extra')+os.pathsep+str(extra)+os.pathsep+str(R/"Toolchains/abba-oracle-runtime"),PYTHONDONTWRITEBYTECODE='1')
 r=subprocess.run([sys.executable,'setup.py','build_ext','--inplace'],cwd=dest,env=env,capture_output=True,text=True)
 (P/'validation'/f'{a}-cython-build.log').write_text(r.stdout+r.stderr)
 records.append({'algorithm':a,'exit':r.returncode,'command':[sys.executable,'setup.py','build_ext','--inplace'],'worktree':str(dest)})
 if r.returncode:print(r.stderr[-2000:]);break
(P/'validation/cython-build.json').write_text(json.dumps(records,indent=2)+'\n')
assert len(records)==2 and all(x['exit']==0 for x in records)
print('Both frozen upstream Cython oracle packages built')
