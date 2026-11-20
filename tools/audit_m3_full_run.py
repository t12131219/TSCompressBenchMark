#!/usr/bin/env python3
"""Audit one sealed full M3 run: denominator, metrics and retained corpus custody."""
import argparse
from collections import Counter
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_full_custody import audit as audit_custody
from tsbench.application.m3_ledger_census import census
from tsbench.application.m3_metric_details import extract
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, require


def _cross_check(plan, population, metric, custody):
    require(population['all_frozen_decisions_and_obligations_accounted'], 'audit requires one sealed full M3 run, not a preflight')
    require(population['run_id'] == metric['run_id'] == custody['run_id'] and
            population['seal_id'] == metric['seal_id'] == custody['source_seal_id'] and
            all(d['plan_content_id'] == plan['plan_content_id'] for d in (population, metric, custody)),
            'M3 audit projections came from different runs or plans')
    n = len(plan['work_items'])
    require(metric['includes_all_plan_decisions'] and custody['all_corpus_decisions_present'] and
            len(population['decisions']) == metric['decision_rows'] == custody['corpus_decision_count'] == n and
            population['corpus_statuses'] == metric['decision_statuses'] and
            sum(sum(v.values()) for v in population['obligation_statuses'].values()) == len(plan['obligations']),
            'M3 audit projections disagree on denominator or outcomes')


def _summary(plan, population, metric, custody):
    _cross_check(plan, population, metric, custody)
    domain = Counter(w['applicability'] for w in plan['work_items'])
    obligation_gaps = {k: {s: n for s, n in group.items() if s != 'verified'}
                       for k, group in population['obligation_statuses'].items()}
    exclusions = set(domain) - {'input_domain_matches'}
    failures = {s: n for s, n in population['corpus_statuses'].items() if s not in exclusions | {'verified'}}
    return {'schema': 'bmk.m3-full-run-audit/1', 'run_id': population['run_id'], 'plan_content_id': plan['plan_content_id'],
            'source_seal': population['seal_id'], 'scope': 'full_run_denominator_and_metrics_and_retained_corpus_custody',
            'decisions': metric['decision_rows'], 'frozen_applicability': dict(domain), 'obligations': len(plan['obligations']),
            'outcomes': population['corpus_statuses'], 'obligation_outcomes': population['obligation_statuses'],
            'specialist_product_outcomes': population['specialist_product_statuses'],
            'applicable_corpus_nonverified': failures, 'obligations_nonverified': obligation_gaps,
            'batch_unit_mismatches': population['batch_unit_mismatches'],
            'no_unbound_obligations': population['no_unbound_obligations'],
            'retained_corpus_files': custody['physical_retained_files'], 'retained_corpus_bytes': custody['physical_retained_bytes'],
            'page_samples_replayed': len(custody['isolated_page_replays']),
            'not_established_here': ['complete_all_family_artifact_replay', 'M2_directional_repetitions_and_timing_admission',
                                     'cross_format_and_TV_stage_exit', 'stage_receipt'],
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


def _file(path):
    return {'path': path.name, 'bytes': path.stat().st_size, 'sha256': digest(path)}


def audit(plan_path, run, out, *, replay_pages=False):
    plan = load_json(plan_path)
    run = run.resolve(strict=True)
    out = out.resolve()
    require(out.parent.is_dir() and not out.exists(), 'M3 audit output needs an existing parent and new directory')
    population = census(ROOT, plan, run)
    require(population['all_frozen_decisions_and_obligations_accounted'], 'audit requires one sealed full M3 run, not a preflight')
    with TemporaryDirectory(prefix='.m3-full-audit-', dir=out.parent) as tmp:
        stage = Path(tmp) / 'audit'
        stage.mkdir()
        write_new(stage / 'census.json', population)
        with (stage / 'metrics.jsonl').open('xb') as sink:
            metric = extract(plan, run, sink)
        write_new(stage / 'metrics-summary.json', metric)
        custody = audit_custody(ROOT, plan, run, replay_pages=replay_pages)
        write_new(stage / 'retained-corpus.json', custody)
        summary = _summary(plan, population, metric, custody)
        summary['code'] = {p: digest(ROOT / p) for p in ('tools/audit_m3_full_run.py', 'src/tsbench/application/m3_ledger_census.py',
                          'src/tsbench/application/m3_metric_details.py', 'src/tsbench/application/m3_full_custody.py')}
        summary['outputs'] = [_file(p) for p in sorted(stage.iterdir())]
        write_new(stage / 'summary.json', {**summary, 'audit_id': content_id(summary)})
        require(not out.exists(), 'M3 audit output appeared during validation')
        stage.rename(out)
    return out / 'summary.json'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ('plan', 'run', 'out'):
        p.add_argument('--' + k, required=True, type=Path)
    p.add_argument('--replay-pages', action='store_true')
    a = p.parse_args()
    try:
        print(audit(a.plan, a.run, a.out, replay_pages=a.replay_pages))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
