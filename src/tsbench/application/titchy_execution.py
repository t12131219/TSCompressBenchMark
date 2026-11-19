"""Execute original Titchy access APIs and audit actual per-operation callback demand."""
from pathlib import Path
import tempfile

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..planner.linear_batch import batch_limits
from ..planner.titchy_access import SCOPE, expected_queries, logical_result_bits
from ..planner.titchy_execution import LOADED, TOOL, operations
from ..planner.titchy_native import BATCH_POLICY, KNOWN_REJECTIONS, sha, words
from ..planner.typed_batch import TITCHY_TOOL
from ..qualification.titchy_access import _read_budget
from ..qualification.titchy_wire import decode_tchy, native_bound
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, _out, completed
from .smoke import _ref, _worker_json


def _container(slot,path):
    raw = path.read_bytes()
    n = slot['window']['count']
    require(86<len(raw)<=min(slot['parts']['backing'],native_bound(n,64,4,1000)), 'Titchy backing outside frozen bound')
    original,splits = decode_tchy(raw,64,n,BATCH_POLICY)
    require(len(splits)==2 and slot['original']=={'bytes':len(original),'sha256':sha(original)},
            'Titchy detached full decode disagrees with original bits')
    values = words(original)
    out = expected_queries(values,slot['request'])
    require(canonical_bytes(slot['expected'])==canonical_bytes(out if slot['method']==LOADED else out['range']),
            'Titchy access oracle not bound to the original range')
    return raw,splits,values[0]


def _invoke(run,plan,slot,work,logs,label,inputs,args,output,cancelled,ops):
    folder = work/label
    folder.mkdir()
    tool = TITCHY_TOOL if label=='tchy-encode' else TOOL
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],tool,batch_limits(plan,slot),folder,logs,label,inputs,args,cancelled,
                                 observe=label!='tchy-encode')
    if ops is not None:
        ops.append(op)
    require(completed(op),f'Titchy {label} failed: {op["reason"]}')
    _out(out,*output)
    return out


def _access(run,plan,slot,work,logs,backing,cancelled,ops):
    req = slot['request']
    args = ['/inputs/backing',*map(str,(slot['window']['count'],req['point'],*req['range'],*req['bits']))]
    for label,_ in operations(slot)[1:]:
        _invoke(run,plan,slot,work,logs,label,{'backing':backing},[label,*args],(),cancelled,ops)


def _failure_trace(row,calls,message):
    require(row=={'calls':calls,'requested_bytes':sum(c[1] for c in calls),
                 'successful_bytes':sum(c[1] for c in calls if c[2])},message)


def _reports(slot,backing,logs,ops=None):
    raw,splits,prefix = _container(slot,backing)
    size = len(raw)
    later = splits[1]['offset']
    limits,req = slot['limits'],slot['request']
    def read(label):
        row, = _worker_json(logs/(label+'.stdout'),1)
        return row
    if ops is not None:
        require(all(op.get('input_mounts')=={'backing':{'bytes':size,'sha256':sha(raw)}} for op in ops[1:]),
                'Titchy access must mount only its immutable backing')
    statuses = KNOWN_REJECTIONS['access']
    mutated = raw[:later]+b'\xff'+raw[later+1:]
    result = {'original':slot['original'],'split_count':len(splits),'backing_bytes':size,
              'pair_mutation_sha256':sha(mutated), 'scope':'whole_container_validation' if slot['method']!=LOADED else SCOPE}
    if slot['method']==LOADED:
        load,file = read('loaded'),read('file')
        require(set(load)=={'count','open','results','reads','statuses','denied_index','bad_index','denied_pair','touched_pair','prefix','prefix_reads'}
                and load['count']==slot['window']['count'] and load['results']==[slot['expected']]*2 and load['prefix']==prefix and
                file=={'result':slot['expected'],'file_quota':statuses['file_quota'],'file_missing':statuses['file_missing']},
                'Titchy loaded/file query result differs')
        _read_budget(load['open'],limits['open'],size,'open')
        require(load['open']['calls']==[[0,38,True],[38,48,True]], 'Titchy open did not read exactly header and index')
        first,second = load['reads']
        bits = logical_result_bits(req)
        require(first==second and set(first)==bits.keys(), 'Titchy repeated immutable reader ledger differs')
        for label,logical in bits.items():
            _read_budget(first[label],limits['bit' if label.startswith('bit-') else label],size,label,logical)
        require(first['point']['requested_bytes']<first['range']['requested_bytes'], 'Titchy point did not read less than range')
        _failure_trace(load['denied_index'],[[0,38,True],[38,48,False]],'Titchy failed index callback trace differs')
        _failure_trace(load['bad_index'],[[0,38,True],[38,48,True]],'Titchy malformed index trace differs')
        _failure_trace(load['denied_pair'],[[later,8,False]],'Titchy failed pair callback trace differs')
        _failure_trace(load['touched_pair'],[[later,8,True]],'Titchy malformed pair trace differs')
        _read_budget(load['prefix_reads'],limits['point'],size,'valid prefix',64)
        require(all(o+n<=later for o,n,_ in load['prefix_reads']['calls']), 'Titchy valid prefix touched the damaged split')
        loaded_keys = ('reader_sample_oob','reader_bit_oob','reader_capacity','reader_range_oob','pair_callback_failure','touched_bad_pair')
        require(load['statuses']=={**{k:statuses[k] for k in loaded_keys},'empty_eof':0},'Titchy loaded native status differs')
        result.update(loaded=load,file=file,index_mutation_sha256=sha(raw[:38]+bytes([raw[38]^1])+raw[39:]))
        return result, {'schema':'bmk.titchy-access-result/1','access':load['results'][0]}
    stateless = read('range')
    require(stateless=={'result':slot['expected'],'statuses':{'empty_eof':0,
            **{k:v for k,v in statuses.items() if k.startswith('stateless_')}}}, 'Titchy stateless range value or validation status differs')
    result.update(stateless=stateless, read_at_bytes=None)
    return result, {'schema':'bmk.titchy-access-result/1','range':stateless['result']}


