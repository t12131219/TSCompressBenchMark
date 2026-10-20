from pathlib import Path
import subprocess,tempfile,json,hashlib,os,argparse
p=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser();ap.add_argument('--cli',default='build/sprintz_cli');a=ap.parse_args();cli=(p/a.cli).resolve();gold=p/'tests/golden';gold.mkdir(exist_ok=True);rows=[]
inputs=[(8,1,p/'tests/data/canonical/dv_source_sprintz_u8_uts.bin'),(16,3,p/'tests/data/national_illness_counts.u16le')]
for bits,d,src in inputs:
 data=src.read_bytes()
 for fire in [0,1]:
  for h in [0,1]:
   for path in [0,1,2,3,4,5]:
    if(path==2 and d>(4 if bits==8 else 2))or(path in [3,4] and fire)or(path==5 and(bits!=8 or not fire)):continue
    name=f'{bits}-{fire}-{h}-{path}-{d}';encoded=gold/(name+'.sz');config=[bits,fire,h,path,d]
    q=subprocess.run([str(cli),'enc']+list(map(str,config))+[str(src),str(encoded),str(len(data))],capture_output=True);assert q.returncode==0,q.stderr
    expected=hashlib.sha256(data).hexdigest()
    sidecar=json.dumps({'config':config,'expected_bytes':len(data)},sort_keys=True,separators=(',',':')).encode()+b'\n'
    (gold/(name+'.json')).write_bytes(sidecar)
    # Cold environment: only executable, shared object, compressed stream.
    with tempfile.TemporaryDirectory(prefix='sprintz-cold-') as td:
     t=Path(td);import shutil
     shutil.copy2(cli,t/'decode');shutil.copy2(p/'build/libsprintz.so',t/'libsprintz.so');shutil.copy2(encoded,t/'payload')
     env={'PATH':'/usr/bin:/bin','LD_LIBRARY_PATH':str(t),'LANG':'C'}
     q=subprocess.run([str(t/'decode'),'dec']+list(map(str,config))+['payload','out',str(len(data))],cwd=t,env=env,capture_output=True);assert q.returncode==0,q.stderr
     assert hashlib.sha256((t/'out').read_bytes()).hexdigest()==expected
    rows.append({'name':name,'config':config,'raw_bytes':len(data),'encoded_bytes':encoded.stat().st_size,'sidecar_bytes':len(sidecar),'full_recovery_bits':8*(encoded.stat().st_size+len(sidecar)),'decoded_sha256':expected,'encoded_sha256':hashlib.sha256(encoded.read_bytes()).hexdigest(),'status':'PASS'})
(p/'tests/golden/manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
(p/'evidence/cold-decode.json').write_text(json.dumps({'cases':len(rows),'input_available_in_decoder_cwd':False,'results':rows},indent=2)+'\n');print('cold decode PASS',len(rows))
