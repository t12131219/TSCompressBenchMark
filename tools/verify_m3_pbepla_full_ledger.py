#!/usr/bin/env python3
"""Independently audit PBEPLA historical prefixes and specialists in a sealed full M3 ledger."""
import argparse
from collections import Counter
from pathlib import Path

from verify_m3_pbepla_corpus import ROOT, PROGRESSIVE, REPLAY, ROUTES, audit_specialized, replay_corpus
from tsbench.application.batch_execution import _files
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, require


def audit(root, plan_path, run):
    plan = load_json(plan_path)
    ledger, seal = full_run_source(plan, run)
    pairs, products, obligations = {}, {}, []
    for row, scope in full_run_rows(plan, ledger):
        if row.get('selection') != 87:
            continue
        kind = row.get('entry_kind')
        if kind == 'specialized_product':
            slot = row['product_slot']
            require(slot not in products, 'duplicate PBEPLA specialist product')
            products[slot] = {k: v for k, v in row.items() if k not in ('entry_kind', 'selection')}
        elif kind == 'specialized_obligation':
            obligations.append({k: v for k, v in row.items() if k != 'entry_kind'})
        elif kind is None:
            (selection, route), ds = (row['selection'], row['route']), row['dataset_id']
            pair = pairs.setdefault(ds, {})
            require((selection, route) in ROUTES and row['applicability'] == 'input_domain_matches' and route not in pair,
                    'unexpected or duplicate PBEPLA source decision')
            pair[route] = (scope, row)
    require(all(set(p) == {PROGRESSIVE, REPLAY} for p in pairs.values()) and
            2*len(pairs) == sum((s['selection'], s['route']) in ROUTES for s in plan['work_items']),
            'incomplete PBEPLA corpus projection')
    corpus = replay_corpus(root, plan, run, pairs)
    paths = [a['path'] for r in corpus['replayed_samples'] if r['decoded'] for a in r['sample']['parts']]
    require(len(set(paths)) == len(paths), 'PBEPLA retained files reused across corpus decisions')
    binding = plan['specialized']['pbepla']
    specialists = audit_specialized(run, binding, obligations, {
        'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': products,
        'statuses': dict(Counter(r['status'] for r in products.values())), 'files': _files(run/'pbepla-specialized')}, replay=True)
    result = {'schema': 'bmk.m3-pbepla-full-ledger-audit/1', 'run_id': run.name, 'plan_id': plan['plan_content_id'],
              'run_seal_id': seal, **corpus, 'replayed_physical_files': len(paths), 'specialized': specialists,
              'corpus_replay_scope': 'new_native_process_per_historical_prefix_not_network_isolation_qualification',
              'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
    return {**result, 'audit_id': content_id(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'run', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        doc = audit(ROOT, args.plan, args.run.resolve(strict=True))
        write_new(args.out, doc)
        print(doc['audit_id'], doc['replayed_physical_files'], len(doc['window_failures']))
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
