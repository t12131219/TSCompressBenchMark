#!/usr/bin/env python3
import argparse,hashlib,io,json,pathlib,tarfile,gzip
R=pathlib.Path(__file__).resolve().parents[1];ROOT=R.parent.parent
NAMES=['chimp-family','chimp','chimp32','chimpn','chimp128-no-index','chimpn32','fpc-chimp','pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized']
def files():
 for top in ['Source','ReWrite']:
  for name in NAMES:
   for p in sorted((ROOT/top/name).rglob('*')):
    if p.is_file() and '__pycache__' not in p.relative_to(ROOT/top/name).parts and p.relative_to(ROOT/top/name).parts[0]!='build':yield p
p=argparse.ArgumentParser();p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args();selected=list(files());contents={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in selected};index=dict(format='local research source rewrite archive v1',files=contents);index_bytes=(json.dumps(index,indent=2)+'\n').encode();a.out.parent.mkdir(parents=True,exist_ok=True)
with a.out.open('wb') as file:
 with gzip.GzipFile(filename='',mode='wb',fileobj=file,mtime=0) as gz:
  with tarfile.open(fileobj=gz,mode='w',format=tarfile.PAX_FORMAT) as tar:
   seen={}
   for f in selected:
    name=str(f.relative_to(ROOT));digest=contents[name];info=tarfile.TarInfo(name);info.mode=0o755 if f.stat().st_mode&0o111 else 0o644;info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
    if digest in seen:
     info.type=tarfile.LNKTYPE;info.linkname=seen[digest];info.size=0;tar.addfile(info)
    else:
     seen[digest]=name;data=f.read_bytes();info.size=len(data);tar.addfile(info,io.BytesIO(data))
   info=tarfile.TarInfo('RELEASE_CONTENTS.json');info.size=len(index_bytes);info.mode=0o644;info.mtime=0;info.uid=info.gid=0;info.uname=info.gname='';tar.addfile(info,io.BytesIO(index_bytes))
report=dict(path=str(a.out),sha256=hashlib.sha256(a.out.read_bytes()).hexdigest(),files=len(contents),unique_contents=len(seen),size=a.out.stat().st_size,storage='tar hardlinks deduplicate byte-identical immutable source/evidence files')
a.out.with_suffix(a.out.suffix+'.manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
