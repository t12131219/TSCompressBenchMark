#!/usr/bin/env python3
"""Recompute primary-ledger M3 timing distributions, without creating a new run."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_in_run_measurement import recompute
from tsbench.application.m3_in_run_fixed_batch import DIRECTORY as FIXED_DIRECTORY, recompute as recompute_fixed
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.planner.m3_in_run_measurement_v2 import FIXED, SCHEMA as MEASUREMENT_V2
from tsbench.planner.m3_in_run_measurement_v3 import SCHEMA as MEASUREMENT_V3
from tsbench.planner.m3_in_run_measurement_v4 import GORILLA, SCHEMA as MEASUREMENT_V4
from tsbench.planner.m3_in_run_measurement_v5 import PCODEC_PAGES, SCHEMA as MEASUREMENT_V5
from tsbench.planner.m3_in_run_measurement_v6 import WHOLE, SCHEMA as MEASUREMENT_V6
from tsbench.planner.m3_in_run_measurement_v7 import ZFP, SCHEMA as MEASUREMENT_V7
from tsbench.planner.m3_in_run_measurement_v8 import TITCHY, SCHEMA as MEASUREMENT_V8
from tsbench.planner.m3_in_run_measurement_v9 import DICTIONARY, SCHEMA as MEASUREMENT_V9
from tsbench.planner.m3_in_run_measurement_v10 import LZBENCH, SCHEMA as MEASUREMENT_V10
from tsbench.planner.m3_in_run_measurement_v11 import SPRINTZ, SCHEMA as MEASUREMENT_V11
from tsbench.planner.m3_in_run_measurement_v12 import HUFF0, SCHEMA as MEASUREMENT_V12
from tsbench.planner.m3_in_run_measurement_v13 import CORAD, SCHEMA as MEASUREMENT_V13
from tsbench.planner.m3_in_run_measurement_v14 import SCHEMA as MEASUREMENT_V14
from tsbench.application import m3_in_run_corad as corad, m3_in_run_corad_pipeline as corad_pipeline
from tsbench.application import m3_in_run_huff0_table as huff0_table
from tsbench.application import m3_in_run_sprintz_query as sprintz
from tsbench.application import m3_in_run_lzbench as lzbench
from tsbench.application import m3_in_run_zstd_dictionary as dictionary
from tsbench.application import m3_in_run_gorilla_retained as retained_gorilla, m3_in_run_pcodec_pages as pcodec_pages
from tsbench.application import m3_in_run_whole as whole
from tsbench.application import m3_in_run_zfp as zfp, m3_in_run_titchy as titchy
from tsbench.application.m3_in_run_gorilla import DIRECTORY as GORILLA_DIRECTORY, recompute as recompute_gorilla
from tsbench.application.m3_in_run_batch import DIRECTORIES, recompute as recompute_batch
from tsbench.application.m3_sealed_ledger import full_run_source, full_run_rows
from tsbench.application.m3_report_stream import stream_report
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, parse_json, require
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan


def _directories(version):
    routes = ({**DIRECTORIES, GORILLA: GORILLA_DIRECTORY, PCODEC_PAGES: pcodec_pages.DIRECTORY}
              if version in (MEASUREMENT_V5, MEASUREMENT_V6, MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14) else
              {**DIRECTORIES, GORILLA: GORILLA_DIRECTORY} if version == MEASUREMENT_V4 else
              DIRECTORIES if version == MEASUREMENT_V3 else
              {FIXED: FIXED_DIRECTORY} if version == MEASUREMENT_V2 else {})
    failed_dirs = ({GORILLA: retained_gorilla.FAILED, PCODEC_PAGES: pcodec_pages.FAILED}
                   if version in (MEASUREMENT_V5, MEASUREMENT_V6, MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14) else {})
    if version in (MEASUREMENT_V6, MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[WHOLE] = whole.DIRECTORY
        failed_dirs[WHOLE] = whole.FAILED
    if version in (MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[ZFP] = zfp.DIRECTORY
        failed_dirs[ZFP] = zfp.FAILED
    if version in (MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[TITCHY] = titchy.DIRECTORY
        failed_dirs[TITCHY] = titchy.FAILED
    if version in (MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[DICTIONARY] = dictionary.DIRECTORY
        failed_dirs[DICTIONARY] = dictionary.FAILED
    if version in (MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[LZBENCH] = lzbench.DIRECTORY
        failed_dirs[LZBENCH] = lzbench.FAILED
    if version in (MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[SPRINTZ] = sprintz.DIRECTORY
        failed_dirs[SPRINTZ] = sprintz.FAILED
    if version in (MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14):
        routes[HUFF0] = huff0_table.DIRECTORY
        failed_dirs[HUFF0] = huff0_table.FAILED
    if version in (MEASUREMENT_V13, MEASUREMENT_V14):
        routes[CORAD] = corad.DIRECTORY
        failed_dirs[CORAD] = corad.FAILED
    return routes, failed_dirs


def _audit_row(root, plan, run, entries, routes, item, row, sessions):
    clock = plan['measurement']; version = clock['schema']; ran_adapter = False
    observed = row['measurement']
    frozen = clock['population'][row['work_item_id']]
    directory = routes.get(frozen.get('adapter'))
    if directory and (row['status'] == 'verified' or frozen.get('adapter') == ZFP and
                      item['route'] == zfp.array.ROUTE and row['status'] == 'quality_rejected' or
                      frozen.get('adapter') == CORAD and row['status'] == 'quality_rejected'):
        entry = entries[row['dataset_id']]
        adapter = frozen.get('adapter')
        if adapter == GORILLA:
            verify_gorilla = retained_gorilla.recompute if version in (MEASUREMENT_V5, MEASUREMENT_V6, MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14) else recompute_gorilla
            summary = verify_gorilla(root, plan, item, row, entry, run, observed, sessions)
        elif adapter == PCODEC_PAGES:
            summary = pcodec_pages.recompute(root, plan, item, row, entry, run, observed, sessions)
        elif adapter == WHOLE:
            summary = whole.recompute(root, plan, item, row, entry, run, observed, sessions)
        elif adapter == ZFP:
            summary = zfp.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == TITCHY:
            summary = titchy.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == DICTIONARY:
            summary = dictionary.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == LZBENCH:
            summary = lzbench.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == SPRINTZ:
            summary = sprintz.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == HUFF0:
            summary = huff0_table.recompute(root, plan, item, entry, run, row, observed, sessions)
        elif adapter == CORAD:
            verifier = corad_pipeline.recompute if version == MEASUREMENT_V14 else corad.recompute
            summary = verifier(root, plan, item, entry, run, row, observed, sessions)
        else:
            verify_batch = recompute_fixed if clock['schema'] == MEASUREMENT_V2 else recompute_batch
            summary = verify_batch(plan, item, row, entry, run, observed, sessions)
        ran_adapter = True
    else:
        summary = recompute(item, row, clock, observed, sessions)
    require(summary==observed.get('summary'),'M3 stored timing distributions differ from recomputation')
    return ({'work_item_id':row['work_item_id'],'dataset_id':row['dataset_id'],'route':row['route'],
                      'functional_status':row['status'],'measurement_status':observed['status'],
                      'trials':dict(Counter(f"{s['phase']}:{s['status']}" for s in observed['trials'])), 'summary':summary}, ran_adapter)


def audit(root, plan, run):
    check_m3_real_corpus_plan(root,plan)
    clock = plan['measurement']
    ledger, seal = full_run_source(plan,run)
    with stream_report(local_file(run,'report.json')) as (report, report_rows):
        result = _audit_stream(root,plan,run,clock,ledger,report,report_rows)
    body = {'schema':'bmk.m3-primary-ledger-measurement-audit/1','plan_content_id':plan['plan_content_id'],
            'run_id':run.name,'source_seal_id':seal,'partial_preflight':report['partial_preflight'],
            **result,'whole_plan_population':dict(Counter(i['status'] for i in clock['population'].values())),
            'timing_admitted':False,'stage_accepted':False,'qualification_granted':False}
    return {**body,'audit_id':content_id(body)}


def _audit_stream(root,plan,run,clock,ledger,report,report_rows):
    require(report['plan_content_id']==plan['plan_content_id'] and report['run_id']==run.name and
            all(report[k] is False for k in ('stage_accepted','timing_admitted','qualification_granted')),
            'in-run clock audit requires the original non-admitting report')
    selected = [i for i in plan['work_items'] if (report['route_filter'] is None or i['route'] in report['route_filter']) and
                ('dataset_filter' not in report or i['dataset_id'] in report['dataset_filter'])]
    if 'max_work_items' in report:
        selected = [i for i in selected if i['applicability']=='input_domain_matches'][:report['max_work_items']]
    require(report['partial_preflight']==(report['route_filter'] is not None or 'dataset_filter' in report or 'max_work_items' in report) and
            len(selected)==report['selected_corpus_decisions'], 'M3 timing audit selected a different population')
    statuses, decisions, sessions = Counter(), [], set()
    routes, failed_dirs = _directories(clock['schema'])
    anchors = {directory: set() for directory in routes.values()}
    failed_cases = {directory: set() for directory in failed_dirs.values()}
    entries = _entry_map(root, load_json(local_file(root, plan['definition']['plan']['path']))) if routes else {}
    with ledger.open('rb') as stream:
        complete = full_run_rows(plan,ledger) if not report['partial_preflight'] else None
        for item,prior in zip(selected,report_rows,strict=True):
            if complete is None:
                row = parse_json(stream.readline(),'M3 primary timing decision')
            else:
                row, wanted = next(complete,(None,None))
                require(wanted==item,'M3 timing full ledger omits a scoped corpus row')
            require(row==prior and all(row[k]==item[k] for k in ('work_item_id','dataset_id','selection','route','operation','applicability')),
                    'M3 timing work identity or primary ledger/report match differs')
            decision, ran_adapter = _audit_row(root, plan, run, entries, routes, item, row, sessions)
            if ran_adapter:
                observed = row['measurement']
                frozen = clock['population'][row['work_item_id']]
                adapter = frozen['adapter']
                if observed['anchors'] is not None:
                    anchors[routes[adapter]].add(frozen['case_id'])
                if adapter in failed_dirs and observed['failure_logs']:
                    failed_cases[failed_dirs[adapter]].add(frozen['case_id'])
            decisions.append(decision)
            statuses[decision['measurement_status']] += 1
        if complete is not None:
            for _ in complete:
                pass
        elif not report['obligations']:
            require(not stream.read(1),'unexpected rows after measured preflight')
    for directory, expected in {**anchors, **failed_cases}.items():
        anchor_dir = run / directory
        require(not anchor_dir.is_symlink() and (not anchor_dir.exists() or anchor_dir.is_dir()) and
                expected == ({p.name for p in anchor_dir.iterdir()} if anchor_dir.exists() else set()),
                'M3 timing anchor inventory differs from primary ledger')
    return {'measurement_decisions':decisions,'statuses':statuses,'group_processes_verified':len(sessions)}


if __name__=='__main__':
    p=ArgumentParser(description=__doc__)
    p.add_argument('--plan',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    out=p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path);out.add_argument('--verify',type=Path)
    a=p.parse_args()
    try:
        doc=audit(ROOT,load_json(a.plan),a.run.resolve(strict=True))
        if a.out:
            write_new(a.out,doc)
        else:
            require(doc==load_json(a.verify),'M3 primary measurement audit did not recompute')
        print(doc['audit_id'],dict(doc['statuses']),doc['group_processes_verified'])
    except (OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
