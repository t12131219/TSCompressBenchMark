from pathlib import Path
import subprocess,json,shlex
P=Path(__file__).resolve().parents[1];commands=json.loads((P/'build/compile_commands.json').read_text());records=[]
for row in commands:
 path=Path(row['file'])
 if path.parent!=P/'src' or '/abba_family.dir/' not in row['command']:continue
 original=shlex.split(row['command']);flags=[];i=1
 while i<len(original):
  if original[i]=='-o':i+=2;continue
  if original[i]=='-c':i+=1;continue
  flags.append(original[i]);i+=1
 cmd=['clang++','--analyze','-Xanalyzer','-analyzer-output=text',*flags];r=subprocess.run(cmd,cwd=P,capture_output=True,text=True);records.append({'file':str(path.relative_to(P)),'command':cmd,'exit':r.returncode,'diagnostics':r.stdout+r.stderr})
out={'status':'PASS' if all(x['exit']==0 and 'warning:' not in x['diagnostics'] for x in records) else 'REVIEW','translation_units':len(records),'results':records};(P/'validation/static-analysis.json').write_text(json.dumps(out,indent=2)+'\n');print(out['status'],len(records))
