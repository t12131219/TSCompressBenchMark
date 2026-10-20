from pathlib import Path
import subprocess,json,argparse
p=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser();ap.add_argument('--san',action='store_true');a=ap.parse_args();rows=[]
configs=[]
for mode in ['primitive-delta','primitive-doubledelta','primitive-xff']:
 for bits in [8,16]:
  for d in [1,2,3,8,17,128]:
   for n in ([1025] if a.san else [1,127,128,1025]):
    for inplace in [0,1]:configs.append([mode,bits,d,n,2,inplace])
for mode in ['delta_simple','delta','doubledelta','dyndelta','delta_rle','delta_rle2','online','delta_online','delta2_online']:
 for n in ([1025] if a.san else [1,7,127,128,129,1025]):configs.append([mode,8,1,n,2,0])
for config in configs:
 results={}
 for build in (['build-san'] if a.san else ['build-baseline','build']):
  try:
   q=subprocess.run([str(p/build/'sprintz_experiments')]+list(map(str,config)),capture_output=True,timeout=5)
   results[build]={'exit':q.returncode,'stdout':q.stdout.decode(errors='replace').strip(),'stderr':q.stderr.decode(errors='replace')[:5000]}
  except subprocess.TimeoutExpired:results[build]={'exit':'TIMEOUT'}
 rows.append({'config':config,'results':results})
report='experimental-sanitizer.json' if a.san else 'experimental.json'
(p/'evidence'/report).write_text(json.dumps({'status':'DIAGNOSTIC_ONLY','cases':len(rows),'results':rows},indent=2)+'\n')
print(json.dumps({'cases':len(rows),'failed':sum(any(z['exit']!=0 for z in r['results'].values()) for r in rows),'qualification':'RESEARCH_ONLY'}))
