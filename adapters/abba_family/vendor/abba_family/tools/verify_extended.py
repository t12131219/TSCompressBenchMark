"""Image/shape, quantization widths, source-symbol interchange, and real path matrix."""
import sys,os,json,random,math,argparse,hashlib
from pathlib import Path
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));ap.add_argument('--report',default='extended.json');args=ap.parse_args();rng=random.Random(20261021);req=[]
 def walk(n):
  x=[0.]
  for i in range(n-1):x.append(x[-1]+rng.uniform(-2,2))
  return x
 for shape in [(4,8),(8,4,3),(2,2,2,2),(2,1,1,1,1),(2,)+(1,)*31]:
  import numpy as np
  data=np.array([rng.randrange(256) for _ in range(math.prod(shape))]).reshape(shape).tolist()
  for adjust in [False,True]:
   for sort in ['2-norm','pca','norm']:req.append({'algorithm':'fabba','operation':'image_fit','values':data,'adjust':adjust,'config':{'sorting':sort,'tol':0.,'alpha':.1}})
 for shape in ['row','column']:
  x=walk(81);req.append({'algorithm':'fabba','values':[x] if shape=='row' else [[v] for v in x]})
 for b in [1,2,7,8,9,15,16,17,31,32,33,48,53,54,63,64]:
  req.append({'algorithm':'qabba','values':walk(81),'config':{'bits_for_len':b,'bits_for_inc':b,'alpha':.1}})
 for m in ['linear','loglinear','quadratic']:
  for j in range(5):req.append({'algorithm':'abba','operation':'native_ckmeans','values':walk(91),'config':{'min_k':1,'max_k':8,'method':m}})
 # Every required configuration group also executes on each selected real dataset.
 for name in ['ECG5000','Chinatown','Coffee']:
  x=json.loads((P/f'tests/data/{name}.json').read_text())[0]
  for norm in [1,2]:
   for weight in [False,True]:
    for sym in [False,True]:req.append({'algorithm':'abba','values':x,'config':{'min_k':1,'c_method':'incremental','norm':norm,'weighted':weight,'symmetric':sym,'tol':[.1,.2]}})
  for scl in [0,.5,1,'inf']:req.append({'algorithm':'abba','values':x,'config':{'min_k':1,'scl':scl}})
  for sorting in ['lexi','1-norm','2-norm','norm','pca']:
   for workers in [1,3]:req.append({'algorithm':'fabba','values':x,'config':{'sorting':sorting,'partition':5,'n_jobs':workers},'alphabet':1})
  for digitizer in ['agg','kmeans','f-kmeans']:
   for sorting in ['norm','pca']:req.append({'algorithm':'qabba','values':[x,x],'config':{'digitizer':digitizer,'sorting':sorting,'n_jobs':2}})
  for codec in ['none','fixed','huffman','huffman1','lzw','zlib','gzip','bz2','lzma','zstd']:req.append({'algorithm':'qabba','values':x,'config':{'symbol_codec':codec}})
 if os.environ.get('AF_SOURCE_BACKEND')=='cython':
  for r in req:
   if r['algorithm']=='fabba':r.setdefault('config',{})['source_backend']='cython'
 records=[];fixtures=[]
 for start in range(0,len(req),25):
  chunk=req[start:start+25];ref=call([sys.executable,P/'tools/oracle.py'],chunk);got=call([args.cli],chunk)
  for r,a,b in zip(chunk,ref,got):
   row={'request':r,'source':a,'cpp':b,'status':'PASS'}
   try:
    assert a['ok']==b['ok'],'accept/reject mismatch'
    if a['ok']:compare(a['result'],b['result'])
   except Exception as e:row.update(status='FAIL',reason=str(e))
   records.append(row)
   if a['ok'] and b['ok'] and r.get('operation','fit')=='fit':fixtures.append((r,a['result'],b['result']))
 # Source representations -> native inverse and native representations -> source inverse.
 for r,a,b in fixtures:
  alg=r['algorithm'];model=dict(b['model']);model['centers']=a['centers'];model['alphabet']=a.get('alphabet',b['alphabet'])
  # Q quantizer model is retained; its learned source state was compared above.
  starts=model['starts'];one=model['single']
  try:
   native_inv=call([args.cli],[{'operation':'inverse','model':model,'symbols':a['symbols']}])[0]
   assert native_inv['ok'];compare(a['reconstructed'],native_inv['result']['reconstructed'])
   if one:
    source_model={'schema_version':1,'centers':b['centers'],'alphabets':b['alphabet'],'splist':b.get('splist',[])}
    sr={'operation':'inverse','algorithm':alg,'symbols':b['symbols'],'centers':b['centers'],'alphabet':b['alphabet'],'model':source_model,'start':starts[0]}
    src=call([sys.executable,P/'tools/oracle.py'],[sr])[0];assert src['ok'],str(src);compare(b['reconstructed'],src['result']['reconstructed'])
   records.append({'algorithm':alg,'kind':'symbol_codebook_interchange','status':'PASS'})
  except Exception as e:records.append({'request':r,'kind':'symbol_codebook_interchange','status':'FAIL','reason':str(e)})
 fail=[r for r in records if r['status']=='FAIL'];out={'status':'FAIL' if fail else 'PASS','cases':len(records),'failures':len(fail),'results':records};(P/'validation'/args.report).write_text(json.dumps(out,indent=2)+'\n');print({k:v for k,v in out.items() if k!='results'})
 for f in fail[:30]:print(f.get('request',{}).get('algorithm'),f.get('request',{}).get('config'),f['reason'])
 if fail:sys.exit(1)
if __name__=='__main__':main()
