#!/usr/bin/env python3
"""Replay Gorilla historical TV frames and snapshots against original T/V in a sealed M3 run."""
import argparse
from collections import Counter, defaultdict
from pathlib import Path

from verify_m3_gorilla import ROOT, ROUTES, audit_regression, audit_specialized, replay_corpus
import numpy as np
from tsbench.application.batch_execution import _files
from tsbench.application.m3_gorilla import RECORD, ROWS, milliseconds
from tsbench.application.m3_gorilla_specialized import NAMES
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, require, verify_asset
from tsbench.corpus_ingress import read_batches


def original_chunk(root, entry):
    """Check the complete declared source identity; keep only the first TV chunk."""
    require(entry['axis']['unit'] == 'second', 'Gorilla audit requires original civil-second samples')
    rows, cols = min(ROWS, entry['rows']), entry['value_count']
    result = np.empty(rows, dtype=RECORD)
    consumed = 0
    for batch in read_batches(root, entry):
        require(batch.start == consumed, 'Gorilla source batches out of order')
        n = min(batch.rows, rows-batch.start)
        if n > 0:
            result['t'][batch.start:batch.start+n] = milliseconds(np.frombuffer(batch.axis, dtype='<i8')[:n])
            result['v'][batch.start:batch.start+n] = np.frombuffer(batch.values, dtype='<u8').reshape(batch.rows, cols)[:n,0]
        consumed += batch.rows
    require(consumed == entry['rows'], 'Gorilla full source extent differs')
    return result.tobytes()


def audit(root, plan_path, run):
    plan = load_json(plan_path)
    ledger, seal = full_run_source(plan, run)
    products, regression, obligations, rows = defaultdict(dict), None, [], []
    for row, scope in full_run_rows(plan, ledger):
        if row.get('selection') != 7:
            continue
        kind = row.get('entry_kind')
        if kind == 'specialized_product':
            lane, slot = row['lane'], row['product_slot']
            require(lane in NAMES and slot not in products[lane], 'unexpected or duplicate Gorilla specialist')
            products[lane][slot] = {k: v for k, v in row.items() if k not in ('entry_kind','selection','lane')}
        elif kind == 'specialized_obligation':
            obligations.append({k: v for k, v in row.items() if k != 'entry_kind'})
        elif kind == 'implementation_regression':
            require(regression is None, 'duplicate Gorilla repair regression')
            regression = row
        elif kind is None:
            require(row['route'] in ROUTES, 'unexpected Gorilla corpus route')
            rows.append((row,scope))
    require(len(rows) == 69 and len({(r['dataset_id'],r['route']) for r,_ in rows}) == len(rows) and
            len(obligations) == 12 and regression is not None, 'incomplete Gorilla full-ledger projection')
    repair = plan['build']['gorilla_state_repair']['repair_build']
    for asset in (repair['programs']['tsbench_gorilla_corpus_control'], repair['dependency']):
        require(verify_asset(root, asset).stat().st_size == asset['bytes'], 'Gorilla repair build extent differs')
    corpus = replay_corpus(root, plan, run, rows, source_oracle=original_chunk)
    require(not corpus['failures'], 'Gorilla repaired corpus must not suppress failures')
    binding = plan['specialized']['gorilla']
    lanes = {}
    for lane, fixtures in products.items():
        directory = f'gorilla-specialized/{NAMES[lane]}'
        lane_plan = binding['tv_batch' if lane == 'tv-batch' else 'state']
        lanes[lane] = {'directory': directory, 'recovery_id': lane_plan['decoder']['recovery_id'],
                       'fixtures': fixtures, 'statuses': dict(Counter(r['status'] for r in fixtures.values())),
                       'files': _files(run/directory)}
    specialist = audit_specialized(root, run, binding, obligations, {'driver':binding['driver'],'lanes':lanes}, replay=True)
    samples = corpus['independently_decoded_samples']
    require(len(samples) == len({r['path'] for r in samples}), 'Gorilla corpus samples share physical files')
    doc = {'schema':'bmk.m3-gorilla-full-ledger-audit/1', 'run_id':run.name, 'run_seal_id':seal,
           'plan_id':plan['plan_content_id'], **corpus, 'specialized':specialist, 'regression':audit_regression(run,regression),
           'replayed_physical_files':len(samples), 'oracle':'original_first_chunk_column_0_civil_ms_and_binary64_bits',
           'corpus_decoder':'independent_python_xorchunk_parser',
           'timing_admitted':False, 'qualification_granted':False, 'stage_accepted':False}
    return {**doc, 'audit_id':content_id(doc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for n in ('plan','run','out'):
        parser.add_argument('--'+n, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = audit(ROOT, args.plan, args.run.resolve(strict=True))
        write_new(args.out, result)
        print(result['audit_id'], result['replayed_physical_files'])
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
