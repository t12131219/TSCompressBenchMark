"""Freeze the Gorilla C11 batch, snapshot and forward iterator diagnostic inputs."""
from hashlib import sha256
import struct

from ..assets import content_id, load_json, local_file, require
from .corpus_windows import bind_window, read_tv_window

CONFIG = 'configs/suites/dev_gorilla_tv_v1/cases.json'
DIR = 'gorilla-tv-control'
TEST = 'tsbench.worker.gorilla-tv.recovery'
PLUGIN = 'gorilla-tv'
LIMIT = 512
PREFIX = 23
SCHEMA = b'{"time_unit":"ms"}'
EMPTY_SCHEMA = b' { "time_unit" : "ms" }\n'
SNAPSHOT = 'native-snapshot.xor'
UNINTERRUPTED = 'native-uninterrupted.xor'
RESUMED = 'native-resumed.xor'
TRAFFIC = 'unique-forecast-traffic'
EXCHANGE = 'unique-forecast-exchange'
DUPLICATE = 'iterator-duplicates'
WORK_EXECUTABLE = 'tsbench_gorilla_work_control'
HEADER = struct.Struct('<8sIIQ')


def sha(data):
    return sha256(data).hexdigest()


def columns(pairs):
    return (b''.join(struct.pack('<q', t) for t, _ in pairs), b''.join(struct.pack('<Q', v) for _, v in pairs))


def oracle(pairs):
    t, v = columns(pairs)
    return {'rows': len(pairs), 'milliseconds_sha256': sha(t), 'value_sha256': sha(v)}


def max_payload(n):
    return 2 + ((144 if n else 0) + (157 if n > 1 else 0) + max(0, n - 2) * 145 + 7) // 8


