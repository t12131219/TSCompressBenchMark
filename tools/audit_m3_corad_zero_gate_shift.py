#!/usr/bin/env python3
"""Distinguish constant-column reconstruction issues from train→development shift."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from m3_corad_sparse_development import ROOT, _identity, binding, check, ref, seal, train_dev_matrix
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, parse_json, require

SCHEMA = 'bmk.m3-corad-zero-gate-shift/1'


def classify(train, development, gate):
    require(train.size and development.size and Fraction(gate['max_abs_error']) == Fraction(gate['mse']) == 0,
            'zero-gate attribution requires a nonempty train and development column')
    x = train[0]
    require(np.isfinite(train).all() and np.isfinite(development).all() and np.all(train == x) and
            Fraction(float(x)) == Fraction(gate['constant_predictor']), 'training predictor is not an exact observed constant')
    values = int(development.size)
    equal = int(np.count_nonzero(development == x))
    different_values = int(np.unique(development).size)
    label = ('same_as_train' if equal == values else 'different_constant' if different_values == 1 else 'variable')
    full = values // 4 * 4
    mismatches = (development[:full] != x).reshape(-1, 4)
    return {'classification': label, 'values': values, 'values_different_from_training_constant': values-equal,
            'distinct_development_numeric_values': different_values, 'complete_tricklets': full//4,
            'complete_tricklets_not_recoverable_by_training_constant': int(np.count_nonzero(np.any(mismatches, axis=1)))}


def _expected(run, report):
    cases = defaultdict(list)
    count = 0
    with local_file(run, 'trials.jsonl').open('rb') as f:
        for line in f:
            r = parse_json(line, 'CORAD development trial')
            k, d = r['key'], r['decision']
            if k['nonzero'] == 4 and d['terminal'] == 'quality_rejected':
                bad = [x['column'] for x in d['quality'] if not (x['max_abs_error_within_bound'] and x['mse_within_bound'])]
                require(bad and len(bad) == len(set(bad)), 'ambiguous CORAD quality rejection columns')
                cases[k['dataset_id']].append((k, bad))
                count += 1
    require(count == report['totals']['4']['quality_rejected'] > 0, 'zero-gate source rejected-frame denominator differs')
    return cases, count


def audit(run):
    plan = load_json(local_file(run, 'plan.json'))
    saved = load_json(local_file(run, 'completion.json'))
    require(plan['dataset_projection'] is None and saved == seal(run, plan), 'expected sealed full development evidence')
    report = load_json(local_file(run, 'report.json'))
    require(report['held_out_run'] is False and report['selected_nonzero_on_full_development'] is None,
            'unexpected model selection or held-out execution')
    cases, frame_count = _expected(run, report)
    guard = check(ROOT, plan['source_guard']).parent
    build = check(ROOT, plan['build'])
    totals, by_dataset, column_windows, details = Counter(), {}, {}, []
    with TemporaryDirectory(prefix='corad-dev-zero-gates-') as tmp:
        for ds in sorted(cases):
            (entry, groups, _), = binding(guard, build, ds)
            require(entry['partitions'][1] == plan['files'][ds]['development'], 'development scope changed')
            folder = Path(tmp)/ds
            folder.mkdir()
            source = train_dev_matrix(ROOT, entry, folder)
            index = {g['id']:g for g in groups}
            split = Counter()
            for key, bad in cases[ds]:
                g = index[key['input_binding_id']]
                lo, hi = key['development_rows']; partition = entry['partitions'][1]
                require(partition['start'] <= lo < hi <= partition['end'] and key['columns'] == g['column_names'] and
                        key['model'] == g['models'][key['producer']], 'rejected case not bound to its frozen cohort')
                columns = g['columns']
                dev = source[lo:hi, columns]
                require(_identity(dev.T.tobytes()) == key['development_input'], 'development trial bytes differ')
                a, z = g['train']['absolute_rows']
                train = source[a:z, columns]
                require(_identity(train.T.tobytes()) == g['train']['values'], 'training fragment bytes differ')
                for col in bad:
                    i = g['column_names'].index(col)
                    facts = classify(train[:,i], dev[:,i], g['gates'][i])
                    split[facts['classification']] += 1
                    split['rejected_column_observations'] += 1
                    for field in ('values', 'values_different_from_training_constant', 'complete_tricklets',
                                  'complete_tricklets_not_recoverable_by_training_constant'):
                        split[field] += facts[field]
                    physical = (ds, lo, hi, col)
                    require(column_windows.setdefault(physical, facts) == facts, 'producer variants disagree on original values')
                    details.append({'dataset':ds, 'column':col, 'rows':[lo,hi], 'trainer':key['producer'], **facts})
            by_dataset[ds] = dict(split)
            totals.update(split)
    body = {'schema':SCHEMA, 'scope':'development_only_zero_gate_attribution_no_model_selection_or_codecs_run',
            'source_seal':ref(ROOT, run/'completion.json'), 'source_seal_id':saved['seal_id'],
            'rejected_frames':frame_count, 'unique_dataset_column_windows':len(column_windows),
            'per_trainer_observation_totals':dict(totals), 'datasets':by_dataset, 'details':details,
            'held_out_read':False, 'stage_accepted':False, 'qualification_granted':False, 'timing_admitted':False}
    return {**body, 'audit_id':content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out', type=Path)
    out.add_argument('--verify', type=Path)
    a = p.parse_args()
    try:
        result = audit(a.run.resolve(strict=True))
        if a.out:
            write_new(a.out, result)
        else:
            require(result == load_json(a.verify), 'zero-gate attribution differs from advisory report')
        print(result['audit_id'], result['unique_dataset_column_windows'], result['per_trainer_observation_totals'])
    except (KeyError, OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
