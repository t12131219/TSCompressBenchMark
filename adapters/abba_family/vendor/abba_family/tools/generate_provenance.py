"""Lock source/dependency licenses, patches, toolchains and build inputs."""
from pathlib import Path
import json,hashlib,difflib,subprocess,sys,platform,os
P=Path(__file__).resolve().parents[1];R=P.parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,j):p.write_text(json.dumps(j,indent=2,ensure_ascii=False)+'\n')
sources=[]
for a in ['abba','fabba','qabba']:
 base=R/'Source'/a;manifest=json.loads((base/'SOURCE_MANIFEST.json').read_text())
 for f in manifest['files']:
  path=base/'upstream'/f['path'];assert sha(path)==f['sha256'],path
 sources.append({'algorithm':a,'repository':manifest['repository'],'commit':manifest['commit'],'manifest_sha256':sha(base/'SOURCE_MANIFEST.json')})
# Source originals stay unchanged. Build/runtime caches are not source closure.
patches=[]
for old,new,name in [(R/'Source/abba/upstream/src/Ckmeans.1d.dp.cpp',P/'vendor/ckmeans/Ckmeans.1d.dp.cpp','ckmeans-safety.patch'),(R/'Source/abba-family-dependencies/nlohmann-json-3.11.3.hpp',P/'include/af_json.hpp','json-oom.patch')]:
 patch=P/'docs/patches'/name;patch.write_text(''.join(difflib.unified_diff(old.read_text().splitlines(True),new.read_text().splitlines(True),fromfile=str(old.relative_to(R)),tofile=str(new.relative_to(P)))));patches.append({'path':str(patch.relative_to(P)),'sha256':sha(patch),'before_sha256':sha(old),'after_sha256':sha(new)})
components=[{'name':'ABBA','version':sources[0]['commit'],'license':'MIT','role':'TRANSLATED pipeline'},{'name':'fABBA','version':sources[1]['commit'],'license':'BSD-3-Clause','role':'TRANSLATED pipeline'},{'name':'QABBA','version':sources[2]['commit'],'license':'MIT','role':'TRANSLATED pipeline'},{'name':'CKmeans','license':'MIT AND LGPL-3.0-or-later','role':'NATIVE_REUSE with safety patches','license_evidence':['Source/abba/upstream/LICENSE','Source/abba-family-dependencies/ckmeans-3.4.6-DESCRIPTION']},{'name':'nlohmann-json','version':'3.11.3','license':'MIT','role':'bundled native dependency with OOM destructor patch'},{'name':'numpy indirect quicksort/heapsort','version':'1.24.3','license':'BSD-3-Clause','role':'structured translation preserving ties'},{'name':'zlib','version':'1.2.13','license':'Zlib','role':'bundled native codec'},{'name':'zstd','version':'1.5.6','license':'BSD-3-Clause','role':'bundled native codec'},{'name':'bzip2','version':'1.0.8','license':'bzip2-1.0.6','role':'bundled native codec'},{'name':'liblzma','version':'5.2.5','license':'LicenseRef-Public-Domain','role':'bundled native codec; build scripts retain their separate notices'}]
files=[]
for sub in ['src','include','vendor','tools','tests','LICENSES']:
 for f in sorted((P/sub).rglob('*')):
  if not f.is_file() or '__pycache__' in f.parts:continue
  name=str(f.relative_to(P));lic='MIT';role='package implementation/test'
  if name.startswith('src/'):lic='MIT AND BSD-3-Clause';role='translated/reconstructed stage or native API'
  if name.startswith('vendor/ckmeans/'):lic='MIT AND LGPL-3.0-or-later';role='patched retained upstream kernel'
  elif name.startswith('vendor/zstd/'):lic='BSD-3-Clause OR GPL-2.0-only';role='unmodified upstream distribution; BSD option for linked sources'
  elif name.startswith('vendor/zlib/'):lic='Zlib';role='unmodified upstream source'
  elif name.startswith('vendor/bzip2/'):lic='bzip2-1.0.6';role='unmodified upstream source'
  elif name.startswith('vendor/xz/'):lic='LicenseRef-XZ-File-Notices';role='unmodified distribution; linked liblzma public domain; build utilities separate licenses'
  elif name=='include/af_json.hpp':lic='MIT';role='modified upstream native header'
  elif name.startswith('tests/data/'):lic='LicenseRef-Dataset-Provenance';role='test-only dataset excerpt; see DATASET_TEST_PLAN, no algorithm license claimed'
  files.append({'path':name,'bytes':f.stat().st_size,'sha256':sha(f),'license':lic,'role':role})
write(P/'docs/SBOM.json',{'format':'abba-family-sbom-v1','components':components,'sources':sources,'patches':patches,'files':files,'note':'Original embedded notices take precedence over directory summaries. See vendor/xz/COPYING for file-specific build-tool licenses; no xz CLI is linked.'})
urls={'zlib-1.2.13.tar.gz':'https://zlib.net/fossils/zlib-1.2.13.tar.gz','zstd-1.5.6.tar.gz':'https://github.com/facebook/zstd/releases/download/v1.5.6/zstd-1.5.6.tar.gz','bzip2-1.0.8.tar.gz':'https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz','xz-5.2.5.tar.gz':'https://tukaani.org/xz/xz-5.2.5.tar.gz','nlohmann-json-3.11.3.hpp':'https://raw.githubusercontent.com/nlohmann/json/v3.11.3/single_include/nlohmann/json.hpp','numpy-quicksort.cpp':'https://raw.githubusercontent.com/numpy/numpy/v1.24.3/numpy/core/src/npysort/quicksort.cpp','numpy-heapsort.h':'https://raw.githubusercontent.com/numpy/numpy/v1.24.3/numpy/core/src/npysort/npysort_heapsort.h'}
deps=R/'Source/abba-family-dependencies';write(deps/'DEPENDENCY_MANIFEST.json',{'files':[{'path':str(f.relative_to(deps)),'bytes':f.stat().st_size,'sha256':sha(f),'url':urls.get(f.name,'https://pypi.org/simple/' if f.suffix=='.whl' else 'upstream license/reference; see filename and SBOM')} for f in sorted(deps.rglob('*')) if f.is_file() and f.name!='DEPENDENCY_MANIFEST.json']})
versions={}
for tool in ['g++','gcc','clang++','cmake','make','ld','ar']:
 r=subprocess.run([tool,'--version'],capture_output=True,text=True);versions[tool]=r.stdout.split('\n')[0]
write(P/'docs/BUILD_TOOLCHAIN.json',{'versions':versions,'python':sys.version,'platform':platform.uname()._asdict(),'machine':platform.machine(),'source_date_epoch':'1789776000','flags':'C++17, binary64, -ffp-contract=off, no fast-math, prefix-map source/build paths; all codecs static PIC','environment':{'LANG':os.environ.get('LANG'),'LC_ALL':os.environ.get('LC_ALL'),'PATH':os.environ.get('PATH')},'cross_toolchain':'AF_ARM_ROOT; see validation/arm64 toolchain evidence'})
print('source manifests, patches, SBOM and toolchains locked')
