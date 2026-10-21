import sys,json,math
from pathlib import Path
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1];requests=[{'algorithm':'abba','config':{'seed':False,'scl':1.0,'min_k':1,'max_k':12,'tol':[.1,.2]},'values':[math.sin(i*.3+j)+math.cos(i*.23)*.2 for i in range(81)]} for j in range(20)];a=call([sys.executable,P/'tools/oracle.py'],requests);b=call([P/'build/abba_family_cli'],requests);records=[]
for request,source,native in zip(requests,a,b):
 assert source['ok'] and native['ok'];s=source['result'];n=native['result'];compare(s['pieces'],n['pieces']);assert 1<=len(n['centers'])<=12;assert len(n['symbols'])==len(n['pieces']);assert all(math.isfinite(v) for v in n['reconstructed']);records.append({'request':request,'source':source,'cpp':native,'criterion':'same deterministic compression; stochastic model cardinality/symbol/reconstruction invariants, no one-run label identity asserted','status':'PASS'})
(P/'validation/unseeded.json').write_text(json.dumps({'status':'PASS','cases':len(records),'results':records},indent=2)+'\n');print('unseeded property cases PASS',len(records))
