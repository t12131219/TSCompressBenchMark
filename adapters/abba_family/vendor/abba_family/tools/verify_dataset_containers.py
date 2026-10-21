"""Frozen datasets through full native frames, cold subprocess decode and model reuse."""
import sys,json,math,hashlib,struct,subprocess,tempfile,os,argparse
from pathlib import Path
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1]
def digest(x):return hashlib.sha256(struct.pack('<'+'d'*len(x),*x)).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));args=ap.parse_args();records=[]
 for name in ['ECG5000','Chinatown','Coffee','shared-float64']:
  rows=json.loads((P/f'tests/data/{name}.json').read_text())
  req=[{'algorithm':a,'values':x,'config':{'min_k':1} if a=='abba' else {}} for x in rows for a in ['abba','fabba','qabba']]
  source=call([sys.executable,P/'tools/oracle.py'],req);native=call([args.cli],req);enc=call([args.cli],[dict(r,operation='encode') for r in req]);dec=call([args.cli],[{'operation':'decode','container_hex':e['result']['container_hex']} for e in enc])
  for r,s,n,e,d in zip(req,source,native,enc,dec):
   assert all(z['ok'] for z in [s,n,e,d]);compare(s['result'],n['result']);compare(n['result']['reconstructed'],d['result']['reconstructed']);bits=call([args.cli],[{'operation':'input_bits','values':r['values']}])[0];assert bytes.fromhex(bits['result']['binary64_le_hex'])==struct.pack('<'+'d'*len(r['values']),*r['values']);physical=bytes.fromhex(e['result']['container_hex']);metadata=struct.unpack_from('<I',physical,8)[0];payload=struct.unpack_from('<Q',physical,12)[0];assert len(physical)==24+metadata+payload
   x=r['values'];y=d['result']['reconstructed'];common=min(len(x),len(y));err=[y[i]-x[i] for i in range(common)];records.append({'dataset':name,'row':len(records)//3,'algorithm':r['algorithm'],'input_samples':len(x),'reconstructed_samples':len(y),'binary64_sha256':digest(x),'config_sha256':hashlib.sha256(json.dumps(r['config'],sort_keys=True).encode()).hexdigest(),'reconstruction_sha256':digest(y),'max_abs_on_common_indices':max(map(abs,err)),'rmse_on_common_indices':math.sqrt(sum(z*z for z in err)/common),'nrmse_on_common_indices':math.sqrt(sum(z*z for z in err)/common)/(max(x)-min(x)) if max(x)!=min(x) else None,'final_bits':len(physical)*8,'ledger_bytes':{'header':20,'model_metadata':metadata,'symbol_payload':payload,'crc':4},'frame_sha256':hashlib.sha256(physical).hexdigest(),'status':'PASS'})
  # Independent decoder process receives only the frame; working directory has no source inputs.
  with tempfile.TemporaryDirectory(prefix='af-cold-') as temp:
   frame=Path(temp)/'data.afs';out=Path(temp)/'decoded.json';frame.write_bytes(bytes.fromhex(enc[0]['result']['container_hex']));subprocess.run([str(Path(args.cli).resolve()),'decode-file',str(frame),str(out)],cwd=temp,env={'PATH':'/usr/bin:/bin'},check=True);compare(dec[0]['result'],json.loads(out.read_text()))
 # Shared corpus qualifications are input objects with inline codebook fitting,
 # not corpus-training/generalization measurements.
 report={'status':'PASS','cases':len(records),'cold_decode_processes':4,'error_contract':'stage tolerance; no guaranteed pointwise bound, original length may change','results':records};(P/'validation/dataset-containers.json').write_text(json.dumps(report,indent=2)+'\n');print({k:v for k,v in report.items() if k!='results'})
if __name__=='__main__':main()
