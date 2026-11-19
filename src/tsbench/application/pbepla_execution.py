"""Execute PBEPLA steps with bounded workers and recompute exact original-domain evidence."""
from fractions import Fraction
from pathlib import Path
import struct
import tempfile

from ..assets import ContractError, canonical_bytes, load_json, require, verify_asset
from ..planner.pbepla_execution import CALLBACK, DEFAULT_METHOD, FILE_CEILING, PROGRESSIVE, REPLAY, identity, is_pbepla, limit, steps
from ..planner.pbepla_progressive import WORD_MAGIC, boundary_source, schema_bytes
from ..qualification.pbepla_progressive import MAGIC, OUTER, _parse_frame, _verify_replay, _verify_replay_failures, quality
from ..recovery import DIRECTORY
from ..supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker
from .selfstar_execution import NONPASS, completed
from .smoke import _ref, _worker_json


def _exact(a,b,why):
    require(canonical_bytes(a)==canonical_bytes(b),why)


def _sha(data):
    return identity(data)['sha256']


def _wrap(spec,wire):
    sc = schema_bytes(spec['name'])
    return OUTER.pack(MAGIC,10,spec['count'],len(sc),len(wire))+sc+wire


def _native(spec,frame):
    return frame[OUTER.size+len(schema_bytes(spec['name'])):]


def _bad(spec,full):
    return { 'truncated_native':_wrap(spec,full[:-1]), 'zero_stored_layer':_wrap(spec,full[:7]+b'\0'+full[8:]),
             'payload_crc':_wrap(spec,full[:-1]+bytes([full[-1]^1])) }


def _input_refs(slot):
    f = slot['spec']
    out = {'input':{'bytes':8*f['count'],'sha256':f['input_sha256']},'schema':identity(schema_bytes(f['name']))}
    if slot['variant']=='input-negatives':
        out['empty-schema'] = identity(b'{}')
        out.update({f'nonfinite-{i}':identity(struct.pack('<Q',v)) for i,v in enumerate(slot['fault_policy']['nonfinite_u64'])})
    return out


def _read(path,cap):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=cap,'PBEPLA isolated or retained output outside bound')
    return path.read_bytes()


def _finish(step,op):
    return (op['status']=='failed' and op['returncode']==3 and op['pid'] is not None) if step['reject'] else completed(op)


def _call(run,plan,slot,w,logs,label,step,paths,cancelled,ops):
    fold = w/label
    fold.mkdir()
    inputs = {k:paths[v] for k,v in step['mounts'].items()}
    limits = limit(slot,plan['limits'])
    if step['tool']:
        out,op = invoke_isolated_tool(run/DIRECTORY,plan['decoder'],step['tool'],limits,fold,logs,label,inputs,step['argv'],cancelled,
                                      observe=True,file_ceiling=FILE_CEILING,private_tmp=step['tmp'])
    else:
        command,*args = step['argv']
        out,op = invoke_isolated_worker(run/DIRECTORY,plan['decoder'],DEFAULT_METHOD,limits,fold,logs,command,inputs,args,cancelled,
                                        label=label,observe=True,file_ceiling=FILE_CEILING,options_text=step['opts'])
    op.update(outputs={},private_tmp=step['tmp'])
    ops.append(op)
    require(_finish(step,op),f'PBEPLA {label}: {op["status"]} (rc={op["returncode"]}): {op["reason"]}')
    require({p.name for p in out.iterdir()}==set(step['outputs']),'PBEPLA output closure differs')
    files = {key:_read(out/key,limits['file_bytes']) for key in step['outputs']}
    op['outputs'] = {k:identity(v) for k,v in files.items()}
    return files


def _log(logs,label,step):
    stdout,stderr = logs/(label+'.stdout'), logs/(label+'.stderr')
    err = stderr.read_bytes().decode('utf-8')
    if step['reject']:
        require(not stdout.stat().st_size and err.startswith(f'plugin status {step["reject"]}: '),f'PBEPLA ABI rejection differs: {label}')
        return {'exit_status':3,'plugin_status':step['reject'],'outputs_absent':True}
    if step['tool']==CALLBACK:
        expect = label.startswith('fault-')
        require(bool(err)==expect,'unexpected replay diagnostic')
        return {'native':load_json(stdout),'error':err.rstrip('\n')}
    require(not err,'unexpected PBEPLA diagnostic')
    if step['tool']:
        return load_json(stdout)
    return _worker_json(stdout,2 if step['argv'][0]=='decode' else 1)


