#!/usr/bin/env python3
"""Audit the sealed M3 Zstd/XZ session and optional dictionary preflight."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_session import CONFIG, invoke, observation
from tsbench.application.m3_lzbench_specialized import audit_specialized
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_lzbench_session import DRIVER, INPUT_SPAN, OUTPUT_SPAN, RETAIN_BYTES, ROUTES, input_size
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_zstd_dictionary import KEY as DICT
from verify_m3_zstd_dictionary import audit_dictionary


def bound_control(root, plan, key):
    binding = plan['build'][key]
    for name in ('dependency', 'executable'):
        asset = binding[name]
        path = verify_asset(root, asset)
        require(path.stat().st_size == asset['bytes'], 'lzbench native build extent differs')
    return path


def replay_corpus(root, plan, run, scoped, projected):
    """Check whole session facts and decode immutable historical frame samples."""
    include_sessions = bool(set(ROUTES) & scoped)
    include_dict = DICT in scoped
    definition = load_json(verify_asset(root,plan['definition']['plan']))
    entries = {e['id']:e for e in load_full_manifest(root,definition['bindings']['manifest'],parse=False)['datasets']}
    exe = bound_control(root,plan,'lzbench_session') if include_sessions else None
    dict_exe = bound_control(root,plan,'zstd_dictionary') if include_dict and 'zstd_dictionary' in plan['build'] else None
    totals = {r:Counter() for _,r in sorted(scoped)}
    failures, replayed, dict_samples = [], [], []
    for item,row in projected:
        require(all(item[k]==row[k] for k in ('work_item_id','dataset_id','selection','route','operation','applicability')),
                'lzbench session work row differs from frozen work item')
        route = row['route']; codec = route.split('-')[0]
        totals[route][row['status']] += 1
        if row['status']=='failed':
            failures.append({k:row[k] for k in ('route','dataset_id','reason')})
        if route==DICT[1] and dict_exe is None:
            require(row['status']=='pending_driver' and row['evidence'] is None,'unbound Zstd dictionary row differs')
            continue
        if route==DICT[1] and row['evidence'] is not None:
            observed = audit_dictionary(root,run,dict_exe,item,row,entries[item['dataset_id']])
            if observed:
                dict_samples.append(observed)
            proof = row['evidence']
            totals[route][proof['tier']+'_files']+=1
            totals[route]['verified_frames']+=sum(f['status']=='verified' for f in proof['frames'])
            totals[route]['training_input_bytes']+=proof['train_bytes']
            continue
        if row['status']!='verified':
            require(row['status']=='failed' and row['reason'] and row['evidence'] is None, 'unexplained lzbench session nonpass')
            continue
        require(route!=DICT[1],'verified dictionary route lacks native evidence')
        proof = row['evidence']; entry = entries[item['dataset_id']]; size = input_size(item,entry)
        source = {'bytes':size,'sha256':entry['canonical']['values_sha256']}
        require(not row['reason'] and proof['source']==proof['recovered']==source and proof['codec']==codec and
                proof['configuration']==CONFIG[codec] and proof['driver']==DRIVER and not proof['timing_admitted'] and
                proof['continuous_sessions_per_direction']==1 and proof['span_bytes']=={'input':INPUT_SPAN,'output':OUTPUT_SPAN},
                'lzbench session source, recovery, or operation identity differs')
        frame = proof['frame']
        observation(proof['encode'],size,frame['bytes']); observation(proof['decode'],frame['bytes'],size)
        totals[route]['logical_bytes'] += size; totals[route]['frame_bytes'] += frame['bytes']
        for op in ('encode','decode'):
            obs = proof[op]
            totals[route][op+'_native_calls'] += obs['calls']
            totals[route][op+'_zero_input_finish_calls'] += obs['zero_input_finish_calls']
        retained = proof['retained_frame']
        require((retained is not None)==(frame['bytes']<=RETAIN_BYTES),'lzbench frame retention policy differs')
        if retained is not None:
            require(retained=={**frame,'path':f"retained/{item['work_item_id']}/native.frame"},'lzbench retained frame reference differs')
            with TemporaryDirectory(prefix='m3-lzbench-session-audit-') as temp:
                output = Path(temp)/'out'
                invoke(exe,codec,'decode',verify_asset(run,retained),output,size)
                require(output.stat().st_size==size and digest(output)==source['sha256'],'lzbench retained frame replay differs')
            replayed.append({'route':route,'dataset_id':item['dataset_id'],'frame':retained,'restored':source})
    return totals, failures, replayed, dict_samples


def verify(root, plan_path, run, *, replay_specialized=False):
    plan = load_json(plan_path)
    check_m3_real_corpus_plan(root,plan)
    files = {name:local_file(run,name) for name in ('report.json','ledger.jsonl','completion.json')}
    report, seal = (load_json(files[n]) for n in ('report.json','completion.json'))
    load_contract(root,'m3-real-corpus-run').validate(report,'lzbench session report')
    include_dict = DICT[1] in (report['route_filter'] or [])
    include_sessions = any(r in (report['route_filter'] or []) for r in ROUTES.values())
    scoped = (set(ROUTES) if include_sessions else set()) | ({DICT} if include_dict else set())
    require(report['partial_preflight'] and report['route_filter']==sorted(route for _,route in scoped) and
            report['run_id']==seal['run_id']==run.name and report['plan_content_id']==seal['plan_content_id']==plan['plan_content_id'] and
            seal['report_sha256']==digest(files['report.json']) and seal['ledger_sha256']==digest(files['ledger.jsonl']) and
            seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}), 'lzbench session run seal or scope differs')
    wanted = [r for r in plan['work_items'] if (r['selection'],r['route']) in scoped]
    obligations = [r for r in plan['obligations'] if (r['selection'],r['route']) in scoped]
    binding = plan.get('specialized',{}).get('lzbench_session') if include_sessions else None
    specs = report['specialized'].get('lzbench_session')
    require(set(report['specialized'])==({'lzbench_session'} if binding is not None else set()) and
            (binding is None)==(specs is None) and (not replay_specialized or binding is not None),'lzbench specialist scope differs')
    product_rows = [] if specs is None else [
        {'entry_kind':'specialized_product','selection':39 if binding['slots'][p]['method']=='xz-session' else 40,**s}
        for p,s in specs['fixtures'].items()]
    expected_obligations = Counter('verified' if binding and (r['selection'],r['route']) in ROUTES else 'not_run' for r in obligations)
    require(report['selected_work_items']==report['selected_corpus_decisions']==len(wanted)==23*len(scoped) and
            report['obligation_statuses']==dict(expected_obligations), 'lzbench denominator differs')
    with files['ledger.jsonl'].open(encoding='utf-8') as ledger:
        for line,item in zip(ledger,[*report['rows'],*product_rows,*report['obligations']],strict=True):
            require(json.loads(line)==item, 'lzbench session main ledger differs from report')
    for ob,row in zip(obligations,report['obligations'],strict=True):
        require(all(ob[k]==row[k] for k in ('selection','route','obligation_id','kind','check')) and
                ((binding and (ob['selection'],ob['route']) in ROUTES) or row['status']=='not_run' and row['evidence'] is None),
                'lzbench session obligation differs')
    specialized = None if binding is None else audit_specialized(
        run,binding,[r for r in report['obligations'] if (r['selection'],r['route']) in ROUTES],specs,replay=replay_specialized)
    totals, failures, replayed, dict_samples = replay_corpus(root,plan,run,scoped,zip(wanted,report['rows'],strict=True))
    require(report['statuses']==dict(Counter(r['status'] for r in report['rows'])), 'lzbench session status accounting differs')
    return {'schema':'bmk.m3-lzbench-session-audit/1','run_id':run.name,'plan_content_id':plan['plan_content_id'],
            'run_seal_id':seal['seal_id'],'totals':totals,'replayed_samples':replayed,'failures':failures,
            **({'dictionary_samples':dict_samples} if include_dict else {}),
            **({'specialized':specialized} if specialized is not None else {}),
            'specialized_obligations':report['obligation_statuses'],'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}


if __name__=='__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True); p.add_argument('--run',type=Path,required=True)
    p.add_argument('--replay-specialized',action='store_true')
    args = p.parse_args()
    print(json.dumps(verify(ROOT,args.plan,args.run.resolve(strict=True),replay_specialized=args.replay_specialized),indent=2))
