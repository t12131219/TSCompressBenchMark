#!/usr/bin/env python3
"""Independently audit the real Zstd/XZ worker and dictionary run, not timing qualification."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_lzbench_profiles import audit_specialized, selection
from tsbench.application.m3_lzbench_workers import LANES, artifact, invoke, outcome, wire_info
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.lzbench_profiles import DICT, ROUTES
from tsbench.planner.m3_lzbench_workers import DRIVER, MAX_FRAME_RETAINED, input_size
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from verify_m3_zstd_dictionary import audit_dictionary
from verify_m3_lzbench_sessions import bound_control


def sample_frames(run,work,codec,proof,exe):
    kept={lane for lane,rec in proof['encode'].items() if rec['frame']['bytes']<=MAX_FRAME_RETAINED}
    require(proof['retained'].keys()==kept,'lzbench worker retention scope differs')
    result={}; expected=proof['source']; size=expected['bytes']
    for lane,ref in proof['retained'].items():
        encode=proof['encode'][lane]
        require(ref=={'path':f"retained/{work['work_item_id']}/{lane}.frame",**encode['frame']},'worker frame reference differs')
        frame=verify_asset(run,ref)
        require(wire_info(frame,codec,size)==encode['wire'],'worker retained wire structure differs')
        with TemporaryDirectory(prefix='tsbench-worker-replay-') as tmp:
            dest=Path(tmp)/'restored.bin'
            lanes=LANES[codec] if codec=='xz' and lane=='2' else ((lane,) if codec=='xz' else ('0',))
            observations={}
            for decode_lane in lanes:
                obs=invoke(exe,codec,'decode',decode_lane,frame,dest,size)
                req=0 if decode_lane=='synchronous' else int(decode_lane)
                require(artifact(dest)==expected and 0<=obs['jobs']['worker_threads']<=req,'worker retained frame replay differs')
                observations[decode_lane]=obs['jobs']
        result[lane]={'frame':ref,'native_decode_jobs':observations,'restored':expected}
    return result


def replay_corpus(root, plan, run, projected, *, include_dictionary=True):
    """Verify worker participation and independently replay retained products."""
    definition=load_json(verify_asset(root,plan['definition']['plan']))
    entries={e['id']:e for e in load_full_manifest(root,definition['bindings']['manifest'],parse=False)['datasets']}
    worker=bound_control(root,plan,'lzbench_workers')
    trainer=bound_control(root,plan,'zstd_dictionary') if include_dictionary else None
    results={r:Counter() for r in ROUTES.values() if include_dictionary or r!=DICT}
    dictionary_samples=[]; worker_samples=[]; failed=[]; native_jobs=[]
    for a,b in projected:
        require(all(a[k]==b[k] for k in ('work_item_id','dataset_id','selection','route','operation','applicability')),
                'lzbench profile result does not match frozen decision')
        route,status=b['route'],b['status']; totals=results[route]; totals[status]+=1
        proof=b['evidence']; entry=entries[a['dataset_id']]
        if a['applicability']=='condition_not_triggered':
            require(status=='condition_not_triggered' and proof is None and b['reason']=='; '.join(a['reasons']),
                    'lzbench ineligible worker input was not preserved')
            continue
        require(a['applicability']=='input_domain_matches' and status in ('verified','failed'),'lzbench profile execution missing')
        if status=='failed':
            require(b['reason'],'unexplained lzbench profile nonpass')
            failed.append({k:b[k] for k in ('route','dataset_id','reason')})
            if proof is None:
                continue
        require(proof is not None,'verified lzbench profile lacks evidence')
        if route==DICT:
            sample=audit_dictionary(root,run,trainer,a,b,entry)
            if sample: dictionary_samples.append(sample)
            totals[proof['tier']+'_files']+=1
            totals['verified_frames']+=sum(f['status']=='verified' for f in proof['frames'])
            continue
        codec=route.split('-')[0]; size=input_size(a,entry)
        require(proof['driver']==DRIVER and not proof['timing_admitted'] and proof['codec']==codec and
                proof['source']=={'bytes':size,'sha256':entry['canonical']['values_sha256']},'lzbench worker source identity differs')
        missing=outcome(proof)
        equal=len({r['frame']['sha256'] for r in proof['encode'].values()})==1
        require(missing==proof['unmet_worker_observations'] and bool(missing)==(status=='failed') and
                equal==proof['all_encoded_frames_equal'],'lzbench worker outcome does not match the evidence')
        samples=sample_frames(run,a,codec,proof,worker)
        if samples: worker_samples.append({'dataset_id':a['dataset_id'],'route':route,'lanes':samples})
        totals['logical_bytes']+=size
        if equal: totals['identical_encoded_frames_cases']+=1
        native_jobs.append({'dataset_id':a['dataset_id'],'route':route,'input_bytes':size,'shared_frame':proof['encode']['2']['frame'] if codec=='xz' else None,
                            'encode':{k:r['observed']['jobs'] for k,r in proof['encode'].items()},
                            'own_decode':{k:r['observed']['jobs'] for k,r in proof['decode_own'].items()},
                            'shared_decode':{k:r['observed']['jobs'] for k,r in proof['decode_shared'].items()}})
    return results, native_jobs, worker_samples, dictionary_samples, failed


def verify(root,plan_path,run,*,replay_specialized=False):
    plan=load_json(plan_path); check_m3_real_corpus_plan(root,plan)
    files={p:local_file(run,p) for p in ('report.json','completion.json','ledger.jsonl')}
    report=load_json(files['report.json']); seal=load_json(files['completion.json'])
    load_contract(root,'m3-real-corpus-run').validate(report,'lzbench profile report')
    require(report['partial_preflight'] and report['route_filter']==sorted(ROUTES.values()) and
            report['run_id']==seal['run_id']==run.name and report['plan_content_id']==seal['plan_content_id']==plan['plan_content_id'] and
            seal['report_sha256']==digest(files['report.json']) and seal['ledger_sha256']==digest(files['ledger.jsonl']) and
            seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}), 'lzbench profile report seal or scope differs')
    wanted=[r for r in plan['work_items'] if (r['selection'],r['route']) in ROUTES]
    ob=[r for r in plan['obligations'] if (r['selection'],r['route']) in ROUTES]
    scope=report['obligations']
    require(report['selected_work_items']==39 and report['selected_corpus_decisions']==len(wanted)==69 and
            len(ob)==13 and report['obligation_statuses']==dict(Counter(r['status'] for r in scope)) and
            set(report['specialized'])=={'lzbench_profiles'},'lzbench profile denominator differs')
    evidence=report['specialized']['lzbench_profiles']; binding=plan['specialized']['lzbench_profiles']
    products=[{'entry_kind':'specialized_product','selection':selection(binding['slots'][p]),**doc} for p,doc in evidence['fixtures'].items()]
    with files['ledger.jsonl'].open(encoding='utf-8') as f:
        for line,row in zip(f,[*report['rows'],*products,*scope],strict=True):
            require(json.loads(line)==row,'lzbench profile main ledger differs from the sealed report')
    for a,b in zip(ob,scope,strict=True):
        require(all(a[k]==b[k] for k in ('selection','route','obligation_id','kind','check')),'lzbench profile obligation identity differs')
    specialized=audit_specialized(run,binding,scope,evidence,replay=replay_specialized)
    results, native_jobs, worker_samples, dictionary_samples, failed = replay_corpus(root,plan,run,zip(wanted,report['rows'],strict=True))
    require(report['statuses']==dict(Counter(r['status'] for r in report['rows'])) and
            sum(v['condition_not_triggered'] for v in results.values())==30,'lzbench main status accounting differs')
    return {'schema':'bmk.m3-lzbench-profiles-audit/1','run_id':run.name,'plan_content_id':plan['plan_content_id'],'run_seal_id':seal['seal_id'],
            'totals':results,'native_jobs':native_jobs,'worker_samples':worker_samples,'dictionary_samples':dictionary_samples,
            'failures':failed,'specialized':specialized,'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',required=True,type=Path); p.add_argument('--run',required=True,type=Path)
    p.add_argument('--replay-specialized',action='store_true')
    a=p.parse_args()
    print(json.dumps(verify(ROOT,a.plan,a.run.resolve(strict=True),replay_specialized=a.replay_specialized),indent=2))
