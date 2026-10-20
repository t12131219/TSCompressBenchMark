#!/usr/bin/env python3
"""Fresh original Java source differential, persistent independent processes, hash-bound evidence."""
import argparse,csv,gzip,hashlib,json,math,os,pathlib,random,struct,subprocess,time
R=pathlib.Path(__file__).resolve().parents[1]; ROOT=R.parent.parent; S=ROOT/'Source/chimp-family'
NAMES={1:'chimp',2:'chimp32',3:'chimpn',4:'chimp128-no-index',5:'chimpn32',6:'fpc-chimp',7:'pmc-mr',8:'swing-filter',9:'swing-filter-disjoint',10:'swing-filter-disjoint-quantized',11:'swing-filter-disjoint-quantized.filter2'}
def sha(b):return hashlib.sha256(b).hexdigest()
def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
def u64(v):return struct.unpack('<Q',struct.pack('<d',v))[0]
def u32(v):return struct.unpack('<I',struct.pack('<f',v))[0]
def wbytes(values):return b''.join(struct.pack('<Q',v) for v in values)
def pbytes(values,times=None):return b''.join(struct.pack('<qf',i if times is None else times[i],v) for i,v in enumerate(values))
class Server:
 def __init__(self,cmd):self.cmd=list(map(str,cmd));self.proc=subprocess.Popen(self.cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
 def call(self,mode,method,data,count,n=128,eps=.1):
  hdr=struct.pack('<IIIfII',mode,method,n,eps,count,len(data));self.proc.stdin.write(hdr+data);self.proc.stdin.flush();head=self.proc.stdout.read(8)
  if len(head)!=8:raise RuntimeError('server died: '+str(self.cmd))
  status,length=struct.unpack('<II',head);out=self.proc.stdout.read(length)
  if len(out)!=length:raise RuntimeError('short server reply')
  return status,out
 def close(self):
  self.proc.stdin.close();code=self.proc.wait(timeout=15)
  if code:raise RuntimeError(('server exit',self.cmd,code))
def normalize(b,segments=False,points=False):
 # Java FP does not specify NaN payload/sign. Lossless raw paths never normalize here.
 b=bytearray(b)
 if segments:
  for pos in range(0,len(b),52):
   for offset in [16,24,32,40]:
    v=struct.unpack_from('<d',b,pos+offset)[0]
    if math.isnan(v):struct.pack_into('<Q',b,pos+offset,0x7ff8000000000000)
   if math.isnan(struct.unpack_from('<f',b,pos+48)[0]):struct.pack_into('<I',b,pos+48,0x7fc00000)
 if points:
  for pos in range(0,len(b),12):
   if math.isnan(struct.unpack_from('<f',b,pos+8)[0]):struct.pack_into('<I',b,pos+8,0x7fc00000)
 return bytes(b)
def load_shared(root):
 index=json.loads((root/'index.json').read_text()); selected=[]
 for e in index['entries']:
  if len(e['shape'])!=1 or e['n_rows']>1025 or e['buffer_count']!=1:continue
  if 'float32' not in e['path'] and 'float64' not in e['path']:continue
  if not (e['group']=='length_extrema' or e['group']=='boundary_n2' or e['group']=='source_domain'):continue
  b=(root/e['path']).read_bytes();assert sha(b)==e['file_sha256']
  version,meta_len,buffers=struct.unpack_from('<IQI',b,8);assert version==1 and buffers==1
  meta=json.loads(b[24:24+meta_len]);p=24+meta_len;name_len,len_=struct.unpack_from('<HQ',b,p);p+=10;name=b[p:p+name_len].decode();p+=name_len;raw=b[p:p+len_];assert p+len_==len(b)
  desc=meta['buffers'][0];assert sha(raw)==desc['payload_sha256']
  if desc['dtype'] not in ['<f4','<f8']:continue
  dtype='f32' if desc['dtype']=='<f4' else 'f64';words=list(struct.unpack('<'+('I' if dtype=='f32' else 'Q')*(len(raw)//(4 if dtype=='f32' else 8)),raw))
  selected.append((e,dtype,words))
 return selected
class Evidence:
 def __init__(self,out):self.out=out;self.blobs=out/'blobs';self.blobs.mkdir(parents=True,exist_ok=True);self.rows=[];self.log=(out/'cases.jsonl').open('w');self.started=time.time()
 def blob(self,b):
  h=sha(b);p=self.blobs/(h+'.gz')
  if not p.exists():p.write_bytes(gzip.compress(b,mtime=0))
  return h
 def row(self,row):self.rows.append(row);self.log.write(json.dumps(row,separators=(',',':'))+'\n');self.log.flush()
def run(a):
 out=a.out;out.mkdir(parents=True,exist_ok=False);ev=Evidence(out);classes=out/'java-classes';classes.mkdir();sources=sorted((S/'oracle-src').rglob('*.java'));compile_cmd=['javac','-d',str(classes)]+list(map(str,sources));cp=subprocess.run(compile_cmd,capture_output=True,text=True);(out/'javac.log').write_text(cp.stdout+cp.stderr);cp.check_returncode()
 java=Server(['java','-Xmx512m','-cp',classes,'Oracle']);cpp=Server(a.prefix+[str(a.cli),'server'])
 def case(label,method,data,count,n=128,eps=.1,kind='synthetic',extra=None):
  row=dict(case=label,method=NAMES[method],method_id=method,count=count,history=n,epsilon=f32(eps),kind=kind,input_sha256=ev.blob(data),oracle_status=None,cpp_status=None,status='RUNNING');row.update(extra or {})
  st,source=java.call(1,method,data,count,n,eps);ct,target=cpp.call(1,method,data,count,n,eps);row.update(oracle_status=st,cpp_status=ct,source_sha256=ev.blob(source),cpp_sha256=ev.blob(target))
  if st or ct:
   row.update(status='EXPECTED_SOURCE_DOMAIN_REJECTION' if st and ct and ((method==8 and count<2) or (method in [9,10,11] and count==0)) else 'FAIL',source_error=source.decode(errors='replace') if st else None,cpp_error=target.decode(errors='replace') if ct else None);ev.row(row)
   if row['status']=='FAIL':raise AssertionError(row)
   return
  identical=source==target if method<7 else normalize(source,segments=True)==normalize(target,segments=True)
  row['source_equivalent']=identical
  if not identical:row['status']='FAIL_RAW';ev.row(row);raise AssertionError(row)
  if method<7:
   jj,jjdata=java.call(2,method,source,count,n,eps);cc,ccdata=cpp.call(2,method,target,count,n,eps);jc,jcdata=cpp.call(2,method,source,count,n,eps);cj,cjdata=java.call(2,method,target,count,n,eps)
   expected=data
   if method==6:expected=wbytes([0x7ff8000000000000 if (w&0x7ff0000000000000)==0x7ff0000000000000 and w&0xfffffffffffff else w for (w,) in struct.iter_unpack('<Q',data)])
   assert not(jj or cc or jc or cj) and jjdata==ccdata==jcdata==cjdata==expected,(label,method,'four-way decode')
   row.update(source_decoded_sha256=ev.blob(jjdata),cpp_decoded_sha256=ev.blob(ccdata),cross_decode=True,bit_exact=(expected==data),source_nan_canonicalization=(expected!=data))
  else:
   js,jd=java.call(5,method,data,count,n,eps);cs,cd=cpp.call(5,method,data,count,n,eps);assert not(js or cs),(label,method,'lossy decode',jd,cd)
   assert normalize(jd,points=True)==normalize(cd,points=True),(label,method,'lossy float values')
   row.update(source_decoded_sha256=ev.blob(jd),cpp_decoded_sha256=ev.blob(cd),decoded_equal=True)
   original=list(struct.iter_unpack('<qf',data));decoded=dict(struct.iter_unpack('<qf',cd));errors=[]
   for i,(t,v) in enumerate(original):errors.append(abs(v-decoded[i if method==10 else t]))
   nonfinite=sum(not math.isfinite(e) for e in errors);maxerr=max((e for e in errors if math.isfinite(e)),default=0);violations=sum(not math.isfinite(e) or e>f32(eps) for e in errors)
   row.update(nonfinite=nonfinite,max_absolute_error='nonfinite' if nonfinite else maxerr,absolute_epsilon_pass=violations==0,epsilon_violations=violations)
   # strict mode cannot silently emit a failing frame; preserve raw source variant separately.
   strict,strictbytes=cpp.call(6,method,data,count,n,eps);assert strict==(1 if violations else 0),(label,'strict quality status')
   row['strict_mode_matches_measured_quality']=True
  fs,frame=cpp.call(3,method,data,count,n,eps);assert fs==0,(label,'frame encoding',frame)
  ds,decoded=cpp.call(4,method,frame,count,n,eps);assert ds==0,(label,'cold frame decode',decoded)
  assert normalize(decoded,points=method>=7)==normalize(ccdata if method<7 else cd,points=method>=7)
  row.update(frame_sha256=ev.blob(frame),frame_bits=8*len(frame),payload_bits=8*len(target),metadata_bits=256,checksum_bits=32,final_bits_closure=(len(frame)==36+len(target)),status='PASS')
  ev.row(row)
 rng=random.Random(612793)
 for dtype,methods,w in [('f64',[1,3,4,6],64),('f32',[2,5],32)]:
  special=[0,1,(1<<(w-1)),(1<<(w-1))|1,0x7ff0000000000000 if w==64 else 0x7f800000,0xfff0000000000000 if w==64 else 0xff800000,0x7ff8000000000001 if w==64 else 0x7fc00001]
  for profile,count in [('empty',0),('single',1),('two',2),('special',len(special)),('random',31),('random',511),('random',512),('random',513),('repeat',999),('repeat',1000),('repeat',1001)]:
   words=special if profile=='special' else [42 if profile=='repeat' else rng.getrandbits(w) for _ in range(count)];data=wbytes(words)
   for method in methods:case(dtype+'_'+profile+'_'+str(count),method,data,count)
  for n in [1,2,4,8,16,32,64,128,256,512,1024,65536]:
   words=[u64(math.sin(i*.1)) if w==64 else u32(math.sin(i*.1)) for i in range(515 if n<65536 else 3)]
   for method in ([3,4] if w==64 else [5]):case(dtype+'_ring_'+str(n),method,wbytes(words),len(words),n=n)
 for dtype,methods,w in [('f64',[1,3,4,6],64),('f32',[2,5],32)]:
  words=[]
  for bit in range(w):words.extend([0,1<<bit,(1<<bit)-1,((1<<w)-1)^(1<<bit)])
  for method in methods:case(dtype+'_all_bit_boundaries',method,wbytes(words),len(words))
 for method in [7,8,9,10,11]:
  vectors=[('signed_zero',[-0.0,0.0,-0.0],None),('single',[1.0],None),('two',[1.,1.25],None),('constant',[2.]*512,None),('sin',[f32(math.sin(i*.05)) for i in range(515)],None),('spike',[0.,0.,100.,0.,0.,200.],None),('negative',[-3.,-2.,-4.,-1.,0.],None),('quant_ties',[.1,.2,.3,-.1,-.2,-.3],None),('irregular',[1.,2.,3.,1.],[-10,-7,-3,3]),('large_time',[1.,2.,1.,3.],[10**15+i for i in range(4)])]
  for label,vals,times in vectors:
   for eps in [.01,.1,1.]:case('lossy_'+label,method,pbytes(vals,times),len(vals),eps=eps)
 # Source original fixed-buffer overflow is tested explicitly, separate from algorithm parity.
 for method,w in [(1,64),(2,32),(3,64),(4,64),(5,32)]:
  words=[rng.getrandbits(w) for _ in range(1500)];data=wbytes(words);st,msg=java.call(1,method,data,len(words));ct,raw=cpp.call(1,method,data,len(words));assert not ct and (st or (raw!=msg and len(msg)>{1:8000,2:5000,3:8000,4:8000,5:4000}[method])),(method,st,ct,len(msg),len(raw))
  assert cpp.call(2,method,raw,len(words))==(0,data)
  ev.row(dict(case='original_fixed_array_overflow',method=NAMES[method],method_id=method,count=len(words),kind='source-defect',status='EXPECTED_SOURCE_CAPACITY_DEFECT',input_sha256=ev.blob(data),source_error=msg.decode(errors='replace') if st else 'source swallowed bitstream write exceptions and returned an over-capacity zero-padded array',source_sha256=ev.blob(msg),source_status=st,source_payload_size=len(msg),cpp_sha256=ev.blob(raw),cpp_roundtrip=cpp.call(2,method,raw,len(words))[1]==data))
 if not a.synthetic_only:
  shared=load_shared(a.shared);(out/'shared-selection.json').write_text(json.dumps(dict(index_sha256=sha((a.shared/'index.json').read_bytes()),entries=[e for e,_,_ in shared]),indent=2))
  for e,dtype,words in shared:
   for start in range(0,max(1,len(words)),512):
    block=words[start:start+512]
    for method in ([1,3,4,6] if dtype=='f64' else [2,5]):
     sentinel=0x7ff8000000000000 if dtype=='f64' else 0x7fc00000
     if method!=6 and sentinel in block:
      ev.row(dict(case=e['key']+str(start),method=NAMES[method],method_id=method,count=len(block),kind='shared',status='EXPECTED_RESERVED_EOF_REJECTION',input_sha256=ev.blob(wbytes(block)),dataset_id=e['dataset_id']));assert cpp.call(1,method,wbytes(block),len(block))[0]==1;continue
     case(e['key']+'_'+str(start),method,wbytes(block),len(block),kind='shared',extra=dict(dataset_id=e['dataset_id']))
  (out/'natural-selection.json').write_text(json.dumps(dict(files=[dict(name=f,sha256=sha((a.corpus/f).read_bytes())) for f in ['ETTh1.csv','ETTh2.csv','exchange_rate.csv','national_illness.csv']]),indent=2))
  for filename in ['ETTh1.csv','ETTh2.csv','exchange_rate.csv','national_illness.csv']:
   with (a.corpus/filename).open() as f:
    reader=csv.reader(f);header=next(reader);columns=[[] for _ in header[1:]]
    for row in reader:
     for c,v in zip(columns,row[1:]):c.append(float(v))
   for col_index,col in enumerate(columns):
    for start in range(0,len(col),512):
     vals=col[start:start+512];count=len(vals);label=filename+'_col'+str(col_index+1)+'_offset'+str(start)
     for method in range(1,7):case(label,method,wbytes([u32(v) if method in [2,5] else u64(v) for v in vals]),count,kind='natural',extra=dict(column=header[col_index+1],offset=start))
     for method in range(7,12):
      for eps in [.01,.1,1.]:case(label,method,pbytes(vals),count,eps=eps,kind='natural',extra=dict(column=header[col_index+1],offset=start))
   print('verified',filename,'cases',len(ev.rows),flush=True)
 java.close();cpp.close();ev.log.close();summary=dict(cases=len(ev.rows),pass_cases=sum(x['status']=='PASS' for x in ev.rows),expected_rejections=sum(x['status']!='PASS' for x in ev.rows),values=sum(x['count'] for x in ev.rows),fail=0,elapsed_seconds=time.time()-ev.started,by_method={})
 for method,name in NAMES.items():
  rows=[x for x in ev.rows if x['method_id']==method];good=[x for x in rows if x['status']=='PASS'];summary['by_method'][name]=dict(cases=len(rows),pass_cases=len(good),quality_failed_cases=sum(x.get('absolute_epsilon_pass')==False for x in good),nonfinite_cases=sum(x.get('nonfinite',0)>0 for x in good),source_equivalent=sum(x.get('source_equivalent',False) for x in good))
 manifest=dict(summary=summary,cli_sha256=sha(a.cli.read_bytes()),source_manifest_sha256=sha((S/'SOURCE_MANIFEST.yaml').read_bytes()),contract_sha256=sha((R/'contract.md').read_bytes()),case_index_sha256=sha((out/'cases.jsonl').read_bytes()),commands=dict(javac=compile_cmd,oracle=java.cmd,cpp=cpp.cmd),environment=dict(java=subprocess.run(['java','-version'],capture_output=True,text=True).stderr,python=os.sys.version),verifier_sha256=sha(pathlib.Path(__file__).read_bytes()),source_files=[dict(path=str(p.relative_to(S)),sha256=sha(p.read_bytes())) for p in sources])
 (out/'verification.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps(summary,indent=2))
def main():
 p=argparse.ArgumentParser();p.add_argument('--cli',type=pathlib.Path,required=True);p.add_argument('--out',type=pathlib.Path,required=True);p.add_argument('--synthetic-only',action='store_true');p.add_argument('--shared',type=pathlib.Path,default=ROOT/'Dataset_Verify');p.add_argument('--corpus',type=pathlib.Path,default=ROOT.parent/'材料/TSBench_Corpus');p.add_argument('--prefix',nargs=argparse.REMAINDER,default=[]);run(p.parse_args())
if __name__=='__main__':main()
