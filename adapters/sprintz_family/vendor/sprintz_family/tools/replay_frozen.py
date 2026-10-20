from pathlib import Path
import json,hashlib,subprocess,tempfile,ctypes as C,argparse,os
p=Path(__file__).resolve().parents[1];ap=argparse.ArgumentParser();ap.add_argument('--build',default='build');a=ap.parse_args();cli=p/a.build/'sprintz_cli';rows=[]
# Validate stored raw golden bytes and decode using only frozen config, not input.
with tempfile.TemporaryDirectory(prefix='sprintz-replay-') as td:
 t=Path(td)
 for row in json.loads((p/'tests/golden/manifest.json').read_text()):
  stream=p/'tests/golden'/(row['name']+'.sz');assert hashlib.sha256(stream.read_bytes()).hexdigest()==row['encoded_sha256']
  q=subprocess.run([str(cli),'dec']+list(map(str,row['config']))+[str(stream),str(t/'out'),str(row['raw_bytes'])],capture_output=True)
  assert q.returncode==0,q.stderr;assert hashlib.sha256((t/'out').read_bytes()).hexdigest()==row['decoded_sha256'];rows.append(row['name'])
 canonical=[]
 for f in json.loads((p/'tests/data/canonical_manifest.json').read_text()):
  raw=p/f['payload_file'];data=raw.read_bytes();assert hashlib.sha256(data).hexdigest()==f['payload_sha256'];bits=8 if f['dtype'].endswith('1') else 16
  for fire in [0,1]:
   for h in [0,1]:
    config=[str(bits),str(fire),str(h),'0',str(f['ndims'])]
    for op,src,dest in [('enc',raw,t/'encoded'),('dec',t/'encoded',t/'decoded')]:
     q=subprocess.run([str(cli),op]+config+[str(src),str(dest),str(len(data))],capture_output=True);assert q.returncode==0,q.stderr
    assert (t/'decoded').read_bytes()==data;canonical.append(f['key'])
print(json.dumps({'golden_cold_decode':len(rows),'canonical_frozen':len(canonical),'status':'PASS'}))
