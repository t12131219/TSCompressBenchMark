from pathlib import Path
import subprocess,json,hashlib,sys
p=Path(__file__).resolve().parents[1];rows=[]
commands=[
 ('sanitizer-test-clean.log',[p/'build-san/sprintz_tests'],True),
 ('sanitizer-negative.log',[p/'build-san/sprintz_negative'],True),
 ('experimental-sanitizer.log',[sys.executable,p/'tools/experiments.py','--san'],False),
 ('tsan-test.log',[p/'build-tsan/sprintz_negative'],True),
 ('fuzz.log',[p/'build-fuzz/sprintz_fuzz',p/'tests/fuzz-seeds','-runs=50000','-max_len=131072','-timeout=3','-artifact_prefix='+str(p/'evidence/fuzz-')],True)]
for name,cmd,required in commands:
 with (p/'evidence'/name).open('w') as f:r=subprocess.run(list(map(str,cmd)),stdout=f,stderr=f)
 rows.append({'log':name,'exit':r.returncode,'required_for_main':required,'command':list(map(str,cmd))})
 print(name,r.returncode,flush=True)
 if required:r.check_returncode()
artifacts={str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in [p/'build-san/libsprintz.so',p/'build-tsan/libsprintz.so',p/'build-fuzz/libsprintz.so',p/'build-fuzz/sprintz_fuzz']}
(p/'evidence/final-sanitizers.json').write_text(json.dumps({'scope':'qualified C ABI plus separately labelled experimental probes','sanitizers_disabled':[],'required_status':'PASS','runs':rows,'artifacts':artifacts},indent=2)+'\n')
