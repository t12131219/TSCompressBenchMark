"""Pure-file negative tests of current lossless native report admission."""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import tempfile

ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parent
tool=ROOT/'tools/onboard_requested_lossless.py'
spec=importlib.util.spec_from_file_location('independent_lossless_gate',tool)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
algorithms=tuple(sorted(json.loads((ROOT/'adapters/rewrite_lossless/FROZEN_APIS.json').read_text())['algorithms']))
path=ROOT/'docs/audits/20261011_port_standard_v30/general_native_qualification_v4/qualification.json'
base=json.loads(path.read_text())
accepted=module.read_native_report(ROOT,path,algorithms)
assert len(accepted)==12
temporary=Path(tempfile.mkdtemp(prefix='tscb-independent-lossless-gate-',dir='/tmp'))
mutations=[]
legacy=json.loads((ROOT/'build/rewrite_review/native-abi/report.json').read_text())
legacy['cases']=[]
legacy['driver_sha256']='0'*64
mutations.append(('legacy_empty_cases_and_zero_driver',legacy))
changed=copy.deepcopy(base);changed['results']=[];changed['record_count']=0;mutations.append(('empty_current_native_universe',changed))
changed=copy.deepcopy(base);changed['driver']['sha256']='0'*64;mutations.append(('drifted_current_native_driver',changed))
changed=copy.deepcopy(base);selected=next(r for r in changed['results'] if r['algorithm'] in algorithms);changed['results'].append(copy.deepcopy(selected));changed['record_count']=len(changed['results']);mutations.append(('duplicate_selected_native_profile',changed))
changed=copy.deepcopy(base);index=next(i for i,r in enumerate(changed['results']) if r['algorithm'] in algorithms);del changed['results'][index];changed['record_count']=len(changed['results']);mutations.append(('missing_selected_native_profile',changed))
rows=[]
for label,document in mutations:
    file=temporary/(label+'.json');file.write_text(json.dumps(document)+'\n')
    try:
        module.read_native_report(ROOT,file,algorithms)
    except RuntimeError as error:rows.append({'case':label,'status':'PASS_REJECTED','reason':str(error)})
    else:rows.append({'case':label,'status':'FAIL_ACCEPTED'})
assert all(row['status']=='PASS_REJECTED' for row in rows)
result={'status':'PASS_FIXED_LOSSLESS_REPORT_GATE_NEGATIVES','scope':'CURRENT_REAL_READ_NATIVE_REPORT_FILE_GATE_NO_CODEC_LDD_TESTS_OR_ADMISSION_WRITES','baseline_selected_native_profiles':len(accepted),'negative_count':len(rows),'rows':rows,'onboarding_source_sha256':hashlib.sha256(tool.read_bytes()).hexdigest(),'native_report_path':str(path.relative_to(ROOT)),'native_report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'main_registry_modified':False,'full_admission_reexecution':False}
(OUT/'lossless_gate_review.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
