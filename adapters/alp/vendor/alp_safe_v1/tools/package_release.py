#!/usr/bin/env python3
"""Create deterministic complete standalone source/evidence archive (no build cache)."""
import argparse,gzip,hashlib,json,pathlib,tarfile
ROOT=pathlib.Path(__file__).resolve().parents[1]
ASSETS=ROOT.parents[1]
EXCLUDE=['build/','reports/verification/','reports/profiles-clang/','reports/profiles-arm64/']
def selected():
    for start in [ASSETS/'Source/alp-cwida', ROOT]:
        for f in sorted(start.rglob('*')):
            if not f.is_file() or '__pycache__' in f.parts:continue
            if start==ROOT and any(str(f.relative_to(ROOT)).startswith(x) for x in EXCLUDE):continue
            yield f
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args();a.out.parent.mkdir(parents=True,exist_ok=True)
    files=list(selected());index={str(f.relative_to(ASSETS)):sha(f) for f in files}
    with a.out.open('wb') as out:
        with gzip.GzipFile(fileobj=out,mode='wb',filename='',mtime=0) as z:
            with tarfile.open(fileobj=z,mode='w',format=tarfile.PAX_FORMAT) as t:
                for f in files:
                    item=t.gettarinfo(str(f),arcname=str(f.relative_to(ASSETS)));item.uid=item.gid=0;item.uname=item.gname='';item.mtime=0
                    with f.open('rb') as r:t.addfile(item,r)
    manifest={'archive':a.out.name,'sha256':sha(a.out),'bytes':a.out.stat().st_size,'file_count':len(files),'files':index,'standard':'v3.0','route':'NATIVE_PORT','scope':'ALP and ALP-RD native safe-v1 bounded profile; no FULL_PARITY/Bench/FORMAL claim','source_commit':'31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce'}
    a.out.with_suffix(a.out.suffix+'.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    a.out.with_suffix(a.out.suffix+'.sha256').write_text(manifest['sha256']+'  '+a.out.name+'\n')
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'}))
if __name__=='__main__':main()
