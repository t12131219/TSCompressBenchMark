"""Primary-ledger measurements for the whole-file ABI and ordered SElf* drivers."""
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import load_json, local_file, require
from ..planner import m3_huff0_fec1, m3_sprintz
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_whole_durable as whole
from .m3_in_run_measurement import guard

DIRECTORY = 'measurement-whole-anchors'
FAILED = 'measurement-whole-failures'
DIRECTIONS = ('encode', 'decode')
SEED = 20261120


def schedule(case_id):
    rng = Random(SEED ^ int(case_id[:16], 16))
    for i in range(4):
        for op in rng.sample(DIRECTIONS, 2):
            yield {'operation': op, 'round': i, 'phase': 'warmup' if i == 0 else 'measured'}


def _case(item, row, entry, case_id):
    scope, proof = item['input'], row['evidence']
    cols, rows = entry['value_count'], entry['rows']
    obj = item['canonical_object_id']
    require(obj == entry['canonical']['object_id'] and scope['full_extent_of_file_rows_and_value_columns'] and
            scope['value_column_range'] == [0, cols] and
            scope['row_ranges'] == [{'object_id': obj, 'partition': 'full', 'start': 0, 'end': rows}],
            'whole-file measurement scope differs from current decision')
    key = (item['selection'], item['route'])
    common = {k: item[k] for k in ('selection', 'dataset_id', 'route', 'work_item_id', 'canonical_object_id')}
    case = {**common, 'case_id': case_id, 'configuration': scope, 'source_file': entry['file']}
    if key in whole.abi.CODECS:
        plugin = whole.abi.CODECS[key]
        driver = m3_sprintz.DRIVER if key == m3_sprintz.BATCH else m3_huff0_fec1.DRIVER
        require(proof['driver'] == driver, 'whole-file ABI functional driver differs')
        return {**case, 'driver': 'abi', 'plugin': plugin, 'units': whole.abi.project(proof, entry, item, plugin)}
    require(key in whole.selfstar.DRIVERS and proof['driver'] == whole.selfstar.DRIVERS[key] and
            (proof['rows'], proof['columns'], proof['input_bytes']) == (rows, cols, rows*cols*8) and
            scope['representation'] == 'f64_columns' and scope['column_grouping'] == 'one_work_unit_series_per_value_column',
            'SElf* full-column driver or extent differs')
    live = item['route'] == whole.selfstar.LIVE
    units = [{k:v for k,v in u.items() if k != 'process_wall_ns'} for u in proof['units']]
    require([u['column'] for u in units] == list(range(cols)) and proof['artifact_bytes'] == sum(u['artifact_bytes'] for u in units)
            and all(u['row_range'] == [0, rows] and u['input_bytes'] == rows*8 <= whole.selfstar.LIMITS['file_bytes'] and
                    whole.abi.br(whole.selfstar.schema(rows, u['column']))['sha256'] == u['schema_sha256'] and
                    0 < u['artifact_bytes'] <= whole.selfstar.LIMITS['file_bytes'] and (u['lifecycle'] is not None) == live and
                    u['artifact_bytes'] == u['native_payload_bytes'] + u['block_header_bytes'] + u['object_envelope_bytes']
                    for u in units), 'SElf* column bytes or native lifecycle differs')
    return {**case, 'driver': 'selfstar', 'rows': rows, 'cols': cols, 'variant': 'incremental' if live else 'batch', 'units': units}


def _facts(case, wire):
    if case['driver'] == 'abi':
        paths = whole.abi.files(wire, len(list(whole.abi.groups(case['units']))))
        return paths, whole.abi.verify_frames(paths, case['units'])
    _, wanted = whole.selfstar.refs(case)
    paths = whole._self_paths(wire, wanted)
    for unit in case['units']:
        col = unit['column']
        facts = whole.selfstar.wire_facts(paths[whole.selfstar.names(col)[2]].read_bytes(), case['rows'],
                                          whole.selfstar.schema(case['rows'], col))
        require(facts == {k: unit[k] for k in facts}, 'SElf* exact native block layout differs')
    return paths, wanted


def _log_dir(case, slot):
    return f"{DIRECTORY}/{case['case_id']}/logs/{slot['round']:02d}-{slot['operation']}"


