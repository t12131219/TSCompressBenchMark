#!/usr/bin/env python3
"""Independently replay the pcodec and Zstd/XZ specialist products of one M3 run."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_batch_specialized import audit_specialized, ledger_products
from tsbench.assets import content_id, digest, load_json, local_file, require
from tsbench.contracts import load_contract
from tsbench.planner.m3_batch_specialized import FAMILIES
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan


def verify(root, plan, run, *, replay=False):
    check_m3_real_corpus_plan(root, plan)
    report_path, ledger_path, seal_path = (local_file(run, p) for p in ('report.json', 'ledger.jsonl', 'completion.json'))
    report, seal = load_json(report_path), load_json(seal_path)
    load_contract(root, 'm3-real-corpus-run').validate(report, 'M3 batch specialists run')
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report_path), 'ledger_sha256': digest(ledger_path)}
    routes = set().union(*(x[1].keys() for x in FAMILIES.values()))
    selected = {key for key in routes if key[1] in (report['route_filter'] or [])}
    families = {name: spec for name, spec in FAMILIES.items() if spec[1].keys() <= selected}
    require(families and set().union(*(x[1].keys() for x in families.values())) == selected and
            seal == {**body, 'seal_id': content_id(body)} and report['run_id'] == run.name and
            report['plan_content_id'] == plan['plan_content_id'] and report['partial_preflight'] and
            report['route_filter'] == sorted(r for _, r in selected) and set(report['specialized']) == families.keys(),
            'M3 batch specialists preflight scope or seal differs')
    rows, obligations = report['rows'], report['obligations']
    expected = [r for r in plan['work_items'] if (r['selection'], r['route']) in selected]
    required = [r for r in plan['obligations'] if (r['selection'], r['route']) in selected]
    require(len(rows) == len(expected) == report['selected_corpus_decisions'] == len(selected) * 23 and
            report['selected_work_items'] == sum(r['applicability'] == 'input_domain_matches' for r in expected) and
            all(all(r[k] == e[k] for k in ('work_item_id', 'dataset_id', 'selection', 'route', 'operation', 'applicability'))
                for r, e in zip(rows, expected, strict=True)) and
            report['statuses'] == dict(Counter(r['status'] for r in rows)), 'M3 batch corpus decision census differs')
    require(len(obligations) == len(required) == sum(spec[2] for spec in families.values()) and
            all(all(r[k] == e[k] for k in ('obligation_id', 'selection', 'route', 'kind', 'check'))
                for r, e in zip(obligations, required, strict=True)) and
            report['obligation_statuses'] == dict(Counter(r['status'] for r in obligations)), 'M3 batch obligation census differs')
    evidence = [(plan['specialized'][name], [r for r in obligations if (r['selection'], r['route']) in spec[1]],
                 report['specialized'][name]) for name, spec in families.items()]
    with ledger_path.open(encoding='utf-8') as stream:
        products = [p for binding, _, group in evidence for p in ledger_products(binding, group)]
        for line, expected_row in zip(stream, [*rows, *products, *obligations], strict=True):
            require(json.loads(line) == expected_row, 'M3 batch ledger differs from sealed report')
    return {'schema': 'bmk.m3-batch-specialist-audit/1', 'run_id': run.name, 'seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'corpus_statuses_ledger_only': report['statuses'],
            'specialized': {binding['family']: audit_specialized(root, run, binding, obs, group, replay=replay)
                            for binding, obs, group in evidence},
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    print(json.dumps(verify(ROOT, load_json(args.plan), args.run.resolve(strict=True), replay=args.replay), indent=2))
