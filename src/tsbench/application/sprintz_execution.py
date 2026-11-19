"""Execute and replay Sprintz batch/query products using only sealed decode inputs."""
import struct
import tempfile
from pathlib import Path

from ..assets import ContractError, canonical_bytes, load_json, require, verify_asset
from ..planner.sprintz import DECODE_REJECTIONS, NATIVE_REJECTIONS, plain, ref
from ..planner.sprintz_execution import (ABI_METHOD, ISA_SKIP, NATIVE_BACKEND, PLUGIN, QUERY, SCHEMA, TOOL, operations)
from ..planner.linear_batch import batch_limits
from ..qualification.sprintz import GROUP_HEADER, check_sfb1, inspect_sfb1
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker
from .selfstar_execution import NONPASS, _out, _status, completed
from .smoke import _ref, _worker_json


class Runner:
    def __init__(self, run, plan, slot, work, logs, cancelled, ops=None):
        self.bundle = run/DIRECTORY
        self.plan,self.slot = plan,slot
        self.work,self.logs,self.cancelled,self.ops = work,logs,cancelled,ops

    def stage(self, name, data):
        p = self.work/name
        p.write_bytes(data)
        return p

    def invoke(self, label, inputs, args, outputs, *, abi=None, status=0, observe=False):
        work = self.work/label
        work.mkdir()
        limits = batch_limits(self.plan,self.slot)
        if abi is None:
            out,row = invoke_isolated_tool(self.bundle,self.plan['decoder'],TOOL,limits,work,self.logs,label,
                                           inputs,args,self.cancelled,observe=observe)
        else:
            out,row = invoke_isolated_worker(self.bundle,self.plan['decoder'],ABI_METHOD,limits,work,self.logs,
                                             abi,inputs,args,self.cancelled,label=label)
        if self.ops is not None:
            self.ops.append(row)
        require(_terminal(row,self.logs,status),'Sprintz operation failed: '+label+': '+row['reason'])
        _out(out,*outputs)
        return out

    def native(self, op, asset, output, *, observe=False):
        params = [str(self.slot['shape'][key]) for key in ('width','dims','message_limit_bytes')]
        return self.invoke('sfb1-'+op,{'input':asset},[op,*params,'/inputs/input',output],
                           [] if output=='-' else [output],observe=observe)


def _terminal(row,logs,status=0):
    return _status(row,logs,row['operation'],status) if status else completed(row)


def _isa_skip(op,logs):
    path = logs/'sfb1-encode.stdout'
    return (op['operation']=='sfb1-encode' and op['status']=='failed' and op['returncode']==77 and
            op['pid'] is not None and path.read_text(encoding='utf-8')==ISA_SKIP+'\n' and
            (logs/'sfb1-encode.stderr').stat().st_size==0)


def _oracle(slot,raw):
    require(ref(slot['original']['path'],raw)==slot['original'],'Sprintz original-byte oracle differs')


def _frame(slot,wire):
    if not slot['abi']:
        return wire
    at = GROUP_HEADER.size+len(SCHEMA)
    require(len(wire)>=at and GROUP_HEADER.unpack_from(wire)==(b'BMKSPR\x01\x00',4,slot['shape']['count'],len(SCHEMA),len(wire)-at)
            and wire[GROUP_HEADER.size:at]==SCHEMA,'Sprintz ABI frame boundary differs')
    return wire[at:]


def _abi_mutations(wire):
    cases = [wire+b'!']
    at = GROUP_HEADER.size+len(SCHEMA)
    for pos in (8,at+12,at+20,len(wire)-1):
        changed = bytearray(wire)
        # Switch U16 to I16 without altering the byte extent: at the cap,
        # changing it to a wider dtype would test size precedence, not dtype.
        changed[pos] = 3 if pos==8 else changed[pos]^1
        cases.append(bytes(changed))
    return dict(zip(DECODE_REJECTIONS,cases,strict=True))


def _query_witness(slot,logs):
    row, = _worker_json(logs/'sfb1-query.stdout',1)
    s = slot['shape']
    lowdim = s['dims'] <= (4 if s['width']==8 else 2)
    denied = ['truncated','trailing','wrong_raw_length','above_message_limit']
    if s['width']==16 and slot['original']['bytes'] < s['message_limit_bytes']:
        denied.append('odd_u16_raw_length')
    require(canonical_bytes(row)==canonical_bytes({
        'auto':{'backend':'scalar' if lowdim else 'upstream_simd',**slot['oracle']},
        'scalar':{'backend':'scalar',**slot['oracle']},'query_rejections':denied,
        'lowdim_forced_simd_rejected':True if lowdim else None}), 'Sprintz reductions, dispatch or refusal differs')
    return row


