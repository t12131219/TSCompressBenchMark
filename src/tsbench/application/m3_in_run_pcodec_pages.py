"""Whole-file pcodec page-direction measurements bound to this run's functional row."""
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import local_file, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_pcodec_grouped_timing as grouped
from .m3_in_run_measurement import guard

DIRECTORY = 'measurement-pcodec-page-anchors'
FAILED = 'measurement-pcodec-page-failures'
DIRECTIONS = grouped.DIRECTIONS


def _case(item, row, entry, case_id):
    lane = next(k for k, v in grouped.LANES.items() if v == item['route'])
    extent, e = item['input'], row['evidence']
    cols, rows = entry['value_count'], entry['rows']
    ranges = list(grouped._groups(cols, rows))
    count, logical = len(ranges), cols * rows * 8
    obj = item['canonical_object_id']
    require(item['selection'] == 11 and obj == entry['canonical']['object_id'] and
            e['driver'] == 'pcodec-pages-control/1' and e['lane'] == lane and e['columns'] == cols and
            len(e['units']) == count == extent['size_estimate']['input_units'] and
            extent['value_column_range'] == [0, cols] and extent['full_extent_of_file_rows_and_value_columns'] and
            extent['row_ranges'] == [{'object_id': obj, 'partition': 'full', 'start': 0, 'end': rows}] and
            extent['slice_extent']['max_per_unit'] == grouped.CHUNK_ROWS and
            extent['size_estimate']['native_input_bytes_one_pass'] == e['input_bytes'] == logical,
            'pcodec measurement footprint differs from same-run functional decision')
    units = []
    for (col, start, end), unit in zip(ranges, e['units'], strict=True):
        require((unit['column'], unit['row_range'], unit['input_bytes']) == (col, [start, end], (end-start)*8)
                and 0 < unit['artifact_bytes'] <= grouped.launch.FILE_CEILING,
                'pcodec current native group geometry differs')
        units.append({'frame': {'bytes': unit['artifact_bytes'], 'sha256': unit['artifact_sha256']},
                      'semantics': {op: grouped._semantic(unit[op]) for op in DIRECTIONS}})
    payload = sum(u['frame']['bytes'] for u in units)
    raw_bytes, wire_bytes = grouped._archive_bytes(count, logical), grouped._archive_bytes(count, payload)
    require(payload == e['artifact_bytes'] and 0 < cols <= 4096 and 0 < rows <= 10000000 and
            max(raw_bytes, wire_bytes, 1024 * count) <= grouped.launch.FILE_CEILING,
            'pcodec measurement exceeds frozen byte extent or isolated capacity')
    case = {'case_id': case_id, 'dataset_id': item['dataset_id'], 'columns': cols, 'rows': rows,
            'group_count': count, 'logical_bytes': logical, 'source': entry['file'], 'canonical_object_id': obj,
            'input_archive_bytes': raw_bytes, 'variants': {lane: {'units': units, 'frame_archive_bytes': wire_bytes,
            'original_native_frame_bytes': payload}}}
    return case, lane


def schedule(case_id, lane):
    rng = Random(grouped.SEED ^ int(case_id[:16], 16))
    for i in range(grouped.WARMUPS + grouped.ROUNDS):
        for op in rng.sample(DIRECTIONS, len(DIRECTIONS)):
            yield {'case_id': case_id, 'phase': 'warmup' if i < grouped.WARMUPS else 'measured', 'repeat': i,
                   'lane': lane, 'direction': op, 'path': f'{DIRECTORY}/{case_id}/logs/{i:02d}-{op}'}


def _sync_output(path):
    for p in (path, path.parent):
        grouped._sync(p)


def _anchors(root, run, work, scratch, plan, case, lane, entry):
    scratch.mkdir()
    raw = grouped._stage(root, case, entry, scratch)
    frame, _ = grouped._call(work, plan, case, lane, 'encode', scratch/'encode', raw)
    grouped._inspect_frames(case, lane, frame)
    restored, _ = grouped._call(work, plan, case, lane, 'decode', scratch/'decode', frame)
    raw_ref = grouped._amounts(raw)
    require(grouped._amounts(restored) == raw_ref, 'pcodec same-run anchor detached restoration differs')
    fixed = run / DIRECTORY / case['case_id'] / 'fixed.pgf'
    fixed.parent.mkdir(parents=True)
    frame.rename(fixed)
    _sync_output(fixed)
    return {'raw': raw_ref, 'fixed': {lane: grouped._ref(run, fixed)}}