def _worker_info(op,wire):
    return {'backend':'tba-pbepla-rr-port','threads':1,'mode':'batch','fallback':False,'operation':op,
            'layers_stored':wire['stored'],'native_header_bytes':wire['header_bytes'],'native_payload_bytes':wire['payload_bytes']}


def _native_info(wire):
    return {'count':wire['count'],'layers':wire['stored'],'header':wire['header_bytes'],'payload':wire['payload_bytes']}


def _restored(spec,wire,data,doc):
    _exact(doc,[{'dtype':10,'count':spec['count']},_worker_info('decode',wire)],'PBEPLA ABI restore descriptor differs')
    require(len(data)==8*spec['count'],'PBEPLA ABI restore count differs')


def _read_parts(folder,slot):
    return {name:_read(folder/name,cap) for name,cap in slot['parts'].items()}


def _refs(slot,parts):
    """Compute the complete mount/output closure from retained data, not from the log itself."""
    spec = slot['spec']; variant = slot['variant']; n = spec['count']; k = len(spec['requested_eps'])
    refs = _input_refs(slot)
    outputs = {}
    if variant.startswith('budget-'):
        frame = parts[spec['frame']]; refs['budget-frame'] = identity(frame)
        if variant=='budget-at':
            outputs['abi-encode'] = {'frame':identity(frame)}
            outputs['abi-restore'] = {'out':identity(parts['restored']),'schema':refs['schema']}
        else:
            outputs['native-encode'] = {'full':identity(_native(spec,frame))}
    elif variant=='prefixes':
        word = parts[spec['word_path']]; span = 8*n
        for i,name in enumerate(spec['frame_paths'],1):
            data = word[8+i*span:8+(i+1)*span]
            frame = parts[name]
            refs[f'frame-{i}'] = identity(frame)
            refs[f'native-{i}'] = identity(_native(spec,frame))
            outputs[f'restore-{i}'] = {'out':identity(data),'schema':refs['schema']}
            outputs[f'emit-{i}'] = {'out':identity(data)}
        full = _native(spec,parts[spec['frame_paths'][-1]])
        refs['full'] = identity(full)
        refs.update({k:identity(v) for k,v in _bad(spec,full).items()})
        outputs.update({'native-encode':{'full':refs['full']},'callback-encode':{'full':refs['full']},
                        'abi-encode':{'frame':refs[f'frame-{k}']},'prefixes':{f'L{i}':refs[f'native-{i}'] for i in range(1,k+1)}})
        if 'fault_policy' in slot:
            refs['partial'] = identity(parts[slot['fault_policy']['partial']])
            outputs.update({'fault-'+key:{'full':refs['partial'] if key=='sink-fail' else identity(b'')}
                            for key in slot['fault_policy']['fault_modes']})
    return refs,outputs


