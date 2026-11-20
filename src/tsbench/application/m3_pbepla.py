"""File-session input for the PBEPLA real-corpus routes."""
from contextlib import contextmanager
import struct

from ..assets import require
from ..planner.m3_pbepla import windows
from .m3_sprintz_query import _stage


@contextmanager
def staged_windows(root, entry, progressive, replay, work):
    """Exhaust the locked loader once, then read bounded windows from staged columns.

    Loader source SHA/row checks must complete before any window is visible.
    No active file/column handle escapes the caller's workspace context.
    """
    geometry = windows(entry, progressive, replay)
    paths = _stage(root, entry, work / 'columns')
    sentinel = struct.pack('<d', -9999)
    check_missing = entry['parser']['missing'] == 'retain_source_minus_9999'

    def rows():
        stream = None
        active = None
        try:
            for window in geometry:
                if active != window.column:
                    if stream is not None:
                        stream.close()
                    active = window.column
                    stream = paths[active].open('rb')
                stream.seek(8 * window.start)
                raw = stream.read(8 * window.rows)
                require(len(raw) == 8 * window.rows and (not check_missing or
                        all(raw[i:i+8] != sentinel for i in range(0,len(raw),8))),
                        'PBEPLA staged window is incomplete or includes a retained sentinel')
                yield window, raw
        finally:
            if stream is not None:
                stream.close()

    result = rows()
    try:
        yield result
    finally:
        result.close()


def quality(original, restored):
    """Exact maximum; search all ties at the rounded maximum using rational subtraction."""
    from fractions import Fraction
    from hashlib import sha256
    import sys
    import numpy as np

    require(0 < len(original) == len(restored) and len(original) % 8 == 0, 'PBEPLA detached output extent differs')
    x, y = (np.frombuffer(buf, dtype='<f8') for buf in (original, restored))
    require(np.isfinite(x).all() and np.isfinite(y).all(), 'PBEPLA quality needs finite original and restored values')
    with np.errstate(over='ignore', under='ignore'):
        error = np.abs(x-y)
    rounded = error.max()
    # Monotonic round-to-nearest means no value outside the set can have a
    # larger exact error. A rounded 0 is exact for the difference of two f64s.
    if rounded == 0:
        maximum = Fraction(0)
    else:
        maxima = np.flatnonzero(error == rounded)
        # Repeated plateaus do not need evaluating the same pair many times.
        pairs = set(zip(x[maxima].tolist(), y[maxima].tolist(), strict=True))
        maximum = max(abs(Fraction(a)-Fraction(b)) for a,b in pairs)
    return maximum, {'max_abs_error': float(maximum) if maximum <= sys.float_info.max else None,
                     'exact_max_abs_error': str(maximum), 'restored_sha256': sha256(restored).hexdigest()}


GROUP = 32


def _call(control, folder, operation, indexes, *parameters):
    import subprocess
    from ..assets import parse_json
    proc = subprocess.run([str(control), operation, *map(str,parameters), *map(str,indexes)], cwd=folder,
                          env={'LC_ALL': 'C'}, capture_output=True, text=True, timeout=120)
    require(proc.returncode == 0 and not proc.stderr, f'PBEPLA {operation}: {proc.stderr.strip() or proc.returncode}')
    rows = [parse_json(line, 'PBEPLA native observation') for line in proc.stdout.splitlines()]
    require([r['index'] for r in rows] == indexes and all(r['status'] in {'failed','encoded','restored'} for r in rows),
            'PBEPLA bounded group omitted or reordered a product')
    return rows


