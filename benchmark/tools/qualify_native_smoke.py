import json,time,pathlib
import numpy as np
from tsbench.registry import Registry
from tsbench.build import build_codec
from tsbench.bridges import create_bridge
root=pathlib.Path(__file__).resolve().parents[2]
rows=[]
for spec in Registry(root).list(include_reference=False):
 start=time.monotonic()
 try:
  record=build_codec(root,spec.key)
  print(spec.key,'BUILD ok',round(time.monotonic()-start,2),flush=True)
  n=max(65,spec.document['input'].get('min_n',0))
  dtype=np.dtype(spec.dtypes[0])
  if spec.key in ['abba','fabba']:
   a=(np.sin(np.arange(n)/8)+np.arange(n)/10).astype(dtype)
  elif spec.key in ['deepzip','dzip']:
   a=(np.arange(n)%4).astype(dtype)
  elif dtype.kind=='f':
   a=(np.arange(n)%8/4).astype(dtype)
  else:
   a=(np.arange(n)%17).astype(dtype)
  b=create_bridge(root,spec.key)
  params=Registry(root).resolve_params(spec.key,{})
  p=b.encode(a,params)
  v=b.decode(p,a.dtype,a.shape,params)
  if spec.loss_mode=='LOSSLESS':
   equal=a.tobytes()==v.tobytes()
  elif spec.loss_mode=='ERROR_BOUNDED_LOSSY':
   equal=bool(np.max(np.abs(a.astype(np.float64)-v.astype(np.float64)))<=float(params['error_bound']))
  else:
   equal=bool(v.shape==a.shape and np.isfinite(v).all())
  if not equal:raise RuntimeError('decoded output violates loss contract')
  row={'codec':spec.key,'status':'ok','build_id':record['build_id'],'artifact_sha256':record['artifact_sha256'],'dtype':dtype.str,'n':n,'payload_bytes':len(p),'elapsed_seconds':round(time.monotonic()-start,2)}
  print(spec.key,'ROUNDTRIP ok',len(p),flush=True)
 except Exception as e:
  row={'codec':spec.key,'status':getattr(e,'status','error'),'error':str(e),'elapsed_seconds':round(time.monotonic()-start,2)}
  print(spec.key,'FAIL',str(e),flush=True)
 rows.append(row)
 (root/'build/tsbench').mkdir(parents=True,exist_ok=True)
 (root/'build/tsbench/native_roundtrip.json').write_text(json.dumps({'schema_version':'tsbench.native-roundtrip.v1','records':rows},indent=2)+'\n')
print('COMPLETE',sum(r['status']=='ok' for r in rows),'/',len(rows),flush=True)