def _trial(root, run, work, scratch, plan, case, lane, entry, setup, slot):
    op = slot['direction']
    start, cpu = monotonic_ns(), process_time_ns()
    wire = setup['fixed'][lane]
    if op == 'encode':
        source = grouped._stage(root, case, entry, scratch)
        ingress = monotonic_ns() - start
    else:
        source, ingress = local_file(run, wire['path']), None
    output, facts = grouped._call(work, plan, case, lane, op, scratch/op, source)
    want_in, want_out = (setup['raw'], {k: wire[k] for k in ('bytes', 'sha256')}) if op == 'encode' else (
        {k: wire[k] for k in ('bytes', 'sha256')}, setup['raw'])
    result = grouped._inspect_frames(case, lane, output) if op == 'encode' else grouped._amounts(output)
    require(facts['process']['input_mounts'] == {'object': want_in} and result == want_out,
            'pcodec measured output or exact single-object input differs from anchor')
    _sync_output(output)
    observed = {**slot, **facts, 'input_original': case['source'] if op == 'encode' else None, 'result': result,
                'ingress_wall_ns': ingress, 'verified_durable_wall_ns': monotonic_ns()-start,
                'controller_cpu_ns': process_time_ns()-cpu, 'status': 'measured_as_declared'}
    target = run / slot['path']
    target.mkdir(parents=True)
    observed['logs'] = []
    for name in failure.NAMES:
        dst = target / name
        shutil.copyfile(scratch/op/name, dst)
        observed['logs'].append(grouped._ref(run, dst))
    return observed


def _summary(case, lane, trials):
    get = grouped._distribution
    directions = {}
    for op in DIRECTIONS:
        found = [t for t in trials if t['phase'] == 'measured' and t['direction'] == op]
        require(len(found) == grouped.ROUNDS, 'pcodec matched direction coverage differs')
        directions[op] = {'count': len(found), **{k: get([t[k] for t in found]) for k in (
            'prepared_to_sync_wall_ns', 'verified_durable_wall_ns', 'controller_cpu_ns')},
            'ingress_wall_ns': get([t['ingress_wall_ns'] for t in found]) if op == 'encode' else None,
            'process_wall_ns': get([t['process']['process_wall_ns'] for t in found]),
            'native': {k: get([t['native'][k] for t in found]) for k in found[0]['native']},
            'child_usage': {k: get([t['process']['child_usage'][k] for t in found])
                            for k in found[0]['process']['child_usage']}}
    wire = case['variants'][lane]
    return {**{k: case[k] for k in ('case_id', 'dataset_id', 'columns', 'rows', 'group_count', 'logical_bytes',
                                    'input_archive_bytes')}, 'lane': lane, 'native_threads': 1,
            'byte_bill': {'native_frame_bytes': wire['original_native_frame_bytes'],
                          'grouped_frame_archive_bytes': wire['frame_archive_bytes'],
                          'grouped_framing_bytes': wire['frame_archive_bytes'] - wire['original_native_frame_bytes']},
            'directions': directions}


