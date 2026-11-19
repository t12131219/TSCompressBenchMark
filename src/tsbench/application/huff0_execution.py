"""Isolated Huff0 execution; keep the original-byte oracle out of decode mounts."""
from binascii import crc32
from collections import Counter
from pathlib import Path
import struct
import tempfile

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..planner.huff0 import BLOCK, ENVELOPE, FEC, MAGIC, MODE, PLUGIN, RECORD, TABLE, TABLE_REJECTIONS, ref
from ..planner import huff0_bmi2 as bmi2
from ..planner.huff0_execution import TOOL, fec_rejections, fec_schema, operations
from ..planner.linear_batch import batch_limits
from ..qualification.huff0 import _bitstreams, _calls, _model, _weights_size
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker
from .selfstar_execution import NONPASS, _out, _status, completed
from .smoke import _ref, _worker_json


def _matches(raw, expected):
    require(ref(expected['path'],raw)==expected, 'Huff0 original-byte oracle differs')


def _runtime(log):
    compiled, cpu = log['dynamic_bmi2_compiled'],log['cpu_bmi2_available']
    require(type(compiled) is bool and type(cpu) is bool, 'invalid Huff0 backend flags')
    return compiled,cpu


class Execution:
    def __init__(self, run, plan, slot, work, logs, cancelled, ops=None):
        self.bundle, self.plan, self.slot = run/DIRECTORY, plan, slot
        self.work, self.logs, self.cancelled, self.ops = work, logs, cancelled, ops

    def call(self, label, inputs, args, outputs, *, command=None, status=0):
        # Inputs and outputs are disjoint and immutable between processes.
        work = self.work/label
        work.mkdir()
        fixed = (self.bundle,self.plan['decoder'])
        common = (batch_limits(self.plan,self.slot),work,self.logs)
        if command is None:
            op = 'encode' if label=='encode' else 'decode'
            out,row = invoke_isolated_worker(*fixed,{'plugin':PLUGIN,'options':self.slot['options']},*common,
                                             op,inputs,args,self.cancelled,label=label)
        else:
            portable = label==bmi2.OPERATION
            if portable:
                fixed = (self.bundle.parent/bmi2.DIRECTORY,self.plan[bmi2.KEY]['decoder'])
            bind_inputs = bool(self.slot.get(bmi2.KEY) and label in ('fec-decode','table-decode',bmi2.OPERATION))
            out,row = invoke_isolated_tool(*fixed,bmi2.TOOL if portable else TOOL,*common,label,inputs,
                                           [command,*args],self.cancelled,bind_inputs=bind_inputs)
        if self.ops is not None:
            self.ops.append(row)
        require(_exit(row,self.logs,status,abi=command is None),f'Huff0 {label} terminal differs: {row["reason"]}')
        _out(out,*outputs)
        return out

    def stage(self, name, data):
        p = self.work/name
        p.write_bytes(data)
        return p


def _exit(row,logs,status,*,abi):
    label = row['operation']
    if not status:
        return completed(row)
    if abi:
        return _status(row,logs,label,status)
    return (row['status']=='failed' and row['returncode']==1 and row['pid'] is not None and
            (logs/(label+'.stderr')).stat().st_size>0 and (logs/(label+'.stdout')).stat().st_size==0)


