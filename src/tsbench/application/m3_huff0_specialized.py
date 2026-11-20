"""Execute and audit Huff0 named products within the M3 main ledger."""
from collections import Counter

from ..assets import ContractError, require
from ..planner import huff0_bmi2 as bmi2
from ..planner.huff0_execution import ROUTES, huff0_inputs
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import huff0_execution as native
from .batch_execution import _files

FOLDER = 'huff0-specialized'


def scope(binding, rows):
    required, condition = binding['required_slots'], binding['condition']
    require(all((r['selection'], r['route']) in ROUTES and
                (r['kind'] == 'required' and r['obligation_id'] in required or
                 r['kind'] == 'conditional' and r['obligation_id'] == condition['obligation_id']) for r in rows),
            'Huff0 specialist ledger scope differs')
    selected = {p for r in rows if r['kind'] == 'required' for p in required[r['obligation_id']]}
    if bmi2.KEY in binding and any(r['kind'] == 'conditional' for r in rows):
        selected.update(condition['slots'])
    return sorted(selected)


def ledger_products(binding, evidence):
    return [{'entry_kind': 'specialized_product', 'selection': 29, 'route': binding['slots'][p]['method'], **row}
            for p, row in evidence['fixtures'].items()]


def obligation(binding, row, products):
    conditional = row['kind'] == 'conditional'
    if conditional and bmi2.KEY not in binding:
        return {'status': 'not_run', 'reason': 'no recipe-matched portable Huff0 build bound to this plan', 'evidence': None}
    members = binding['condition']['slots'] if conditional else binding['required_slots'][row['obligation_id']]
    proof = {'driver': binding['driver'], 'fixture_slots': members}
    bad = [p for p in members if products[p]['status'] !=
           ('expected_rejection' if binding['slots'][p]['expected_status'] else 'verified')]
    if bad:
        return {'status': 'failed', 'reason': 'failed Huff0 products: ' + ', '.join(bad), 'evidence': proof}
    if conditional:
        try:
            evidence = native.condition_evidence([products[p] for p in members])
        except ContractError as exc:
            return {'status': 'failed', 'reason': str(exc), 'evidence': proof}
        return {'status': 'verified' if evidence['cpu_bmi2_available'] else 'hardware_pending',
                'reason': evidence['reason'], 'evidence': {**proof, 'runtime_comparison': evidence}}
    return {'status': 'verified', 'reason': '', 'evidence': proof}


def run_specialized(root, run, binding, rows, append):
    selected = scope(binding, rows)
    folder = run / FOLDER
    folder.mkdir()
    fixtures, _ = huff0_inputs(root, compare_bmi2=bmi2.KEY in binding)
    require(binding['slots'] == {p: slot for p, (slot, _) in fixtures.items()}, 'Huff0 specialist input drifted')
    products = {}
    try:
        require(launcher_lock() == binding['launchers'], 'Huff0 specialist isolation launchers drifted')
        stage_recovery(root, folder, binding['decoder'])
        if bmi2.KEY in binding:
            stage_recovery(root, folder, binding[bmi2.KEY]['decoder'], directory=bmi2.DIRECTORY)
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for k in ('logs', 'products', 'controls'):
            (folder / k).mkdir()
        for p in selected:
            slot, raw = fixtures[p]
            products[p] = native.run_slot(folder, binding, slot, raw, lambda: False)
        for row in ledger_products(binding, {'fixtures': products}):
            append(row)
        for row in rows:
            row.update(obligation(binding, row, products))
    return {'driver': binding['driver'], 'fixtures': products, 'files': _files(folder),
            'statuses': dict(Counter(p['status'] for p in products.values()))}


def audit_specialized(run, binding, rows, evidence, *, replay=False):
    folder = run / FOLDER
    products, files = evidence['fixtures'], evidence['files']
    decoders = {DIRECTORY: binding['decoder']}
    if bmi2.KEY in binding:
        decoders[bmi2.DIRECTORY] = binding[bmi2.KEY]['decoder']
    closure = {f'{directory}/{k}': {'path': f'{directory}/{k}', 'bytes': v['bytes'], 'sha256': v['sha256']}
               for directory, decoder in decoders.items() for k, v in decoder['files'].items()}
    require(evidence['driver'] == binding['driver'] and list(products) == scope(binding, rows) and files == _files(folder) and
            all(files.get(k) == v for k, v in closure.items()) and
            evidence['statuses'] == dict(Counter(p['status'] for p in products.values())), 'Huff0 specialist seal or closure differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'Huff0 specialist replay launchers drifted')
    allowed, restored = set(closure), []
    for p, product in products.items():
        slot = binding['slots'][p]
        require(product['product_slot'] == p, 'Huff0 stored product slot differs')
        passed = native.inspect_evidence(folder, binding, slot, product, files, allowed)
        if replay and passed and product['status'] == 'verified':
            restored.append(native.restore_slot(folder, binding, slot, product))
    require(allowed == files.keys(), 'Huff0 specialist evidence contains undeclared assets')
    for row in rows:
        require(all(row[k] == v for k, v in obligation(binding, row, products).items()), 'Huff0 obligation verdict differs')
    return {'statuses': evidence['statuses'], 'obligation_statuses': dict(Counter(r['status'] for r in rows)),
            'condition': next((r for r in rows if r['kind'] == 'conditional'), None), 'replayed': restored,
            'required_verified': sum(r['kind'] == 'required' and r['status'] == 'verified' for r in rows)}
