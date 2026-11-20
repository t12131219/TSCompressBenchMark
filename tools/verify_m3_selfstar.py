#!/usr/bin/env python3
"""Audit SElf* whole-column products, ordered parity and specialist evidence."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_selfstar import audit_specialized, restore, wire_facts, _live_adds
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_selfstar import DRIVERS
from tsbench.planner.selfstar import BLOCK

KEYS = ('input_bytes', 'artifact_bytes', 'native_bits', 'native_payload_bytes', 'block_header_bytes',
        'object_envelope_bytes', 'blocks')


def source_digests(root, entry):
    """Independently re-stream all cells, including the sign bit of zero."""
    values = sha256()
    per_column = [sha256() for _ in range(entry['value_count'])]
    n = 0
    for batch in read_batches(root, entry):
        values.update(batch.values)
        data = np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, len(per_column))
        for i, column in enumerate(per_column):
            column.update(data[:, i].tobytes())
        n += batch.rows
    require(n == entry['rows'] and values.hexdigest() == entry['canonical']['values_sha256'],
            'SElf* auditor input does not match the canonical corpus')
    return [c.hexdigest() for c in per_column]


def _sample(root, run, binding, row, live):
    case = row['evidence']
    first = case['units'][0]
    sample = case['retained_sample']
    require(sample['path'] == f"retained/{row['work_item_id']}/full-column-zero.bmk" and
            sample['sha256'] == first['frame_sha256'] and sample['bytes'] == first['artifact_bytes'],
            'SElf* retained column identity differs')
    artifact = verify_asset(run, sample)
    with tempfile.TemporaryDirectory(prefix='selfstar-corpus-audit-') as td:
        work = Path(td)
        frame = work / 'frame'
        shutil.copyfile(artifact, frame)
        restore(root, binding, live, work, frame)
        raw, schema = (work / 'raw'), (work / 'schema').read_bytes()
        facts = wire_facts(frame.read_bytes(), case['rows'], schema)
        require(raw.stat().st_size == first['input_bytes'] and digest(raw) == first['restored_sha256'] and
                sha256(schema).hexdigest() == first['schema_sha256'] and
                facts == {k: first[k] for k in facts},
                'SElf* detached sample digest or complete frame parses differently')
    return {'dataset_id': row['dataset_id'], 'route': row['route'], 'rows': case['rows'],
            'frame_sha256': sample['sha256'], 'restored_sha256': first['restored_sha256']}


def verify(root, plan_path, run, *, replay=False):
    plan = load_json(plan_path)
    check_m3_real_corpus_plan(root, plan)
    report_path = local_file(run, 'report.json')
    ledger = local_file(run, 'ledger.jsonl')
    report = load_json(report_path)
    load_contract(root, 'm3-real-corpus-plan').validate(plan, 'plan')
    load_contract(root, 'm3-real-corpus-run').validate(report, 'report')
    seal = load_json(local_file(run, 'completion.json'))
    require(seal['plan_content_id'] == report['plan_content_id'] == plan['plan_content_id'] and
            seal['run_id'] == report['run_id'] == run.name and seal['report_sha256'] == digest(report_path) and
            seal['ledger_sha256'] == digest(ledger) and seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}),
            'SElf* report or ledger seal does not match')
    binding = plan['specialized']['selfstar']
    spec = report['specialized']['selfstar']
    typed = [{'entry_kind': 'specialized_product', 'selection': 4, **p} for p in spec['fixtures'].values()]
    expected = [r for r in plan['work_items'] if (r['selection'], r['route']) in DRIVERS]
    routes = sorted(route for _, route in DRIVERS)
    require(report['partial_preflight'] and report['route_filter'] == routes and report['statuses'] == {'verified': 46} and
            len(expected) == len(report['rows']) == 46 and len(report['obligations']) == 9,
            'SElf* preflight does not pass all declared file-routes and specialized scope')
    with ledger.open(encoding='utf-8') as stream:
        for line, row in zip(stream, [*report['rows'], *typed, *report['obligations']], strict=True):
            require(json.loads(line) == row, 'SElf* ledger row differs from report')
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    manifest = load_full_manifest(root, definition['bindings']['manifest'], parse=False)
    entries = {e['id']: e for e in manifest['datasets']}
    source = {}
    parity = {}
    samples = []
    totals = {route: Counter() for route in routes}
    for d, row in zip(expected, report['rows'], strict=True):
        require(all(d[k] == row[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation', 'applicability')) and
                d['applicability'] == 'input_domain_matches' and row['status'] == 'verified' and not row['reason'],
                'SElf* file-route is out of scope or unverified')
        dataset = row['dataset_id']
        if dataset not in source:
            source[dataset] = source_digests(root, entries[dataset])
        case = row['evidence']
        n, columns = entries[dataset]['rows'], entries[dataset]['value_count']
        live = row['route'] == 'selfstar-incremental'
        require(not case['timing_admitted'] and case['driver'] == DRIVERS[4, row['route']] and
                (case['rows'], case['columns'], len(case['units'])) == (n, columns, columns) and
                [u['restored_sha256'] for u in case['units']] == source[dataset] and
                case['input_bytes'] == d['input']['size_estimate']['native_input_bytes_one_pass'],
                'SElf* whole-V recovery or scope differs')
        for col, u in enumerate(case['units']):
            require((u['column'], u['row_range'], u['input_bytes'], u['blocks'], u['last_block_rows']) ==
                    (col, [0, n], 8*n, (n+BLOCK-1)//BLOCK, (n-1)%BLOCK+1) and
                    u['block_header_bytes'] == 4*u['blocks'] and
                    u['artifact_bytes'] == u['native_payload_bytes'] + u['object_envelope_bytes'] + u['block_header_bytes'] and
                    (u['lifecycle']['add_calls'] == _live_adds(n) and 0 < u['lifecycle']['prefinish_bits'] < u['native_bits']
                     if live else u['lifecycle'] is None), 'SElf* column state extent or accounting differs')
        for k in KEYS:
            require(case[k] == sum(u[k] for u in case['units']), 'SElf* corpus totals do not close')
        signature = [{k: u[k] for k in (*KEYS, 'last_block_rows', 'schema_sha256', 'frame_sha256', 'restored_sha256')}
                     for u in case['units']]
        require(parity.setdefault(dataset, signature) == signature, 'public batch and native add/finish differ on a full column')
        totals[row['route']].update({'datasets': 1, 'columns': columns, **{k: case[k] for k in KEYS}})
        samples.append(_sample(root, run, binding, row, live))
    obligations = [o for o in plan['obligations'] if o['selection'] == 4]
    require(all(all(x[k] == o[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind'))
                for x, o in zip(report['obligations'], obligations, strict=True)), 'SElf* obligation rows differ from plan')
    return {'schema': 'bmk.m3-selfstar-audit/1', 'run_id': report['run_id'], 'run_seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'whole_column_parity': True, 'totals': totals, 'replayed_samples': samples,
            'specialized': audit_specialized(root, run, binding, report['obligations'], spec, replay=replay),
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, args.plan, args.run.resolve(strict=True), replay=args.replay), indent=2))
