"""Execute and replay ALP decode probes without mounting original values in decoders."""
from pathlib import Path
import tempfile

from ..assets import ContractError, canonical_bytes, load_json, require, verify_asset
from ..planner.alp import AVX512, ID
from ..planner.alp_decode import REQUESTS, TOOL, identity, operations, original
from ..qualification.alp import verify_backend_width
from ..qualification.alp_wire import analyze
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref

ERROR = 'requested decode backend unavailable for width/CPU/build'


def _match(got,expected,message):
    require(canonical_bytes(got)==canonical_bytes(expected),message)


def _log(logs,label):
    require(not (logs/(label+'.stderr')).stat().st_size,'unexpected ALP direct control stderr')
    return load_json(logs/(label+'.stdout'))


def _frame_path(slot):
    return f'products/{slot["product_slot"]}.aln1'


def _wire(slot,frame,raw=None):
    require(frame.is_file() and not frame.is_symlink() and 0<frame.stat().st_size<=slot['parts']['frame'],
            'ALP standalone frame outside frozen bound')
    f = slot['fixture']
    wire = analyze(frame.read_bytes(),raw,f['width'],count=f['count'])
    require(wire['rowgroup_kinds']==f['expected_kinds'] and
            [wire[k] for k in ('coded_decimal_vectors','coded_rd_vectors','raw_vectors')]==f['decimal_rd_raw_vectors'],
            'ALP standalone wire branches differ from fixture')
    return wire


def _decode_record(slot,wire,request,doc):
    f = slot['fixture']
    width = f['width']
    caps = doc['caps']
    require(type(caps) is list and len(caps)==len(ID) and all(type(p) is list and len(p)==2 and
            all(type(v) is int and v in (0,1) for v in p) for p in caps),'invalid ALP capability transcript')
    capability = {}
    for name,num in ID.items():
        built,available = map(bool,caps[num])
        reason = ('platform_not_selected' if name in ('falp-neon','falp-sve') else
                  'width_unsupported' if width==32 and name in ('falp-avx2',AVX512) else
                  'not_built' if not built else 'runtime_unavailable' if not available else None)
        cap = {'built_for_width':built,'available':available,'reason':reason}
        if width==64 and name==AVX512:
            cap['runtime_state'] = 'available' if available else 'pending_supported_runtime'
        capability[name] = cap
    verify_backend_width(str(width),capability)
    cap = capability[request]
    record = {'request':request,'capability':cap,'native':doc,'state':'rejected_unavailable'}
    if not cap['available']:
        _match(doc,{'caps':caps,'status':1,'diagnostic':ERROR,'written':0,'width':width,
                    'request':ID[request],'effective':-1,'counts':[0]*5},'ALP backend native rejection differs')
        return record
    effective = (next(n for n in (AVX512,'falp-avx2','falp-scalar') if capability[n]['available'])
                 if request=='falp-auto' else request)
    dec,rd,raw = (wire[k] for k in ('coded_decimal_vectors','coded_rd_vectors','raw_vectors'))
    counts = [dec if effective==name else 0 for name in ('scalar-unfused','falp-scalar','falp-avx2')]+[rd,raw]
    _match(doc,{'caps':caps,'status':0,'diagnostic':'','written':f['count'],'width':width,
                'request':ID[request],'effective':ID[effective],'counts':counts},'ALP native dispatch or branch counters differ')
    return {**record,'state':'restored_bit_exact','dispatch':effective,'decimal_vectors_in_wire':dec,
            'native_decimal_kernel_vectors':None if effective==AVX512 else dec,
            'confirmation':'no_decimal_work_in_wire' if not dec else
            'effective_dispatch_and_bit_exact_no_native_counter' if effective==AVX512 else 'native_decimal_counter_and_bit_exact'}


