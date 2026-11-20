#!/usr/bin/env python3
"""Reconcile Huff0 specialist obligations and replay retained products offline."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_huff0_specialized import audit_specialized, ledger_products
from tsbench.assets import content_id, digest, load_json, local_file, require
from tsbench.contracts import load_contract
from tsbench.planner.huff0_execution import ROUTES
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan


def verify(root, plan, run, *, replay=False):
    check_m3_real_corpus_plan(root, plan)
    f = {n: local_file(run, n) for n in ('report.json', 'ledger.jsonl', 'completion.json')}
    report, seal = load_json(f['report.json']), load_json(f['completion.json'])
    load_contract(root, 'm3-real-corpus-run').validate(report, 'Huff0 specialist run')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(f['report.json']), 'ledger_sha256': digest(f['ledger.jsonl'])}
    routes = sorted(route for _, route in ROUTES)
    require(seal == {**body, 'seal_id': content_id(body)} and report['run_id'] == run.name and
            report['plan_content_id'] == plan['plan_content_id'] and report['partial_preflight'] and
            report['route_filter'] == routes and set(report['specialized']) == {'huff0'}, 'Huff0 specialist run seal or scope differs')
    wanted = [ob for ob in plan['obligations'] if (ob['selection'], ob['route']) in ROUTES]
    rows = report['obligations']
    require(len(wanted) == len(rows) == 12 and report['obligation_statuses'] == dict(Counter(r['status'] for r in rows)),
            'Huff0 specialist census differs')
    for a, b in zip(wanted, rows, strict=True):
        require(all(a[k] == b[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind')),
                'Huff0 specialist verdict is not joined to the frozen obligation')
    decisions = [item for item in plan['work_items'] if (item['selection'], item['route']) in ROUTES]
    require(len(decisions) == len(report['rows']) == report['selected_work_items'] == report['selected_corpus_decisions'] == 46 and
            [i['work_item_id'] for i in decisions] == [r['work_item_id'] for r in report['rows']], 'Huff0 corpus decisions differ')
    binding, proof = plan['specialized']['huff0'], report['specialized']['huff0']
    with f['ledger.jsonl'].open(encoding='utf-8') as ledger:
        for line, expected in zip(ledger, [*report['rows'], *ledger_products(binding, proof), *rows], strict=True):
            require(json.loads(line) == expected, 'Huff0 specialist ledger differs from the sealed report')
    return {'schema': 'bmk.m3-huff0-specialized-audit/1', 'run_id': run.name, 'run_seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'specialized': audit_specialized(run, binding, rows, proof, replay=replay),
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--replay', action='store_true')
    a = p.parse_args()
    print(json.dumps(verify(ROOT, load_json(a.plan), a.run.resolve(strict=True), replay=a.replay), indent=2))
