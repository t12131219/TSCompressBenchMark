"""Files-only execution and restoration of finalized SElf* ordered products."""
from pathlib import Path
import tempfile

from ..assets import ContractError, require, verify_asset
from ..planner.linear_batch import batch_limits
from ..planner.selfstar import BITLEN, HEADER, MAGIC, schema_bytes, sha
from ..planner.selfstar_execution import (ABI_DECODE, ABI_ENCODE, LIMITS, LIVE, LIVE_ENCODE, MUTATIONS, PARITY, PLUGIN,
                                          READ, STATE, TOOL, operations)
from ..qualification.selfstar_wire import read_frame
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker
from .smoke import _ref, _worker_json

NONPASS = {'cancelled','timeout','crash','dependency_failed','file_limit_signal','sandbox_failed','execution_failed','validation_failed'}


def completed(op):
    return op['status']=='completed' and op['returncode']==0 and op['pid'] is not None


def _boundary(slot, artifact):
    schema = schema_bytes(slot['width'],slot['name'])
    require(len(schema)==slot['original']['schema_bytes'] and sha(schema)==slot['original']['schema_sha256'] and
            0<artifact.stat().st_size<=slot['parts']['frame'], 'SElf* envelope outside frozen size')
    return read_frame(artifact.read_bytes(),slot['width'],slot['count'],schema)


def _out(folder,*names):
    require({p.name for p in folder.iterdir()}==set(names) and all(p.is_file() and not p.is_symlink() for p in folder.iterdir()),
            'unexpected isolated SElf* output')


def _run(run,plan,slot,work,logs,label,inputs,args,cancelled,ops,*,tool=False,operation=None):
    if tool:
        out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],TOOL,batch_limits(plan,slot),work,logs,label,inputs,args,cancelled)
    else:
        method = {'plugin':PLUGIN,'options':slot['options']}
        out,op = invoke_isolated_worker(run/DIRECTORY,plan['decoder'],method,batch_limits(plan,slot),work,logs,operation or label,
                                       inputs,args,cancelled,label=label)
    if ops is not None:
        ops.append(op)
    return out,op


def _status(op,logs,label,status):
    return (op['status']=='failed' and op['returncode']==3 and op['pid'] is not None and
            (logs/(label+'.stderr')).read_bytes().startswith(f'plugin status {status}:'.encode()) and
            (logs/(label+'.stdout')).stat().st_size==0)


def _raw(slot,path):
    original = slot['original']
    require(path.stat().st_size==original['bytes'] and sha(path.read_bytes())==original['sha256'], 'SElf* restored original bits differ')
    return {'bytes':original['bytes'],'sha256':original['sha256']}


def _mutations(artifact,slot):
    wire = artifact.read_bytes()
    start = HEADER.size+slot['original']['schema_bytes']
    # Recompute the outer length except when explicitly testing its truncation.
    def wrap(payload, *, count=slot['count'], dtype=slot['dtype']):
        return HEADER.pack(MAGIC,dtype,count,slot['original']['schema_bytes'],len(payload))+wire[HEADER.size:start]+payload
    payload = wire[start:]
    return dict(zip(MUTATIONS,(wire[:-1],wrap(payload[:-1]),wrap(BITLEN.pack(0)+payload[4:]),
                              wrap(BITLEN.pack(0xffffffff)+payload[4:]),wrap(payload+b'!'),
                              wrap(payload,count=0),wrap(payload,dtype=5)),strict=True))


