"""Materialize bounded CORAD inputs from a previously rederived corpus definition."""
from hashlib import sha256
import struct

from ..assets import content_id, require
from ..corpus_ingress import read_batches
from .corad_corpus import calibrate_quality


def _id(blob):
    return {'bytes':len(blob), 'sha256':sha256(blob).hexdigest()}


def bind_cohort(root, entry, cohort, layout):
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
    require(len(ranges)>1 and (sum(b-a for a,b in ranges)*8*(width+1)) <= 16<<20, 'CORAD cohort workspace exceeded')
    words = [[bytearray() for _ in range(width)] for _ in ranges]
    ticks = [bytearray() for _ in ranges]
    sentinel = struct.pack('<d', -9999) if entry['parser']['missing']=='retain_source_minus_9999' else None
    cursor = 0
    for batch in read_batches(root, entry):
        while cursor < len(ranges) and ranges[cursor][0] < batch.start + batch.rows:
            a, b = ranges[cursor]
            lo0, hi0 = max(a, batch.start)-batch.start, min(b, batch.start+batch.rows)-batch.start
            if lo0 < hi0:
                ticks[cursor].extend(batch.axis[lo0*8:hi0*8])
                stride = 8*entry['value_count']
                for r in range(lo0,hi0):
                    for j in range(width):
                        p = r*stride+8*(c0+j)
                        word = batch.values[p:p+8]
                        require(word != sentinel, 'CORAD selected a retained missing value')
                        words[cursor][j].extend(word)
            if b > batch.start+batch.rows:
                break
            cursor += 1
    require(cursor==len(ranges), 'CORAD source did not cover all bound row ranges')
    payloads = [b''.join(w) for w in words]
    refs = []
    for (a,b), time, values in zip(ranges,ticks,payloads,strict=True):
        require(len(time)==8*(b-a) and len(values)==width*len(time), 'incomplete CORAD extracted shape')
        sequence = [t for t, in struct.iter_unpack('<q', time)]
        require(all(t0<=t1 for t0,t1 in zip(sequence,sequence[1:])), 'CORAD selected unordered time labels')
        refs.append({'absolute_rows':[a,b], 'first_tick':sequence[0], 'last_tick':sequence[-1],
                     'time':_id(time), 'values':_id(values)})
    require(all(refs[0]['last_tick'] < f['first_tick'] for f in refs[1:]), 'CORAD train/heldout time overlap')
    bounds = calibrate_quality(payloads[0], count=hi-lo, width=width)
    input_binding = {'source':entry['id'], 'canonical_object_id':entry['canonical']['object_id'],
                     'cohort_id':cohort['cohort_id'], 'producer_binding_ids':cohort['producer_binding_ids'],
                     'ordered_columns':cohort['ordered_column_names'], 'profile_id':content_id(layout),
                     'train':refs[0], 'test_frames':refs[1:], 'train_only_quality_bounds':bounds}
    return {**input_binding, 'input_binding_id':content_id(input_binding)}, payloads[0], payloads[1:]
