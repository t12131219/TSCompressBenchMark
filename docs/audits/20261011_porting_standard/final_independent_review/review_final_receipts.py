"""Pure-file linkage review of final current inventory/admission/SDK evidence."""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[4]
OUT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--inventory',default='docs/audits/20261011_porting_standard/source_build_inventory_r1/inventory-final.json')
parser.add_argument('--admission',default='docs/audits/20261011_porting_standard/lossless_admission_r1/admission.json')
parser.add_argument('--sdk',default='build/source-audits/simdcomp-sdk-port-standard-v30-20261011-r3')
parser.add_argument('--refresh',default='build/source-audits/native-sdk-registry-refresh-port-standard-v30-20261011-r3')
parser.add_argument('--output',default='stable_receipts_review.json')
args=parser.parse_args()
cache={}
errors=[]
references=0
def local(value):
    path=Path(value)
    return path if path.is_absolute() else ROOT/path
def sha(path):
    path=path.resolve()
    if path not in cache:cache[path]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return cache[path]
def check(condition,label):
    if not condition:errors.append(label)
def verify(path,expected,label):
    global references
    references+=1
    check(sha(path)==expected,label+': '+str(path))
def walk(value,label):
    if isinstance(value,list):
        for n,item in enumerate(value):walk(item,label+'/'+str(n))
    elif isinstance(value,dict):
        if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):verify(local(value['path']),value['sha256'],label)
        for key,digest in value.items():
            if key.endswith('_sha256') and isinstance(value.get(key[:-7]),str):verify(local(value[key[:-7]]),digest,label+'/'+key)
        for key,item in value.items():
            if isinstance(item,(list,dict)):walk(item,label+'/'+key)

inventory_path=ROOT/args.inventory
inventory=json.loads(inventory_path.read_text())
walk(inventory,'inventory')
check(inventory['active_codec_count']==33 and len(inventory['rows'])==33,'33 inventory rows')
check(inventory['execution_dependency_status_counts']=={'CURRENT_DECLARED_HASHES_VERIFIED_BY_ACTUAL_ADAPTER_FACTORY':33},'33 declared factory checks')
check(inventory['source_inventory_status_counts']=={'HASHES_VERIFIED_SELECTED_CLOSURE':1,'HASHES_VERIFIED_VENDOR_TREES':8,'UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT':24},'honest source inventory scope')
check(all(inventory[k] is False for k in ['formal_granted','full_parity_granted','rewrite_done_granted','referenced_evidence_semantic_status_promoted']),'inventory no parity/formal promotion')

admission_path=ROOT/args.admission
admission=json.loads(admission_path.read_text())
walk(admission,'admission')
verify(ROOT/'tools/onboard_requested_lossless.py',admission['driver_sha256'],'admission driver')
check(admission['status']=='PASS' and admission['algorithm_count']==6 and admission['native_profile_count']==12,'six admission/twelve profiles')
check(all(admission[k] is False for k in ['full_parity_granted','rewrite_done_granted','formal_granted','historical_evidence_rewritten']),'admission scope')
for entry in admission['files']:
    path=ROOT/entry['path']
    verify(path,entry['current_sha256'],'current onboarding')
    verify(admission_path.parent/'candidate'/entry['path'],entry['current_sha256'],'candidate equals current onboarding')
    verify(admission_path.parent/'before'/entry['path'],entry['before_sha256'],'original preserved onboarding')
source=admission['evidence']['source']
check(source['legal_source_case_count']==613 and source['source_end_marker_case_count']==2 and source['archived_source_failure_native_rejection_case_count']==8 and source['network_case_count']==6,'source counts kept separate')
elf=source['packages']['elf-plus']
check(elf['fresh_original_java_executed'] is True and elf['archived_rejections_fresh_original_java_executed'] is False,'Elf+ fresh Java/archive rejection scope')
for row in admission['evidence']['native']:
    test=row['native_test']
    check(test['compile']['returncode']==0 and test['run']['returncode']==0,'native compile/run exit')
    check(test['run']['command']==[str(local(test['executable']['path']))],'actual native test command')
    check(test['runtime_resolution_scope']=='LDD_SELECTED_FOR_SEPARATE_NATIVE_EXECUTABLE_NOT_PROC_MAP_TRACE','native test runtime scope')

