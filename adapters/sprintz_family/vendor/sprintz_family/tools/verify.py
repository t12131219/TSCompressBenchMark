#!/usr/bin/env python3
from pathlib import Path
import ctypes as C,json,random,subprocess,tempfile,hashlib,argparse,csv,struct,shutil,time
p=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--build',default='build');ap.add_argument('--oracle',default='build-baseline/sprintz_oracle');ap.add_argument('--report',default='differential.json');ap.add_argument('--frozen-data',action='store_true');args=ap.parse_args()
class Config(C.Structure):_fields_=[(k,C.c_uint32) for k in ['width','predictor','huffman','path','ndims']]
lib=C.CDLL(str(p/args.build/'libsprintz.so'))
lib.sz_encode.argtypes=[C.POINTER(Config),C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
lib.sz_decode.argtypes=[C.POINTER(Config),C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
def encode(c,data):
 out=C.create_string_buffer(300000);n=C.c_size_t();rc=lib.sz_encode(C.byref(c),data,len(data),out,len(out),C.byref(n));assert rc==0,(list(c),len(data),rc);return out.raw[:n.value]
def decode(c,data,expected):
 out=C.create_string_buffer(expected+1);n=C.c_size_t();rc=lib.sz_decode(C.byref(c),data,len(data),expected,out,expected,C.byref(n));return rc,out.raw[:n.value]
Config.__iter__=lambda self:iter(getattr(self,k) for k,_ in self._fields_)
rng=random.Random(171017);rows=[];bugs=[]
with tempfile.TemporaryDirectory(prefix='szverify-') as td:
 t=Path(td)
 for bits in [8,16]:
  for fire in [0,1]:
   for h in [0,1]:
    for d in [1,2,3,4,5,8,17,32,128]:
     for path in [0,1,2,3,4,5]:
      if (path==2 and d>(4 if bits==8 else 2)) or (path in [3,4] and fire) or (path==5 and (bits!=8 or not fire)):continue
      for pattern in ['random','zero','ramp']:
       n=1025;data=bytes(rng.randrange(256) if pattern=='random' else 0 if pattern=='zero' else i//17%256 for i in range(n*(bits//8)))
       c=Config(bits,fire,h,path,d);enc=encode(c,data);rc,dec=decode(c,enc,len(data));assert rc==0 and dec==data,(list(c),pattern,rc)
       (t/'in').write_bytes(data)
       opts=[str(bits),str(fire),str(h),str(path),str(d)]
       def oracle(op,fi,fo):
        q=subprocess.run([str(p/args.oracle),op]+opts+[str(t/fi),str(t/fo),str(len(data))],capture_output=True);assert q.returncode==0,(q.returncode,q.stderr.decode());return (t/fo).read_bytes()
       orig=oracle('enc','in','source');same=orig==enc
       rc,refdec=decode(c,orig,len(data));fromsource=rc==0 and refdec==data
       (t/'port').write_bytes(enc);cross=oracle('dec','port','decoded')==data
       assert cross
       repaired=False
       if bits==16 and not h and not same:
        plus=oracle('enc16plus','in','sourceplus');assert plus==enc,(list(c),len(orig),len(enc));repaired=True
        assert not fromsource
       else:assert same and fromsource,(list(c),pattern,len(orig),len(enc),rc)
       row={'config':list(c),'pattern':pattern,'source_bytes':len(orig),'port_bytes':len(enc),'byte_identical':same,'source_to_port':fromsource,'port_to_source':cross,'source_truncated_16b':repaired,'input_sha256':hashlib.sha256(data).hexdigest(),'encoded_sha256':hashlib.sha256(enc).hexdigest()};rows.append(row)
 # Real integer channels: losslessly select original count fields, no quantization.
 real=Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus/national_illness.csv')
 manifest=p/'tests/data/real_manifest.json'
 if real.exists() and not args.frozen_data:
  columns=['AGE 0-4','AGE 5-24','NUM. OF PROVIDERS'];vals=[]
  with real.open() as f:
   for row in csv.DictReader(f):
    for k in columns:
     v=int(row[k]);assert str(v)==row[k] and 0<=v<=65535;vals.append(v)
  data=struct.pack('<'+'H'*len(vals),*vals)
  origin={'source':str(real),'source_sha256':hashlib.sha256(real.read_bytes()).hexdigest(),'columns':columns,'rows':len(vals)//3,'mapping':'CSV exact integer -> u16 little endian, row-major selected three columns; reshape d1/d2 preserves flat sequence','payload_sha256':hashlib.sha256(data).hexdigest()}
  if manifest.exists():assert origin==json.loads(manifest.read_text()),'Real data provenance changed'
  manifest.write_text(json.dumps(origin,indent=2)+'\n')
 else:
  origin=json.loads(manifest.read_text());data=(p/'tests/data/national_illness_counts.u16le').read_bytes()
  assert hashlib.sha256(data).hexdigest()==origin['payload_sha256']
 realrows=[]
 (p/'tests/data/national_illness_counts.u16le').write_bytes(data)
 for d in [1,2,3]:
  for fire in [0,1]:
   for h in [0,1]:
    c=Config(16,fire,h,0,d);enc=encode(c,data);rc,dec=decode(c,enc,len(data));assert rc==0 and dec==data
    opts=['16',str(fire),str(h),'0',str(d)];(t/'port').write_bytes(enc);(t/'in').write_bytes(data)
    original=oracle('enc','in','source');cross=oracle('dec','port','decoded')==data;assert cross
    realrows.append({'config':list(c),'raw_bytes':len(data),'compressed_bytes':len(enc),'port_to_source':cross,'source_byte_identical':original==enc})
 provenance={**origin,'provenance_mode':'LOCAL_SOURCE_READ' if real.exists() and not args.frozen_data else 'FROZEN_EXTRACT_REPLAY','results':realrows}
 (p/'evidence/real-data.json').write_text(json.dumps(provenance,indent=2)+'\n')
(p/'evidence'/args.report).write_text(json.dumps({'seed':171017,'cases':len(rows),'source_16b_truncations':sum(x['source_truncated_16b'] for x in rows),'results':rows},indent=2)+'\n')
print(json.dumps({'cases':len(rows),'source_16b_truncations':sum(x['source_truncated_16b'] for x in rows),'real_cases':len(realrows),'status':'PASS'}))