def _validate(slot,parts,doc,folder):
    spec = slot['spec']; variant = slot['variant']; n = spec['count']; k = len(spec['requested_eps'])
    if variant=='input-negatives':
        return {'rejected_options':slot['fault_policy']['options'],'actual_rejections':doc}
    if variant.startswith('budget-'):
        frame = parts[spec['frame']]
        wire,_,_,_ = _parse_frame(frame,spec,k)
        result = {'value_layers':n*k,'wire':wire,'frame_sha256':_sha(frame)}
        if variant=='budget-over':
            _exact(doc['native-encode'],_native_info(wire),'PBEPLA over-budget valid frame proof differs')
            return {**result,'abi_encode':doc['abi-encode'],'abi_decode':doc['abi-restore']}
        _exact(doc['abi-encode'],[_worker_info('encode',wire)],'PBEPLA work-limit encoder descriptor differs')
        _restored(spec,wire,parts['restored'],doc['abi-restore'])
        maximum,q = quality(boundary_source(n),parts['restored'])
        require(maximum<=Fraction(wire['eps'][-1]),'PBEPLA work-limit restore exceeds effective bound')
        return {**result,'quality':q,'effective_eps':wire['eps'][-1]}
    words = parts[spec['word_path']]; span = 8*n
    raw = words[8:8+span]
    require(words.startswith(WORD_MAGIC) and len(words)==spec['word_bytes'] and _sha(raw)==spec['input_sha256'],
            'PBEPLA word evidence or original identity differs')
    layers,ce,parsed = [],[],[]
    for i,name in enumerate(spec['frame_paths'],1):
        frame = parts[name]
        wire,grid,native,body = _parse_frame(frame,spec,i)
        parsed.append((wire,grid,native,body))
        data = words[8+i*span:8+(i+1)*span]
        _restored(spec,wire,data,doc[f'restore-{i}'])
        maximum,q = quality(raw,data)
        e = wire['eps'][i-1]
        require(maximum<=Fraction(e),f'PBEPLA exact original-domain error exceeds effective bound at layer {i}')
        ce.append({'layer':i,**q})
        layers.append({'layer':i,'effective_eps':e,'incremental_payload_bytes':wire['layer_bytes'][-1],
                       'prefix_header_bytes':wire['header_bytes'],'cumulative_payload_bytes':len(body),
                       'detached_prefix_bytes':len(native),'worker_frame_bytes':len(frame),'frame_sha256':_sha(frame),**q})
    full,grid,native,body = parsed[-1]
    for wire,prefix_grid,_,prefix_body in parsed:
        require(prefix_grid==grid and wire['eps']==full['eps'] and wire['resolutions']==full['resolutions'] and
                wire['bits']==full['bits'][:wire['stored']] and prefix_body==body[:len(prefix_body)],
                'PBEPLA detached payload is not a prefix')
    result = {'wire':full,'layers':layers,'native_sha256':_sha(native)}
    prefix_log = doc['prefixes']
    if slot['method']==PROGRESSIVE:
        _exact(doc['native-encode'],_native_info(full),'PBEPLA native encoder descriptor differs')
        if 'abi-encode' in doc:
            _exact(doc['abi-encode'],[_worker_info('encode',full)],'PBEPLA ABI encoder descriptor differs')
        layer_error = 'pbepla_rr: requested layers exceed the stored layers'
        reject = {'zero_layers':layer_error,'absent_layer':layer_error}
        if n:
            reject['value_budget'] = 'pbepla_rr: value count exceeds the decode limit'
        if body:
            reject['later_crc_even_for_layer1'] = 'pbepla_rr: payload checksum mismatch'
        targets = [{'requested':e,'layers_used':i,'bound_met':True} for i,e in enumerate(full['eps'],1)]
        targets += [{'requested':full['eps'][-1]/2,'layers_used':k,'bound_met':False}]
        expected = {'count':n,'layers':k,'native_rejects':reject,'targets':targets}
        require(prefix_log==expected and all(type(t['bound_met']) is bool and type(t['layers_used']) is int for t in prefix_log['targets']),
                'PBEPLA native layer, capacity or target control differs')
        return {**result,'targets':targets,'native_rejects':reject,
                'worker_rejects':{key:doc[key] for key in ('truncated_native','zero_stored_layer','payload_crc') if key in doc}}
    _exact(prefix_log,{'count':n,'layers':k},'PBEPLA replay prefix descriptor differs')
    for i in range(1,k+1):
        _exact(doc[f'emit-{i}'],{'emitted':n,'abort_after':int(n!=0)},'PBEPLA detached callback emission/failure differs')
    policy = slot['replay_policy']
    replay = {'name':spec['name'],'scope':policy['scope'],'same_bytes_as_batch':True,
              'payload_sha256':_sha(native),'wire':full,'quality':ce,'io':doc['callback-encode']['native']}
    _verify_replay(spec,replay,policy,(full,len(native),_sha(native),ce))
    report = {**result,'replay':replay}
    if 'fault_policy' in slot:
        faults = slot['fault_policy']; partial = parts[faults['partial']]
        error = 'pbepla_rr: payload length does not match the header'
        _exact(doc['partial-reject'],{'diagnostic':error},'PBEPLA partial native restore refusal differs')
        rows = []
        for name in faults['fault_modes']:
            t = doc['fault-'+name]
            rows.append({'case':name,'error':t['error'],'io':t['native'],'source_sha256':spec['input_sha256'],
                         'max_values':n-int(name=='value-limit'),
                         'partial_artifact':{**identity(partial),'native_layer1_rejection':error} if name=='sink-fail' else None})
        _verify_replay_failures(faults,rows,spec,folder,slot['parts'][faults['partial']])
        report['faults'] = rows
    return report