def plan_gorilla(root):
    cfg = load_json(local_file(root, CONFIG))
    require(cfg.keys() == {'schema', 'method', 'corpus', 'corpus_id', 'time_conversion', 'validator', 'windows'} and
            cfg['schema'] == 'bmk.dev-gorilla-tv-cases/1' and cfg['time_conversion'] == 'civil_i64_s_to_i64_ms_exact_x1000' and
            cfg['validator'] == 'native_xor_payload_and_independent_tv_bits_v1' and
            cfg['method'] == {'plugin': PLUGIN, 'selection': 7, 'role': 'timestamp_value', 'options': {}, 'max_chunk_rows': LIMIT},
            'unexpected Gorilla case config')
    points = [(-2**63, 0x8000000000000000), (2**63-1, 0x7ff800000000004a), (-1000, 0x7ff0000000000000),
              (-1000, 1), (0, 0xfff0000000000000), (1800, 0x7ff80000000000fe), (1801, 0)]
    pairs = {'empty': [], 'single-negative': points[:1], 'time-wrap-and-float-bits': points,
             DUPLICATE: [(-9, 0), (-1, 0x8000000000000000), (-1, 0x7ff80000000000fe), (3, 1), (20, 2)]}
    lineage = {}
    require(isinstance(cfg['windows'], list) and [w['dataset'] for w in cfg['windows']] == [TRAFFIC, EXCHANGE] and
            [w['count'] for w in cfg['windows']] == [LIMIT, 13], 'unexpected Gorilla window closure')
    for req in cfg['windows']:
        window = bind_window(root, cfg['corpus'], cfg['corpus_id'], req)
        t, v = read_tv_window(root, window)
        tv = [(stamp * 1000, raw) for (stamp,), (raw,) in zip(struct.iter_unpack('<q', t), struct.iter_unpack('<Q', v), strict=True)]
        require(all(-2**63 <= ms < 2**63 for ms, _ in tv), 'Gorilla time conversion overflows int64')
        pairs[req['dataset']] = tv
        lineage[req['dataset']] = {'window': window, 'original_seconds_sha256': sha(t)}
    traffic = pairs[TRAFFIC]
    require(all(a[0] < b[0] for a, b in zip(traffic, traffic[1:])), 'Gorilla traffic seek oracle needs strictly increasing time')
    fixtures = [{**oracle(values), 'name': name, 'schema': (SCHEMA if values else EMPTY_SCHEMA).decode('ascii'),
                 'frame': name + '.bmk', 'lineage': lineage.get(name, {})} for name, values in pairs.items()]
    index = {row['name']: row for row in fixtures}
    # Each tuple is (public operation, request, expected native status, expected result index).
    scripts = {
        TRAFFIC: [('seek', traffic[50][0] - 1, 0, 50), ('seek', traffic[25][0], 0, 50),
                  ('seek', traffic[-1][0] + 1, 0, None), ('next', None, 0, None)],
        DUPLICATE: [('seek', -20, 0, 0), ('seek', -1, 0, 1), ('next', None, 0, 2),
                    ('seek', -1, 0, 2), ('seek', 2, 0, 3), ('seek', 20, 0, 4),
                    ('seek', 21, 0, None), ('next', None, 0, None)],
    }
    seeks = {name: [[op, query, status, list(pairs[name][pos]) if pos is not None else None]
                    for op, query, status, pos in calls] for name, calls in scripts.items()}
    snapshot = {**oracle(traffic[:PREFIX]), 'frame': SNAPSHOT, 'cut_rows': PREFIX,
                'resume_tail_rows': len(traffic) - PREFIX, 'workspace_bytes': max_payload(LIMIT)}
    work = {'observer': 'elf-call-interposition-v1', 'executable': WORK_EXECUTABLE,
            'resume': [{'name':'prefix','source':SNAPSHOT,'mode':'valid'},
                       {'name':'full','source':TRAFFIC,'mode':'valid'},
                       {'name':'empty','source':'empty','mode':'valid'},
                       {'name':'trailing','source':SNAPSHOT,'mode':'trailing'}],
            'iterator': list(seeks)}
    routes = {
        'tv-batch': {'timestamp_and_delta_edges': ['time-wrap-and-float-bits'], 'f64_bits_empty_and_single': ['empty', 'single-negative', 'time-wrap-and-float-bits'],
                     'native_payload_cross_decode': list(index)},
        'append-resume': {'append_snapshot_tail_resume': [TRAFFIC], 'independent_snapshot_restore': [TRAFFIC],
                          'invalid_snapshot_and_order': [TRAFFIC], 'final_frame_equals_uninterrupted': [TRAFFIC],
                          'source_scan_and_copy_accounting': [TRAFFIC,'empty']},
        'iterator': {'iterator_and_forward_seek_oracle': [TRAFFIC], 'seek_duplicate_and_edges': [DUPLICATE],
                     'scan_work_and_unsupported_backward': [TRAFFIC,DUPLICATE]},
    }
    cases = []
    for route, checks in routes.items():
        for check, names in checks.items():
            criteria = {'fixtures': [index[n] for n in names]}
            if route == 'append-resume':
                criteria.update(snapshot=snapshot, uninterrupted=UNINTERRUPTED, resumed=RESUMED,
                                invalid_statuses={'invalid_span': 1, 'overflow': 6, 'closed_append': 1, 'bad_snapshot': 5})
            if check == 'source_scan_and_copy_accounting':
                criteria['work'] = work['resume']
            if check == 'scan_work_and_unsupported_backward':
                criteria['work'] = {name:seeks[name] for name in names}
            elif route == 'iterator':
                criteria['seeks'] = seeks[names[0]]
            row = {'name': 'gorilla-' + check.replace('_', '-'), 'route': route, 'check': check, 'selection': 7, 'criteria': criteria}
            cases.append({**row, 'case_id': content_id(row)})
    body = {'config_id': content_id(cfg), 'test': TEST, 'evidence_path': f'{DIR}/report.json', 'fixtures': fixtures,
            'snapshot': snapshot, 'seeks': seeks, 'work': work, 'cases': cases,
            'binary': [row['frame'] for row in fixtures] + [SNAPSHOT, UNINTERRUPTED, RESUMED]}
    return {**body, 'bundle_id': content_id(body)}, pairs


def retained_paths(bundle):
    return [f'{DIR}/{name}' for name in bundle['binary']]
