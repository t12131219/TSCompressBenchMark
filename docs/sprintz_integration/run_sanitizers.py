#!/usr/bin/env python3
from pathlib import Path
import json,subprocess,os,hashlib
from tsbench import _native_recipes as recipes
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'build/sprintz-family-integration/sanitizer';OUT.mkdir(parents=True,exist_ok=True)
recipes.PROJECT_ROOT=ROOT
# Compile the same frozen native/API units once, then all four macro bindings.
first=OUT/'libdelta.so';command=recipes._sprintz_family_command(first,'sanitizer','sprintz-delta');libs=[];records=[]
for key in recipes.SPRINTZ_FAMILY:
 predictor,huffman=recipes.SPRINTZ_FAMILY[key];target=OUT/(key+'.so');cmd=[f'-DTSCB_SPRINTZ_PREDICTOR={predictor}' if v.startswith('-DTSCB_SPRINTZ_PREDICTOR=') else f'-DTSCB_SPRINTZ_HUFFMAN={huffman}' if v.startswith('-DTSCB_SPRINTZ_HUFFMAN=') else f'-DTSCB_SPRINTZ_KEY="{key}"' if v.startswith('-DTSCB_SPRINTZ_KEY=') else str(target) if v==str(first) else v for v in command];recipes._run(cmd);libs.append(target);records.append({'key':key,'command':cmd,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
exe=OUT/'binding';recipes._run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-fno-omit-frame-pointer','-I',str(ROOT/'native/include'),str(ROOT/'docs/sprintz_integration/sanitizer_binding.cpp'),'-ldl','-o',str(exe)])
env={**os.environ,'ASAN_OPTIONS':'detect_leaks=1:halt_on_error=1','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1'}
p=subprocess.run([str(exe),*map(str,libs)],env=env,capture_output=True,text=True)
result={'status':'PASS' if p.returncode==0 else 'FAIL','returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'libraries':records,'commands':recipes.COMMANDS,'asan_options':env['ASAN_OPTIONS'],'ubsan_options':env['UBSAN_OPTIONS']}
(ROOT/'docs/sprintz_integration/sanitizer.json').write_text(json.dumps(result,indent=2)+'\n');print(p.stdout+p.stderr);raise SystemExit(p.returncode)