def _fec(slot, frame):
    schema = fec_schema(slot['name'])
    n = slot['input']['bytes']
    offset = ENVELOPE.size+len(schema)
    require(offset+FEC.size<=len(frame)<=slot['parts']['frame'] and
            ENVELOPE.unpack_from(frame)==(MAGIC,2,n,len(schema),len(frame)-offset) and
            frame[ENVELOPE.size:offset]==schema,'Huff0 envelope differs')
    payload = frame[offset:]
    modes = slot['modes']
    require(FEC.unpack_from(payload)==(b'FEC1',2,b'\0'*3,BLOCK,n,len(modes)) and len(modes)==(n+BLOCK-1)//BLOCK,
            'Huff0 FEC1 header differs')
    records, pos = [], FEC.size
    for i,mode in enumerate(modes):
        require(pos+RECORD.size<=len(payload),'truncated FEC1 record')
        tag,d,c,crc = RECORD.unpack_from(payload,pos)
        pos += RECORD.size
        body = payload[pos:pos+c]
        require(tag==MODE.index(mode) and d==min(BLOCK,n-i*BLOCK) and 0<c==len(body), 'invalid FEC1 record geometry')
        if mode=='raw':
            require(c==d and crc32(body)==crc,'FEC1 raw extent or CRC differs')
        elif mode=='rle':
            require(c==1 and crc32(body*d)==crc,'FEC1 RLE extent or CRC differs')
        else:
            require(c<d,'FEC1 stored Huffman extent differs')
            _bitstreams(body[_weights_size(body):],4)
        records.append({'mode':mode,'decoded_bytes':d,'encoded_bytes':c,'crc32':crc})
        pos += c
    require(pos==len(payload),'unaccounted FEC1 bytes')
    return schema,payload,records


def _fec_mutations(frame,schema,payload,n):
    def wrap(data,count=n):
        return ENVELOPE.pack(MAGIC,2,count,len(schema),len(data))+schema+data
    rows = {'envelope-truncated':frame[:-1],'unexpected-algorithm':wrap(payload[:4]+b'\x01'+payload[5:]),
            'declared-size-mismatch':wrap(payload[:12]+struct.pack('<Q',n+1)+payload[20:]),
            'trailing-byte':wrap(payload+b'\0'),'envelope-size-limit':wrap(payload,(64<<20)+1)}
    if n:
        p = FEC.size
        rows['illegal-mode'] = wrap(payload[:p]+b'\xff'+payload[p+1:])
        p += 9
        rows['crc-mismatch'] = wrap(payload[:p]+bytes([payload[p]^1])+payload[p+1:])
    return rows


def _encode_fec(ex,sample):
    slot = ex.slot
    plain, = sample.columns
    _matches(plain,slot['input'])
    status = slot['expected_status']
    require(sample.schema==(b'{}' if status else fec_schema(slot['name'])), 'Huff0 original schema differs')
    inputs = {'raw':ex.stage('raw',plain),'schema':ex.stage('schema',sample.schema)}
    out = ex.call('encode',inputs,[str(slot['dtype']),'/inputs/raw','/inputs/schema','frame'],
                  () if status else ('frame',),status=status)
    if status:
        return None
    schema,payload,_ = _fec(slot,(out/'frame').read_bytes())
    direct = ex.call('fec-encode',{'raw':inputs['raw']},['/inputs/raw','fec'],('fec',),command='fec-encode')
    require((direct/'fec').read_bytes()==payload,'Huff0 ABI payload differs from direct FEC1')
    return {'frame':out/'frame'},{}


def _restore_fec(ex,parts):
    slot, frame = ex.slot, parts['frame'].read_bytes()
    schema,payload,records = _fec(slot,frame)
    mounts, args = {'fec':ex.stage('payload',payload)},['/inputs/fec','raw']
    out = ex.call('fec-decode',mounts,args,('raw',),command='fec-decode')
    data = (out/'raw').read_bytes()
    _matches(data,slot['input'])
    require(all(crc32(data[i*BLOCK:(i+1)*BLOCK])==r['crc32'] for i,r in enumerate(records)), 'FEC1 decoded CRC differs')
    if slot.get(bmi2.KEY):
        control = ex.call(bmi2.OPERATION,mounts,args,('raw',),command='fec-decode')
        require((control/'raw').read_bytes()==data,'Huff0 portable FEC1 restored bytes differ')
    out = ex.call('decode',{'frame':parts['frame']},['/inputs/frame','raw','schema'],('raw','schema'))
    require((out/'raw').read_bytes()==data and (out/'schema').read_bytes()==schema,'Huff0 ABI restore differs')
    for label,bad in _fec_mutations(frame,schema,payload,len(data)).items():
        ex.call(label,{'frame':ex.stage(label+'.bad',bad)},['/inputs/frame','raw','schema'],(),status=fec_rejections(slot)[label])


def _block_keys(slot):
    return [f'block-{i}' for i in range(len(slot['blocks']))]