def _encoding(slot,backing,logs):
    n = slot['window']['count']
    enc, = _worker_json(logs/'tchy-encode.stdout',1)
    require(enc=={'count':n,'bytes':backing.stat().st_size,'bound':native_bound(n,64,4,1000),
                 'encode_capacity_status':2,'decode_capacity_status':2,'decode_quota_status':2},
            'Titchy native generation metadata differs')


def _name(sid,key):
    return f'products/{sid}.{key}'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'titchy_access':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-tchy-access-') as tmp:
            work = Path(tmp)
            raw, = sample.columns
            require(not sample.schema and slot['original']=={'bytes':len(raw),'sha256':sha(raw)}, 'Titchy staged original differs')
            source = work/'original'
            source.write_bytes(raw)
            backing = _invoke(run,plan,slot,work,logs,'tchy-encode',{'input':source},['64','/inputs/input','backing'],
                              ('backing',),cancelled,ops)/'backing'
            _container(slot,backing)
            _encoding(slot,backing,logs)
            _access(run,plan,slot,work,logs,backing,cancelled,ops)
            info,result = _reports(slot,backing,logs,ops)
            outputs = {'backing':backing.read_bytes(),'answer':canonical_bytes(result)+b'\n'}
            require(all(len(v)<=slot['parts'][k] for k,v in outputs.items()), 'Titchy retained product exceeds ceiling')
            for k,v in outputs.items():
                p = run/_name(sid,k)
                with p.open('xb') as f:
                    f.write(v)
                row['parts'][k] = _ref(run,p)
            row.update(status='verified',titchy_access=info)
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [label for label,_ in operations(slot)]
    logs = run/'logs'/sid
    require(set(row)=={'product_slot','status','reason','operations','parts','titchy_access'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(map(completed,ops[:-1])) and
            len({op['session_id'] for op in ops})==len(ops),'Titchy access operation evidence differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{e}' for e in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'Titchy access logs missing or beyond limits')
    require(row['parts'].keys()<=slot['parts'].keys(),'undeclared Titchy product')
    for k,r in row['parts'].items():
        p = _name(sid,k)
        require(r==files.get(p) and r['bytes']<=slot['parts'][k], 'Titchy retained product differs')
        allowed.add(p)
    if row['status']=='verified':
        require(not row['reason'] and len(ops)==len(labels) and all(map(completed,ops)) and row['parts'].keys()==slot['parts'].keys(),
                'incomplete Titchy access evidence')
        backing,answer = (run/row['parts'][k]['path'] for k in ('backing','answer'))
        _encoding(slot,backing,logs)
        info,result = _reports(slot,backing,logs,ops)
        require(canonical_bytes(row['titchy_access'])==canonical_bytes(info) and answer.read_bytes()==canonical_bytes(result)+b'\n',
                'Titchy access result or accounting differs')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['titchy_access'] is None,'invalid Titchy access terminal')
    return False


def restore_slot(run,plan,slot,row):
    backing,answer = (verify_asset(run,row['parts'][k]) for k in ('backing','answer'))
    with tempfile.TemporaryDirectory(prefix='tsbench-tchy-access-audit-') as tmp:
        work = Path(tmp)
        logs = work/'logs'
        logs.mkdir()
        _access(run,plan,slot,work,logs,backing,lambda:False,None)
        info,result = _reports(slot,backing,logs)
        require(info==row['titchy_access'] and answer.read_bytes()==canonical_bytes(result)+b'\n','Titchy access audit differs')
        for p in logs.iterdir():
            require(p.read_bytes()==(run/'logs'/slot['product_slot']/p.name).read_bytes(),'Titchy access detached transcript differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],'restored':slot['original'],
            'access_replayed':True}
