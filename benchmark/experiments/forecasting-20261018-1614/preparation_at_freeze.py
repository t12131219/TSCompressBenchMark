from pathlib import Path
import pandas as pd, numpy as np, json, hashlib, collections, time
root=Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark'); dest=root/'benchmark/experiments/forecasting-20261018-1614'; data=dest/'data'; data.mkdir(exist_ok=True)
rows=[]; started=time.time()
for i,p in enumerate(sorted((root/'forecasting_transpose').glob('*.csv'))):
 r={'id':p.stem,'family':p.stem.split('_dataset')[0], 'source':str(p), 'source_bytes':p.stat().st_size,'source_sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()}
 try:
  df=pd.read_csv(p); cols=[c for c in df if c!='date']; a=np.ascontiguousarray(df[cols].to_numpy(dtype='<f8')); a=a[:,0].copy() if a.shape[1]==1 else a
  r.update(shape=list(a.shape),columns=cols,values=int(a.size),raw_bytes=a.nbytes,nonfinite=int(np.count_nonzero(~np.isfinite(a))),min=float(np.nanmin(a)),max=float(np.nanmax(a)),integral=bool(np.isfinite(a).all() and np.equal(a,np.trunc(a)).all()),timestamp_parser='int' if str(df['date'].iloc[0]).isdigit() else 'datetime64')
  np.save(data/(p.stem+'.npy'),a,allow_pickle=False); r['npy']=str(data/(p.stem+'.npy')); r['status']='ok'
 except Exception as e:r.update(status='error',reason=str(e))
 rows.append(r)
 if i%1000==0:print(i,round(time.time()-started,1),flush=True)
(dest/'inventory.json').write_text(json.dumps({'files':rows,'count':len(rows),'source_root':str(root/'forecasting_transpose'),'parse':'pandas CSV -> all non-date columns float64, C-order; single channel rank1, all rows; no fill/scale/quantization','parse_errors':sum(r['status']!='ok' for r in rows)},ensure_ascii=False,indent=2,allow_nan=True))
print('DONE',len(rows),collections.Counter(r['status'] for r in rows),'nonfinite',sum(r.get('nonfinite',0)>0 for r in rows),'seconds',time.time()-started,flush=True)
