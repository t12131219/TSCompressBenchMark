#!/usr/bin/env python3
"""Spot-check already written M3 measurements without sealing or modifying a live run."""
from argparse import ArgumentParser
from hashlib import sha256
from os import fstat
from pathlib import Path
import sys

from audit_m3_in_run_measurement import ROOT, _audit_row, _directories
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, parse_json, require, verify_asset

COORDINATES = ('work_item_id','dataset_id','selection','route','operation','applicability')


def _read_prefix(stream, items, wanted, *, through=None):
    limit = fstat(stream.fileno()).st_size
    prefix = sha256()
    picked, committed = [], 0
    for i, item in enumerate(items):
        remaining = limit - stream.tell()
        if not remaining:
            break
        line = stream.readline(remaining)
        if not line.endswith(b'\n'):
            require(stream.tell() == limit, 'M3 ledger shrank or changed during the observation')
            break  # The one writer may be in the middle of appending this line.
        row = parse_json(line, f'M3 live ledger line {i+1}')
        require(not row.get('entry_kind') and all(row.get(k) == item[k] for k in COORDINATES),
                'M3 live ledger is not an ordered prefix of the supplied unfiltered plan')
        prefix.update(line)
        committed += 1
        if (item['dataset_id'],item['route']) in wanted:
            picked.append((item,row))
        if through is not None and committed==through:
            break
    require(through is None or committed==through,'M3 ledger has not reached the declared complete-line extent')
    return committed, stream.tell(), prefix.hexdigest(), picked


def check(root, plan, run, picks, *, through=None):
    require(through is None or type(through) is int and 0<through<=len(plan['work_items']), 'invalid M3 prefix extent')
    require(through is not None or not (run/'completion.json').exists(), 'sealed run must use the full M3 audit')
    require(plan['plan_content_id'] == content_id({k:v for k,v in plan.items() if k!='plan_content_id'}),
            'M3 live ledger candidate plan identity differs')
    known = {(i['dataset_id'],i['route']) for i in plan['work_items']}
    require(picks and len(picks) <= 4 and picks <= known, 'choose 1 to 4 known dataset/route pairs')
    with local_file(run,'ledger.jsonl').open('rb') as stream:
        count, read_bytes, prefix, picked = _read_prefix(stream, plan['work_items'], picks,through=through)
    matches = {(i['dataset_id'],i['route']) for i,_ in picked}
    require(matches == picks and len(picked) == len(picks), 'a selected spot-check is not present in the complete-line prefix')
    sessions = set()
    routes, _ = _directories(plan['measurement']['schema'])
    context = verify_asset(root,plan['definition']['plan'])
    require(context.stat().st_size==plan['definition']['plan']['bytes'],'M3 live definition extent differs')
    entries = _entry_map(root,load_json(context))
    checked = []
    for item,row in picked:
        detail, _ = _audit_row(root,plan,run,entries,routes,item,row,sessions)
        checked.append({k:v for k,v in detail.items() if k!='summary'})
    result = {'schema':'bmk.m3-live-spot-check/1','scope':'ordered_complete_line_prefix_and_selected_measurement_records_not_a_seal',
            'run_id':run.name,'candidate_plan_id':plan['plan_content_id'],'complete_corpus_lines_observed':count,
            'prefix_sha256':prefix,'ledger_bytes_read':read_bytes,'measurements_recomputed':checked,
            'group_processes_verified':len(sessions),'source_bound_to_plan_by_seal':False,
            'timing_admitted':False,'stage_accepted':False,'qualification_granted':False}
    if through is not None:
        result['prefix_fixed_at_corpus_rows'] = through
        result['audit_id'] = content_id(result)
    return result


def main():
    import json
    p = ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--pick',action='append',nargs=2,metavar=('DATASET','ROUTE'),required=True)
    p.add_argument('--through',type=int,help='exact number of complete rows, for stable recomputation')
    output = p.add_mutually_exclusive_group()
    output.add_argument('--out',type=Path)
    output.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        require(len(a.pick)==len({tuple(x) for x in a.pick}), 'duplicate spot-check coordinate')
        require(not (a.out or a.verify) or a.through is not None,'persisted spot-check requires a fixed --through extent')
        result = check(ROOT,load_json(a.plan),a.run.resolve(strict=True),{tuple(x) for x in a.pick},through=a.through)
        if a.out:
            write_new(a.out,result)
        elif a.verify:
            require(result==load_json(a.verify),'M3 live spot-check differs from recomputation of the same prefix')
        else:
            print(json.dumps(result,ensure_ascii=False,indent=2))
    except (OSError, ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()