def _inspect(slot,ops,docs,folder):
    parts = _read_parts(folder,slot)
    refs,outputs = _refs(slot,parts)
    for op,(label,step) in zip(ops,steps(slot).items(),strict=True):
        require(op.get('input_mounts')=={key:refs[value] for key,value in step['mounts'].items()} and
                op.get('private_tmp') is step['tmp'],'PBEPLA operation mount or scratch closure differs')
        require(op.get('outputs')==outputs.get(label,{}),'PBEPLA actual output identity or paired byte comparison differs')
    return _validate(slot,parts,docs,folder)


def _pipeline(run,plan,slot,raw,work,logs,folder,cancelled,ops,retained=None):
    spec = slot['spec']; variant = slot['variant']; k = len(spec['requested_eps'])
    stage = work/'stage'; stage.mkdir()
    paths = {}; parts = {}; docs = {}; outputs = {}
    def put(name,blob,path=None):
        p = path if path is not None else stage/name
        if path is None:
            p.write_bytes(blob)
        paths[name] = p
    require(identity(raw)==_input_refs(slot)['input'],'PBEPLA source was changed')
    put('input',raw); put('schema',schema_bytes(spec['name']))
    if variant=='input-negatives':
        put('empty-schema',b'{}')
        for i,v in enumerate(slot['fault_policy']['nonfinite_u64']):
            put(f'nonfinite-{i}',struct.pack('<Q',v))
    for label,step in steps(slot).items():
        files = _call(run,plan,slot,work,logs,label,step,paths,cancelled,ops)
        outputs[label] = files
        docs[label] = _log(logs,label,step)
        if label in ('native-encode','callback-encode'):
            put('full',files['full'])
        if label=='prefixes':
            for i,name in enumerate(spec['frame_paths'],1):
                generated = files[f'L{i}']
                parts[name] = _wrap(spec,generated)
                original = retained.get(name) if retained is not None else None
                put(f'frame-{i}',parts[name],original)
                # Callback decoder accepts native PBEP, not the ABI envelope.
                put(f'native-{i}',_native(spec,original.read_bytes()) if original is not None else generated)
            for name,blob in _bad(spec,paths['full'].read_bytes()).items():
                put(name,blob)
        if variant.startswith('budget-') and (label=='native-encode' or (variant=='budget-at' and label=='abi-encode')):
            frame = _wrap(spec,files['full']) if label=='native-encode' else files['frame']
            parts[spec['frame']] = frame
            put('budget-frame',frame,retained.get(spec['frame']) if retained is not None else None)
        if label=='fault-sink-fail':
            partial = files['full']
            parts[slot['fault_policy']['partial']] = partial
            put('partial',partial,retained.get(slot['fault_policy']['partial']) if retained is not None else None)
        if label.startswith('restore-') or (variant=='budget-at' and label=='abi-restore'):
            require(files['schema']==schema_bytes(spec['name']),'PBEPLA worker changed the output schema')
    if variant=='prefixes':
        parts[spec['word_path']] = WORD_MAGIC+raw+b''.join(outputs[f'restore-{i}']['out'] for i in range(1,k+1))
    if variant=='budget-at':
        parts['restored'] = outputs['abi-restore']['out']
    require(parts.keys()==slot['parts'].keys(),'PBEPLA retained part closure differs')
    for name,payload in parts.items():
        (folder/name).write_bytes(payload)
        if retained is not None:
            require(payload==retained[name].read_bytes(),'PBEPLA replayed retained output differs')
    return _inspect(slot,ops,docs,folder)


def _terminal(slot):
    return 'expected_rejection' if slot['variant'] in ('budget-over','input-negatives') else 'verified'


def run_slot(run,plan,slot,sample,cancelled):
    sid = slot['product_slot']; logs = run/'logs'/sid; logs.mkdir()
    row = {'product_slot':sid,'status':'validation_failed','reason':'','operations':[], 'parts':{},'pbepla':None}
    try:
        with tempfile.TemporaryDirectory(prefix='tsbench-pbepla-slot-') as tmp:
            w = Path(tmp); folder = w/'parts'; folder.mkdir()
            raw, = sample.columns
            result = _pipeline(run,plan,slot,raw,w,logs,folder,cancelled,row['operations'])
            dest = run/'products'/sid
            if slot['parts']:
                dest.mkdir()
            for name in slot['parts']:
                with (dest/name).open('xb') as out:
                    out.write((folder/name).read_bytes())
                row['parts'][name] = _ref(run,dest/name)
            row.update(status=_terminal(slot),pbepla=result)
    except (ContractError,OSError,TypeError,KeyError,ValueError) as exc:
        last = row['operations'][-1]['status'] if row['operations'] else None
        row.update(status=last if last in NONPASS else 'validation_failed',reason=str(exc))
    return row


