"""Isolated IntMult encoding, standalone footer drain, and replayable negative terminals."""
from pathlib import Path
import tempfile

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..planner.linear_batch import batch_limits
from ..planner.pcodec import identity, page_spans
from ..planner.pcodec_intmult import TOOL, negative_input, operations
from ..qualification.pcodec import intmult_wire_header
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref, _worker_json


def _call(run,plan,slot,work,logs,mode,inputs,argv,cancelled,ops=None):
    work.mkdir()
    label = 'intmult-'+mode
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],TOOL,batch_limits(plan,slot),work,logs,label,
                                 inputs,[label,*argv],cancelled,observe=True)
    if ops is not None:
        ops.append(op)
    rejected = mode=='encode' and slot['expected_status']
    require(_finished(slot,op),f'pcodec {label} did not reach expected terminal: {op["reason"]}')
    names = set() if rejected else {'frame'} if mode=='encode' else {'v'}
    require({p.name for p in out.iterdir()}==names and all(p.is_file() and not p.is_symlink() for p in out.iterdir()),
            'pcodec IntMult produced undeclared output')
    return out


def _finished(slot,op):
    if op['operation']=='intmult-encode' and slot['expected_status']:
        return op['status']=='failed' and op['returncode']==4 and op['pid'] is not None
    return completed(op)


def _encode(run,plan,slot,work,logs,raw,cancelled,ops=None):
    require(identity(raw)==slot['original'],'pcodec staged IntMult original differs')
    source = work/'input'
    source.write_bytes(raw)
    out = _call(run,plan,slot,work/'encoder',logs,'encode',{'input':source},
                [slot['dtype'],str(slot['count']),str(slot['base'])],cancelled,ops)
    source.unlink()
    return out/'frame'


def _encode_log(slot,logs,n):
    record, = _worker_json(logs/'intmult-encode.stdout',1)
    expected = {'native_status':slot['expected_status'],'output_bytes':n,'output_pointer_null':not n}
    require(canonical_bytes(record)==canonical_bytes(expected),'pcodec IntMult encode or rejection transcript differs')
    return record


def _wire(slot,frame):
    require(15<=frame.stat().st_size<=slot['parts']['frame'],'IntMult bare frame outside bound')
    wire = intmult_wire_header(frame.read_bytes())
    require(wire=={'dtype':slot['dtype'],'count':slot['count'],'delta':slot['parameters']['delta'],**slot['wire']},
            'pcodec IntMult emitted mode or exact wire base differs')
    return wire


def _decode_log(slot,logs,wire):
    record, = _worker_json(logs/'intmult-decode.stdout',1)
    base,dtype = wire['base'],wire['dtype']
    chunk = {'backend':'source-rust-repaired','mode':wire['mode'],
             'mode_detail':f'IntMult({dtype.upper()}({base}))' if base is not None else 'Classic',
             'delta':wire['delta'],'delta_detail':'NoOp'}
    expected = {'spans':page_spans(wire['count'],slot['parameters']['read_capacity'])+[0],
                'state':{'backend':'source-rust-repaired','kind':'standalone','decoded_chunk_headers':[chunk]}}
    require(canonical_bytes(record)==canonical_bytes(expected),'pcodec IntMult decoder metadata or footer drain differs')
    return {**record,'restored':slot['original']}


def _decode(run,plan,slot,work,logs,frame,cancelled,ops=None):
    out = _call(run,plan,slot,work,logs,'decode',{'frame':frame},[],cancelled,ops)/'v'
    require(out.stat().st_size==slot['original']['bytes'] and identity(out.read_bytes())==slot['original'],
            'pcodec IntMult native decode differs from original bits')


def _frame_path(slot):
    return f'products/{slot["product_slot"]}.pco'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'intmult':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-pcodec-intmult-') as tmp:
            work = Path(tmp)
            raw, = sample.columns
            require(not sample.schema,'pcodec IntMult has no external schema')
            frame = _encode(run,plan,slot,work,logs,raw,cancelled,ops)
            if slot['expected_status']:
                record = _encode_log(slot,logs,0)
                row.update(status='expected_rejection',reason='native PC_INVALID',intmult={'encode':record})
                return row
            wire = _wire(slot,frame)
            record = _encode_log(slot,logs,frame.stat().st_size)
            _decode(run,plan,slot,work/'decoder',logs,frame,cancelled,ops)
            decoded = _decode_log(slot,logs,wire)
            dest = run/_frame_path(slot)
            with dest.open('xb') as f:
                f.write(frame.read_bytes())
            row['parts']['frame'] = _ref(run,dest)
            row.update(status='verified',intmult={'encode':record,'emitted':wire,'decode':decoded})
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [label for label,_ in operations(slot)]
    require(set(row)=={'product_slot','status','reason','operations','parts','intmult'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(_finished(slot,op) for op in ops[:-1]) and
            len({op['session_id'] for op in ops})==len(ops),'pcodec IntMult operation order differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{e}' for e in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'IntMult logs missing or beyond limit')
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected pcodec IntMult retained part')
    if 'frame' in row['parts']:
        p = _frame_path(slot)
        ref = row['parts']['frame']
        require(ref==files.get(p) and ref['bytes']<=slot['parts']['frame'],'IntMult retained frame reference differs')
        allowed.add(p)
    if row['status'] in {'verified','expected_rejection'}:
        reject = slot['expected_status']==1
        require((row['status']=='expected_rejection')==reject and row['reason']==('native PC_INVALID' if reject else '') and
                len(ops)==len(labels) and all(_finished(slot,o) for o in ops) and
                row['parts'].keys()==slot['parts'].keys() and ops[0].get('input_mounts')=={'input':slot['original']},
                'incomplete pcodec IntMult execution evidence')
        logs = run/'logs'/sid
        if reject:
            want = {'encode':_encode_log(slot,logs,0)}
        else:
            ref = row['parts']['frame']
            require(ops[1].get('input_mounts')=={'frame':{k:ref[k] for k in ('bytes','sha256')}},
                    'IntMult decoder must mount only the standalone frame')
            wire = _wire(slot,run/ref['path'])
            want = {'encode':_encode_log(slot,logs,ref['bytes']),'emitted':wire,'decode':_decode_log(slot,logs,wire)}
        require(canonical_bytes(row['intmult'])==canonical_bytes(want),'pcodec IntMult retained evidence differs')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['intmult'] is None,'invalid pcodec IntMult terminal')
    return False


def audit_slot(run,plan,slot,row):
    with tempfile.TemporaryDirectory(prefix='tsbench-intmult-audit-') as tmp:
        work = Path(tmp)
        if row['status']=='expected_rejection':
            _encode(run,plan,slot,work,work,negative_input(slot),lambda:False)
            replay = {'encode':_encode_log(slot,work,0)}
            require(replay==row['intmult'],'pcodec IntMult replayed native rejection differs')
            return {'product_slot':slot['product_slot'],'case':slot['name'],'negative_replayed':replay}
        frame = verify_asset(run,row['parts']['frame'])
        _decode(run,plan,slot,work/'decoder',work,frame,lambda:False)
        wire = _wire(slot,frame)
        restored = _decode_log(slot,work,wire)
        require(restored==row['intmult']['decode'],'pcodec IntMult replayed restore differs')
        return {'product_slot':slot['product_slot'],'case':slot['name'],'frame':row['parts']['frame'],'emitted':wire,'restored':restored}
