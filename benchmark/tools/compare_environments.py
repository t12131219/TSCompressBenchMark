"""Compare coverage and per-case metrics from independently resolved CPU runs."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from tsbench.records import file_hash, read_jsonl, stable_hash, write_json
from tsbench.report import _distribution
from tsbench.study import effective_allocation
from tsbench.trial_analysis import analysis_dependency_hash, case_coverage, scheduled_rows


def load_run(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'manifest.json').read_bytes())
    rows, tail = read_jsonl(root / 'observations.jsonl')
    if tail:
        raise ValueError('interrupted observation tail')
    selected, planned = scheduled_rows(manifest, rows)
    cases = {}
    for case in manifest['cases']:
        key = (case['dataset_id'], case['method_id'], case['profile_id'])
        if key in cases:
            raise ValueError('duplicate comparison key')
        observed = [row for row in selected.values() if row['case_id'] == case['case_id']]
        coverage = case_coverage(manifest, case, selected, planned)
        cases[key] = (case, observed, coverage)
    evidence = {'root': str(root), 'run_id': manifest['run_id'], 'environment': manifest['environment'],
                'manifest_sha256': file_hash(root / 'manifest.json'),
                'observations_sha256': file_hash(root / 'observations.jsonl'),
                'state': manifest.get('state'), 'execution': manifest['resolved_config']['execution'],
                'requested_trials': sum(len(keys) for keys in planned.values()),
                'missing_trials': sum(entry[2]['missing_trials'] for entry in cases.values()),
                'ready_cases': sum(case['status'] == 'ready' for case in manifest['cases']),
                'complete_cases': sum(entry[2]['complete'] for entry in cases.values()),
                'admission': dict(collections.Counter(c['status'] for c in manifest['cases'])),
                'trials': dict(collections.Counter(r['status'] for r in selected.values()))}
    return manifest, cases, evidence


def compare(pairs, destination):
    results = []
    for base_path, alternate_path in pairs:
        base, first, base_evidence = load_run(base_path)
        alternate, second, alternate_evidence = load_run(alternate_path)
        if set(first) != set(second) or base['resolved_config']['task'] != alternate['resolved_config']['task']:
            raise ValueError('request matrix/task differs between environments')
        comparisons = []
        for key in sorted(first):
            left, left_rows, left_coverage = first[key]
            right, right_rows, right_coverage = second[key]
            if any(left[field] != right[field] for field in ('method', 'task', 'boundary', 'lifecycle', 'cache_policy', 'raw_object_id', 'profile')):
                raise ValueError(f'comparison semantics/input differs: {key}')
            entry = {'dataset_id': key[0], 'method_id': key[1], 'profile_id': key[2],
                     'base_case_id': left['case_id'], 'alternate_case_id': right['case_id'],
                     'raw_object_id': left['raw_object_id'], 'base_status': left['status'], 'alternate_status': right['status'],
                     'base_implementation_id': left.get('implementation_id'),
                     'alternate_implementation_id': right.get('implementation_id'),
                     'profile': left['profile'],
                     'base_effective_profile': left.get('effective_profile'),
                     'alternate_effective_profile': right.get('effective_profile'),
                     'same_effective_allocation': effective_allocation(left) == effective_allocation(right)
                        if left.get('effective_profile') and right.get('effective_profile') else None,
                     'base_build_evidence': left.get('build_evidence', []),
                     'alternate_build_evidence': right.get('build_evidence', []),
                     'base_coverage': left_coverage, 'alternate_coverage': right_coverage,
                     'base_trial_statuses': dict(collections.Counter(r['status'] for r in left_rows)),
                     'alternate_trial_statuses': dict(collections.Counter(r['status'] for r in right_rows)),
                     'trace': {'base': [{'session': r['session'], 'round': r['round'], 'attempt': r.get('attempt', 0),
                                        'line': r['observation_line'], 'status': r['status']} for r in left_rows],
                               'alternate': [{'session': r['session'], 'round': r['round'], 'attempt': r.get('attempt', 0),
                                              'line': r['observation_line'], 'status': r['status']} for r in right_rows]}}
            for label, rows, coverage in (('base', left_rows, left_coverage), ('alternate', right_rows, right_coverage)):
                ok = [r for r in rows if r['status'] == 'ok']
                entry[label + '_performance_scope'] = 'diagnostic only; execution source changed' if not coverage['execution_source_valid'] else 'all scheduled trials' if coverage['complete'] else 'conditional on successful primary trials'
                entry[label + '_metrics'] = {metric: _distribution([r[metric] for r in ok])
                                             for metric in ('encode_ns', 'decode_ns', 'stored_bytes')}
                entry[label + '_quality'] = {metric: _distribution([r['verification'][metric] for r in ok
                                             if r.get('verification', {}).get(metric) is not None])
                                             for metric in ('max_abs', 'rmse')}
            comparisons.append(entry)
        environment_fields = ('platform', 'machine', 'cpu_model', 'cpu_count', 'isa_flags', 'affinity')
        environment_matches = {field: base['environment'].get(field) == alternate['environment'].get(field)
                               if base['environment'].get(field) is not None and alternate['environment'].get(field) is not None else None
                               for field in environment_fields}
        results.append({'base': base_evidence, 'alternate': alternate_evidence, 'cases': comparisons,
                        'recorded_environment_matches': environment_matches,
                        'same_execution_plan': base['resolved_config']['execution'] == alternate['resolved_config']['execution'],
                        'same_admission': all(c['base_status'] == c['alternate_status'] for c in comparisons)})
    report = {'schema': 'tsbench.environment-comparison/1', 'code_sha256': file_hash(__file__), 'trial_analysis_hash': analysis_dependency_hash(),
              'scope': 'descriptive comparison of declared requests, exact scheduled trials and recorded environment/build evidence',
              'primary_policy': 'earliest executed attempt; successful retry never replaces executed failure',
              'timing_limit': 'each run retains its declared sessions and rounds; randomized assignment across environments and physical host identity are not established by this analysis; timing is descriptive',
              'pairs': results}
    report['analysis_id'] = stable_hash(report)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / 'summary.json', report)
    lines = ['# Alternate software environment replay', '', report['scope'] + '.', '',
             '| Base run | Alternate run | Same admission | Complete alternate ready cases | Alternate trials |', '|---|---|---|---:|---|']
    for result in results:
        alternate = result['alternate']
        lines.append(f"| {Path(result['base']['root']).name} | {Path(alternate['root']).name} | {result['same_admission']} | {alternate['complete_cases']}/{alternate['ready_cases']} | {alternate['trials']} |")
    lines.extend(['', report['timing_limit'] + '.',
                  'Per-case scheduled denominators, missing trial keys, all statuses, successful primary-trial sizes/quality/times and raw-line traces are in summary.json. Partial metrics are explicitly conditional on success.'])
    (destination / 'README.md').write_text('\n'.join(lines) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pair', nargs=2, type=Path, action='append', required=True, metavar=('BASE', 'ALTERNATE'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = compare(args.pair, args.output)
    print(json.dumps({'pairs': len(result['pairs']), 'same_admission': all(p['same_admission'] for p in result['pairs']),
                      'analysis_id': result['analysis_id']}))
