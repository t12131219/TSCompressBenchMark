"""Bind source-side Titchy batch, stream and access cases to one probe."""
from hashlib import sha256

from ..assets import canonical_bytes, content_id, require
from .titchy_access import BACKING, EVIDENCE, PROBE, TRANSFORM

LIMIT = 1_000_000
BATCH_POLICY = {'chunk': 4, 'split': 1000, 'endian': 0, 'threshold_ppm': 250000, 'active_bytes': 2**64 - 1}
TSTR_FILE, TSC1_FILE = 'stream.tstr', 'stream.tsc1'
KNOWN_REJECTIONS = {
    'batch_input': {'worker_f64': 1, 'worker_unknown_option': 3, 'worker_count': 7,
                    'native_encode_capacity': 2, 'native_decode_capacity': 2, 'native_decode_quota': 2},
    'batch_frames': {'truncated': 5, 'outer_trailing': 5, 'count_mismatch': 5, 'count_limit': 7,
                     'dtype_mismatch': 5, 'unexpected_endian': 5, 'native_trailing': 5},
    'stream': {'blocked_push': 2, 'blocked_finish': 2, 'small_pop': 2, 'small_output_retry': 2,
               'truncated_packet': 4, 'decode_after_corruption': 1, 'tail_quota': 2,
               'decode_after_quota': 1, 'push_after_finish': 1, 'finish_after_finish': 1,
               'empty_session_overflow': 1, 'finish_after_overflow': 1},
    'access': {'file_quota': 2, 'file_missing': 1, 'index_callback_failure': 4, 'pair_callback_failure': 4,
               'bad_index': 4, 'touched_bad_pair': 4, 'stateless_unrelated_bad_pair': 4,
               'stateless_bad_pair_empty_request': 4, 'stateless_capacity': 2, 'stateless_quota': 2,
               'stateless_oob': 1, 'reader_capacity': 2, 'reader_range_oob': 1,
               'reader_sample_oob': 1, 'reader_bit_oob': 1},
}
CHECKS = {
    'batch': ['u8_u16_u32_u64', 'chunk_and_split_boundaries', 'independent_frame_count',
              'native_frame_agreement', 'size_capacity_and_options_rejected'],
    'packet-stream': ['packet_before_finish', 'backpressure_retry', 'tail_and_reset', 'bounded_padded_values',
                      'finish_and_truncation', 'independent_tsc1_restore'],
    'loaded-file-access': ['open_index_validation', 'separate_capacity_and_bounds', 'touched_pair_corruption',
                           'repeated_immutable_reader'],
    'batch-range': ['unrelated_split_corruption', 'whole_container_validation', 'output_quota_and_capacity',
                    'input_range_reject'],
}


def sha(wire):
    return sha256(wire).hexdigest()


def words(wire, width=64):
    import struct
    return tuple(v for (v,) in struct.iter_unpack({8: '<B', 16: '<H', 32: '<I', 64: '<Q'}[width], wire))


def pack(values, width=64):
    return b''.join(v.to_bytes(width//8, 'little') for v in values)


def fixtures(source, window):
    yield 'empty', 64, (), {}
    for bits in (8, 16, 32, 64):
        yield f'u{bits}-tail', bits, (0, 1, (1 << bits)-1, 1 << (bits-1), (1 << (bits-1))-1), {}
    yield 'explicit-f64-special-bits', 64, (0x8000000000000000, 0x7ff8000000000021, 0x7ff0000000000000,
                                          0xfff0000000000000, 1), {'transform': TRANSFORM}
    for n in (3, 4, 3999, 4000, 4001, window['count']):
        name = 'traffic-split-and-tail' if n == window['count'] else f'traffic-{n}'
        yield name, 64, words(source[:8*n]), {'window': {**window, 'count': n}, 'transform': TRANSFORM}


def retained_paths(bundle):
    return {bundle['backing_path'], TSTR_FILE, TSC1_FILE, *(s['artifact'] for s in bundle['batch'])}


def plan_titchy_native(access, cfg, source):
    require(cfg['batch'] == {'plugin':'titchy-batch', 'role':'value', 'options':{}, 'widths':[8,16,32,64]},
            'invalid Titchy batch case policy')
    require(canonical_bytes(cfg['stream']) == canonical_bytes({'chunks_per_packet':7, 'max_active_bytes':72,
             'validator':'native_packet_and_tstr_detached_bits_v1'}), 'invalid Titchy stream case policy')
    oracle = access['cases'][0]
    window = oracle['window']
    require(window['count'] == 4013 and len(source) == 8 * window['count'] and sha(source) == oracle['input_sha256'],
            'invalid Titchy boundary source identity')
    batch = []
    for name, bits, values, lineage in fixtures(source, window):
        batch.append({'case': name, 'bits_per_sample': bits, 'count': len(values),
                      'input_sha256': sha(pack(values, bits)), 'artifact': f'titchy-{name}.bmk', **lineage})
    stream = {**cfg['stream'], 'archive': TSTR_FILE, 'config': TSC1_FILE, 'count': window['count'],
              'input_sha256': oracle['input_sha256'], 'max_artifact_bytes': 128 << 10}
    body = {'schema': 'bmk.titchy-native-cases/1', 'test': PROBE, 'evidence_path': EVIDENCE, 'backing_path': BACKING,
            'access_bundle_id': access['bundle_id'], 'batch_policy': BATCH_POLICY, 'batch': batch, 'stream': stream,
            'status_policy': KNOWN_REJECTIONS, 'qualification_granted': False}
    cases = []
    common = content_id(body)
    for route, checks in CHECKS.items():
        for check in checks:
            row = {'name': f'titchy-{route}-{check.replace("_", "-")}', 'selection': 85, 'route': route,
                   'check': check, 'input_and_policy_id': common}
            cases.append({**row, 'case_id': content_id(row)})
    body['cases'] = cases
    return {**body, 'bundle_id': content_id(body)}
