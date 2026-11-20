"""Same-run ZFP field and fixed-rate array measurements on verified functional evidence."""
from pathlib import Path
from random import Random
from shutil import copyfile
from tempfile import TemporaryDirectory

from ..assets import canonical_bytes, local_file, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_zfp_array_timing as array, m3_zfp_field_timing as field
from .m3_in_run_measurement import guard
from .m3_lzbench_timing import _affinity, _file, _ref

D = 'measurement-zfp'
DIRECTORY = f'{D}/cases'
FAILED = 'measurement-zfp-failures'
SEED = 20261120


def _case(item, row, entry, case_id):
    ev, scope = row['evidence'], item['input']
    cols, rows, obj = entry['value_count'], entry['rows'], item['canonical_object_id']
    route, status = item['route'], row['status']
    sizes = scope['size_estimate']
    require(item['selection'] == 31 and ev['driver'] == field.DRIVER and ev['timing_admitted'] is False and
            obj == entry['canonical']['object_id'] and scope['representation'] == 'f64_columns' and
            ev['columns'] == cols and scope['value_column_range'] == [0, cols] and
            scope['row_ranges'] == [{'partition': 'full', 'start': 0, 'end': rows, 'object_id': obj}] and
            len(ev['units']) == sizes['input_units'], 'ZFP same-run decision identity or extent differs')
    case = {**{k: item[k] for k in ('dataset_id', 'route', 'work_item_id', 'canonical_object_id', 'operation_config_id')},
            'case_id': case_id, 'source': entry['file'], 'rows': rows, 'columns': cols, 'configuration': scope}
    if route == array.ROUTE:
        units = ev['units']
        geometry = list(array.array_windows(scope['array_contract'], cols, rows))
        require(status in ('verified', 'quality_rejected') and ev['input_domain'] == 'bounded_balanced_windows' and
                0 < len(geometry) == len(units) <= 25000, 'ZFP array same-run window count differs')
        native = meta = logical = rejected = 0
        for (c, a, b), unit in zip(geometry, units, strict=True):
            n = b-a
            conf = array._config(n)
            shape = field._stamp(canonical_bytes({'format': 'zfp-array-rank1-v1', 'type': 'f64', 'shape': [n],
                                                   'requested_rate': 18, 'effective_rate': 32}))
            payload = conf['frame_bytes']
            require((unit['column'], unit['row_range'], unit['logical_input_bytes']) == (c, [a,b], n*8) and
                    unit['config'] == conf and unit['before_frame']['bytes'] == unit['after_frame']['bytes'] == payload and
                    unit['input']['bytes'] == unit['restored']['bytes'] == unit['exact_mutated_reference']['bytes'] == n*8 and
                    unit['metadata'] == shape and unit['artifact_bytes'] == payload + shape['bytes'] and
                    unit['unchanged_native_blocks'] == (payload-32)//16 and
                    unit['quality_passed'] == (unit['before']['accepted'] and unit['after']['accepted']),
                    'ZFP array same-run window facts differ')
            native += payload; meta += shape['bytes']; logical += n*8; rejected += not unit['quality_passed']
        require(logical == ev['input_bytes_one_pass'] == sizes['native_input_bytes_one_pass'] and
                meta + native == ev['artifact_bytes'] and ev['quality_rejected_units'] == rejected and
                (status == 'quality_rejected') == bool(rejected), 'ZFP array same-run quality or bytes differ')
        case.update(status=status, reason=row['reason'], units=units, logical_bytes=logical, native_frame_bytes=native,
                    old_json_shape_bytes=meta, rejected_windows=rejected)
        require(max(array._extent(case, tag) for tag in (array.RAW, array.WIRE, array.VALUES)) <= array.launch.FILE_CEILING,
                'ZFP same-run array launch budget exceeded')
        return case
    lanes = {k: p for k, (r, p) in field.LANES.items() if r == route}
    logical = rows*cols*8
    require(lanes and status == 'verified' and ev['quality_rejected_units'] == 0 and
            ev['input_domain'] == 'full_reversible_columns' and len(ev['units']) == cols and
            ev['input_bytes_one_pass'] == logical == sizes['native_input_bytes_one_pass'] and
            scope['full_extent_of_file_rows_and_value_columns'] and scope['slice_extent']['max_per_unit'] is None and
            0 < rows <= 131072 and 0 < cols <= 4096 and logical <= field.launch.FILE_CEILING,
            'ZFP reversible same-run full column geometry differs')
    raw, payloads = [], {k: [] for k in lanes}
    shape = field._stamp(canonical_bytes({'format': 'zfp-raw-reversible-v1', 'type': 'f64', 'shape': [rows]}))
    for col, unit in enumerate(ev['units']):
        ref = unit['same_field']
        require((unit['column'], unit['row_range'], unit['logical_input_bytes']) == (col, [0,rows], rows*8) and
                ref['bytes'] == rows*8 and set(unit['profiles']) == set(lanes.values()), 'ZFP field profile geometry differs')
        raw.append(ref)
        for lane, p in lanes.items():
            observed = unit['profiles'][p]; f = observed['frame']; n = f['bytes']
            require(0 < n <= 4 << 20 and n % 8 == 0 and observed['encode'] == field._field_record(rows, n, p) and
                    observed['restore'] == field._field_record(rows, n, 'serial') and observed['restored'] == ref and
                    observed['metadata'] == shape and observed['artifact_bytes'] == n+shape['bytes'], 'ZFP native profile differs')
            payloads[lane].append(f)
    require(ev['artifact_bytes'] == {p: sum(f['bytes'] for f in payloads[k])+cols*shape['bytes'] for k,p in lanes.items()},
            'ZFP full field billing differs')
    case.update(raw_units=raw, lanes=payloads, old_metadata_bytes_per_column=shape['bytes'])
    require(all(field._archive_bytes(case, lane) <= field.launch.FILE_CEILING for lane in lanes), 'ZFP full archive exceeds budget')
    return case