def _model_binding(slot, model, blocks):
    # The ETB1 block wire has no in-band model identifier; this exact persisted
    # sidecar is mandatory for selecting a decoder model.
    def asset(path):
        return {'bytes':path.stat().st_size,'sha256':_ref(path.parent,path)['sha256']}
    return canonical_bytes({'schema':'bmk.etb1-model-binding/1','product_slot':slot['product_slot'],'streams':slot['streams'],
                            'model':asset(model),'blocks':[asset(p) for p in blocks]})+b'\n'


def _encode_table(ex,sample):
    slot, keys = ex.slot, _block_keys(ex.slot)
    _matches(sample.schema,slot['training'])
    train = ex.stage('training',sample.schema)
    model = ex.call('train',{'input':train},[str(slot['streams']),'/inputs/input','table'],('table',),command='train')/'table'
    inputs,args = {'model':model},['/inputs/model']
    for key,data,original in zip(keys,sample.columns,slot['blocks'],strict=True):
        _matches(data,original)
        inputs['raw-'+key] = ex.stage('raw-'+key,data)
        args += ['/inputs/raw-'+key,key]
    out = ex.call('table-encode',inputs,args,keys,command='table-encode')
    alt = ex.call('train-alternate',{'input':ex.stage('other-training',b'\xff'*BLOCK)},
                  [str(slot['streams']),'/inputs/input','table'],('table',),command='train')/'table'
    blocks = [out/k for k in keys]
    sidecar = ex.stage('binding.json',_model_binding(slot,model,blocks))
    return {'model':model,'binding':sidecar,**dict(zip(keys,blocks,strict=True))},{'alternate':alt}


def _table_wire(slot,parts,controls):
    model, alt = parts['model'].read_bytes(),controls['alternate'].read_bytes()
    log,other_log = _model(model,slot['streams']),_model(alt,slot['streams'])
    keys = _block_keys(slot)
    blocks = [parts[k] for k in keys]
    binding = parts['binding'].read_bytes()
    require(binding==_model_binding(slot,parts['model'],blocks), 'ETB1 expected model/block binding differs')
    # Exercise the same binding check with a structurally valid alternate.
    require(binding!=_model_binding(slot,controls['alternate'],blocks), 'ETB1 alternate satisfied the model binding')
    records = []
    for path,original,mode in zip(blocks,slot['blocks'],slot['modes'],strict=True):
        raw = path.read_bytes()
        require(len(raw)>=TABLE.size,'missing ETB1 block header')
        tag,n,c = TABLE.unpack_from(raw)
        require(n==original['bytes'] and len(raw)==TABLE.size+c and tag==int(mode=='huffman'), 'ETB1 stored length or mode differs')
        if mode=='huffman':
            require(0<c<n,'invalid ETB1 compressed extent')
            _bitstreams(raw[TABLE.size:],slot['streams'])
        else:
            _matches(raw[TABLE.size:],original)
        records.append({'mode':mode,'stored_original_bytes':n,'body_bytes':c,'header_bytes':TABLE.size})
    return log,other_log,records


