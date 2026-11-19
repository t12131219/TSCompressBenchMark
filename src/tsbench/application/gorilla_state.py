"""Gorilla C11 state operations, file-only restore and separate work diagnostics."""
from pathlib import Path
import struct
import tempfile

from ..assets import ContractError, canonical_bytes, load_json, require, verify_asset
from ..planner.batch_execution import DIRECT_TOOL
from ..planner.gorilla import LIMIT, PREFIX, max_payload, oracle, sha
from ..planner.gorilla_state import APPEND, ITER, TOOL, operations
from ..planner.linear_batch import batch_limits
from ..qualification.gorilla import decode_chunk, iterator_work, resume_work
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import MOUNT, invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref


def _ref_bytes(wire):
    return {'bytes':len(wire),'sha256':sha(wire)}


def _pairs(t,v):
    return list(zip((x for x, in struct.iter_unpack('<q',t)),(x for x, in struct.iter_unpack('<Q',v)),strict=True))


def _match(actual,expected,message):
    require(canonical_bytes(actual)==canonical_bytes(expected),message)


def _call(run,plan,slot,work,logs,label,inputs,argv,outputs,cancelled,ops):
    folder = work/label
    folder.mkdir()
    tool = dict(operations(slot))[label]
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],tool,batch_limits(plan,slot),folder,logs,label,inputs,
                                 argv,cancelled,observe=True)
    if ops is not None:
        ops.append(op)
    require(completed(op),f'Gorilla {label} failed: {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(outputs) and all(p.is_file() and not p.is_symlink() for p in out.iterdir()),
            'Gorilla lifecycle produced unexpected output')
    return out


def _part_map(slot):
    if 'snapshot' in slot['parts']:
        return {'prefix-work':('snapshot','valid'),'full-work':('uninterrupted','valid'),'trailing-work':('snapshot','trailing')}
    return {'iterator-work':('backing','iterate')} if slot['method']==ITER else {'empty-work':('backing','valid')}


def _decode(run,plan,slot,work,logs,label,key,part,cancelled,ops):
    argv = [label] if label=='iterator-drain' else ['decode',f'/inputs/{key}','t','v']
    out = _call(run,plan,slot,work,logs,label,{key:part},argv,('t','v'),cancelled,ops)
    target = slot['prefix'] if key=='snapshot' else slot['original']
    require(all((out/k).stat().st_size==target['rows']*8 for k in ('t','v')),'Gorilla native recovered extent differs')
    t,v = ((out/k).read_bytes() for k in ('t','v'))
    require(oracle(_pairs(t,v))==target,'Gorilla native recovered bits differ')
    return t,v


def _observe(run,plan,slot,work,logs,label,key,mode,part,cancelled,ops):
    base = [f'{MOUNT}/lib/libgorilla_c.so']
    if mode=='iterate':
        argv = [*base,'iterate','/inputs/backing',*('n' if op=='next' else f's:{query}' for op,query,*_ in slot['seek'])]
    else:
        argv = [*base,'resume',f'/inputs/{key}',mode]
    _call(run,plan,slot,work,logs,label,{key:part},argv,(),cancelled,ops)


def _operate_restore(run,plan,slot,work,logs,parts,cancelled,ops):
    observations = _part_map(slot)
    recovered = {}
    for label,_ in operations(slot):
        if label in observations:
            key,mode = observations[label]
            _observe(run,plan,slot,work,logs,label,key,mode,parts[key],cancelled,ops)
        elif label.startswith('restore-') or label=='iterator-drain':
            key = 'backing' if label=='iterator-drain' else label.removeprefix('restore-')
            recovered[key] = _decode(run,plan,slot,work,logs,label,key,parts[key],cancelled,ops)
    return recovered