def schedule(case_id, route):
    rng = Random(SEED ^ int(case_id[:16], 16))
    coords = [(None, op) for op in array.OPERATIONS] if route == array.ROUTE else [
        (k, op) for k, (r, _) in field.LANES.items() if r == route for op in field.DIRECTIONS]
    prefix = f'cases/{case_id}'
    for i in range(4):
        for lane, op in rng.sample(coords, len(coords)):
            tag = f'{lane}-{op}' if lane else op
            yield {'case_id': case_id, 'op': op, 'repeat': i, 'phase': 'warmup' if not i else 'measure',
                   'path': f'{prefix}/{i:02d}-{tag}', **({'lane': lane} if lane else {})}


def _field_anchor(root, work, binding, c, entry, reference):
    place = work/'cases'/c['case_id']
    fixed = place/'fixed'
    fixed.mkdir(parents=True)
    source, raw = field._stage_raw(root, c, entry, reference)
    anchors, observers = {}, {}
    for lane in c['lanes']:
        out, proc, logs = field._call(work, binding, c, lane, 'encode', reference/f'{lane}-encode', source, 'timing')
        facts = field._verify_archive(out, c, lane)
        require(proc['input_mounts'] == {'columns': raw}, 'ZFP anchor mounted different columns')
        field._native(c, lane, 'encode', logs[0], 'timing')
        archive = fixed/f'{lane}.zfg'
        out.rename(archive)
        anchors[lane] = _ref(work, archive)
        require(field._amounts(anchors[lane]) == facts, 'ZFP fixed anchor bytes differ')
        field._sync(archive)
        decode, proc, logs = field._call(work, binding, c, lane, 'decode', reference/f'{lane}-decode', archive, 'timing')
        require(proc['input_mounts'] == {'archive': facts} and field._verify_raw(decode, c) == raw,
                'ZFP detached reversible anchor failed')
        field._native(c, lane, 'decode', logs[0], 'timing')
        if lane not in field.OBSERVED:
            continue
        for op in field.DIRECTIONS:
            path = place/'observer'/f'{lane}-{op}'
            path.parent.mkdir(exist_ok=True)
            out, proc, logs = field._call(work, binding, c, lane, op, path, source if op == 'encode' else archive, 'observer')
            native = field._native(c, lane, op, logs[0], 'observer')
            product = field._done(out, c, lane, op)
            obs = field._result(work, path, lane, op, 'observer', native, proc, logs, product)
            observers[f'{lane}-{op}'] = obs
            out.unlink(); out.parent.rmdir()
    return source, {'raw': raw, 'anchors': anchors, 'observations': observers}


