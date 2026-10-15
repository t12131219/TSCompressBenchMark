"""Read-only audit of restored Gorilla run; write a separate reviewable report."""
from pathlib import Path
from collections import Counter
import hashlib
import json
import sys
from tsbench.artifact import read_bundle_prefix, validate_descriptor
from tsbench.provenance import execution_provenance
from tsbench.records import read_jsonl
from tsbench.trial_analysis import scheduled_rows, case_coverage

ROOT = Path(__file__).resolve().parents[2]
run = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'runs/gorilla-real-records-20261015'
manifest = json.loads((run/'manifest.json').read_text())
rows, tail = read_jsonl(run/'observations.jsonl')
assert tail is None
selected, planned = scheduled_rows(manifest, rows)
coverage = [case_coverage(manifest, c, selected, planned) for c in manifest['cases']]
assert len(manifest['cases']) == 24 and all(c['complete'] for c in coverage)
assert len(manifest['schedule']) == len(selected) == 504
assert all(r['status']=='ok' and r['verification']['passed'] and r['verification']['input_unchanged'] for r in selected.values())
assert manifest['execution_source_unchanged']
assert manifest['execution_provenance']['source_id'] == execution_provenance()['source_id']
for file in manifest['source_snapshot']['files']:
    current = ROOT/'benchmark/src/tsbench'/file['module']
    assert 'sha256:'+hashlib.sha256(current.read_bytes()).hexdigest() == file['sha256']
exact = [r for r in rows if r.get('phase')=='qualification' and r.get('event')=='terminal' and r.get('qualification_kind')=='exact']
assert len(exact)==24 and all(r['status']=='ok' and r['independent_recovery']['decoder_process'] for r in exact)
cases={c['case_id']:c for c in manifest['cases']}
chunks={};raw_lists={};wire_records=[]
for cid, case in cases.items():
    trial=next(r for k,r in sorted(selected.items()) if k[0]==cid and r.get('artifact_path'))
    path=Path(trial['artifact_path']);wire=path.read_bytes()
    assert 'sha256:'+hashlib.sha256(wire).hexdigest()==trial['artifact_hash']
    d,body=read_bundle_prefix(wire);validate_descriptor(d,body)
    record={'case_id':cid,'artifact':str(path.relative_to(ROOT)),'wire_sha256':trial['artifact_hash'],'stored_bytes':len(wire),'payload_bytes':len(body),'header_bytes':len(wire)-len(body),'codec_input_bytes':d['codec_input_bytes']}
    if case['codec']=='gorilla-prometheus-xor':
        entries=d['joint_parts'];group=[{'channel':p['channel'],'row_start':p['row_start'],'row_stop':p['row_stop'],'raw_bytes':p['length'],'sha256':p['sha256']} for p in entries]
        chunks[(case['dataset_id'],case['method_id'])]=group
        raw_lists[(case['dataset_id'],case['method_id'])]=[body[p['offset']:p['offset']+p['length']] for p in entries]
        record['raw_encxor_chunks']=group
    wire_records.append(record)
comparisons=[]
for dataset in manifest['resolved_config']['datasets']:
    key=dataset['id'];a=chunks[(key,'gorilla-canonical')];b=chunks[(key,'gorilla-optimized')]
    assert a==b
    assert raw_lists[(key,'gorilla-canonical')]==raw_lists[(key,'gorilla-optimized')]
    comparisons.append({'dataset_id':key,'all_chunks_byte_identical':True,'chunks':len(a)})
report={'schema':'tsbench.gorilla-run-audit/1','passed':True,'run':str(run.relative_to(ROOT)),'run_id':manifest['run_id'],'requested_cases':24,'complete_cases':sum(c['complete'] for c in coverage),'planned_trials':504,'status_counts':dict(Counter(r['status'] for r in selected.values())),'gorilla_successful_trials':sum(cases[k[0]]['codec']=='gorilla-prometheus-xor' for k in selected),'fresh_exact_decoders':len(exact),'execution_source_unchanged':True,'source_id':manifest['execution_provenance']['source_id'],'canonical_optimized_complete_chunk_lists':comparisons,'artifacts':wire_records,'verification':'every measurement checked bitwise and input_unchanged; exact-input qualification spawned fresh wire-only decoders','scope':'selected sources and fixed nested windows; full objects and repeated T charged; no universal performance ranking'}
(ROOT/'docs/gorilla_integration/run-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('PASS: 24/24 cases, 504/504 trials, 24 fresh exact decoders, 6 complete raw chunk comparisons')
