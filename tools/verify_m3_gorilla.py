#!/usr/bin/env python3
"""Check the Gorilla corpus preflight's ledger parity and independently decode retained XORChunks."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tsbench.application.m3_gorilla import HEADER, LENGTH, PAIR, ROWS, restore_independent
from tsbench.application.m3_gorilla_specialized import STATE_ROUTES, audit_regression, audit_specialized
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract

ROUTES = {'tv-batch', 'append-resume', 'iterator'}


def replay_corpus(root, plan, run, projected, *, source_oracle=None):
    """Recheck extent and native XORChunk parity, then replay retained samples."""
    repair = plan['build'].get('gorilla_state_repair')
    for ref in plan['build']['gorilla_corpus'].values():
        require(verify_asset(root, ref).stat().st_size == ref['bytes'], 'Gorilla plan asset differs')
    native_def = load_json(verify_asset(root, plan['definition']['plan']))
    manifest = load_json(local_file(root, native_def['bindings']['manifest']))
    require(content_id(manifest) == native_def['bindings']['manifest_id'], 'Gorilla source manifest differs')
    entries = {v['id']: v for v in manifest['datasets']}
    statuses, excluded, failures = Counter(), Counter(), []
    totals = {r: Counter() for r in ROUTES}
    by_dataset, samples, oracles = {}, [], {}
    for row, decision in projected:
        require(all(row[k] == decision[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability')),
                'Gorilla work item differs from plan')
        route, name = row['route'], row['dataset_id']
        entry = entries[name]
        if decision['applicability'] == 'outside_declared_domain':
            require(row['status'] == 'outside_declared_domain' and row['evidence'] is None and
                    row['reason'] == '; '.join(decision['reasons']) and entry['axis']['unit'] != 'second',
                    'Gorilla excluded input reason differs')
            excluded[route] += 1
            continue
        if row['status'] == 'failed':
            require(route == 'append-resume' and row['evidence'] is None and row['reason'], 'unexpected Gorilla failure scope')
            failures.append({'dataset_id': name, 'route': route, 'reason': row['reason']})
            continue
        require(row['status'] == 'verified', 'Gorilla work item not verified')
        statuses[route] += 1
        evidence = row['evidence']
        if repair is not None:
            chosen = (repair['repair_build']['programs']['tsbench_gorilla_corpus_control'], repair['repair_build']['dependency'],
                      repair['implementation']) if route in STATE_ROUTES else (
                          plan['build']['gorilla_corpus']['executable'], plan['build']['gorilla_corpus']['dependency'],
                          'gorilla-c11-unique-v1')
            require(tuple(evidence[k] for k in ('executable', 'dependency', 'implementation')) == chosen,
                    'Gorilla corpus implementation differs from the route binding')
        cols, rows = entry['value_count'], entry['rows']
        require(evidence['backend'] == 'gorilla_c' and evidence['axis_coordinate'] == 'civil_label_ms_not_utc' and
                evidence['input_identity']['canonical_seconds_sha256'] == entry['canonical']['axis_sha256'] and
                evidence['input_identity']['canonical_value_rows_sha256'] == entry['canonical']['values_sha256'],
                'Gorilla verified inputs lack canonical identity')
        units = evidence['units']
        estimate = decision['input']['size_estimate']
        coords = [(col, [start, min(rows, start + ROWS)]) for col in range(cols) for start in range(0, rows, ROWS)]
        require(coords == [(u['column'], u['row_range']) for u in units] and len(units) == estimate['input_units'] and
                evidence['input_bytes'] == estimate['native_input_bytes_one_pass'] == rows * cols * PAIR.size and
                evidence['unique_logical_axis_bytes'] == rows * 8 and evidence['unique_logical_value_bytes'] == rows * cols * 8,
                'Gorilla corpus unit or logical byte extent differs')
        require(evidence['native_frame_bytes'] == sum(u['native_frame_bytes'] for u in units) and
                evidence['harness_framing_bytes'] == HEADER.size + len(units) * LENGTH.size and
                evidence['artifact_bytes'] == evidence['native_frame_bytes'] + evidence['harness_framing_bytes'],
                'Gorilla final bytes do not close')
        if route == 'append-resume':
            require(all(u['batch_byte_parity_verified'] and u['snapshot']['resume_input_bytes']==u['snapshot']['native_bytes'] for u in units) and
                    evidence['snapshot_native_bytes'] == sum(u['snapshot']['native_bytes'] for u in units) and
                    evidence['snapshot_artifact_bytes'] == evidence['snapshot_native_bytes'] + evidence['harness_framing_bytes'],
                    'Gorilla snapshot bytes do not close')
        elif route == 'iterator':
            require(all(s['forward_seek']['target_ms'] == s['forward_seek']['timestamp_ms'] and
                        0 <= s['forward_seek']['first_at_or_after_index_within_chunk'] <= (s['row_range'][1]-s['row_range'][0]) // 2
                        for s in units), 'Gorilla forward seek metadata differs')
        totals[route].update(units=len(units), columns=cols, input_bytes=evidence['input_bytes'],
                             native_bytes=evidence['native_frame_bytes'], archive_bytes=evidence['artifact_bytes'],
                             snapshot_archive_bytes=evidence['snapshot_artifact_bytes'] or 0)
        parity = tuple((u['frame_sha256'], u['restored_tv_sha256']) for u in units)
        require(by_dataset.setdefault(name, parity) == parity, 'Gorilla route frame and restoration parity differs')
        first = units[0]
        want = {'frame'} | ({'snapshot'} if route == 'append-resume' else set())
        require(evidence['retained_samples'].keys() == want, 'Gorilla retained sample scope differs')
        reference = None
        if source_oracle is not None and name not in oracles:
            oracles[name] = source_oracle(root, entry)
        for label in sorted(want):
            ref = evidence['retained_samples'][label]
            wire = verify_asset(run, ref).read_bytes()
            record = first if label == 'frame' else first['snapshot']
            require(len(wire) == ref['bytes'] == record['native_frame_bytes' if label == 'frame' else 'native_bytes'] and
                    ref['sha256'] == record['frame_sha256' if label == 'frame' else 'sha256'] and
                    ref['restored_tv_sha256'] == record['restored_tv_sha256'] and
                    ref['rows'] == (first['row_range'][1] if label == 'frame' else first['snapshot']['rows']),
                    'Gorilla retained sample identity differs')
            decoded = restore_independent(wire, ref['rows'])
            require(sha256(decoded).hexdigest() == ref['restored_tv_sha256'], 'independent Gorilla recovery differs')
            if source_oracle is not None:
                require(decoded == oracles[name][:ref['rows'] * PAIR.size], 'Gorilla recovery differs from original T and V')
            if label == 'frame':
                reference = decoded
            else:
                require(reference is not None and reference[:len(decoded)] == decoded, 'independent Gorilla prefix differs')
            samples.append({'dataset_id': name, 'route': route, 'part': label, 'rows': ref['rows'],
                            'path': ref['path'], 'bytes': ref['bytes'], 'sha256': ref['sha256'], 'restored_tv_sha256': ref['restored_tv_sha256']})
    require(statuses['tv-batch'] == statuses['iterator'] == statuses['append-resume'] + len(failures) == 16 and
            dict(excluded) == dict.fromkeys(ROUTES, 7) and len(samples) == 64 - 2 * len(failures) and
            len(by_dataset) == 16, 'Gorilla verification and failure scope incomplete')
    return {'verified': dict(statuses), 'outside_declared_domain': dict(excluded), 'failures': failures,
            'totals_by_route': {k: dict(v) for k, v in sorted(totals.items())}, 'independently_decoded_samples': samples}


def verify(root, plan_path, run, *, replay=False):
    plan = load_json(plan_path)
    report_path = local_file(run, 'report.json')
    ledger = local_file(run, 'ledger.jsonl')
    report = load_json(report_path)
    load_contract(root, 'm3-real-corpus-plan').validate(plan, 'plan')
    load_contract(root, 'm3-real-corpus-run').validate(report, 'report')
    seal = load_json(local_file(run, 'completion.json'))
    require(plan['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}) ==
            report['plan_content_id'] == seal['plan_content_id'] and seal['run_id'] == report['run_id'] and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}) and
            seal['report_sha256'] == digest(report_path) and seal['ledger_sha256'] == digest(ledger), 'Gorilla run seal differs')
    repair = plan['build'].get('gorilla_state_repair')
    specialist = report.get('specialized', {}).get('gorilla')
    typed_rows = []
    if repair is not None:
        check_m3_real_corpus_plan(root, plan)
        require(specialist is not None and specialist.get('regression'), 'missing Gorilla repair evidence')
        typed_rows = [{'entry_kind': 'specialized_product', 'selection': 7, 'lane': lane, **row}
                      for lane, detail in specialist['lanes'].items() for row in detail['fixtures'].values()]
        typed_rows.append(specialist['regression'])
    with ledger.open(encoding='utf-8') as stream:
        for line, row in zip(stream, [*report['rows'], *typed_rows, *report['obligations']], strict=True):
            require(json.loads(line) == row, 'Gorilla ledger row differs from report')
    require(report['route_filter'] == sorted(ROUTES) and report['partial_preflight'] and
            report['statuses'] == dict(Counter(r['status'] for r in report['rows'])), 'not a complete Gorilla route preflight')
    expected = [r for r in plan['work_items'] if r['selection'] == 7 and r['route'] in ROUTES]
    require(len(expected) == len(report['rows']) == 69, 'Gorilla denominator differs')
    corpus = replay_corpus(root, plan, run, zip(report['rows'], expected, strict=True))
    extra = {}
    if repair is not None:
        expected = [o for o in plan['obligations'] if o['selection'] == 7]
        actual = report['obligations']
        require(not corpus['failures'] and len(actual) == len(expected) == 12 and all(
            all(row[k] == ob[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind'))
            for row, ob in zip(actual, expected, strict=True)), 'Gorilla repaired corpus or obligation scope incomplete')
        extra = {'specialized': audit_specialized(root, run, plan['specialized']['gorilla'], actual, specialist, replay=replay),
                 'regression': audit_regression(run, specialist['regression'])}
    return {'schema': 'bmk.m3-gorilla-sample-audit/1', 'run_id': report['run_id'], 'run_seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], **corpus, **extra,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true', help='replay detached specialist restores and rejections under isolation')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, args.plan, args.run.resolve(strict=True), replay=args.replay), indent=2))
