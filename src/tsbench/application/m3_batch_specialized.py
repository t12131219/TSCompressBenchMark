"""Execute and replay frozen M3 batch and wrapped-page products."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import ContractError, require, verify_asset
from ..planner.linear_batch import wants_pcodec_direct, wants_xz_direct
from ..planner.m3_batch_specialized import FAMILIES, inputs
from ..planner.pcodec_pages import PROTOCOL
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import batch_execution as batch, pcodec_pages as wrapped


def _wrapped(slot):
    return slot.get('protocol') == PROTOCOL


def _expected(slot):
    return 'expected_rejection' if slot.get('expected_status') else 'verified'


def folder_name(binding):
    return binding['family'].replace('_', '-') + '-specialized'


def scope(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['kind'] == 'required' and r['obligation_id'] in mapping and
                all(r[k] == mapping[r['obligation_id']][k] for k in ('selection', 'route', 'check'))
                for r in rows), 'M3 batch specialist ledger scope differs')
    return sorted({p for r in rows for p in mapping[r['obligation_id']]['slots']})


def ledger_products(binding, report):
    by_method = {v: k for k, v in FAMILIES[binding['family']][1].items()}
    for p, row in report['fixtures'].items():
        selection, route = by_method[binding['slots'][p]['method']]
        yield {'entry_kind': 'specialized_product', 'selection': selection, 'route': route, **row}


def verdict(binding, row, actual):
    ref = binding['obligation_slots'][row['obligation_id']]
    ev = {'driver': binding['driver'], 'fixture_slots': ref['slots'], 'case_inputs': ref['case_inputs']}
    failed = {p: actual[p]['status'] for p in ref['slots'] if actual[p]['status'] != _expected(binding['slots'][p])}
    if failed:
        return {'status': 'failed', 'reason': 'M3 batch specialist product did not match its contract',
                'evidence': {**ev, 'nonpass_products': failed}}
    return {'status': 'verified', 'reason': '', 'evidence': ev}


def run_specialized(root, run, binding, rows, append):
    folder = run / folder_name(binding)
    folder.mkdir()
    actual, selected = {}, scope(binding, rows)
    try:
        require(launcher_lock() == binding['launchers'], 'M3 batch isolation launchers changed')
        products, _ = inputs(root, binding['family'])
        require(binding['slots'] == {p: s for p, (s, _) in products.items()}, 'M3 batch specialist fixture drift')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc) or type(exc).__name__)
    else:
        for name in ('logs', 'products', 'controls'):
            (folder / name).mkdir()
        for p in selected:
            slot, sample = products[p]
            execute = wrapped.run_slot if _wrapped(slot) else batch._case
            actual[p] = execute(folder, binding, slot, sample, lambda: False)
        for row in ledger_products(binding, {'fixtures': actual}):
            append(row)
        for row in rows:
            row.update(verdict(binding, row, actual))
    return {'driver': binding['driver'], 'fixtures': actual,
            'statuses': dict(Counter(r['status'] for r in actual.values())), 'files': batch._files(folder)}


def _audit_abi(folder, binding, slot, row, files, allowed):
    p = slot['product_slot']
    logs = folder / 'logs' / p
    ops, labels = row['operations'], batch._linear_order(binding, slot)
    status, direct = slot['expected_status'], wants_pcodec_direct(binding, slot)
    require([op['operation'] for op in ops] == labels, 'M3 batch operation order differs')
    for label, op in zip(labels, ops, strict=True):
        negative = status if label == batch.ENCODE else batch._decode_status(slot, label) if label in slot['reject_decodes'] else 0
        require(batch._rejected_log(op, logs, label, negative) if negative else batch._completed(op),
                'M3 batch specialist operation terminal differs')
        for suffix in ('stdout', 'stderr'):
            path = f'logs/{p}/{label}.{suffix}'
            require(files[path]['bytes'] <= binding['limits']['file_bytes'], 'M3 batch specialist log exceeds limit')
            allowed.add(path)
    if status:
        require(row['reason'] == batch.INPUT_STATUS[status] and all(row[k] is None for k in
                ('artifact', 'restored', 'payload_validation', 'control_payload', 'decoder_rejections', 'upstream_restored')) and
                (not direct or row['pcodec_control'] == batch._pcodec_direct_log(slot, None, logs)),
                'M3 batch input refusal evidence differs')
        return
    path = f'products/{p}.bmk'
    require(not row['reason'] and row['artifact'] == files.get(path), 'M3 batch artifact binding differs')
    artifact = verify_asset(folder, row['artifact'])
    allowed.add(path)
    require(row['payload_validation'] == batch._inspect(artifact, slot) and row['restored'] == slot['original'],
            'M3 batch retained frame or recovery differs')
    native = row['control_payload']
    if slot['upstream_zstd']:
        path = f'controls/{p}.zst'
        require(native is not None and native == files.get(path) and 6 <= native['bytes'] <= 66000,
                'M3 upstream Zstd frame binding differs')
        allowed.add(path)
    else:
        require(native is None, 'unexpected direct payload file')
    batch._verify_linear(binding, row, slot, folder, row['artifact'], native)


def _replay_abi(folder, binding, slot, sample, row):
    with TemporaryDirectory(prefix='m3-batch-abi-audit-') as tmp:
        work, bundle = Path(tmp), folder / DIRECTORY
        stop = lambda: False
        if slot['expected_status']:
            ins = {k: work / k for k in ('schema', 'v')}
            ins['schema'].write_bytes(sample.schema)
            ins['v'].write_bytes(sample.columns[0])
            out, op = batch._encode(bundle, binding, slot, work, work, ins, stop)
            require(batch._rejected_log(op, work, batch.ENCODE, slot['expected_status']) and not list(out.iterdir()),
                    'M3 batch ABI refusal did not replay')
            if wants_pcodec_direct(binding, slot):
                require(batch._pcodec_control(bundle, binding, slot, ins['v'], None, work, stop) == row['pcodec_control'],
                        'M3 batch native input refusal did not replay')
            return
        frame = verify_asset(folder, row['artifact'])
        require(batch._restore(bundle, binding, slot, frame, work, work, stop) == row['restored'],
                'M3 batch detached recovery did not replay')
        data = work / 'out' / 'v'
        if wants_pcodec_direct(binding, slot):
            require(batch._pcodec_control(bundle, binding, slot, data, frame, work, stop) == row['pcodec_control'],
                    'M3 batch pcodec cross-direction control did not replay')
        if wants_xz_direct(binding, slot):
            require(batch._xz_control(bundle, binding, slot, data, frame, work, stop) == row['xz_control'],
                    'M3 batch XZ direct control did not replay')
        if slot['reject_decodes']:
            require(batch._rejected_decodes(bundle, binding, slot, frame, work, stop) == row['decoder_rejections'],
                    'M3 batch malformed frame refusal did not replay')
        if slot['upstream_zstd']:
            control = verify_asset(folder, row['control_payload'])
            require(batch._upstream_restore(bundle, binding, slot, frame, control, work, stop) == row['upstream_restored'],
                    'M3 batch upstream Zstd frame recovery did not replay')


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    folder = run / folder_name(binding)
    actual, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{p}': {'path': f'{DIRECTORY}/{p}', 'bytes': v['bytes'], 'sha256': v['sha256']}
               for p, v in binding['decoder']['files'].items()}
    require(evidence['driver'] == binding['driver'] and list(actual) == scope(binding, rows) and files == batch._files(folder) and
            all(files.get(p) == v for p, v in closure.items()) and
            evidence['statuses'] == dict(Counter(r['status'] for r in actual.values())), 'M3 batch specialist evidence closure differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'M3 batch audit isolation launchers changed')
    products, _ = inputs(root, binding['family'])
    allowed, sessions, verified = set(closure), set(), []
    for p, row in actual.items():
        slot, sample = products[p]
        require(row['product_slot'] == p and slot == binding['slots'][p] and row['status'] == _expected(slot),
                'M3 batch specialist product differs from its frozen terminal')
        for op in row['operations']:
            session = op['session_id']
            require(session and session not in sessions, 'M3 batch specialist reused an operation session')
            sessions.add(session)
        if _wrapped(slot):
            require(wrapped.inspect_evidence(folder, binding, slot, row, files, allowed), 'M3 wrapped specialist did not verify')
            if replay:
                wrapped.restore_slot(folder, binding, slot, row)
        else:
            _audit_abi(folder, binding, slot, row, files, allowed)
            if replay:
                _replay_abi(folder, binding, slot, sample, row)
        verified.append({'product_slot': p, 'method': slot['method'], 'status': row['status']})
    require(allowed == files.keys(), 'M3 batch specialist includes undeclared sealed files')
    for row in rows:
        require(all(row[k] == v for k, v in verdict(binding, row, actual).items()), 'M3 batch obligation verdict differs')
    return {'products': evidence['statuses'], 'obligations': dict(Counter(r['status'] for r in rows)),
            'audited_products': verified, 'independently_replayed': replay, 'distinct_operation_sessions': len(sessions)}
