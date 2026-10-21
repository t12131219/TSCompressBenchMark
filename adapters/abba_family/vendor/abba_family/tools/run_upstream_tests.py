from pathlib import Path
import subprocess,os,sys,json
P=Path(__file__).resolve().parents[1];R=P.parents[1];site=R/'Toolchains/abba-oracle-runtime';extra=R/'Toolchains/abba-python-extra';records=[]
for name,work,command in [('abba',P/'oracle-runtime/abba',[sys.executable,'-m','unittest','test_ABBA']),('fabba',P/'oracle-runtime/fabba',[sys.executable,'-m','pytest','-q','tests/test_core.py']),('qabba',P/'oracle-runtime/qabba',[sys.executable,'-m','pytest','-q','tests/test_qabba_api.py'])]:
 env=dict(os.environ,PYTHONPATH=os.pathsep.join(map(str,[site,extra,work,work/'src'])),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1');r=subprocess.run(command,cwd=work,capture_output=True,text=True,env=env);log=P/f'validation/{name}-upstream-final-tests.log';log.write_text(r.stdout+r.stderr);records.append({'algorithm':name,'exit':r.returncode,'command':command,'cwd':str(work),'log':str(log.relative_to(P))});print(name,r.returncode,(r.stdout+r.stderr)[-500:])
(P/'validation/upstream-tests.json').write_text(json.dumps({'status':'PASS' if all(x['exit']==0 for x in records) else 'FAIL','results':records},indent=2)+'\n')
