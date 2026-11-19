"""Run and independently restore the selected pcodec multi-asset page products."""
from pathlib import Path
import tempfile

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..planner.pcodec import identity
from ..planner.pcodec_pages import METHODS, OPERATIONS, PARTS, TOOL
from ..qualification.pcodec_pages import (check_slot, expect_decode, expect_diagnosis, expect_encode,
                                          expect_missing, geometry, native_method, read_geometry)
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .smoke import _ref, _worker_json

OP_ENCODE, OP_PAGE1, OP_PAGE0, OP_MISSING, OP_DIAGNOSE = OPERATIONS
NONPASS = {'cancelled','timeout','crash','dependency_failed','file_limit_signal','sandbox_failed',
           'validation_failed','execution_failed'}


def _completed(op):
    return op['status']=='completed' and op['returncode']==0 and op['pid'] is not None


def _files(output, names):
    require({p.name for p in output.iterdir()} == set(names) and
            all(p.is_file() and not p.is_symlink() for p in output.iterdir()), 'unexpected wrapped native output files')


def _call(run, plan, slot, work, logs, label, operation, inputs, cancelled, ops, *, page=None):
    driver = plan['protocol_methods'][slot['method']]
    require(driver == METHODS[slot['method']], 'wrapped driver does not match frozen route')
    lane = 'native' if native_method(slot) else 'source'
    args = [operation,lane,*([str(page)] if page is not None else []),*(f'/inputs/{n}' for n in inputs)]
    output, op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],driver['tool'],plan['limits'],
                                     work,logs,label,inputs,args,cancelled)
    if ops is not None:
        ops.append(op)
    require(_completed(op), f'{label} did not complete: {op["reason"]}')
    result, = _worker_json(logs/(label+'.stdout'),1)
    return output,result


def _positive_output(path, expected):
    require(path.stat().st_size == expected['bytes'], 'wrapped output length differs')
    raw = path.read_bytes()
    require(identity(raw) == expected,'wrapped output bits differ')
    return raw


def _derive_from_logs(slot, sizes, state, logs):
    detached = []
    for i,label in ((1,OP_PAGE1),(0,OP_PAGE0)):
        obs, = _worker_json(logs/(label+'.stdout'),1)
        detached.append(expect_decode(slot,sizes,state,i,obs))
    obs, = _worker_json(logs/(OP_MISSING+'.stdout'),1)
    missing = expect_missing(slot,sizes,obs)
    obs, = _worker_json(logs/(OP_DIAGNOSE+'.stdout'),1)
    diagnosed = expect_diagnosis(slot,obs)
    return {'detached':detached,'whole_original':slot['original'],'missing_meta':missing,'session_controls':diagnosed}


def _native_checks(run, plan, slot, row, sizes, state, logs, cancelled, ops=None):
    # Sidecar is parsed by the control plane; the decoder mounts only the declared native inputs.
    refs = row['product_parts']
    paths = {name:verify_asset(run,ref) for name,ref in refs.items() if name != 'geometry.json'}
    original = {}
    for i,label in ((1,OP_PAGE1),(0,OP_PAGE0)):
        with tempfile.TemporaryDirectory(prefix='tsbench-detached-page-') as tmp:
            output, obs = _call(run,plan,slot,Path(tmp),logs,label,'decode',
                {'meta':paths['meta'],'page':paths[f'page-{i}']},cancelled,ops,page=i)
            _files(output,('raw',))
            expect_decode(slot,sizes,state,i,obs)
            original[i] = _positive_output(output/'raw',slot['page_originals'][i])
    require(identity(original[0]+original[1]) == slot['original'], 'detached pages do not restore the whole original')
    with tempfile.TemporaryDirectory(prefix='tsbench-missing-page-meta-') as tmp:
        output, obs = _call(run,plan,slot,Path(tmp),logs,OP_MISSING,'missing',{'page':paths['page-0']},cancelled,ops)
        _files(output,())
        expect_missing(slot,sizes,obs)
    with tempfile.TemporaryDirectory(prefix='tsbench-wrapped-scope-') as tmp:
        output, obs = _call(run,plan,slot,Path(tmp),logs,OP_DIAGNOSE,'diagnose',paths,cancelled,ops)
        expected = expect_diagnosis(slot,obs)
        want = ('session-0','session-1',*(['ownership'] if native_method(slot) else []))
        _files(output,want)
        for i in range(2):
            _positive_output(output/f'session-{i}',expected['session_restored'][i])
        if native_method(slot):
            _positive_output(output/'ownership',expected['ownership_restored'])
    return _derive_from_logs(slot,sizes,state,logs)