def _call(run,plan,slot,work,logs,label,key,path,arg,cancelled,ops=None):
    folder = work/label
    folder.mkdir()
    cmd = ['encode' if key=='raw' else 'decode',str(arg),f'/inputs/{key}']
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],TOOL,plan['limits'],folder,logs,label,{key:path},cmd,
                                  cancelled,observe=True)
    op['outputs'] = {}
    if ops is not None:
        ops.append(op)
    require(completed(op),f'ALP {label}: {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    doc = _log(logs,label)
    expected = {'frame'} if key=='raw' else {'raw'} if doc['status']==0 else set()
    require({p.name for p in out.iterdir()}==expected and all(p.is_file() and not p.is_symlink() for p in out.iterdir()),
            'unexpected ALP direct output closure')
    for name in expected:
        op['outputs'][name] = identity((out/name).read_bytes())
    if key=='frame' and expected:
        _match(op['outputs']['raw'],original(slot),'ALP bit-exact detached output differs')
    return out,doc


def _decode_all(run,plan,slot,frame,wire,work,logs,cancelled,ops=None):
    observed, first = {},None
    for request in REQUESTS:
        out,doc = _call(run,plan,slot,work,logs,request,'frame',frame,ID[request],cancelled,ops)
        observed[request] = _decode_record(slot,wire,request,doc)
        if request==REQUESTS[0]:
            first = out/'raw'
    _same_caps(observed)
    return observed,first


def _same_caps(observed):
    require(all(r['native']['caps']==observed[REQUESTS[0]]['native']['caps'] for r in observed.values()),
            'ALP capabilities changed in same-frame requests')


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'frame':None,'decode_backends':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-alp-backends-') as tmp:
            work = Path(tmp)
            raw, = sample.columns
            require(not sample.schema and identity(raw)==original(slot),'ALP original binding differs')
            path = work/'raw'
            path.write_bytes(raw)
            out,doc = _call(run,plan,slot,work,logs,'encode','raw',path,slot['fixture']['width'],cancelled,ops)
            frame = out/'frame'
            wire = _wire(slot,frame,raw)
            _match(doc,{'status':0,'written':frame.stat().st_size},'ALP encoded extent differs')
            observed,_ = _decode_all(run,plan,slot,frame,wire,work,logs,cancelled,ops)
            dest = run/_frame_path(slot)
            with dest.open('xb') as f:
                f.write(frame.read_bytes())
            row.update(status='verified',frame=_ref(run,dest),decode_backends={'wire':wire,'requests':observed})
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        terminal = ops[-1]['status'] if ops else None
        row.update(status=terminal if terminal in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid = slot['product_slot']
    ops = row['operations']
    labels = [name for name,_ in operations(slot)]
    require(set(row)=={'product_slot','status','reason','operations','frame','decode_backends'} and
            len(ops)<=len(labels) and [op['operation'] for op in ops]==labels[:len(ops)] and
            all(completed(op) for op in ops[:-1]) and len({op['session_id'] for op in ops})==len(ops),
            'ALP backend operation order differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{e}' for e in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=plan['limits']['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'ALP backend logs missing or beyond limit')
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['frame'] is None and row['decode_backends'] is None,
                'invalid ALP backend failure terminal')
        return False
    path = _frame_path(slot)
    ref = row['frame']
    require(not row['reason'] and len(ops)==len(labels) and all(completed(op) for op in ops) and
            ref is not None and ref==files.get(path),'incomplete ALP backend evidence')
    allowed.add(path)
    frame = {k:ref[k] for k in ('bytes','sha256')}
    logs = run/'logs'/sid
    wire = _wire(slot,run/path)
    _match(_log(logs,'encode'),{'status':0,'written':ref['bytes']},'ALP encoded extent differs')
    require(ops[0].get('input_mounts')=={'raw':original(slot)} and ops[0]['outputs']=={'frame':frame},
            'ALP encoder input/output closure differs')
    requests = {}
    for req,op in zip(REQUESTS,ops[1:],strict=True):
        require(op.get('input_mounts')=={'frame':frame},'ALP backend recovery may mount only the shared frame')
        observed = requests[req] = _decode_record(slot,wire,req,_log(logs,req))
        require(op['outputs']==({'raw':original(slot)} if observed['state']=='restored_bit_exact' else {}),
                'ALP backend output identity differs')
    _same_caps(requests)
    _match(row['decode_backends'],{'wire':wire,'requests':requests},'ALP backend ledger and transcripts differ')
    return True


def condition_state(criterion,row):
    rows = row['decode_backends']['requests']
    backend = criterion['backend']
    selected = [rows[name] for name in criterion['requests']]
    cap = rows[backend]['capability']
    if not cap['available']:
        return 'pending_supported_runtime' if cap['built_for_width'] else 'pending_supported_build'
    require(all(r['state']=='restored_bit_exact' and r['dispatch']==backend and r['decimal_vectors_in_wire']>0 and
                (r['native_decimal_kernel_vectors']>0 if backend!=AVX512 else r['native_decimal_kernel_vectors'] is None)
                for r in selected),'ALP condition lacks effective decimal work evidence')
    return 'verified_candidate'


def audit_slot(run,plan,slot,row):
    frame = verify_asset(run,row['frame'])
    with tempfile.TemporaryDirectory(prefix='tsbench-alp-backend-audit-') as tmp:
        work = Path(tmp)
        wire = _wire(slot,frame)
        requests,raw = _decode_all(run,plan,slot,frame,wire,work,work,lambda:False)
        _match({'wire':wire,'requests':requests},row['decode_backends'],'ALP replayed backend or host capability differs')
        _wire(slot,frame,raw.read_bytes())
        out,doc = _call(run,plan,slot,work,work,'encode','raw',raw,slot['fixture']['width'],lambda:False)
        _match(doc,{'status':0,'written':row['frame']['bytes']},'ALP replayed encode extent differs')
        _match(identity((out/'frame').read_bytes()),{k:row['frame'][k] for k in ('bytes','sha256')},'ALP replayed ALN1 identity differs')
        return {'product_slot':slot['product_slot'],'frame':row['frame'],'wire':wire,'requests':requests}
