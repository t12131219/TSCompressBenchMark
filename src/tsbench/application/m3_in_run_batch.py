"""Shared same-run batch timing, including common-frame decoder lanes."""
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic_ns

from ..assets import require
from ..planner.m3_in_run_measurement_v2 import FIXED
from ..planner.m3_in_run_measurement_v3 import COLUMN
from ..planner.m3_fixed_batch import DRIVER as FIXED_DRIVER
from ..planner.m3_titchy import BATCH_DRIVER as TITCHY_DRIVER
from .m3_in_run_fixed_batch import DIRECTORY as FIXED_DIRECTORY, _read_anchors
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_column_batch as batch, m3_column_batch_timing as timing, m3_fixed_batch_corpus as fixed

COLUMN_DIRECTORY = 'measurement-column-batch-anchors'
DIRECTORIES = {FIXED: FIXED_DIRECTORY, COLUMN: COLUMN_DIRECTORY}
FAILURES = (OSError, ValueError, subprocess.TimeoutExpired)


def _protocol(plan, item, prescribed):
    key = item['selection'], item['route']
    clock = plan['measurement']
    if prescribed['adapter'] == FIXED:
        require(key in fixed.ROUTES, 'wrong adapter for fixed batch decision')
        return clock['fixed_batch'], ['default'], fixed.prepare
    require(prescribed['adapter'] == COLUMN and key in batch.ROUTES, 'wrong adapter for column batch decision')
    backends = list(batch.ROUTES[key][1])
    require(clock['column_batch']['operations'][item['route']] == ['encode', *backends],
            'column batch decoder lanes differ from freeze')
    return clock['column_batch'], backends, batch.prepare_values


def _case(plan, item, row, entry, prescribed, backends):
    proof = row['evidence']
    if prescribed['adapter'] == FIXED:
        units = fixed.project(item, entry, proof, plan['build']['fixed_batch']['decoder']['recovery_id'])
    else:
        if item['selection'] == 9:
            require(proof['driver'] == FIXED_DRIVER and
                    proof['recovery_id'] == plan['build']['fixed_batch']['decoder']['recovery_id'],
                    'ALP functional recovery closure differs')
        else:
            require(proof['driver'] == TITCHY_DRIVER, 'wrong Titchy functional driver')
        units = batch.project(item, entry, proof)
    return {**{k: item[k] for k in fixed.BASIS}, 'case_id': prescribed['case_id'], 'configuration': item['input'],
            'view': item['view'], 'source_file': entry['file'], 'units': units,
            'group_count': len(list(batch.groups(units))), 'decode_backends': backends}


def _anchor_path(run, prescribed):
    return run / DIRECTORIES[prescribed['adapter']] / prescribed['case_id']


def _create_anchors(root, target, work, binding, bundle, case, entry, prepare):
    raw = prepare(root, entry, case, work)
    wire, _, _ = batch.invoke(binding, bundle, case, 'encode', raw, work / 'anchor-call')
    pending = work / 'anchors'
    pending.mkdir()
    next(iter(raw.values())).parent.rename(pending / 'raw')
    next(iter(wire.values())).parent.rename(pending / 'wire')
    _, raw_ids, wire_ids = _read_anchors(pending, case)
    target.parent.mkdir(exist_ok=True)
    require(not target.exists(), 'duplicate batch timing anchor')
    pending.rename(target)
    return {name: target / 'wire' / name for name in wire_ids}, {'raw': raw_ids, 'wire': wire_ids}


def _trial(root, run, work, binding, bundle, case, entry, slot, wire, anchors, prepare):
    tick = monotonic_ns()
    encode = slot['slot'] == 'encode'
    inputs = prepare(root, entry, case, work) if encode else wire
    got, native, process = batch.invoke(binding, bundle, case, slot['slot'], inputs, work / 'call')
    product = batch.verify_frames(got, case['units']) if encode else batch.identities(got)
    require(product == anchors['wire' if encode else 'raw'], 'batch directional product differs')
    sync = monotonic_ns()
    fixed._sync(got, run)
    end = monotonic_ns()
    return {**slot, 'case_id': case['case_id'], 'status': 'measured_as_declared', 'native': native, 'process': process,
            'product': product, 'durable_wall_ns': end - tick, 'fsync_wall_ns': end - sync}


def measure(root, plan, item, entry, work, run, row):
    clock = plan['measurement']
    prescribed = clock['population'][item['work_item_id']]
    require(row['status'] == 'verified', 'unverified batch timing dependency')
    binding, backends, prepare = _protocol(plan, item, prescribed)
    cpu = clock['environment']['cpu']
    before = resource.observe(cpu)
    anchors, failed, trials, sessions = None, None, [], set()
    case = {**prescribed, 'decode_backends': backends}
    try:
        case = _case(plan, item, row, entry, prescribed, backends)
        stage_recovery(root, work, binding['runtime'], directory='runtime')
        wire, anchors = _create_anchors(root, _anchor_path(run, prescribed), work, binding, work / 'runtime', case, entry, prepare)
    except FAILURES as exc:
        failed = f'batch same-run anchor preparation failed: {exc}'
    for slot in timing._schedule(case):
        terminal = {**slot, 'case_id': prescribed['case_id']}
        if failed:
            trials.append({**terminal, 'status': 'not_run_after_measurement_failure', 'reason': failed})
            continue
        try:
            with TemporaryDirectory(prefix='trial-', dir=work) as tmp:
                observed = _trial(root, run, Path(tmp), binding, work / 'runtime', case, entry, slot, wire, anchors, prepare)
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
    _, backends, _ = _protocol(plan, item, prescribed)
    passed = doc['status'] == 'measured_and_verified'
    require(row['status'] == 'verified' and doc['timing_admitted'] is False and doc['adapter'] == prescribed['adapter'] and
            doc['case_id'] == prescribed['case_id'] and doc['status'] in ('measured_and_verified', 'measurement_failed') and
            (doc['reason'] is None if passed else isinstance(doc['reason'], str) and bool(doc['reason'])),
            'invalid batch measurement status or identity')
    base = _anchor_path(run, prescribed)
    anchors = doc['anchors']
    case = {**prescribed, 'decode_backends': backends}
    if anchors is None:
        require(not passed and not base.exists(), 'unanchored batch must not have outputs')
    else:
        case = _case(plan, item, row, entry, prescribed, backends)
        if validate_files:
            _, raw, wire = _read_anchors(base, case)
            require(anchors == {'raw': raw, 'wire': wire}, 'batch retained group digest differs')
    failed = anchors is None
    rounds = {lane: [] for lane in ('encode', *backends)}
    schedule = list(timing._schedule(case))
    require(len(doc['trials']) == len(schedule), 'batch direction coverage differs')
    for slot, trial in zip(schedule, doc['trials'], strict=True):
        require(trial['case_id'] == prescribed['case_id'] and all(trial[k] == v for k, v in slot.items()),
                'batch timing slot differs')
        if not failed and trial['status'] == 'measured_as_declared':
            timing._validate(case, clock['environment']['cpu'], slot, trial, anchors['raw'], anchors['wire'], seen)
            if slot['phase'] == 'measured':
                rounds[slot['slot']].append(trial)
        else:
            require(not passed and trial['reason'] == doc['reason'] and set(trial) == set(slot) | {'case_id', 'status', 'reason'} and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'invalid batch terminal trial')
            failed = True
    require(passed == (not failed), 'batch terminal does not match directional evidence')
    return timing._summarize(case, rounds) if passed else None
