import sys,json,random,math,subprocess,argparse,os,hashlib
from pathlib import Path
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));args=ap.parse_args();x=[math.sin(i*.31)+i*.03 for i in range(65)];req=[]
 for alphabet in [['甲','乙','丙','丁']+[chr(i) for i in range(300,800)],['only-one']]:req.append({'algorithm':'qabba','values':x,'config':{'alphabet':alphabet}})
 req.append({'algorithm':'fabba','operation':'digitize','pieces':[[2.3,-.1]]*13,'config':{'sorting':'pca'}})
 for alphabet in [-1,0,1,2,None,'fallback',1.0]:req.append({'algorithm':'fabba','values':x,'alphabet':alphabet})
 for a in ['fabba','qabba']:
  for fill in ['ffill','bfill','zero','mean','median','Mean','Median']:
   for v in [[None,None,*x[2:]], [*x[:-2],None,None],[None]*65]:req.append({'algorithm':a,'values':v,'fill':fill,'config':{('fillna' if a=='fabba' else 'fill_value'):fill}})
 for alg in ['abba','fabba','qabba']:
  for maxlen in ([-1,1,3,7,2.3] if alg=='fabba' else [1,3,7,2.3]):req.append({'algorithm':alg,'values':x,'config':dict({'min_k':1} if alg=='abba' else {},max_len=maxlen)})
 for b in [0,-1,65,66,128,1024]:req.append({'algorithm':'qabba','values':x,'config':{'bits_for_len':b,'bits_for_inc':b}})
 records=[];refs=call([sys.executable,P/'tools/oracle.py'],req);actual=call([args.cli],req)
 for r,a,b in zip(req,refs,actual):
  row={'request':r,'source':a,'cpp':b,'status':'PASS'}
  try:
   assert a['ok']==b['ok'],'accept/reject mismatch'
   if a['ok']:compare(a['result'],b['result'])
  except Exception as e:row.update(status='FAIL',reason=str(e))
  records.append(row)
 # Explicit edited/empty source/native symbol-codebook exchange.
 for alg in ['abba','fabba','qabba']:
  fit=call([args.cli],[{'algorithm':alg,'values':x,'config':{'min_k':1} if alg=='abba' else {}}])[0]['result'];m=fit['model']
  for symbols in [[],fit['symbols'][:3],list(reversed(fit['symbols']))]:
   src={'operation':'inverse','algorithm':alg,'symbols':symbols,'centers':fit['centers'],'alphabet':fit['alphabet'],'start':1.25,'model':{'schema_version':1,'centers':fit['centers'],'alphabets':fit['alphabet'],'splist':fit.get('splist',[])}}
   a=call([sys.executable,P/'tools/oracle.py'],[src])[0];b=call([args.cli],[{'operation':'inverse','model':m,'symbols':symbols,'starts':[1.25]}])[0]
   assert a['ok']==b['ok'],str((a,b));
   if a['ok']:compare(a['result'],b['result'])
   records.append({'algorithm':alg,'kind':'edited_inverse','symbol_count':len(symbols),'status':'PASS'})
 # A finite IEEE-extrema input overflows the source segmentation arithmetic.
 # Do not count a timeout as source parity: document it as a rejected safety domain.
 extreme={'algorithm':'abba','operation':'compress','values':[1.7976931348623157e308,-1.7976931348623157e308,0.0]}
 source_state='UNKNOWN'
 try:
  run=subprocess.run([sys.executable,str(P/'tools/oracle.py')],input=json.dumps(extreme)+'\n',capture_output=True,text=True,timeout=5);source_state={'exit':run.returncode,'stdout':run.stdout,'stderr':run.stderr[-1000:]}
 except subprocess.TimeoutExpired:source_state={'status':'TIMEOUT','limit_seconds':5}
 native=call([args.cli],[extreme])[0];assert not native['ok'];records.append({'kind':'source_numerical_overflow_diagnostic','source':source_state,'cpp':native,'parity_claim':False,'status':'PASS'})
 failures=[x for x in records if x['status']=='FAIL'];out={'status':'FAIL' if failures else 'PASS','cases':len(records),'failures':len(failures),'results':records};(P/'validation/extra-boundaries.json').write_text(json.dumps(out,indent=2)+'\n');print({k:v for k,v in out.items() if k!='results'})
 for f in failures:print(f['request']['algorithm'],f['request'].get('fill'),f['reason'])
 if failures:sys.exit(1)
if __name__=='__main__':main()