def _summary(c, setup, xs):
    if c['route'] == array.ROUTE:
        return array._summary(c, setup, xs)
    stats, dist = {}, field._dist
    logical = setup['raw']['bytes']
    for lane in c['lanes']:
        wire = setup['anchors'][lane]['bytes']
        native = sum(x['bytes'] for x in c['lanes'][lane])
        arm = {'encoder_profile': field.LANES[lane][1], 'decoder_profile': 'serial', 'billing': {
            'logical_bytes': logical, 'native_frame_bytes': native, 'archive_bytes': wire, 'wrapper_bytes': wire-native,
            'separate_shape_bytes_in_functional_path': c['old_metadata_bytes_per_column']*c['columns'], 'ratio': logical/wire}}
        for op in field.DIRECTIONS:
            rows = [x for x in xs if (x['lane'], x['op'], x['phase']) == (lane, op, 'measure')]
            n, d = [x['native']['api_wall_ns'] for x in rows], [x['durable_wall_ns'] for x in rows]
            require(len(rows) == 3, 'ZFP measured denominator differs')
            arm[op] = {'samples': len(rows), 'native_api_wall_ns': dist(n), 'durable_wall_ns': dist(d),
                       'native_process_cpu_ns': dist([x['native']['api_process_cpu_ns'] for x in rows]),
                       'isolated_process_wall_ns': dist([x['process']['process_wall_ns'] for x in rows]),
                       'controller_cpu_ns': dist([x['controller_cpu_ns'] for x in rows]),
                       'ingress_wall_ns': dist([x['ingress_wall_ns'] for x in rows]) if op == 'encode' else None,
                       'child_usage': {k: dist([x['process']['child_usage'][k] for x in rows]) for k in rows[0]['process']['child_usage']},
                       'logical_mib_s': {k: dist([logical*1e9/(t*(1<<20)) for t in vals]) for k, vals in [('native', n), ('durable', d)]},
                       'configured_threads': rows[0]['native']['configured_threads'], 'timed_trial_block_thread_count': None,
                       'separate_block_observation': setup['observations'].get(f'{lane}-{op}', {}).get('native')}
        stats[lane] = arm
    return {'case_id': c['case_id'], 'dataset_id': c['dataset_id'], 'route': c['route'], 'profiles': stats}


def _cpu_ids(plan, item):
    m = plan['measurement']
    return [m['environment']['cpu']] if item['route'] == array.ROUTE else [r['cpu'] for r in m['zfp']['field_environment']]


def _retain_failure(run, case_id, place, label):
    base = run/FAILED/case_id/label
    logs = []
    for p in sorted(place.rglob('native.*')):
        if p.name not in ('native.stdout', 'native.stderr') or not p.is_file() or p.is_symlink():
            continue
        dest = base/p.relative_to(place)
        dest.parent.mkdir(parents=True, exist_ok=True)
        copyfile(p, dest)
        field._sync(dest)
        logs.append(_ref(run, dest))
    if logs:
        for folder in sorted((p for p in base.parent.rglob('*') if p.is_dir()), key=lambda p: -len(p.parts)):
            field._sync(folder)
        for folder in (base.parent, base.parent.parent, run):
            field._sync(folder)
    return logs


