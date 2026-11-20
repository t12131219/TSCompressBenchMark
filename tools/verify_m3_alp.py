#!/usr/bin/env python3
"""Verify a sealed ALP-only M3 ledger and replay its specialist products."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_alp_specialized import audit_specialized, ledger_products
from tsbench.application import alp_decode as native, batch_execution as batch
from tsbench.assets import content_id, digest, load_json, local_file, require
from tsbench.contracts import load_contract
from tsbench.planner.alp_decode import is_decode
from tsbench.planner.m3_alp_specialized import ROUTES, inputs, route
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.recovery import DIRECTORY
from tsbench.supervisor.isolated_worker import launcher_lock


def replay_products(root, run, binding, products):
    require(launcher_lock() == binding['launchers'], 'ALP audit isolation launchers changed')
    fixtures, _ = inputs(root)
    folder, replayed = run / 'alp-specialized', []
    for p, row in products.items():
        slot, sample = fixtures[p]
        if is_decode(slot):
            native.audit_slot(folder, binding, slot, row)
        else:
            # Only the two mixed fixtures carry the frozen malformed-sidecar cases.
            artifact = folder / row['artifact']['path']
            with TemporaryDirectory(prefix='m3-alp-abi-replay-') as tmp:
                work, bundle = Path(tmp), folder / DIRECTORY
                require(batch._restore(bundle, binding, slot, artifact, work, work, lambda: False) == row['restored'],
                        'ALP ABI detached recovery differs')
                if slot['reject_decodes']:
                    require(batch._rejected_decodes(bundle, binding, slot, artifact, work, lambda: False) == row['decoder_rejections'],
                            'ALP ABI malformed side-info rejection differs')
                if batch._requires_fenv(binding, slot):
                    raw = work / 'raw'
                    raw.write_bytes(sample.columns[0])
                    require(batch._fenv(bundle, binding, slot, raw, artifact, work, lambda: False) == row['fenv_control'],
                            'ALP rounding-mode rejection did not replay')
        replayed.append({'product_slot': p, 'route': route(slot)})
    return replayed


def verify(root, plan, run, *, replay=False):
    check_m3_real_corpus_plan(root, plan)
    report_path, ledger_path, seal_path = (local_file(run, p) for p in ('report.json', 'ledger.jsonl', 'completion.json'))
    report, seal = load_json(report_path), load_json(seal_path)
    load_contract(root, 'm3-real-corpus-run').validate(report, 'M3 ALP run')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report_path), 'ledger_sha256': digest(ledger_path)}
    require(seal == {**body, 'seal_id': content_id(body)} and report['run_id'] == run.name and
            report['plan_content_id'] == plan['plan_content_id'] and report['partial_preflight'] and
            report['route_filter'] == sorted(r for _, r in ROUTES) and set(report['specialized']) == {'alp'},
            'ALP preflight scope or seal differs')
    binding, specialist = plan['specialized']['alp'], report['specialized']['alp']
    rows, obligations = report['rows'], report['obligations']
    expected = [r for r in plan['work_items'] if (r['selection'], r['route']) in ROUTES]
    required = [r for r in plan['obligations'] if (r['selection'], r['route']) in ROUTES]
    require(len(rows) == len(expected) == report['selected_corpus_decisions'] == report['selected_work_items'] == 46 and
            all(all(r[k] == e[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability'))
                for r, e in zip(rows, expected, strict=True)) and
            report['statuses'] == dict(Counter(r['status'] for r in rows)), 'ALP corpus decision census differs')
    require(len(obligations) == len(required) == 14 and
            all(all(r[k] == e[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check'))
                for r, e in zip(obligations, required, strict=True)) and
            report['obligation_statuses'] == dict(Counter(r['status'] for r in obligations)), 'ALP obligation census differs')
    with ledger_path.open(encoding='utf-8') as stream:
        for line, expected_row in zip(stream, [*rows, *ledger_products(binding, specialist), *obligations], strict=True):
            require(json.loads(line) == expected_row, 'ALP ledger differs from sealed report')
    audited = audit_specialized(root, run, binding, obligations, specialist)
    if replay:
        audited['replayed'] = replay_products(root, run, binding, specialist['fixtures'])
    return {'schema': 'bmk.m3-alp-audit/1', 'run_id': run.name, 'seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'corpus_statuses_ledger_only': report['statuses'],
            'specialized': audited,
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, load_json(args.plan), args.run.resolve(strict=True), replay=args.replay), indent=2))
