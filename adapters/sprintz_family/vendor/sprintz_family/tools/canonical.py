from pathlib import Path
import json,struct,hashlib,ctypes as C,sys
p=Path(__file__).resolve().parents[1];sys.path.insert(0,str(p/'tools'))
class Config(C.Structure):_fields_=[(k,C.c_uint32) for k in ['width','predictor','huffman','path','ndims']]
lib=C.CDLL(str(p/'build/libsprintz.so'))
lib.sz_encode.argtypes=[C.POINTER(Config),C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
lib.sz_decode.argtypes=[C.POINTER(Config),C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
shared=p.parent.parent/'Dataset_Verify';index=json.loads((shared/'index.json').read_text());entries=index['entries'] if 'entries' in index else index['datasets']
rows=[];fixtures=[];(p/'tests/data/canonical').mkdir(parents=True,exist_ok=True)
for en in entries:
 if not (en['key'].startswith('dv_source_sprintz') or 'boundary' in en['path']):continue
 f=shared/en['path'];b=f.read_bytes()
 if b[:8]!=b'TSCB2\x00\x00\x00':continue
 assert hashlib.sha256(b).hexdigest()==en['file_sha256'],'Canonical transport hash mismatch'
 version,msz,nbuf=struct.unpack_from('<IQI',b,8);meta=json.loads(b[24:24+msz]);pos=24+msz;payloads=[]
 for i in range(nbuf):
  ns,z=struct.unpack_from('<HQ',b,pos);pos+=10;name=b[pos:pos+ns].decode();pos+=ns;data=b[pos:pos+z];pos+=z;payloads.append((name,data))
 values=[(m,data) for m,(name,data) in zip(meta['buffers'],payloads) if name.startswith('value/')]
 if len(values)!=1:continue
 m,data=values[0];assert hashlib.sha256(data).hexdigest()==m['payload_sha256'],'Canonical payload hash mismatch'
 dt=m['dtype'];shape=m['shape']
 if dt not in ['|u1','|i1','<u2','<i2'] or len(data)>65536:continue
 d=1
 for k in shape[1:]:d*=k
 if not 1<=d<=128:continue
 if not (en['key'].startswith('dv_source_sprintz') or 'boundary' in en['path']):continue
 bits=8 if dt.endswith('1') else 16
 dest='tests/data/canonical/'+en['key']+'.bin';(p/dest).write_bytes(data)
 fixtures.append({'key':en['key'],'dataset_id':en['dataset_id'],'source_file':en['path'],'source_file_sha256':hashlib.sha256(b).hexdigest(),'payload_file':dest,'payload_sha256':hashlib.sha256(data).hexdigest(),'dtype':dt,'shape':shape,'ndims':d,'bytes':len(data)})
 for fire in [0,1]:
  for h in [0,1]:
   c=Config(bits,fire,h,0,d);enc=C.create_string_buffer(300000);out=C.create_string_buffer(len(data)+1);n=C.c_size_t();z=C.c_size_t()
   rc=lib.sz_encode(C.byref(c),data,len(data),enc,len(enc),C.byref(z));assert rc==0,(en['key'],rc)
   rc=lib.sz_decode(C.byref(c),enc,z.value,len(data),out,len(data),C.byref(n));assert rc==0 and n.value==len(data) and out.raw[:n.value]==data
   rows.append({'key':en['key'],'config':[bits,fire,h,0,d],'bytes':len(data),'encoded_bytes':z.value,'encoded_sha256':hashlib.sha256(enc.raw[:z.value]).hexdigest()})
(p/'tests/data/canonical_manifest.json').write_text(json.dumps(fixtures,indent=2)+'\n')
(p/'evidence/canonical.json').write_text(json.dumps({'fixtures':len(fixtures),'cases':len(rows),'results':rows},indent=2)+'\n')
print(json.dumps({'fixtures':len(fixtures),'cases':len(rows),'status':'PASS'}))
