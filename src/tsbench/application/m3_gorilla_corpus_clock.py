"""Whole-file Gorilla diagnostics bound to the sealed M3 per-block evidence."""
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import os
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns
from uuid import uuid4

import numpy as np

from ..assets import canonical_bytes, content_id, load_json, local_file, parse_json, require
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import gorilla_corpus_clock as launch, timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from .m3_gorilla import HEADER, LENGTH, PAIR, RECORD, ROWS, _head, observe, read_frame, stage
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-gorilla-corpus-clock-plan/2'
WARMUPS, REPEATS = 1, 3
ROUTES = launch.ROUTES
CLOCKS = {
    'tv-batch': {'encode': ('encode',), 'decode': ('decode',)},
    'append-resume': {'encode': ('prefix_append', 'snapshot', 'resume', 'tail_append', 'finish'),
                      'decode': ('full_decode',), 'snapshot_decode': ('snapshot_decode',)},
    'iterator': {'encode': ('encode',), 'decode': ('iterator_open', 'iterator_drain_and_eof', 'fresh_forward_seek')},
}
POLICY = {
    'warmups': WARMUPS, 'repeats': REPEATS, 'block_rows': ROWS,
    'directions': {route: list(clocks) for route, clocks in CLOCKS.items()},
    'reservation': resource.RESERVATION, 'exclusive_cpu': False,
    'cache': 'natural inherited file cache, not a cold-cache experiment',
    'reference': 'prepare once outside trials, verify every block against r40, then use fixed final and snapshot frames',
    'ingress': 'each encode trial reopens and parses the frozen original; decode only mounts a fixed frame',
    'native_clock': 'sum of existing controller spans; excludes encoder create/destroy, iterator reset, state batch '
                    'parity control, file I/O and untimed iterator correctness probes; inclusive caller-wall spans',
    'child_clock': 'supervised process wall, wait4 CPU and maximum RSS; not codec-exclusive',
    'durable_output_clock': 'from prepared canonical or fixed frame input through native trial, structural checks and fsync',
    'verified_durable_clock': 'encode starts before reading the original; decode starts before mounting the fixed frame; '
                              'each stops after semantic verification and fsync of output and its immediate parent',
    'retention': 'fixed reference frames and native logs retained; trial products released only after verified observation',
    'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False,
}


def _blocks(cols, rows):
    return ((c, start, min(ROWS, rows - start)) for c in range(cols) for start in range(0, rows, ROWS))


def _commit(dig, value):
    dig.update(canonical_bytes(value) + b'\n')


def _without_clocks(unit):
    return {k: v for k, v in unit.items() if k != 'native_wall_ns'}


def _bindings(root, build):
    original = build['gorilla_corpus']
    repair = build['gorilla_state_repair']
    patched = repair['repair_build']
    require(repair['implementation'] == 'gorilla-c11-unique-v1+tsbench-state-repair-v1' and
            patched['base_dependency'] == {k: original['dependency'][k] for k in ('path', 'sha256')} and
            patched['dependency']['sha256'] != original['dependency']['sha256'],
            'Gorilla repair identity does not derive from the frozen original C11 dependency')
    result = {}
    for lane, implementation, exe, dep in (
            ('original', 'gorilla-c11-unique-v1', original['executable'], original['dependency']),
            ('repair', repair['implementation'], patched['programs'][Path(launch.TOOL).name], patched['dependency'])):
        _file(root, exe)
        _file(root, dep)
        tools = {'gorilla': {k: exe[k] for k in ('path', 'sha256')}}
        runtime = plan_recovery(root, {}, (), tools=tools, libraries=[dep])
        require(runtime['tools'] == {'gorilla': launch.TOOL} and
                runtime['files'][launch.LIBRARY]['sha256'] == dep['sha256'], 'Gorilla runtime closure differs')
        result[lane] = {'implementation': implementation, 'executable': exe, 'dependency': dep, 'runtime': runtime}
    return result


