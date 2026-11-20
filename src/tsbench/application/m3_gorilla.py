"""Corpus Gorilla C11 TV, snapshot/resume and forward iterator drivers."""
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
import struct
import subprocess
import time

import numpy as np

from ..assets import digest, local_file, require
from ..corpus_ingress import read_batches
from ..qualification.gorilla import decode_chunk

ROWS = 512
MAGIC = b'GTV1\1\0\0\0'
HEADER = struct.Struct('<8sIQ')
LENGTH = struct.Struct('<I')
PAIR = struct.Struct('<qQ')
RECORD = np.dtype([('t', '<i8'), ('v', '<u8')])
MIN_SECONDS, MAX_SECONDS = -(2**63 // 1000), (2**63 - 1) // 1000


def invoke(control, cwd, *args):
    env = {k: v for k, v in os.environ.items() if k not in {'LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT'}}
    start = time.monotonic_ns()
    p = subprocess.run([str(control), *map(str, args)], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    elapsed = time.monotonic_ns() - start
    require(p.returncode == 0, f'Gorilla {args[:2]} failed ({p.returncode}): {p.stderr.strip()}')
    return json.loads(p.stdout), elapsed


def milliseconds(axis: np.ndarray) -> np.ndarray:
    require(axis.dtype == np.dtype('<i8') and np.all((axis >= MIN_SECONDS) & (axis <= MAX_SECONDS)),
            'Gorilla seconds-to-ms exceeds i64')
    out = axis * np.int64(1000)
    require(np.array_equal(out // 1000, axis), 'Gorilla seconds-to-ms is not reversible')
    return out


def stage(root, entry, folder):
    axis_meta = entry['axis']
    require(axis_meta['unit'] == 'second' and axis_meta['interpretation'] == 'source_civil_label_coordinate_not_utc',
            'Gorilla requires an explicit civil-second coordinate')
    cols = entry['value_count']
    folder.mkdir()
    paths = [folder / f'column-{i:04d}.bin' for i in range(cols)]
    axis = folder / 'axis.ms'
    seconds_digest, values_digest = sha256(), sha256()
    rows, last = 0, None
    with ExitStack() as stack:
        t = stack.enter_context(axis.open('wb'))
        v = [stack.enter_context(path.open('wb')) for path in paths]
        for batch in read_batches(root, entry):
            s = np.frombuffer(batch.axis, dtype='<i8')
            require(batch.start == rows and len(s) == batch.rows and
                    (last is None or s[0] >= last) and np.all(s[1:] >= s[:-1]), 'Gorilla requires source-order nondecreasing T')
            seconds_digest.update(batch.axis)
            values_digest.update(batch.values)
            t.write(milliseconds(s).astype('<i8', copy=False).tobytes())
            # Preserve binary64 bit patterns in V, without arithmetic or NaN canonicalization.
            data = np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, cols)
            for i, out in enumerate(v):
                out.write(data[:, i].tobytes())
            rows += batch.rows
            last = s[-1]
    require(rows == entry['rows'], 'Gorilla ingested extent differs')
    return axis, paths, {'canonical_seconds_sha256': seconds_digest.hexdigest(),
                         'canonical_value_rows_sha256': values_digest.hexdigest(), 'native_ms_sha256': digest(axis)}


def _head(f, cols, rows):
    require(f.read(HEADER.size) == HEADER.pack(MAGIC, cols, rows), 'Gorilla corpus envelope differs')


def read_frame(f, n):
    prefix = f.read(LENGTH.size)
    require(len(prefix) == LENGTH.size, 'missing Gorilla frame length')
    size = LENGTH.unpack(prefix)[0]
    require(2 <= size <= 16384, 'Gorilla frame length outside bound')
    wire = f.read(size)
    require(len(wire) == size and int.from_bytes(wire[:2], 'big') == n, 'Gorilla chunk count or extent differs')
    return wire


def restore_independent(wire, n):
    pairs, _ = decode_chunk(wire, n)
    return b''.join(PAIR.pack(*p) for p in pairs)


def _duration(*values):
    require(all(type(x) is int and x > 0 for x in values), 'Gorilla native operation observation missing')


def observe(mode, col, start, n, wire, original, recovered, enc, dec, snapshot=None):
    facts = [col, start, n, len(wire)]
    require(enc[:4] == dec[:4] == facts and recovered == original.tobytes(), 'Gorilla per-unit geometry or recovery differs')
    unit = {'column': col, 'row_range': [start, start + n], 'native_frame_bytes': len(wire),
            'frame_sha256': sha256(wire).hexdigest(), 'restored_tv_sha256': sha256(recovered).hexdigest()}
    if mode == 'append-resume':
        snap, snap_record, saved = snapshot
        cut, size, bits, space, *elapsed = enc[4:]
        require(cut == n // 2 and size == len(snap) and snap_record[:4] == [col, start, cut, size] and
                saved == recovered[:cut * PAIR.size] and space > 0 and bits >= 16 and size == (bits + 7) // 8,
                'Gorilla snapshot progress, extent or recovery differs')
        _duration(*elapsed, *dec[4:], *snap_record[4:])
        require(len(elapsed) == 5 and len(dec) == len(snap_record) == 5, 'Gorilla native state observations incomplete')
        unit.update(snapshot={'rows': cut, 'native_bytes': size, 'resume_input_bytes': size, 'compressed_data_bits': bits - 16,
                              'bounded_workspace_bytes': space, 'sha256': sha256(snap).hexdigest(),
                              'restored_tv_sha256': sha256(saved).hexdigest()},
                    native_wall_ns=dict(zip(('prefix_append', 'snapshot', 'resume', 'tail_append', 'finish', 'full_decode', 'snapshot_decode'),
                                             [*elapsed, dec[4], snap_record[4]], strict=True)),
                    batch_byte_parity_verified=True)
    elif mode == 'iterator':
        open_ns, drain_ns, seek_ns, target, stamp, bits = dec[4:]
        _duration(enc[4], open_ns, drain_ns, seek_ns)
        ts = original['t']
        index = int(ts.searchsorted(target, 'left'))
        require(target == ts[n // 2] and stamp == ts[index] and bits == int(original['v'][index]),
                'Gorilla forward seek differs from original lower bound')
        unit.update(forward_seek={'target_ms': target, 'first_at_or_after_index_within_chunk': index,
                                  'timestamp_ms': stamp, 'value_bits': bits},
                    native_wall_ns={'encode': enc[4], 'iterator_open': open_ns, 'iterator_drain_and_eof': drain_ns,
                                    'fresh_forward_seek': seek_ns})
    else:
        _duration(enc[4], dec[4])
        unit['native_wall_ns'] = {'encode': enc[4], 'decode': dec[4]}
    return unit


def run_gorilla(root: Path, plan: dict, item: dict, entry: dict, work: Path, run: Path) -> dict:
    control = local_file(root, plan['build']['gorilla_corpus']['executable']['path'])
    mode, extent = item['route'], item['input']
    cols, rows = entry['value_count'], entry['rows']
    require(extent['value_column_range'] == [0, cols] and len(extent['row_ranges']) == 1 and
            (extent['row_ranges'][0]['start'], extent['row_ranges'][0]['end']) == (0, rows) and
            extent['slice_extent']['max_per_unit'] == ROWS and extent['full_extent_of_file_rows_and_value_columns'] and
            extent['covers_time_axis'] and extent['planned_transforms'] == ['checked_i64_seconds_to_ms_keep_civil_coordinate'],
            'Gorilla TV extent differs from planned full corpus')
    axis, paths, identities = stage(root, entry, work / 'values')
    ts = np.fromfile(axis, dtype='<i8')
    require(len(ts) == rows, 'Gorilla axis extent differs')
    detached = work / 'detached'
    detached.mkdir()
    archive_path = detached / 'dataset.gtv1'
    state = mode == 'append-resume'
    snap_path = detached / 'snapshot.gtv1'
    (detached / 'restored').mkdir()
    encoded, enc_ns = invoke(control, work, 'encode', mode, 'values', cols, rows, archive_path, snap_path if state else '-')
    decoded, dec_ns = invoke(control, detached, 'decode', mode, archive_path.name, 'restored')
    records = [encoded, decoded]
    times = {'encode': enc_ns, 'detached_restore': dec_ns}
    if state:
        (detached / 'prefix').mkdir()
        prefixes, times['detached_snapshot_restore'] = invoke(control, detached, 'decode', 'snapshots', snap_path.name, 'prefix')
        records.append(prefixes)
    expected = cols * ((rows + ROWS - 1) // ROWS)
    require(all(r['cols'] == cols and r['rows'] == rows and len(r['units']) == expected for r in records),
            'Gorilla process did not cover all units')
    observations, samples = [], {}
    with ExitStack() as stack:
        archive = stack.enter_context(archive_path.open('rb'))
        snapshots = stack.enter_context(snap_path.open('rb')) if state else None
        _head(archive, cols, rows)
        if snapshots is not None:
            _head(snapshots, cols, rows)
        for column, path in enumerate(paths):
            with ExitStack() as files:
                original = files.enter_context(path.open('rb'))
                recovery = files.enter_context((detached / 'restored' / path.with_suffix('.tv').name).open('rb'))
                prefix = files.enter_context((detached / 'prefix' / path.with_suffix('.tv').name).open('rb')) if state else None
                for start in range(0, rows, ROWS):
                    n = min(rows - start, ROWS)
                    content = np.empty(n, dtype=RECORD)
                    content['t'] = ts[start:start + n]
                    values = original.read(8 * n)
                    require(len(values) == 8 * n, 'Gorilla staged V is short')
                    content['v'] = np.frombuffer(values, dtype='<u8')
                    wire, raw = read_frame(archive, n), recovery.read(n * PAIR.size)
                    i = len(observations)
                    snap = None
                    if state:
                        cut = n // 2
                        snap = (read_frame(snapshots, cut), prefixes['units'][i], prefix.read(cut * PAIR.size))
                    seen = observe(mode, column, start, n, wire, content, raw, encoded['units'][i], decoded['units'][i], snap)
                    observations.append(seen)
                    if i == 0:
                        require(restore_independent(wire, n) == raw, 'independent Gorilla retained TV recovery differs')
                        samples['frame'] = (wire, n, seen['restored_tv_sha256'])
                        if snap is not None:
                            require(restore_independent(snap[0], cut) == snap[2], 'independent Gorilla snapshot recovery differs')
                            samples['snapshot'] = (snap[0], cut, seen['snapshot']['restored_tv_sha256'])
                require(not original.read(1) and not recovery.read(1) and (prefix is None or not prefix.read(1)),
                        'Gorilla TV recovery contains trailing data')
        require(not archive.read(1) and (snapshots is None or not snapshots.read(1)), 'Gorilla archive contains trailing data')
    logical = rows * cols * PAIR.size
    native = sum(u['native_frame_bytes'] for u in observations)
    framing = HEADER.size + expected * LENGTH.size
    require(len(observations) == expected == extent['size_estimate']['input_units'] and
            logical == extent['size_estimate']['native_input_bytes_one_pass'] and
            native + framing == archive_path.stat().st_size, 'Gorilla corpus ledger does not close')
    snapshot_bytes = sum(u['snapshot']['native_bytes'] for u in observations) if state else 0
    if state:
        require(snapshot_bytes + framing == snap_path.stat().st_size, 'Gorilla snapshot bytes do not close')
    folder = Path('retained') / item['work_item_id']
    (run / folder).mkdir(parents=True)
    retained = {}
    for name, (wire, n, restored) in samples.items():
        relative = folder / f'{name}.xor'
        (run / relative).write_bytes(wire)
        retained[name] = {'path': relative.as_posix(), 'bytes': len(wire), 'sha256': sha256(wire).hexdigest(),
                          'rows': n, 'restored_tv_sha256': restored}
    return {'driver': 'gorilla-corpus-control/1', 'backend': 'gorilla_c', 'columns': cols, 'rows': rows,
            'input_bytes': logical, 'unique_logical_axis_bytes': rows * 8, 'unique_logical_value_bytes': rows * cols * 8,
            'native_frame_bytes': native, 'harness_framing_bytes': framing, 'artifact_bytes': native + framing,
            'snapshot_artifact_bytes': snapshot_bytes + framing if state else None, 'snapshot_native_bytes': snapshot_bytes if state else None,
            'process_wall_ns': times, 'units': observations, 'retained_samples': retained, 'input_identity': identities,
            'axis_coordinate': 'civil_label_ms_not_utc', 'native_threads': 1,
            'clock_scope': 'diagnostic_native_call_wall_excludes_staging_harness_io_and_verification', 'timing_admitted': False}