def _restore_table(ex,parts,controls):
    slot, keys = ex.slot, _block_keys(ex.slot)
    _table_wire(slot,parts,controls)
    empty = ex.stage('empty-block',TABLE.pack(0,0,0))
    out = ex.call('load-alternate',{'model':controls['alternate'],'block':empty},
                  ['/inputs/model','/inputs/block','raw'],('raw',),command='table-decode')
    require((out/'raw').read_bytes()==b'', 'ETB1 alternate model did not load')
    model = parts['model']
    args = ['/inputs/model',*(arg for key in reversed(keys) for arg in ('/inputs/'+key,key))]
    mounts = {'model':model,**{k:parts[k] for k in keys}}
    out = ex.call('table-decode',mounts,args,keys,command='table-decode')
    if slot.get(bmi2.KEY):
        control = ex.call(bmi2.OPERATION,mounts,args,keys,command='table-decode')
        require(all((control/k).read_bytes()==(out/k).read_bytes() for k in keys),'Huff0 portable ETB1 restored bytes differ')
    for key,original in zip(keys,slot['blocks'],strict=True):
        _matches((out/key).read_bytes(),original)
    first = parts[keys[slot['modes'].index('huffman')]]
    raw, m = first.read_bytes(),model.read_bytes()
    bad = {'missing-table':(None,first),
           'unexpected-stream-tag':(ex.stage('bad-model',m[:6]+b'\x02'+m[7:]),first),
           'truncated-model':(ex.stage('short-model',m[:7]),first),
           'block-truncated':(model,ex.stage('short-block',raw[:-1])),
           'invalid-length-field':(model,ex.stage('bad-length',raw[:5]+struct.pack('<I',len(raw)-TABLE.size+1)+raw[TABLE.size:])),
           'decoded-value-limit':(model,ex.stage('bad-count',raw[:1]+struct.pack('<I',BLOCK+1)+raw[5:]))}
    for label,(asset,block) in bad.items():
        ex.call(label,{'block':block,**({'model':asset} if asset else {})},['/inputs/model','/inputs/block','raw'],(),
                command='table-decode',status=1)
    if slot['profile']=='synthetic':
        i = slot['modes'].index('raw')
        wire = parts[keys[i]].read_bytes()
        changed = bytes([wire[TABLE.size]^1])+wire[TABLE.size+1:]
        out = ex.call('raw-mutation',{'model':model,'block':ex.stage('changed-block',wire[:TABLE.size]+changed)},
                      ['/inputs/model','/inputs/block','raw'],('raw',),command='table-decode')
        require((out/'raw').read_bytes()==changed and ref(slot['blocks'][i]['path'],changed)!=slot['blocks'][i],
                'ETB1 changed raw literal did not expose the lack of CRC')


def _comparison(slot,parts,logs,ops):
    if not slot.get(bmi2.KEY):
        return {}
    fec = slot['method']==PLUGIN
    label = 'fec-decode' if fec else 'table-decode'
    by_op = {op['operation']:op for op in ops}
    primary, = _worker_json(logs/(label+'.stdout'),1)
    portable, = _worker_json(logs/(bmi2.OPERATION+'.stdout'),1)
    compiled, cpu = _runtime(primary)
    require(compiled and _runtime(portable)==(False,cpu),'Huff0 comparison requires observed ON/OFF backends on the same host')
    def mount(data):
        return {'bytes':len(data),'sha256':ref('',data)['sha256']}
    if fec:
        _,payload,_ = _fec(slot,parts['frame'].read_bytes())
        mounts = {'fec':mount(payload)}
        entry, streams, log = 0, 0, 0
    else:
        mounts = {k:mount(parts[k].read_bytes()) for k in ('model',*_block_keys(slot))}
        streams = slot['streams']
        entry = 1 if streams==1 else 2
        log = _model(parts['model'].read_bytes(),streams)
    require(all(by_op[name].get('input_mounts')==mounts for name in (label,bmi2.OPERATION)),
            'Huff0 portable and primary mounts must be the same retained payloads and model')
    n = slot['modes'].count('huffman')
    entries = _calls(portable,(False,cpu),entry,n,streams,log)
    return {'bmi2_comparison':{'retained_input_mounts':mounts,'portable_runtime':portable,
                               'portable_decode_entries':entries}}