sdk_folder=ROOT/args.sdk
sdk_path=sdk_folder/'report.json'
sdk=json.loads(sdk_path.read_text())
walk(sdk,'sdk')
check(sdk['status']=='PASS' and sdk['test_totals']=={'tests':504,'failures':0,'errors':0,'skipped':0},'SDK504 exact totals')
check(sdk['qualification_scope']=='DIRECT_PYTHON_UINT32_PLAIN_SSE4_1_AND_AVX2_SDK','SDK plain scope')
check(sdk['benchmark_five_layers']=='PENDING','SDK does not grant Bench')
verify(ROOT/'tools/qualify_simdcomp_sdk.py',sdk['driver_sha256'],'SDK driver')
verify(ROOT/'tools/audit_simdcomp_native.py',sdk['native_auditor_sha256'],'SDK auditor')
verify(sdk_folder/'pytest.xml',sdk['junit_sha256'],'SDK JUnit')
tests=list(ET.parse(sdk_folder/'pytest.xml').getroot().iter('testcase'))
check(len(tests)==504 and all(not list(t.iter('failure')) and not list(t.iter('error')) and not list(t.iter('skipped')) for t in tests),'SDK JUnit no skipped/failed')
check(all(command['returncode']==0 for command in sdk['commands']),'SDK command exits')
for entry in sdk['source_snapshot']:verify(ROOT/entry['path'],entry['sha256'],'SDK current Python snapshot')

refresh_folder=ROOT/args.refresh
refresh_path=refresh_folder/'report.json'
refresh=json.loads(refresh_path.read_text())
check(refresh['status']=='PASS' and refresh['source_ids_preserved'] is True,'SDK registration refresh')
codec_path=ROOT/'registry/codecs/simdcomp-u32.json'
onboard_path=ROOT/'registry/onboarding/simdcomp-u32.json'
check(codec_path.read_bytes()==(refresh_folder/'candidate/registry/codecs/simdcomp-u32.json').read_bytes(),'SDK codec candidate matches current')
check(onboard_path.read_bytes()==(refresh_folder/'candidate/registry/onboarding/simdcomp-u32.json').read_bytes(),'SDK onboarding candidate matches current')

runtime_path=ROOT/'docs/audits/20261011_port_standard_v30/runtime_profiles_v2/registration.json'
runtime=json.loads(runtime_path.read_text())
walk(runtime,'runtime registration')
check(runtime['status']=='REGISTERED' and runtime['profiles']==36 and len(runtime['fresh_process_observations'])==72,'runtime 36 capture/replay counts')
check(Counter(r['status'] for r in runtime['fresh_process_observations'])=={'ACTUAL_LOAD_CAPTURE_PASS':36,'FRESH_PROCESS_PRE_POST_LOAD_PASS':36},'runtime observation statuses')
for identity in runtime['identities']:
    entry=identity['runtime_profile']
    profile=json.loads((ROOT/entry['path']).read_text())
    walk(profile,'runtime profile/'+identity['codec'])
    check(profile['qualification']=='ACTUAL_CDLL_LOAD_ONLY_NOT_FULL_N1_OR_CODEC_PARITY','runtime profile qualification scope')

reviewed_reports=[{'path':str(p.relative_to(ROOT)),'sha256':sha(p)} for p in [inventory_path,admission_path,sdk_path,refresh_path,runtime_path]]
review_script_sha256=sha(Path(__file__))
result={'status':'PASS_STABLE_CURRENT_RECEIPTS' if not errors else 'FAIL','scope':'PURE_FILE_LINKAGE_REVIEW_NO_BUILD_CODEC_SOURCE_OR_TEST_EXECUTION','review_script_sha256':review_script_sha256,'hash_reference_count':references,'unique_files_hashed':len(cache),'inventory_active_codec_count':33,'source_tree_scope_counts':inventory['source_inventory_status_counts'],'strict_admission_profiles':12,'source_legal_cases':613,'sdk_test_count':504,'runtime_profiles':36,'runtime_fresh_observations':72,'full_parity_granted':False,'complete_n1_granted':False,'new_formal_granted':False,'errors':errors,'reviewed_reports':reviewed_reports}
(OUT/args.output).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(1 if errors else 0)
