"""Execute CORAD with scoped mounts and recompute its original-domain quality decision."""
from pathlib import Path
import struct
import tempfile

from ..assets import ContractError, canonical_bytes, require, verify_asset
from ..corad_quality import assess
from ..planner.corad_execution import (COLS, DEFAULT_METHOD, ENCODE_REJECTS, FILE_CEILING, identity, limit,
                                       split_deployment, steps)
from ..qualification.corad_inference import HEADER, frame_evidence, verify_bounds
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker
from .selfstar_execution import NONPASS, completed
from .smoke import _ref, _worker_json


def _read(p,cap):
    require(p.is_file() and not p.is_symlink() and p.stat().st_size<=cap,'CORAD output or artifact outside frozen file limits')
    return p.read_bytes()


def _wrap(schema,native):
    return HEADER.pack(b'BMKCRD\x01\0',len(schema),0,len(native))+schema+native


def _read_parts(slot,folder):
    return {k:_read(folder/k,cap) for k,cap in slot['parts'].items()}


def _columns(source,n):
    size = len(source)//3
    return [source[i*size:i*size+8*n] for i in range(3)]


def _input_extents(slot,parts):
    b=slot['bundle']; src=b['input']; cal=b['quality_policy']['calibration']
    for spec in (src,cal):
        require(identity(parts[spec['path']])=={k:spec[k] for k in ('bytes','sha256')},'CORAD frozen input extent or digest differs')
    return parts[src['path']]


