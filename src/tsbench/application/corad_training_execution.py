"""Separate training, native model evaluation and artifact-only cold restore."""
from pathlib import Path
import struct
import tempfile

from ..assets import ContractError, canonical_bytes, load_json, parse_json, require, verify_asset
from ..planner.corad_training import STAGED_BRIDGE, VECTORS, ref, source_argv
from ..planner.corad_training_execution import C, SOURCE, ENCODE, PYTHON, FILE_CEILING, identity, limits, steps, source_runtime
from ..qualification.corad_training import _c, _data, _normalization, _source, exact, inference_evidence
from ..qualification.corad_wire import HEADER, interpret
from ..recovery import DIRECTORY
from ..supervisor.corad_source import invoke_source
from ..supervisor.isolated_worker import invoke_isolated_tool
from .selfstar_execution import NONPASS, completed
from .smoke import _ref


def _read(p,cap=FILE_CEILING):
    require(p.is_file() and not p.is_symlink() and p.stat().st_size<=cap,'CORAD training output exceeds bound')
    return p.read_bytes()


def _npy(vectors, rows, width):
    require(len(vectors)==rows*width,'CORAD train-only vector dimensions differ')
    tag=f"{{'descr': '<f8', 'fortran_order': False, 'shape': ({rows}, {width}), }}".encode('ascii')
    header=tag+b' '*((-(10+len(tag)+1))%64)+b'\n'
    return b'\x93NUMPY\x01\0'+struct.pack('<H',len(header))+header+struct.pack(f'<{len(vectors)}d',*vectors)


def _inference_parts(parts,label):
    return tuple(parts[label+s] for s in ('.model.crd1','.heldout.crd1','.restored.f64le'))


def _optional(label,step,parts):
    if 'when' not in step:
        return True
    require(step['when']=='native_reference_exists' and label.endswith('-self_reference'),'unknown CORAD training condition')
    return interpret(parts[label.removesuffix('-self_reference')+'.heldout.crd1'])[1]['first_reference'] is not None


def execution_labels(slot,parts):
    return [label for label,s in steps(slot).items() if _optional(label,s,parts)]


def _negatives(frame):
    mutated=bytearray(frame); struct.pack_into('<d',mutated,HEADER.size,float('nan'))
    rows={'nan_atom':(bytes(mutated),4),'trailing_byte':(frame+b'\0',4),'truncated':(frame[:-1],4),
          'max_values':(frame,2),'model_load_data_frame':(frame,2)}
    first=interpret(frame)[1]['first_reference']
    if first is not None:
        off,j=first
        mutated=bytearray(frame); struct.pack_into('<H',mutated,off,j); rows['self_reference']=(bytes(mutated),4)
    return rows


def _io(slot,parts,label,norm):
    b=slot['bundle']; means,scales,_=norm
    if label=='solver-controls':
        return {},{}
    if label.startswith('fit-'):
        inp={'train':parts[b['data']['train']['values']['path']]}
        model=parts.get('c-lars.model.crd1')
        if label in ('fit-0','fit-1'):
            return inp,None if model is None else {'model':model}
        return inp,{}
    if label.startswith('train-'):
        out=label.removeprefix('train-')+'.json'
        return {STAGED_BRIDGE:parts[STAGED_BRIDGE],VECTORS:parts[VECTORS]},None if out not in parts else {out:parts[out]}
    if label.startswith('pack-'):
        origin=label.removeprefix('pack-')
        d=parse_json(parts[origin+'.json'].decode(),origin)['dictionary']
        flat=[v for row in d for v in row]
        require(len(flat)==b['model']['atoms']*b['model']['tricklet'],'CORAD Source dictionary extent differs')
        raw=struct.pack(f'<{len(flat)+2*len(means)}d',*flat,*means,*scales)
        model=parts.get(origin+'.model.crd1')
        return {'arrays':raw},None if model is None else {'model':model}
    if label.startswith('evaluate-'):
        origin=label.removeprefix('evaluate-'); frame=parts.get(origin+'.heldout.crd1')
        inp={'model':parts[origin+'.model.crd1'],'values':parts[b['data']['evaluation']['values']['path']]}
        return inp,None if frame is None else {'native':frame}
    if label.startswith('restore-'):
        origin=label.removeprefix('restore-'); frame=parts[origin+'.heldout.crd1']
        return {'frame':frame},{'values':interpret(frame)[0]}
    origin,kind=label.rsplit('-',1)
    frame,_=_negatives(parts[origin+'.heldout.crd1'])[kind]
    return {'frame':frame},{}