def _preserve_failure(run, directory, kind, scratch, directions):
    # The existing ABI supervisor uses its direction as the log prefix.
    for op in directions:
        for name in failure.NAMES:
            suffix = name.split('.')[1]
            source = scratch/op/f'{op}.{suffix}'
            if source.is_file():
                source.rename(source.with_name(name))
    return failure.retain(run, directory, kind, scratch, directions)


def _anchor(root, run, work, binding, case, entry, scratch):
    scratch.mkdir()
    raw = whole._raw(root, entry, case, scratch)
    raw_ref = whole.abi.identities(raw)
    # Both directions are untimed anchors, used only to establish exact product identity.
    op = 'encode'
    encoded, trial = whole._resolved(work, binding, case, {'operation': op, 'round': -1, 'phase': 'anchor'}, raw, scratch/op)
    wire_dir = next(iter(encoded.values())).parent
    paths, wire_ref = _facts(case, wire_dir)
    seen = set()
    for op in DIRECTIONS:
        slot = {'operation': op, 'round': -1, 'phase': 'anchor'}
        if op == 'decode':
            _, trial = whole._resolved(work, binding, case, slot, paths, scratch/op)
        _check_operation(binding, case, slot, trial, raw_ref, wire_ref, seen)
    base = run/DIRECTORY/case['case_id']
    base.mkdir(parents=True)
    wire_dir.rename(base/'wire')
    whole._sync({k: base/'wire'/k for k in paths}, run)
    return {'raw': raw_ref, 'wire': wire_ref}


def _check_operation(binding, case, slot, trial, raw, wire, seen):
    if case['driver'] == 'abi':
        source, output = (raw, wire) if slot['operation'] == 'encode' else (wire, raw)
        whole.abi.validate(binding, case, slot, trial, source, output, seen)
    else:
        whole.selfstar.validate(binding, case, slot, trial, seen)


def _trial(root, run, work, scratch, binding, case, entry, anchors, slot):
    op = slot['operation']
    begin, cpu = monotonic_ns(), process_time_ns()
    if op == 'encode':
        source = whole._raw(root, entry, case, scratch)
    else:
        wire = run/DIRECTORY/case['case_id']/'wire'
        source = {k: local_file(wire, k) for k in anchors['wire']}
    got, row = whole._resolved(work, binding, case, slot, source, scratch/op)
    require(row['output'] == anchors['wire' if op == 'encode' else 'raw'], 'whole-file direction differs from same-run anchor')
    sync = monotonic_ns()
    whole._sync(got, run)
    end = monotonic_ns()
    elapsed_cpu = process_time_ns()-cpu
    directory = run/_log_dir(case, slot)
    directory.mkdir(parents=True)
    logs = []
    for name in failure.NAMES:
        path = directory/name
        (scratch/op/f"{op}.{name.split('.')[1]}").rename(path)
        logs.append(failure._ref(run, path))
    return {**row, 'direction': op, 'status': 'measured_as_declared', 'logs': logs,
            'durable_wall_ns': end-begin, 'fsync_wall_ns': end-sync, 'controller_cpu_ns': elapsed_cpu}


