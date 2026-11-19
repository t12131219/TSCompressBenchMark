"""Independently parse bounded Gorilla XOR chunks and check the sealed test transcript."""
from ..assets import content_id, load_json, local_file, require
from ..planner.gorilla import (DIR, HEADER, PLUGIN, RESUMED, SNAPSHOT, TRAFFIC, UNINTERRUPTED,
                              max_payload, oracle, retained_paths, sha)
from .probe_build import verify_probe_build_lock

_MASK = (1 << 64) - 1


def decode_chunk(payload, rows, *, projection=None):
    """Offline bit reader with optional role-token projection of a native TV chunk."""
    require(type(rows) is int and 0 <= rows <= 512 and 2 <= len(payload) <= max_payload(rows) and
            int.from_bytes(payload[:2], 'big') == rows, 'Gorilla chunk count or bound differs')
    stream = int.from_bytes(payload[2:], 'big')
    remaining = (len(payload) - 2) * 8

    def read(bits):
        nonlocal remaining
        require(0 <= bits <= remaining, 'truncated Gorilla token')
        remaining -= bits
        return (stream >> remaining) & ((1 << bits) - 1)

    def varint():
        value = 0
        for i in range(10):
            byte = read(8)
            require(i < 9 or byte < 2, 'overflowing Gorilla varint')
            value |= (byte & 127) << (7 * i)
            if byte < 128:
                return value
        raise AssertionError('unreachable varint')

    pairs = []
    delta = 0
    window = None
    role_words = {'timestamp': (0, 0), 'value': (0, 0)}

    def collect(role, start):
        word, count = role_words[role]
        width = start - remaining
        role_words[role] = ((word << width) | ((stream >> remaining) & ((1 << width) - 1)), count + width)

    for i in range(rows):
        token_start = remaining
        if i == 0:
            zig = varint()
            stamp = (zig >> 1) ^ -(zig & 1)
        else:
            if i == 1:
                delta = varint()
            else:
                prefix = 0
                while prefix < 4 and read(1):
                    prefix += 1
                if prefix:
                    width = (14, 17, 20, 64)[prefix - 1]
                    dod = read(width)
                    # First three Gorilla ranges are asymmetric (-2^(w-1), 2^(w-1)].
                    delta += dod - (1 << width) if width < 64 and dod > (1 << (width - 1)) else dod
            stamp = (stamp + delta) & _MASK
            stamp -= (stamp >> 63) << 64
        if projection is not None:
            collect('timestamp', token_start)
        token_start = remaining
        if i == 0:
            value = read(64)
        elif read(1):
            if read(1):
                left, count = read(5), read(6) or 64
                require(left + count <= 64, 'invalid Gorilla value window')
                window = (count, 64 - left - count)
            require(window is not None, 'Gorilla window reused before definition')
            change = read(window[0])
            require(change != 0, 'unexpected zero Gorilla XOR')
            value ^= change << window[1]
        if projection is not None:
            collect('value', token_start)
        pairs.append((stamp, value))
    bits = len(payload) * 8 - remaining
    require(remaining < 8 and read(remaining) == 0, 'Gorilla trailer or padding is not canonical')
    if projection is not None:
        for role, (word, count) in role_words.items():
            padding = -count % 8
            projection[role] = (payload[:2] + (word << padding).to_bytes((count + padding) // 8, 'big'), count)
    return pairs, bits


def _exact(actual, expected, message):
    from ..assets import canonical_bytes
    require(canonical_bytes(actual) == canonical_bytes(expected), message)


def _read_frame(out, name, cap):
    file = local_file(out, f'{DIR}/{name}')
    require(2 <= file.stat().st_size <= cap, 'Gorilla retained frame exceeds bound')
    return file.read_bytes()


def frame_ref(name, wire):
    return {'path': name, 'bytes': len(wire), 'sha256': sha(wire)}


def _work_counts(calls, rows, copies=0, copied=0):
    return {'next_calls': calls, 'rows_scanned': rows, 'source_copy_calls': copies, 'source_bytes_copied': copied}


def resume_work(payload, bad):
    rows = int.from_bytes(payload[:2], 'big')
    decode_chunk(payload, rows)
    copied = bool(rows) and not bad
    n = len(payload) + int(bad)
    return {'status':5 if bad else 0,'source_bytes':n,'same_snapshot_after_source_overwrite':not bad,
            **_work_counts(rows+1,rows,int(copied),n if copied else 0)}


def iterator_work(payload, script):
    pairs, _ = decode_chunk(payload, int.from_bytes(payload[:2], 'big'))
    pos, steps = -1, []
    for op, query, status, pair in script:
        calls = scanned = 0
        # A cached hit (including a request behind the cursor) never
        # enters next. A terminal call consumes no row and is distinct.
        while op == 'next' or pos < 0 or pairs[pos][0] < query:
            calls += 1
            if pos+1 == len(pairs):
                break
            scanned += 1
            pos += 1
            if op == 'next':
                break
        observed = None if calls > scanned else list(pairs[pos])
        _exact([status,pair], [0,observed], 'Gorilla iterator work script differs from retained frame')
        steps.append({'status': 0, 'pair': observed, **_work_counts(calls,scanned)})
    return steps


def _verify_work(policy, transcript, diagnostic, native, snap, scripts):
    expected_resume = {}
    for row in policy['resume']:
        payload = snap if row['source'] == SNAPSHOT else native[row['source']]
        expected_resume[row['name']] = {'source_sha256':sha(payload),
                                       'observed':resume_work(payload,row['mode']=='trailing')}
    expected_iterator = {name:{'source_sha256':sha(native[name]),'observed':iterator_work(native[name],scripts[name])}
                         for name in policy['iterator']}
    _exact(transcript, {'observer': policy['observer'], 'executable_sha256': diagnostic,
                       'resume': expected_resume, 'iterator': expected_iterator},
           'Gorilla scan/copy or forward-only work differs')


def verify_gorilla(bundle, build, driver_sha256, out, *, sealed_paths=None):
    require(bundle['bundle_id'] == content_id({k: v for k, v in bundle.items() if k != 'bundle_id'}),
            'Gorilla bundle identity differs')
    paths = set(retained_paths(bundle))
    require(sealed_paths is None or (bundle['evidence_path'] in sealed_paths and
            {p for p in sealed_paths if p.startswith(DIR + '/') and p != bundle['evidence_path']} == paths),
            'Gorilla sealed output closure differs')
    doc = load_json(local_file(out, bundle['evidence_path']))
    work = bundle.get('work')
    require(isinstance(doc, dict) and doc.keys() == {'schema','config_id','definitions','build','bundle_id','case_ids',
                'formal_performance','formal_qualification','rejected_inputs','cases','direct_native_mechanisms'} and
            doc['schema'] == ('bmk.m0-gorilla-control/3' if work else 'bmk.m0-gorilla-control/2') and
            doc['definitions'] == driver_sha256 and
            doc['config_id'] == bundle['config_id'] and doc['bundle_id'] == bundle['bundle_id'] and
            doc['case_ids'] == [c['case_id'] for c in bundle['cases']] and
            doc['formal_performance'] is False and doc['formal_qualification'] is False, 'Gorilla report binding differs')
    build = dict(build)
    if work:
        diagnostic = build.pop(work['executable'], None)
        require(isinstance(diagnostic,str) and len(diagnostic) == 64, 'Gorilla work executable binding missing')
    verify_probe_build_lock(doc['build'], build, PLUGIN, dependency_count=1)
    _exact(doc['rejected_inputs'], [7, 2, 1, 1], 'Gorilla ABI input rejection statuses differ')
    obs = doc['cases']
    require(isinstance(obs, list) and len(obs) == len(bundle['fixtures']), 'Gorilla case denominator differs')
    native = {}
    for case, row in zip(bundle['fixtures'], obs, strict=True):
        name, n = case['name'], case['rows']
        schema = case['schema'].encode('ascii')
        fixed_size = HEADER.size + len(schema)
        wire = _read_frame(out, case['frame'], fixed_size + max_payload(n))
        require(len(wire) >= fixed_size + 2 and HEADER.unpack_from(wire) ==
                (b'BMKGTV\x01\0', len(schema), n, len(wire) - fixed_size) and wire[HEADER.size:fixed_size] == schema,
                'Gorilla TV envelope differs')
        payload = native[name] = wire[fixed_size:]
        expected = {k: case[k] for k in ('rows', 'milliseconds_sha256', 'value_sha256')}
        _exact(oracle(decode_chunk(payload, n)[0]), expected, 'Gorilla independent chunk decode differs')
        _exact(row, {'case': name, **expected, **case['lineage'], 'logical_tv_bytes': n * 16,
                     'full_frame_bytes': len(wire), 'full_frame_sha256': sha(wire), 'native_bytes': len(payload), 'native_sha256': sha(payload),
                     'independent_tv_verified': True, 'rejected_frames': 4}, 'Gorilla worker restoration identity differs')
    m = doc['direct_native_mechanisms']
    require(isinstance(m, dict) and m.keys() == {'files','prefix_before','no_progress_after_overflow','resumed_prefix',
                'invalid_statuses','finish_again_sha256','reset_snapshot_hex','snapshot_child','iterators'} | ({'work'} if work else set()),
            'Gorilla native mechanism evidence is incomplete')
    prefix = bundle['snapshot']
    snap = _read_frame(out, SNAPSHOT, max_payload(prefix['rows']))
    start, bits = decode_chunk(snap, prefix['rows'])
    expected_start = {k: prefix[k] for k in ('rows', 'milliseconds_sha256', 'value_sha256')}
    _exact(oracle(start), expected_start, 'Gorilla retained snapshot original domain differs')
    _exact(m['snapshot_child'], expected_start, 'Gorilla fresh-process snapshot decode differs')
    progress = {'rows': prefix['rows'], 'chunk_bits': bits, 'workspace_bytes': prefix['workspace_bytes']}
    for name in ('prefix_before', 'no_progress_after_overflow', 'resumed_prefix'):
        _exact(m[name], progress, 'Gorilla prefix bit/row/workspace accounting differs')
    uninterrupted = _read_frame(out, UNINTERRUPTED, max_payload(512))
    resumed = _read_frame(out, RESUMED, max_payload(512))
    require(resumed == uninterrupted == native[TRAFFIC] and m['finish_again_sha256'] == sha(uninterrupted) and
            m['reset_snapshot_hex'] == '0000', 'Gorilla append/finish/resume does not reproduce untouched batch')
    _exact(m['files'], [frame_ref(k, v) for k, v in ((SNAPSHOT, snap), (UNINTERRUPTED, uninterrupted), (RESUMED, resumed))],
           'Gorilla native artifact references differ')
    reject = next(c['criteria']['invalid_statuses'] for c in bundle['cases'] if c['check'] == 'invalid_snapshot_and_order')
    _exact(m['invalid_statuses'], reject, 'Gorilla native rejection or order differs')
    expected_iter = {}
    for name, seeks in bundle['seeks'].items():
        expected_iter[name] = {'drained': oracle(decode_chunk(native[name], int.from_bytes(native[name][:2], 'big'))[0]),
                               'eof': [0, None], 'seeks': seeks, 'bad_trailer': [[5, None], [5, None]]}
    _exact(m['iterators'], expected_iter, 'Gorilla iterator, forward seek or EOF differs')
    if work:
        _verify_work(work, m['work'], diagnostic, native, snap, bundle['seeks'])