def _evidence(slot,parts,controls,logs,ops):
    def read(label):
        row, = _worker_json(logs/(label+'.stdout'),1)
        return row
    if slot['method']==PLUGIN:
        schema,payload,records = _fec(slot,parts['frame'].read_bytes())
        dec,enc = read('fec-decode'),read('fec-encode')
        modes = Counter(slot['modes'])
        runtime = _runtime(dec)
        _calls(enc,runtime,0,0)
        entries = _calls(dec,runtime,0,modes['huffman'])
        geometry = {'mode':'batch','threads':1,'blocks':len(records),'fallback':bool(modes['raw']),
                    **{f'{key}_blocks':modes[key] for key in MODE}}
        shape,observation = _worker_json(logs/'decode.stdout',2)
        require(shape=={'dtype':2,'count':slot['input']['bytes']} and
                observation==dict(geometry,operation='decode',backend=dec['cpu_backend'] if modes['huffman'] else 'no-huffman-decode') and
                read('encode')==dict(geometry,operation='encode',backend='huff0-reference-encode'), 'Huff0 FEC1 observation differs')
        return {'original':slot['input'],'schema_bytes':len(schema),'envelope_bytes':ENVELOPE.size,
                'fec_header_bytes':FEC.size,'fec_record_bytes':len(records)*RECORD.size,'fec_bytes':len(payload),
                'records':records,'native_decode_entries':entries,'rejected':fec_rejections(slot),
                'direct_payload_sha256':ref('',payload)['sha256'],'runtime':dec,**_comparison(slot,parts,logs,ops)}
    log,other,records = _table_wire(slot,parts,controls)
    streams = slot['streams']
    entry = 1 if streams==1 else 2
    dec = read('table-decode')
    runtime = _runtime(dec)
    entries = _calls(dec,runtime,entry,slot['modes'].count('huffman'),streams,log)
    for label,effective in [('train',log),('train-alternate',other),('load-alternate',other),
                            *([('raw-mutation',log)] if slot['profile']=='synthetic' else [])]:
        _calls(read(label),runtime,entry,0,streams,effective)
    enc = read('table-encode')
    count = sum(x['bytes']>1 for x in slot['blocks'])
    require(enc['table_encode_calls']==([count,0] if streams==1 else [0,count]),'ETB1 CTable calls differ')
    _calls(dict(enc,table_encode_calls=[0,0]),runtime,entry,0,streams,log)
    charged = {key:path.stat().st_size for key,path in parts.items()}
    return {'training':slot['training'],'blocks':records,'decode_order':list(reversed(range(len(records)))),
            'model_and_blocks_and_binding_bytes':sum(charged.values()),'bytes_by_part':charged,
            'alternate_control_bytes':controls['alternate'].stat().st_size,'alternate_rejected_by_model_binding':True,
            'raw_mutation_native_success_oracle_rejected':slot['profile']=='synthetic',
            'native_decode_entries':entries,'table_encode_calls':enc['table_encode_calls'],
            'rejected':TABLE_REJECTIONS,'runtime':dec,**_comparison(slot,parts,logs,ops)}


def _name(sid,key,*,control=False):
    return f'{"controls" if control else "products"}/{sid}.{key}'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'controls':{},'huff0_validation':None}
    fec = slot['method']==PLUGIN
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-huff0-') as tmp:
            ex = Execution(run,plan,slot,Path(tmp),logs,cancelled,ops)
            encoded = (_encode_fec if fec else _encode_table)(ex,sample)
            if slot['expected_status']:
                row.update(status='expected_rejection',reason=f'plugin status {slot["expected_status"]}')
                return row
            parts,controls = encoded
            require(set(parts)==slot['parts'].keys() and all(path.stat().st_size<=slot['parts'][k] for k,path in parts.items()),
                    'Huff0 retained products exceed limits')
            require(controls.keys()==(set() if fec else {'alternate'}) and all(p.stat().st_size<=1024 for p in controls.values()),
                    'Huff0 retained controls exceed limits')
            if fec:
                _restore_fec(ex,parts)
            else:
                _restore_table(ex,parts,controls)
            evidence = _evidence(slot,parts,controls,logs,ops)
            for group,paths in [('parts',parts),('controls',controls)]:
                for key,src in paths.items():
                    p = run/_name(sid,key,control=group=='controls')
                    with p.open('xb') as f:
                        f.write(src.read_bytes())
                    row[group][key] = _ref(run,p)
            row.update(status='verified',huff0_validation=evidence)
    except (ContractError,OSError,ValueError,struct.error,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    declared = operations(slot)
    logs = run/'logs'/sid
    fec = slot['method']==PLUGIN
    def valid(op,spec):
        key,tool = spec
        expected = slot['expected_status'] or (fec_rejections(slot).get(key,0) if fec else TABLE_REJECTIONS.get(key,0))
        return _exit(op,logs,expected,abi=not tool)
    require(set(row)=={'product_slot','status','reason','operations','parts','controls','huff0_validation'} and
            [op['operation'] for op in ops]==[key for key,_ in declared[:len(ops)]] and
            all(valid(op,spec) for op,spec in zip(ops[:-1],declared)), 'Huff0 operation transcript order differs')
    require(len({op['session_id'] for op in ops})==len(ops),'Huff0 operation session reused')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()), 'Huff0 logs missing or over limit')
    for group,bounds in [('parts',slot['parts']),('controls',{} if fec else {'alternate':1024})]:
        require(row[group].keys()<=bounds.keys(),'Huff0 undeclared retained asset')
        for k,r in row[group].items():
            name = _name(sid,k,control=group=='controls')
            require(r==files.get(name) and r['bytes']<=bounds[k],'Huff0 retained asset differs')
            allowed.add(name)
    if row['status']=='verified':
        parts,controls = ({k:run/r['path'] for k,r in row[group].items()} for group in ('parts','controls'))
        require(not slot['expected_status'] and len(ops)==len(declared) and all(valid(o,s) for o,s in zip(ops,declared,strict=True)) and
                not row['reason'] and parts.keys()==slot['parts'].keys() and controls.keys()==(set() if fec else {'alternate'}) and
                row['huff0_validation']==_evidence(slot,parts,controls,logs,ops),'Huff0 validation evidence differs')
        return True
    if row['status']=='expected_rejection':
        require(slot['expected_status'] and len(ops)==1 and valid(ops[0],declared[0]) and
                row['reason']==f'plugin status {slot["expected_status"]}' and not row['parts'] and not row['controls'] and
                row['huff0_validation'] is None, 'invalid Huff0 input rejection evidence')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['huff0_validation'] is None, 'invalid Huff0 failure terminal')
    return False


