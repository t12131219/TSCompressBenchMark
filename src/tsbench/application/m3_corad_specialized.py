"""Run CORAD specialist products once and derive independent named verdicts."""
from collections import Counter

from ..assets import ContractError, require
from ..planner.corad_corpus import INFERENCE
from ..planner.corad_execution import QUALITY_CHECK, is_corad
from ..planner.m3_corad_specialized import fixture_inputs, route
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import corad_execution as inference
from . import corad_training_execution as training
from .batch_execution import _files

FOLDER = 'corad-specialized'


def scope(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['kind'] == 'required' and r['selection'] == 80 and r['obligation_id'] in mapping and
                (r['route'], r['check']) == (mapping[r['obligation_id']]['route'], mapping[r['obligation_id']]['check'])
                for r in rows), 'CORAD specialist ledger scope differs')
    return sorted({mapping[r['obligation_id']]['fixture_slot'] for r in rows})


def ledger_products(binding, evidence):
    return [{'entry_kind': 'specialized_product', 'selection': 80, 'route': route(binding['slots'][p]), **row}
            for p, row in evidence['fixtures'].items()]


def verdict(binding, row, products):
    record = binding['obligation_slots'][row['obligation_id']]
    p = record['fixture_slot']
    product = products[p]
    evidence = {'driver': binding['driver'], 'fixture_slot': p, 'case_inputs': record['case_inputs']}
    if product['status'] != 'verified':
        return {'status': 'failed', 'reason': f'CORAD specialist product {product["status"]}: {product["reason"]}',
                'evidence': evidence}
    if (row['route'], row['check']) == (INFERENCE, QUALITY_CHECK):
        assessment = product['corad']
        evidence['quality_gate'] = assessment['quality_gate']
        if not assessment['quality_comparable']:
            return {'status': 'quality_rejected', 'reason': 'predeclared held-out original-domain bounds exceeded',
                    'evidence': evidence}
    return {'status': 'verified', 'reason': '', 'evidence': evidence}


def run_specialized(root, run, binding, rows, append):
    folder = run / FOLDER
    folder.mkdir()
    selected = scope(binding, rows)
    products = {}
    try:
        require(launcher_lock() == binding['launchers'], 'CORAD specialist isolation launchers drifted')
        fixtures, _ = fixture_inputs(root)
        require(binding['slots'] == {p: s for p, (s, _) in fixtures.items()}, 'CORAD specialist fixture drifted')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for r in rows:
            r.update(status='dependency_failed', reason=str(exc) or type(exc).__name__)
    else:
        for k in ('logs', 'products'):
            (folder/k).mkdir()
        for p in selected:
            slot, sample = fixtures[p]
            runner = inference if is_corad(slot) else training
            products[p] = runner.run_slot(folder, binding, slot, sample, lambda: False)
        for row in ledger_products(binding, {'fixtures': products}):
            append(row)
        for row in rows:
            row.update(verdict(binding, row, products))
    return {'driver': binding['driver'], 'fixtures': products, 'files': _files(folder),
            'statuses': dict(Counter(r['status'] for r in products.values()))}


def audit_specialized(run, binding, rows, evidence, *, replay=False):
    folder = run / FOLDER
    products, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{p}': {'path': f'{DIRECTORY}/{p}', 'bytes': v['bytes'], 'sha256': v['sha256']}
               for p, v in binding['decoder']['files'].items()}
    require(evidence['driver'] == binding['driver'] and list(products) == scope(binding, rows) and files == _files(folder) and
            all(files.get(p) == v for p, v in closure.items()) and
            evidence['statuses'] == dict(Counter(r['status'] for r in products.values())), 'CORAD specialist seal or closure differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'CORAD specialist replay launchers drifted')
    allowed, restored, sessions = set(closure), {}, set()
    for p, product in products.items():
        slot = binding['slots'][p]
        require(product['product_slot'] == p, 'CORAD specialist product slot differs')
        runner = inference if is_corad(slot) else training
        passed = runner.inspect_evidence(folder, binding, slot, product, files, allowed)
        for op in product['operations']:
            if op['session_id'] is not None:
                require(op['session_id'] not in sessions, 'CORAD specialist reused a process session')
                sessions.add(op['session_id'])
        if replay and passed:
            restored[route(slot)] = runner.audit_slot(folder, binding, slot, product)
    require(allowed == files.keys(), 'CORAD specialist evidence contains undeclared assets')
    for row in rows:
        require(all(row[k] == v for k,v in verdict(binding, row, products).items()),
                'CORAD specialist obligation terminal differs from product evidence')
    return {'products': evidence['statuses'], 'obligations': dict(Counter(r['status'] for r in rows)),
            'quality_gate': next((r for r in rows if (r['route'], r['check']) == (INFERENCE, QUALITY_CHECK)), None),
            'replayed': restored}
