"""Execute and replay ZFP specialist products under the unified run/ledger."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import ContractError, require, verify_asset
from ..planner import zfp_execution as spec
from ..planner.m3_zfp_specialized import inputs
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import batch_execution as batch, zfp_execution as native


def _selected(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['selection'] == 31 and r['obligation_id'] in mapping for r in rows), 'ZFP obligation scope differs')
    return sorted({sid for r in rows for sid in mapping[r['obligation_id']]})


def _expected(slot, row):
    return row['status'] == ('expected_rejection' if slot.get('expected_status') else 'verified')


def _evidence(binding, row, products):
    ids = binding['obligation_slots'][row['obligation_id']]
    evidence = {'driver': binding['driver'], 'fixture_slots': ids}
    if row['kind'] == 'conditional':
        sid, = ids
        observed = products[sid]['zfp']['profiles']
        evidence['native_work'] = {'encode_participants': {m: len(p['encode_block_work']) for m, p in observed.items()},
                                   'decode_on_caller': all(len(p['decode_block_work']) == 1 and
                                       p['decode_block_work'][0]['tid'] == p['caller_tid'] for p in observed.values()),
                                   'same_payload': products[sid]['zfp']['same_payload']}
        require(evidence['native_work'] == {'encode_participants': spec.THREADS, 'decode_on_caller': True, 'same_payload': True},
                'ZFP condition needs observed two-thread native block work, same field and detached serial recovery')
    return evidence


def run_specialized(root, run, binding, rows, append):
    folder = run / 'zfp-specialized'
    folder.mkdir()
    products, _ = inputs(root)
    require(binding['slots'] == {sid: slot for sid, (slot, _) in products.items()}, 'ZFP specialist fixture drift')
    selected = _selected(binding, rows)
    actual = {}
    try:
        require(launcher_lock() == binding['launchers'], 'ZFP isolation launchers changed')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for name in ('logs', 'products'):
            (folder / name).mkdir()
        for sid in selected:
            slot, sample = products[sid]
            execute = native.run_slot if spec.is_zfp(slot) else batch._case
            result = actual[sid] = execute(folder, binding, slot, sample, lambda: False)
            append({'entry_kind': 'specialized_product', 'selection': 31, **result})
        for row in rows:
            ids = binding['obligation_slots'][row['obligation_id']]
            bad = [f"{sid}: {actual[sid]['status']} ({actual[sid]['reason']})"
                   for sid in ids if not _expected(binding['slots'][sid], actual[sid])]
            if bad:
                row.update(status='failed', reason='; '.join(bad),
                           evidence={'driver': binding['driver'], 'fixture_slots': ids})
            else:
                row.update(status='verified', reason='', evidence=_evidence(binding, row, actual))
    return {'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': actual,
            'statuses': dict(Counter(row['status'] for row in actual.values())), 'files': batch._files(folder)}


def _audit_abi(folder, binding, slot, sample, row, files, allowed, replay):
    sid = slot['product_slot']
    logs = folder / 'logs' / sid
    ops = row['operations']
    labels = batch._linear_order(binding, slot)
    require([op['operation'] for op in ops] == labels and len({op['session_id'] for op in ops}) == len(ops),
            'ZFP ABI specialist isolation or operation order differs')
    for label in labels:
        for suffix in ('stdout', 'stderr'):
            name = f'logs/{sid}/{label}.{suffix}'
            require(files[name]['bytes'] <= binding['limits']['file_bytes'], 'ZFP specialist log outside limits')
            allowed.add(name)
    status = slot['expected_status']
    if status:
        require(batch._rejected_log(ops[0], logs, labels[0], status) and row['reason'] == batch.INPUT_STATUS[status] and
                all(row[k] is None for k in ('artifact', 'restored', 'payload_validation', 'control_payload', 'decoder_rejections')),
                'ZFP ABI specialist expected refusal differs')
    else:
        require(not row['reason'] and all(batch._completed(op) for op in ops if op['operation'] not in slot['reject_decodes']),
                'ZFP ABI specialist execution incomplete')
        relative = f'products/{sid}.bmk'
        require(row['artifact'] == files[relative] and row['control_payload'] is None, 'ZFP ABI retained reference differs')
        allowed.add(relative)
        frame = verify_asset(folder, row['artifact'])
        require(row['payload_validation'] == batch._inspect(frame, slot, sample.columns[0]) and row['restored'] == slot['original'],
                'ZFP ABI specialist envelope or recovery differs')
        batch._verify_linear(binding, row, slot, folder, row['artifact'], None)
    if replay:
        with TemporaryDirectory(prefix='m3-zfp-abi-audit-') as tmp:
            work = Path(tmp)
            if status:
                ins = {k: work / k for k in ('schema', 'v')}
                ins['schema'].write_bytes(sample.schema)
                ins['v'].write_bytes(sample.columns[0])
                out, op = batch._encode(folder / DIRECTORY, binding, slot, work, work, ins, lambda: False)
                require(batch._rejected_log(op, work, labels[0], status) and not list(out.iterdir()), 'ZFP ABI refusal did not replay')
            else:
                require(batch._restore(folder / DIRECTORY, binding, slot, frame, work, work, lambda: False) == row['restored'] and
                        batch._rejected_decodes(folder / DIRECTORY, binding, slot, frame, work, lambda: False) == row['decoder_rejections'],
                        'ZFP ABI detached replay or bad-frame rejection differs')
    return {'product_slot': sid, 'status': row['status'], 'replayed': replay}


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    folder = run / 'zfp-specialized'
    fixtures, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{key}': {'path': f'{DIRECTORY}/{key}', 'bytes': row['bytes'], 'sha256': row['sha256']}
               for key, row in binding['decoder']['files'].items()}
    require(evidence['driver'] == binding['driver'] and evidence['recovery_id'] == binding['decoder']['recovery_id'] and
            set(fixtures) == set(_selected(binding, rows)) and files == batch._files(folder) and
            {k: v for k, v in files.items() if k.startswith(DIRECTORY + '/')} == closure and
            evidence['statuses'] == dict(Counter(f['status'] for f in fixtures.values())), 'ZFP specialist evidence differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'ZFP audit isolation launchers changed')
    allowed, replayed = set(closure), []
    products, _ = inputs(root)
    for sid, row in fixtures.items():
        slot, sample = products[sid]
        require(row['product_slot'] == sid and _expected(slot, row), 'ZFP specialist product terminal differs')
        if spec.is_zfp(slot):
            require(native.inspect_evidence(folder, binding, slot, row, files, allowed), 'unverified ZFP native specialist product')
            if replay:
                replayed.append(native.audit_slot(folder, binding, slot, row))
        else:
            item = _audit_abi(folder, binding, slot, sample, row, files, allowed, replay)
            if replay:
                replayed.append(item)
    require(files.keys() == allowed, 'ZFP specialist has undeclared retained files')
    for row in rows:
        require(row['status'] == 'verified' and not row['reason'] and row['evidence'] == _evidence(binding, row, fixtures),
                'ZFP obligation lacks verified evidence')
    return {'verified_obligations': len(rows), 'fixture_statuses': evidence['statuses'], 'replayed': replayed}
