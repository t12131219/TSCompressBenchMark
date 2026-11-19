"""Isolate dictionary/worker profiles, seal dependencies, and replay their evidence."""
from pathlib import Path
import tempfile

from ..assets import ContractError, load_json, require, verify_asset
from ..planner.lzbench import byte_identity, dictionary_sample, worker_input
from ..planner.lzbench_profiles import DICT, XZ, FILE_CEILING, steps
from ..qualification.lzbench import _verify_dictionary, _verify_workers
from ..qualification.lzbench_session import match
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref


def _path(slot,name):
    return f'products/{slot["product_slot"]}.{name}'


def _inputs(slot):
    spec = slot['spec']
    if slot['method']!=DICT:
        return {'raw':spec['input']}
    return {'raw':spec['held_out'],**{f'train-{i:03}':row for i,row in enumerate(spec['training_samples'])}}


def _stage(slot,work,recovered=None):
    spec = slot['spec']
    if slot['method']==DICT:
        samples = {f'train-{i:03}':dictionary_sample('train',i) for i in range(len(spec['training_samples']))}
        raw = recovered if recovered is not None else b''.join(dictionary_sample('held-out',i) for i in range(len(spec['held_out_samples'])))
    else:
        samples = {}
        raw = recovered if recovered is not None else worker_input(slot['method'].split('-')[0],spec['input']['bytes'])
    blobs = {**samples,'raw':raw}
    match({k:byte_identity(v) for k,v in blobs.items()},_inputs(slot),'lzbench staged input identity differs')
    paths = {k:work/k for k in blobs}
    for k,p in paths.items():
        p.write_bytes(blobs[k])
    return paths


def _wire(path,bound):
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=bound,'lzbench profile output extent differs')
    return path.read_bytes()


def _wrong_dictionary(data):
    require(len(data)>=8 and data[:4]==b'\x37\xa4\x30\xec' and int.from_bytes(data[4:8],'little')>1,
            'wrong-ID control needs a standard trained dictionary')
    return data[:4] + (int.from_bytes(data[4:8],'little')^1).to_bytes(4,'little') + data[8:]


def _succeeded(step,op):
    if step['error']:
        return op['status']=='failed' and op['returncode']==2 and op['pid'] is not None
    return completed(op)


