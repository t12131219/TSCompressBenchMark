#!/usr/bin/env python3
"""Independent extraction, hash check, fresh C++ and Java builds, installed cold decode and reproducibility."""
import argparse,gzip,hashlib,json,pathlib,shutil,subprocess,tarfile,tempfile
from verify import Server,normalize,sha
p=argparse.ArgumentParser();p.add_argument('--archive',type=pathlib.Path,required=True);p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args();commands=[]
def run(cmd):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True);commands.append(dict(command=list(map(str,cmd)),returncode=r.returncode,stdout=r.stdout,stderr=r.stderr));assert r.returncode==0,commands[-1]
with tempfile.TemporaryDirectory(prefix='chimp-clean-') as tmp:
 tmp=pathlib.Path(tmp)
 with tarfile.open(a.archive,'r:gz') as tar:
  seen=set()
  for member in tar.getmembers():
   rel=pathlib.PurePosixPath(member.name);assert not rel.is_absolute() and '..' not in rel.parts and (member.isfile() or member.islnk())
   if member.islnk():assert member.linkname in seen and '..' not in pathlib.PurePosixPath(member.linkname).parts and not pathlib.PurePosixPath(member.linkname).is_absolute()
   seen.add(member.name)
  tar.extractall(tmp)
 root=tmp;index=json.loads((root/'RELEASE_CONTENTS.json').read_text());actual={str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()};assert actual==set(index['files'])|{'RELEASE_CONTENTS.json'}
 for name,h in index['files'].items():assert sha((root/name).read_bytes())==h,name
 r=root/'ReWrite/chimp-family';s=root/'Source/chimp-family';build=tmp/'clean-build';installed=tmp/'installed'
 internal=json.loads((r/'validation/EVIDENCE_INDEX.json').read_text())
 for name,h in internal['files'].items():assert (root/name).is_file() and sha((root/name).read_bytes())==h,('internal evidence index',name)
 run(['cmake','-S',r,'-B',build,'-DCMAKE_BUILD_TYPE=Release']);run(['cmake','--build',build,'-j2']);run(['ctest','--test-dir',build,'--output-on-failure']);run(['cmake','--install',build,'--prefix',installed])
 run(['python',r/'tools/verify.py','--cli',installed/'bin/chimp_cli','--out',tmp/'clean-synthetic','--synthetic-only'])
 # Exact source patch replay. Algorithms are the original Java classes, with only frozen fixed-width infrastructure patch.
 patched=tmp/'patch-replay';shutil.copytree(s/'upstream',patched);run(['patch','-p1','-i',s/'PATCHES/fixed-width-oracle.patch','-d',patched])
 for original in (s/'upstream/src/main/java').rglob('*.java'):
  rel=original.relative_to(s/'upstream/src/main/java');assert sha((patched/'src/main/java'/rel).read_bytes())==sha((s/'oracle-src'/rel).read_bytes()),str(rel)
 baseline=r/'validation/qualified-v2';server=Server([installed/'bin/chimp_cli','server']);checked=set();cold=[]
 for line in (baseline/'cases.jsonl').read_text().splitlines():
  row=json.loads(line);m=row['method_id']
  if row['status']!='PASS' or m in checked:continue
  checked.add(m);b=gzip.decompress((baseline/'blobs'/(row['frame_sha256']+'.gz')).read_bytes());expected=gzip.decompress((baseline/'blobs'/(row['source_decoded_sha256']+'.gz')).read_bytes());status,out=server.call(4,m,b,row['count'],row['history'],row['epsilon']);assert status==0 and normalize(out,points=m>=7)==normalize(expected,points=m>=7);cold.append(dict(method=m,frame_sha256=row['frame_sha256'],pass_=True))
 server.close();assert len(checked)==11
 reproducible={}
 for file in ['bin/chimp_cli','lib/libchimp_family.so']:
  expected=sha((r/'dist/x86_64'/file).read_bytes());actual=sha((installed/file).read_bytes());reproducible[file]=dict(expected_sha256=expected,actual_sha256=actual,byte_identical=expected==actual);assert expected==actual,(file,expected,actual)
 # Installed public C++ consumer, independent of both Java and the source/build checkout.
 consumer=tmp/'consumer.cpp';consumer.write_text('#include <chimp_family.hpp>\nint main(){chimp::Config c{chimp::Method::ChimpN,128,0.1f};std::vector<std::uint64_t> v={1,2,3};return chimp::decode_frame(chimp::encode_frame(c,v)).words==v?0:1;}\n')
 run(['g++','-std=c++17',consumer,'-I'+str(installed/'include'),'-L'+str(installed/'lib'),'-Wl,-rpath,'+str(installed/'lib'),'-lchimp_family','-o',tmp/'consumer']);run([tmp/'consumer'])
 result=dict(status='PASS',archive_sha256=sha(a.archive.read_bytes()),indexed_files=len(index['files']),clean_synthetic=json.loads((tmp/'clean-synthetic/verification.json').read_text())['summary'],cold_decode=cold,reproducible_binaries=reproducible,patch_replay=True,installed_cpp_consumer=True,commands=commands)
 a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['commands','cold_decode']},indent=2))
