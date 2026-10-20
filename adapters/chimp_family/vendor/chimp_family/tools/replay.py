#!/usr/bin/env python3
import argparse,pathlib,json,gzip,time
from verify import Server,sha,normalize
p=argparse.ArgumentParser();p.add_argument('--baseline',type=pathlib.Path,required=True);p.add_argument('--cli',type=pathlib.Path,required=True);p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--first-natural-column',action='store_true');p.add_argument('--prefix',nargs=argparse.REMAINDER,default=[]);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
server=Server(a.prefix+[str(a.cli),'server']);rows=[];started=time.time()
def blob(h):
 b=gzip.decompress((a.baseline/'blobs'/(h+'.gz')).read_bytes());assert sha(b)==h;return b
for text in (a.baseline/'cases.jsonl').read_text().splitlines():
 r=json.loads(text)
 if r['status']!='PASS':continue
 if a.first_natural_column and r['kind']=='natural' and '_col1_' not in r['case']:continue
 m=r['method_id'];data=blob(r['input_sha256']);raw=blob(r['source_sha256']);frame=blob(r['frame_sha256']);expected=blob(r['source_decoded_sha256']);count=r['count'];n=r['history'];eps=r['epsilon']
 st,out=server.call(1,m,data,count,n,eps);assert not st and normalize(out,segments=m>=7)==normalize(raw,segments=m>=7),(r['case'],m,'encode')
 st,out=server.call(2 if m<7 else 5,m,raw if m<7 else data,count,n,eps);assert not st and normalize(out,points=m>=7)==normalize(expected,points=m>=7),(r['case'],m,'raw decode')
 st,out=server.call(3,m,data,count,n,eps);frame_identical=out==frame;assert not st and (frame_identical or (m>=7 and out[:32]==frame[:32] and normalize(out[32:-4],segments=True)==normalize(frame[32:-4],segments=True))),(r['case'],m,'frame equivalence')
 st,out=server.call(4,m,frame,count,n,eps);assert not st and normalize(out,points=m>=7)==normalize(expected,points=m>=7),(r['case'],m,'cold decode')
 rows.append(dict(case=r['case'],method=r['method'],method_id=m,count=count,input_sha256=r['input_sha256'],raw_identical=True,cross_decode=True,frame_identical=frame_identical,frame_semantic_equivalent=True))
server.close();report=dict(status='PASS',cases=len(rows),values=sum(r['count'] for r in rows),fail=0,elapsed_seconds=time.time()-started,selection='all synthetic/shared plus all rows first numeric column each natural dataset' if a.first_natural_column else 'all successful baseline cases',cli_sha256=sha(a.cli.read_bytes()),baseline_sha256=sha((a.baseline/'verification.json').read_bytes()),command=server.cmd,rows=rows)
(a.out/'replay.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='rows'},indent=2))
