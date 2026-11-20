"""Match whole-file fixed-batch repeats against the current functional decision."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic_ns

from ..assets import require
from ..planner.m3_in_run_measurement_v2 import FIXED
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_column_batch as batch, m3_column_batch_timing as timing, m3_fixed_batch_corpus as fixed

DIRECTORY = 'measurement-fixed-batch-anchors'
FAILURES = (OSError, ValueError, subprocess.TimeoutExpired)


def _case(plan, item, row, entry):
    units = fixed.project(item, entry, row['evidence'], plan['build']['fixed_batch']['decoder']['recovery_id'])
    prescribed = plan['measurement']['population'][item['work_item_id']]
    return {**{k: item[k] for k in fixed.BASIS}, 'case_id': prescribed['case_id'], 'configuration': item['input'],
            'view': item['view'], 'source_file': entry['file'], 'units': units,
            'group_count': len(list(batch.groups(units))), 'decode_backends': ['default']}


def _read_anchors(base, case):
    require(base.is_dir() and not base.is_symlink() and {p.name for p in base.iterdir()} == {'raw', 'wire'} and
            not any((base / name).is_symlink() for name in ('raw', 'wire')), 'fixed batch anchor directory differs')
    raw = batch.files(base / 'raw', case['group_count'])
    timing._verify_staged(raw, case)
    wire = batch.files(base / 'wire', case['group_count'])
    return wire, batch.identities(raw), batch.verify_frames(wire, case['units'])


def _create_anchors(root, run, work, binding, bundle, case, entry):
    raw = fixed.prepare(root, entry, case, work)
    wire, _, _ = batch.invoke(binding, bundle, case, 'encode', raw, work / 'anchor-call')
    pending = work / 'anchors'
    pending.mkdir()
    next(iter(raw.values())).parent.rename(pending / 'raw')
    next(iter(wire.values())).parent.rename(pending / 'wire')
    _, raw_ids, wire_ids = _read_anchors(pending, case)
    target = run / DIRECTORY / case['case_id']
    target.parent.mkdir(exist_ok=True)
    require(not target.exists(), 'duplicate fixed batch timing anchor')
    pending.rename(target)
    return {name: target / 'wire' / name for name in wire_ids}, {'raw': raw_ids, 'wire': wire_ids}


def _trial(root, run, work, binding, bundle, case, entry, slot, wire, anchors):
    tick = monotonic_ns()
    encode = slot['slot'] == 'encode'
    inputs = fixed.prepare(root, entry, case, work) if encode else wire
    got, native, process = batch.invoke(binding, bundle, case, slot['slot'], inputs, work / 'call')
    product = batch.verify_frames(got, case['units']) if encode else batch.identities(got)
    require(product == anchors['wire' if encode else 'raw'], 'fixed batch directional product differs')
    sync = monotonic_ns()
    fixed._sync(got, run)
    end = monotonic_ns()
    return {**slot, 'case_id': case['case_id'], 'status': 'measured_as_declared', 'native': native, 'process': process,
            'product': product, 'durable_wall_ns': end - tick, 'fsync_wall_ns': end - sync}


def measure(root, plan, item, entry, work, run, row):
    clock = plan['measurement']
    prescribed = clock['population'][item['work_item_id']]
    require(prescribed['adapter'] == FIXED and row['status'] == 'verified', 'unverified fixed batch timing dependency')
    binding, cpu = clock['fixed_batch'], clock['environment']['cpu']
    before = resource.observe(cpu)
    anchors, failed, trials, sessions = None, None, [], set()
    case = {**prescribed, 'decode_backends': ['default']}
    try:
        case = _case(plan, item, row, entry)
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        wire, anchors = _create_anchors(root, run, work, binding, work / 'runtime', case, entry)
    except FAILURES as exc:
        failed = f'fixed batch same-run anchor preparation failed: {exc}'
    for slot in timing._schedule(case):
        terminal = {**slot, 'case_id': prescribed['case_id']}
        if failed:
            trials.append({**terminal, 'status': 'not_run_after_measurement_failure', 'reason': failed})
            continue
        try:
            with TemporaryDirectory(prefix='trial-', dir=work) as tmp:
                observed = _trial(root, run, Path(tmp), binding, work / 'runtime', case, entry, slot, wire, anchors)
                timing._validate(case, cpu, slot, observed, anchors['raw'], anchors['wire'], sessions)
        except FAILURES as exc:
            failed = str(exc) or type(exc).__name__
            trials.append({**terminal, 'status': 'measurement_failed', 'reason': failed})
        else:
            trials.append(observed)
    doc = {**prescribed, 'status': 'measurement_failed' if failed else 'measured_and_verified', 'reason': failed,
           'trials': trials, 'anchors': anchors, 'resource_before': before, 'resource_after': resource.observe(cpu),
           'timing_admitted': False}
    return {**doc, 'summary': recompute(plan, item, row, entry, run, doc, set(), validate_files=False)}


def recompute(plan, item, row, entry, run, doc, seen, *, validate_files=True):
    clock = plan['measurement']
    prescribed = clock['population'][item['work_item_id']]
    passed = doc['status'] == 'measured_and_verified'
    require(row['status'] == 'verified' and doc['timing_admitted'] is False and doc['adapter'] == prescribed['adapter'] == FIXED and
            doc['case_id'] == prescribed['case_id'] and doc['status'] in ('measured_and_verified', 'measurement_failed') and
            (doc['reason'] is None if passed else isinstance(doc['reason'], str) and bool(doc['reason'])),
            'invalid fixed batch measurement status or identity')
    base = run / DIRECTORY / prescribed['case_id']
    anchors = doc['anchors']
    case = {**prescribed, 'decode_backends': ['default']}
    if anchors is None:
        require(not passed and not base.exists(), 'unanchored fixed batch must not have outputs')
    else:
        case = _case(plan, item, row, entry)
        if validate_files:
            _, raw, wire = _read_anchors(base, case)
            require(anchors == {'raw': raw, 'wire': wire}, 'fixed batch retained group digest differs')
    failed = anchors is None
    rounds = {'encode': [], 'default': []}
    schedule = list(timing._schedule(case))
    require(len(doc['trials']) == len(schedule), 'fixed batch direction coverage differs')
    for slot, trial in zip(schedule, doc['trials'], strict=True):
        require(trial['case_id'] == prescribed['case_id'] and all(trial[k] == v for k, v in slot.items()),
                'fixed batch timing slot differs')
        if not failed and trial['status'] == 'measured_as_declared':
            timing._validate(case, clock['environment']['cpu'], slot, trial, anchors['raw'], anchors['wire'], seen)
            if slot['phase'] == 'measured':
                rounds[slot['slot']].append(trial)
        else:
            require(not passed and trial['reason'] == doc['reason'] and set(trial) == set(slot) | {'case_id', 'status', 'reason'} and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'invalid fixed batch terminal trial')
            failed = True
    require(passed == (not failed), 'fixed batch terminal does not match directional evidence')
    return timing._summarize(case, rounds) if passed else None
