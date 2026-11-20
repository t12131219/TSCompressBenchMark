"""Execute and independently audit the ALP products in the M3 main ledger."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import ContractError, require, verify_asset
from ..planner import alp_decode as spec
from ..planner.m3_alp_specialized import inputs, route
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import alp_decode as native, batch_execution as batch

FOLDER = 'alp-specialized'


def scope(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['selection'] == 9 and r['obligation_id'] in mapping and
                all(mapping[r['obligation_id']][k] == r[k] for k in ('route', 'check', 'kind'))
                for r in rows), 'ALP specialist ledger scope differs')
    return sorted({p for r in rows for p in mapping[r['obligation_id']]['slots']})


def ledger_products(binding, evidence):
    return [{'entry_kind': 'specialized_product', 'selection': 9, 'route': route(binding['slots'][p]), **row}
            for p, row in evidence['fixtures'].items()]


def verdict(binding, row, products):
    frozen = binding['obligation_slots'][row['obligation_id']]
    ids = frozen['slots']
    ev = {'driver': binding['driver'], 'fixture_slots': ids}
    failed = {p: products[p]['status'] for p in ids if products[p]['status'] != 'verified'}
    if failed:
        return {'status': 'failed', 'reason': 'ALP specialist product did not verify',
                'evidence': {**ev, 'nonpass_products': failed}}
    if row['kind'] == 'required':
        return {'status': 'verified', 'reason': '', 'evidence': {**ev, 'case_inputs': frozen['case_inputs']}}
    p, = ids
    c = frozen['condition']['criteria']
    state = native.condition_state(c, products[p])
    requested = products[p]['decode_backends']['requests']
    ev.update(condition=frozen['condition'], observed_requests={r: requested[r] for r in c['requests']})
    return {'status': 'verified' if state == 'verified_candidate' else state,
            'reason': '' if state == 'verified_candidate' else requested[c['backend']]['capability']['reason'],
            'evidence': ev}


def run_specialized(root, run, binding, rows, append):
    folder = run / FOLDER
    folder.mkdir()
    actual, selected = {}, scope(binding, rows)
    try:
        require(launcher_lock() == binding['launchers'], 'ALP specialist isolation launchers changed')
        products, _ = inputs(root)
        require(binding['slots'] == {p: s for p, (s, _) in products.items()}, 'ALP specialist fixture drift')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc) or type(exc).__name__)
    else:
        for name in ('logs', 'products'):
            (folder / name).mkdir()
        for p in selected:
            slot, sample = products[p]
            execute = native.run_slot if spec.is_decode(slot) else batch._case
            actual[p] = execute(folder, binding, slot, sample, lambda: False)
        for row in ledger_products(binding, {'fixtures': actual}):
            append(row)
        for row in rows:
            row.update(verdict(binding, row, actual))
    return {'driver': binding['driver'], 'fixtures': actual,
            'statuses': dict(Counter(r['status'] for r in actual.values())), 'files': batch._files(folder)}


def _audit_abi(folder, binding, slot, sample, row, files, allowed, replay):
    p = slot['product_slot']
    logs = folder / 'logs' / p
    labels = batch._linear_order(binding, slot)
    ops = row['operations']
    require([op['operation'] for op in ops] == labels and all(
        batch._rejected_log(op, logs, label, batch._decode_status(slot, label)) if label in slot['reject_decodes']
        else batch._completed(op) for label, op in zip(labels, ops, strict=True)), 'ALP ABI operation terminal differs')
    for label in labels:
        for suffix in ('stdout', 'stderr'):
            path = f'logs/{p}/{label}.{suffix}'
            require(files[path]['bytes'] <= binding['limits']['file_bytes'], 'ALP ABI operation log exceeds limit')
            allowed.add(path)
    path = f'products/{p}.bmk'
    require(row['status'] == 'verified' and not row['reason'] and row['artifact'] == files.get(path) and
            row['control_payload'] is None, 'ALP ABI product is not verified')
    allowed.add(path)
    artifact = verify_asset(folder, row['artifact'])
    data, = sample.columns
    require(row['payload_validation'] == batch._inspect(artifact, slot, data) and row['restored'] == slot['original'],
            'ALP ABI retained wire or recovery differs')
    batch._verify_linear(binding, row, slot, folder, row['artifact'], None)
    if replay:
        with TemporaryDirectory(prefix='m3-alp-abi-audit-') as tmp:
            work, bundle = Path(tmp), folder / DIRECTORY
            require(batch._restore(bundle, binding, slot, artifact, work, work, lambda: False) == row['restored'] and
                    batch._rejected_decodes(bundle, binding, slot, artifact, work, lambda: False) == (row['decoder_rejections'] or {}),
                    'ALP ABI detached replay or malformed side-info rejection differs')
            if batch._requires_fenv(binding, slot):
                raw = work / 'raw'
                raw.write_bytes(data)
                require(batch._fenv(bundle, binding, slot, raw, artifact, work, lambda: False) == row['fenv_control'],
                        'ALP rounding-mode rejection did not replay')


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    folder = run / FOLDER
    actual, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{p}': {'path': f'{DIRECTORY}/{p}', **{k: v[k] for k in ('bytes', 'sha256')}}
               for p, v in binding['decoder']['files'].items()}
    require(evidence['driver'] == binding['driver'] and list(actual) == scope(binding, rows) and files == batch._files(folder) and
            all(files.get(p) == v for p, v in closure.items()) and
            evidence['statuses'] == dict(Counter(r['status'] for r in actual.values())), 'ALP specialist closure or product census differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'ALP audit isolation launchers changed')
    products, _ = inputs(root)
    allowed, sessions, replayed = set(closure), set(), []
    for p, row in actual.items():
        slot, sample = products[p]
        require(row['product_slot'] == p and slot == binding['slots'][p], 'ALP specialist product slot differs')
        for op in row['operations']:
            require(op['session_id'] and op['session_id'] not in sessions, 'ALP specialist reused an operation session')
            sessions.add(op['session_id'])
        if spec.is_decode(slot):
            require(native.inspect_evidence(folder, binding, slot, row, files, allowed), 'ALP direct product did not verify')
            if replay:
                native.audit_slot(folder, binding, slot, row)
        else:
            _audit_abi(folder, binding, slot, sample, row, files, allowed, replay)
        if replay:
            replayed.append({'product_slot': p, 'route': route(slot)})
    require(allowed == files.keys(), 'ALP specialist has undeclared retained files')
    for row in rows:
        require(all(row[k] == v for k, v in verdict(binding, row, actual).items()), 'ALP obligation verdict differs from execution')
    return {'products': evidence['statuses'], 'obligations': dict(Counter(r['status'] for r in rows)),
            'conditions': [r for r in rows if r['kind'] == 'conditional'], 'replayed': replayed}
