"""Gather all frozen M3 CORAD cohorts per file without reparsing it per cohort."""
from hashlib import sha256
import struct

import numpy as np

from ..assets import content_id, require
from ..corpus_ingress import read_batches
from .corad_corpus import calibrate_quality


def _id(blob):
    return {'bytes':len(blob), 'sha256':sha256(blob).hexdigest()}


def _ranges(entry, cohort, layout):
    require(cohort['state'] == 'eligible' and cohort['source_object_id'] == entry['canonical']['object_id'],
            'CORAD cohort is not eligible for this source')
    c0, c1 = cohort['columns']; width = c1-c0
    require(0 <= c0 < c1 <= entry['value_count'] and 2 <= width <= layout['max_columns'] and
            cohort['ordered_column_names'] == entry['columns'][c0+1:c1+1], 'CORAD ordered columns differ')
    train, _, test = entry['partitions']
    lo, hi = cohort['train']['rows']
    require(train['start'] <= lo < hi <= train['end'] <= test['start'] and hi-lo==layout['train_rows'] and
            cohort['train']['source_id']==train['canonical']['object_id'] and
            cohort['test']['source_id']==test['canonical']['object_id'], 'CORAD train and test identities overlap or differ')
    cap = cohort['test']['max_rows_per_frame']
    require(0 < cap <= layout['max_test_rows_per_frame'] and cap*width <= layout['max_values_per_frame'],
            'CORAD frame exceeds the declared extent')
    ranges = [(lo, hi)]
    previous = test['start']
    for a,b in cohort['test']['eligible_row_spans']:
        require(previous <= a < b <= test['end'], 'CORAD held-out ranges differ or overlap')
        ranges.extend((i, min(i+cap,b)) for i in range(a,b,cap))
        previous = b
    cost = sum(b-a for a,b in ranges)*8*(width+1)
    require(len(ranges)>1 and cost <= 16<<20, 'CORAD cohort workspace exceeded')
    return ranges, cost


def _finish(entry, cohort, layout, ranges, ticks, words):
    width = len(cohort['ordered_column_names'])
    payloads = [b''.join(w) for w in words]
    refs = []
    for (a,b), time, values in zip(ranges,ticks,payloads,strict=True):
        require(len(time)==8*(b-a) and len(values)==width*len(time), 'incomplete CORAD extracted shape')
        sequence = [t for t, in struct.iter_unpack('<q', time)]
        require(all(t0<=t1 for t0,t1 in zip(sequence,sequence[1:])), 'CORAD selected unordered time labels')
        refs.append({'absolute_rows':[a,b], 'first_tick':sequence[0], 'last_tick':sequence[-1],
                     'time':_id(time), 'values':_id(values)})
    require(all(refs[0]['last_tick'] < f['first_tick'] for f in refs[1:]), 'CORAD train/heldout time overlap')
    bounds = calibrate_quality(payloads[0], count=ranges[0][1]-ranges[0][0], width=width)
    input_binding = {'source':entry['id'], 'canonical_object_id':entry['canonical']['object_id'],
                     'cohort_id':cohort['cohort_id'], 'producer_binding_ids':cohort['producer_binding_ids'],
                     'ordered_columns':cohort['ordered_column_names'], 'profile_id':content_id(layout),
                     'train':refs[0], 'test_frames':refs[1:], 'train_only_quality_bounds':bounds}
    return {**input_binding, 'input_binding_id':content_id(input_binding)}, payloads[0], payloads[1:]


def bind_cohorts(root, entry, cohorts, layout):
    """Collect the declared disjoint cohorts with one verified source scan per file."""
    cohorts = tuple(cohorts)
    require(cohorts, 'CORAD has no eligible cohorts to materialize')
    specs = [_ranges(entry, cohort, layout) for cohort in cohorts]
    require(len({c['cohort_id'] for c in cohorts}) == len(cohorts) and all(
            a['columns'][1] <= b['columns'][0] for a,b in zip(cohorts, cohorts[1:])),
            'CORAD cohorts overlap or are unordered')
    require(sum(cost for _, cost in specs) <= 64 << 20, 'CORAD file extraction budget exceeded')
    groups = []
    for cohort, (ranges, _) in zip(cohorts, specs, strict=True):
        c0, c1 = cohort['columns']
        groups.append((c0, c1, ranges, [bytearray() for _ in ranges],
                       [[bytearray() for _ in range(c1-c0)] for _ in ranges]))
    cursors = [0] * len(groups)
    sentinel = (int.from_bytes(struct.pack('<d', -9999), 'little')
                if entry['parser']['missing'] == 'retain_source_minus_9999' else None)
    for batch in read_batches(root, entry):
        # View little-endian words as integers only for byte-preserving gather and
        # sentinel detection; never convert or reorder floating-point values.
        values = np.frombuffer(batch.values, dtype='<u8').reshape(batch.rows, entry['value_count'])
        end = batch.start + batch.rows
        for index, (c0, c1, ranges, ticks, words) in enumerate(groups):
            cursor = cursors[index]
            while cursor < len(ranges) and ranges[cursor][0] < end:
                a, b = ranges[cursor]
                lo, hi = max(a, batch.start)-batch.start, min(b, end)-batch.start
                if lo < hi:
                    ticks[cursor].extend(batch.axis[lo*8:hi*8])
                    slab = values[lo:hi, c0:c1]
                    require(sentinel is None or not np.any(slab == sentinel), 'CORAD selected a retained missing value')
                    for dst, column in zip(words[cursor], slab.T, strict=True):
                        dst.extend(column.tobytes())
                if b > end:
                    break
                cursor += 1
            cursors[index] = cursor
    require(all(cursor == len(ranges) for cursor, (_, _, ranges, _, _) in zip(cursors, groups, strict=True)),
            'CORAD source did not cover all bound row ranges')
    return [_finish(entry, cohort, layout, ranges, ticks, words)
            for cohort, (_, _, ranges, ticks, words) in zip(cohorts, groups, strict=True)]


