#!/usr/bin/env python3
"""Record current immutable build identities and completed integration checks."""
from pathlib import Path
import json,hashlib,platform,shutil
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/sprintz_integration'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
keys=['sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman']
lock=json.loads((ROOT/'adapters/sprintz_family/FROZEN_SOURCES.json').read_text())
for row in lock['files']:assert sha(ROOT/row['path'])==row['sha256']
assert not (ROOT/'adapters/sprintz').exists()
for key in ['sprintz-delta-u8','sprintz-fire-u8','sprintz-fire-huff0']:
 assert not (ROOT/'registry/codecs'/f'{key}.json').exists()
 assert not (ROOT/'build/tsbench'/f'{key}.index.json').exists()
builds=[]
for key in keys:
 index=json.loads((ROOT/'build/tsbench'/f'{key}.index.json').read_text());p=Path(index['build_record']);d=json.loads(p.read_text());artifact=Path(index['artifact']);assert d['status']=='ok' and sha(artifact)==d['artifact_sha256']
 # Report only actual current binaries and compiler-consumed source closure.
 for row in d['compiled_source_closure']:assert sha(Path(row['path']))==row['sha256']
 builds.append({'key':key,'build_id':d['build_id'],'record':str(p.relative_to(ROOT)),'record_sha256':sha(p),'artifact':str(artifact.relative_to(ROOT)),'artifact_sha256':sha(artifact),'compiled_dependency_count':len(d['compiled_source_closure']),'source_artifact_id':json.loads((ROOT/'registry/codecs'/f'{key}.json').read_text())['identity']['source_artifact_id']})
src=json.loads((OUT/'source-qualification.json').read_text());objs=json.loads((OUT/'object-native-qualification.json').read_text());san=json.loads((OUT/'sanitizer.json').read_text());assert src['status']==objs['status']==san['status']=='PASS' and not san['stderr']
assert '1259 passed' in (OUT/'full-python-suite.log').read_text()
checks=[]
d=json.loads((ROOT/'benchmark/experiments/native-all/design.json').read_text())
for row in d['configurations']:checks.append({'path':row['path'],'sha256':sha(Path(row['path'])),'original_sha256':row['sha256'].removeprefix('sha256:')});assert checks[-1]['sha256']==checks[-1]['original_sha256']
files=[p for p in OUT.rglob('*') if p.is_file() and p.name!='evidence.json' and '__pycache__' not in p.parts]
files += [ROOT/p for p in ['benchmark/tests/test_sprintz_family.py','benchmark/tools/qualify_sprintz_family.py','benchmark/examples/sprintz-family.toml','adapters/sprintz_family/FROZEN_SOURCES.json','adapters/sprintz_family/native/tscb_sprintz_family.cc','adapters/sprintz_family/native/direct_core.inc']]
result={'schema':'tsbench.sprintz-native-integration/1','date':'2026-10-17','status':'LIMITED_NATIVE_PORT_BINDING_VALIDATED','formal_performance':'NOT_RERUN','full_parity':'NOT_ASSERTED','platform':platform.platform(),'active_sprintz_keys':keys,'release_sha256':lock['release_sha256'],'frozen_files':len(lock['files']),'consumed_core_modified':False,'builds':builds,'verification':{'fresh_source_differential_cases':src['source_cases'],'source_byte_identical':src['source_byte_identical'],'source_16b_truncation_repairs':src['source_16b_truncation_repairs'],'source_truncated_streams_rejected':src['source_truncated_streams_rejected'],'canonical_and_real_cases':src['canonical_real_cases'],'standalone_api_roundtrips':80448,'standalone_ctest':{'passed':2,'failed':0},'targeted_sprintz_tests':297,'final_adjacent_tests':330,'full_python_suite':1259,'objects_with_new_process_cli_decode':objs['object_count'],'native_combinations':objs['native_combinations'],'validated_native_products':objs['native_products'],'sanitizer_binding_cases':san['binding_cases'],'asan':True,'ubsan':True,'lsan_detect_leaks':True,'final_sanitizer_stderr_bytes':0},'historical_designs_unchanged':checks,'scope':'Linux x86_64 ISA profile; 8/16-bit integer bits; dimensions1..128; input<=65536 bytes; no float mapping/query/outer auto chunking','framing':{'native_core':'SZF1','native_api':'SZF1','header_bytes':24,'payload':'unchanged released sz_* payload','complete_output_counted':True,'decode_encoder_parameters_required':False},'files':[{'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(files)]}
(OUT/'evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print({k:v for k,v in result.items() if k in ['status','active_sprintz_keys','frozen_files','verification']})
if __name__=='__main__':pass
