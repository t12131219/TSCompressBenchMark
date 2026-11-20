"""Audit amended CORAD terminals, bytes and detached frame-only recoveries."""
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import canonical_bytes, require
from ..planner.corad_execution import COLS, is_corad
from ..planner.m3_corad_specialized import route
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import launcher_lock
from . import corad_execution as old, corad_training_execution as training, m3_corad_specialized_v2 as amended
from .batch_execution import _files
from .m3_corad_specialized import FOLDER, scope


def _audit_inference(folder, binding, slot, policy, row, files, allowed, replay):
    sid = slot['product_slot']
    recipes = amended._recipes(slot, policy)
    ops = row['operations']
    require([op['operation'] for op in ops] == list(recipes)[:len(ops)] and
            all(old._finish(recipes[op['operation']], op) for op in ops[:-1]), 'CORAD amended operation prefix differs')
    for op in ops:
        if op['pid'] is not None:
            names = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
            require(names <= files.keys() and all(files[p]['bytes'] <= old.FILE_CEILING for p in names),
                    'CORAD amended logs incomplete')
            allowed.update(names)
    if row['status'] != 'verified':
        require(row['status'] in old.NONPASS and row['reason'] and row['corad'] is None and not row['parts'],
                'invalid failed CORAD amended terminal')
        return None
    expected = amended._parts(slot, policy)
    require(len(ops) == len(recipes) and row['parts'].keys() == expected.keys() and not row['reason'],
            'incomplete CORAD amended run')
    for k,ref in row['parts'].items():
        p = f'products/{sid}/{k}'
        require(ref == files[p] and ref['bytes'] <= expected[k], 'CORAD amended product identity differs')
        allowed.add(p)
    products = folder/'products'/sid
    got = amended._evaluate(slot, policy, products, ops, folder/'logs'/sid)
    require(canonical_bytes(got) == canonical_bytes(row['corad']), 'CORAD amended evidence does not recompute')
    if replay:
        parts = {k:old._read(products/k, cap) for k,cap in expected.items()}
        selected = [k for k in recipes if k.endswith('-restore') or k.startswith('restore-') or k=='bad-reference']
        with TemporaryDirectory(prefix='tsbench-corad-amended-audit-') as td:
            tmp = Path(td)
            for label in selected:
                mounts, want = amended._io(slot, policy, parts, label)
                require(set(mounts) == {'frame'}, 'CORAD audit decoder depends on data or deployment')
                require(old._invoke(folder, binding, slot, tmp, label, recipes[label], mounts, tmp, lambda:False, []) == want,
                        'CORAD amended isolated replay differs')
        return {'detached_operations': selected, 'quality_gate': got['quality_gate'], 'controls': got['reference_controls'],
                'bad_reference': got['rejections']['bad-reference']}
    return None


def audit_specialized(run, binding, amendment, rows, evidence, *, replay=False):
    folder = run/FOLDER
    policy = amendment['contract']
    products, files = evidence['fixtures'], evidence['files']
    closure = {f'{DIRECTORY}/{p}':{'path':f'{DIRECTORY}/{p}', 'bytes':v['bytes'], 'sha256':v['sha256']}
               for p,v in binding['decoder']['files'].items()}
    require(evidence['driver'] == amendment['driver'] and evidence['amendment_id'] == policy['amendment_id'] and
            list(products) == scope(binding, rows) and files == _files(folder) and
            all(files.get(p) == v for p,v in closure.items()) and
            evidence['statuses'] == dict(Counter(p['status'] for p in products.values())), 'CORAD amended inventory differs')
    if replay:
        require(launcher_lock() == binding['launchers'], 'CORAD amended replay launcher changed')
    allowed,sessions,restored = set(closure),set(),{}
    for sid,row in products.items():
        slot = binding['slots'][sid]
        require(row['product_slot'] == sid, 'CORAD amended product identity differs')
        if is_corad(slot):
            result = _audit_inference(folder,binding,slot,policy,row,files,allowed,replay)
            if result is not None:
                restored[route(slot)] = result
        elif training.inspect_evidence(folder,binding,slot,row,files,allowed) and replay:
            restored[route(slot)] = training.audit_slot(folder,binding,slot,row)
        for op in row['operations']:
            sess = op['session_id']
            if sess is not None:
                require(sess not in sessions, 'CORAD amended replay reused a process')
                sessions.add(sess)
    require(files.keys() == allowed, 'CORAD amended unaccounted product')
    for row in rows:
        require(all(row[k] == v for k,v in amended.verdict(binding,amendment,row,products).items()),
                'CORAD amended verdict differs')
    return {'amendment_id':policy['amendment_id'], 'products':evidence['statuses'],
            'obligations':dict(Counter(r['status'] for r in rows)), 'replayed':restored}
