from pathlib import Path
import json,subprocess,os,platform,hashlib
P=Path(__file__).resolve().parents[1];cpu=min(os.sched_getaffinity(0));runs=[]
for dataset in ['ECG5000','Chinatown','Coffee']:
 for run in range(3):
  p=subprocess.run(['taskset','-c',str(cpu),str(P/'build/af_benchmark'),str(P/f'tests/data/{dataset}.json')],capture_output=True,text=True,check=True);r=json.loads(p.stdout);r.update(dataset=dataset,process_run=run);runs.append(r)
report={'status':'PASS','scope':'standalone smoke performance; no source speedup or formal Benchmark comparison claimed','cpu':cpu,'uname':platform.uname()._asdict(),'cpuinfo':Path('/proc/cpuinfo').read_text(),'runs':runs};(P/'validation/performance.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS',len(runs),'independent benchmark processes')
