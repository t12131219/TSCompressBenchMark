"""Independent pure-file hash and count validation; does not execute drivers."""
from pathlib import Path
from collections import Counter
import hashlib
import json

ROOT=Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
OUT=Path('/tmp/tscb-final-gap-counterexamples')
cache={}
checks=[]
errors=[]
def verify(path, expected, label):
    path=Path(path)
    if not path.is_absolute():path=ROOT/path
    if path not in cache:
        cache[path]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    checks.append(str(path))
    if cache[path]!=expected:errors.append({'label':label,'path':str(path),'expected':expected,'actual':cache[path]})
def explicit_hash_pairs(value,label):
    if isinstance(value,list):
        for n,v in enumerate(value):explicit_hash_pairs(v,label+'/'+str(n))
    if not isinstance(value,dict):return
    for key,expected in value.items():
        if key.endswith('_sha256') and key[:-7] in value and isinstance(value[key[:-7]],str):
            verify(value[key[:-7]],expected,label+'/'+key)
    if isinstance(value.get('path'),str) and 'sha256' in value:verify(value['path'],value['sha256'],label)
    for key,v in value.items():
        if isinstance(v,(dict,list)):explicit_hash_pairs(v,label+'/'+key)

summary=json.loads((ROOT/'docs/audits/20261011_porting_standard/fresh_source_summary.json').read_text())
explicit_hash_pairs(summary,'fresh-summary')
source_path=ROOT/summary['source_report']['path']
source=json.loads(source_path.read_text())
verify(ROOT/'tools/verify_preserved_source_oracles.py',source['driver_sha256'],'source-driver')
explicit_hash_pairs(source,'source-report')
java_counts={}
for name,record in source['packages'].items():
    isolated=source_path.parent/'isolated/Compression_Rewrite'
    for relative,expected in record['source_files'].items():verify(isolated/'Source'/name/relative,expected,name+'/source')
    for relative,expected in record['native_source_files'].items():verify(isolated/'ReWrite'/name/relative,expected,name+'/native')
    report=json.loads(Path(record['result']).read_text())
    cases=report['cases']
    counts=dict(Counter(case['status'] for case in cases))
    if counts!=record['case_status_counts']:errors.append({'label':name+'/case-status-count','expected':record['case_status_counts'],'actual':counts})
    java_counts[name]=counts
for name,record in source['completed'].items():
    for relative,expected in record['source_files'].items():verify(source_path.parent/'isolated/Compression_Rewrite/Source'/name/relative,expected,name+'/source')
    verify(source_path.parent/'isolated/Compression_Rewrite/ReWrite'/name/'tests/oracle'/f'{name}_oracle.py',record['oracle_driver_sha256'],name+'/oracle-driver')
rust_path=ROOT/summary['lzss']['path']
rust=json.loads(rust_path.read_text())
explicit_hash_pairs(rust,'rust-report')
verify(ROOT/'tools/verify_lzss_fresh_source.py',rust['driver_sha256'],'rust-driver')
verify(ROOT/'tools/verify_lzss_cpp.py',rust['input_driver_sha256'],'rust-input-driver')
verify(ROOT/'adapters/lzss_raw/tests/fixtures/reference_vectors.json',rust['fixture_sha256'],'rust-fixture')
for relative,expected in rust['source_files'].items():verify(rust_path.parent/'original/lzss'/relative,expected,'rust/source')
for relative,expected in rust['void_source_files'].items():verify(rust_path.parent/'original/void'/relative,expected,'rust/void')
for relative,key in [('src/main.rs','oracle_wrapper_sha256'),('Cargo.toml','oracle_cargo_manifest_sha256'),('Cargo.lock','oracle_cargo_lock_sha256'),('target/release/tscb_original_lzss_oracle','oracle_binary_sha256')]:
    verify(rust_path.parent/relative,rust[key],'rust/'+key)
if len(rust['cases'])!=282 or any(c['status']!='PASS' or c.get('both_cross_decode') is not True for c in rust['cases']):errors.append({'label':'rust-case-universe'})
link=json.loads((ROOT/'docs/audits/20261011_porting_standard/lossless_cli_vendor_link.json').read_text())
explicit_hash_pairs(link,'cli-vendor-link')
verify(ROOT/'adapters/rewrite_lossless/FROZEN_APIS.json',link['frozen_lock_sha256'],'frozen-api-lock')
for name,entry in link['algorithms'].items():
    for file in entry['files']:
        for label,path in file['paths'].items():verify(path,file['hashes'][label],name+'/cli-link/'+label)
        if len(set(file['hashes'].values()))!=1:errors.append({'label':name+'/cli-link/core-equality'})
result={'status':'PASS_READONLY_CURRENT_SCOPED_SOURCE_EVIDENCE' if not errors else 'FAIL','checked_hash_reference_count':len(checks),'unique_files_checked':len(cache),'errors':errors,'java_case_counts':java_counts,'java_legal_cases':sum(v.get('PASS',0) for v in java_counts.values()),'rust_case_count':len(rust['cases']),'full_parity_granted':False,'benchmark_qualification_granted':False,'formal_granted':False,'scope':'PURE_FILE_REVIEW_NO_SOURCE_OR_CODEC_EXECUTION'}
(OUT/'fresh_source_readonly_report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
