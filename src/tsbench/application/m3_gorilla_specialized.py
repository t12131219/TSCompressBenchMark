"""Gorilla specialist products in the M3 ledger, with disjoint C11 closures."""
from collections import Counter
from pathlib import Path
import struct
import subprocess
import tempfile

from ..assets import ContractError, require, verify_asset
from ..planner.batch_execution import _inputs, requires_cross
from ..planner.gorilla_state import state_inputs
from ..planner.m3_gorilla_specialized import STATE_ROUTES
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import batch_execution as batch, gorilla_state as state
from .m3_gorilla import _head, invoke, read_frame, restore_independent, run_gorilla

NAMES = {'tv-batch': 'original-tv-batch', 'state': 'repaired-state'}


def run_bound_corpus(root, plan, item, entry, work, run):
    original = plan['build']['gorilla_corpus']
    repair = plan['build']['gorilla_state_repair']
    implementation = 'gorilla-c11-unique-v1'
    selected = original
    if item['route'] in STATE_ROUTES:
        build = repair['repair_build']
        selected = {**original, 'executable': build['programs']['tsbench_gorilla_corpus_control'],
                    'dependency': build['dependency']}
        implementation = repair['implementation']
    bound = {**plan, 'build': {**plan['build'], 'gorilla_corpus': selected}}
    return {**run_gorilla(root, bound, item, entry, work, run), 'implementation': implementation,
            'executable': selected['executable'], 'dependency': selected['dependency']}


def _lane_inputs(root, binding):
    tv, _ = _inputs(root)
    lifecycle, _ = state_inputs(root)
    tv = {slot['product_slot']: (slot, sample) for slot, sample in tv.values()}
    require({sid: slot for sid, (slot, _) in lifecycle.items()} == binding['state']['slots'] and
            [slot for slot, _ in tv.values()] == binding['tv_batch']['slots'],
            'Gorilla specialist inputs differ from frozen slots')
    return {'tv-batch': tv, 'state': lifecycle}


def _ids(mapping, rows):
    require(all(row['selection'] == 7 and row['obligation_id'] in mapping for row in rows),
            'Gorilla obligation does not match its planned closure')
    return sorted({sid for row in rows for sid in mapping[row['obligation_id']]})


def _wanted(slot):
    return 'expected_rejection' if slot.get('expected_status') else 'verified'


