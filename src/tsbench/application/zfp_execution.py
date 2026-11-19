"""Run ZFP native fixtures with sealed inputs, detached restoration and replayable oracles."""
from pathlib import Path
import tempfile

from ..assets import ContractError, load_json, require, verify_asset
from ..planner.zfp import ARRAY_REJECTIONS, FIELD_REJECTIONS, array_input, field_input, field_layout, ref, values
from ..planner.zfp_execution import ARRAY, FIELD, OMP, MODES, THREADS, TYPES, blobs, identity, metadata, steps
from ..qualification.zfp import compare_numeric, exact, work_counts
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref


def _path(slot,name):
    return f'products/{slot["product_slot"]}.{name}'


def _bounded(path,cap):
    require(path.is_file() and not path.is_symlink() and 0<path.stat().st_size<=cap,'ZFP output outside frozen bound')
    return path.read_bytes()


def _stage(slot,work,meta,raw):
    data = blobs(slot['method'],slot['spec'],raw)
    require({k:identity(v) for k,v in data.items()}==slot['inputs'],'ZFP original worker inputs differ')
    paths = {'metadata':meta}
    for name,blob in data.items():
        p = work/('staged-'+name)
        p.write_bytes(blob)
        paths[name] = p
    return paths


def _log(logs,label):
    require(not (logs/(label+'.stderr')).stat().st_size,'unexpected ZFP native stderr')
    return load_json(logs/(label+'.stdout'))


