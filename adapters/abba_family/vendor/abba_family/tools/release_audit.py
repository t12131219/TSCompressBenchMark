"""Materialize the distribution outside this workspace and verify cold recovery."""
from pathlib import Path
import subprocess,shutil,json,hashlib,os,sys,argparse,time
P=Path(__file__).resolve().parents[1];R=P.parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--reindex',action='store_true');ap.add_argument('--directory',default='/tmp/abba-family-package-audit-20261020/Compression_Rewrite');args=ap.parse_args();dest=Path(args.directory);dest.mkdir(parents=True,exist_ok=True)
 def ignore(path,names):
  excluded=[n for n in names if n=='__pycache__' or n.endswith('.pyc') or n=='core' or n.startswith('core.')]
  if Path(path)==P:excluded += [n for n in names if n=='build' or n.startswith('build-') or n in ['oracle-runtime','install']]
  return excluded
 for name in ['abba','fabba','qabba','abba-family-dependencies']:shutil.copytree(R/'Source'/name,dest/'Source'/name,dirs_exist_ok=True,ignore=ignore)
 for name in ['abba','fabba','qabba','abba-family']:shutil.copytree(R/'ReWrite'/name,dest/'ReWrite'/name,dirs_exist_ok=True,ignore=ignore)
 family=dest/'ReWrite/abba-family';steps=[];env=dict(os.environ,LC_ALL='C',TZ='UTC',SOURCE_DATE_EPOCH='1789776000');env.pop('PYTHONPATH',None);env.pop('LD_LIBRARY_PATH',None)
 commands=[['cmake','-S','.','-B','build','-DCMAKE_BUILD_TYPE=Release'],['cmake','--build','build','-j3'],['ctest','--test-dir','build','--output-on-failure'],[sys.executable,'tools/install_consumer.py'],[sys.executable,'tools/bootstrap_oracle.py'],[sys.executable,'tools/build_oracles.py'],[sys.executable,'tools/build_cython_oracles.py'],[sys.executable,'tools/verify_stages.py','--report','package-source-stages.json'],[sys.executable,'tools/verify_capabilities.py','--report','package-source-capabilities.json']]
 if args.reindex:
  previous=json.loads((P/'validation/package-recovery-audit.json').read_text());assert all(x['exit']==0 for x in previous['steps']);steps=previous['steps'];commands=[]
 for i,cmd in enumerate(commands):
  r=subprocess.run(cmd,cwd=family,env=env,capture_output=True,text=True);log=P/f'validation/package-audit-{i}.log';log.write_text(r.stdout+r.stderr);steps.append({'command':cmd,'exit':r.returncode,'cwd':str(family),'log':str(log.relative_to(P))});r.check_returncode()
 # Revalidate every transported file after replay; generated files are separate.
 mismatches=[];count=0
 for area,names in [('Source',['abba','fabba','qabba','abba-family-dependencies']),('ReWrite',['abba','fabba','qabba','abba-family'])]:
  for name in names:
   base=R/area/name
   for src in base.rglob('*'):
    relative=src.relative_to(base)
    if not src.is_file() or ('__pycache__' in relative.parts or (area=='ReWrite' and name=='abba-family' and (relative.parts[0]=='build' or relative.parts[0].startswith('build-') or relative.parts[0] in ['oracle-runtime','install']))) or src.suffix=='.pyc' or src.name.startswith('core'):continue
    if area=='ReWrite' and name=='abba-family' and relative.parts[0]=='validation':continue
    target=dest/area/name/relative;count+=1
    if not target.exists() or hashlib.sha256(src.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():mismatches.append(str(target))
 report={'status':'PASS' if not mismatches else 'FAIL','files_verified':count,'transport_reindex_after_documentation':args.reindex,'mismatches':mismatches,'package_root':str(dest),'steps':steps,'closed_runtime':'C++ only; all byte codecs statically linked. Python oracle rebuilt offline from bundled wheels and frozen sources.'};(P/'validation/package-recovery-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],count)
 if mismatches:raise SystemExit(1)
if __name__=='__main__':main()
