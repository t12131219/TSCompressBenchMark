from pathlib import Path
import json,hashlib,tarfile,gzip,tempfile,subprocess,sys,io
p=Path(__file__).resolve().parents[1];root=p.parent.parent;release=root/'Release';release.mkdir(exist_ok=True)
name='sprintz-family-native-20261017';archive=release/(name+'.tar.gz');index_rel=Path('ReWrite/sprintz-family/PACKAGE_INDEX.json')
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
# Validate immutable source snapshot first.
manifest=json.loads((root/'Source/sprintz-family/SOURCE_MANIFEST.json').read_text())
for row in manifest['files']:assert sha(root/'Source/sprintz-family'/row['path'])==row['sha256'],row['path']
files=[]
for base in [root/'Source/sprintz-family',p]+[root/'ReWrite'/n for n in ['sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman']]:
 for f in sorted(base.rglob('*')):
  if not f.is_file():continue
  parts=f.relative_to(base).parts
  if base==p and any(x.startswith('build') or x=='__pycache__' for x in parts):continue
  if f.relative_to(root)==index_rel:continue
  assert not f.is_symlink(),f
  files.append(f)
rows=[{'path':str(f.relative_to(root)),'bytes':f.stat().st_size,'sha256':sha(f)} for f in sorted(set(files))]
index={'format':'sprintz-family-recovery-index-v1','excluded_self':str(index_rel),'files':rows,'file_count':len(rows),'network_dependency':False}
(root/index_rel).write_text(json.dumps(index,indent=2)+'\n');files.append(root/index_rel)
with archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,filename='',mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w|') as tar:
 for f in sorted(set(files)):
  info=tar.gettarinfo(str(f),arcname=str(f.relative_to(root)));info.uid=info.gid=0;info.uname=info.gname='';info.mtime=0;info.mode=0o755 if f.stat().st_mode&0o111 else 0o644
  with f.open('rb') as data:tar.addfile(info,data)
# Package-outside audit in a new directory; no original install/build used.
with tempfile.TemporaryDirectory(prefix='sprintz-package-audit-') as td:
 target=Path(td)
 with tarfile.open(archive) as tar:
  for item in tar.getmembers():assert item.isfile() and not Path(item.name).is_absolute() and '..' not in Path(item.name).parts,item.name
  tar.extractall(target)
 unpacked=json.loads((target/index_rel).read_text());expected={x['path'] for x in unpacked['files']}|{str(index_rel)};actual={str(f.relative_to(target)) for f in target.rglob('*') if f.is_file()};assert actual==expected,(actual-expected,expected-actual)
 for row in unpacked['files']:assert sha(target/row['path'])==row['sha256']
 extracted=target/'ReWrite/sprintz-family'
 def run(cmd):
  r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True);r.check_returncode();return {'command':list(map(str,cmd)),'exit':r.returncode,'stdout':r.stdout[-3000:],'stderr':r.stderr[-3000:]}
 results=[]
 results.append(run([sys.executable,extracted/'tools/offline_replay.py','--report','package-offline-replay.json']))
 replay=json.loads((extracted/'evidence/package-offline-replay.json').read_text());assert replay['status']=='PASS'
 audit={'status':'PASS','archive_sha256':sha(archive),'package_index_sha256':sha(root/index_rel),'indexed_files':len(rows),'all_archive_files_indexed':True,'hashes_verified':True,'package_outside_clean_offline_replay':replay,'runner':results}
(release/(name+'.audit.json')).write_text(json.dumps(audit,indent=2)+'\n')
outer={'archive':archive.name,'archive_bytes':archive.stat().st_size,'archive_sha256':sha(archive),'index_sha256':sha(root/index_rel),'audit':name+'.audit.json','audit_sha256':sha(release/(name+'.audit.json')),'qualification':'NATIVE_PORT_QUALIFIED(limited profile)','full_parity':False,'rewrite_done':False,'benchmark_integrated':False}
(release/(name+'.index.json')).write_text(json.dumps(outer,indent=2)+'\n')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':sha(archive),'indexed_files':len(rows),'package_outside_audit':'PASS'},indent=2))
