"""Retain correctness products for both native boundaries and lifecycle modes."""
from pathlib import Path
import json
import numpy as np
from tsbench import native
from tsbench.bridges import create_bridge
from tsbench.families import CAMEO_FAMILY
from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
from tsbench.data import TimeSeriesObject
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent/'native_matrix'
OUT.mkdir(exist_ok=True)
native.ensure_driver(ROOT,ROOT/'build/tsbench')
rows=[]
a=(3+np.sin(np.arange(64)*.49)).astype('<f8');obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}})
for key in CAMEO_FAMILY:
 for boundary in ['native_core','native_api']:
  for lifecycle in ['prepared','fresh_request']:
   method={'id':key,'codec':key};task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle,'fidelity':'empirical_quality'}
   support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
   m=native.NativeMeasurement(method,task,{**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'timeout_s':60},support,ROOT,ROOT/'build/tsbench');m.prepare(obj)
   row,wire=m.measure(obj,independent=True,artifact_dir=OUT/key/boundary/lifecycle)
   assert row['verification']['passed'] and row['independent_recovery']['passed'] and row['verification']['validated_operations']==3
   frame=Path(row['artifact_path']).read_bytes();assert frame[:4]==b'CF01' and row['codec_complete_bytes']==len(frame) and row['bits_per_value']==len(frame)*8/a.size
   restored=create_bridge(ROOT,key).decode(frame,a.dtype,a.shape,{});assert np.isfinite(restored).all()
   # Detailed measurement JSON includes timing observations solely as test output,
   # not as a formal throughput result; all retained operations were validated.
   rows.append({'codec':key,'boundary':boundary,'lifecycle':lifecycle,'status':'PASS','row':row})
(OUT/'results.json').write_text(json.dumps({'scope':'correctness matrix only; no FORMAL performance claim','groups':len(rows),'validated_operations':sum(r['row']['verification']['validated_operations'] for r in rows),'results':rows},indent=2)+'\n')
print('PASS',len(rows),'groups',len(rows)*3,'products')
