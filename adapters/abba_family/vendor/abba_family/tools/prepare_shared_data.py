import json,hashlib,struct
from pathlib import Path
p=Path(__file__).resolve().parents[1];root=p.parents[1];index=root/'Dataset_Verify/index.json';idx=json.loads(index.read_text());entries=[];out=[]
for e in idx['entries']:
 if e['category']!='without_timestamp_univariate' or e['group']!='main' or e['n_rows']>1024 or 'float64' not in e['path']:continue
 if len(entries)>=12:break
 data=(root/'Dataset_Verify'/e['path']).read_bytes();assert hashlib.sha256(data).hexdigest()==e['file_sha256'];assert data[:8]==b'TSCB2\0\0\0';version,msz,nbuf=struct.unpack_from('<IQI',data,8);meta=json.loads(data[24:24+msz]);pos=24+msz
 for _ in range(nbuf):
  ns,n=struct.unpack_from('<HQ',data,pos);pos+=10;name=data[pos:pos+ns].decode();pos+=ns;raw=data[pos:pos+n];pos+=n
  spec=next(b for b in meta['buffers'] if b['name']==name);assert hashlib.sha256(raw).hexdigest()==spec['payload_sha256']
  if name.startswith('value/'):
   assert spec['dtype']=='<f8';values=list(struct.unpack('<'+'d'*(n//8),raw));out.append(values)
 assert pos==len(data);entries.append(e)
(p/'tests/data/shared-float64.json').write_text(json.dumps(out)+'\n');plan=json.loads((p/'docs/DATASET_TEST_PLAN.json').read_text());plan['shared_corpus']={'relative_root':'../../Dataset_Verify','index_sha256':hashlib.sha256(index.read_bytes()).hexdigest(),'selection':'All four main-profile 4KiB entries without timestamp, univariate float64 n512; no cast/normalization. IEEE extrema fixtures audited separately as unsupported numerical overflow.','entries':entries,'frozen':'tests/data/shared-float64.json'};plan['fit_policy']='Per-object adaptive codebook learned only from the encoded input, fully serialized; no corpus model or TEST-based tuning. Frozen-model reuse separately uses TRAIN fit and TEST transform.';(p/'docs/DATASET_TEST_PLAN.json').write_text(json.dumps(plan,indent=2)+'\n');print(len(out),[len(v) for v in out])