def _read_parts(slot,parts):
    wire = {}
    for key,p in parts.items():
        n = slot['prefix']['rows'] if key=='snapshot' else slot['original']['rows']
        require(2<=p.stat().st_size<=slot['parts'][key],'Gorilla raw frame outside frozen bound')
        raw = p.read_bytes()
        decoded,bits = decode_chunk(raw,n)
        want = slot['prefix'] if key=='snapshot' else slot['original']
        require(oracle(decoded)==want,'Gorilla independent state payload differs from original')
        wire[key] = raw,bits,decoded
    if 'snapshot' in wire:
        require(wire['resumed'][0]==wire['uninterrupted'][0] and wire['snapshot'][2]==wire['resumed'][2][:PREFIX],
                'Gorilla resumed and uninterrupted/initial native bytes differ')
        tail = _interleave(wire['resumed'][2][PREFIX:])
        require(_ref_bytes(tail)==slot['tail'],'Gorilla composed tail differs from frozen input')
    return wire


def _reports(plan,slot,parts,logs):
    wire = _read_parts(slot,parts)
    read = lambda label: load_json(logs/(label+'.stdout'))
    n = slot['original']['rows']
    progress = {'rows':PREFIX,'chunk_bits':wire['snapshot'][1],'workspace_bytes':max_payload(LIMIT)} if 'snapshot' in wire else None
    if progress:
        _match(read('state-append'),{'prefix':progress,'after_overflow':progress,'invalid_span':1,'overflow':6,
               'closed_append':1,'prefix_equals_batch':True,'finish_equals_batch':True,'finish_idempotent':True,
               'reset_snapshot_hex':'0000'},'Gorilla append progress or lifecycle differs')
        _match(read('state-resume'),{'resumed_prefix':progress,'bad_snapshot':5},'Gorilla resume progress or bad snapshot differs')
    else:
        _match(read('state-encode'),{'rows':n},'Gorilla backing encode count differs')
    work = {}
    for label,(key,mode) in _part_map(slot).items():
        raw = wire[key][0]
        expected = iterator_work(raw,slot['seek']) if mode=='iterate' else resume_work(raw,mode=='trailing')
        _match(read(label),expected,'Gorilla scan/copy or iterator work differs')
        work[label] = expected
    for key in parts:
        if key=='backing' and slot['method']==ITER:
            _match(read('iterator-drain'),{'rows':n,'eof':[0,None],'bad_trailer':[[5,None],[5,None]],'reset_verified':True},
                   'Gorilla iterator terminal/poison/reset differs')
        else:
            _match(read('restore-'+key),{'rows':PREFIX if key=='snapshot' else n},'Gorilla file-only restore count differs')
    return {'restored':slot['original'],'prefix_progress':progress,'work':work,
            'scope':'elf_calls_and_logical_copy_bytes_not_latency','observer_sha256':plan['direct_control']['tool_refs'][TOOL]['sha256']}


def _interleave(pairs):
    return b''.join(struct.pack('<qQ',t,v) for t,v in pairs)


def _resume(run,plan,slot,work,logs,part,tail,cancelled,ops):
    require(_ref_bytes(tail)==slot['tail'],'Gorilla staged tail differs')
    path = work/'tail'
    path.write_bytes(tail)
    out = _call(run,plan,slot,work,logs,'state-resume',{'snapshot':part,'tail':path},['state-resume'],('resumed',),cancelled,ops)
    path.unlink()
    return out/'resumed'


