"""Run a bound stateful exercise and recover each stream without predecessor or truth input."""
from pathlib import Path
import tempfile

from ..assets import ContractError, load_json, require, verify_asset
from ..planner.lzbench import byte_identity
from ..planner.lzbench_session import BUDGET_FRAME, METHODS, PARTS, TOOL, operations
from ..planner.linear_batch import batch_limits
from ..qualification.lzbench_session import match, verify_exercise, verify_restore
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref


def _original(slot,key):
    return {k:slot['inputs'][key][k] for k in ('bytes','sha256')}


def _mounts(slot,refs):
    return {'session-exercise':{**{k:_original(slot,k) for k in PARTS},
                                **({'budget':slot['budget_frame']} if slot['budget_frame'] else {})},
            **{'restore-'+k:{'frame':{n:refs[k][n] for n in ('bytes','sha256')}} for k in PARTS}}


def _part_path(slot,key):
    return f'products/{slot["product_slot"]}.{key}'


def _read(path,lo,hi):
    require(path.is_file() and not path.is_symlink() and lo<=path.stat().st_size<=hi,'lzbench session output extent differs')
    return path.read_bytes()


def _call(run,plan,slot,work,logs,label,mounts,args,files,cancelled,ops):
    folder = work/label
    folder.mkdir()
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],TOOL,batch_limits(plan,slot),folder,logs,label,
                                 mounts,args,cancelled,observe=True)
    if ops is not None:
        ops.append(op)
    require(completed(op),f'lzbench {label} failed: {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(files),'lzbench session produced unexpected files')
    return out


def _exercise(run,plan,slot,work,logs,originals,cancelled,ops):
    mounts = dict(originals)
    if slot['budget_frame']:
        guard_path = work/'budget'
        guard_path.write_bytes(BUDGET_FRAME)
        mounts['budget'] = guard_path
    codec = METHODS[slot['method']]['codec']
    out = _call(run,plan,slot,work,logs,'session-exercise',mounts,['exercise',codec],PARTS,cancelled,ops)
    return {k:_read(out/k,1,slot['parts'][k]) for k in PARTS}


def _restore(run,plan,slot,work,logs,key,frame,wire,cancelled,ops):
    label = 'restore-'+key
    codec = METHODS[slot['method']]['codec']
    out = _call(run,plan,slot,work,logs,label,{'frame':frame},['restore',codec,key],('raw',),cancelled,ops)
    expected = _original(slot,key)
    recovered = out/'raw'
    match(byte_identity(_read(recovered,expected['bytes'],expected['bytes'])),expected,'lzbench restored original bytes differ')
    verify_restore(slot,key,wire,load_json(logs/f'{label}.stdout'))
    return recovered


def _report(slot,wires,logs):
    info = verify_exercise(slot,wires,load_json(logs/'session-exercise.stdout'))
    return {**info,'independent_restores':{k:verify_restore(slot,k,wires[k],load_json(logs/f'restore-{k}.stdout')) for k in PARTS}}


def run_slot(run,plan,slot,original,cancelled):
    sid,ops = slot['product_slot'],[]
    logs = run/'logs'/sid
    logs.mkdir()
    row = {'product_slot':sid,'operations':ops,'parts':{},'session':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-session-') as tmp:
            work = Path(tmp)
            inputs = {k:work/k for k in PARTS}
            for k,data in zip(PARTS,original.columns,strict=True):
                match(byte_identity(data),_original(slot,k),'lzbench planned fixture differs')
                inputs[k].write_bytes(data)
            wires = _exercise(run,plan,slot,work,logs,inputs,cancelled,ops)
            for p in inputs.values():
                p.unlink()
            for k in PARTS:
                frame = work/f'{k}.frame'
                frame.write_bytes(wires[k])
                _restore(run,plan,slot,work,logs,k,frame,wires[k],cancelled,ops)
            info = _report(slot,wires,logs)
            for k in PARTS:
                p = run/_part_path(slot,k)
                with p.open('xb') as f:
                    f.write(wires[k])
                row['parts'][k] = _ref(run,p)
            row.update(status='verified',reason='',session=info)
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [label for label,_ in operations(slot)]
    require(set(row)=={'product_slot','status','reason','operations','parts','session'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(map(completed,ops[:-1])) and
            len({op['session_id'] for op in ops})==len(ops),'lzbench session operation order differs')
    for op in ops:
        logs = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(logs)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in logs if p in files) and
                (op['pid'] is None or logs<=files.keys()),'lzbench session logs missing or outside limit')
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected lzbench session part')
    for key,ref in row['parts'].items():
        name = _part_path(slot,key)
        require(ref==files.get(name) and 0<ref['bytes']<=slot['parts'][key],'lzbench session retained reference differs')
        allowed.add(name)
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['session'] is None,'invalid lzbench session terminal')
        return False
    require(not row['reason'] and len(ops)==len(labels) and all(map(completed,ops)) and row['parts'].keys()==slot['parts'].keys(),
            'incomplete lzbench session evidence')
    match({op['operation']:op.get('input_mounts') for op in ops},_mounts(slot,row['parts']),'lzbench session input closure differs')
    wires = {k:_read(run/v['path'],1,slot['parts'][k]) for k,v in row['parts'].items()}
    match(row['session'],_report(slot,wires,run/'logs'/sid),'lzbench session report differs from retained transcript')
    return True


def audit_slot(run,plan,slot,row):
    parts = {k:verify_asset(run,v) for k,v in row['parts'].items()}
    wires = {k:_read(parts[k],1,slot['parts'][k]) for k in PARTS}
    with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-session-audit-') as tmp:
        work = Path(tmp)
        work.joinpath('logs').mkdir()
        logs = work/'logs'
        originals = {k:_restore(run,plan,slot,work,logs,k,parts[k],wires[k],lambda:False,None) for k in PARTS}
        replayed = _exercise(run,plan,slot,work,logs,originals,lambda:False,None)
        require(replayed==wires,'lzbench session recreated frame bytes differ')
        # An XZ worker may complete on a different call. Validate all replayed
        # bounds and statuses, not equality of transient progress transcripts.
        _report(slot,replayed,logs)
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],
            'replayed_from_independent_restores':True,**row['session']}
