from pathlib import Path
import subprocess,json,hashlib,shutil,sys
root=Path(__file__).resolve().parents[3]
repos=Path('/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos')
configs={'abba':('nla-group_ABBA_web_20261020','https://github.com/nla-group/ABBA','MIT'),'fabba':('nla-group_fABBA_web_20261020','https://github.com/nla-group/fABBA','BSD-3-Clause'),'qabba':('inEXASCALE_qabba','https://github.com/inEXASCALE/qabba','MIT')}
for a,(name,url,license) in configs.items():
 repo=repos/name;out=root/'Source'/a;out.mkdir(exist_ok=True);rows=[];inventory=[]
 for x in subprocess.check_output(['git','-C',str(repo),'ls-files'],text=True).splitlines():
  take=(x in ['ABBA.py','LICENSE','README.md','setup.py','makefile','requirements.txt','pyproject.toml','setup.cfg','test_ABBA.py','runtest.py','util.py','.travis.yml'] or x.startswith(('.github/','tests/','test/','docs/source/')) or x.startswith({'abba':'src/','fabba':'fABBA/','qabba':'src/qabba/'}[a])) and Path(x).suffix in ['','.txt','.py','.pyx','.pxd','.c','.cpp','.h','.i','.toml','.cfg','.yml','.yaml','.rst','.md']
  inventory.append({'path':x,'included':take,'reason':'source/build/test/documentation closure' if take else 'dataset, experiment, generated build, distribution or unrelated artifact'})
  if not take:continue
  data=subprocess.check_output(['git','-C',str(repo),'show','HEAD:'+x]);f=out/'upstream'/x;f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(data)
  rows.append({'path':x,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'license':license})
 commit=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
 (out/'SOURCE_MANIFEST.json').write_text(json.dumps({'algorithm_id':a,'repository':url,'clone_directory':str(repo),'acquired_directly_from_github':'2026-10-20','commit':commit,'license':license,'patches':[],'files':rows},indent=2)+'\n')
 (out/'REPOSITORY_INVENTORY.json').write_text(json.dumps(inventory,indent=2)+'\n')
 print(a,commit,len(rows))