def _query_product(row):
    return canonical_bytes({'schema':'bmk.sprintz-unsigned-reduction/1',**row['auto']})+b'\n'


def _restore(ex,frame):
    slot = ex.slot
    wire = frame.read_bytes()
    payload = _frame(slot,wire)
    sfb1 = ex.stage('extracted-sfb1',payload) if slot['abi'] else frame
    query = None
    if slot['method']==QUERY:
        # This process has only compressed input, not a plaintext reference or ABI library.
        ex.native('query',sfb1,'-',observe=True)
        query = _query_product(_query_witness(slot,ex.logs))
    restored = (ex.native('decode',sfb1,'raw')/'raw').read_bytes()
    _oracle(slot,restored)
    check_sfb1(payload,slot['shape'],restored)
    if slot['abi']:
        args = ['/inputs/frame','raw','schema']
        out = ex.invoke('decode',{'frame':frame},args,('raw','schema'),abi='decode')
        require((out/'raw').read_bytes()==restored and (out/'schema').read_bytes()==SCHEMA,'Sprintz ABI restore differs')
        for label,mutated in _abi_mutations(wire).items():
            ex.invoke(label,{'frame':ex.stage(label+'.wire',mutated)},args,(),abi='decode',status=5)
    return query


def _evidence(slot,parts,logs,ops):
    shape = slot['shape']
    wire = parts['frame'].read_bytes()
    native = _frame(slot,wire)
    info = inspect_sfb1(native,shape,slot['raw_crc32'])
    original = plain(shape['name'],shape['width'],shape['dims'],shape['count'])
    _oracle(slot,original)
    check_sfb1(native,shape,original)
    direct, = _worker_json(logs/'sfb1-encode.stdout',1)
    # Workspace is native Codec::workspace_capacity(), not a TSBench RSS sample.
    cap = shape['message_limit_bytes']
    require(direct=={'backend':NATIVE_BACKEND,'raw_bytes':slot['original']['bytes'],
                     'workspace_bytes':3*(524288 if cap<=65536 else cap*8+8192),'message_limit_bytes':cap},
            'Sprintz native encoder observation differs')
    result = {'restored':slot['original'],'native_frame':ref('SFB1',native),'layout':info,'encoder':direct,
              'abi_envelope_bytes':len(wire)-len(native),'decoder_rejections':[],'query':None,'native_limit_rejections':[]}
    if slot['abi']:
        enc, = _worker_json(logs/'encode.stdout',1)
        desc,dec = _worker_json(logs/'decode.stdout',2)
        geom = {'algorithm':'fire','lanes':4,'path':'generic_rle','threads':1}
        require(enc=={**geom,'operation':'encode'} and dec=={**geom,'operation':'decode'} and
                desc=={'dtype':4,'count':shape['count']},'Sprintz ABI operation metadata differs')
        result['decoder_rejections'] = DECODE_REJECTIONS
    if slot['method']==QUERY:
        op, = [op for op in ops if op['operation']=='sfb1-query']
        require(op.get('input_mounts')=={'input':{'bytes':len(native),'sha256':result['native_frame']['sha256']}},
                'Sprintz compressed-only query mount differs')
        query = _query_witness(slot,logs)
        require(parts['reductions'].read_bytes()==_query_product(query),'Sprintz retained result differs')
        result['query'] = query
    if slot['method']==PLUGIN and shape['name']=='worker-cap':
        require(load_json(logs/'native-limits.stdout')==NATIVE_REJECTIONS,'Sprintz native limit receipts differ')
        result['native_limit_rejections'] = NATIVE_REJECTIONS
    return result


