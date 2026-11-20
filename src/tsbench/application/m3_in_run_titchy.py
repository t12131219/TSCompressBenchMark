"""Primary-ledger Titchy packet stream, loaded access, and stateless range timing."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import local_file, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_titchy_grouped as grouped, m3_titchy_grouped_timing as timing
from .m3_fixed_batch_corpus import _sync
from .m3_in_run_measurement import guard
from .m3_in_run_whole import _preserve_failure

DIRECTORY = 'measurement-titchy-anchors'
FAILED = 'measurement-titchy-failures'


def _case(root, item, row, entry, cid, work):
    proof = row['evidence']; stream = grouped.is_stream(item)
    require(row['status'] == 'verified' and item['selection'] == 85 and item['route'] in grouped.ROUTES and
            proof['driver'] == ('titchy-stream-control/1' if stream else 'titchy-access-control/1'),
            'Titchy timing needs a verified same-run native route')
    case = {**{k: item[k] for k in ('work_item_id','canonical_object_id','dataset_id','operation_config_id','route')},
            'case_id': cid, 'source_file': entry['file'], 'configuration': item['input']}
    if stream:
        case['units'] = grouped.project(item, entry, proof, {})
        return case, grouped.prepare(root, entry, case, work)
    geometry = grouped.extent(item, entry, proof)
    paths = grouped.stage_columns(root, entry, work/'columns')
    raw = work/'raw'; raw.mkdir()
    units = []
    # Access rows include the validated native frame and query results, but do not
    # store a full original-value digest per unit. Recompute it from the locked source.
    # This does not need a separate batch decision, historical or otherwise.
    with ExitStack() as stack:
        sources = [stack.enter_context(p.open('rb')) for p in paths]
        for i, ((col, lo, hi), u) in enumerate(zip(geometry, proof['units'], strict=True)):
            n = (hi-lo)*8
            f = sources[col]
            require(f.tell() == lo*8, 'Titchy original column extent diverged')
            original = raw/grouped.filename(i, 'raw'); original.write_bytes(f.read(n))
            orig = grouped.ref(original)
            bill = {k:u[k] for k in ('header_bytes','index_bytes','dictionary_and_payload_bytes')}
            require(orig['bytes'] == n == u['logical_input_bytes'] and sum(bill.values()) == u['artifact_bytes'] and
                    0 < n <= grouped.LIMITS['file_bytes'] and 0 < u['artifact_bytes'] <= grouped.LIMITS['file_bytes'],
                    'Titchy access unit byte extent differs')
            units.append({'column': col, 'row_range': [lo,hi], 'original': orig, 'cost': bill,
                          'parts': {'wire': {'bytes': u['artifact_bytes'], 'sha256': u['sha256']}},
                          'native': {'encode': grouped.facts(u['encode']), 'decode': grouped.facts(u['access'])}})
        require(all(not f.read(1) for f in sources), 'Titchy original column has unread rows')
    require(sum(u['parts']['wire']['bytes'] for u in units) == proof['artifact_bytes'], 'Titchy route byte bill differs')
    case['units'] = units
    return case, grouped.files(raw, grouped.expected(case, 'raw'))


def _slot(case_id, i, direction):
    return f'{DIRECTORY}/{case_id}/logs/{i:02d}-{direction}'


def _trial(root, run, work, scratch, binding, case, entry, fixed, slot, i):
    direction = slot['direction']; start, cpu = monotonic_ns(), process_time_ns()
    args = grouped.prepare(root, entry, case, scratch) if direction == 'encode' else fixed
    native = scratch/direction
    products, obs, proc = grouped.invoke(binding, work/'runtime', case, direction, args, native)
    ids = {n:grouped.ref(p) for n,p in products.items()}
    sync = monotonic_ns()
    _sync(products, run)
    end, elapsed_cpu = monotonic_ns(), process_time_ns()-cpu
    dest = run/_slot(case['case_id'], i, direction)
    dest.mkdir(parents=True)
    logs = []
    for name in failure.NAMES:
        path = dest/name
        (native/f"{direction}.{name.split('.')[1]}").rename(path)
        logs.append(failure._ref(run, path))
    _sync({p.name:p for p in dest.iterdir()}, run)
    return {**slot, 'case_id':case['case_id'], 'outputs':ids, 'process':proc, 'observations':timing.metrics(case,direction,obs),
            'durable_wall_ns':end-start, 'fsync_wall_ns':end-sync, 'controller_cpu_ns':elapsed_cpu, 'logs':logs,
            'status':'measured_as_declared'}


def measure(root, plan, item, entry, run, row, work):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']
    cpu = m['environment']['cpu']; before = resource.observe(cpu)
    binding = m['titchy_grouped']
    base = run/DIRECTORY/cid; dir_fail = f'{FAILED}/{cid}'
    anchor = work/'anchor'; anchor.mkdir()
    setup = err = None; trials, logs = [], []
    try:
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        case, raw = _case(root, item, row, entry, cid, anchor)
        wire, en, _ = grouped.invoke(binding, work/'runtime', case, 'encode', raw, anchor/'encode')
        restored, de, _ = grouped.invoke(binding, work/'runtime', case, 'decode', wire, anchor/'decode')
        grouped.certify(case, raw, wire, restored, en, de)
        # Only the fixed wire/manifest survives. Original bits are regenerated by audit.
        base.mkdir(parents=True)
        next(iter(wire.values())).parent.rename(base/'wire')
        fixed = grouped.files(base/'wire', grouped.expected(case, 'wire'))
        _sync(fixed, run)
        setup = {part: grouped.expected(case, part) for part in ('raw','wire')}
    except (ValueError, OSError) as exc:
        logs = _preserve_failure(run, dir_fail, 'anchor', anchor, grouped.DIRS)
        err = 'Titchy same-run anchor failed: ' + failure.reason(exc, anchor, run/dir_fail/'anchor')
    for i, slot in enumerate(timing.schedule({'case_id':cid})):
        if err:
            trials.append({**slot, 'case_id':cid, 'status':'not_run_after_measurement_failure', 'reason':err})
            continue
        with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
            scratch = Path(tmp)
            try:
                trials.append(_trial(root, run, work, scratch, binding, case, entry, fixed, slot, i))
            except (ValueError, OSError) as exc:
                logs = _preserve_failure(run, dir_fail, 'trial', scratch, (slot['direction'],))
                err = failure.reason(exc, scratch, run/dir_fail/'trial')
                trials.append({**slot,'case_id':cid,'status':'measurement_failed','reason':err})
    doc = {**frozen, 'anchors':setup, 'failure_logs':logs, 'status':'measurement_failed' if err else 'measured_and_verified',
           'reason':err, 'trials':trials, 'timing_admitted':False, 'resource_before':before, 'resource_after':resource.observe(cpu)}
    return {**doc, 'summary':recompute(root, plan, item, entry, run, row, doc, set(), cached_case=case if setup else None)}


def recompute(root, plan, item, entry, run, row, doc, seen, *, cached_case=None):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']
    base = run/DIRECTORY/cid; setup = doc['anchors']; passed = doc['status'] == 'measured_and_verified'
    require(row['status'] == 'verified' and doc['case_id'] == cid and doc['adapter'] == frozen['adapter'] and
            doc['timing_admitted'] is False and doc['status'] in ('measurement_failed','measured_and_verified') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (setup is not None or not passed),
            'Titchy primary timing identity or terminal differs')
    failure.check(run, f'{FAILED}/{cid}', doc, grouped.DIRS)
    files = set()
    if setup is not None:
        case = cached_case
        if case is None:
            with TemporaryDirectory(prefix='titchy-audit-') as tmp:
                case, _ = _case(root, item, row, entry, cid, Path(tmp))
        require(setup == {part: grouped.expected(case, part) for part in ('raw','wire')}, 'Titchy same-run anchor facts differ')
        fixed = grouped.files(base/'wire', setup['wire'])
        files.update(p.relative_to(run).as_posix() for p in fixed.values())
    else:
        require(not base.exists(), 'unanchored Titchy decision has retained products')
    failed = setup is None; measured = {d:[] for d in grouped.DIRS}
    slots = list(timing.schedule({'case_id':cid}))
    require(len(slots) == len(doc['trials']), 'Titchy frozen direction denominator differs')
    for i, (slot, trial) in enumerate(zip(slots,doc['trials'],strict=True)):
        direction = slot['direction']
        require(trial['case_id'] == cid and all(trial[k] == v for k,v in slot.items()), 'Titchy frozen direction schedule differs')
        if not failed and trial['status'] == 'measured_as_declared':
            expected = [f'{_slot(cid,i,direction)}/{name}' for name in failure.NAMES]
            require([r['path'] for r in trial['logs']] == expected and trial['logs'][1]['bytes'] == 0 and
                    trial['controller_cpu_ns'] > 0, 'Titchy retained native logs or controller clock differ')
            stdout, _ = (failure._file(run, r) for r in trial['logs'])
            cpu = m['environment']['cpu']
            timing._check(case, cpu, slot, trial, grouped.read_observations(case,direction,stdout,cpu), seen)
            files.update(expected)
            if trial['phase'] == 'measured':
                measured[direction].append(trial)
        else:
            require(not passed and trial.get('reason') == doc['reason'] and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'Titchy measurement direction terminal differs')
            failed = True
    require(passed == (not failed), 'Titchy decision disagrees with direction terminals')
    entries = list(base.rglob('*'))
    require(not base.is_symlink() and all(not p.is_symlink() for p in entries) and
            files == {p.relative_to(run).as_posix() for p in entries if p.is_file()}, 'Titchy retained inventory differs')
    if not passed:
        return None
    stats = timing._summarize(case, measured)
    for d in grouped.DIRS:
        stats['directions'][d]['controller_cpu_ns'] = timing.distribution([t['controller_cpu_ns'] for t in measured[d]])
    stats['native_threads'] = 1
    return stats


def observe(root, plan, item, entry, run, row):
    with guard(plan), TemporaryDirectory(prefix='m3-titchy-primary-',dir=run) as tmp:
        return measure(root, plan, item, entry, run, row, Path(tmp))
