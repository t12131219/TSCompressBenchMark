"""Re-materialize a CORAD inference trial's exact held-out inputs from raw text."""
from bisect import bisect_right
from collections import defaultdict

import numpy as np

from ..assets import require
from ..corpus_ingress import read_batches
from .m3_in_run_corad import _identity


def _key(case):
    return case['b']['input_binding_id'], tuple(case['span']['absolute_rows'])


def materialize(root, entry, cases):
    """Exhaust the locked parser once; gather only held-out V and its source axis.

    Two trained-model variants share the same ingress. Each focus interval is
    bound to the independently verified same-run input before native work starts.
    """
    specs, cohorts = {}, defaultdict(dict)
    require(cases and len(entry['columns']) == entry['value_count'] + 1, 'empty CORAD ingress or invalid source columns')
    positions = {column: i for i, column in enumerate(entry['columns'][1:])}
    require(len(positions) == entry['value_count'], 'ambiguous CORAD ingress columns')
    test = entry['partitions'][2]
    for case in cases:
        b, span = case['b'], case['span']
        key = _key(case)
        cid, (a, z) = key
        require(entry['id'] == b['source'] and entry['canonical']['object_id'] == b['canonical_object_id'] and
                test['start'] <= a < z <= test['end'] and span in b['test_frames'], 'CORAD ingress cannot select outside frozen held-out bounds')
        cols = tuple(positions.get(name, -1) for name in b['ordered_columns'])
        require(cols and all(i >= 0 for i in cols) and cols == tuple(range(cols[0], cols[0] + len(cols))),
                'CORAD ingress column order or source differs')
        require(key not in specs or specs[key] == (cols, span), 'CORAD producer variants disagree on raw input')
        specs[key] = cols, span
        cohorts[cid][a] = (z, key)
    require(sum(spec[1]['values']['bytes'] + spec[1]['time']['bytes'] for spec in specs.values()) <= 64 << 20,
            'CORAD held-out ingress materialization exceeds the declared file budget')
    columns = {key: [bytearray() for _ in cols] for key, (cols, _) in specs.items()}
    axes = {key: bytearray() for key in specs}
    lanes = []
    for group in cohorts.values():
        starts = sorted(group)
        require(all(group[a][0] <= b for a, b in zip(starts, starts[1:])), 'overlapping CORAD ingress frames')
        lanes.append((starts, group))
    for batch in read_batches(root, entry):
        end = batch.start + batch.rows
        array = np.frombuffer(batch.values, dtype='<u8').reshape(batch.rows, entry['value_count'])
        for starts, group in lanes:
            i = max(0, bisect_right(starts, batch.start) - 1)
            while i < len(starts) and starts[i] < end:
                start = starts[i]
                stop, key = group[start]
                a, z = max(start, batch.start) - batch.start, min(stop, end) - batch.start
                if a < z:
                    axes[key].extend(batch.axis[a*8:z*8])
                    for col, dst in zip(specs[key][0], columns[key], strict=True):
                        dst.extend(array[a:z, col].tobytes())
                i += 1
    payloads, records = {}, []
    for key, (_, span) in specs.items():
        raw = b''.join(columns[key])
        ident = _identity(raw), _identity(axes[key])
        require(ident == (span['values'], span['time']), 'CORAD held-out raw ingress differs from the locked same-run slice')
        payloads[key] = raw
        records.append({'input_binding_id': key[0], 'absolute_rows': list(key[1]), 'values': ident[0], 'time': ident[1]})
    return [{**c, 'raw': payloads[_key(c)]} for c in cases], records


def expected_records(cases):
    facts = {}
    for case in cases:
        span = case['span']
        key = _key(case)
        facts[key] = {'input_binding_id': key[0], **{k: span[k] for k in ('absolute_rows', 'values', 'time')}}
    return list(facts.values())
