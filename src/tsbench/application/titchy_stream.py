"""Run Titchy push/pop and file-only restoration as separately isolated operations."""
import tempfile
from pathlib import Path

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..planner.linear_batch import batch_limits
from ..planner.titchy_native import sha
from ..planner.titchy_stream import TOOL, operations
from ..qualification.titchy_native import stream_evidence
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref, _worker_json


def _invoke(run,plan,slot,work,logs,label,inputs,mode,expected,cancelled,ops=None):
    work.mkdir()
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],TOOL,batch_limits(plan,slot),work,logs,label,inputs,
                                 [mode],cancelled,observe=True)
    if ops is not None:
        ops.append(op)
    require(completed(op),f'Titchy {label} failed: {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(expected) and all(p.is_file() and not p.is_symlink() for p in out.iterdir()),
            'unexpected isolated Titchy stream output')
    return out


def _reference(slot,parts):
    for k,p in parts.items():
        require(0<p.stat().st_size<=slot['parts'][k],f'Titchy {k} exceeds frozen wire bound')
    return stream_evidence(parts['archive'].read_bytes(),parts['config'].read_bytes(),slot['stream'],slot['policy'],slot['status_policy'])


def _match(row,expected,message):
    require(canonical_bytes(row)==canonical_bytes(expected),message)


def _reports(logs,expected):
    enc, = _worker_json(logs/'packet-encode.stdout',1)
    dec, = _worker_json(logs/'packet-decode.stdout',1)
    dec_keys = {'small_output_retry','truncated_packet','decode_after_corruption','tail_quota','decode_after_quota'}
    _match(enc,{**{k:expected[k] for k in ('emitted_after_push','finished_samples','max_active_bases',
                                          'max_ready_packets_observed','dictionary_bases')},
                'reset_identical':True,'statuses':{k:v for k,v in expected['statuses'].items() if k not in dec_keys}},
           'Titchy stream encoder transcript differs')
    _match(dec,{'true_values':expected['true_values'],'padded_values':expected['padded_values'],'decoder_reset_checked':True,
                'statuses':{k:expected['statuses'][k] for k in dec_keys}},'Titchy stream decoder transcript differs')


def _bits(slot,path):
    require(path.stat().st_size==slot['original']['bytes'] and sha(path.read_bytes())==slot['original']['sha256'],
            'Titchy stream detached native decoder differs from frozen original')


def _output(slot,key):
    return f'products/{slot["product_slot"]}.{key}'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logs = run/'logs'/sid
    logs.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'titchy_stream':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-titchy-stream-') as tmp:
            work = Path(tmp)
            raw, = sample.columns
            require(not sample.schema and slot['original']=={'bytes':len(raw),'sha256':sha(raw)},'Titchy stream source differs')
            source = work/'source'
            source.write_bytes(raw)
            out = _invoke(run,plan,slot,work/'encoder',logs,'packet-encode',{'input':source},'encode',slot['parts'],cancelled,ops)
            source.unlink()
            parts = {k:out/k for k in slot['parts']}
            expected = _reference(slot,parts)
            decoded = _invoke(run,plan,slot,work/'decoder',logs,'packet-decode',parts,'decode',('v',),cancelled,ops)
            _bits(slot,decoded/'v')
            _reports(logs,expected)
            for k,p in parts.items():
                dst = run/_output(slot,k)
                with dst.open('xb') as f:
                    f.write(p.read_bytes())
                row['parts'][k] = _ref(run,dst)
            row.update(status='verified',titchy_stream=expected)
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops = slot['product_slot'],row['operations']
    labels = [label for label,_ in operations(slot)]
    require(set(row)=={'product_slot','status','reason','operations','parts','titchy_stream'} and
            [op['operation'] for op in ops]==labels[:len(ops)] and all(map(completed,ops[:-1])) and
            len({op['session_id'] for op in ops})==len(ops),'Titchy stream operation closure differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{e}' for e in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=batch_limits(plan,slot)['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'Titchy stream logs missing or outside limit')
    require(row['parts'].keys()<=slot['parts'].keys(),'undeclared Titchy stream output')
    for k,ref in row['parts'].items():
        p = _output(slot,k)
        require(ref==files.get(p) and ref['bytes']<=slot['parts'][k],'Titchy stream retained part differs')
        allowed.add(p)
    if row['status']=='verified':
        require(not row['reason'] and len(ops)==2 and all(map(completed,ops)) and row['parts'].keys()==slot['parts'].keys(),
                'incomplete Titchy stream evidence')
        require(ops[0].get('input_mounts')=={'input':slot['original']} and ops[1].get('input_mounts')=={
                k:{n:r[n] for n in ('bytes','sha256')} for k,r in row['parts'].items()},'Titchy stream inputs are not separated')
        expected = _reference(slot,{k:run/r['path'] for k,r in row['parts'].items()})
        _reports(run/'logs'/sid,expected)
        _match(row['titchy_stream'],expected,'Titchy stream wire/accounting evidence differs')
        return True
    require(row['status'] in NONPASS and row['reason'] and row['titchy_stream'] is None,'invalid Titchy stream terminal')
    return False


def restore_slot(run,plan,slot,row):
    parts = {k:verify_asset(run,r) for k,r in row['parts'].items()}
    with tempfile.TemporaryDirectory(prefix='tsbench-titchy-stream-restore-') as tmp:
        work = Path(tmp)
        out = _invoke(run,plan,slot,work/'decoder',work,'packet-decode',parts,'decode',('v',),lambda:False)
        _bits(slot,out/'v')
        for ext in ('stdout','stderr'):
            name = f'packet-decode.{ext}'
            require((work/name).read_bytes()==(run/'logs'/slot['product_slot']/name).read_bytes(),
                    'Titchy stream detached decoder transcript differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],'restored':slot['original'],
            'titchy_stream':row['titchy_stream']}