def _call(run,plan,slot,work,logs,label,step,paths,cancelled,ops=None):
    folder = work/label
    folder.mkdir()
    out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],step['tool'],plan['limits'],folder,logs,label,
                                  {k:paths[v] for k,v in step['mounts'].items()},step['argv'],cancelled,
                                  observe=True,process_env=step['env'])
    op.update(outputs={},process_env=step['env'])
    if ops is not None:
        ops.append(op)
    require(completed(op),f'ZFP {label}: {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    require({p.name for p in out.iterdir()}==step['outputs'].keys(),'unexpected ZFP operation output closure')
    returned = {}
    for name,key in step['outputs'].items():
        p = out/name
        size = slot['inputs']['input']['bytes'] if key is None else slot['parts'][key]
        data = _bounded(p,size)
        op['outputs'][name] = identity(data)
        if key is None:
            require(op['outputs'][name]==slot['inputs']['input'],'ZFP detached worker field bits differ')
        returned[key or 'decoded'] = p
    return returned,_log(logs,label)


def _field_report(slot,wire,span,retained_original,logs):
    spec = slot['spec']
    dtype = spec['type']
    logical = field_input(spec,retained_original)
    require(ref('frozen:'+spec['id'],logical)==spec['input'] and
            {k:identity(v) for k,v in blobs(FIELD,spec,logical).items()}==slot['inputs'], 'ZFP field original identity differs')
    l = field_layout(spec)
    cells = values(dtype,span)
    touched = set(l['offsets'])
    require(len(wire)%8==0 and len(cells)==l['span_count'] and
            all(cell==8191 for i,cell in enumerate(cells) if i not in touched), 'ZFP field padding or word extent differs')
    err,rmse = compare_numeric(values(dtype,logical),[cells[i] for i in l['offsets']],spec['max_observed_error'],spec['id'])
    common = {'mode':MODES[spec['mode']],'rank':len(spec['shape']),'type':TYPES[dtype],'requested':spec['requested'],
              'effective':spec['effective'],'logical_bytes':len(logical),'strides':l['strides'],'offset_bounds':l['offset_bounds'],
              'decode_execution':0}
    extra = {'invalid_configs':FIELD_REJECTIONS,'cuda_built':0} if 'quality-original' in slot['parts'] else {}
    exact(logs['encode'],{**common,'bad_origin_status':1,'written':len(wire),**extra},'ZFP observed field configuration/rejection differs')
    exact(logs['restore'],{**common,'status':0},'ZFP detached field effective configuration differs')
    return {'requested_vs_effective':common,'case':spec['id'],'error_limit':spec['max_observed_error'],
            'observed_max_abs_error':err,'observed_rmse':rmse,'padding_preserved':True,
            'restore_required_bytes':len(wire)+slot['parts']['metadata'],'bad_origin_status':1,**extra}


def _omp_report(slot,parts,logs):
    spec = slot['spec']
    frames = [parts['frame-'+k] for k in THREADS]
    require(len(set(frames))==1 and len(frames[0])%8==0,'ZFP same-field OpenMP payloads differ')
    profiles = {}
    for name,threads in THREADS.items():
        doc = logs['encode-'+name]
        caller = doc['caller_tid']
        enc,dec = doc['encode_block_work'],doc['decode_block_work']
        for rows,n in ((enc,threads),(dec,1)):
            work_counts(rows,n,spec['count']//4,caller)
        if threads==2:
            require(all(r['blocks']==1024 for r in enc),'ZFP two-thread full-block assignment differs')
        exact({k:v for k,v in doc.items() if k not in ('caller_tid','encode_block_work','decode_block_work')},
              {'policy':name,'configured_threads':threads,'chunk_blocks':0 if name=='serial' else spec['chunk_blocks'],
               'omp_dynamic':0,'omp_thread_limit':2,'serial_decode_reported':True,'reversible_bits_verified':True},
              'ZFP requested versus effective OpenMP policy differs')
        exact(logs['restore-'+name],{'mode':0,'rank':1,'type':4,'requested':0,'effective':0,'logical_bytes':spec['count']*8,
                                    'strides':[1],'offset_bounds':[0,spec['count']-1],'decode_execution':0,'status':0},
              'ZFP detached OpenMP field must recover with serial decoding')
        profiles[name] = doc
    return {'observer':'native_full_block_entry_per_OS_tid','profiles':profiles,'same_payload':True,
            'restore_required_bytes_per_profile':len(frames[0])+slot['parts']['metadata']}


def _array_report(slot,parts,logs):
    spec = slot['spec']
    before,after = (parts[k] for k in ('before','after'))
    left,right = (values('f64',parts[k]) for k in ('baseline','restored'))
    orig,updated = array_input(spec)
    base_max,_ = compare_numeric(orig,left,spec['max_observed_error'],'ZFP initial array')
    max_err,rmse = compare_numeric(updated,right,spec['max_observed_error'],'ZFP persisted array')
    require(len(before)==len(after)==64 and before[32:]==after[32:] and parts['baseline'][64:]==parts['restored'][64:],
            'ZFP untouched compressed blocks or restored values differ')
    doc = logs['update']
    evicted = doc['evicted_point']
    require(type(evicted) in (int,float) and 0<abs(evicted-spec['point_value'])<=spec['max_observed_error'],
            'ZFP array did not observe quantization after eviction')
    r = ARRAY_REJECTIONS
    exact(doc,{'rate':spec['effective_rate'],'cached_point':spec['point_value'],'evicted_point':evicted,
               'range_tail':spec['range_values'][-1],'cache_size_request':16384,'cache_populated':2048,'cache_after_set_size':0,
               'cache_repopulated':2048,'cache_after_flush':0,'rejected':{k:r[k] for k in ('point_oob','nonfinite_write','range_oob','export_capacity')}},
          'ZFP native array cache/rejection differs')
    base = {'rate':spec['effective_rate'],'count':13,'cross_block_read':True}
    exact(logs['reopen-before'],base,'ZFP baseline import differs')
    exact(logs['reopen-after'],{**base,'rejected':{k:r[k] for k in ('truncated_raw','wrong_derived_size','wrong_mode')}},
          'ZFP persisted import and metadata rejections differ')
    return {'requested_rate':spec['requested_rate'],'effective_rate':spec['effective_rate'],'baseline_max_abs_error':base_max,
            'observed_max_abs_error':max_err,'observed_rmse':rmse,'update':doc,'untouched_blocks':[2,3],
            'import_rejected':logs['reopen-after']['rejected'],'restore_required_bytes':len(after)+slot['parts']['metadata']}


def _validate(slot,parts,logs):
    method,spec = slot['method'],slot['spec']
    require(parts['metadata']==metadata(method,spec),'ZFP external format metadata differs')
    if method==FIELD:
        return _field_report(slot,parts['frame'],parts['span'],parts.get('quality-original'),logs)
    if method==OMP:
        return _omp_report(slot,parts,logs)
    return _array_report(slot,parts,logs)


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']
    logdir = run/'logs'/sid
    logdir.mkdir()
    ops = []
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':ops,'parts':{},'zfp':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-zfp-route-') as tmp:
            w = Path(tmp)
            raw = None if slot['method']==ARRAY else sample.columns[0]
            meta = w/'metadata'
            meta.write_bytes(metadata(slot['method'],slot['spec']))
            paths = _stage(slot,w,meta,raw)
            transcripts = {}
            for label,step in steps(slot).items():
                files,transcripts[label] = _call(run,plan,slot,w,logdir,label,step,paths,cancelled,ops)
                paths.update(files)
            if 'quality-original' in slot['parts']:
                path = w/'quality-original'
                path.write_bytes(raw)
                paths['quality-original'] = path
            parts = {k:_bounded(paths[k],cap) for k,cap in slot['parts'].items()}
            validation = _validate(slot,parts,transcripts)
            for name,data in parts.items():
                dest = run/_path(slot,name)
                with dest.open('xb') as f:
                    f.write(data)
                row['parts'][name] = _ref(run,dest)
            row.update(status='verified',zfp=validation)
    except (ContractError,OSError,KeyError,ValueError,TypeError) as exc:
        last = ops[-1]['status'] if ops else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid = slot['product_slot']
    spec = steps(slot)
    ops = row['operations']
    require(set(row)=={'product_slot','status','reason','operations','parts','zfp'} and len(ops)<=len(spec) and
            [op['operation'] for op in ops]==list(spec)[:len(ops)] and all(completed(op) for op in ops[:-1]) and
            len({op['session_id'] for op in ops})==len(ops),'ZFP operation order or isolation differs')
    for op in ops:
        names = {f'logs/{sid}/{op["operation"]}.{suffix}' for suffix in ('stdout','stderr')}
        allowed.update(names)
        require(all(files[p]['bytes']<=plan['limits']['file_bytes'] for p in names if p in files) and
                (op['pid'] is None or names<=files.keys()),'ZFP operation logs missing or over bounds')
    require(row['parts'].keys()<=slot['parts'].keys(),'unknown retained ZFP product')
    parts = {}
    for name,r in row['parts'].items():
        p = _path(slot,name)
        require(r==files.get(p),'ZFP retained artifact identity differs')
        allowed.add(p)
        parts[name] = _bounded(run/p,slot['parts'][name])
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['zfp'] is None,'invalid ZFP failure terminal')
        return False
    require(not row['reason'] and len(ops)==len(spec) and all(completed(op) for op in ops) and parts.keys()==slot['parts'].keys(),
            'incomplete native ZFP execution evidence')
    refs = {**slot['inputs'],**{k:identity(v) for k,v in parts.items()}}
    logs = run/'logs'/sid
    for operation,(label,step) in zip(ops,spec.items(),strict=True):
        require(operation.get('input_mounts')=={k:refs[v] for k,v in step['mounts'].items()} and
                operation.get('process_env')==step['env'],'ZFP operation mount or environment closure differs')
        require(operation.get('outputs')=={n:refs[k or 'input'] for n,k in step['outputs'].items()},'ZFP observed output identity differs')
    exact(row['zfp'],_validate(slot,parts,{k:_log(logs,k) for k in spec}),'ZFP ledger and sealed evidence differ')
    return True


