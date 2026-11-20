#!/usr/bin/env python3
"""Recompute the CORAD ledger, exact quality and model/frame charges from sealed products."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json
from multiprocessing import get_context
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.corad_corpus_execution import _native, verify_cohort_ledger
from tsbench.application.m3_corad import SUCCESSFUL_RESTORES, prepare, project
from tsbench.application.m3_corad_specialized import audit_specialized, ledger_products
from tsbench.application.m3_corad_amendment_audit import audit_specialized as audit_amended
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.corad_corpus import C, INFERENCE, SOURCE, TRAINERS
from tsbench.planner.corad_training import STAGED_BRIDGE, VECTORS
from tsbench.planner.m3_corad import FOLDER, ROUTES
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.qualification.corad_wire import interpret
from tsbench.recovery import DIRECTORY

FRAME_CHARGES = ('header_bytes', 'embedded_model_bytes', 'tricklet_record_bytes', 'tail_bytes')


def identity(ref):
    return {k: ref[k] for k in ('bytes', 'sha256')}


def proc(records, key, mounts, *, native=None):
    op = records[key]
    require(op['operation'] == key and op['input_mounts'] == mounts and op['status'] == 'completed' and
            op['returncode'] == 0 and type(op['pid']) is int and op['pid'] > 0 and op['session_id'] and
            (op.get('native') is None if native is None else op['native'] == native),
            f'CORAD {key} terminal or mount binding differs')


def audit_cohort(folder, driver, material, terminals, replay, replay_all=False):
    b, train, tests = material
    verify_cohort_ledger(folder, b, train, tests, terminals)
    width = len(b['ordered_columns'])
    ntrain = len(train)//(8*width)
    assets, sessions, samples, fbytes = set(), [], [], Counter()
    for index, producer in enumerate(TRAINERS):
        start = index*(len(tests)+1)
        fit, *evaluations = terminals[start:start+1+len(tests)]
        prefix = f"products/{b['input_binding_id']}/{producer}"
        if fit['status'] != 'verified':
            require(fit['status'] in {'native_rejected', 'training_process_failed'} and
                    [r['frame_range'] for r in evaluations] == [e['absolute_rows'] for e in b['test_frames']],
                    'invalid CORAD failed fit or dependency terminals')
        else:
            deployment, model = fit['deployment'], fit['deployment']['model']
            dep = fit['deployment_asset']
            require(model['path'] == f'{prefix}/model.crd1' and dep['path'] == f'{prefix}/deployment.json' and
                    verify_asset(folder, dep).stat().st_size == dep['bytes'] and
                    all(deployment[k] == fit[k] for k in ('dataset', 'producer', 'producer_binding_id', 'input_binding_id')),
                    'CORAD model escaped its bound deployment')
            assets.update((model['path'], dep['path']))
            fit_native = fit['native']
            require(fit_native['native_status'] == 0 and fit_native['columns'] == width and
                    fit_native['output_bytes'] == model['bytes'], 'CORAD fit output differs')
            if producer == C:
                require(set(fit['processes']) == {'c-train'} and fit_native['rows'] == ntrain and
                        fit_native['training_samples'] == ntrain//4*width and 1 <= fit_native['iterations'] <= 6,
                        'CORAD C11 fit geometry differs')
                proc(fit['processes'], 'c-train', {'train': b['train']['values']}, native=fit_native)
            else:
                require(producer == SOURCE and set(fit['processes']) == {'source-train', 'source-pack'} and
                        set(fit['training_assets']) == {'dictionary_json', 'train_vectors'}, 'CORAD Source fit terminal differs')
                for name, ref in fit['training_assets'].items():
                    require(ref['path'] == f'{prefix}/{name}' and verify_asset(folder, ref).stat().st_size == ref['bytes'],
                            'CORAD Source producer asset differs')
                    assets.add(ref['path'])
                source_mounts = fit['processes']['source-train']['input_mounts']
                bridge = source_mounts[STAGED_BRIDGE]
                require(bridge['sha256'] == driver['source_bridge_sha256'] and 0 < bridge['bytes'] <= 1<<20,
                        'CORAD Source bridge mount differs from the plan')
                proc(fit['processes'], 'source-train', {STAGED_BRIDGE: bridge, VECTORS: identity(fit['training_assets']['train_vectors'])})
                packed = fit['processes']['source-pack']['input_mounts']
                _, _, arrays = interpret(verify_asset(folder, model).read_bytes())
                packed_arrays = arrays[:128] + b''.join(arrays[i:i+8] for base in (128, 136)
                                                        for i in range(base, len(arrays), 16))
                require(packed == {'arrays': {'bytes': len(packed_arrays), 'sha256': sha256(packed_arrays).hexdigest()}} and
                        fit_native['rows'] == 0,
                        'CORAD Source model packing envelope differs')
                proc(fit['processes'], 'source-pack', packed, native=fit_native)
        for r in (fit, *evaluations):
            for op in r.get('processes', {}).values():
                if op['pid'] is not None:
                    require(op['session_id'] and op['pid'] > 0, 'CORAD operation lacks process identity')
                    sessions.append(op['session_id'])
        for i, (r, f) in enumerate(zip(evaluations, b['test_frames'], strict=True)):
            if 'frame' in r:
                frame = r['frame']
                require(frame['path'] == f'{prefix}/heldout-{i}.crd1' and verify_asset(folder, frame).stat().st_size == frame['bytes'],
                        'CORAD frame identity or extent differs')
                assets.add(frame['path'])
            if r['status'] not in SUCCESSFUL_RESTORES:
                require(r['status'] in {'dependency_not_produced', 'encode_process_failed', 'native_rejected', 'restore_failed'},
                        'unexpected CORAD non-success frame terminal')
                continue
            frame_path = verify_asset(folder, frame)
            # The independent interpreter inside verify_cohort_ledger redoes the
            # quality comparison. Also reconcile the exact byte-charge decomposition.
            _, meta, _ = interpret(frame_path.read_bytes(), max_values=131072)
            charges = {k: meta[k] for k in FRAME_CHARGES}
            rows = f['absolute_rows'][1]-f['absolute_rows'][0]
            require((meta['rows'], meta['columns']) == (rows, width) and charges == r['frame_accounting'] and
                    sum(charges.values()) == frame['bytes'] and r['logical_value_bytes'] == f['values']['bytes'],
                    'CORAD logical shape or complete frame charge differs')
            fbytes.update(charges)
            enc, dec = f'encode-{i}', f'restore-{i}'
            require(set(r['processes']) == {enc, dec}, 'CORAD inference produced extra or missing calls')
            native = {'native_status': 0, 'rows': rows, 'columns': width}
            proc(r['processes'], enc, {'model': identity(model), 'test': f['values']},
                 native={**native, 'output_bytes': frame['bytes']})
            proc(r['processes'], dec, {'frame': identity(frame)}, native={**native, 'output_bytes': r['restore']['bytes']})
            if replay_all or (replay and not any(s['producer'] == producer for s in samples)):
                with tempfile.TemporaryDirectory(prefix='m3-corad-audit-') as tmp:
                    temp = Path(tmp)
                    logs = temp/'logs'
                    logs.mkdir()
                    ops = {}
                    restored, doc = _native(folder, driver, temp, logs, 'decode', {'frame': frame_path},
                                            ['decode', '/inputs/frame', str(rows), str(width)], 'values', ops)
                    process = ops['decode']
                    require(restored is not None and {'bytes': len(restored), 'sha256': sha256(restored).hexdigest()} == r['restore'] and
                            process['input_mounts'] == {'frame': identity(frame)} and process['session_id'] and
                            process['session_id'] not in sessions and doc == r['processes'][dec]['native'],
                            'CORAD detached sample recovery differs')
                    sessions.append(process['session_id'])
                samples.append({'producer': producer, 'frame': frame, 'restore': r['restore'], 'status': r['status']})
    return assets, sessions, samples, fbytes


def verify(root, plan, run, *, replay=False):
    check_m3_real_corpus_plan(root, plan)
    report_path, ledger_path, seal_path = (local_file(run, p) for p in ('report.json', 'ledger.jsonl', 'completion.json'))
    report, seal = load_json(report_path), load_json(seal_path)
    load_contract(root, 'm3-real-corpus-run').validate(report, 'M3 CORAD corpus run')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report_path), 'ledger_sha256': digest(ledger_path)}
    binding = plan.get('specialized', {}).get('corad')
    require(seal == {**body, 'seal_id': content_id(body)} and report['run_id'] == run.name and
            report['plan_content_id'] == plan['plan_content_id'] and report['partial_preflight'] and
            report['route_filter'] == sorted(r for _, r in ROUTES) and
            set(report['specialized']) == ({'corad'} if binding else set()), 'CORAD preflight scope or seal differs')
    obligations = [ob for ob in plan['obligations'] if (ob['selection'], ob['route']) in ROUTES]
    actual_obligations = report['obligations']
    require(len(obligations) == len(actual_obligations) == 17 and
            report['obligation_statuses'] == dict(Counter(o['status'] for o in actual_obligations)) and all(
            all(a[k] == b[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check'))
            for a,b in zip(actual_obligations, obligations, strict=True)), 'CORAD named obligations unexpectedly changed')
    specialist = report['specialized'].get('corad')
    specialized_rows = ledger_products(binding, specialist) if binding else []
    if not binding:
        require(report['obligation_statuses'] == {'not_run': 17} and all(o['evidence'] is None for o in actual_obligations),
                'unbound CORAD obligations were marked as executed')
    with ledger_path.open(encoding='utf-8') as f:
        for line, row in zip(f, [*report['rows'], *specialized_rows, *actual_obligations], strict=True):
            require(json.loads(line) == row, 'CORAD main ledger differs from sealed report')
    amendment = plan.get('corad_specialist_amendment')
    if amendment:
        specialized_audit = audit_amended(run, binding, amendment, actual_obligations, specialist, replay=replay)
    else:
        specialized_audit = audit_specialized(run, binding, actual_obligations, specialist, replay=replay) if binding else None
    wanted = [r for r in plan['work_items'] if (r['selection'], r['route']) in ROUTES]
    require(len(wanted) == len(report['rows']) == report['selected_corpus_decisions'] == 69 and report['selected_work_items'] == 39 and
            report['statuses'] == dict(Counter(r['status'] for r in report['rows'])), 'CORAD decision census differs')
    result = _corpus(root,plan,run,wanted,report['rows'],replay=replay)
    return {'schema': 'bmk.m3-corad-corpus-audit/1', 'run_id': run.name, 'run_seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], **result,
            **({'specialized': specialized_audit} if binding else {}),
            'obligations': report['obligation_statuses'], 'stage_accepted': False, 'timing_admitted': False,
            'qualification_granted': False}


def _corpus(root,plan,run,wanted,observed,*,replay=False,replay_all=False,dataset=None):
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    entries = {e['id']: e for e in load_full_manifest(root, definition['bindings']['manifest'], parse=False)['datasets']}
    items, actual = defaultdict(dict), defaultdict(dict)
    for w, row in zip(wanted, observed, strict=True):
        require(all(row[k] == w[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability')),
                'CORAD file-route decision identity differs')
        if w['applicability'] != 'input_domain_matches':
            require(row['status'] == w['applicability'] and row['reason'] == '; '.join(w['reasons']) and row['evidence'] is None,
                    'CORAD non-applicable input was not retained')
            continue
        items[w['dataset_id']][w['route']] = w
        actual[w['dataset_id']][w['route']] = row
    require(len(items)==13 and all(set(v)=={route for _,route in ROUTES} for v in items.values()),
            'CORAD full ledger does not bind three routes per applicable input')
    require(dataset is None or dataset in items, 'CORAD replay projection is not an applicable dataset')
    if dataset is not None:
        items,actual = {dataset:items[dataset]},{dataset:actual[dataset]}
    folder, driver = run/FOLDER, plan['build']['corad_corpus']
    for basename, info in driver['decoder']['files'].items():
        path = verify_asset(folder, {'path': f'{DIRECTORY}/{basename}', 'sha256': info['sha256']})
        require(path.stat().st_size == info['bytes'], 'CORAD staged ELF closure size differs')
    total_sessions, all_assets, samples, byte_charges = set(), set(), [], Counter()
    fits, frames, decisions = ({p: Counter() for p in TRAINERS}, {p: Counter() for p in TRAINERS},
                              {p: Counter() for p in (INFERENCE, *TRAINERS)})
    model_cost, deploy_cost = Counter(), Counter()
    with ProcessPoolExecutor(max_workers=min(len(os.sched_getaffinity(0)), driver['parallel_cohorts_max']),
                             mp_context=get_context('spawn')) as pool:
        for dataset, group in items.items():
            lanes = actual[dataset]
            proofs = {route: row['evidence'] for route, row in lanes.items()}
            require(all(e is not None and not e['execution_errors'] for e in proofs.values()), 'CORAD incomplete controller evidence')
            info = proofs[INFERENCE]
            material = prepare(root, entries[dataset], group)
            require(info['input_bindings'] == [b for b,_,_ in material], 'CORAD input bindings differ from re-ingested source')
            terminal_members = defaultdict(list)
            for p in TRAINERS:
                for record in [*proofs[p]['fits'], *info['evaluations'][p]]:
                    terminal_members[record['input_binding_id'],p].append(record)
            joined = []
            pending = []
            for index, prepared in enumerate(material):
                b = prepared[0]
                terminals = [r for p in TRAINERS for r in terminal_members.pop((b['input_binding_id'], p))]
                joined.append({'input_binding': b, 'terminals': terminals, 'execution_error': ''})
                pending.append(pool.submit(audit_cohort, folder, driver, prepared, terminals, replay and index == 0,replay_all))
            require(not terminal_members, 'CORAD unbound cohort terminals')
            recomputed = project(group, joined)
            require(all(all(lanes[r][k] == v for k,v in expected.items()) for r,expected in recomputed.items()),
                    'CORAD file status or aggregate accounting differs from recomputation')
            for task in pending:
                assets, sessions, replays, charges = task.result()
                require(not all_assets.intersection(assets) and not total_sessions.intersection(sessions) and len(sessions) == len(set(sessions)),
                        'CORAD reused artifact or process identities')
                all_assets.update(assets)
                total_sessions.update(sessions)
                samples.extend({'dataset_id': dataset, **s} for s in replays)
                byte_charges.update(charges)
            for p in TRAINERS:
                fits[p].update(proofs[p]['fit_statuses'])
                frames[p].update(info['frame_statuses'][p])
                model_cost[p] += proofs[p]['model_bytes']
                deploy_cost[p] += proofs[p]['deployment_metadata_bytes']
                decisions[p][lanes[p]['status']] += 1
            decisions[INFERENCE][lanes[INFERENCE]['status']] += 1
    if dataset is None:
        require(all_assets == {p.relative_to(folder).as_posix() for p in (folder/'products').rglob('*') if p.is_file()},
                'CORAD has unaccounted held-out or model products')
        require(all(sum(fits[p].values()) == 346 and sum(frames[p].values()) == 587 for p in TRAINERS),
                'CORAD fitted and held-out denominators differ')
    if replay_all:
        require(Counter(r['producer'] for r in samples)==Counter({p:sum(frames[p][s] for s in SUCCESSFUL_RESTORES) for p in TRAINERS}),
                'CORAD detached decode does not cover every restorable frame')
    return {'fits': fits, 'frames': frames, 'applicable_decisions': decisions,
            'complete_restorable_frame_bytes': sum(byte_charges.values()), 'frame_cost_breakdown': byte_charges,
            'model_bytes': model_cost, 'deployment_metadata_bytes': deploy_cost, 'detached_samples': samples}


def _select_full(plan,ledger):
    wanted, observed, obligations = [], [], []
    for row,item in full_run_rows(plan,ledger):
        if (row.get('selection'),row.get('route')) not in ROUTES:
            continue
        if item is not None and row.get('entry_kind') is None:
            wanted.append(item)
            observed.append(row)
        elif row.get('entry_kind') == 'specialized_obligation':
            obligations.append(row)
    require(len(wanted)==len(observed)==69 and len(obligations)==17 and
            sum(w['applicability']=='input_domain_matches' for w in wanted)==39,
            'CORAD sealed full-ledger population differs')
    return wanted,observed,obligations


def verify_full(root,plan,run,*,dataset=None,replay_all=False):
    """Read only the selected full-ledger rows; the report is hash-bound, not reloaded."""
    check_m3_real_corpus_plan(root,plan)
    ledger,seal_id = full_run_source(plan,run)
    wanted,observed,obligations = _select_full(plan,ledger)
    result = _corpus(root,plan,run,wanted,observed,replay_all=replay_all,dataset=dataset)
    body = {'schema':'bmk.m3-corad-full-ledger-corpus-audit/1','run_id':run.name,'run_seal_id':seal_id,
            'plan_content_id':plan['plan_content_id'],'dataset_projection':dataset,'corad_decisions_on_ledger':len(wanted),
            'scope':'sealed_corpus_only_specialist_status_census_not_specialist_replay_or_timing',
            'frame_only_native_replay':replay_all,'obligation_census':Counter(r['status'] for r in obligations),
            **result,'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**body,'audit_id':content_id(body)}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--replay', action='store_true')
    p.add_argument('--full-run',action='store_true')
    p.add_argument('--dataset',help='explicit diagnostic projection of full-run corpus audit only')
    out = p.add_mutually_exclusive_group()
    out.add_argument('--out',type=Path)
    out.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        require(a.full_run or a.dataset is None,'--dataset requires --full-run')
        plan,run = load_json(a.plan),a.run.resolve(strict=True)
        if a.full_run and a.replay:
            from tsbench.supervisor.timing_resource import reserve
            with reserve():
                result = verify_full(ROOT,plan,run,dataset=a.dataset,replay_all=True)
        elif a.full_run:
            result = verify_full(ROOT,plan,run,dataset=a.dataset)
        else:
            result = verify(ROOT,plan,run,replay=a.replay)
        if a.out:
            write_new(a.out,result)
        elif a.verify:
            require(result==load_json(a.verify),'CORAD audit differs from recomputation')
        else:
            print(json.dumps(result,indent=2))
    except (OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