def _population(plan, ledger, entries, bindings):
    cases, excluded = [], []
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') is not None or item['selection'] != 7:
            continue
        route = item['route']
        require(route in ROUTES, 'unmapped Gorilla corpus route')
        body = {k: item[k] for k in ('dataset_id', 'route', 'work_item_id', 'operation_config_id', 'canonical_object_id')}
        if item['applicability'] == 'outside_declared_domain':
            require(row['status'] == 'outside_declared_domain' and row.get('evidence') is None,
                    'unexplained Gorilla non-run')
            excluded.append({**body, 'reasons': item['reasons']})
            continue
        require(item['applicability'] == 'input_domain_matches' and row['status'] == 'verified',
                'applicable Gorilla reference did not verify')
        binding = bindings['original' if route == 'tv-batch' else 'repair']
        evidence, entry, scope = row['evidence'], entries[item['dataset_id']], item['input']
        cols, rows = entry['value_count'], entry['rows']
        count = cols * ((rows + ROWS - 1) // ROWS)
        require(all(evidence[k] == binding[k] for k in ('implementation', 'executable', 'dependency')) and
                evidence['backend'] == 'gorilla_c' and evidence['driver'] == 'gorilla-corpus-control/1' and
                evidence['native_threads'] == 1 and evidence['axis_coordinate'] == 'civil_label_ms_not_utc' and
                (evidence['columns'], evidence['rows'], len(evidence['units'])) == (cols, rows, count) and
                0 < rows <= 1000000 and 0 < cols <= 4096 and
                scope['value_column_range'] == [0, cols] and scope['slice_extent']['max_per_unit'] == ROWS and
                scope['row_ranges'] == [{'partition': 'full', 'start': 0, 'end': rows, 'object_id': body['canonical_object_id']}] and
                scope['size_estimate']['input_units'] == count and evidence['input_bytes'] == rows * cols * PAIR.size and
                body['canonical_object_id'] == entry['canonical']['object_id'], 'Gorilla reference extent or implementation differs')
        framing = HEADER.size + count * LENGTH.size
        dig, progress, native, snapshot = sha256(), sha256(), 0, 0
        for (c, start, n), unit in zip(_blocks(cols, rows), evidence['units'], strict=True):
            require((unit['column'], unit['row_range']) == (c, [start, start + n]) and
                    2 <= unit['native_frame_bytes'] <= 16384, 'Gorilla reference block geometry differs')
            native += unit['native_frame_bytes']
            if route == 'append-resume':
                require(unit['snapshot']['rows'] == n // 2 and 2 <= unit['snapshot']['native_bytes'] <= 16384 and
                        unit['batch_byte_parity_verified'] is True, 'Gorilla reference snapshot geometry differs')
                snap = unit['snapshot']
                snapshot += snap['native_bytes']
                _commit(progress, [c, start, n, unit['native_frame_bytes'], snap['rows'], snap['native_bytes'],
                                   snap['compressed_data_bits'] + 16, snap['bounded_workspace_bytes']])
            _commit(dig, _without_clocks(unit))
        state = route == 'append-resume'
        require(evidence['native_frame_bytes'] == native and evidence['harness_framing_bytes'] == framing and
                evidence['artifact_bytes'] == native + framing <= launch.FILE_CEILING and
                evidence['snapshot_native_bytes'] == (snapshot if state else None) and
                evidence['snapshot_artifact_bytes'] == (snapshot + framing if state else None) and
                (not state or snapshot + framing <= launch.FILE_CEILING), 'Gorilla reference file size differs')
        body.update(columns=cols, rows=rows, units=count, input_bytes=evidence['input_bytes'],
                    artifact_bytes=evidence['artifact_bytes'], snapshot_bytes=evidence['snapshot_artifact_bytes'],
                    input_identity=evidence['input_identity'], source_original=entry['file'],
                    state_progress_sha256=progress.hexdigest() if state else None, block_facts_sha256=dig.hexdigest())
        cases.append({**body, 'case_id': content_id(body)})
    keys = {(x['dataset_id'], x['route']) for x in cases + excluded}
    require(len(keys) == 69 and keys == {(d, r) for d, _ in keys for r in ROUTES} and
            Counter(c['route'] for c in cases) == dict.fromkeys(ROUTES, 16) and
            Counter(c['route'] for c in excluded) == dict.fromkeys(ROUTES, 7), 'incomplete Gorilla projection')
    return cases, excluded


def freeze(root, source_plan, source_run, cpu):
    plan = load_json(source_plan)
    ledger, seal = full_run_source(plan, source_run)
    definition = plan['definition']['plan']
    entries = _entry_map(root, load_json(_file(root, definition)))
    bindings = _bindings(root, plan['build'])
    cases, excluded = _population(plan, ledger, entries, bindings)
    code = ('src/tsbench/application/m3_gorilla_corpus_clock.py', 'src/tsbench/application/m3_gorilla.py',
            'src/tsbench/application/m3_sealed_ledger.py', 'src/tsbench/corpus_ingress.py',
            'src/tsbench/supervisor/gorilla_corpus_clock.py', 'src/tsbench/supervisor/process.py',
            'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/recovery.py', 'tools/m3_gorilla_corpus_clock.py')
    body = {'schema': SCHEMA, 'source_plan': _ref(root, source_plan), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'definition': definition, 'bindings': bindings, 'cases': cases, 'excluded': excluded,
            'environment': resource.environment(cpu), 'launchers': launcher_lock(), 'policy': POLICY,
            'code': [_ref(root, local_file(root, name)) for name in code]}
    return {**body, 'plan_content_id': content_id(body)}


def _archive_keys(route):
    return ('frame.gtv1', 'snapshot.gtv1') if route == 'append-resume' else ('frame.gtv1',)


def _archive_sizes(case):
    sizes = {'frame.gtv1': case['artifact_bytes']}
    if case['route'] == 'append-resume':
        sizes['snapshot.gtv1'] = case['snapshot_bytes']
    return sizes


def _metrics(case, direction, record):
    cols, rows, route = case['columns'], case['rows'], case['route']
    names = CLOCKS[route][direction]
    require(set(record) == {'cols', 'rows', 'units'} and (record['cols'], record['rows']) == (cols, rows) and
            len(record['units']) == case['units'], 'Gorilla native log geometry differs')
    start_at, tail = (8, 0) if route == 'append-resume' and direction == 'encode' else (
        (4, 3) if route == 'iterator' and direction == 'decode' else (4, 0))
    sums = dict.fromkeys(names, 0)
    archive_bytes = HEADER.size
    state_progress = sha256() if route == 'append-resume' and direction == 'encode' else None
    for (c, start, n), raw in zip(_blocks(cols, rows), record['units'], strict=True):
        if direction == 'snapshot_decode':
            n //= 2
        require(len(raw) == start_at + len(names) + tail and raw[:3] == [c, start, n] and
                all(type(v) is int for v in raw) and 2 <= raw[3] <= 16384, 'Gorilla native log block differs')
        for name, elapsed in zip(names, raw[start_at:start_at + len(names)], strict=True):
            require(elapsed > 0, 'Gorilla native log has nonpositive span')
            sums[name] += elapsed
        archive_bytes += LENGTH.size + raw[3]
        if state_progress is not None:
            _commit(state_progress, raw[:start_at])
    if state_progress is not None:
        require(state_progress.hexdigest() == case['state_progress_sha256'], 'Gorilla state progress differs from r40')
    wanted = case['snapshot_bytes'] if direction == 'snapshot_decode' else case['artifact_bytes']
    require(archive_bytes == wanted, 'Gorilla native log frame sizes do not close')
    return sums


def _encode_facts(case, out, record):
    """Check emitted frame counts and byte lengths before fsync; hash the files afterward."""
    sizes = _archive_sizes(case)
    require({p.name: p.stat().st_size for p in out.iterdir() if p.is_file()} == sizes and
            len(list(out.iterdir())) == len(sizes), 'Gorilla emitted archive inventory differs')
    with ExitStack() as stack:
        streams = {name: stack.enter_context((out / name).open('rb')) for name in sizes}
        for f in streams.values():
            _head(f, case['columns'], case['rows'])
        for (_, _, n), raw in zip(_blocks(case['columns'], case['rows']), record['units'], strict=True):
            require(len(read_frame(streams['frame.gtv1'], n)) == raw[3], 'Gorilla final frame and log disagree')
            if 'snapshot.gtv1' in streams:
                require(raw[4] == n // 2 and len(read_frame(streams['snapshot.gtv1'], n // 2)) == raw[5],
                        'Gorilla snapshot and log disagree')
        require(all(not f.read(1) for f in streams.values()), 'Gorilla emitted archive has trailing bytes')


def _decoded_sizes(case, direction):
    rows = case['rows']
    if direction == 'snapshot_decode':
        rows = (rows // ROWS) * (ROWS // 2) + (rows % ROWS) // 2
    return {f'column-{c:04d}.tv': rows * PAIR.size for c in range(case['columns'])}


def _verify_products(case, source, archives, enc, dec, snap=None):
    """Recreate the frozen per-block facts and compare every original and recovered TV bit."""
    cols, rows, route = case['columns'], case['rows'], case['route']
    state = route == 'append-resume'
    dec_dir, dec_record = dec
    require(state == (snap is not None), 'Gorilla missing or extra snapshot recovery')
    paths = launch.value_files(cols)
    axis = np.fromfile(source / 'axis.ms', dtype='<i8')
    result = sha256()
    i = 0
    with ExitStack() as archive_stack:
        frame = archive_stack.enter_context((archives / 'frame.gtv1').open('rb'))
        _head(frame, cols, rows)
        snapshots = None
        if state:
            snap_dir, snap_record = snap
            snapshots = archive_stack.enter_context((archives / 'snapshot.gtv1').open('rb'))
            _head(snapshots, cols, rows)
        for c, name in enumerate(paths):
            with ExitStack() as streams:
                original = streams.enter_context((source / name).open('rb'))
                restored = streams.enter_context((dec_dir / Path(name).with_suffix('.tv')).open('rb'))
                prefix = streams.enter_context((snap_dir / Path(name).with_suffix('.tv')).open('rb')) if state else None
                for start in range(0, rows, ROWS):
                    n = min(ROWS, rows - start)
                    content = np.empty(n, dtype=RECORD)
                    content['t'] = axis[start:start + n]
                    raw = original.read(n * 8)
                    require(len(raw) == n * 8, 'Gorilla canonical V ends before the declared extent')
                    content['v'] = np.frombuffer(raw, dtype='<u8')
                    recovered = restored.read(n * PAIR.size)
                    snap_unit = (read_frame(snapshots, n // 2), snap_record['units'][i],
                                 prefix.read((n // 2) * PAIR.size)) if state else None
                    unit = observe(route, c, start, n, read_frame(frame, n), content, recovered,
                                   enc['units'][i], dec_record['units'][i], snap_unit)
                    _commit(result, _without_clocks(unit))
                    i += 1
                require(not original.read(1) and not restored.read(1) and (prefix is None or not prefix.read(1)),
                        'Gorilla per-column product contains trailing bytes')
        require(not frame.read(1) and (snapshots is None or not snapshots.read(1)), 'Gorilla archive has trailing bytes')
    require(i == case['units'] and result.hexdigest() == case['block_facts_sha256'],
            'Gorilla trial block content, recovery or seek differs from r40')
    return result.hexdigest()


def _fsync(path, *, directory=False):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if directory else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _invoke(run, plan, case, source, fixed, scratch, direction):
    route, cols, rows = (case[k] for k in ('route', 'columns', 'rows'))
    lane = 'original' if route == 'tv-batch' else 'repair'
    encode = direction == 'encode'
    names = ('axis.ms', *launch.value_files(cols))
    inputs = {k: source / k for k in names} if encode else {
        'frame.gtv1': fixed / ('snapshot.gtv1' if direction == 'snapshot_decode' else 'frame.gtv1')}
    sizes = _archive_sizes(case) if encode else _decoded_sizes(case, direction)
    # A controller JSON log is also an inherited output FD under RLIMIT_FSIZE.
    cap = max(4096, max(sizes.values()), 320 * case['units'] + 128)
    scratch.mkdir(parents=True)
    wall, cpu = monotonic_ns(), process_time_ns()
    out, proc = launch.run(run / f'runtime-{lane}', plan['bindings'][lane]['runtime'], scratch, inputs,
                           route, direction, cols, rows, cap)
    require(proc['status'] == 'completed', f"Gorilla {direction} {proc['status']}; see {scratch / 'native.stderr'}")
    logs = [_ref(run, scratch / f'native.{name}') for name in ('stdout', 'stderr')]
    require(logs[1]['bytes'] == 0, 'Gorilla native controller produced stderr')
    raw = load_json(scratch / 'native.stdout')
    spans = _metrics(case, direction, raw)
    require({p.name: p.stat().st_size for p in out.iterdir() if p.is_file() and not p.is_symlink()} == sizes and
            len(list(out.iterdir())) == len(sizes), 'Gorilla native output does not cover frozen extent')
    if encode:
        _encode_facts(case, out, raw)
    for name in sizes:
        _fsync(out / name)
    _fsync(out, directory=True)
    _fsync(scratch, directory=True)
    # Semantic verification is a separate boundary; decode does not have its source mounted.
    elapsed = {'durable_output_wall_ns': monotonic_ns() - wall, 'controller_cpu_ns': process_time_ns() - cpu}
    return out, raw, {'direction': direction, 'process': proc, 'logs': logs, 'native_ns': spans, **elapsed}


def _trial_path(case, index):
    return f"cases/{case['case_id']}/trial-{index:02d}"


def _archive_refs(base, case, archive):
    return {name: _ref(base, archive / name) for name in _archive_keys(case['route'])}


def _stash_anchors(run, plan, case, source, case_dir):
    fixed = case_dir / 'fixed'
    with TemporaryDirectory(prefix='reference-', dir=case_dir) as folder:
        out, raw, _ = _invoke(run, plan, case, source, fixed, Path(folder) / 'encode', 'encode')
        control = {}
        for direction in list(CLOCKS[case['route']])[1:]:
            replay, record, _ = _invoke(run, plan, case, source, out, Path(folder) / direction, direction)
            control[direction] = (replay, record)
        _verify_products(case, source, out, raw, control['decode'], control.get('snapshot_decode'))
        out.rename(fixed)
        _fsync(case_dir, directory=True)
    return fixed, _archive_refs(run, case, fixed)


def _facts(ref):
    return {k: ref[k] for k in ('bytes', 'sha256')}


def _descriptor_refs(run, case, setup):
    prefix = f"cases/{case['case_id']}/fixed/"
    anchors = setup['fixed']
    require(set(anchors) == set(_archive_sizes(case)), 'Gorilla fixed archive inventory differs')
    for name, n in _archive_sizes(case).items():
        ref = anchors[name]
        require(ref['path'] == prefix + name and ref['bytes'] == n, 'Gorilla fixed archive name or extent differs')
        _file(run, ref)
    stage_mounts = setup['canonical_files']
    names = {'axis.ms', *launch.value_files(case['columns'])}
    require(set(stage_mounts) == names and all(set(x) == {'bytes', 'sha256'} and x['bytes'] == case['rows'] * 8
                                               for x in stage_mounts.values()) and
            stage_mounts['axis.ms']['sha256'] == case['input_identity']['native_ms_sha256'],
            'Gorilla canonical file inventory differs')
    require(all(type(setup[k]) is int and setup[k] > 0 for k in ('ingress_wall_ns', 'ingress_cpu_ns')),
            'Gorilla ingress observation differs')


def _verify_restored_direction(case, direction, source, archive, out, record):
    """Check every independently recovered TV record and the iterator's actual seek answer."""
    cols, rows = case['columns'], case['rows']
    axis = np.fromfile(source / 'axis.ms', dtype='<i8')
    require(len(axis) == rows, 'Gorilla verification axis extent differs')
    i = 0
    with archive.open('rb') as wire:
        _head(wire, cols, rows)
        for name in launch.value_files(cols):
            with (source / name).open('rb') as value, (out / Path(name).with_suffix('.tv')).open('rb') as tv:
                for start in range(0, rows, ROWS):
                    full = min(ROWS, rows - start)
                    n = full // 2 if direction == 'snapshot_decode' else full
                    payload = read_frame(wire, n)
                    unit = record['units'][i]
                    raw = value.read(full * 8)
                    require(len(raw) == full * 8 and len(payload) == unit[3], 'Gorilla recovery log or canonical input extent differs')
                    expected = np.empty(n, dtype=RECORD)
                    expected['t'] = axis[start:start + n]
                    expected['v'] = np.frombuffer(raw, dtype='<u8', count=n)
                    require(tv.read(n * PAIR.size) == expected.tobytes(), 'Gorilla recovered TV bit pattern differs')
                    if case['route'] == 'iterator':
                        target, timestamp, bits = unit[-3:]
                        times = expected['t']
                        lower = int(times.searchsorted(times[n // 2], 'left'))
                        require(target == times[n // 2] and timestamp == times[lower] and bits == int(expected['v'][lower]),
                                'Gorilla iterator seek differs from original lower bound')
                    i += 1
                require(not tv.read(1) and not value.read(1), 'Gorilla recovery contains trailing bytes')
        require(not wire.read(1) and i == case['units'], 'Gorilla restoration archive extent differs')


def _trial(root, run, plan, case, entry, setup_source, fixed, setup, index):
    """Keep data preparation, native work and verified durability as nested boundaries."""
    trial_dir = run / _trial_path(case, index)
    trial_dir.mkdir()
    operations, products = [], []
    require(entry['file'] == case['source_original'], 'Gorilla trial original descriptor differs')
    with TemporaryDirectory(prefix='canonical-', dir=trial_dir) as scratch:
        source = Path(scratch) / 'values'
        wall, cpu = monotonic_ns(), process_time_ns()
        _, _, identity = stage(root, entry, source)
        ingress = {'wall_ns': monotonic_ns() - wall, 'cpu_ns': process_time_ns() - cpu}
        require(identity == case['input_identity'], 'Gorilla trial ingress produced different canonical TV')
        out, _, op = _invoke(run, plan, case, source, fixed, trial_dir / 'encode', 'encode')
        verified_encode = {k: _facts(ref) for k, ref in _archive_refs(run, case, out).items()}
        require(verified_encode == {k: _facts(ref) for k, ref in setup['fixed'].items()} and
                op['process']['input_mounts'] == setup['canonical_files'],
                'Gorilla trial input or produced archive differs from fixed reference')
        operations.append({**op, 'verified_durable_wall_ns': monotonic_ns() - wall,
                           'verified_durable_controller_cpu_ns': process_time_ns() - cpu})
        products.append(out)
    for direction in list(CLOCKS[case['route']])[1:]:
        name = 'snapshot.gtv1' if direction == 'snapshot_decode' else 'frame.gtv1'
        wall, cpu = monotonic_ns(), process_time_ns()
        out, raw, op = _invoke(run, plan, case, setup_source, fixed, trial_dir / direction, direction)
        require(op['process']['input_mounts'] == {'frame.gtv1': _facts(setup['fixed'][name])},
                'Gorilla decode did not mount exactly the frozen archive')
        _verify_restored_direction(case, direction, setup_source, fixed / name, out, raw)
        operations.append({**op, 'verified_durable_wall_ns': monotonic_ns() - wall,
                           'verified_durable_controller_cpu_ns': process_time_ns() - cpu})
        products.append(out)
    return {'case_id': case['case_id'], 'index': index, 'phase': 'warmup' if index < WARMUPS else 'measure',
            'block_facts_sha256': case['block_facts_sha256'], 'source_original': case['source_original'],
            'ingress': ingress, 'verified_encode_files': verified_encode, 'operations': operations}, products


def _check_trial(run, case, setup, index, trial, sessions):
    prefix = _trial_path(case, index)
    require(trial['case_id'] == case['case_id'] and trial['index'] == index and
            trial['phase'] == ('warmup' if index < WARMUPS else 'measure') and
            trial['block_facts_sha256'] == case['block_facts_sha256'] and
            trial['source_original'] == case['source_original'] and
            set(trial['ingress']) == {'wall_ns', 'cpu_ns'} and
            all(type(x) is int and x > 0 for x in trial['ingress'].values()) and
            [p['direction'] for p in trial['operations']] == list(CLOCKS[case['route']]), 'unexpected Gorilla trial')
    require(trial['verified_encode_files'] == {name: _facts(ref) for name, ref in setup['fixed'].items()},
            'Gorilla trial archive digest differs from fixed decode input')
    for op in trial['operations']:
        direction, proc = op['direction'], op['process']
        archive = 'snapshot.gtv1' if direction == 'snapshot_decode' else 'frame.gtv1'
        mounts = setup['canonical_files'] if direction == 'encode' else {'frame.gtv1': _facts(setup['fixed'][archive])}
        usage = proc['child_usage']
        require(proc['operation'] == 'native' and proc['status'] == 'completed' and proc['returncode'] == 0 and
                not proc['reason'] and type(proc['pid']) is int and proc['pid'] > 0 and
                isinstance(proc['session_id'], str) and proc['session_id'] not in sessions and
                proc['input_mounts'] == mounts and set(usage) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and
                all(type(v) is int and v >= 0 for v in usage.values()) and usage['maxrss_bytes'] > 0 and
                type(op['controller_cpu_ns']) is int and op['controller_cpu_ns'] > 0 and
                type(proc['process_wall_ns']) is int and type(op['verified_durable_wall_ns']) is int and
                type(op['verified_durable_controller_cpu_ns']) is int and
                0 < op['controller_cpu_ns'] <= op['verified_durable_controller_cpu_ns'] and
                0 < proc['process_wall_ns'] <= op['durable_output_wall_ns'] <= op['verified_durable_wall_ns'] and
                (direction != 'encode' or trial['ingress']['wall_ns'] + op['durable_output_wall_ns'] <= op['verified_durable_wall_ns']),
                'Gorilla isolated process evidence differs')
        sessions.add(proc['session_id'])
        require([r['path'] for r in op['logs']] == [f'{prefix}/{direction}/native.{s}' for s in ('stdout', 'stderr')] and
                op['logs'][1]['bytes'] == 0, 'Gorilla retained native logs differ')
        stdout, _ = (_file(run, ref) for ref in op['logs'])
        require(_metrics(case, direction, load_json(stdout)) == op['native_ns'] and
                sum(op['native_ns'].values()) <= proc['process_wall_ns'], 'Gorilla native clock does not recompute')


def _series(xs):
    return {'min': min(xs), 'median': median(xs), 'max': max(xs)}


def _bill(case, direction):
    """Bill shared T exactly once; native arguments and complete GTV1 are separate."""
    snapshot = direction == 'snapshot_decode'
    rows, cols = case['rows'], case['columns']
    if snapshot:
        rows = (rows // ROWS) * (ROWS // 2) + (rows % ROWS) // 2
    n = case['snapshot_bytes'] if snapshot else case['artifact_bytes']
    overhead = HEADER.size + case['units'] * LENGTH.size
    logical = rows * (cols + 1) * 8
    require(0 <= logical and n > overhead, 'invalid Gorilla byte bill')
    return {'logical_unique_tv_bytes': logical, 'unique_time_bytes': rows * 8, 'logical_value_bytes': rows * cols * 8,
            'native_per_column_tv_bytes': rows * cols * PAIR.size, 'complete_gtv1_bytes': n,
            'native_xorchunk_bytes': n - overhead, 'gtv1_envelope_bytes': overhead, 'logical_over_complete': logical / n}


def _mibps(n, ns):
    return n * 1e9 / ((1 << 20) * ns)


def _summary(case, setup, trials):
    measured = trials[WARMUPS:]
    dirs = {}
    for i, (direction, clocks) in enumerate(CLOCKS[case['route']].items()):
        rows = [t['operations'][i] for t in measured]
        bill = _bill(case, direction)
        n = bill['logical_unique_tv_bytes']
        dirs[direction] = {
            'samples': len(rows), 'byte_bill': bill,
            'native_call_wall_ns': {k: _series([r['native_ns'][k] for r in rows]) for k in clocks},
            'process_wall_ns': _series([r['process']['process_wall_ns'] for r in rows]),
            'durable_output_wall_ns': _series([r['durable_output_wall_ns'] for r in rows]),
            'verified_durable_wall_ns': _series([r['verified_durable_wall_ns'] for r in rows]),
            'verified_durable_controller_cpu_ns': _series([r['verified_durable_controller_cpu_ns'] for r in rows]),
            'controller_cpu_ns': _series([r['controller_cpu_ns'] for r in rows]),
            'child_usage': {k: _series([r['process']['child_usage'][k] for r in rows])
                            for k in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes')},
        }
        if (case['route'], direction) == ('iterator', 'decode'):
            # The full path contains a seek and a traversal; do not pass it off as scan-only bandwidth.
            dirs[direction]['traversal_native_logical_mib_s'] = _series([
                _mibps(n, r['native_ns']['iterator_open'] + r['native_ns']['iterator_drain_and_eof']) for r in rows])
            dirs[direction]['mean_native_seek_ns_per_block'] = _series([
                r['native_ns']['fresh_forward_seek'] / case['units'] for r in rows])
        else:
            dirs[direction]['logical_mib_s'] = {
                'native_call_sum': _series([_mibps(n, sum(r['native_ns'].values())) for r in rows]),
                'verified_durable': _series([_mibps(n, r['verified_durable_wall_ns']) for r in rows]),
            }
        if (case['route'], direction) == ('append-resume', 'encode'):
            dirs[direction]['checkpoint_byte_bill'] = _bill(case, 'snapshot_decode')
            dirs[direction]['total_gtv1_bytes_written'] = case['artifact_bytes'] + case['snapshot_bytes']
    return {**case, 'setup': setup, 'directions': dirs, 'native_backend': 'gorilla_c', 'native_threads': 1,
            'ingress': {key: _series([t['ingress'][key] for t in measured]) for key in ('wall_ns', 'cpu_ns')}}


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY, 'unknown Gorilla diagnostic plan')
    inventory = load_json(local_file(run, 'setup.json'))
    require(list(sorted(inventory)) == sorted(c['case_id'] for c in plan['cases']), 'Gorilla setup population differs')
    env = load_json(local_file(run, 'environment.json'))
    require(set(env) == {'before', 'after'} and all(e['affinity'] == [plan['environment']['cpu']] for e in env.values()),
            'Gorilla timing CPU binding differs')
    summary, sessions = [], set()
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for case in plan['cases']:
            _identity(case, 'case_id')
            setup = inventory[case['case_id']]
            _descriptor_refs(run, case, setup)
            trials = []
            for index in range(WARMUPS + REPEATS):
                row = parse_json(next(f, ''), 'Gorilla measurement row')
                _check_trial(run, case, setup, index, row, sessions)
                trials.append(row)
            summary.append(_summary(case, setup, trials))
        require(next(f, None) is None, 'Gorilla has extra trial records')
    return {'schema': 'bmk.m3-gorilla-corpus-clock-report/2', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'source_seal': plan['source_seal'], 'environment': env, 'policy': POLICY,
            'cases': summary, 'excluded': plan['excluded'], 'verified_trials': (WARMUPS + REPEATS) * len(summary),
            'isolated_operations': len(sessions), 'file_routes': dict(Counter(c['route'] for c in summary)),
            'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}


def _seal(run):
    body = {'schema': 'bmk.m3-gorilla-corpus-clock-seal/1', 'run_id': run.name,
            'files': [_ref(run, local_file(run, name)) for name in ('plan.json', 'setup.json', 'environment.json',
                                                                   'trials.jsonl', 'report.json')]}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, results):
    cpu = plan['environment']['cpu']
    require(results.is_relative_to(root), 'Gorilla results directory is outside of the workspace')
    with resource.reserve():
        require(freeze(root, _file(root, plan['source_plan']), _folder(root, plan['source_run']), cpu) == plan,
                'Gorilla plan or frozen reference differs')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        with _affinity([cpu]):
            results.mkdir(parents=True, exist_ok=True)
            run = results / uuid4().hex
            run.mkdir()
            write_new(run / 'plan.json', plan)
            for lane, binding in plan['bindings'].items():
                stage_recovery(root, run, binding['runtime'], directory=f'runtime-{lane}')
            def environment():
                return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshot': resource.observe(cpu)}
            before = environment()
            setups = {}
            with (run / 'trials.jsonl').open('xb') as f:
                for case in plan['cases']:
                    case_dir = run / 'cases' / case['case_id']
                    case_dir.mkdir(parents=True)
                    with TemporaryDirectory(prefix='canonical-', dir=case_dir) as temp:
                        source = Path(temp) / 'values'
                        a, b = monotonic_ns(), process_time_ns()
                        axis, values, identity = stage(root, entries[case['dataset_id']], source)
                        ingress = {'ingress_wall_ns': monotonic_ns() - a, 'ingress_cpu_ns': process_time_ns() - b}
                        require(identity == case['input_identity'], 'Gorilla original decoded to a different canonical TV view')
                        mounts = {p.name: _facts(_ref(source, p)) for p in [axis, *values]}
                        fixed, anchors = _stash_anchors(run, plan, case, source, case_dir)
                        setups[case['case_id']] = {**ingress, 'canonical_files': mounts, 'fixed': anchors}
                        for index in range(WARMUPS + REPEATS):
                            trial, products = _trial(root, run, plan, case, entries[case['dataset_id']],
                                                     source, fixed, setups[case['case_id']], index)
                            _line(f, trial)  # Persist verified observations before releasing trial products.
                            for folder in products:
                                for path in folder.iterdir():
                                    path.unlink()
                                folder.rmdir()
            write_new(run / 'setup.json', setups)
            write_new(run / 'environment.json', {'before': before, 'after': environment()})
            write_new(run / 'report.json', _report(run, plan))
            write_new(run / 'completion.json', _seal(run))
            _fsync(run, directory=True)
    return run


def verify(run):
    require(load_json(local_file(run, 'completion.json')) == _seal(run), 'Gorilla diagnostic run seal differs')
    plan = load_json(local_file(run, 'plan.json'))
    for lane, binding in plan['bindings'].items():
        for name, ref in binding['runtime']['files'].items():
            _file(run, {'path': f'runtime-{lane}/{name}', **ref})
    result = _report(run, plan)
    require(result == load_json(local_file(run, 'report.json')), 'Gorilla diagnostic report differs on recomputation')
    return result