def _part_path(slot,key):
    return f'products/{slot["product_slot"]}.{key}.xor'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'gorilla_state':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-gorilla-state-') as tmp:
            work = Path(tmp)
            pairs = _pairs(*sample.columns)
            require(not sample.schema and len(sample.columns)==2 and oracle(pairs)==slot['original'],'Gorilla staged input differs')
            if 'snapshot' in slot['parts']:
                raw = work/'raw'
                raw.write_bytes(_interleave(pairs))
                out = _call(run,plan,slot,work,logs,'state-append',{'raw':raw},['state-append'],('snapshot','uninterrupted'),cancelled,ops)
                raw.unlink()
                parts = {'snapshot':out/'snapshot','uninterrupted':out/'uninterrupted'}
                parts['resumed'] = _resume(run,plan,slot,work,logs,parts['snapshot'],_interleave(pairs[PREFIX:]),cancelled,ops)
            else:
                paths = {k:work/k for k in ('t','v')}
                for p,data in zip(paths.values(),sample.columns,strict=True):
                    p.write_bytes(data)
                out = _call(run,plan,slot,work,logs,'state-encode',paths,['encode','/inputs/t','/inputs/v','backing'],('backing',),cancelled,ops)
                for p in paths.values():
                    p.unlink()
                parts = {'backing':out/'backing'}
            _operate_restore(run,plan,slot,work,logs,parts,cancelled,ops)
            info = _reports(plan,slot,parts,logs)
            for key,p in parts.items():
                dest = run/_part_path(slot,key)
                with dest.open('xb') as f:
                    f.write(p.read_bytes())
                row['parts'][key] = _ref(run,dest)
            row.update(status='verified',gorilla_state=info)
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def _mounts(slot,parts):
    orig = slot['original']
    picked = {k:{n:r[n] for n in ('bytes','sha256')} for k,r in parts.items()}
    expect = {label:{key:picked[key]} for label,(key,_) in _part_map(slot).items()}
    for key in picked:
        label = 'iterator-drain' if slot['method']==ITER else 'restore-'+key
        expect[label] = {key:picked[key]}
    if 'snapshot' in picked:
        data,_ = decode_chunk(parts['uninterrupted']['file'].read_bytes(),orig['rows'])
        expect.update({'state-append':{'raw':_ref_bytes(_interleave(data))},
                       'state-resume':{'snapshot':picked['snapshot'],'tail':slot['tail']}})
    else:
        expect['state-encode'] = {'t':{'bytes':8*orig['rows'],'sha256':orig['milliseconds_sha256']},
                                  'v':{'bytes':8*orig['rows'],'sha256':orig['value_sha256']}}
    return expect


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [label for label,_ in operations(slot)]
    require(set(row)=={'product_slot','status','reason','operations','parts','gorilla_state'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(map(completed,ops[:-1])) and
            len({op['session_id'] for op in ops})==len(ops),'Gorilla lifecycle operation order differs')
    for op in ops:
        logs = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(logs)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in logs if p in files) and
                (op['pid'] is None or logs<=files.keys()),'Gorilla lifecycle logs missing or outside limit')
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected Gorilla lifecycle artifact')
    for key,ref in row['parts'].items():
        name = _part_path(slot,key)
        require(ref==files.get(name) and ref['bytes']<=slot['parts'][key],'Gorilla lifecycle retained reference differs')
        allowed.add(name)
    if row['status']=='verified':
        require(not row['reason'] and len(ops)==len(labels) and all(map(completed,ops)) and row['parts'].keys()==slot['parts'].keys(),
                'incomplete Gorilla lifecycle evidence')
        parts = {k:run/r['path'] for k,r in row['parts'].items()}
        info = _reports(plan,slot,parts,run/'logs'/sid)
        mounts = _mounts(slot,{k:{**r,'file':parts[k]} for k,r in row['parts'].items()})
        _match({op['operation']:op.get('input_mounts') for op in ops},mounts,'Gorilla lifecycle input closure differs')
        _match(row['gorilla_state'],info,'Gorilla lifecycle retained work evidence differs')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['gorilla_state'] is None,'invalid Gorilla lifecycle terminal')
    return False


def audit_slot(run,plan,slot,row):
    parts = {k:verify_asset(run,r) for k,r in row['parts'].items()}
    with tempfile.TemporaryDirectory(prefix='tsbench-gorilla-state-audit-') as tmp:
        work = Path(tmp)
        recovered = _operate_restore(run,plan,slot,work,work,parts,lambda:False,None)
        resumed = None
        if 'snapshot' in parts:
            pairs = _pairs(*recovered['uninterrupted'])
            replay = _resume(run,plan,slot,work,work,parts['snapshot'],_interleave(pairs[PREFIX:]),lambda:False,None)
            require(replay.read_bytes()==parts['resumed'].read_bytes(),'Gorilla independently replayed tail resume differs')
            resumed = True
        for log in work.glob('*.stdout'):
            require(log.read_bytes()==(run/'logs'/slot['product_slot']/log.name).read_bytes(),
                    'Gorilla state/iterator replayed transcript differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'case':slot['name'],'parts':row['parts'],
            'tail_resume_replayed_from_restored_uninterrupted':resumed,**row['gorilla_state']}