def measure(root, plan, item, entry, run, work, row):
    frozen = plan['measurement']
    prescribed = frozen['population'][item['work_item_id']]
    case_id = prescribed['case_id']
    lane = next(k for k, v in grouped.LANES.items() if v == item['route'])
    failed_path = f'{FAILED}/{case_id}'
    binding = frozen['pcodec_pages']
    anchors = error = None
    trials, logs = [], []
    before = resource.observe(frozen['environment']['cpu'])
    scratch = work/'reference'
    try:
        case, lane = _case(item, row, entry, case_id)
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        anchors = _anchors(root, run, work, scratch, binding, case, lane, entry)
    except (OSError, ValueError) as exc:
        logs = failure.retain(run, failed_path, 'anchor', scratch, DIRECTIONS)
        error = 'pcodec same-run anchor failed: ' + failure.reason(exc, scratch, run/failed_path/'anchor')
    for slot in schedule(case_id, lane):
        if error:
            trials.append({**slot, 'status': 'not_run_after_measurement_failure', 'reason': error})
            continue
        with TemporaryDirectory(prefix='trial-', dir=work) as tmp:
            scratch = Path(tmp)
            try:
                trials.append(_trial(root, run, work, scratch, binding, case, lane, entry, anchors, slot))
            except (OSError, ValueError) as exc:
                logs = failure.retain(run, failed_path, 'trial', scratch, (slot['direction'],))
                error = failure.reason(exc, scratch, run/failed_path/'trial')
                trials.append({**slot, 'status': 'measurement_failed', 'reason': error})
    doc = {**prescribed, 'status': 'measurement_failed' if error else 'measured_and_verified', 'reason': error,
           'trials': trials, 'anchors': anchors, 'resource_before': before,
           'resource_after': resource.observe(frozen['environment']['cpu']), 'timing_admitted': False,
           'failure_logs': logs}
    return {**doc, 'summary': recompute(root, plan, item, row, entry, run, doc, set(), check_anchors=False)}


def recompute(root, plan, item, row, entry, run, doc, seen, *, check_anchors=True):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    case_id = prescribed['case_id']
    lane = next(k for k, v in grouped.LANES.items() if v == item['route'])
    anchors, passed = doc['anchors'], doc['status'] == 'measured_and_verified'
    base = run/DIRECTORY/case_id
    require(row['status'] == 'verified' and prescribed['adapter'] == doc['adapter'] and doc['case_id'] == case_id and
            doc['timing_admitted'] is False and doc['status'] in ('measured_and_verified', 'measurement_failed') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (anchors is not None or not passed),
            'pcodec measured decision identity or terminal differs')
    failure.check(run, f'{FAILED}/{case_id}', doc, DIRECTIONS, full=check_anchors)
    if anchors is not None:
        case, lane = _case(item, row, entry, case_id)
        fixed = anchors['fixed'][lane]
        require(set(anchors) == {'fixed', 'raw'} and set(anchors['fixed']) == {lane} and
                fixed['path'] == f'{DIRECTORY}/{case_id}/fixed.pgf', 'pcodec anchor inventory differs')
        if check_anchors:
            with TemporaryDirectory(prefix='pcodec-audit-') as tmp:
                raw = grouped._amounts(grouped._stage(root, case, entry, Path(tmp)))
            wire = grouped._inspect_frames(case, lane, grouped._file(run, fixed))
            require(raw == anchors['raw'] and wire == {k: fixed[k] for k in ('bytes', 'sha256')},
                    'pcodec same-run anchors do not recompute')
    else:
        require(not base.exists(), 'unanchored pcodec measurement has retained products')
    failed = anchors is None
    slots = list(schedule(case_id, lane))
    require(len(slots) == len(doc['trials']), 'pcodec frozen direction coverage differs')
    paths = set()
    for slot, trial in zip(slots, doc['trials'], strict=True):
        require(all(trial[k] == v for k, v in slot.items()), 'pcodec frozen direction schedule differs')
        if not failed and trial['status'] == 'measured_as_declared':
            grouped._check_trial(run, case, anchors, slot, trial, seen)
            paths.update(r['path'] for r in trial['logs'])
        else:
            require(not passed and trial.get('reason') == doc['reason'] and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'pcodec invalid direction failure terminal')
            failed = True
    if check_anchors and anchors is not None:
        require({p.relative_to(run).as_posix() for p in base.rglob('*') if p.is_file()} == paths | {fixed['path']},
                'pcodec anchor/log file inventory differs')
    require(passed == (not failed), 'pcodec direction terminals disagree with decision')
    return _summary(case, lane, doc['trials']) if passed else None


def observe(root, plan, item, entry, run, row):
    with guard(plan), TemporaryDirectory(prefix='m3-pcodec-pages-', dir=run) as work:
        return measure(root, plan, item, entry, run, Path(work), row)
