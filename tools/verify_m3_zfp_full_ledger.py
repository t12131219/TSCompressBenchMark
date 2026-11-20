#!/usr/bin/env python3
"""Independently audit ZFP retained corpus and specialist products in a sealed full M3 ledger."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from verify_m3_zfp_corpus import IsolatedReplay, LIMITS, ROOT, ROUTES, THREAD_ENV, replay_corpus
from tsbench.application.batch_execution import _files
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m3_zfp_specialized import audit_specialized
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, require
from tsbench.supervisor.timing_resource import reserve


def audit(root, plan_path, run, *, isolate_corpus=False):
    with ExitStack() as stack:
        if isolate_corpus:
            stack.enter_context(reserve())
            scratch = Path(stack.enter_context(TemporaryDirectory(prefix='m3-zfp-isolated-audit-')))
        else:
            scratch = None
        return _audit(root, plan_path, run, scratch)


def _audit(root, plan_path, run, scratch):
    plan = load_json(plan_path)
    ledger, seal = full_run_source(plan, run)
    routes, products, obligations = defaultdict(Counter), {}, []
    datasets, seen, absent = defaultdict(list), set(), []
    for row, scope in full_run_rows(plan, ledger):
        if row.get('selection') != 31:
            continue
        kind = row.get('entry_kind')
        if kind == 'specialized_product':
            slot = row['product_slot']
            require(slot not in products, 'duplicate ZFP specialist product')
            products[slot] = {k: v for k, v in row.items() if k not in ('entry_kind', 'selection')}
        elif kind == 'specialized_obligation':
            obligations.append({k: v for k, v in row.items() if k != 'entry_kind'})
        elif kind is None:
            key = row['dataset_id'], row['route']
            require((31, row['route']) in ROUTES and key not in seen, 'unexpected or duplicate ZFP corpus route')
            seen.add(key)
            routes[row['route']][row['status']] += 1
            if row['status'] in ('verified', 'quality_rejected'):
                require(row['applicability'] == 'input_domain_matches', 'ZFP replay source out of domain')
                datasets[row['dataset_id']].append((scope, row))
            else:
                require(row['reason'] and row['evidence'] is None, 'ZFP absent sample lacks a recorded reason')
                absent.append({k: row[k] for k in ('dataset_id', 'route', 'status', 'reason')})
    require(len(seen) == sum((s['selection'], s['route']) in ROUTES for s in plan['work_items']),
            'incomplete ZFP corpus projection')
    isolated = IsolatedReplay(root, plan, scratch) if scratch is not None else None
    counts, replayed = replay_corpus(root, plan, run, datasets, isolated=isolated)
    require(len(replayed) + len(absent) == len(seen), 'ZFP replay omitted a corpus decision')
    paths = [a['path'] for r in replayed for a in r['sample']['parts'].values()]
    require(len(set(paths)) == len(paths), 'ZFP retained files reused across corpus decisions')
    binding = plan['specialized']['zfp']
    specialists = audit_specialized(root, run, binding, obligations, {
        'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': products,
        'statuses': dict(Counter(r['status'] for r in products.values())), 'files': _files(run/'zfp-specialized')}, replay=True)
    result = {'schema': 'bmk.m3-zfp-full-ledger-audit/1', 'run_id': run.name, 'plan_id': plan['plan_content_id'],
              'run_seal_id': seal, 'route_statuses': routes, 'units': counts, 'absent': absent,
              'replayed_samples': replayed, 'replayed_physical_files': len(paths), 'specialized': specialists,
              'corpus_replay_scope': 'new_native_process_per_historical_payload_not_network_isolation_qualification',
              'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
    if isolated is not None:
        frame_count = sum(name in {'before', 'after'} or name.endswith('.frame')
                          for r in replayed for name in r['sample']['parts'])
        require(frame_count == len(isolated.sessions), 'ZFP isolated corpus replay omitted retained frames')
        result.update(schema='bmk.m3-zfp-full-ledger-audit/2',
                      corpus_replay_scope='one_new_bubblewrap_network_namespace_per_retained_frame_no_native_timing',
                      corpus_replay_runtime_id=isolated.runtime['recovery_id'],
                      corpus_replay_runtime=isolated.runtime,
                      corpus_replay_policy={'limits': LIMITS, 'environment': THREAD_ENV},
                      corpus_replay_launchers=isolated.launchers, isolated_corpus_processes=frame_count)
    return {**result, 'audit_id': content_id(result)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'run', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--isolate-corpus', action='store_true',
                        help='reopen each retained corpus frame with Bubblewrap; no direct-process fallback')
    args = parser.parse_args()
    try:
        result = audit(ROOT, args.plan, args.run.resolve(strict=True), isolate_corpus=args.isolate_corpus)
        write_new(args.out, result)
        print(result['audit_id'], len(result['replayed_samples']), result['replayed_physical_files'])
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