def _lane(run, root, lane, plan, mapping, rows, inputs, driver, append):
    folder = run / 'gorilla-specialized' / NAMES[lane]
    folder.mkdir(parents=True, exist_ok=False)
    ids = _ids(mapping, rows)
    results = {}
    try:
        require(launcher_lock() == plan['launchers'], 'Gorilla isolation launchers changed after planning')
        stage_recovery(root, folder, plan['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for name in ('logs', 'products', 'controls'):
            (folder / name).mkdir()
        execute = batch._case if lane == 'tv-batch' else state.run_slot
        for sid in ids:
            slot, sample = inputs[sid]
            result = results[sid] = execute(folder, plan, slot, sample, lambda: False)
            append({'entry_kind': 'specialized_product', 'selection': 7, 'lane': lane, **result})
        for row in rows:
            slots = mapping[row['obligation_id']]
            failures = [f"{sid}: {results[sid]['status']} ({results[sid]['reason']})" for sid in slots
                        if results[sid]['status'] != _wanted(inputs[sid][0])]
            row.update(status='failed' if failures else 'verified', reason='; '.join(failures),
                       evidence={'driver': driver, 'lane': lane, 'fixture_slots': slots})
    return {'directory': folder.relative_to(run).as_posix(), 'recovery_id': plan['decoder']['recovery_id'],
            'fixtures': results, 'statuses': dict(Counter(r['status'] for r in results.values())),
            'files': batch._files(folder)}


def _regression_bits():
    t = (0, 1000, 2000, 3000)
    v = (0, 0, 1, 1)
    return struct.pack('<4q', *t), struct.pack('<4Q', *v), b''.join(struct.pack('<qQ', *p) for p in zip(t, v))


def _run_regression(root, run, build):
    folder = run / 'gorilla-specialized' / 'repair-regression'
    folder.mkdir(parents=True, exist_ok=False)
    original = build['gorilla_corpus']['executable']
    selected = build['gorilla_state_repair']['repair_build']['programs']['tsbench_gorilla_corpus_control']
    result = {'entry_kind': 'implementation_regression', 'selection': 7, 'route': 'append-resume',
              'case': 'initial-undefined-xor-window-four-rows', 'rows': 4, 'cut': 2,
              'status': 'failed', 'reason': '', 'original_failure': None, 'files': {}}
    t, v, want = _regression_bits()
    try:
        with tempfile.TemporaryDirectory(prefix='m3-gorilla-regression-') as td:
            work = Path(td)
            source = work / 'input'
            source.mkdir()
            (source / 'axis.ms').write_bytes(t)
            (source / 'column-0000.bin').write_bytes(v)
            try:
                invoke(verify_asset(root, original), work, 'encode', 'append-resume', 'input', 1, 4,
                       'original.gtv1', 'original-snapshot.gtv1')
            except ContractError as exc:
                result['original_failure'] = str(exc)
            require(result['original_failure'] and 'resumed result differs from batch bytes' in result['original_failure'],
                    'original Gorilla four-row failure did not reproduce')
            exe = verify_asset(root, selected)
            invoke(exe, work, 'encode', 'append-resume', 'input', 1, 4, 'final.gtv1', 'snapshot.gtv1')
            detached = work / 'detached'
            detached.mkdir()
            for label, rows, mode in (('final', 4, 'append-resume'), ('snapshot', 2, 'snapshots')):
                archive = work / f'{label}.gtv1'
                archive.rename(detached / archive.name)
                restored = detached / label
                restored.mkdir()
                invoke(exe, detached, 'decode', mode, archive.name, label)
                with (detached / archive.name).open('rb') as stream:
                    _head(stream, 1, 4)
                    wire = read_frame(stream, rows)
                    require(not stream.read(1), 'Gorilla regression contains trailing data')
                require((restored / 'column-0000.tv').read_bytes() == restore_independent(wire, rows) == want[:16 * rows],
                        'Gorilla regression native or independent restoration differs')
                (folder / f'{label}.xor').write_bytes(wire)
        result['status'] = 'verified'
    except (ContractError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        result['reason'] = str(exc)
    result['files'] = batch._files(folder)
    return result


def audit_regression(run, row):
    folder = run / 'gorilla-specialized' / 'repair-regression'
    require(row['entry_kind'] == 'implementation_regression' and row['selection'] == 7 and row['route'] == 'append-resume' and
            row['case'] == 'initial-undefined-xor-window-four-rows' and (row['rows'], row['cut']) == (4, 2) and
            row['status'] == 'verified' and not row['reason'] and 'resumed result differs from batch bytes' in row['original_failure'] and
            row['files'] == batch._files(folder) and row['files'].keys() == {'final.xor', 'snapshot.xor'},
            'Gorilla implementation regression did not verify')
    _, _, want = _regression_bits()
    for name, n in (('final.xor', 4), ('snapshot.xor', 2)):
        require(restore_independent((folder / name).read_bytes(), n) == want[:16 * n],
                'Gorilla retained regression recovery differs')
    return row


def run_specialized(root: Path, run: Path, binding: dict, rows: list, append, *, build) -> dict:
    inputs = _lane_inputs(root, binding)
    lanes = {}
    for lane, mapping in binding['obligation_slots'].items():
        subset = [row for row in rows if row['obligation_id'] in mapping]
        if subset:
            plan = binding['tv_batch' if lane == 'tv-batch' else 'state']
            lanes[lane] = _lane(run, root, lane, plan, mapping, subset, inputs[lane], binding['driver'], append)
    require(sum(r['evidence'] is not None or r['status'] == 'dependency_failed' for r in rows) == len(rows),
            'unmapped Gorilla specialist obligation')
    result = {'driver': binding['driver'], 'lanes': lanes}
    if any(row['route'] == 'append-resume' for row in rows):
        result['regression'] = _run_regression(root, run, build)
        append(result['regression'])
    return result


def _audit_tv(folder, plan, slot, sample, row, allowed, *, replay):
    sid = slot['product_slot']
    cross = requires_cross(plan, slot)
    status = slot['expected_status']
    order = ([batch.ENCODE] if status else
             [batch.ENCODE, batch.NATIVE_ENCODE, batch.DECODE, batch.NATIVE_DECODE, batch.CROSS_DECODE]
             if cross else [batch.ENCODE, batch.DECODE])
    ops = row['operations']
    logs = folder / 'logs' / sid
    require([op['operation'] for op in ops] == order and
            len({op['session_id'] for op in ops}) == len(ops), 'Gorilla TV batch operation chain differs')
    for op in ops:
        for ext in ('stdout', 'stderr'):
            p = logs / f"{op['operation']}.{ext}"
            require(0 <= p.stat().st_size <= plan['limits']['file_bytes'], 'Gorilla batch log outside bound')
            allowed.add(p.relative_to(folder).as_posix())
    if status:
        require(row['reason'] == batch.INPUT_STATUS[status] and
                batch._rejected_log(ops[0], logs, batch.ENCODE, status) and
                all(row[k] is None for k in ('artifact', 'control_payload', 'payload_validation', 'restored', 'cross_restored')),
                'Gorilla TV expected rejection differs')
    else:
        require(not row['reason'] and all(batch._completed(op) for op in ops), 'Gorilla TV batch operation failed')
        name = f'products/{sid}.bmk'
        require(row['artifact']['path'] == name, 'Gorilla TV retained frame path differs')
        frame = verify_asset(folder, row['artifact'])
        allowed.add(name)
        require(frame.stat().st_size == row['artifact']['bytes'] and
                row['payload_validation'] == batch._inspect(frame, slot) and row['restored'] == slot['original'],
                'Gorilla TV retained frame or independent restoration differs')
        shape, _ = batch._worker_json(logs / (batch.DECODE + '.stdout'), 2)
        require(shape == {'columns': slot['original']['columns']}, 'Gorilla TV decoder shape differs')
        if cross:
            name = f'controls/{sid}.xor'
            source = slot['original']
            direct = row['control_payload']
            require(direct['path'] == name and verify_asset(folder, direct).stat().st_size == direct['bytes'] and
                    direct['sha256'] == row['payload_validation']['native_payload_sha256'] and
                    row['cross_restored'] == {'abi_to_native': {k: source[k] for k in ('column_bytes', 'column_sha256')},
                                              'native_to_abi': source}, 'Gorilla direct C11 parity differs')
            for label in (batch.NATIVE_ENCODE, batch.NATIVE_DECODE):
                observed, = batch._worker_json(logs / (label + '.stdout'), 1)
                require(observed == {'rows': source['columns'][0]['count']}, 'Gorilla C11 row count differs')
            shape, _ = batch._worker_json(logs / (batch.CROSS_DECODE + '.stdout'), 2)
            require(shape == {'columns': source['columns']}, 'Gorilla cross decoder shape differs')
            allowed.add(name)
        else:
            require(row['control_payload'] is None and row['cross_restored'] is None, 'unexpected Gorilla TV control')
    if replay:
        with tempfile.TemporaryDirectory(prefix='m3-gorilla-tv-audit-') as tmp:
            work = Path(tmp)
            # Refusal needs its original inputs; positive restoration has only the retained decoder and frames.
            if status:
                source = work / 'source'
                source.mkdir()
                inputs = {name: source / name for name in ('schema', *batch._column_names(slot))}
                for path, data in zip(inputs.values(), (sample.schema, *sample.columns), strict=True):
                    path.write_bytes(data)
                out, operation = batch._encode(folder / DIRECTORY, plan, slot, work, work, inputs, lambda: False)
                require(batch._rejected_log(operation, work, batch.ENCODE, status),
                        'Gorilla TV expected rejection did not replay')
                batch._expect_files(out, ())
            else:
                require(batch._restore(folder / DIRECTORY, plan, slot, frame, work, work, lambda: False) == row['restored'],
                        'Gorilla TV detached replay differs')
                if cross:
                    require(batch._cross_restore(folder / DIRECTORY, plan, slot, frame, folder / name, work,
                                                 lambda: False) == row['cross_restored'], 'Gorilla TV cross replay differs')


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    inputs = _lane_inputs(root, binding)
    require(evidence['driver'] == binding['driver'], 'Gorilla specialist driver differs')
    expected_lanes = set()
    statuses = {}
    for lane, mapping in binding['obligation_slots'].items():
        subset = [row for row in rows if row['obligation_id'] in mapping]
        if not subset:
            continue
        expected_lanes.add(lane)
        plan = binding['tv_batch' if lane == 'tv-batch' else 'state']
        spec = plan['decoder']
        retained = evidence['lanes'][lane]
        directory = f'gorilla-specialized/{NAMES[lane]}'
        folder = run / directory
        fixtures, files = retained['fixtures'], retained['files']
        require(retained['directory'] == directory and retained['recovery_id'] == spec['recovery_id'] and
                set(fixtures) == set(_ids(mapping, subset)) and files == batch._files(folder) and
                retained['statuses'] == dict(Counter(r['status'] for r in fixtures.values())),
                'Gorilla specialist evidence is incomplete or was modified')
        allowed = set()
        for name, ref in spec['files'].items():
            rel = f'{DIRECTORY}/{name}'
            require(files.get(rel) == {'path': rel, 'sha256': ref['sha256'], 'bytes': ref['bytes']},
                    'Gorilla specialist decoder closure differs')
            allowed.add(rel)
        for row in subset:
            require(row['status'] == 'verified' and not row['reason'] and
                    row['evidence'] == {'driver': binding['driver'], 'lane': lane,
                                        'fixture_slots': mapping[row['obligation_id']]}, 'Gorilla obligation failed')
        if replay:
            require(launcher_lock() == plan['launchers'], 'Gorilla specialist replay launchers differ')
        for sid, row in fixtures.items():
            slot, sample = inputs[lane][sid]
            require(row['product_slot'] == sid and row['status'] == _wanted(slot), 'Gorilla fixture terminal differs')
            if lane == 'tv-batch':
                _audit_tv(folder, plan, slot, sample, row, allowed, replay=replay)
            else:
                require(state.inspect_evidence(folder, plan, slot, row, files, allowed), 'Gorilla lifecycle fixture failed')
                if replay:
                    state.audit_slot(folder, plan, slot, row)
        require(files.keys() == allowed, 'Gorilla has undeclared specialist files')
        statuses[lane] = retained['statuses']
    require(evidence['lanes'].keys() == expected_lanes and all(any(r['obligation_id'] in m for m in
            binding['obligation_slots'].values()) for r in rows), 'Gorilla audit scope differs')
    return {'verified_obligations': len(rows), 'fixture_statuses': statuses, 'replayed': replay}