def _evidence(slot,artifact,logs):
    records = _boundary(slot,artifact)
    counts, bits = [r[0] for r in records],[r[1] for r in records]
    common = {'rows':slot['count'],'width':slot['width']}
    live = slot['method']==LIVE
    for label,mode in ([(LIVE_ENCODE,'live'),(PARITY,'batch')] if live else [(PARITY,'batch')]):
        report, = _worker_json(logs/(label+'.stdout'),1)
        require(set(report)=={'rows','width','mode','blocks'} and all(report[k]==v for k,v in common.items()) and
                report['mode']==mode and len(report['blocks'])==len(records), 'SElf* direct encode geometry differs')
        for r,n,b in zip(report['blocks'],counts,bits,strict=True):
            require(set(r)=={'n','bits','before_finish_bits','add_counts','add_bits'} and (r['n'],r['bits'])==(n,b),
                    'SElf* encoded bits differ from product')
            c = sorted({min(n,v) for v in (1,8,71,192,n)}) if mode=='live' else []
            progress = r['add_bits']
            require(r['add_counts']==c and len(progress)==len(c) and
                    (0<r['before_finish_bits']==progress[-1]<b and progress==sorted(set(progress)) and min(progress)>0
                     if c else r['before_finish_bits']==0),'SElf* live add progress differs')
    read, = _worker_json(logs/(READ+'.stdout'),1)
    require(read=={**common,'drained_bits':bits},'SElf* reader did not drain the full product')
    if not live:
        enc, = _worker_json(logs/(ABI_ENCODE+'.stdout'),1)
        shape,dec = _worker_json(logs/(ABI_DECODE+'.stdout'),2)
        info = {'backend':'selfstar-c-scalar','mode':'batch','threads':1,'fallback':False,'blocks':len(records),
                'native_bits':sum(bits),'native_payload_bytes':sum(len(r[2]) for r in records),'block_header_bytes':4*len(records),
                'block_values':512}
        require(enc=={**info,'operation':'encode'} and dec=={**info,'operation':'decode'} and
                shape=={'columns':[{'count':slot['count'],'dtype':slot['dtype']}]},'SElf* ABI evidence differs')
    evidence = {'block_counts':counts,'block_bits':bits,'native_bytes':sum(len(r[2]) for r in records),
                'direct_batch_parity':True,'drained_bits':read['drained_bits']}
    if len(records)>1:
        state, = _worker_json(logs/(STATE+'.stdout'),1)
        require(state=={'skip_prefix':3,'prefix_rows':counts[0],'prefix_body_bytes':len(records[0][2]),'prefix_header_bytes':4,
                        'before_finish_bits':state['before_finish_bits'],'partial_rows':counts[1],'partial_terminal':3,
                        'after_failure':5,'reset_replay':True,'fresh_second_differs':True} and
                0<state['before_finish_bits']<bits[1],'SElf* lifecycle evidence differs')
        evidence['state'] = state
    if slot['name']=='fixture-1591':
        cap, = _worker_json(logs/(LIMITS+'.stdout'),1)
        require(cap=={'max_block_rows':1000,'max_block_bits':cap['max_block_bits'],'workspace_bytes':25000,
                     'batch_invalid':[1]*4,'live_invalid':[1]*5,'capacity':2,'finish_after_capacity':5,'reset_recovers':True} and
                0<cap['max_block_bits']<=8*25000,'SElf* native capacity evidence differs')
        evidence['limits'] = cap
    return evidence