def _call(run,plan,slot,work,logs,label,step,paths,cancelled,ops):
    folder = work/label
    folder.mkdir()
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],step['tool'],slot['limits'],folder,logs,label,
                                 {n:paths[k] for n,k in step['mounts'].items()},step['argv'],cancelled,observe=True,
                                 file_ceiling=FILE_CEILING)
    op['outputs'] = {}
    if ops is not None:
        ops.append(op)
    require(_succeeded(step,op),f'lzbench profile {label} unexpected {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(step['outputs']),'lzbench profile produced unexpected files')
    original = _inputs(slot)['raw']
    for name,key in step['outputs'].items():
        p = out/name
        blob = _wire(p,original['bytes'] if key=='raw' else slot['parts'][key])
        identity = byte_identity(blob)
        if key=='raw':
            match(identity,original,'lzbench native original bytes differ')
        elif key in paths:
            match(identity,byte_identity(_wire(paths[key],slot['parts'][key])),'lzbench recovery rewrote its input frame')
        op['outputs'][name] = identity
    return out


def _pipeline(run,plan,slot,work,logs,cancelled,ops,recovered=None):
    paths = _stage(slot,work,recovered)
    for label,step in steps(slot).items():
        out = _call(run,plan,slot,work,logs,label,step,paths,cancelled,ops)
        for name,key in step['outputs'].items():
            if key in slot['parts'] and key not in paths:
                paths[key] = out/name
        if label=='train':
            k = slot['spec']['dictionary_path']
            wrong = work/'wrong-id'
            wrong.write_bytes(_wrong_dictionary(_wire(paths[k],slot['parts'][k])))
            paths['wrong-dictionary'] = wrong
    return {k:_wire(paths[k],bound) for k,bound in slot['parts'].items()}


def _log(logs,label,step):
    out = logs/f'{label}.stdout'; err = logs/f'{label}.stderr'
    if step['error']:
        require(not out.stat().st_size and err.read_bytes()==(step['error']+'\n').encode(),
                'lzbench profile native rejection transcript differs')
        return {'error':step['error'],'exit_status':2}
    require(not err.stat().st_size,'unexpected lzbench profile stderr')
    doc = load_json(out)
    require(isinstance(doc,dict),'invalid lzbench profile log')
    timings = {'train':{'training_ns'}}.get(label,set() if step['tool']!='lzbench-native-features' else {'encode_ns','decode_ns'})
    require(timings <= doc.keys() and all(type(doc[k]) is int and doc[k]>=0 for k in timings),
            'invalid lzbench diagnostic timer fields')
    return {k:v for k,v in doc.items() if k not in timings}


def _summary(slot,wires,logs):
    method,spec = slot['method'],slot['spec']
    values = {label:_log(logs,label,step) for label,step in steps(slot).items()}
    refs = {key:byte_identity(wire) for key,wire in wires.items()}
    if method==DICT:
        key,frame = spec['dictionary_path'],spec['frame_path']
        dictionary = wires[key]
        dict_id = int.from_bytes(dictionary[4:8],'little')
        match(values['train'],{'dictionary_bytes':len(dictionary)},'lzbench training extent transcript differs')
        result = {'training_samples':spec['training_samples'],'sample_set_identity':{'train':'train','held_out':'held-out'},
                  'training_capacity_bytes':spec['capacity'],
                  'trainer_rejected':{str(n):values[f'reject-cap-{n}'] for n in spec['bad_capacities']},
                  'dictionary':{**refs[key],'id':dict_id},'encoded':refs[frame],'held_out':spec['held_out'],
                  'serialized_bytes_including_dictionary':len(dictionary)+len(wires[frame]),'roundtrip':values['encode'],
                  'fresh_process_decode':values['restore'],'fresh_process_restored':spec['held_out'],
                  'negative_dictionary_id':dict_id^1,'rejected':{'missing':values['reject-missing'],'wrong_id':values['reject-wrong-id']}}
        _verify_dictionary(spec,result,wires)
        return result
    codec = method.split('-')[0]
    result = {'input':spec['input'],'profile_parameter':spec['parameter'],'configured_base':spec['base'],'observed':{}}
    for n in spec['settings']:
        name = spec['frame_paths'][str(n)]
        log = values[f'restore-{n}']
        template = values[f'encode-{n}']
        expected = {**{k:template[k] for k in ('codec','mode','level','native_stream','input_bytes','encoded_bytes','repeats')},
                    'encode_jobs':{'jobs':0,'worker_threads':0,'caller_jobs':0},'effective_parameters':{}}
        match({k:v for k,v in log.items() if k!='decode_jobs'},expected,'lzbench independent worker restore log differs')
        lane = {**template,'frame':refs[name],'frame_path':name,'fresh_process_restored':spec['input']}
        if method==XZ:
            lane['same_multiblock_frame_decode'] = {**values[f'decode-shared-{n}'],
                'source_frame':refs[spec['frame_paths']['2']],'fresh_process_restored':spec['input']}
        else:
            match(log['decode_jobs'],expected['encode_jobs'],'Zstd fresh decode reported native worker jobs')
        result['observed'][str(n)] = lane
    if method==XZ:
        sync,shared = spec['synchronous']['frame_path'],spec['frame_paths']['2']
        result['synchronous'] = {'encode':values['encode-sync'],'frame_path':sync,'frame':refs[sync],
            'decode':{role:{**values[f'decode-sync-{role}'],'source_frame_path':name,'source_frame':refs[name],
                            'fresh_process_restored':spec['input']} for role,name in [('own',sync),('shared',shared)]}}
    _verify_workers(codec,spec,result,wires)
    return result


def _verify_ops(slot,ops,wires):
    graph = steps(slot)
    identities = {**_inputs(slot),**{k:byte_identity(v) for k,v in wires.items()}}
    if slot['method']==DICT:
        identities['wrong-dictionary'] = byte_identity(_wrong_dictionary(wires[slot['spec']['dictionary_path']]))
    for label,op in zip(graph,ops,strict=True):
        step = graph[label]
        require(_succeeded(step,op),'incomplete lzbench native profile operation')
        match(op.get('input_mounts'),{n:identities[k] for n,k in step['mounts'].items()},'lzbench profile input closure differs')
        match(op['outputs'],{n:identities[k] for n,k in step['outputs'].items()},'lzbench profile native output identity differs')


def run_slot(run,plan,slot,_original,cancelled):
    sid,ops = slot['product_slot'],[]
    logs = run/'logs'/sid
    logs.mkdir()
    row = {'product_slot':sid,'operations':ops,'parts':{},'profile':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-profile-') as tmp:
            wires = _pipeline(run,plan,slot,Path(tmp),logs,cancelled,ops)
        _verify_ops(slot,ops,wires)
        result = _summary(slot,wires,logs)
        for key,wire in wires.items():
            part = run/_path(slot,key)
            with part.open('xb') as f:
                f.write(wire)
            row['parts'][key] = _ref(run,part)
        row.update(status='verified',reason='',profile=result)
    except (ContractError,OSError,ValueError,TypeError,KeyError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid,ops,graph = slot['product_slot'],row['operations'],steps(slot)
    require(set(row)=={'product_slot','status','reason','operations','parts','profile'} and
            [op['operation'] for op in ops]==list(graph)[:len(ops)] and
            all(_succeeded(graph[op['operation']],op) for op in ops[:-1]) and len({op['session_id'] for op in ops})==len(ops),
            'lzbench profile operation order differs')
    for op in ops:
        logs = {f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(logs)
        require(all(files[p]['bytes']<=slot['limits']['file_bytes'] for p in logs if p in files) and
                (op['pid'] is None or logs<=files.keys()),'lzbench profile logs missing or outside limit')
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected lzbench profile part')
    for key,ref in row['parts'].items():
        name = _path(slot,key)
        require(ref==files.get(name) and 0<ref['bytes']<=slot['parts'][key],'lzbench profile retained identity differs')
        allowed.add(name)
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['profile'] is None,'invalid lzbench profile terminal')
        return False
    require(not row['reason'] and len(ops)==len(graph) and row['parts'].keys()==slot['parts'].keys(),
            'incomplete lzbench profile evidence')
    wires = {k:_wire(run/v['path'],slot['parts'][k]) for k,v in row['parts'].items()}
    _verify_ops(slot,ops,wires)
    match(row['profile'],_summary(slot,wires,run/'logs'/sid),'lzbench profile differs from retained native evidence')
    return True


def audit_slot(run,plan,slot,row):
    paths = {k:verify_asset(run,ref) for k,ref in row['parts'].items()}
    wires = {k:_wire(p,slot['parts'][k]) for k,p in paths.items()}
    graph = steps(slot)
    with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-profile-audit-') as tmp:
        work = Path(tmp)
        logs = work/'logs'; logs.mkdir()
        ops = []
        # Restore and compare each retained frame in a fresh files-only process,
        # using the exact shared frame for XZ worker comparison again below.
        labels = ['restore'] if slot['method']==DICT else [n for n in graph if n.startswith('restore-')]
        if slot['method']==XZ:
            labels.append('decode-sync-own')
        original = None
        for label in labels:
            step = graph[label]
            out = _call(run,plan,slot,work,logs,label,step,paths,lambda:False,ops)
            name = next(n for n,k in step['outputs'].items() if k=='raw')
            original = _wire(out/name,_inputs(slot)['raw']['bytes'])
        require(original is not None,'missing lzbench independent restore')
        replay = work/'replay'; replay.mkdir()
        replay_logs = replay/'logs'; replay_logs.mkdir()
        trials = []
        regenerated = _pipeline(run,plan,slot,replay,replay_logs,lambda:False,trials,original)
        require(regenerated==wires,'lzbench profile recreated artifact bytes differ')
        _verify_ops(slot,trials,regenerated)
        _summary(slot,regenerated,replay_logs)
    return {'product_slot':slot['product_slot'],'method':slot['method'],'parts':row['parts'],
            'replayed_from_independent_restore':True,'profile':row['profile']}
