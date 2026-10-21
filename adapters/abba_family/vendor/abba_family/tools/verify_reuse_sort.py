import sys,json,random,math,argparse,hashlib
from pathlib import Path
from verify_stages import call,compare
P=Path(__file__).resolve().parents[1]
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cli',default=str(P/'build/abba_family_cli'));args=ap.parse_args();records=[];rng=random.Random(20261022);req=[]
 for n in [0,1,2,15,16,17,31,32,33,129,1024,4096,10000]:
  for mode in ['equal','few','sorted','reverse','organ','saw','random']:
   x=[0. if mode=='equal' else float(rng.randrange(5)) if mode=='few' else float(i) if mode=='sorted' else float(n-i) if mode=='reverse' else float(min(i,n-i)) if mode=='organ' else float(i%17) if mode=='saw' else rng.random() for i in range(n)];req.append({'algorithm':'fabba','operation':'argsort','values':x})
 refs=call([sys.executable,P/'tools/oracle.py'],req);cpp=call([args.cli],req)
 for r,a,b in zip(req,refs,cpp):
  assert a['ok'] and b['ok'];assert a['result']['indices']==b['result']['indices'];records.append({'kind':'numpy_argsort','n':len(r['values']),'input_sha256':hashlib.sha256(json.dumps(r).encode()).hexdigest(),'status':'PASS'})
 plan=json.loads((P/'docs/DATASET_TEST_PLAN.json').read_text())
 for ds in plan['datasets']:
  test=json.loads((P/ds['frozen']).read_text());source=Path(ds['source']);train=source.with_name(source.name.replace('_TEST','_TRAIN'));training=json.loads((P/ds['training_frozen']).read_text());config={};fitted=call([args.cli],[{'algorithm':'qabba','values':training,'config':config}])[0]['result'];model=fitted['model'];model.pop('symbols')
  for x in test[:3]:
   src=call([sys.executable,P/'tools/oracle.py'],[{'algorithm':'qabba','operation':'reuse','training':training,'values':x,'config':config}])[0];symbols=call([args.cli],[{'operation':'transform','model':model,'values':x}])[0];assert src['ok'] and symbols['ok'];compare(src['result']['symbols'],symbols['result']['symbols']);native=call([args.cli],[{'operation':'inverse','model':model,'symbols':symbols['result']['symbols'],'starts':[x[0]]}])[0];assert native['ok'];compare(src['result']['reconstructed'],native['result']['reconstructed']);records.append({'dataset':ds['id'],'kind':'TRAIN_model_TEST_transform','training_file_sha256':ds['training_source_sha256'],'training':training,'input':x,'model':model,'status':'PASS'})
 out={'status':'PASS','cases':len(records),'results':records};(P/'validation/reuse-sort.json').write_text(json.dumps(out,indent=2)+'\n');print('PASS',len(records))
if __name__=='__main__':main()