def inspect_evidence(run,plan,slot,row,files,allowed):
    sid = slot['product_slot']; recipe = steps(slot); ops = row['operations']; limits = limit(slot,plan['limits'])
    require(set(row)=={'product_slot','status','reason','operations','parts','pbepla'} and len(ops)<=len(recipe) and
            [o['operation'] for o in ops]==list(recipe)[:len(ops)] and
            all(_finish(recipe[op['operation']],op) for op in ops[:-1]) and len({o['session_id'] for o in ops})==len(ops),
            'PBEPLA operation order or isolation differs')
    for op in ops:
        paths = {f'logs/{sid}/{op["operation"]}.{suffix}' for suffix in ('stdout','stderr')}
        allowed.update(paths)
        require(all(files[p]['bytes']<=limits['file_bytes'] for p in paths if p in files) and
                (op['pid'] is None or paths<=files.keys()),'PBEPLA operation logs missing or beyond bounds')
    folder = run/'products'/sid
    require(row['parts'].keys()<=slot['parts'].keys(),'unexpected PBEPLA part')
    for name,ref in row['parts'].items():
        p = f'products/{sid}/{name}'
        require(ref==files.get(p) and ref['bytes']<=slot['parts'][name],'PBEPLA part identity or extent differs')
        allowed.add(p)
    if row['status'] not in ('verified','expected_rejection'):
        require(row['status'] in NONPASS and row['reason'] and row['pbepla'] is None,'invalid PBEPLA nonpass terminal')
        return False
    require(row['status']==_terminal(slot) and not row['reason'] and len(ops)==len(recipe) and
            all(_finish(recipe[o['operation']],o) for o in ops) and row['parts'].keys()==slot['parts'].keys(),
            'incomplete PBEPLA execution evidence')
    docs = {k:_log(run/'logs'/sid,k,step) for k,step in recipe.items()}
    _exact(row['pbepla'],_inspect(slot,ops,docs,folder),'PBEPLA ledger disagrees with sealed evidence')
    return True


def check_same_run(plan,rows,successful):
    pairs = {s['spec']['input_id']:r for s,r in zip(plan['slots'],rows,strict=True)
             if is_pbepla(s) and s['method']==PROGRESSIVE and s['variant']=='prefixes' and r['product_slot'] in successful}
    for s,r in zip(plan['slots'],rows,strict=True):
        if not is_pbepla(s) or s['method']!=REPLAY or r['product_slot'] not in successful:
            continue
        other = pairs.get(s['spec']['input_id'])
        if other is None:
            successful.remove(r['product_slot'])
            continue
        _exact({key:r['pbepla'][key] for key in ('native_sha256','layers','wire')},
               {key:other['pbepla'][key] for key in ('native_sha256','layers','wire')},
               'PBEPLA replay differs from its same-run independent batch product')


def audit_slot(run,plan,slot,row):
    retained = {k:verify_asset(run,v) for k,v in row['parts'].items()}
    spec = slot['spec']; variant = slot['variant']
    if variant.startswith('budget-'):
        raw = boundary_source(spec['count'])
    elif variant=='input-negatives':
        batch, = [s for s in plan['slots'] if is_pbepla(s) and s['method']==PROGRESSIVE and s['variant']=='prefixes' and
                  s['spec']['name']=='weather']
        word = _read(run/'products'/batch['product_slot']/spec['word_path'],spec['word_bytes'])
        raw = word[8:8+spec['count']*8]
    else:
        raw = _read(retained[spec['word_path']], spec['word_bytes'])[8:8+spec['count']*8]
    with tempfile.TemporaryDirectory(prefix='tsbench-pbepla-audit-') as tmp:
        w = Path(tmp); folder = w/'parts'; folder.mkdir()
        observed = _pipeline(run,plan,slot,raw,w,w,folder,lambda:False,[],retained)
    _exact(observed,row['pbepla'],'PBEPLA detached replay observations differ')
    return {'product_slot':slot['product_slot'],'method':slot['method'],'variant':variant,'parts':row['parts'],'observed':observed}
