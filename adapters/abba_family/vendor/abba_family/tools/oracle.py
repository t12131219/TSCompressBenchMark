"""Run unmodified, directly downloaded upstream classes. Python is oracle only."""
from pathlib import Path
import sys,json,importlib,os,warnings
os.environ.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1')
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parents[1];R=P.parents[1]
sys.path.insert(0,str(R/'Toolchains/abba-python-extra'))
sys.path[:0]=[str(P/'oracle-runtime/abba'),str(P/'oracle-runtime/fabba' if os.environ.get('AF_SOURCE_BACKEND')=='cython' else R/'Source/fabba/upstream'),str(P/'oracle-runtime/qabba/src' if os.environ.get('AF_SOURCE_BACKEND')=='cython' else R/'Source/qabba/upstream/src')]
site=Path(os.environ.get('AF_ORACLE_SITE',str(R/'Toolchains/abba-oracle-runtime')))
if site.is_dir():sys.path.insert(0,str(site))
import numpy as np
from ABBA import ABBA
from fABBA import fABBA
from qabba import QABBA

def native(x):
 if isinstance(x,np.ndarray):return native(x.tolist())
 if isinstance(x,np.generic):return x.item()
 if isinstance(x,dict):return {k:native(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [native(v) for v in x]
 return x

def process(r):
 a=r['algorithm'];c=dict(r.get('config',{}));c.pop('source_backend',None)
 if c.get('scl')=='inf':c['scl']=float('inf')
 x=np.asarray(r.get('values',[]),dtype=float)
 op=r.get('operation','fit')
 if op=='argsort':return {'indices':np.argsort(x).tolist()}
 if op=='native_ckmeans':
  from src import Ckmeans
  o=Ckmeans.kmeans_1d_dp(x.tolist(),c.get('min_k',1),c.get('max_k',100),c.get('variance',.1),c.get('method','linear'))
  return {'labels':list(o.cluster),'centers':list(o.centres),'k':o.Kopt}
 if a=='abba':
  m=ABBA(verbose=0,**c)
  if op=='compress':return {'pieces':m.compress(x)}
  if op=='inverse':return {'reconstructed':m.inverse_transform(r['symbols'],np.asarray(r['centers']),r.get('start',0.))}
  if op=='digitize':
   s,z=m.digitize(np.asarray(r['pieces'],dtype=float));return {'symbols':list(s),'centers':z}
  p=m.compress(x);s,z=m.digitize(p)
  return {'pieces':p,'symbols':list(s),'centers':z,'reconstructed':m.inverse_transform(s,z,float(x[0]))}
 if a=='fabba':
  from fABBA.digitization import digitize
  m=fABBA(verbose=0,**c);fill=r.get('fill','bfill');alphabet=r.get('alphabet',0)
  if op=='image_fit':
   from fABBA import image_compress,image_decompress
   seq=image_compress(m,x,adjust=r.get('adjust',True))
   return {'symbols':list(seq),'centers':m.parameters.centers,'splist':m.parameters.splist,'image':image_decompress(m,seq)}
  if op=='compress':return {'pieces':m.compress(x,fillm=fill)}
  if op=='digitize':
   s,z=m.digitize(r['pieces'],alphabet_set=alphabet);return {'symbols':list(s),'centers':z.centers,'alphabet':z.alphabets,'splist':z.splist}
  if op=='inverse':return {'reconstructed':m.inverse_transform(r['symbols'],start=r.get('start',0.),parameters=importlib.import_module('fABBA.fabba').Model.from_dict(r['model']))}
  s=m.fit_transform(x,fillm=fill,alphabet_set=alphabet)
  return {'pieces':m.pieces_,'symbols':list(s),'centers':m.parameters.centers,'alphabet':m.parameters.alphabets,'splist':m.parameters.splist,'reconstructed':m.inverse_transform(s,start=m.start_)}
 m=QABBA(**c)
 if op=='compress':return {'pieces':m._compress_one(x)}
 if op=='digitize':
  l,z=m._fit_digitizer(np.asarray(r['pieces'],dtype=float));return {'labels':l,'centers':z}
 if op=='inverse':
  m.centers_=np.asarray(r['centers'],dtype=float);m.alphabet_=np.asarray(r['alphabet']);m.start_values_=np.asarray([r.get('start',0.)]);m.symbols_=r['symbols']
  return {'reconstructed':m.inverse_transform(r['symbols'],r.get('start',0.))}
 if op=='reuse':
  m.fit(np.asarray(r['training'],dtype=float));symbols=m.transform(x)
  return {'symbols':symbols,'reconstructed':m.inverse_transform(symbols,float(x[0]))}
 m.fit(x)
 seq=m.symbols_; rec=m.inverse_transform();trans=m.transform(x)
 return {'pieces':m.pieces_,'symbols':seq,'alphabet':m.alphabet_,'centers':m.centers_,'quantized_centers':m.quantized_centers_,'quantizers':[[m.len_quantizer_.scale_,m.len_quantizer_.zero_point_],[m.inc_quantizer_.scale_,m.inc_quantizer_.zero_point_]],'reconstructed':rec,'transformed':trans,'storage':vars(m.storage_),'symbol_stats':{k:v for k,v in vars(m.symbol_codec_stats_).items() if k not in ['payload','sequences','metadata']}}

if __name__=='__main__':
 for line in sys.stdin:
  if not line.strip():continue
  try:
   with warnings.catch_warnings():
    warnings.simplefilter('ignore');out={'ok':True,'result':native(process(json.loads(line)))}
   print(json.dumps(out,allow_nan=False),flush=True)
  except Exception as e:print(json.dumps({'ok':False,'type':type(e).__name__,'error':str(e)}),flush=True)
