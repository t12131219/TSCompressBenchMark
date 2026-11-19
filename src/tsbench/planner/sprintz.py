"""Freeze the Sprintz-FIRE typed worker and direct-source case definitions."""
import struct
from hashlib import sha256

from ..assets import content_id

TEST = 'tsbench.worker.sprintz-fire.recovery'
REPORT = 'sprintz-native-control.json'
WORKER_SCHEMA = {'dtype': 4, 'rank': 1, 'role': 'value'}
NATIVE_REJECTIONS = ['zero_lanes', '129_lanes', 'encode_above_default_limit', 'encode_odd_u16_bytes']
WORKER_REJECTIONS = {'f64': 1, 'above_worker_limit': 7}
DECODE_REJECTIONS = ['outer_trailing', 'outer_dtype', 'sfb1_raw_length', 'sfb1_raw_crc', 'sfb1_payload']

# name, bits, lanes, count, message limit in bytes, participates in worker ABI
SHAPES = (
    ('empty',       16,   4,      0, 65536, True),
    ('sub-row',     16,   4,      3, 65536, True),
    ('worker-tail', 16,   4,   1031, 65536, True),
    ('worker-cap',  16,   4,  32768, 65536, True),
    ('u8-lowdim',    8,   4,    131, 65536, False),
    ('u8-generic',   8,   5,    263, 65536, False),
    ('u8-wide',      8, 128,   3201, 65536, False),
    ('u16-lowdim',  16,   2,    133, 65536, False),
    ('u16-wide-sum',16,   3, 198001, 524288, False),
)
CHECKS = {
    'fire-batch': {
        'u8_u16_lowdim_generic': ['u8-lowdim', 'u8-generic', 'u16-lowdim', 'worker-tail'],
        'dims_and_short_tail': ['sub-row', 'worker-tail', 'u8-wide'],
        'channel_count_and_size_reject': ['worker-cap'],
        'native_payload_and_frame': ['empty', 'sub-row', 'worker-tail', 'worker-cap'],
        'distinct_shape_recovery': ['u8-lowdim', 'u8-generic', 'u8-wide', 'u16-lowdim', 'u16-wide-sum'],
    },
    'query': {
        'unsigned_count_sum_max': ['u8-lowdim', 'u8-generic', 'u16-lowdim', 'worker-tail'],
        'generic_avx2_and_lowdim_fallback': ['u8-lowdim', 'u8-generic', 'u16-lowdim', 'worker-tail'],
        'query_matches_original': [row[0] for row in SHAPES],
        'per_channel_accumulator_and_tail': ['sub-row', 'u8-wide', 'u16-wide-sum'],
        'input_range_and_message_limits': ['worker-cap', 'u16-lowdim', 'u16-wide-sum'],
    },
}


def plain(name, width, dims, count):
    mask = (1 << width) - 1
    if name in {'empty', 'sub-row', 'worker-tail', 'worker-cap'}:
        values = ((i // dims) ** 2 + (i % dims) * 40001 for i in range(count))
    elif name == 'u16-wide-sum':
        # The first lane exceeds UINT32_MAX; the other lanes and final partial
        # row reveal accidental broadcasting, overflow or loss of one lane.
        values = (mask - i % dims for i in range(count))
    else:
        values = ((mask if (i // dims) == (i % dims) % 3 else
                   (i // dims) ** 2 + (i % dims) * 41) for i in range(count))
    return struct.pack(f'<{count}{"B" if width == 8 else "H"}', *(x & mask for x in values))


def ref(name, data):
    return {'path': name, 'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def plan_sprintz():
    shapes = []
    for name, width, dims, count, limit, worker in SHAPES:
        shapes.append({'name': name, 'width': width, 'dims': dims, 'count': count,
                       'message_limit_bytes': limit, 'algorithm': 1, 'path': 0,
                       'native_frame': name + '.sfb1', 'worker_frame': name + '.bmk' if worker else None,
                       'original': ref('generated:' + name, plain(name, width, dims, count))})
    cases = []
    shape_ids = {shape["name"]: content_id(shape) for shape in shapes}
    for route, checks in CHECKS.items():
        for check, names in checks.items():
            row = {'name': f'sprintz-{route}-{check.replace("_", "-")}', 'selection': 19, 'route': route,
                   'check': check, 'shapes': {name: shape_ids[name] for name in names},
                   'validator': 'sfb1_structure_literal_tail_query_oracle_and_detached_recovery/1'}
            cases.append({**row, 'case_id': content_id(row)})
    body = {'schema': 'bmk.sprintz-cases/1', 'test': TEST, 'evidence_path': REPORT,
            'fixture_generator': 'sprintz-fire-unsigned/1', 'shapes': shapes, 'cases': cases,
            'worker_schema': WORKER_SCHEMA, 'native_rejections': NATIVE_REJECTIONS,
            'worker_rejections': WORKER_REJECTIONS, 'decode_rejections': DECODE_REJECTIONS,
            'qualification_granted': False}
    return {**body, 'bundle_id': content_id(body)}


def retained_paths(bundle):
    return {frame for shape in bundle['shapes'] for frame in (shape['native_frame'], shape['worker_frame']) if frame}
