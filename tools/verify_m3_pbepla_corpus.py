#!/usr/bin/env python3
"""Audit a sealed PBEPLA corpus preflight and independently restore retained prefixes."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_pbepla import _call, _quality_layers, staged_windows
from tsbench.application.m3_pbepla_specialized import audit_specialized
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_pbepla import DRIVER, LAYOUT, PROGRESSIVE, REPLAY, ROUTES
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan


def sample_replay(control, run, sample, record, original, replay):
    require(all(sample[k] == record[k] for k in ('column','row_range','window_ordinal','logical_input_bytes','input_sha256')),
            'PBEPLA sample is not associated with its declared window')
    wires = [verify_asset(run, ref).read_bytes() for ref in sample['parts']]
    require(len(wires) == 3 and all(0 < len(wire) == ref['bytes'] <= LAYOUT['max_prefix_frame_bytes']
            for wire,ref in zip(wires,sample['parts'],strict=True)), 'PBEPLA retained prefix extent differs')
    if record['status'] == 'failed':
        return False
    restored = []
    for layer,wire in enumerate(wires,1):
        with TemporaryDirectory(prefix='m3-pbepla-audit-') as tmp:
            work = Path(tmp)
            (work/'input').mkdir(); (work/'out').mkdir()
            filename = f'0-{layer}'
            (work/'input'/filename).write_bytes(wire)
            packet, = _call(control,work,'restore-callback' if replay else 'restore-batch',[0],layer)
            require(packet == {'index':0,'status':'restored','layer':layer}, 'PBEPLA sample did not independently restore')
            restored.append((work/'out'/filename).read_bytes())
    recomputed = _quality_layers(original,wires,restored,{'rows':len(original)//8,
                              'native_full_bytes':len(wires[-1]),'replay':record['replay']},replay)
    require(all(record[k] == v for k,v in recomputed.items()), 'PBEPLA sample replay or quality differs')
    return True


def replay_corpus(root, plan, run, pairs):
    """Re-stage source windows and detach the recorded historical prefixes."""
    definition = load_json(verify_asset(root,plan['definition']['plan']))
    entries = load_full_manifest(root,definition['bindings']['manifest'],parse=False)['datasets']
    binding = plan['build']['pbepla_corpus']
    control = verify_asset(root,binding['executable'])
    verify_asset(root,binding['dependency'])
    replayed, parity, totals = [], Counter(), {r:Counter() for r in (PROGRESSIVE,REPLAY)}
    consistency_failures, window_failures = [], []
    for entry in entries:
        name = entry['id']
        pre, left = pairs[name][PROGRESSIVE]; replay, right = pairs[name][REPLAY]
        details = {r['route']:r['evidence'] for r in (left,right) if r['evidence'] is not None}
        for row in (left,right):
            if row['evidence'] is None:
                require(row['status']=='failed' and row['reason'], 'PBEPLA absent file evidence has no failure reason')
                consistency_failures.append({'route':row['route'],'dataset_id':name,'reason':row['reason']})
        if not details:
            continue
        counts = {r:Counter() for r in details}
        sample_seen = {r:set() for r in details}
        with TemporaryDirectory(prefix='m3-pbepla-source-audit-') as tmp:
            streams = {r:iter(doc['units']) for r,doc in details.items()}
            with staged_windows(root,entry,pre,replay,Path(tmp)) as source:
                for window,raw in source:
                    records = []
                    for route,stream in streams.items():
                        unit = next(stream,None)
                        require(unit is not None and (unit['column'],unit['row_range'],unit['window_ordinal'],unit['logical_input_bytes'],unit['input_sha256']) ==
                                (window.column,[window.start,window.end],window.ordinal,len(raw),sha256(raw).hexdigest()),
                                'PBEPLA corpus input coverage differs')
                        status = unit['status']; records.append(unit)
                        counts[route][status] += 1
                        counts[route]['logical_bytes'] += len(raw)
                        if status == 'failed':
                            require(unit['reason'], 'PBEPLA window failure lacks reason')
                            window_failures.append({'dataset_id':name,'route':route,
                                                    **{k:unit[k] for k in ('column','row_range','window_ordinal','input_sha256','reason')}})
                        else:
                            require(status in {'verified','quality_rejected'} and len(unit['layers'])==3 and
                                    [x['layer'] for x in unit['layers']]==[1,2,3] and
                                    [x['requested_eps'] for x in unit['layers']]==LAYOUT['requested_eps'] and
                                    all(x['bytes'] == x['header_bytes']+x['payload_bytes'] for x in unit['layers']) and
                                    unit['full_frame_bytes']==unit['layers'][-1]['bytes'] and
                                    unit['full_frame_sha256']==unit['layers'][-1]['frame_sha256'] and
                                    unit['quality_passed']==all(x['quality_passed'] for x in unit['layers'])==(status=='verified'),
                                    'PBEPLA prefix accounting or terminal differs')
                            counts[route]['full_frame_bytes'] += unit['full_frame_bytes']
                        sample = details[route]['retained_samples'].get(status)
                        if sample and (sample['column'],sample['window_ordinal'])==(window.column,window.ordinal):
                            done = sample_replay(control,run,sample,unit,raw,route==REPLAY)
                            replayed.append({'dataset_id':name,'route':route,'status':status,'decoded':done,'sample':sample})
                            sample_seen[route].add(status)
                    if len(records)==2 and all(r['status']!='failed' for r in records):
                        require(records[0]['layers']==records[1]['layers'],'PBEPLA independently observed batch/callback outputs differ')
                        parity['windows'] += 1
        for route,stream in streams.items():
            doc = details[route]; count = counts[route]; row = pairs[name][route][1]
            state = 'failed' if count['failed'] else 'quality_rejected' if count['quality_rejected'] else 'verified'
            require(next(stream,None) is None and doc['driver']==DRIVER and not doc['timing_admitted'] and
                    doc['verify_each_detached_prefix'] is True and
                    sample_seen[route]==doc['retained_samples'].keys() and
                    all(not count[s] or s in sample_seen[route] for s in ('verified','quality_rejected')) and
                    doc['failed_units']==count['failed'] and doc['quality_rejected_units']==count['quality_rejected'] and
                    doc['full_frame_bytes']==count['full_frame_bytes'] and doc['input_bytes_one_pass']==count['logical_bytes'] and
                    row['status']==state, 'PBEPLA file evidence does not reconcile')
            totals[route].update(count)
    return {'totals': totals, 'paired_identical': parity, 'replayed_samples': replayed,
            'window_failures': window_failures, 'file_failures_without_window_evidence': consistency_failures}


def verify(root, path, run, *, replay_specialized=False):
    plan = load_json(path)
    check_m3_real_corpus_plan(root,plan)
    report_path, ledger_path = (local_file(run,p) for p in ('report.json','ledger.jsonl'))
    report, seal = load_json(report_path), load_json(local_file(run,'completion.json'))
    load_contract(root,'m3-real-corpus-run').validate(report,'PBEPLA run report')
    require(report['partial_preflight'] and report['route_filter'] == [PROGRESSIVE,REPLAY] and
            report['plan_content_id'] == plan['plan_content_id'] == seal['plan_content_id'] and
            report['run_id'] == run.name == seal['run_id'] and seal['ledger_sha256'] == digest(ledger_path) and
            seal['report_sha256'] == digest(report_path) and seal['seal_id'] == content_id({k:v for k,v in seal.items() if k!='seal_id'}),
            'PBEPLA corpus run is not sealed for the declared scope')
    binding = plan.get('specialized', {}).get('pbepla')
    specialists = report['specialized'].get('pbepla')
    require(set(report['specialized']) == ({'pbepla'} if binding is not None else set()) and
            (binding is None) == (specialists is None) and (not replay_specialized or binding is not None),
            'PBEPLA specialist closure differs from plan')
    products = [] if binding is None else [
        {'entry_kind':'specialized_product','selection':87,**p} for p in specialists['fixtures'].values()]
    expected = [r for r in plan['work_items'] if (r['selection'],r['route']) in ROUTES]
    obligations = [r for r in plan['obligations'] if r['selection']==87]
    obligation_rows = report['obligations']
    require(report['selected_work_items'] == report['selected_corpus_decisions'] == len(expected) == 46 and
            len(obligations) == 9 and sum(len(x['planned_case_inputs']) for x in obligations) == 33 and
            report['obligation_statuses'] == dict(Counter(r['status'] for r in obligation_rows)) and
            (binding is not None or report['obligation_statuses'] == {'not_run':9}), 'PBEPLA denominator differs')
    with ledger_path.open(encoding='utf-8') as ledger:
        for line,row in zip(ledger,[*report['rows'],*products,*obligation_rows],strict=True):
            require(json.loads(line) == row, 'PBEPLA single ledger differs from report')
    for ob,row in zip(obligations,obligation_rows,strict=True):
        require(all(ob[k] == row[k] for k in ('obligation_id','selection','route','kind','check')) and
                (binding is not None or row['evidence'] is None),
                'PBEPLA specialist status differs')
    specialized_audit = None if binding is None else audit_specialized(
        run,binding,obligation_rows,specialists,replay=replay_specialized)
    pairs = {}
    for item,row in zip(expected,report['rows'],strict=True):
        require(all(item[k] == row[k] for k in ('work_item_id','dataset_id','route','operation','selection','applicability')) and
                item['applicability']=='input_domain_matches', 'PBEPLA row differs from accepted decision')
        pairs.setdefault(item['dataset_id'],{})[item['route']] = (item,row)
    require(report['statuses'] == dict(Counter(row['status'] for row in report['rows'])), 'PBEPLA file totals differ')
    corpus = replay_corpus(root, plan, run, pairs)
    return {'schema':'bmk.m3-pbepla-corpus-audit/1','plan_content_id':plan['plan_content_id'],'run_id':run.name,
            'run_seal_id':seal['seal_id'], **corpus,
            'specialized_executed':binding is not None,
            **({'specialized':specialized_audit} if specialized_audit is not None else {}),
            'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--replay-specialized',action='store_true')
    ns = parser.parse_args()
    print(json.dumps(verify(ROOT,ns.plan,ns.run.resolve(strict=True),replay_specialized=ns.replay_specialized),indent=2))
