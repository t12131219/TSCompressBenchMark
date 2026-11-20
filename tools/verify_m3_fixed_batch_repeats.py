#!/usr/bin/env python3
"""Recompute two sealed M3 timing runs and compare drift without pooling them."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_batch_timing import DIRECTIONS, report_timing
from tsbench.application.smoke import _rows
from tsbench.assets import content_id, require
from tsbench.planner.frame_batches import EXTENTS, LANES


def verify(first, second):
    require(first != second and first.name != second.name, 'M3 repeat must have a distinct run identity')
    a, b = report_timing(first), report_timing(second)
    require(a['plan_content_id'] == b['plan_content_id'] and a['functional_seal_id'] == b['functional_seal_id'] and
            a['environment']['resource'] == b['environment']['resource'], 'M3 timing repeats use different policies or scope')
    sessions = [{r['process']['session_id'] for r in _rows(run / 'batches.jsonl') if r['process']['session_id']}
                for run in (first, second)]
    require(sessions[0].isdisjoint(sessions[1]), 'M3 timing repeat reused process sessions')
    details = []
    identity = ('group_id', 'case_id', 'dataset_id', 'route', 'unit_index', 'decode_backend', 'lifecycle', 'bytes')
    for x, y in zip(a['groups'], b['groups'], strict=True):
        require(all(x[k] == y[k] for k in identity), 'M3 repeat group identity differs')
        ids = {k: x[k] for k in identity}
        ratios = {}
        for lane in LANES:
            ratios[lane] = {}
            for d in DIRECTIONS:
                p, q = (g['lanes'][lane]['median_native_ns_per_operation'][d] for g in (x, y))
                complete = len(x['matched_rounds']) == len(y['matched_rounds']) == 3
                ratios[lane][d] = {'first_ns_per_op': p, 'second_ns_per_op': q,
                                   'second_over_first': q / p if complete and p and q else None}
        details.append({**ids, 'logical_over_complete_frame_ratio': ids['bytes']['logical_value_bytes'] /
                        ids['bytes']['complete_frame_bytes'], 'matched_rounds_by_run': [len(g['matched_rounds']) for g in (x, y)],
                        'repeat_ratios_not_pooled': ratios})
    drift = []
    for lifecycle in EXTENTS:
        for lane in LANES:
            for d in DIRECTIONS:
                values = [g['repeat_ratios_not_pooled'][lane][d]['second_over_first']
                          for g in details if g['lifecycle'] == lifecycle]
                measured = [abs(v - 1) for v in values if v is not None]
                drift.append({'lifecycle': lifecycle, 'lane': lane, 'direction': d, 'complete_groups': len(measured),
                              'median_abs_relative_change': median(measured) if measured else None,
                              'max_abs_relative_change': max(measured) if measured else None})
    body = {'schema': 'bmk.m3-fixed-batch-timing-repeat-audit/1', 'plan_content_id': a['plan_content_id'],
            'functional_seal_id': a['functional_seal_id'], 'runs': [{k: r[k] for k in ('run_id', 'seal_id', 'status_counts', 'environment')}
                                                                  for r in (a, b)],
            'matched_rounds_by_run': [sum(len(g['matched_rounds']) for g in r['groups']) for r in (a, b)],
            'drift_scope': 'descriptive_only_not_attributed_to_codec_or_host_no_exclusive_cpu',
            'drift': drift, 'groups': details, 'pooled': False, 'performance_admitted': False}
    return {**body, 'audit_id': content_id(body)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('first', type=Path)
    parser.add_argument('second', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.first.resolve(strict=True), args.second.resolve(strict=True)), indent=2, ensure_ascii=False))
