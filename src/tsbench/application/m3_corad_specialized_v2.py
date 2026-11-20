"""Execute the amended CORAD inference recipe; retain legacy training evidence."""
from collections import Counter
from pathlib import Path
from struct import pack_into
from tempfile import TemporaryDirectory

from ..assets import canonical_bytes, require
from ..corad_quality import assess
from ..planner.corad_deployment import NATIVE
from ..planner.corad_execution import COLS, identity, is_corad, split_deployment, steps
from ..planner.m3_corad_specialized import fixture_inputs, route
from ..qualification.corad_inference import HEADER, frame_evidence, verify_bounds
from ..qualification.corad_wire import interpret
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import corad_execution as old, corad_training_execution as training, m3_corad_specialized as legacy
from .batch_execution import _files
from .smoke import _ref

FOLDER = legacy.FOLDER


def _frame(slot, frame, raw, spec):
    src = slot['bundle']['input']
    # The old common parser still validates the entire frame, deployment, charge, original and tail.
    # Its legacy branch co-occurrence rule is not part of the amended quality receipt.
    original, restored, doc = frame_evidence(frame, raw, src, {**spec, 'case': 'quality-only'} if spec['case']=='held-out' else spec)
    if spec['case'] == 'held-out':
        doc.update(case='held-out', pinned_decode={**doc['encode'], 'operation': 'decode'})
    return original, restored, doc


def _recipes(slot, policy):
    control_jobs = {}
    for case in policy['controls']:
        name = case['id']
        probe = steps({'deployments': [case['deployment']]*2, 'bundle': {'frames': [{'case': 'held-out'}]}})
        control_jobs.update({name+'-encode': probe['encode-0'], name+'-restore': probe['restore-0']})
    return {**control_jobs, **steps(slot)}


def _control(case, frame):
    raw = {key: bytes.fromhex(case['inputs'][key]) for key in ('schema', *COLS)}
    schema = raw['schema']; start = HEADER.size+len(schema)
    payload = frame[start:]
    require(HEADER.unpack_from(frame) == (b'BMKCRD\x01\0', len(schema), 0, len(payload)) and
            frame[HEADER.size:start] == schema, 'CORAD control frame envelope differs')
    restored, sections, embedded = interpret(payload)
    _, model = split_deployment(case['deployment'])
    desc = NATIVE.unpack_from(payload)
    require(desc[1:7] == (7, 3, 4, 4, 2, 0.9) and model[NATIVE.size:] == embedded and
            (sections['references'], sections['sparse_records'], sections['tail_bytes']) ==
            (case['expected_references'], case['expected_sparse_records'], case['tail_bytes']) and
            restored == b''.join(raw[k] for k in COLS), 'CORAD exact reference control differs')
    decoded = {'schema': schema, **{k: restored[i*56:(i+1)*56] for i,k in enumerate(COLS)}}
    encode = {'backend': 'corad-c-frozen', 'mode': 'batch', 'operation': 'encode', 'threads': 1,
              'columns': 3, 'rows': 7, 'tricklet': 4, 'fallback': False, 'embedded_model_bytes': len(embedded),
              'tail_rows': 3, 'external_deployment_loaded': True}
    desc = {'columns': [{'dtype': 10, 'count': 7}]*3}
    return raw, decoded, encode, desc, sections


def _io(slot, policy, parts, label):
    for case in policy['controls']:
        name = case['id']
        if label == name+'-encode':
            frame = parts.get(name+'.bmk')
            return {k: bytes.fromhex(case['inputs'][k]) for k in ('schema', *COLS)}, None if frame is None else {'frame': frame}
        if label == name+'-restore':
            frame = parts[name+'.bmk']
            return {'frame': frame}, _control(case, frame)[1]
    if label == 'bad-reference':
        case = next(c for c in policy['controls'] if c['id']=='safe-reference')
        frame = parts['safe-reference.bmk']
        start = HEADER.size+len(bytes.fromhex(case['inputs']['schema']))
        offset, col = _control(case, frame)[4]['first_reference']
        mutated = bytearray(frame)
        pack_into('<H', mutated, start+offset, col)
        return {'frame': bytes(mutated)}, {}
    alias = {**slot, 'bundle': {**slot['bundle'], 'frames': [
        {**f, 'case': 'quality-only'} if f['case']=='held-out' else f for f in slot['bundle']['frames']]}}
    return old._io(alias, parts, label)


def _parts(slot, policy):
    return {**slot['parts'], **{c['id']+'.bmk': 4096 for c in policy['controls']}}