def _restore_checks(run,plan,slot,artifact,logs,cancelled,ops,*,audit=False):
    with tempfile.TemporaryDirectory(prefix='tsbench-selfstar-restore-') as tmp:
        work = Path(tmp)
        def call(label,inputs,args,**kw):
            place = work/label; place.mkdir()
            return _run(run,plan,slot,place,logs,label,inputs,args,cancelled,ops,**kw)
        out,op = call(READ,{'frame':artifact},['decode','/inputs/frame','/out/raw'],tool=True)
        require(completed(op),'SElf* direct reader failed: '+op['reason'])
        _out(out,'raw'); recovered = out/'raw'; _raw(slot,recovered)
        if slot['method']!=LIVE:
            out,op = call(ABI_DECODE,{'frame':artifact},['/inputs/frame','/out/schema','/out/raw'])
            require(completed(op),'SElf* ABI decoder failed: '+op['reason'])
            _out(out,'schema','raw'); _raw(slot,out/'raw')
            require(sha((out/'schema').read_bytes())==slot['original']['schema_sha256'],'SElf* restored ABI schema differs')
        if audit:
            schema = work/'schema'; schema.write_bytes(schema_bytes(slot['width'],slot['name']))
            out,op = call(PARITY,{'raw':recovered,'schema':schema},['batch',str(slot['width']),'/inputs/raw','/inputs/schema','/out/frame'],tool=True)
            require(completed(op),'SElf* replay parity failed: '+op['reason'])
            _out(out,'frame'); require((out/'frame').read_bytes()==artifact.read_bytes(),'SElf* replay direct parity differs')
        if slot['count']>512:
            out,op = call(STATE,{'frame':artifact,'raw':recovered},['exercise','/inputs/frame','/inputs/raw'],tool=True)
            require(completed(op),'SElf* ordered state control failed: '+op['reason']); _out(out)
        if slot['name']=='fixture-1591':
            out,op = call(LIMITS,{'raw':recovered},['limits',str(slot['width']),'/inputs/raw'],tool=True)
            require(completed(op),'SElf* capacity control failed: '+op['reason']); _out(out)
            if slot['method']!=LIVE:
                for label,wire in _mutations(artifact,slot).items():
                    source = work/(label+'.bmk'); source.write_bytes(wire)
                    out,op = call(label,{'frame':source},['/inputs/frame','/out/schema','/out/raw'],operation=ABI_DECODE)
                    require(_status(op,logs,label,5),'SElf* malformed envelope did not reject: '+label); _out(out)
        return _raw(slot,recovered)


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    row = {'product_slot':sid,'status':'cancelled','reason':'cancelled before product','operations':[],
           'artifact':None,'restored':None,'selfstar_validation':None}
    if cancelled(): return row
    logs = run/'logs'/sid; logs.mkdir()
    ops = row['operations']
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-selfstar-encode-') as tmp:
            work = Path(tmp)
            raw,schema = work/'raw',work/'schema'
            plain, = sample.columns
            raw.write_bytes(plain); _raw(slot,raw)
            schema.write_bytes(sample.schema)
            require(sha(sample.schema)==slot['original']['schema_sha256'],'SElf* planned schema differs')
            inputs = {'raw':raw,'schema':schema}
            live = slot['method']==LIVE
            if live:
                out,op = _run(run,plan,slot,work,logs,LIVE_ENCODE,inputs,['live',str(slot['width']),'/inputs/raw','/inputs/schema','/out/frame'],cancelled,ops,tool=True)
            else:
                out,op = _run(run,plan,slot,work,logs,ABI_ENCODE,inputs,['/inputs/schema','/out/frame',str(slot['dtype']),'/inputs/raw'],cancelled,ops)
            if slot['expected_status']:
                require(_status(op,logs,ABI_ENCODE,slot['expected_status']),'SElf* input rejection differs')
                _out(out); row.update(status='expected_rejection',reason=f'plugin status {slot["expected_status"]}'); return row
            require(completed(op),'SElf* encode failed: '+op['reason']); _out(out,'frame')
            encoded = out/'frame'; _boundary(slot,encoded)
            parity = work/'parity'; parity.mkdir()
            alt,op = _run(run,plan,slot,parity,logs,PARITY,inputs,['batch',str(slot['width']),'/inputs/raw','/inputs/schema','/out/frame'],cancelled,ops,tool=True)
            require(completed(op),'SElf* direct batch parity failed: '+op['reason']); _out(alt,'frame'); _boundary(slot,alt/'frame')
            data = encoded.read_bytes()
            require(data==(alt/'frame').read_bytes(),'SElf* direct batch payload differs')
            artifact = run/'products'/(sid+'.bmk')
            with artifact.open('xb') as dst: dst.write(data)
            row['artifact'] = _ref(run,artifact)
        row['restored'] = _restore_checks(run,plan,slot,artifact,logs,cancelled,ops)
        row['selfstar_validation'] = _evidence(slot,artifact,logs)
        row.update(status='verified',reason='')
    except (ContractError,OSError,UnicodeError,ValueError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed' if last=='completed' else 'execution_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    expected = [o for o,_ in operations(slot)]
    logs = run/'logs'/sid
    def valid(op):
        label = op['operation']
        if label in MUTATIONS: return _status(op,logs,label,5)
        if slot['expected_status']: return _status(op,logs,label,slot['expected_status'])
        return completed(op)
    require(set(row)=={'product_slot','status','reason','operations','artifact','restored','selfstar_validation'} and
            [op['operation'] for op in ops]==expected[:len(ops)] and all(valid(op) for op in ops[:-1]),'SElf* ledger operation order differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'SElf* logs missing or over limit')
    ref = row['artifact']
    if ref:
        name = f'products/{sid}.bmk'
        require(not slot['expected_status'] and len(ops)>=2 and all(completed(o) for o in ops[:2]) and
                ref==files.get(name) and ref['path']==name and ref['bytes']<=slot['parts']['frame'],'SElf* retained artifact differs')
        allowed.add(name)
    if row['status']=='verified':
        require(ref and len(ops)==len(expected) and all(valid(op) for op in ops) and not row['reason'] and
                row['restored']=={k:slot['original'][k] for k in ('bytes','sha256')} and
                row['selfstar_validation']==_evidence(slot,run/ref['path'],logs),'SElf* validation evidence differs')
        return True
    if row['status']=='expected_rejection':
        require(slot['expected_status'] and len(ops)==1 and valid(ops[0]) and not ref and
                row['restored'] is None and row['selfstar_validation'] is None and
                row['reason']==f'plugin status {slot["expected_status"]}','SElf* false input rejection')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['selfstar_validation'] is None,'invalid SElf* failure terminal')
    return False


def restore_slot(run,plan,slot,row):
    artifact = verify_asset(run,row['artifact']); _boundary(slot,artifact)
    with tempfile.TemporaryDirectory(prefix='tsbench-selfstar-audit-') as tmp:
        logs = Path(tmp)
        result = _restore_checks(run,plan,slot,artifact,logs,lambda:False,None,audit=True)
        for name,_ in operations(slot):
            # ABI encode and live progress are from original execution. Independent audit
            # re-encodes decoded values through the direct batch control, not as a new sample.
            if name in {ABI_ENCODE,LIVE_ENCODE}: continue
            for ext in ('stdout','stderr'):
                log = f'{name}.{ext}'
                require((logs/log).read_bytes()==(run/'logs'/slot['product_slot']/log).read_bytes(),'SElf* restored operation differs: '+log)
    require(result==row['restored'],'SElf* independent result differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'artifact':row['artifact'],'restored':result}
