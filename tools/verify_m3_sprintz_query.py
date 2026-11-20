#!/usr/bin/env python3
"""Audit Sprintz query-only or public ABI batch + query preflight evidence."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tsbench.application.m3_sprintz import _call, audit_specialized, verify_frame
from tsbench.application.m3_sprintz_query import HEADER, _oracle, invoke
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_sprintz import BATCH, DRIVER, QUERY
from tsbench.planner.sprintz_execution import PLUGIN, TOOL
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract


def _batch_audit(root, run, plan, decisions, rows, queries):
    spec = plan['specialized']['sprintz']['decoder']
    worker, library, direct = (local_file(root, spec['files'][path]['source']) for path in
                               (spec['worker'], spec['plugins'][PLUGIN], spec['tools'][TOOL]))
    total = {'units': 0, 'input_bytes': 0, 'artifact_bytes': 0, 'sfb1_bytes': 0, 'abi_envelope_bytes': 0}
    samples = []
    for decision, row in zip(decisions, rows, strict=True):
        evidence = row['evidence']
        units = evidence['units']
        extent = decision['input']
        query = queries[row['dataset_id']]['evidence']
        require(all(row[k] == decision[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation', 'applicability')) and
                row['status'] == 'verified' and evidence['driver'] == DRIVER and not evidence['timing_admitted'] and
                len(units) == extent['size_estimate']['input_units'] and evidence['input_bytes'] == query['input_bytes'] ==
                extent['size_estimate']['native_input_bytes_one_pass'] == sum(u['raw_bytes'] for u in units),
                'Sprintz public ABI batch denominator differs')
        for batch_unit, query_unit in zip(units, query['units'], strict=True):
            require(all(batch_unit[k] == query_unit[k] for k in ('column', 'row_start', 'row_end', 'raw_bytes', 'restored_sha256')) and
                    batch_unit['sfb1_sha256'] == query_unit['frame_sha256'] and batch_unit['sfb1_bytes'] == query_unit['frame_bytes'] and
                    batch_unit['artifact_bytes'] == batch_unit['abi_envelope_bytes'] + batch_unit['sfb1_bytes'],
                    'Sprintz batch native payload, coordinate, or restoration differs from query')
        total['units'] += len(units)
        total['input_bytes'] += evidence['input_bytes']
        for key in ('artifact_bytes', 'abi_envelope_bytes', 'sfb1_bytes'):
            require(evidence[key] == sum(u[key] for u in units), 'Sprintz batch accounting differs')
            total[key] += evidence[key]
        sample = evidence['retained_sample']
        first = units[0]
        require(sample['observation'] == first and sample['sha256'] == first['frame_sha256'], 'Sprintz batch sample identity differs')
        frame = verify_asset(run, sample).read_bytes()
        require(len(frame) == first['artifact_bytes'] == sample['bytes'], 'Sprintz batch sample extent differs')
        with tempfile.TemporaryDirectory(prefix='m3-sprintz-abi-audit-') as td:
            work = Path(td)
            (work / 'frame').write_bytes(frame)
            observation, _ = _call(worker, library, direct, work, 'decode-columns', 'frame', 'schema', 'raw')
            raw, schema = ((work / name).read_bytes() for name in ('raw', 'schema'))
            inner = verify_frame(frame, raw, schema)
            require(observation[0] == {'columns': [{'dtype': 4, 'count': len(raw) // 2}]} and
                    sha256(schema).hexdigest() == first['schema_sha256'] and sha256(inner).hexdigest() == first['sfb1_sha256'] and
                    sha256(raw).hexdigest() == first['restored_sha256'], 'Sprintz batch sample replay differs')
        samples.append({'dataset_id': row['dataset_id'], 'frame_sha256': sample['sha256'],
                        'restored_sha256': first['restored_sha256']})
    return {**total, 'replayed_samples': samples, 'native_frame_parity_with_query': True}


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
            seal['report_sha256'] == digest(report_path) and seal['ledger_sha256'] == digest(ledger),
            'M3 report or ledger differs from plan/run seal')
    together = report['route_filter'] == ['fire-batch', 'query']
    specialist = report.get('specialized', {}).get('sprintz')
    typed_rows = []
    route_keys = {QUERY}
    if together:
        check_m3_real_corpus_plan(root, plan)
        require(specialist is not None, 'missing Sprintz specialist evidence')
        typed_rows = [{'entry_kind': 'specialized_product', 'selection': 19, **row} for row in specialist['fixtures'].values()]
        route_keys.add(BATCH)
    with ledger.open(encoding='utf-8') as stream:
        for line, row in zip(stream, [*report['rows'], *typed_rows, *report['obligations']], strict=True):
            require(json.loads(line) == row, 'M3 ledger differs from its report')
    n = 23 * len(route_keys)
    require((together or report['route_filter'] == ['query']) and report['partial_preflight'] and report['statuses'] == {'verified': n},
            'not a complete Sprintz route preflight')
    decisions = [r for r in plan['work_items'] if (r['selection'], r['route']) in route_keys]
    require(len(decisions) == len(report['rows']) == n and all(r['work_item_id'] == d['work_item_id']
            for r, d in zip(report['rows'], decisions, strict=True)), 'Sprintz preflight denominator differs')
    expected = [d for d in decisions if d['route'] == QUERY[1]]
    queries = [r for r in report['rows'] if r['route'] == QUERY[1]]
    binding = plan['build']['sprintz_query']
    for ref in binding.values():
        require(verify_asset(root, ref).stat().st_size == ref['bytes'], 'Sprintz plan asset size differs')
    control = local_file(root, binding['executable']['path'])
    totals = {'units': 0, 'columns': 0, 'input_bytes': 0, 'artifact_bytes': 0, 'frame_header_bytes': 0, 'payload_bytes': 0}
    replayed = []
    for row, decision in zip(queries, expected, strict=True):
        require(all(row[k] == decision[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation', 'applicability')) and
                row['status'] == 'verified', 'Sprintz missing file-route verification')
        extent = decision['input']
        evidence = row['evidence']
        units = evidence['units']
        step = extent['slice_extent']['max_per_unit']
        n = extent['row_ranges'][0]['end']
        expected_ranges = [(c, s, min(n, s + step)) for c in range(extent['value_column_range'][1]) for s in range(0, n, step)]
        require(expected_ranges == [(u['column'], u['row_start'], u['row_end']) for u in units] and
                all(u['raw_bytes'] == 8 * (u['row_end'] - u['row_start']) and
                    u['frame_bytes'] == HEADER.size + u['payload_bytes'] and
                    u['auto']['backend'] == 'upstream_simd' and u['scalar']['backend'] == 'scalar' and
                    all(u['auto'][k] == u['scalar'][k] for k in ('count', 'sum', 'max')) for u in units) and
                len(units) == extent['size_estimate']['input_units'], 'Sprintz verified frame extent differs')
        require(evidence['input_bytes'] == sum(u['raw_bytes'] for u in units) == extent['size_estimate']['native_input_bytes_one_pass'] and
                evidence['artifact_bytes'] == sum(u['frame_bytes'] for u in units) and
                evidence['frame_header_bytes'] == len(units) * HEADER.size and
                evidence['artifact_bytes'] == evidence['frame_header_bytes'] + evidence['payload_bytes'], 'Sprintz byte tally differs')
        totals['units'] += len(units)
        for k in ('columns', 'input_bytes', 'artifact_bytes', 'frame_header_bytes', 'payload_bytes'):
            totals[k] += evidence[k]
        sample = evidence['retained_sample']
        first = units[0]
        require(sample['observation'] == first and sample['sha256'] == first['frame_sha256'], 'Sprintz sample is not bound to the first frame')
        wire = verify_asset(run, sample).read_bytes()
        require(len(wire) == sample['bytes'] == first['frame_bytes'], 'Sprintz retained length differs')
        with tempfile.TemporaryDirectory(prefix='m3-sprintz-sample-') as td:
            scratch = Path(td)
            (scratch / 'sample.sfb1').write_bytes(wire)
            sample_rows = first['row_end'] - first['row_start']
            query, _ = invoke(control, scratch, 'query', 'sample.sfb1', 1, sample_rows, '-')
            (scratch / 'restored').mkdir()
            invoke(control, scratch, 'decode', 'sample.sfb1', 1, sample_rows, 'restored')
            bits = (scratch / 'restored' / 'column-0000.bin').read_bytes()
            require(sha256(bits).hexdigest() == first['restored_sha256'] and len(bits) == first['raw_bytes'],
                    'Sprintz sample restored digest differs')
            oracle = _oracle(bits)
            for mode in ('auto', 'scalar'):
                require(query['units'][0][mode] == first[mode] == {'backend': first[mode]['backend'], **oracle},
                        'Sprintz sample reductions differ')
        replayed.append({'dataset_id': row['dataset_id'], 'frame_sha256': sample['sha256'],
                         'restored_sha256': first['restored_sha256'], 'rows': sample_rows})
    extra = {}
    if together:
        obligations = [o for o in plan['obligations'] if o['selection'] == 19]
        actual = report['obligations']
        require(len(actual) == len(obligations) == 10 and all(
            all(row[k] == ob[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind'))
            for row, ob in zip(actual, obligations, strict=True)), 'Sprintz specialist obligation scope differs')
        extra = {'specialized': audit_specialized(run, plan['specialized']['sprintz'], actual, specialist, replay=replay),
                 'fire_batch': _batch_audit(root, run, plan, [d for d in decisions if d['route'] == BATCH[1]],
                                            [r for r in report['rows'] if r['route'] == BATCH[1]],
                                            {r['dataset_id']: r for r in queries})}
    return {'schema': 'bmk.m3-sprintz-sample-audit/1', 'run_id': report['run_id'], 'run_seal_id': seal['seal_id'],
            'plan_content_id': report['plan_content_id'], **totals, **extra, 'replayed_samples': replayed,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true', help='also replay all specialist products under Bubblewrap')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, args.plan, args.run.resolve(strict=True), replay=args.replay), indent=2))
