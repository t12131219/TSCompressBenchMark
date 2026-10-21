from pathlib import Path
import sys,json,random,math,argparse,os
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1]
def cases():
 rng=random.Random(77102);out=[]
 def walk(n=81):
  v=[];z=0
  for i in range(n):z+=rng.uniform(-2,2);v.append(z)
  return v
 for norm in [1,2]:
  for weight in [False,True]:
   for sym in [False,True]:
    for j in range(5):out.append({'algorithm':'abba','config':{'c_method':'incremental','min_k':1,'max_k':16,'norm':norm,'weighted':weight,'symmetric':sym,'tol':[.05,.3]},'values':walk()})
 for scl in [.25,.5,1.,2.,'inf']:
  for j in range(12):out.append({'algorithm':'abba','config':{'scl':scl,'min_k':1,'max_k':12,'tol':[.1,.2]},'values':walk()})
 for sort in ['lexi','1-norm','2-norm','norm','pca']:
  for j in range(12):
   out.append({'algorithm':'fabba','config':{'sorting':sort,'alpha':[0.,.1,.5][j%3],'scl':[0.,.5,2.][j%3],'max_len':[1,3,-1][j%3]},'values':walk(65),'alphabet':1 if j%2 else ['↑','↓','甲','乙','丙','丁','戊','己','庚','辛','壬','癸']*0+list(map(chr,range(0x400,0x500)))})
 for partition in [1,2,7,200]:
  for jobs in [1,2,3]:out.append({'algorithm':'fabba','config':{'partition':partition,'n_jobs':jobs,'tol':.001,'alpha':.1},'values':walk(103)})
 for rate in [.25,1.,4.]:out.append({'algorithm':'fabba','config':{'partition_rate':rate,'n_jobs':2,'tol':.01},'values':walk(103)})
 for a in ['fabba','qabba']:
  for fill in ['ffill','bfill','zero','mean','median']:
   v=walk(31);v[3]=v[4]=v[16]=None
   out.append({'algorithm':a,'fill':fill,'config':{('fillna' if a=='fabba' else 'fill_value'):fill},'values':v})
 for digitizer in ['agg','kmeans','f-kmeans']:
  for sort in ['norm','pca']:
   for j in range(8):out.append({'algorithm':'qabba','config':{'digitizer':digitizer,'sorting':sort,'n_symbols':2+j%5,'random_state':[0,7,42][j%3],'sample_rate':[.2,.5,1.][j%3],'max_iter':50,'scale_length':[0.,.5,2.][j%3],'bits_for_len':[4,8,12,16][j%4],'bits_for_inc':[4,8,12,16][j%4]},'values':walk()})
 for jobs in [1,2,3]:
  for digitizer in ['agg','kmeans','f-kmeans']:out.append({'algorithm':'qabba','config':{'digitizer':digitizer,'n_jobs':jobs,'n_symbols':3},'values':[walk(81),walk(81),walk(81)]})
 for codec in ['none','fixed','huffman','huffman1','lzw','zlib','gzip','bz2','lzma','zstd']:
  for include in [False,True]:out.append({'algorithm':'qabba','config':{'symbol_codec':codec,'include_symbol_model':include},'values':walk(129)})
 return out

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));ap.add_argument('--report',default='capabilities-initial.json');args=ap.parse_args();reqs=cases();results=[]
 if os.environ.get("AF_SOURCE_BACKEND")=="cython":
  for r in reqs:
   if r["algorithm"]=="fabba":r.setdefault("config",{})["source_backend"]="cython"
 for offset in range(0,len(reqs),25):
  chunk=reqs[offset:offset+25];ref=call([sys.executable,P/'tools/oracle.py'],chunk);got=call([args.cli],chunk)
  for i,(req,a,b) in enumerate(zip(chunk,ref,got)):
   row={'id':offset+i,'request':req,'source':a,'cpp':b,'status':'PASS'}
   try:
    if a['ok']!=b['ok']:raise AssertionError('accept/reject mismatch')
    if a['ok']:compare(a['result'],b['result'])
   except Exception as e:row.update(status='FAIL',reason=str(e))
   results.append(row)
 fail=[x for x in results if x['status']=='FAIL'];out={'status':'FAIL' if fail else 'PASS','cases':len(results),'failures':len(fail),'results':results};(P/'validation'/args.report).write_text(json.dumps(out,indent=2)+'\n');print({k:v for k,v in out.items() if k!='results'})
 for x in fail[:30]:print(x['id'],x['request']['algorithm'],x['reason'])
 if fail:sys.exit(1)
if __name__=='__main__':main()
