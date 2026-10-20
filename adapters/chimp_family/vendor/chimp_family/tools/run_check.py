#!/usr/bin/env python3
import argparse,subprocess,pathlib,time,json,hashlib
p=argparse.ArgumentParser();p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args();a.out.parent.mkdir(parents=True,exist_ok=True);t=time.time()
with a.out.open('w') as f:r=subprocess.run(a.command,stdout=f,stderr=subprocess.STDOUT)
report=dict(command=a.command,returncode=r.returncode,elapsed_seconds=time.time()-t,log_sha256=hashlib.sha256(a.out.read_bytes()).hexdigest());a.out.with_suffix(a.out.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(r.returncode)