def measure(root, plan, item, entry, run, row, work):
    frozen = plan['measurement']; prescribed = frozen['population'][item['work_item_id']]; cid = prescribed['case_id']
    is_array = item['route'] == array.ROUTE
    binding = frozen['zfp']['array' if is_array else 'field']
    cpus = _cpu_ids(plan, item)
    before = {str(cpu): resource.observe(cpu) for cpu in cpus}
    slots = list(schedule(cid, item['route']))
    terminals, logs, anchors, error = [], [], None, None
    reference = work/'reference'; reference.mkdir()
    try:
        c = _case(item, row, entry, cid)
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        src, anchors = (array._prepare if is_array else _field_anchor)(root, work, binding, c, entry, reference)
    except (OSError, ValueError) as exc:
        logs = _retain_failure(run, cid, work, 'anchor')
        error = f'ZFP same-run anchor failed: {exc}'.replace(str(work)+'/', f'{FAILED}/{cid}/anchor/')
    for i, slot in enumerate(slots):
        if error:
            terminals.append({'slot': slot, 'phase': slot['phase'], 'status': 'not_run_after_measurement_failure', 'reason': error})
            continue
        try:
            args = (root, work, binding, c, entry)
            trial, products = (array._trial(*args, src, anchors, slot) if is_array else field._trial(*args, anchors, slot))
            if is_array:
                array._check_trial(work, c, anchors, slot, trial, set())
                for p in products.values():
                    p.unlink()
            else:
                field._check(work, c, anchors, trial, 'timing', set(), slot=slot)
                products.unlink()
            (work/slot['path']/'out').rmdir()
            terminals.append({'slot': slot, 'phase': slot['phase'], 'status': 'measured_as_declared', 'evidence': trial})
        except (OSError, ValueError) as exc:
            logs = _retain_failure(run, cid, work/slot['path'], f'trial-{i:02d}')
            error = (str(exc) or type(exc).__name__).replace(str(work/slot['path'])+'/', f'{FAILED}/{cid}/trial-{i:02d}/')
            terminals.append({'slot': slot, 'phase': slot['phase'], 'status': 'measurement_failed', 'reason': error})
            # Publish only completed logs, fixed frames and observer evidence.
    if anchors is not None:
        dest = run/DIRECTORY/cid
        dest.mkdir(parents=True)
        source = work/'cases'/cid
        for name in ['fixed', *(['observer'] if (source/'observer').exists() else []),
                     *(Path(t['slot']['path']).name for t in terminals if t['status'] == 'measured_as_declared')]:
            (source/name).rename(dest/name)
        for parent in (dest, dest.parent, dest.parent.parent, run):
            field._sync(parent)
    status = 'measurement_failed' if error else 'measured_quality_rejected' if row['status'] == 'quality_rejected' else 'measured_and_verified'
    doc = {**prescribed, 'status': status, 'reason': error, 'trials': terminals, 'anchors': anchors, 'failure_logs': logs,
           'cpu_ids': cpus, 'resource_before': before, 'resource_after': {str(cpu): resource.observe(cpu) for cpu in cpus},
           'timing_admitted': False}
    return {**doc, 'summary': recompute(root, plan, item, entry, run, row, doc, set(), check_anchors=False)}


def _anchors(root, c, entry, base, setup, sessions, full):
    cid = c['case_id']
    paths = set()
    if c['route'] == array.ROUTE:
        require(set(setup) == {'raw', 'archives', 'recovery'} and set(setup['archives']) == set(setup['recovery']) == set(array.ARCHIVE_ROLES),
                'ZFP array anchor inventory differs')
        for role, ref in setup['archives'].items():
            require(ref['path'] == f'cases/{cid}/fixed/{role}.zag' and
                    setup['recovery'][role]['quality'] == array._quality_proof(c, role) and
                    setup['recovery'][role]['product']['bytes'] == array._extent(c, array.VALUES), 'ZFP array anchor coordinates differ')
            paths.add(ref['path'])
        if full:
            with TemporaryDirectory(prefix='zfp-array-audit-') as tmp:
                _, raw = array._staging(root, c, entry, Path(tmp))
            archives = array._archives(c, {role: _file(base, ref) for role,ref in setup['archives'].items()})
            require(setup['raw'] == raw and archives == {k: field._amounts(v) for k,v in setup['archives'].items()},
                    'ZFP array anchors do not recompute')
        return paths
    require(set(setup) == {'raw', 'anchors', 'observations'} and set(setup['anchors']) == set(c['lanes']),
            'ZFP field anchor inventory differs')
    arms = [(lane, op) for lane in c['lanes'] if lane in field.OBSERVED for op in field.DIRECTIONS]
    require(set(setup['observations']) == {f'{lane}-{op}' for lane,op in arms}, 'ZFP separate observer inventory differs')
    for lane, ref in setup['anchors'].items():
        require(ref['path'] == f'cases/{cid}/fixed/{lane}.zfg', 'ZFP field anchor coordinates differ')
        paths.add(ref['path'])
        if full:
            require(field._verify_archive(_file(base, ref), c, lane) == field._amounts(ref), 'ZFP field anchor differs')
    if full:
        with TemporaryDirectory(prefix='zfp-field-audit-') as tmp:
            _, raw = field._stage_raw(root, c, entry, Path(tmp))
        require(setup['raw'] == raw, 'ZFP raw original anchor differs')
    for lane, op in arms:
        obs = setup['observations'][f'{lane}-{op}']
        field._check(base, c, setup, obs, 'observer', sessions, lane=lane, op=op)
        paths.update(r['path'] for r in obs['logs'])
    return paths