def _quality_layers(raw, frames, originals, info, replay):
    from fractions import Fraction
    from hashlib import sha256
    from ..planner.m3_pbepla import LAYOUT
    from ..planner.pbepla_progressive import schema_bytes
    from ..qualification.pbepla_progressive import OUTER, MAGIC, _parse_frame

    n = len(raw)//8
    schema = schema_bytes('m3-pbepla-native')
    spec = {'name': 'm3-pbepla-native', 'schema_sha256': sha256(schema).hexdigest(), 'count': n,
            'expected_flags': 1, 'requested_eps': LAYOUT['requested_eps'], 'expected_delay': LAYOUT['max_delay'],
            'geometry': None}
    parsed, assessed = [], []
    for k,(wire, recovered) in enumerate(zip(frames, originals, strict=True),1):
        # The validator's outer envelope is only a local parse view. The
        # actual recovery product is PBEP; fabricated outer bytes are not billed.
        parsed.append(_parse_frame(OUTER.pack(MAGIC,10,n,len(schema),len(wire))+schema+wire,spec,k))
        fields, _, _, body = parsed[-1]
        error, q = quality(raw,recovered)
        effective = fields['eps'][k-1]
        assessed.append({'layer': k, 'requested_eps': LAYOUT['requested_eps'][k-1], 'effective_eps': effective,
                         **q, 'quality_passed': error <= Fraction(effective), 'frame_sha256': sha256(wire).hexdigest(),
                         'bytes': len(wire), 'header_bytes': fields['header_bytes'], 'payload_bytes': len(body),
                         'layer_payload_bytes': fields['layer_bytes'][-1]})
    full, grid, native, body = parsed[-1]
    require(all(geometry == grid and fields['eps'] == full['eps'] and fields['resolutions'] == full['resolutions'] and
                fields['bits'] == full['bits'][:fields['stored']] and payload == body[:len(payload)]
                for fields, geometry, _, payload in parsed) and info['rows'] == n and info['native_full_bytes'] == len(native),
            'PBEPLA independently restored parts do not form the declared prefix sequence')
    io = info['replay']
    if replay:
        retries = io['native_numerical_retries']; payload = len(body)
        require(type(retries) is int and retries >= 0, 'PBEPLA native retries not observed')
        passes = 3+retries
        expected = {'result': 0, 'rewind_calls': passes, 'eof_passes': passes, 'native_passes': passes,
                    'first_sink_after_pass': passes, 'source_bytes_read': 8*n*passes,
                    'native_value_count': n, 'native_buffer_slots': 3*(full['delay']+2),
                    'sink_bytes': len(native), 'temp_bytes_read': 3*payload, 'temp_seeks': 9,
                    'temp_files_created': 3*(1+retries), 'temp_files_closed': 3*(1+retries), 'same_bytes_as_batch': True}
        require(all(io[key] == value for key,value in expected.items()) and io['first_sink_ns'] > 0 and io['sink_calls'] >= 1 and
                io['temp_bytes_written'] >= io['temp_peak_live_bytes'] >= payload and
                (retries or io['temp_bytes_written'] == io['temp_peak_live_bytes'] == payload),
                'PBEPLA actual source and logical temp traffic differs from the native pass contract')
    else:
        require(io is None, 'PBEPLA batch route reported replay activity')
    return {'layers': assessed, 'quality_passed': all(p['quality_passed'] for p in assessed),
            'full_frame_bytes': len(native), 'full_frame_sha256': assessed[-1]['frame_sha256'], 'replay': io}