def _normalized(doc):
    """Across fresh namespaces, TIDs differ; compare the caller and worker work, not their names."""
    counts = {k:sorted((r['tid']==doc['caller_tid'],r['blocks']) for r in doc[k])
              for k in ('encode_block_work','decode_block_work')}
    return {k:v for k,v in doc.items() if k!='caller_tid'} | counts


def audit_slot(run,plan,slot,row):
    paths = {k:verify_asset(run,v) for k,v in row['parts'].items()}
    spec = steps(slot)
    method = slot['method']
    with tempfile.TemporaryDirectory(prefix='tsbench-zfp-route-audit-') as tmp:
        w = Path(tmp)
        docs = {}
        # Do all fresh recoveries before staging any input for the optional re-encode checks.
        decoded = None
        for label,s in spec.items():
            if 'input' in s['mounts']:
                continue
            result,docs[label] = _call(run,plan,slot,w,w,label,s,paths,lambda:False)
            for k,p in result.items():
                if k=='decoded':
                    decoded = p
                else:
                    require(p.read_bytes()==paths[k].read_bytes(),'ZFP detached replay output differs')
        if method==OMP:
            raw = decoded.read_bytes()
        elif method==FIELD:
            raw = field_input(slot['spec'],paths['quality-original'].read_bytes() if 'quality-original' in paths else None)
        else:
            raw = None
        staged = _stage(slot,w,paths['metadata'],raw)
        for label,s in spec.items():
            if 'input' not in s['mounts']:
                continue
            result,docs[label] = _call(run,plan,slot,w,w,label,s,staged,lambda:False)
            for k,p in result.items():
                require(p.read_bytes()==paths[k].read_bytes(),'ZFP replay generated different payload bytes')
        replay = _validate(slot,{k:p.read_bytes() for k,p in paths.items()},docs)
        old = row['zfp']
        if method==OMP:
            replay = {**replay,'profiles':{k:_normalized(v) for k,v in replay['profiles'].items()}}
            old = {**old,'profiles':{k:_normalized(v) for k,v in old['profiles'].items()}}
        exact(replay,old,'ZFP replay observations differ from seal')
    return {'product_slot':slot['product_slot'],'method':method,'parts':row['parts'],'observed':row['zfp']}