def recompute(root, plan, item, entry, run, row, doc, sessions, *, check_anchors=True):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    cid = prescribed['case_id']; base = run/D
    array_mode = item['route'] == array.ROUTE
    accepted = row['status'] == 'verified'
    done = 'measured_and_verified' if accepted else 'measured_quality_rejected'
    setup, passed = doc['anchors'], doc['status'] == done
    require((accepted or array_mode and row['status'] == 'quality_rejected') and doc['case_id'] == cid and
            doc['adapter'] == prescribed['adapter'] and doc['cpu_ids'] == _cpu_ids(plan, item) and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed', done) and (doc['reason'] is None if passed else bool(doc['reason'])) and
            (setup is not None or not passed), 'ZFP main-ledger measurement identity or terminal differs')
    paths = set()
    if setup is not None:
        c = _case(item, row, entry, cid)
        paths = _anchors(root, c, entry, base, setup, sessions, check_anchors)
    else:
        require(not (run/DIRECTORY/cid).exists(), 'unanchored ZFP decision retained purported anchors')
    failed = setup is None
    slots = list(schedule(cid, item['route']))
    require(len(doc['trials']) == len(slots), 'ZFP operation denominator differs')
    failure_kind = 'anchor' if failed else None
    valid = []
    for i, (slot, terminal) in enumerate(zip(slots, doc['trials'], strict=True)):
        status = terminal['status']
        require(terminal['slot'] == slot and terminal['phase'] == slot['phase'], 'ZFP operation coordinates differ')
        if not failed and status == 'measured_as_declared':
            trial = terminal['evidence']
            if array_mode:
                array._check_trial(base, c, setup, slot, trial, sessions)
            else:
                field._check(base, c, setup, trial, 'timing', sessions, slot=slot)
            paths.update(r['path'] for r in trial['logs'])
            valid.append(trial)
        else:
            require(not passed and terminal.get('reason') == doc['reason'] and
                    status == ('not_run_after_measurement_failure' if failed else 'measurement_failed') and
                    'evidence' not in terminal, 'ZFP invalid operation terminal')
            if not failed:
                failure_kind = f'trial-{i:02d}'
            failed = True
    require(passed == (not failed), 'ZFP decision disagrees with operation terminals')
    p = run/FAILED/cid
    failure_paths = []
    for ref in doc['failure_logs']:
        path = Path(ref['path'])
        require(failed and path.parts[:3] == (FAILED, cid, failure_kind) and
                path.name in ('native.stdout','native.stderr'), 'ZFP failure log coordinates differ')
        _file(run, ref)
        failure_paths.append(ref['path'])
    require(len(set(failure_paths)) == len(failure_paths), 'duplicate ZFP failure logs')
    if check_anchors:
        for folder, origin, expected in ((p, run, set(failure_paths)), (run/DIRECTORY/cid, base, paths)):
            actual = list(folder.rglob('*'))
            require(not folder.is_symlink() and all(not x.is_symlink() for x in actual) and
                    {x.relative_to(origin).as_posix() for x in actual if x.is_file()} == expected and folder.exists() == bool(expected),
                    'ZFP retained file inventory differs')
    return _summary(c, setup, valid) if passed else None


def observe(root, plan, item, entry, run, row):
    with TemporaryDirectory(prefix='m3-zfp-primary-', dir=run) as tmp:
        work = Path(tmp)
        if item['route'] == array.ROUTE:
            with guard(plan):
                return measure(root, plan, item, entry, run, row, work)
        cpus = _cpu_ids(plan, item)
        require(field._cpus(cpus) == plan['measurement']['zfp']['field_environment'], 'ZFP field CPU policy no longer matches')
        with _affinity(cpus):
            return measure(root, plan, item, entry, run, row, work)
