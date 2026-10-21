from pathlib import Path
import subprocess,json,sys,math,random,argparse,hashlib,os,time
P=Path(__file__).resolve().parents[1]
def call(cmd,reqs):
 r=subprocess.run(list(map(str,cmd)),input=''.join(json.dumps(x,allow_nan=False)+'\n' for x in reqs),text=True,capture_output=True,timeout=300)
 if r.returncode:raise RuntimeError(r.stderr[-3000:])
 out=[json.loads(x) for x in r.stdout.split("\n") if x.strip()]
 if len(out)!=len(reqs):raise RuntimeError('response count mismatch '+r.stderr[-2000:])
 return out

def compare(ref,got,path='result'):
 if isinstance(ref,dict):
  for k,v in ref.items():
   if k not in got:raise AssertionError(path+' missing '+k)
   compare(v,got[k],path+'.'+k)
 elif isinstance(ref,list):
  if len(ref)!=len(got):raise AssertionError(f'{path} length {len(ref)} != {len(got)}')
  for i,(a,b) in enumerate(zip(ref,got)):compare(a,b,path+f'[{i}]')
 elif isinstance(ref,(int,float)):
  if ('quantized_centers' in path or '.labels[' in path) and ref!=got:raise AssertionError(f'{path}: integer decision {ref!r} != {got!r}')
  if not isinstance(got,(int,float)) or not math.isfinite(got) or abs(ref-got)>1e-10+1e-10*abs(ref):raise AssertionError(f'{path}: {ref!r} != {got!r}')
 elif ref!=got:raise AssertionError(f'{path}: {ref!r} != {got!r}')

def requests():
 rng=random.Random(20261020);reqs=[]
 for a in ['abba','fabba','qabba']:
  for case in range(100):
   n=[2,3,15,16,17,31,32,33,63,65,127,128,129][case%13]
   x=[];last=0
   for j in range(n):
    if case%5==0:last=3.
    elif case%5==1:last=math.sin(.17*j+case)
    elif case%5==2:last+=rng.uniform(-2,2)
    elif case%5==3:last=float(j%7)
    else:last=j*.5
    x.append(last)
   if a=='abba':c={'min_k':1,'max_k':min(12,n-1),'tol':[.1,.2]}
   elif a=='fabba':c={'tol':[0.,.01,.1,.3][case%4],'alpha':[0.,.1,.5,1.][case%4]}
   else:c={'tol':[.01,.1,.3][case%3],'alpha':[.1,.5,1.][case%3]}
   reqs.append({'algorithm':a,'values':x,'config':c})
 for name in ['ECG5000','Chinatown','Coffee']:
  for x in json.loads((P/f'tests/data/{name}.json').read_text()):
   for a in ['abba','fabba','qabba']:reqs.append({'algorithm':a,'values':x,'config':{'min_k':1} if a=='abba' else {}})
 return reqs

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));ap.add_argument('--report',default='stages-initial.json');args=ap.parse_args();reqs=requests();results=[]
 if os.environ.get("AF_SOURCE_BACKEND")=="cython":
  for r in reqs:
   if r["algorithm"]=="fabba":r.setdefault("config",{})["source_backend"]="cython"
 for offset in range(0,len(reqs),50):
  chunk=reqs[offset:offset+50];sources=call([sys.executable,P/'tools/oracle.py'],chunk);actual=call([args.cli],chunk)
  for i,(req,ref,got) in enumerate(zip(chunk,sources,actual)):
   row={'id':offset+i,'algorithm':req['algorithm'],'request':req,'source':ref,'cpp':got,'status':'PASS'}
   try:
    if ref['ok']!=got['ok']:raise AssertionError('accept/reject mismatch')
    if ref['ok']:compare(ref['result'],got['result'])
   except Exception as e:row['status']='FAIL';row['reason']=str(e)
   results.append(row)
 failures=[x for x in results if x['status']=='FAIL'];report={'status':'FAIL' if failures else 'PASS','cases':len(results),'failures':len(failures),'results':results}
 (P/'validation'/args.report).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='results'}))
 for row in failures[:15]:print(row['id'],row['algorithm'],row['reason'])
 if failures:sys.exit(1)
if __name__=='__main__':main()