def _name(slot,key):
    return f'products/{slot["product_slot"]}.{key}'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'operations':ops,'parts':{},'sprintz_validation':None,'reason':'','status':'validation_failed'}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-sprintz-') as tmp:
            ex = Runner(run,plan,slot,Path(tmp),logs,cancelled,ops)
            raw, = sample.columns
            _oracle(slot,raw)
            status = slot['expected_status']
            require(sample.schema==(b'{}' if status else SCHEMA if slot['abi'] else b''),'Sprintz input schema differs')
            source = ex.stage('original',raw)
            if status:
                ex.invoke('encode',{'input':source,'schema':ex.stage('schema',sample.schema)},
                          [str(slot['dtype']),'/inputs/input','/inputs/schema','frame'],(),abi='encode',status=status)
                row.update(status='expected_rejection',reason=f'plugin status {status}')
                return row
            native = ex.native('encode',source,'frame')/'frame'
            frame = native
            if slot['abi']:
                frame = ex.invoke('encode',{'input':source,'schema':ex.stage('schema',sample.schema)},
                                  ['4','/inputs/input','/inputs/schema','frame'],('frame',),abi='encode')/'frame'
                require(_frame(slot,frame.read_bytes())==native.read_bytes(),'Sprintz ABI payload differs from native encode')
            require(frame.stat().st_size<=slot['parts']['frame'],'Sprintz frame exceeds frozen bound')
            query = _restore(ex,frame)
            parts = {'frame':frame}
            if query is not None:
                require(len(query)<=slot['parts']['reductions'],'Sprintz query result exceeds frozen bound')
                parts['reductions'] = ex.stage('reduction.json',query)
            if slot['method']==PLUGIN and slot['shape']['name']=='worker-cap':
                ex.invoke('native-limits',{},['reject'],())
            evidence = _evidence(slot,parts,logs,ops)
            for key,p in parts.items():
                retained = run/_name(slot,key)
                with retained.open('xb') as stream:
                    stream.write(p.read_bytes())
                row['parts'][key] = _ref(run,retained)
            row.update(status='verified',sprintz_validation=evidence)
    except (ContractError, OSError, UnicodeError, ValueError, struct.error, KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        if len(ops)==1 and _isa_skip(ops[0],logs):
            row.update(status='unsupported_platform',reason=ISA_SKIP)
        else:
            row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [name for name,_ in operations(slot)]
    logs = run/'logs'/sid
    state = row['status']
    def valid(op):
        label = op['operation']
        return _terminal(op,logs,slot['expected_status'] or (5 if label in DECODE_REJECTIONS else 0))
    require(set(row)=={'product_slot','operations','parts','sprintz_validation','reason','status'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(valid(op) for op in ops[:-1]) and
            len({op['session_id'] for op in ops})==len(ops),'Sprintz operation evidence differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'Sprintz operation logs missing or over budget')
    require(row['parts'].keys()<=slot['parts'].keys(),'undeclared Sprintz product')
    for k,r in row['parts'].items():
        name = _name(slot,k)
        require(r==files.get(name) and r['bytes']<=slot['parts'][k],'retained Sprintz product differs')
        allowed.add(name)
    if state=='verified':
        parts = {k:run/r['path'] for k,r in row['parts'].items()}
        require(not slot['expected_status'] and not row['reason'] and len(ops)==len(labels) and all(map(valid,ops)) and
                parts.keys()==slot['parts'].keys() and row['sprintz_validation']==_evidence(slot,parts,logs,ops),
                'Sprintz product evidence differs')
        return True
    require(row['sprintz_validation'] is None and row['reason'],'Sprintz failure cannot carry positive evidence')
    if state=='expected_rejection':
        require(slot['expected_status'] and len(ops)==1 and valid(ops[0]) and not row['parts'] and
                row['reason']==f'plugin status {slot["expected_status"]}', 'Sprintz input rejection differs')
        return True
    if state=='unsupported_platform':
        require(not slot['expected_status'] and not row['parts'] and len(ops)==1 and _isa_skip(ops[0],logs) and row['reason']==ISA_SKIP,
                'Sprintz unsupported-platform witness differs')
        return False
    require(state in NONPASS,'invalid Sprintz terminal')
    return False


def restore_slot(run,plan,slot,row):
    frame = verify_asset(run,row['parts']['frame'])
    with tempfile.TemporaryDirectory(prefix='tsbench-sprintz-audit-') as tmp:
        root = Path(tmp)
        logs = root/'logs'
        logs.mkdir()
        ex = Runner(run,plan,slot,root,logs,lambda:False)
        queried = _restore(ex,frame)
        if queried is not None:
            require(queried==verify_asset(run,row['parts']['reductions']).read_bytes(),'Sprintz query replay differs')
        for path in logs.iterdir():
            old = run/'logs'/slot['product_slot']/path.name
            require(path.read_bytes()==old.read_bytes(),'Sprintz detached transcript differs: '+path.name)
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],'restored':slot['original'],
            'query_replayed':queried is not None}