def _evaluate(slot, policy, folder, ops, logs):
    parts = {k: old._read(folder/k, cap) for k,cap in _parts(slot, policy).items()}
    b = slot['bundle']; raw = old._input_extents(slot, parts); src = b['input']; quality = b['quality_policy']
    require(quality['policy_id'] == policy['quality_policy_id'], 'CORAD amendment changed original quality limits')
    bounds = verify_bounds(folder, quality, src['columns'], b['window'])
    evidence, heldout, diagnostics, refusals, controls = [], {}, {}, {}, {}
    for case in policy['controls']:
        name = case['id']; frame = parts[name+'.bmk']
        _, decoded, enc, desc, sect = _control(case, frame)
        diagnostics[name+'-encode'] = [enc]
        diagnostics[name+'-restore'] = [desc, {**enc, 'operation': 'decode', 'external_deployment_loaded': False}]
        controls[name] = {'frame': identity(frame), 'restored': identity(b''.join(decoded[k] for k in COLS)),
                          **{k:sect[k] for k in ('references','sparse_records','tail_bytes')}}
    for i,spec in enumerate(b['frames']):
        original, restored, doc = _frame(slot, parts[spec['path']], raw, spec)
        diagnostics.update({f'encode-{i}':[doc['encode']],f'native-{i}':[],f'restore-{i}':[doc['descriptor'],doc['decode']]})
        if spec['case']=='held-out':
            heldout[spec['route']] = assess(bounds,original,restored)
            diagnostics[f'pinned-{i}']=[doc['descriptor'],doc['pinned_decode']]
        evidence.append(doc)
    for (label,step),op in zip(_recipes(slot, policy).items(), ops, strict=True):
        inputs, outputs = _io(slot, policy, parts, label)
        require(op['operation'] == label and old._finish(step, op) and op['input_mounts'] == {k:identity(v) for k,v in inputs.items()} and
                op['outputs'] == {k:identity(v) for k,v in outputs.items()}, f'CORAD amended mount or output differs: {label}')
        doc = old._log(logs,label,step)
        if step['reject']:
            refusals[label] = doc
        else:
            require(canonical_bytes(doc) == canonical_bytes(diagnostics[label]), f'CORAD amended descriptor differs: {label}')
    require(refusals.keys() == b['rejections'].keys(), 'CORAD amended refusal denominator differs')
    return {'frames':evidence,'reference_controls':controls,'rejections':refusals,
            'quality_gate':{'policy_id':quality['policy_id'],'heldout':heldout},'functional_restoration':True,
            'quality_comparable':all(v['decision']=='passed' for v in heldout.values()), 'amendment_id':policy['amendment_id']}


def run_slot(folder, binding, slot, sample, policy):
    sid = slot['product_slot']; logs = folder/'logs'/sid; logs.mkdir()
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':[],'parts':{},'corad':None}
    b = slot['bundle']; original,calibration = sample.columns
    parts = {b['input']['path']:original,b['quality_policy']['calibration']['path']:calibration}
    try:
        with TemporaryDirectory(prefix='tsbench-corad-guard-') as td:
            work = Path(td); products = work/'parts'; products.mkdir()
            for label,step in _recipes(slot, policy).items():
                inputs, expected = _io(slot, policy, parts, label)
                got = old._invoke(folder, binding, slot, work, label, step, inputs, logs, lambda: False, row['operations'])
                if expected is None:
                    if label.startswith('encode-'):
                        spec=b['frames'][int(label[7:])]
                        _frame(slot, got['frame'], original, spec)
                        parts[spec['path']] = got['frame']
                    else:
                        case = next(c for c in policy['controls'] if label == c['id']+'-encode')
                        _control(case, got['frame'])
                        parts[case['id']+'.bmk'] = got['frame']
                else:
                    require(got == expected, f'CORAD amended native output differs: {label}')
            want = _parts(slot, policy)
            require(parts.keys() == want.keys() and all(len(v) <= want[k] for k,v in parts.items()), 'CORAD amended retention differs')
            for name,v in parts.items():
                (products/name).write_bytes(v)
            assessment = _evaluate(slot, policy, products, row['operations'], logs)
            dest = folder/'products'/sid; products.rename(dest) if products.stat().st_dev==dest.parent.stat().st_dev else _copy(products, dest)
            row.update(status='verified', corad=assessment, parts={name:_ref(folder,dest/name) for name in parts})
    except (OSError, ValueError) as exc:
        last = row['operations'][-1]['status'] if row['operations'] else None
        row.update(status=last if last in old.NONPASS else 'validation_failed',reason=str(exc))
    return row


def _copy(src, dest):
    dest.mkdir()
    for p in src.iterdir():
        (dest/p.name).write_bytes(p.read_bytes())


def verdict(binding, amendment, row, products):
    result = legacy.verdict(binding, row, products)
    if row['obligation_id'] in amendment['contract']['obligations']:
        result['evidence']['amendment_id'] = amendment['contract']['amendment_id']
        result['evidence']['amended_evidence'] = amendment['contract']['obligations'][row['obligation_id']]['evidence']
    return result


def run_specialized(root, run, binding, amendment, rows, append):
    folder = run/FOLDER; folder.mkdir()
    selected = legacy.scope(binding, rows)
    products = {}
    require(launcher_lock() == binding['launchers'], 'CORAD amended isolation launchers drifted')
    fixtures, _ = fixture_inputs(root)
    require(binding['slots'] == {key:slot for key,(slot,_) in fixtures.items()}, 'CORAD amended fixture drifted')
    stage_recovery(root, folder, binding['decoder'])
    for name in ('logs','products'):
        (folder/name).mkdir()
    for key in selected:
        slot, sample = fixtures[key]
        products[key] = (run_slot(folder, binding, slot, sample, amendment['contract']) if is_corad(slot) else
                         training.run_slot(folder, binding, slot, sample, lambda: False))
    for row in legacy.ledger_products(binding, {'fixtures':products}):
        append(row)
    for row in rows:
        row.update(verdict(binding, amendment, row, products))
    return {'driver':amendment['driver'],'amendment_id':amendment['contract']['amendment_id'],
            'fixtures':products,'files':_files(folder),'statuses':dict(Counter(r['status'] for r in products.values()))}