def measure(root, plan, item, row, entry, run, work):
    frozen = plan['measurement']
    prescribed = frozen['population'][item['work_item_id']]
    case_id = prescribed['case_id']
    failed_path = f'{FAILED}/{case_id}'
    before = resource.observe(frozen['environment']['cpu'])
    trials, logs = [], []
    anchors = reason = None
    scratch = work/'reference'
    try:
        case = _case(item, row, entry, case_id)
        binding = frozen['whole'][case['driver']]
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        anchors = _anchor(root, run, work, binding, case, entry, scratch)
    except (OSError, ValueError) as exc:
        logs = _preserve_failure(run, failed_path, 'anchor', scratch, DIRECTIONS)
        reason = 'whole-file same-run anchor failed: ' + failure.reason(exc, scratch, run/failed_path/'anchor')
    for slot in schedule(case_id):
        identity = {**slot, 'case_id': case_id, 'direction': slot['operation']}
        if reason:
            trials.append({**identity, 'status': 'not_run_after_measurement_failure', 'reason': reason})
            continue
        with TemporaryDirectory(prefix='trial-', dir=work) as tmp:
            scratch = Path(tmp)
            try:
                trials.append(_trial(root, run, work, scratch, binding, case, entry, anchors, slot))
            except (OSError, ValueError) as exc:
                logs = _preserve_failure(run, failed_path, 'trial', scratch, (slot['operation'],))
                reason = failure.reason(exc, scratch, run/failed_path/'trial')
                trials.append({**identity, 'status': 'measurement_failed', 'reason': reason})
    doc = {**prescribed, 'status': 'measurement_failed' if reason else 'measured_and_verified', 'reason': reason,
           'trials': trials, 'anchors': anchors, 'resource_before': before,
           'resource_after': resource.observe(frozen['environment']['cpu']), 'timing_admitted': False, 'failure_logs': logs}
    return {**doc, 'summary': recompute(root, plan, item, row, entry, run, doc, set(), check_anchors=False)}


def recompute(root, plan, item, row, entry, run, doc, seen, *, check_anchors=True):
    prescribed = plan['measurement']['population'][item['work_item_id']]
    case_id = prescribed['case_id']
    base = run/DIRECTORY/case_id
    anchors, passed = doc['anchors'], doc['status'] == 'measured_and_verified'
    require(row['status'] == 'verified' and doc['case_id'] == case_id and prescribed['adapter'] == doc['adapter'] and
            doc['timing_admitted'] is False and doc['status'] in ('measured_and_verified', 'measurement_failed') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (anchors is not None or not passed),
            'invalid whole-file measurement identity or terminal')
    failure.check(run, f'{FAILED}/{case_id}', doc, DIRECTIONS, full=check_anchors)
    paths = set()
    if anchors is not None:
        case = _case(item, row, entry, case_id)
        binding = plan['measurement']['whole'][case['driver']]
        if check_anchors:
            with TemporaryDirectory(prefix='whole-audit-') as tmp:
                raw = whole.abi.identities(whole._raw(root, entry, case, Path(tmp)))
            files, wire = _facts(case, base/'wire')
            paths.update(p.relative_to(run).as_posix() for p in files.values())
            require(anchors == {'raw': raw, 'wire': wire}, 'whole-file anchors fail independent recomputation')
    else:
        require(not base.exists(), 'unanchored whole-file decision has retained products')
    failed = anchors is None
    slots = list(schedule(case_id))
    require(len(slots) == len(doc['trials']), 'whole-file direction coverage differs')
    for slot, trial in zip(slots, doc['trials'], strict=True):
        require(trial['case_id'] == case_id and all(trial[k] == v for k,v in slot.items()) and
                trial['direction'] == slot['operation'], 'whole-file direction schedule differs')
        if not failed and trial['status'] == 'measured_as_declared':
            expected = [f'{_log_dir(case, slot)}/{n}' for n in failure.NAMES]
            require([r['path'] for r in trial['logs']] == expected and trial['logs'][1]['bytes'] == 0,
                    'whole-file native log paths differ')
            stdout, _ = (failure._file(run, ref) for ref in trial['logs'])
            require(load_json(stdout) == trial['native'] and trial['controller_cpu_ns'] > 0,
                    'whole-file native log or controller CPU disagrees')
            whole._validate(binding, case, slot, trial, anchors['raw'], anchors['wire'], seen)
            paths.update(expected)
        else:
            require(not passed and trial.get('reason') == doc['reason'] and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'invalid whole-file direction terminal')
            failed = True
    if check_anchors and anchors is not None:
        entries = list(base.rglob('*'))
        require(all(not p.is_symlink() for p in entries) and paths == {p.relative_to(run).as_posix() for p in entries if p.is_file()},
                'whole-file retained log inventory differs')
    require(passed == (not failed), 'whole-file decision disagrees with trials')
    return whole._summarize(case, doc['trials']) if passed else None


def observe(root, plan, item, row, entry, run):
    with guard(plan), TemporaryDirectory(prefix='m3-whole-', dir=run) as work:
        return measure(root, plan, item, row, entry, run, Path(work))
