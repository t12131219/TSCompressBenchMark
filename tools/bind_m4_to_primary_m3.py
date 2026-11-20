#!/usr/bin/env python3
"""Link replayed M4 diagnostics to the same inputs and native work in an M3 ledger.

Plan-only mode locks the matching work items and codec bytes but proves no new
runtime correspondence. A bounded live prefix is preliminary; only a fully
sealed run supports the final binding. No mode imports prior main-run clocks.
"""
from argparse import ArgumentParser
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_report_stream import stream_report
from tsbench.application.m4_cost_comparison import compare
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, parse_json, require
from tsbench.planner.m3_batch_timing import checked_file, reference
from tsbench.planner.m3_lzbench_workers import DRIVER as LZ_WORKERS_DRIVER

CASES = {'alp-fused': ('alp-auto', 'libalp_native.so'),
         'xz-opaque': ('xz-baseline', 'liblzbench_native.so'),
         'zstd-mt': ('zstd', 'liblzbench_native.so')}


def _file_id(ref):
    return {k: ref[k] for k in ('bytes', 'sha256')}


def _plan(path):
    plan = load_json(path)
    require(plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}),
            'M4 linkage source plan identity differs')
    return plan


def _one(items, label):
    items = list(items)
    require(len(items) == 1, f'M4 matching {label} is missing or ambiguous')
    return items[0]


def _match_row(name, case, row, run):
    require(row['status'] == 'verified', f'M4 {name} requires a verified primary M3 work item')
    e, cfg = row['evidence'], case['native_config']
    if name == 'zstd-mt':
        enc, dec = e['encode']['2'], e['decode_own']['2']
        source = case['original']['raw']
        retained = e['retained']['2']
        require(e['driver'] == LZ_WORKERS_DRIVER and e['codec'] == 'zstd' and
                e['source'] == source == dec['restored'] and case['geometry'] == {'byte_range': [0, source['bytes']]} and
                case['expected_m3_frame'] == enc['frame'] == dec['source_frame'] == _file_id(retained) and
                not e['unmet_worker_observations'] and enc['observed']['jobs']['worker_threads'] == 2 and
                dec['observed']['jobs']['worker_threads'] == 0 and
                all(cfg[k] == v['observed']['effective_parameters'] for k, v in [('encode', enc), ('decode', dec)]),
                'M4 Zstd candidate differs in native configuration, activity, full source or frame')
        checked_file(run, retained)
        return {'encode_jobs': enc['observed']['jobs'], 'decode_jobs': dec['observed']['jobs'],
                'retained_frame_checked': True}
    unit = _one((u for u in e['units'] if all(u.get(k) == v for k, v in case['geometry'].items())), f'{name} geometry')
    dispatch = 'falp-auto' if name == 'alp-fused' else 'default'
    dec = unit['decodes'][dispatch]
    require(unit['original'] == dec['restored'] == case['original'] and unit['artifact'] == case['expected_m3_frame'],
            f'M4 {name} primary M3 source/schema/restore/frame identity differs')
    enc, native = unit['encode']['native'], dec['native']
    if name == 'alp-fused':
        require(cfg['m3_decode_dispatch'] == dispatch == native['requested_backend'] and
                cfg['effective_backend'] == native['backend'] == 'falp-avx2' and
                cfg['threads'] == native['threads'] == enc['threads'] == 1 and
                cfg['fused_vectors'] == native['falp_avx2_vectors'] > 2 and enc['backend'] == 'alpn-auto-encoder',
                'M4 ALP candidate did not exercise the matched fused decode')
    else:
        require({'encode': enc, 'decode': native} == cfg, 'M4 XZ candidate native encode/decode settings differ')
    return {'encode': enc, 'decode': native, 'frame_and_restore_matched_by_sealed_identity': True}


