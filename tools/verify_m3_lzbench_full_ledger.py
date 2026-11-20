#!/usr/bin/env python3
"""Replay all historical session, worker and dictionary products in the locked full M3 ledger."""
import argparse
from collections import Counter
from pathlib import Path

import verify_m3_lzbench_profiles as profiles
import verify_m3_lzbench_sessions as sessions
from tsbench.application.batch_execution import _files
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, require


def audit(root, plan_path, run):
    plan = load_json(plan_path)
    ledger, seal = full_run_source(plan, run)
    session_routes, profile_routes = set(sessions.ROUTES), set(profiles.ROUTES)
    all_routes = session_routes | profile_routes
    lanes = {
        'lzbench_session': (sessions, session_routes, 'lzbench-session-specialized'),
        'lzbench_profiles': (profiles, profile_routes, 'lzbench-profile-specialized'),
    }
    bindings = {k: plan['specialized'][k] for k in lanes}
    slots = {slot: k for k, b in bindings.items() for slot in b['slots']}
    require(len(slots) == sum(len(b['slots']) for b in bindings.values()), 'lzbench specialist slot overlap')
    products = {k: {} for k in lanes}
    obligations = {k: [] for k in lanes}
    session_rows, worker_rows, seen = [], [], set()
    for row, item in full_run_rows(plan, ledger):
        kind = row.get('entry_kind')
        if kind == 'specialized_product' and (key := slots.get(row['product_slot'])):
            p = row['product_slot']
            slot = bindings[key]['slots'][p]
            selection = profiles.selection(slot) if key == 'lzbench_profiles' else (39 if slot['method']=='xz-session' else 40)
            require(row['selection']==selection and p not in products[key], 'duplicate or foreign lzbench specialist product')
            products[key][p] = {k:v for k,v in row.items() if k not in ('entry_kind','selection')}
        elif kind == 'specialized_obligation':
            for key, (_, routes, _) in lanes.items():
                if (row['selection'],row['route']) in routes:
                    obligations[key].append({k:v for k,v in row.items() if k!='entry_kind'})
        elif kind is None and (route := (row['selection'], row['route'])) in all_routes:
            key = (row['dataset_id'], *route)
            require(key not in seen, 'duplicate lzbench corpus decision')
            seen.add(key)
            (session_rows if route in session_routes | {sessions.DICT} else worker_rows).append((item,row))
    require(len(seen) == sum((i['selection'],i['route']) in all_routes for i in plan['work_items']),
            'incomplete lzbench corpus projection')
    session_totals, session_failures, retained, dicts = sessions.replay_corpus(
        root, plan, run, session_routes | {sessions.DICT}, session_rows)
    worker_totals, jobs, workers, _, worker_failures = profiles.replay_corpus(
        root, plan, run, worker_rows, include_dictionary=False)
    specialists = {}
    for key,(mod, _,directory) in lanes.items():
        binding, fixtures = bindings[key], products[key]
        require(set(fixtures) == set(binding['slots']), 'incomplete lzbench specialist projection')
        specialists[key] = mod.audit_specialized(run, binding, obligations[key], {
            'driver':binding['driver'], 'recovery_id':binding['decoder']['recovery_id'], 'fixtures':fixtures,
            'files':_files(run/directory), 'statuses':dict(Counter(p['status'] for p in fixtures.values())),
        }, replay=True)
    refs = [x['frame'] for x in retained] + [x[k] for x in dicts for k in ('frame','dictionary')] + [
        v['frame'] for x in workers for v in x['lanes'].values()]
    require(len(refs)==len({r['path'] for r in refs}), 'lzbench replay samples reuse physical files')
    body = {'schema':'bmk.m3-lzbench-full-ledger-audit/1', 'run_id':run.name, 'run_seal_id':seal,
            'plan_id':plan['plan_content_id'], 'corpus_decisions':len(seen), 'session_and_dictionary_totals':session_totals,
            'worker_totals':worker_totals, 'worker_native_jobs':jobs, 'failures':session_failures+worker_failures,
            'session_samples':retained, 'dictionary_samples':dicts, 'worker_samples':workers,
            'replayed_files':refs, 'specialized':specialists,
            'corpus_scope':'detached_historical_frames_and_dictionary_dependencies_in_new_native_processes',
            'specialist_scope':'network_isolated_replay',
            'stage_accepted':False, 'timing_admitted':False, 'qualification_granted':False}
    return {**body, 'audit_id':content_id(body)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','run','out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        doc = audit(sessions.ROOT, args.plan, args.run.resolve(strict=True))
        write_new(args.out, doc)
        print(doc['audit_id'], doc['corpus_decisions'], len(doc['replayed_files']))
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
