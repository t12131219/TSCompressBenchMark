"""Read-only exact-trial summaries and explicitly paired scheme/layout effects.

No codec execution, overall winner, source-level significance test, or change to
raw manifests/observations. All C/F interventions retain both exact object IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics

from characterize_data import sha256
from generate_real_objects import freeze_text, json_text
from tsbench.data import array_descriptor, fingerprint, load_dataset, project
from tsbench.records import file_hash, read_jsonl, stable_hash, write_json
from tsbench.report import _distribution
from tsbench.study import comparison_group, effective_allocation, pair_condition
from tsbench.trial_analysis import case_coverage, scheduled_rows


ROOT = Path(__file__).resolve().parents[2]
METRICS = ('encode_ns', 'decode_ns', 'stored_bytes')


def component_identity(obj):
    components = {name: {'dtype': array.dtype.str, 'shape': list(array.shape),
                         'role': obj.schema.get('roles', {}).get(name, name),
                         'c_order_bytes_sha256': hashlib.sha256(array.tobytes(order='C')).hexdigest()}
                  for name, array in obj.components.items()}
    return {'logical_component_identity': stable_hash({'schema': dict(obj.schema), 'components': components}),
            'components': components,
            'scope': 'exact dtype/shape/schema and bitwise C-order component bytes, ignoring physical C/F layout only'}


def freeze_components(characterization_path: Path, output: Path):
    document = json.loads(characterization_path.read_text())
    identities = []
    for record in document['objects']:
        lineage = record['lineage']
        dataset = {**lineage['parse_rule'], 'path': lineage['source_path'], 'source': lineage.get('source'),
                   'license': lineage.get('license')}
        obj = project(load_dataset(dataset), {'kind': record['schema']['task']})
        if fingerprint(obj) != record['raw_object_id'] or obj.lineage['source_hash'] != lineage['source_hash']:
            raise ValueError(f"frozen object identity drift: {record['dataset_id']}")
        identities.append({'experiment': record['experiment'], 'dataset_id': record['dataset_id'],
                           'raw_object_id': record['raw_object_id'], 'raw_bytes': record['raw_bytes'],
                           'source_id': lineage.get('source'),
                           'component_layouts': {name: array_descriptor(array)['order']
                                                 for name, array in obj.components.items()},
                           **component_identity(obj)})
    result = {'schema': 'tsbench.layout-pairing-inputs/1', 'codec_execution': False,
              'characterization_path': str(characterization_path.resolve()),
              'characterization_sha256': sha256(characterization_path),
              'freeze_code_sha256': sha256(Path(__file__)),
              'policy': 'supplementary input identities, reloaded and verified against frozen exact raw_object_id/source hash; no prior artifact overwritten',
              'objects': identities}
    freeze_text(output, json_text(result))
    return result


def _safe_output(destination: Path, roots):
    for root in roots:
        if destination == root or root in destination.parents or destination in root.parents:
            raise ValueError('analysis output must be separate from every input run directory')


def _session_summary(case_id, selected, planned):
    by_session = defaultdict(list)
    for key in sorted(planned.get(case_id, set())):
        if key in selected and selected[key]['status'] == 'ok':
            by_session[key[1]].append(selected[key])
    return {str(session): {metric: _distribution([row.get(metric) for row in rows])['median']
                           for metric in METRICS} for session, rows in sorted(by_session.items())}


def _metrics_valid(point):
    return bool(point['session_summaries']) and all(
        isinstance(metrics.get(metric), (int, float)) and math.isfinite(metrics[metric]) and metrics[metric] > 0
        for metrics in point['session_summaries'].values() for metric in METRICS)


def paired_row(reference, candidate, manifest, kind):
    reason = None
    if reference is None:
        reason = 'declared matching baseline case absent'
    elif not reference['complete'] or not candidate['complete']:
        reason = 'one or both exact scheduled cases incomplete or execution provenance invalid'
    elif reference['scheduled_session_rounds'] != candidate['scheduled_session_rounds']:
        reason = 'scheduled session/round identities differ'
    elif effective_allocation(reference) != effective_allocation(candidate):
        reason = 'effective resource allocations differ'
    elif not _metrics_valid(reference) or not _metrics_valid(candidate):
        reason = 'a paired session metric is missing, nonfinite or nonpositive'
    elif reference['task'] != candidate['task'] or reference['profile'] != candidate['profile']:
        reason = 'full task or requested profile differs'
    elif any(reference[field] != candidate[field] for field in ('boundary', 'lifecycle', 'cache_policy')):
        reason = 'object/lifecycle/cache boundary differs'
    elif kind == 'scheme' and reference['raw_object_id'] != candidate['raw_object_id']:
        reason = 'exact canonical object differs'
    elif kind == 'layout' and (reference.get('logical_component_identity') is None or
                              reference['logical_component_identity'] != candidate.get('logical_component_identity')):
        reason = 'bitwise layout-independent components differ or are not frozen'
    condition = {
        **comparison_group(candidate, reference, manifest),
        'pair_kind': kind, 'source_id': candidate['source_id'],
        'candidate_dataset_id': candidate['dataset_id'],
        'baseline_dataset_id': reference['dataset_id'] if reference else None,
        'candidate_raw_object_id': candidate['raw_object_id'],
        'baseline_raw_object_id': reference['raw_object_id'] if reference else None,
        'logical_component_identity': candidate.get('logical_component_identity'),
    }
    row = {'run_id': manifest['run_id'], 'source_id': candidate['source_id'], 'pair_kind': kind,
           'baseline_case_id': reference['case_id'] if reference else None, 'candidate_case_id': candidate['case_id'],
           'baseline_method_id': reference['method_id'] if reference else None,
           'candidate_method_id': candidate['method_id'], 'pair_available': reason is None, 'reason': reason,
           'group_id': stable_hash(condition), 'group_condition': condition,
           'object_identity_differs': reference['raw_object_id'] != candidate['raw_object_id'] if reference else None,
           'baseline_trace': reference['primary_trace'] if reference else None, 'candidate_trace': candidate['primary_trace'],
           'semantics': 'baseline/candidate; >1 means candidate faster or smaller; median round within each matched session',
           'interpretation': 'C baseline / F candidate is a layout intervention on matched exact component bits with different canonical object identities'
                             if kind == 'layout' else 'same exact canonical object; explicit scheme and complete wire cost'}
    if reason is None:
        row['session_ratios'] = {
            metric: [{'session': int(session), 'ratio': reference['session_summaries'][session][metric] /
                       candidate['session_summaries'][session][metric]} for session in reference['session_summaries']]
            for metric in METRICS}
        row['descriptive_session_ratio_median'] = {
            metric: statistics.median(item['ratio'] for item in ratios) for metric, ratios in row['session_ratios'].items()}
    return row


def analyze(run_dirs, destination: Path, component_path: Path, baselines=None):
    roots = [Path(path).resolve(strict=True) for path in run_dirs]
    destination = destination.resolve()
    _safe_output(destination, roots)
    component_document = json.loads(component_path.read_text())
    component_index = {(entry['experiment'], entry['dataset_id'], entry['raw_object_id']): entry
                       for entry in component_document['objects']}
    if len(component_index) != len(component_document['objects']):
        raise ValueError('duplicate frozen component identity')
    run_ids, inputs, points, pairs = set(), [], [], []
    baselines = baselines or {}
    for root in roots:
        manifest = json.loads((root/'manifest.json').read_text())
        if manifest['run_id'] in run_ids:
            raise ValueError('a run cannot contribute twice')
        run_ids.add(manifest['run_id'])
        rows, tail = read_jsonl(root/'observations.jsonl')
        if tail:
            raise ValueError('analysis refuses interrupted JSONL tails; preserve/recover through the runner')
        selected, planned = scheduled_rows(manifest, rows)
        baseline = baselines.get(manifest['name'],
                                 'zstd-frame' if manifest['resolved_config']['task']['fidelity'] == 'bitwise' else 'zfp-accuracy-1d')
        declared = {method['id'] for method in manifest['resolved_config']['methods']}
        if baseline not in declared:
            raise ValueError(f"{manifest['name']}: baseline {baseline!r} is not a declared method id")
        attempts = defaultdict(list)
        for line, row in enumerate(rows, 1):
            if row.get('phase') == 'measurement' and row.get('event') == 'terminal':
                attempts[row['case_id']].append({**row, 'observation_line': line})
        inputs.append({'path': str(root), 'run_id': manifest['run_id'], 'name': manifest['name'],
                       'baseline_method_id': baseline, 'manifest_sha256': file_hash(root/'manifest.json'),
                       'observations_sha256': file_hash(root/'observations.jsonl'),
                       'execution_provenance': manifest.get('execution_provenance'),
                       'execution_source_unchanged': manifest.get('execution_source_unchanged'),
                       'schedule': manifest['schedule'], 'requested_cases': len(manifest['cases']),
                       'scheduled_trials': len(manifest['schedule']),
                       'all_terminal_status_counts': dict(Counter(row['status'] for values in attempts.values() for row in values))})
        run_points = []
        by_pair_condition = {}
        for case in manifest['cases']:
            coverage = case_coverage(manifest, case, selected, planned)
            primary = [selected[key] for key in sorted(planned.get(case['case_id'], set())) if key in selected]
            for row in attempts[case['case_id']]:
                for field in ('raw_object_id', 'implementation_id', 'boundary', 'lifecycle', 'cache_policy'):
                    if row.get(field) is not None and row[field] != case.get(field):
                        raise ValueError(f"measurement context differs from requested case: {case['case_id']}/{field}")
            ok = [row for row in primary if row['status'] == 'ok']
            frozen = component_index.get((manifest['name'], case['dataset_id'], case.get('raw_object_id')))
            if case.get('status') == 'ready' and frozen is None:
                raise ValueError(f"ready case has no matching frozen input identity: {case['case_id']}")
            point = {
                **case, **coverage, 'run_id': manifest['run_id'],
                'task': manifest['resolved_config']['task'], 'source_id': case['dataset'].get('source', case['dataset_id']),
                'admission': case['status'], 'condition': pair_condition(case, manifest),
                'logical_component_identity': frozen['logical_component_identity'] if frozen else None,
                'component_layouts': frozen['component_layouts'] if frozen else None,
                'component_hashes': frozen['components'] if frozen else None,
                'primary_trace': [{key: row.get(key) for key in ('session', 'round', 'attempt', 'status', 'stage', 'reason',
                                                               'observation_line', 'artifact_hash', 'implementation_id')} for row in primary],
                'all_attempts_trace': attempts[case['case_id']],
                'scheduled_session_rounds': [[key[1], key[2]] for key in sorted(planned.get(case['case_id'], set()))],
                'session_summaries': _session_summary(case['case_id'], selected, planned),
                'performance_scope': 'all exact scheduled trials' if coverage['complete'] else 'conditional on successful primary attempts',
            }
            for metric in (*METRICS, 'payload_bytes', 'header_bytes'):
                point[metric] = _distribution([row.get(metric) for row in ok])
            point['quality'] = {metric: _distribution([row.get('verification', {}).get(metric) for row in primary])
                                for metric in ('max_abs', 'rmse', 'nrmse', 'psnr_db', 'effective_absolute_bound')}
            pair_key = (stable_hash(point['condition']), case['method_id'])
            if pair_key in by_pair_condition:
                raise ValueError('duplicate exact condition/method case')
            by_pair_condition[pair_key] = point
            run_points.append(point)
        for candidate in run_points:
            if candidate['method_id'] != baseline:
                reference = by_pair_condition.get((stable_hash(candidate['condition']), baseline))
                pairs.append(paired_row(reference, candidate, manifest, 'scheme'))
        layout_groups = defaultdict(dict)
        for point in run_points:
            layouts = point.get('component_layouts') or {}
            if layouts.get('V') not in {'C', 'F'} or point.get('logical_component_identity') is None:
                continue
            # C/F raw IDs intentionally differ; retain all other method/resource/boundary fields.
            condition = {key: point[key] for key in ('task', 'profile', 'method', 'boundary', 'lifecycle', 'cache_policy',
                                                    'source_id', 'logical_component_identity')}
            key, order = stable_hash(condition), layouts['V']
            if order in layout_groups[key]:
                raise ValueError('duplicate logical-data/method/layout condition')
            layout_groups[key][order] = point
        for group in layout_groups.values():
            if 'C' in group and 'F' in group:
                pairs.append(paired_row(group['C'], group['F'], manifest, 'layout'))
        points.extend(run_points)
    result = {
        'schema': 'tsbench.real-object-analysis/1', 'analysis_code_sha256': sha256(Path(__file__)),
        'dependency_sha256': {str(Path(module.__file__).resolve()): sha256(Path(module.__file__)) for module in
                              (__import__('tsbench.trial_analysis', fromlist=['_']), __import__('tsbench.study', fromlist=['_']),
                               __import__('tsbench.report', fromlist=['_']), __import__('tsbench.records', fromlist=['_']))},
        'component_pairing_path': str(component_path.resolve()), 'component_pairing_sha256': sha256(component_path),
        'runs': inputs, 'requested_cases': len(points), 'complete_cases': sum(point['complete'] for point in points),
        'planned_trials': sum(run['scheduled_trials'] for run in inputs),
        'source_count': len({point['source_id'] for point in points}),
        'primary_policy': 'earliest executed attempt; not_run placeholders skipped when execution exists; recovered unfinished operation remains a primary error even if resumed successfully',
        'pair_policy': 'exact schedules must complete with valid source provenance; full task/profile/boundary and allocation match; scheme uses identical raw_object_id; layout uses frozen exact component bits and preserves both raw IDs',
        'inference': 'none; only two selected sources; all rows are conditional exploratory descriptions, no overall winner, p-values or population generalization',
        'cases': points, 'paired_comparisons': pairs,
        'available_pair_counts': dict(Counter(pair['pair_kind'] for pair in pairs if pair['pair_available'])),
        'requested_pair_counts': dict(Counter(pair['pair_kind'] for pair in pairs)),
    }
    result['analysis_id'] = stable_hash(result)
    # All input validation finishes before any output is written.
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination/'summary.json', result)
    lines = ['# Real object and scheme study', '',
             f"Requested cases: {result['requested_cases']}; complete: {result['complete_cases']}; exact scheduled trials: {result['planned_trials']}.", '',
             'The two sources, nested windows, reused channels/layouts and sessions support exploratory descriptions. No overall winner or significance claim.', '',
             '| Kind | Run | Baseline → candidate | Complete pair | Encode ratio | Decode ratio | Complete wire ratio |',
             '|---|---|---|---|---:|---:|---:|']
    for pair in pairs:
        medians = pair.get('descriptive_session_ratio_median', {})
        metrics = [f'{medians[metric]:.6g}' if metric in medians else '—' for metric in METRICS]
        lines.append('| ' + ' | '.join([pair['pair_kind'], pair['run_id'][:12],
                                       str(pair['baseline_case_id'])+' → '+pair['candidate_case_id'],
                                       'yes' if pair['pair_available'] else pair['reason'], *metrics]) + ' |')
    lines.extend(['', 'Ratios are baseline/candidate, computed from per-session median rounds. Values above one mean candidate faster or smaller.',
                  'Layout rows are C/F interventions with identical component bits and different exact canonical objects. Schema, source hashes, all statuses, schedules, implementation/runtime conditions and raw trial traces are retained in summary.json.'])
    (destination/'README.md').write_text('\n'.join(lines)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('freeze-components')
    freeze.add_argument('--characterization', type=Path, default=ROOT/'docs/data_characterization/real_objects.json')
    freeze.add_argument('--output', type=Path, default=ROOT/'docs/data_characterization/component_pairing.json')
    inspect = commands.add_parser('analyze')
    inspect.add_argument('runs', nargs='+', type=Path)
    inspect.add_argument('--output', type=Path, required=True)
    inspect.add_argument('--components', type=Path, default=ROOT/'docs/data_characterization/component_pairing.json')
    inspect.add_argument('--baselines', type=Path, help='JSON mapping manifest experiment name to declared baseline method id')
    args = parser.parse_args()
    if args.command == 'freeze-components':
        result = freeze_components(args.characterization, args.output)
        print(json_text({'objects': len(result['objects']), 'output': str(args.output), 'codec_execution': False}), end='')
    else:
        baselines = json.loads(args.baselines.read_text()) if args.baselines else None
        result = analyze(args.runs, args.output, args.components, baselines)
        print(json_text({key: result[key] for key in ('analysis_id', 'requested_cases', 'complete_cases', 'planned_trials',
                                                      'available_pair_counts', 'requested_pair_counts')}), end='')