def _json(logs,label):
    require(not _read(logs/(label+'.stderr')),f'unexpected CORAD training diagnostic: {label}')
    return load_json(logs/(label+'.stdout'))


def _empty_logs(logs,label):
    require(not _read(logs/(label+'.stdout')) and not _read(logs/(label+'.stderr')),f'unexpected CORAD assembly diagnostic: {label}')


def _fitness(logs,label,b,offset):
    got=_json(logs,label); opts=b['c_options']
    if label=='fit-cap':
        exact(got,{'options':{**opts,'max_training_samples':opts['max_training_samples']-1},'stats':None,
                   'status':b['native_rejections']['insufficient_training_samples']},'CORAD sample-cap failure differs')
    elif label=='fit-mask':
        exact(got,{'options':{**opts,'training_columns':1<<b['model']['columns']},'stats':None,
                   'status':b['native_rejections']['out_of_range_mask']},'CORAD invalid mask failure differs')
    else:
        exact(got,{'options':opts,'status':0,'stats':offset},'CORAD C fit effective options or repeat stats differ')
    return got['status']


def _evidence(slot,parts,ops,logs):
    b=slot['bundle']; train,held=_data(b,parts.__getitem__)
    norm=_normalization(train,b['model']['tricklet'],b['c_options']['training_columns'])
    exec_steps=steps(slot)
    for label,op in zip(execution_labels(slot,parts),ops,strict=True):
        require(label==op['operation'] and completed(op),'CORAD training operation is missing or failed')
        inputs,out=_io(slot,parts,label,norm)
        require(op['input_mounts']=={k:identity(v) for k,v in inputs.items()} and
                op['outputs']=={k:identity(v) for k,v in out.items()},f'CORAD training mount or output identity differs: {label}')
        if exec_steps[label]['tool']==PYTHON:
            exact(op.get('source_runtime'),slot['source_runtime'],'CORAD Source recorded runtime differs')
    if slot['method']==C:
        stat=_json(logs,'fit-0')['stats']
        fits=[]
        for label in ('fit-0','fit-1'):
            _fitness(logs,label,b,stat)
            fits.append({'model':ref('c-lars.model.crd1',parts['c-lars.model.crd1']),'stats':stat})
        controls=_json(logs,'solver-controls')
        require(set(controls)=={'analytical_controls','sparse_nonconvergence'},'CORAD known answer control result differs')
        rec={'options':b['c_options'],'fits':fits,'analytical_controls':controls['analytical_controls'],
             'rejections':{'insufficient_training_samples':_fitness(logs,'fit-cap',b,None),
                           'out_of_range_mask':_fitness(logs,'fit-mask',b,None),
                           'sparse_nonconvergence':controls['sparse_nonconvergence']}}
        _c(rec,b,parts.__getitem__)
        kind='c_training'; labels=['c-lars']; dicts={}
    else:
        rows=[]
        for name in b['source_labels']:
            label='train-'+name
            rows.append({'origin':name,'argv':source_argv(b,name),'returncode':0,'dictionary':ref(name+'.json',parts[name+'.json']),
                         **{k:_read(logs/(label+'.'+k)).decode() for k in ('stdout','stderr')}})
            _empty_logs(logs,'pack-'+name)
        env=slot['source_runtime']
        rec={'policy':b['policy']['source'],'environment_lock_sha256':env['environment_lock_sha256'],
             'python_sha256':env['python_sha256'],'bridge':ref(STAGED_BRIDGE,parts[STAGED_BRIDGE]),
             'train_vectors':ref(VECTORS,parts[VECTORS]),'runs':rows}
        dicts=_source(rec,b,parts.__getitem__,env['python_sha256'],norm[2])
        kind='source_training'; labels=b['source_labels']
    inference=[]
    for label in labels:
        _empty_logs(logs,'evaluate-'+label)
        frame,restored= _inference_parts(parts,label)[1:]
        exact(_json(logs,'restore-'+label),{'status':0,'values':len(restored)//8},'CORAD actual native decode descriptor differs')
        for neg,(_,status) in _negatives(frame).items():
            exact(_json(logs,label+'-'+neg),{'status':status,**({} if neg=='model_load_data_frame' else {'values':0})},
                  f'CORAD native bad-frame result differs: {label}/{neg}')
        inference.append(inference_evidence(label,b,parts.__getitem__,norm[:2],held,dicts.get(label)))
    return {kind:rec,'inference':inference,'model_quality_policy':b['policy']['quality'],
            'deployment_overwritten':False}


def _run(run,plan,slot,work,logs,label,step,inputs,cancelled,ops):
    lane=work/label; lane.mkdir()
    paths={k:lane/k for k in inputs}
    require(list(paths)==step['inputs'],'CORAD training recipe input closure differs')
    for name,path in paths.items():
        path.write_bytes(inputs[name])
    lim=limits(plan,step['tool'])
    if step['tool']==PYTHON:
        out,op=invoke_source(slot,step,lim,lane,logs,label,paths,cancelled)
        op['source_runtime']=slot['source_runtime']
    else:
        out,op=invoke_isolated_tool(run/DIRECTORY,plan['decoder'],step['tool'],lim,lane,logs,label,paths,step['argv'],cancelled,observe=True)
    op['outputs']={}; ops.append(op)
    require(completed(op),f'CORAD training {label}: {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(step['outputs']),f'CORAD training {label} output closure differs')
    data={k:_read(out/k) for k in step['outputs']}
    op['outputs']={k:identity(v) for k,v in data.items()}
    return data


def _store(parts, label, data):
    if label=='fit-0':
        parts['c-lars.model.crd1']=data['model']
    elif label.startswith('train-'):
        parts.update(data)
    elif label.startswith('pack-'):
        parts[label.removeprefix('pack-')+'.model.crd1']=data['model']
    elif label.startswith('evaluate-'):
        parts[label.removeprefix('evaluate-')+'.heldout.crd1']=data['native']
    elif label.startswith('restore-'):
        parts[label.removeprefix('restore-')+'.restored.f64le']=data['values']


def run_slot(run,plan,slot,sample,cancelled):
    sid=slot['product_slot']; logs=run/'logs'/sid; logs.mkdir()
    row={'product_slot':sid,'status':'validation_failed','reason':'','operations':[],'parts':{},'training':None}
    b=slot['bundle']
    names=[b['data'][a][k]['path'] for a in ('train','evaluation') for k in ('timestamps','values')]
    try:
        if slot['method']==SOURCE:
            names.append(STAGED_BRIDGE)
        parts=dict(zip(names,sample.columns,strict=True))
        train,_=_data(b,parts.__getitem__)
        norm=_normalization(train,b['model']['tricklet'],b['c_options']['training_columns'])
        if slot['method']==SOURCE:
            require(identity(parts[STAGED_BRIDGE])['sha256']==b['bridge_sha256'],'CORAD Source bridge changed before execution')
            parts[VECTORS]=_npy(norm[2],b['c_options']['max_training_samples'],b['model']['tricklet'])
        with tempfile.TemporaryDirectory(prefix='tsbench-corad-training-') as tmp:
            work=Path(tmp)
            for label,step in steps(slot).items():
                if not _optional(label,step,parts):
                    continue
                in_bytes,expected=_io(slot,parts,label,norm)
                data=_run(run,plan,slot,work,logs,label,step,in_bytes,cancelled,row['operations'])
                require(expected is None or data==expected,f'CORAD training {label} differs from independent expectation')
                _store(parts,label,data)
        require(parts.keys()==slot['parts'].keys() and all(len(v)<=slot['parts'][k] for k,v in parts.items()),
                'CORAD training retention closure differs')
        observed=_evidence(slot,parts,row['operations'],logs)
        for name,value in parts.items():
            dest=run/'products'/sid/name; dest.parent.mkdir(exist_ok=True)
            with dest.open('xb') as f:
                f.write(value)
            row['parts'][name]=_ref(run,dest)
        row.update(status='verified',training=observed)
    except (ContractError,KeyError,OSError,TypeError,ValueError) as exc:
        last=row['operations'][-1]['status'] if row['operations'] else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid=slot['product_slot']; ops=row['operations']; recipe=steps(slot)
    labels=[o['operation'] for o in ops]
    require(set(row)=={'product_slot','status','reason','operations','parts','training'} and len(labels)==len(set(labels)) and
            labels==[k for k in recipe if k in labels] and len({o['session_id'] for o in ops})==len(ops) and
            all(completed(o) for o in ops[:-1]),'CORAD training ledger operation sequence differs')
    for op in ops:
        label=op['operation']; names={f'logs/{sid}/{label}.{k}' for k in ('stdout','stderr')}
        require((op['pid'] is None or names<=files.keys()) and all(files[k]['bytes']<=FILE_CEILING for k in names if k in files),
                'CORAD training process logs missing or oversized')
        allowed.update(names)
    parts={}
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected CORAD training artifact')
    for name,r in row['parts'].items():
        path=f'products/{sid}/{name}'
        require(r==files.get(path) and r['bytes']<=slot['parts'][name],'CORAD training artifact identity differs')
        allowed.add(path); parts[name]=_read(run/path,slot['parts'][name])
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['training'] is None,'invalid CORAD training nonpassing terminal')
        return False
    require(row['parts'].keys()==slot['parts'].keys() and not row['reason'] and
            labels==execution_labels(slot,parts),'CORAD successful training evidence incomplete')
    exact(row['training'],_evidence(slot,parts,ops,run/'logs'/sid),'CORAD training ledger semantics differ')
    return True


def audit_slot(run,plan,slot,row):
    parts={name:_read(verify_asset(run,r),slot['parts'][name]) for name,r in row['parts'].items()}
    b=slot['bundle']; train,_=_data(b,parts.__getitem__)
    norm=_normalization(train,b['model']['tricklet'],b['c_options']['training_columns'])
    recipe=steps(slot); measured=[]
    # Replay native work only. Source RNG is not frozen; use its sealed dictionary, not a new fit.
    names=execution_labels(slot,parts)
    order=[k for k in names if k.startswith('restore-')]+[k for k in names if not k.startswith('restore-') and recipe[k]['tool']!=PYTHON]
    with tempfile.TemporaryDirectory(prefix='tsbench-corad-training-audit-') as t:
        work=Path(t)
        for label in order:
            inp,want=_io(slot,parts,label,norm)
            data=_run(run,plan,slot,work,work,label,recipe[label],inp,lambda:False,measured)
            require(data==want,'CORAD trained artifact cannot be independently restored or reproduced')
            original=run/'logs'/slot['product_slot']
            for ext in ('stdout','stderr'):
                require(_read(work/(label+'.'+ext))==_read(original/(label+'.'+ext)),'CORAD native audit descriptor differs')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'models':row['training']['inference'],
            'native_operations_replayed':order,'source_refit':False}