def run_group(control, work, sources, replay):
    """For each layer, reopen a detached prefix-only directory in a new process."""
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from ..assets import ContractError
    from ..planner.m3_pbepla import LAYOUT

    indexes = list(range(len(sources)))
    require(0 < len(sources) <= GROUP, 'invalid PBEPLA group size')
    layers = range(1,len(LAYOUT['requested_eps'])+1)
    with TemporaryDirectory(prefix='pbepla-encode-', dir=work) as tmp:
        base = Path(tmp)
        (base/'input').mkdir(); (base/'out').mkdir()
        for i,raw in zip(indexes,sources,strict=True):
            (base/'input'/str(i)).write_bytes(raw)
        observations = _call(control, base, 'replay' if replay else 'progressive', indexes)
        frames = {}
        for row in observations:
            if row['status'] == 'encoded':
                i = row['index']; frames[i] = []
                for k in layers:
                    path = base/'out'/f'{i}-{k}'
                    require(0 < path.stat().st_size <= LAYOUT['max_prefix_frame_bytes'], 'PBEPLA native prefix exceeds declared file bound')
                    frames[i].append(path.read_bytes())
    recovered = {i: [] for i in frames}
    rejected = {}
    if frames:
        for k in layers:
            with TemporaryDirectory(prefix=f'pbepla-restore-L{k}-', dir=work) as tmp:
                base = Path(tmp)
                (base/'input').mkdir(); (base/'out').mkdir()
                for i,prefix in frames.items():
                    (base/'input'/f'{i}-{k}').write_bytes(prefix[k-1])
                records = _call(control, base, 'restore-callback' if replay else 'restore-batch', list(frames), k)
                for record in records:
                    i = record['index']
                    if record['status'] == 'failed':
                        rejected[i] = record['reason']
                    else:
                        require(record['status'] == 'restored' and record['layer'] == k, 'PBEPLA detached layer mismatch')
                        path = base/'out'/f'{i}-{k}'
                        require(path.stat().st_size == len(sources[i]), 'PBEPLA detached product shape differs')
                        recovered[i].append(path.read_bytes())
    for row in observations:
        i = row['index']
        if row['status'] == 'failed' or i in rejected:
            yield {'status': 'failed', 'reason': row.get('reason', rejected.get(i))}, frames.get(i)
            continue
        try:
            proof = _quality_layers(sources[i], frames[i], recovered[i], row, replay)
        except ContractError as exc:
            yield {'status': 'failed', 'reason': str(exc)}, frames[i]
        else:
            yield {'status': 'verified' if proof['quality_passed'] else 'quality_rejected', **proof}, frames[i]


def run_corpus(root, plan, item, partner, entry, work, run):
    from hashlib import sha256
    from itertools import islice
    from pathlib import Path
    import subprocess
    from ..assets import ContractError, local_file
    from ..planner.m3_pbepla import DRIVER, PROGRESSIVE, REPLAY

    control = local_file(root, plan['build']['pbepla_corpus']['executable']['path'])
    replay = item['route'] == REPLAY
    progressive, replay_item = (partner,item) if replay else (item,partner)
    require(progressive['route'] == PROGRESSIVE and replay_item['route'] == REPLAY, 'PBEPLA file partner differs')
    units, retained = [], {}
    with staged_windows(root, entry, progressive, replay_item, work) as source:
        while group := list(islice(source,GROUP)):
            raw = [data for _,data in group]
            next_group = run_group(control,work,raw,replay)
            try:
                results = list(next_group)
            except (ContractError,OSError,subprocess.TimeoutExpired) as exc:
                results = [({'status':'failed','reason':str(exc)},None)]*len(group)
            for (window, original),(proof,frames) in zip(group,results,strict=True):
                scope = {'column':window.column,'row_range':[window.start,window.end], 'window_ordinal':window.ordinal,
                         'logical_input_bytes':len(original),'input_sha256':sha256(original).hexdigest()}
                units.append({**scope,**proof})
                status = proof['status']
                if frames and status not in retained:
                    rel = Path('retained')/item['work_item_id']/status
                    (run/rel).mkdir(parents=True,exist_ok=False)
                    parts = []
                    for k,wire in enumerate(frames,1):
                        part = rel/f'L{k}.pbep'; (run/part).write_bytes(wire)
                        parts.append({'path': part.as_posix(), 'bytes': len(wire), 'sha256': sha256(wire).hexdigest()})
                    retained[status] = {**scope,'parts':parts}
    counts = item['input']['size_estimate']
    logical = sum(row['logical_input_bytes'] for row in units)
    require((len(units),logical) == (counts['input_units'],counts['native_input_bytes_one_pass']),
            'PBEPLA corpus operation accounting does not close')
    return {'driver': DRIVER, 'units': units, 'input_bytes_one_pass': logical,
            'framing': 'native_pbep_rank1_f64_implicit_axis', 'retained_samples': retained,
            'failed_units': sum(u['status']=='failed' for u in units),
            'quality_rejected_units': sum(u['status']=='quality_rejected' for u in units),
            'full_frame_bytes': sum(u.get('full_frame_bytes',0) for u in units),
            'verify_each_detached_prefix': True, 'timing_admitted': False,
            'replay_scope': 'finite_rewindable_source_callbacks_and_logical_temp_stdio_not_physical_io' if replay else None}
