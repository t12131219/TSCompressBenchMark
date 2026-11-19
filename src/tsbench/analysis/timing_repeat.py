"""Compare two whole executions without pooling samples or promoting qualification."""
from pathlib import Path
from statistics import median

from ..application.timing import DIRECTIONS, read_report
from ..assets import require
from ..planner.frame_batches import LANES


def compare_timing_repeats(root: Path, first: str, second: str):
    require(first != second, 'repeat analysis needs two distinct sealed runs')
    _, a = read_report(root, first)
    _, b = read_report(root, second)
    require(a['plan_content_id'] == b['plan_content_id'], 'repeat runs do not share one frozen timing plan')
    results = []
    for g, h in zip(a['groups'], b['groups'], strict=True):
        require(g['group_id'] == h['group_id'], 'repeat comparison group differs')
        rounds = {first: g['complete_matched_rounds'], second: h['complete_matched_rounds']}
        loops = {first: g['calibrated_loops'], second: h['calibrated_loops']}

        def stats(group, lane, direction):
            n = group['calibrated_loops']
            values = [p[direction][lane] / n for p in group['paired_observations']]
            return {'matched_batch_samples': len(values), 'ns_per_operation': values,
                    'min': min(values, default=None), 'median': median(values) if values else None,
                    'max': max(values, default=None)}

        lanes = {}
        for lane in LANES:
            lanes[lane] = {}
            for d in DIRECTIONS:
                x, y = stats(g, lane, d), stats(h, lane, d)
                lanes[lane][d] = {first: x, second: y,
                    'median_second_over_first': y['median'] / x['median'] if x['median'] and y['median'] else None}
        results.append({key: g[key] for key in ('group_id', 'case', 'method', 'lifecycle')} |
                       {'matched_rounds_by_run': rounds, 'calibrated_loops_by_run': loops,
                        'different_batch_lengths': g['calibrated_loops'] != h['calibrated_loops'], 'lanes': lanes})
    return {'schema': 'bmk.timing-repeat-comparison/1', 'plan_content_id': a['plan_content_id'],
            'runs': [first, second], 'formal_performance': False, 'samples_pooled': False,
            'statuses': {first: a['statuses'], second: b['statuses']},
            'resource_observations': {first: a['resource_observations'], second: b['resource_observations']},
            'limitations': ['loop_normalization_does_not_equalize_batching_or_cache_state',
                            'advisory_counters_do_not_attribute_variance_to_interference_or_frequency',
                            'runs_on_one_shared_host_not_independent_hardware_replicates'], 'groups': results}
