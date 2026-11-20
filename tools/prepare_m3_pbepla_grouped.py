#!/usr/bin/env python3
"""Freeze identical PBEPLA-RR windows, fixed PBEP prefixes and native failures from r40."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_sprintz_timing import check, relative
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, require
from tsbench.planner.m3_pbepla import DRIVER, LAYOUT, PROGRESSIVE, REPLAY, ROUTES, windows
from tsbench.recovery import plan_recovery
from tsbench.supervisor.isolated_worker import launcher_lock, validate_limits

LIMITS = {'address_space_bytes': 512 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 60}
CODE = ('native/measurement/pbepla_grouped/main.cpp','native/measurement/pbepla_grouped/CMakeLists.txt',
        'plugins/codecs/pbepla-rr/corpus_control.cpp','src/tsbench/application/m3_pbepla.py',
        'src/tsbench/planner/m3_pbepla.py','src/tsbench/qualification/pbepla_progressive.py',
        'src/tsbench/application/m3_sealed_ledger.py','tools/prepare_m3_pbepla_grouped.py',
        'src/tsbench/supervisor/isolated_worker.py','src/tsbench/supervisor/process.py','src/tsbench/recovery.py')


def _route(row, geometry, item):
    evidence = row['evidence']
    require(evidence['driver'] == DRIVER and evidence['verify_each_detached_prefix'] and
            len(evidence['units']) == len(geometry), 'invalid PBEPLA corpus prefix population')
    units = []
    for unit, w in zip(evidence['units'], geometry, strict=True):
        require((unit['column'],unit['window_ordinal'],unit['row_range'],unit['logical_input_bytes']) ==
                (w.column,w.ordinal,[w.start,w.end],8*w.rows), 'PBEPLA native timing window does not match its canonical extent')
        base = {k:unit[k] for k in ('column','window_ordinal','row_range','logical_input_bytes','input_sha256','status')}
        if unit['status'] == 'failed':
            require(unit['reason'] and 'layers' not in unit, 'PBEPLA failed window cannot supply a successful decode anchor')
            units.append({**base,'reason':unit['reason']})
            continue
        require(unit['status'] in ('verified','quality_rejected') and
                unit['quality_passed'] == (unit['status']=='verified') and
                unit['quality_passed'] == all(t['quality_passed'] for t in unit['layers']) and
                unit['full_frame_bytes'] == unit['layers'][-1]['bytes'] and
                unit['full_frame_sha256'] == unit['layers'][-1]['frame_sha256'] and
                [t['requested_eps'] for t in unit['layers']] == LAYOUT['requested_eps'], 'PBEPLA prefix validation metadata differs')
        replay = unit['replay']
        require((replay is not None) == (item['route']==REPLAY), 'PBEPLA stream work differs from the frozen route')
        units.append({**base,'layers':unit['layers'],'replay':{k:v for k,v in replay.items() if k!='first_sink_ns'} if replay else None})
    terminal = 'failed' if any(u['status']=='failed' for u in units) else 'quality_rejected' if any(
        u['status']=='quality_rejected' for u in units) else 'verified'
    require(terminal==row['status'], 'PBEPLA failed windows cannot be omitted or relabeled')
    return units


def freeze(root, plan_file, run, worker):
    validate_limits(LIMITS,file_ceiling=LIMITS['file_bytes'])
    source = load_json(plan_file)
    ledger, seal = full_run_source(source,run)
    entries = _entry_map(root,load_json(check(root,source['definition']['plan'])))
    pairs = {}
    for row,item in full_run_rows(source,ledger):
        if 'entry_kind' in row or (row['selection'],row['route']) not in ROUTES:
            continue
        entry = pairs.setdefault(row['dataset_id'],{})
        require(row['route'] not in entry and row['applicability']=='input_domain_matches','foreign or repeated PBEPLA decision')
        entry[row['route']] = item,row
    require(set(pairs)==entries.keys(),'PBEPLA frozen full input denominator differs')
    cases = []
    for ds, pair in pairs.items():
        entry = entries[ds]
        require(set(pair)=={PROGRESSIVE,REPLAY},'PBEPLA route pair not complete')
        geometry = windows(entry,pair[PROGRESSIVE][0],pair[REPLAY][0])
        references = {}
        for route,(item,row) in pair.items():
            body = {k:item[k] for k in ('work_item_id','route','dataset_id','canonical_object_id','operation_config_id','operation')}
            body.update(status=row['status'],reason=row['reason'],configuration=item['input'],source_file=entry['file'],
                        units=_route(row,geometry,item))
            references[route] = body
            cases.append({**body,'case_id':content_id(body)})
        left,right = (references[r]['units'] for r in (PROGRESSIVE,REPLAY))
        require(all({k:v for k,v in a.items() if k!='replay'}=={k:v for k,v in b.items() if k!='replay'} for a,b in zip(left,right,strict=True)),
                'PBEPLA matched windows no longer share fixed prefix and failure identities')
    frozen = source['build']['pbepla_corpus']['dependency']
    exe = relative(root,worker)
    runtime = plan_recovery(root,{},(),tools={'pbepla-grouped':{k:exe[k] for k in ('path','sha256')}},libraries=[frozen])
    body = {'schema':'bmk.m3-pbepla-grouped-population/1','source_plan':relative(root,plan_file),'source_run':run.relative_to(root).as_posix(),
            'source_seal':seal,'worker':exe,'runtime':runtime,'layout':LAYOUT,'limits':LIMITS,'launchers':launcher_lock(),
            'code':{p:digest(local_file(root,p)) for p in CODE},'cases':cases,
            'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**body,'population_id':content_id(body)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('source-plan','source-run','worker'):
        p.add_argument('--'+flag,type=Path,required=True)
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path)
    out.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        d = freeze(ROOT,*(x.resolve(strict=True) for x in (a.source_plan,a.source_run,a.worker)))
        if a.out:
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,d)
        else:
            require(d==load_json(a.verify),'PBEPLA population does not recompute')
        print(json.dumps({'population_id':d['population_id'],'files_by_status':Counter(c['status'] for c in d['cases']),
                          'windows_by_status':Counter(u['status'] for c in d['cases'] for u in c['units'])}))
    except (ContractError,OSError) as e:
        p.exit(1,f'{e}\n')


if __name__ == '__main__':
    main()