def restore_slot(run,plan,slot,row):
    parts,controls = ({k:verify_asset(run,r) for k,r in row[group].items()} for group in ('parts','controls'))
    original_logs = run/'logs'/slot['product_slot']
    ops = []
    with tempfile.TemporaryDirectory(prefix='tsbench-huff0-audit-') as tmp:
        logs = Path(tmp)/'logs'
        logs.mkdir()
        ex = Execution(run,plan,slot,Path(tmp),logs,lambda:False,ops)
        if slot['method']==PLUGIN:
            _restore_fec(ex,parts)
        else:
            _restore_table(ex,parts,controls)
        for log in logs.iterdir():
            require(log.read_bytes()==(original_logs/log.name).read_bytes(),'Huff0 detached transcript differs: '+log.name)
        comparison = _comparison(slot,parts,logs,ops)
        require(comparison=={k:row['huff0_validation'][k] for k in comparison},'Huff0 detached runtime comparison differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],**comparison,
            'originals':[slot['input']] if slot['method']==PLUGIN else slot['blocks']}



def condition_evidence(rows):
    from ..qualification.huff0 import DECODE_API
    require(len(rows)==9 and all(r['status']=='verified' for r in rows),'Huff0 BMI2 condition has missing work')
    reports = [r['huff0_validation'] for r in rows]
    available = {r['runtime']['cpu_bmi2_available'] for r in reports}
    require(len(available)==1,'Huff0 CPU feature report differs across same-run processes')
    cpu, = available
    fields = ('bmi2_arg_0','bmi2_arg_1')
    def counts(evidence):
        return {key:{arg:sum(r[key][arg] for r in evidence) for arg in fields} for key in DECODE_API}
    primary = counts([r['native_decode_entries'] for r in reports])
    portable = counts([r['bmi2_comparison']['portable_decode_entries'] for r in reports])
    for key,n in zip(DECODE_API,(3,4,4),strict=True):
        require(primary[key]=={fields[0]:0 if cpu else n,fields[1]:n if cpu else 0} and
                portable[key]=={fields[0]:n,fields[1]:0}, 'Huff0 condition actual native call census differs')
    return {'state':'verified_candidate' if cpu else 'pending_supported_runtime',
            'reason':'' if cpu else 'host_bmi2_unavailable', 'cpu_bmi2_available':cpu,
            'primary_completed_decode_calls':primary,'portable_completed_decode_calls':portable}