def _io(slot,parts,label):
    """Rebuild input bytes and expected outputs using the source and independent frame parser."""
    b=slot['bundle']; src=b['input']; raw=parts[src['path']]
    op,_,index=label.partition('-')
    if index.isdigit():
        i=int(index); f=b['frames'][i]
        schema,model=split_deployment(slot['deployments'][i//3])
        data=_columns(raw,f['rows']); frame=parts.get(f['path'])
        if op=='encode':
            return {'schema':schema,**dict(zip(COLS,data,strict=True))},(None if frame is None else {'frame':frame})
        if op=='native':
            return {'model':model,'values':b''.join(data)},{'native':frame[HEADER.size+len(schema):]}
        _,restored,_=frame_evidence(frame,raw,src,f)
        return {'frame':frame},{'schema':schema,**dict(zip(COLS,restored,strict=True))}
    f=b['frames'][0]; schema,_=split_deployment(slot['deployments'][0]); data=_columns(raw,src['rows'])
    reordered=canonical_bytes({'schema':'bmk.corad-columns/1','columns':src['columns'][::-1],'dtype':'f64le'})
    n=131072//3+1
    if label in ENCODE_REJECTS:
        if label=='column-order':
            schema,data=reordered,data[::-1]
        elif label=='unequal-row-count':
            data[1]=data[1][:-8]
        elif label=='nonfinite':
            data[0]=struct.pack('<d',float('inf'))+data[0][8:]
        elif label=='encode-value-budget':
            data=[bytes(8*n)]*3
        return {'schema':schema,**dict(zip(COLS,data,strict=True))},{}
    frame=parts[f['path']]; payload=frame[HEADER.size+len(schema):]
    if label=='wrong-expected-schema':
        frame=_wrap(reordered,payload)
    elif label=='decode-value-budget':
        mutated=bytearray(payload); struct.pack_into('<I',mutated,4,n); frame=_wrap(schema,mutated)
    elif label=='bad-reference':
        _,_,doc=frame_evidence(frame,raw,src,f)
        off,j=doc['sections']['first_reference']
        mutated=bytearray(payload); struct.pack_into('<H',mutated,off,j); frame=_wrap(schema,mutated)
    elif label=='truncated':
        frame=frame[:-1]
    elif label=='trailing-byte':
        frame+=b'\0'
    return {'frame':frame},{}


def _finish(step,op):
    return (op['status']=='failed' and op['returncode']==3 and op['pid'] is not None) if step['reject'] else completed(op)


def _log(logs,label,step):
    stdout,stderr=(logs/(label+'.'+x) for x in ('stdout','stderr'))
    err=_read(stderr,FILE_CEILING).decode()
    if step['reject']:
        require(not _read(stdout,FILE_CEILING) and err.startswith(f'plugin status {step["reject"]}:'),
                f'CORAD actual ABI refusal differs: {label}')
        return {'plugin_status':step['reject'],'returncode':3,'no_outputs':True,'diagnostic':err.strip()}
    require(not err,'unexpected CORAD successful diagnostic')
    if step['tool']:
        require(not _read(stdout,FILE_CEILING),'unexpected CORAD native diagnostic')
        return []
    return _worker_json(stdout,1 if step['command']=='encode-columns' else 2)


def _evaluate(slot,folder,ops,logs):
    parts=_read_parts(slot,folder); raw=_input_extents(slot,parts)
    b=slot['bundle']; src=b['input']; policy=b['quality_policy']; bounds=verify_bounds(folder,policy,src['columns'],b['window'])
    evidence,heldout,diagnostics,refusals=[],{},{},{}
    for spec in b['frames']:
        original,restored,doc=frame_evidence(parts[spec['path']],raw,src,spec)
        i=len(evidence)
        diagnostics.update({f'encode-{i}':[doc['encode']],f'native-{i}':[],f'restore-{i}':[doc['descriptor'],doc['decode']]})
        if spec['case']=='held-out':
            heldout[spec['route']]=assess(bounds,original,restored)
            diagnostics[f'pinned-{i}']=[doc['descriptor'],doc['pinned_decode']]
        evidence.append(doc)
    for (label,step),op in zip(steps(slot).items(),ops,strict=True):
        inputs,outputs=_io(slot,parts,label)
        require(op['input_mounts']=={k:identity(v) for k,v in inputs.items()} and
                op['outputs']=={k:identity(v) for k,v in outputs.items()},f'CORAD actual mount or output identity differs: {label}')
        doc=_log(logs,label,step)
        if step['reject']:
            refusals[label]=doc
        else:
            require(canonical_bytes(doc)==canonical_bytes(diagnostics[label]),f'CORAD measured descriptor differs: {label}')
    require(b['rejections'].keys()==refusals.keys(),'CORAD refusal denominator differs')
    return {'frames':evidence,'rejections':refusals,'quality_gate':{'policy_id':policy['policy_id'],'heldout':heldout},
            'functional_restoration':True,'quality_comparable':all(v['decision']=='passed' for v in heldout.values())}


def _invoke(run,plan,slot,stage,label,step,inputs,logs,cancelled,ops):
    work=stage/label; work.mkdir()
    require(list(inputs)==step['inputs'],'CORAD requested input mounts differ from frozen driver')
    paths={k:work/('input-'+k) for k in inputs}
    for k,p in paths.items():
        p.write_bytes(inputs[k])
    if step['tool']:
        out,op=invoke_isolated_tool(run/DIRECTORY,plan['decoder'],step['tool'],limit(plan),work,logs,label,paths,
                                    step['argv'],cancelled,observe=True)
    else:
        out,op=invoke_isolated_worker(run/DIRECTORY,plan['decoder'],DEFAULT_METHOD,limit(plan),work,logs,step['command'],paths,
                                      step['argv'],cancelled,label=label,observe=True,options_text=step['options'])
    op['outputs']={}
    ops.append(op)
    require(_finish(step,op),f'CORAD {label}: {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(step['outputs']),f'CORAD output closure differs: {label}')
    files={name:_read(out/name,FILE_CEILING) for name in step['outputs']}
    op['outputs']={k:identity(v) for k,v in files.items()}
    return files


def _execute(run,plan,slot,parts,work,logs,folder,cancelled,ops,*,detached=False):
    b=slot['bundle']; recipe=steps(slot)
    _input_extents(slot,parts)
    # During the cold audit, recovery from sealed frames happens before re-encoding.
    if detached:
        early={}
        for name,step in recipe.items():
            if name.startswith('restore-'):
                inputs,expected=_io(slot,parts,name)
                obs=[]
                files=_invoke(run,plan,slot,work,name,step,inputs,logs,cancelled,obs)
                require(files==expected,'CORAD detached restored values differ from the independent CRD1 parser')
                early[name]=obs[0]
    for name,step in recipe.items():
        if detached and name in early:
            ops.append(early[name]); continue
        inputs,expected=_io(slot,parts,name)
        files=_invoke(run,plan,slot,work,name,step,inputs,logs,cancelled,ops)
        if expected is None:
            spec=b['frames'][int(name[7:])]
            parts[spec['path']]=files['frame']
            frame_evidence(files['frame'],parts[b['input']['path']],b['input'],spec)
        else:
            require(files==expected,f'CORAD actual worker/native bytes differ: {name}')
    require(parts.keys()==slot['parts'].keys(),'CORAD actual retention closure differs')
    for name,value in parts.items():
        require(len(value)<=slot['parts'][name],'CORAD retained file exceeds its frozen bound')
        (folder/name).write_bytes(value)
    return _evaluate(slot,folder,ops,logs)


def run_slot(run,plan,slot,sample,cancelled):
    sid=slot['product_slot']; logs=run/'logs'/sid; logs.mkdir()
    row={'product_slot':sid,'status':'validation_failed','reason':'','operations':[],'parts':{},'corad':None}
    b=slot['bundle']
    try:
        original,calibration=sample.columns
        parts={b['input']['path']:original,b['quality_policy']['calibration']['path']:calibration}
        with tempfile.TemporaryDirectory(prefix='tsbench-corad-slot-') as t:
            work=Path(t); folder=work/'parts'; folder.mkdir()
            result=_execute(run,plan,slot,parts,work,logs,folder,cancelled,row['operations'])
            dest=run/'products'/sid; dest.mkdir()
            for name in slot['parts']:
                with (dest/name).open('xb') as fp:
                    fp.write((folder/name).read_bytes())
                row['parts'][name]=_ref(run,dest/name)
        row.update(status='verified',corad=result)
    except (ContractError,OSError,TypeError,KeyError,ValueError) as exc:
        last=row['operations'][-1]['status'] if row['operations'] else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid=slot['product_slot']; ops=row['operations']; recipe=steps(slot)
    require(set(row)=={'product_slot','status','reason','operations','parts','corad'} and len(ops)<=len(recipe) and
            list(recipe)[:len(ops)]==[o['operation'] for o in ops] and all(_finish(recipe[o['operation']],o) for o in ops[:-1]) and
            len({o['session_id'] for o in ops})==len(ops),'CORAD operation sequence or sessions differ')
    for op in ops:
        logs={f'logs/{sid}/{op["operation"]}.{ext}' for ext in ('stdout','stderr')}
        allowed.update(logs)
        require(all(files[name]['bytes']<=limit(plan)['file_bytes'] for name in logs if name in files) and
                (op['pid'] is None or logs<=files.keys()),'missing or oversized CORAD operation logs')
    require(row['parts'].keys()<=slot['parts'].keys(),'undeclared CORAD parts')
    for name,ref in row['parts'].items():
        p=f'products/{sid}/{name}'; allowed.add(p)
        require(ref==files.get(p) and ref['bytes']<=slot['parts'][name],'CORAD artifact identity differs')
    if row['status']!='verified':
        require(row['status'] in NONPASS and row['reason'] and row['corad'] is None,'invalid nonpassing CORAD terminal')
        return False
    require(not row['reason'] and row['parts'].keys()==slot['parts'].keys() and len(ops)==len(recipe) and
            all(_finish(recipe[o['operation']],o) for o in ops),'CORAD incomplete functional execution')
    expect=_evaluate(slot,run/'products'/sid,ops,run/'logs'/sid)
    require(canonical_bytes(row['corad'])==canonical_bytes(expect),'CORAD original-domain quality or functional ledger differs')
    return True


def audit_slot(run,plan,slot,row):
    parts={name:_read(verify_asset(run,ref),slot['parts'][name]) for name,ref in row['parts'].items()}
    with tempfile.TemporaryDirectory(prefix='tsbench-corad-audit-') as t:
        work=Path(t); folder=work/'parts'; folder.mkdir()
        observed=_execute(run,plan,slot,parts,work,work,folder,lambda:False,[],detached=True)
    require(canonical_bytes(observed)==canonical_bytes(row['corad']),'CORAD audit differs from original-domain sealed evidence')
    return {'product_slot':slot['product_slot'],'observed':observed,'restored_frames':len(observed['frames'])}
