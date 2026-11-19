"""Closed-interval accounting for compatible host monotonic trace snapshots."""
from collections import Counter, defaultdict

from ..assets import require

STAGES = {
    1: ('L0', 'operation', ['operation']),
    2: ('L1', 'allocate_and_context_prepare', ['allocate', 'prepare']),
    3: ('L1', 'native_codec_and_cleanup', ['codec', 'finalize']),
    4: ('L1', 'write_and_close_file', ['serialize']),
    5: ('L2', 'generated::falp::x86_64::avx2::falp', ['unpack_bits', 'reconstruct']),
    6: ('L2', 'ZSTDMT_compressionJob', ['worker_job']),
}


def interval_union(rows):
    points = sorted((p, delta) for row in rows for p, delta in ((row['start_ns'], 1), (row['end_ns'], -1)))
    covered = overlapping = peak = active = last = 0
    for t, delta in points:
        if active:
            covered += t - last
        if active > 1:
            overlapping += t - last
        active += delta
        peak = max(peak, active)
        last = t
    require(active == 0, 'unclosed trace interval union')
    return covered, overlapping, peak


def summarize_trace(document, limit, observation, case, op):
    spans = document['spans']
    ids = {r['span_id']: r for r in spans}
    lost = document['dropped']
    require(document['capacity_per_thread'] == limit and len(ids) == len(spans), 'trace capacity or unique IDs differ')
    counts = Counter(r['stage'] for r in spans)
    expected = Counter({1: 1, 2: 1, 3: 1, 4: 1})
    if case == 'alp-fused' and op == 'decode':
        expected[5] = observation['alp_fused_vectors']
    if case == 'zstd-mt':
        expected[6] = observation['native_jobs']
    require(counts[1] == 1 and counts <= expected and sum(expected.values()) - len(spans) == lost,
            'trace event coverage differs from original execution counters')
    root = ids.get(1)
    require(root is not None and root['stage'] == 1 and root['parent_id'] == 0 and root['thread_id'] == observation['pid'] and
            0 < root['end_ns'] - root['start_ns'] <= observation['wall_ns'], 'invalid trace root or L0 duration')
    by_thread, children, work = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in spans:
        sid, parent, stage, tid = (row[k] for k in ('span_id', 'parent_id', 'stage', 'thread_id'))
        require(root['start_ns'] <= row['start_ns'] < row['end_ns'] <= root['end_ns'] and (sid - 1) % 256 < limit,
                'span outside L0 or allocated capacity')
        if stage != 1:
            p = ids.get(parent)
            expected_parent = 3 if stage == 5 else 1
            require(p and p['stage'] == expected_parent and p['start_ns'] <= row['start_ns'] <= row['end_ns'] <= p['end_ns'],
                    'span outside its declared parent')
            if stage != 6:
                require(tid == p['thread_id'], 'caller stage uses an unexpected thread')
            if p['thread_id'] == tid:
                children[parent].append(row)
        by_thread[tid].append(row)
        work[stage].append(row)
    require(len(by_thread) <= 16 and all(len(v) <= limit for v in by_thread.values()), 'thread capacity differs')
    for rows in by_thread.values():
        stack = []
        for r in sorted(rows, key=lambda x: (x['start_ns'], -x['end_ns'], x['span_id'])):
            while stack and stack[-1]['end_ns'] <= r['start_ns']:
                stack.pop()
            require(not stack or r['parent_id'] == stack[-1]['span_id'], 'crossing or mislabeled same-thread spans')
            stack.append(r)
    if case == 'zstd-mt' and op == 'encode' and not lost:
        native = work[6]
        require(len({r['thread_id'] for r in native if r['thread_id'] != root['thread_id']}) ==
                observation['native_worker_threads'] and sum(r['thread_id'] == root['thread_id'] for r in native) ==
                observation['native_caller_jobs'], 'observed worker threads differ from native counters')
    stages = []
    for key, rows in work.items():
        level, name, roles = STAGES[key]
        union, overlap, peak = interval_union(rows)
        stages.append({'stage': key, 'level': level, 'native_stage_name': name, 'roles': roles,
                       'status': 'fused' if key == 5 else 'measured', 'events': len(rows),
                       'observed_union_ns': union, 'observed_overlap_ns': overlap, 'max_observed_concurrency': peak,
                       'sum_thread_interval_ns_not_wall': sum(r['end_ns'] - r['start_ns'] for r in rows),
                       'complete_for_instrumented_points': not lost})
    missing = [{'stage': stage, 'status': 'not_measured', 'value_ns': None} for stage in expected if expected[stage] and not counts[stage]]
    root_caller_coverage = interval_union(children[1])[0]
    return {'clock_id': 'host_monotonic_ns', 'sampling': 'every_instrumented_call_until_per_thread_capacity',
            'dropped': lost, 'observed_spans': len(spans), 'stages': sorted(stages, key=lambda p:p['stage']),
            'missing_stages': missing, 'caller_unattributed_ns': None if lost else root['end_ns'] - root['start_ns'] - root_caller_coverage}