def _live_prefix(plan, ledger, through, wanted_ids):
    """Read exactly a stated number of complete, ordered corpus rows."""
    require(type(through) is int and 0 < through <= len(plan['work_items']),
            'M4 live linkage extent is outside the frozen corpus')
    prefix_hash, size, selected = sha256(), 0, {}
    with ledger.open('rb') as stream:
        for n, item in enumerate(plan['work_items'][:through], 1):
            payload = stream.readline()
            require(payload.endswith(b'\n'), 'M4 live linkage needs a complete newline-terminated prefix')
            prefix_hash.update(payload)
            size += len(payload)
            row = parse_json(payload, f'M4 live M3 ledger line {n}')
            require(isinstance(row,dict) and row.get('entry_kind') is None and
                    all(row.get(k)==item[k] for k in ('work_item_id','dataset_id','selection','route','operation','applicability')),
                    'M4 live prefix has a foreign or out-of-order decision')
            if row['work_item_id'] in wanted_ids:
                require(row['work_item_id'] not in selected, 'M4 live prefix repeats a matching decision')
                selected[row['work_item_id']] = (n, sha256(payload).hexdigest(), row)
    return {'corpus_rows':through,'bytes':size,'sha256':prefix_hash.hexdigest()},selected


def audit(root, plan_path, cost_path, run=None, *, live_run=None, live_through=None):
    require((live_run is None)==(live_through is None) and not (run and live_run),
            'M4 live extent requires a separate live run and cannot replace sealed linkage')
    candidate = _plan(plan_path)
    cost = load_json(cost_path)
    profile_run = checked_file(root, cost['profile_seal']).parent
    timings = {k: checked_file(root, cost['cases'][k]['main_seal']).parent for k in CASES}
    link_path = checked_file(root, cost['multiscale_abi_diagnostics']['link'])
    require(compare(root, profile_run, timings, multiscale_link=link_path) == cost,
            'M4 profiling and cost evidence does not independently recompute')
    profile = _plan(local_file(profile_run, 'plan.json'))
    prior = _plan(checked_file(root, profile['m3_plan']))
    require(candidate['definition'] == prior['definition'] and
            candidate['build']['lzbench_workers'] == prior['build']['lzbench_workers'],
            'M4 primary M3 source definition or workers control differs')
    lock = load_json(checked_file(root, candidate['build']['lock']))
    build = candidate['build']
    current, previous = ({i['work_item_id']: i for i in x['work_items']} for x in (candidate, prior))
    require(set(profile['inputs']) == set(CASES), 'M4 case population differs')
    cases, by_id = {}, {}
    for name, case in profile['inputs'].items():
        key = case['work_item_id']
        item = current.get(key)
        require(item is not None and item == previous.get(key) and item['applicability'] == 'input_domain_matches',
                f'M4 {name} does not bind the same applicable planned M3 decision')
        plugin, lib = CASES[name]
        native = _one((f for f in lock['plugins'][plugin]['dependencies'] if Path(f['path']).name == lib), lib)
        native_path = local_file(root, native['path'])
        runtime = (build['fixed_batch']['decoder']['files'][f'lib/{lib}'] if name != 'zstd-mt'
                   else build['lzbench_workers']['dependency'])
        native_id = {'bytes': native_path.stat().st_size, 'sha256': digest(native_path)}
        require(native['sha256'] == native_id['sha256'] and _file_id(runtime) == native_id == cost['cases'][name]['same_native_library'],
                f'M4 {name} pristine dependency does not match candidate M3 native runtime bytes')
        cases[name] = {'profile_case_id': case['case_content_id'], 'work_item_id': key,
                       'dataset_id': item['dataset_id'], 'route': item['route'], 'operation_config_id': item['operation_config_id'],
                       'geometry': case['geometry'], 'original': case['original'], 'frame': case['expected_m3_frame'],
                       'same_native_library': native_id, 'runtime_match': None}
        by_id[key] = name
    require(set(cases) == set(CASES) and len(by_id) == len(CASES), 'M4 case population differs')
    binding = None
    if run is not None:
        run = run.resolve(strict=True)
        ledger, seal = full_run_source(candidate, run)
        report_rows = {}
        with stream_report(local_file(run,'report.json')) as (report,rows):
            require(report['partial_preflight'] is False and report['route_filter'] is None and
                    'dataset_filter' not in report and 'max_work_items' not in report and
                    report['run_id'] == run.name and report['plan_content_id'] == candidate['plan_content_id'],
                    'M4 linkage requires the unfiltered sealed M3 run')
            for item,row in zip(candidate['work_items'],rows,strict=True):
                key = row['work_item_id']
                require(key==item['work_item_id'],'M4 report row does not match frozen corpus order')
                if key in by_id:
                    require(key not in report_rows,'M4 report repeats a representative work item')
                    report_rows[key] = row
        require(report_rows.keys()==by_id.keys(),'M4 report omits a representative work item')
        seen = set()
        for row, _ in full_run_rows(candidate, ledger):
            k = row.get('work_item_id')
            if k in by_id:
                name = by_id[k]
                require(row == report_rows[k], f'M4 {name} primary ledger and report disagree')
                cases[name]['runtime_match'] = _match_row(name, profile['inputs'][name], row, run)
                seen.add(k)
        require(seen == set(by_id), 'M4 case omitted from sealed primary M3 ledger')
        binding = {'run_id': run.name, 'seal_id': seal, 'seal': reference(root, run / 'completion.json')}
    if live_run is not None:
        live_run = live_run.resolve(strict=True)
        ledger = local_file(live_run, 'ledger.jsonl')
        prefix, observed = _live_prefix(candidate,ledger,live_through,by_id)
        for work_id,name in by_id.items():
            found = observed.get(work_id)
            cases[name]['live_observation'] = None
            if found:
                ordinal, row_sha, row = found
                match = _match_row(name,profile['inputs'][name],row,live_run)
                if match.pop('frame_and_restore_matched_by_sealed_identity',False):
                    match['frame_and_restore_matched_by_prefix_identity'] = True
                cases[name]['live_observation'] = {'ledger_ordinal':ordinal,'row_sha256':row_sha,'match':match}
        provisional = {'schema':'bmk.m4-primary-m3-live-link/1','binding_state':'unsealed_prefix_only',
            'primary_plan':reference(root,plan_path),'primary_plan_id':candidate['plan_content_id'],
            'live_source':{'run_id':live_run.name,'ledger_path':ledger.relative_to(root).as_posix(),'prefix':prefix},
            'm4_cost_comparison':reference(root,cost_path),'m4_cost_comparison_id':cost['comparison_id'],
            'profile_seal':cost['profile_seal'],'cases':cases,'observed_case_count':len(observed),
            'scope':'preliminary_input_frame_restore_and_backend_link_no_sealed_report_or_clock_equivalence',
            'new_main_timing_inferred':False,'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
        return {**provisional,'link_id':content_id(provisional)}
    body = {'schema': 'bmk.m4-primary-m3-link/1', 'binding_state': 'sealed_runtime' if binding else 'plan_only_no_runtime_evidence',
            'primary_plan': reference(root, plan_path), 'primary_plan_id': candidate['plan_content_id'], 'primary_run': binding,
            'original_m4_source_plan': profile['m3_plan'], 'm4_cost_comparison': reference(root, cost_path),
            'm4_cost_comparison_id': cost['comparison_id'], 'profile_seal': cost['profile_seal'], 'cases': cases,
            'scope': 'input_build_geometry_frame_and_effective_native_work_only_not_clock_equivalence',
            'new_main_timing_inferred': False, 'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
    return {**body, 'link_id': content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    for name in ('m3-plan', 'cost'):
        p.add_argument('--' + name, type=Path, required=True)
    source = p.add_mutually_exclusive_group()
    source.add_argument('--m3-run', type=Path)
    source.add_argument('--m3-live-run', type=Path)
    p.add_argument('--live-through',type=int,help='exact frozen corpus prefix length (requires --m3-live-run)')
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out', type=Path)
    out.add_argument('--verify', type=Path)
    a = p.parse_args()
    try:
        doc = audit(ROOT, a.m3_plan.resolve(strict=True), a.cost.resolve(strict=True), a.m3_run,
                    live_run=a.m3_live_run,live_through=a.live_through)
        if a.out:
            write_new(a.out, doc)
        else:
            require(doc == load_json(a.verify), 'M4 primary M3 linkage differs from recomputation')
        print(doc['link_id'], doc['binding_state'])
    except (OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