def _publish_parts(run, output, slot, encode_observation):
    names = ('meta','page-0','page-1')
    _files(output,names)
    for name in names:
        require((2 if name == 'meta' else 1) <= (output/name).stat().st_size <= PARTS[name],
                'wrapped compression output exceeds frozen bounds')
    sizes = geometry(slot,{name:{'bytes':(output/name).stat().st_size} for name in names})
    state = expect_encode(slot,sizes,encode_observation)
    dest = run/'products'/slot['product_slot']
    with tempfile.TemporaryDirectory(prefix='.wrapped-parts-',dir=run) as tmp:
        staged = Path(tmp)/'product'
        staged.mkdir()
        for name in names:
            (staged/name).write_bytes((output/name).read_bytes())
        (staged/'geometry.json').write_bytes(canonical_bytes(sizes))
        staged.rename(dest)
    return {name:_ref(run,dest/name) for name in PARTS},sizes,state


def run_slot(run, plan, slot, sample, cancelled):
    check_slot(slot)
    sid = slot['product_slot']
    row = {'product_slot':sid,'status':'cancelled','reason':'cancelled before product',
           'operations':[],'product_parts':None,'encode_observation':None,'wrapped_validation':None}
    if cancelled():
        return row
    logs = run/'logs'/sid
    logs.mkdir()
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-wrapped-encode-') as tmp:
            work = Path(tmp)
            raw = work/'original'
            plain, = sample.columns
            require(not sample.schema and identity(plain)==slot['original'], 'wrapped planned input differs')
            raw.write_bytes(plain)
            output, encode_obs = _call(run,plan,slot,work,logs,OP_ENCODE,'encode',{'raw':raw},cancelled,row['operations'])
            refs,sizes,state = _publish_parts(run,output,slot,encode_obs)
            row.update(product_parts=refs,encode_observation=encode_obs)
        row['wrapped_validation'] = _native_checks(run,plan,slot,row,sizes,state,logs,cancelled,row['operations'])
        row.update(status='verified',reason='')
    except (ContractError,OSError,UnicodeError) as exc:
        last = row['operations'][-1]['status'] if row['operations'] else None
        status = last if last in NONPASS else 'validation_failed' if last=='completed' else 'execution_failed'
        row.update(status=status,reason=str(exc))
    return row


def inspect_evidence(run, plan, slot, row, files, allowed):
    check_slot(slot)
    ops, sid = row['operations'], slot['product_slot']
    require(set(row)=={'product_slot','status','reason','operations','product_parts','encode_observation','wrapped_validation'} and
            [op['operation'] for op in ops] == list(OPERATIONS[:len(ops)]) and all(_completed(op) for op in ops[:-1]),
            'wrapped operation order differs')
    logs = run/'logs'/sid
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{suffix}' for suffix in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes'] <= plan['limits']['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths <= files.keys()), 'wrapped operation logs missing or oversized')
    refs = row['product_parts']
    if refs is not None:
        require(isinstance(refs,dict) and refs.keys()==PARTS.keys() and ops and _completed(ops[0]),
                'wrapped product is missing a required part')
        for name, limit in PARTS.items():
            key = f'products/{sid}/{name}'
            require(refs[name] == files.get(key) and refs[name]['path']==key and
                    (2 if name == 'meta' else 1) <= refs[name]['bytes'] <= limit, 'wrapped product part reference differs')
            allowed.add(key)
        sizes = read_geometry(slot,run/refs['geometry.json']['path'],refs)
        encode, = _worker_json(logs/(OP_ENCODE+'.stdout'),1)
        require(canonical_bytes(encode) == canonical_bytes(row['encode_observation']), 'wrapped retained encoder log differs')
        state = expect_encode(slot,sizes,encode)
    else:
        require(row['encode_observation'] is None, 'wrapped product without parts has encoder evidence')
    if row['status']=='verified':
        require(refs is not None and row['reason']=='' and len(ops)==len(OPERATIONS) and all(_completed(op) for op in ops),
                'wrapped product did not complete all operations')
        derived = _derive_from_logs(slot,sizes,state,logs)
        require(canonical_bytes(derived)==canonical_bytes(row['wrapped_validation']), 'wrapped recovered evidence differs')
        return True
    require(row['status'] in NONPASS and bool(row['reason']) and row['wrapped_validation'] is None,
            'invalid wrapped nonpassing terminal')
    return False


def restore_slot(run, plan, slot, row):
    refs = row['product_parts']
    sizes = read_geometry(slot,run/refs['geometry.json']['path'],refs)
    state = expect_encode(slot,sizes,row['encode_observation'])
    with tempfile.TemporaryDirectory(prefix='tsbench-wrapped-audit-') as tmp:
        result = _native_checks(run,plan,slot,row,sizes,state,Path(tmp),lambda:False)
    require(result==row['wrapped_validation'], 'wrapped restored audit differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'protocol':slot['protocol'],
            'product_parts':refs,'restored':result}
