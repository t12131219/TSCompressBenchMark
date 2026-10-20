#!/usr/bin/env python3
import argparse,pathlib,json,random,struct,time
from verify import Server,wbytes,sha
p=argparse.ArgumentParser();p.add_argument('--cli',type=pathlib.Path,required=True);p.add_argument('--classes',type=pathlib.Path,required=True);p.add_argument('--out',type=pathlib.Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
j=Server(['java','-Xmx512m','-cp',a.classes,'Oracle']);c=Server([a.cli,'server']);rng=random.Random(8811);rows=[]
for trial,chunk in enumerate([1,2,3,7,31,511,512,1001]):
 assert j.call(9,6,b'',0)==c.call(9,6,b'',0)==(0,b'')
 total=4097 if chunk<7 else 70001
 all_source=bytearray();all_cpp=bytearray();input_=bytearray()
 for start in range(0,total,chunk):
  words=[rng.getrandbits(64) for _ in range(min(chunk,total-start))];words=[w if w&0x7ff0000000000000!=0x7ff0000000000000 else 42 for w in words];data=wbytes(words);input_+=data
  js,jraw=j.call(7,6,data,len(words));cs,craw=c.call(7,6,data,len(words));assert not(js or cs) and jraw==craw
  # persistent decoders cross directions, including odd-call padding.
  jd,jout=j.call(8,6,craw,len(words));cd,cout=c.call(8,6,jraw,len(words));assert not(jd or cd) and jout==cout==data
  all_source+=jraw;all_cpp+=craw
 rows.append(dict(chunk=chunk,count=total,input_sha256=sha(input_),source_raw_sha256=sha(all_source),cpp_raw_sha256=sha(all_cpp),source_equivalent=True,cross_decode=True))
helpers=[]
for w in [0,1,255,256,0x010203,0xffffff,0x1000000,0x100000000,0x10000000000,0xffffffffffffffff]:
 js,jraw=j.call(11,6,wbytes([w]),1);cs,craw=c.call(11,6,wbytes([w]),1);assert not(js or cs) and jraw==craw
 js,jout=j.call(10,6,jraw,1);cs,cout=c.call(10,6,craw,1);assert not(js or cs) and jout==cout==wbytes([w])
 helpers.append(dict(word=str(w),bytes_hex=jraw.hex(),pass_=True))
j.close();c.close();report=dict(status='PASS',rows=rows,helpers=helpers,values=sum(x['count'] for x in rows),cli_sha256=sha(a.cli.read_bytes()),scope='FPC continuous predictor state across odd/even compress/decompress calls; reset before each series; >65536 updates exercise table replacement')
(a.out/'state.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
