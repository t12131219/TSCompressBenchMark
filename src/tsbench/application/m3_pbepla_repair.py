"""Run the repaired PBEPLA corpus route with a frame-only detached decoder."""
from fractions import Fraction
from hashlib import sha256
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory

from .m3_pbepla import GROUP, _quality_layers, quality, staged_windows
from ..assets import ContractError, local_file, parse_json, require
from ..planner.m3_pbepla import DRIVER, PROGRESSIVE, REPLAY
from ..planner.m3_pbepla_repair import TOOL
from ..qualification.pbep_wide import CAP, EPS, LAYERS, parse_prefix
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import invoke_isolated_tool


def _native(bundle, binding, tmp, mode, inputs, processes, layer=None):
    with TemporaryDirectory(prefix='native-',dir=tmp) as d:
        step = Path(d)
        files = {}
        for name,data in inputs.items():
            files[name] = step/name
            files[name].write_bytes(data)
        indexes = [int(n.split('-')[0]) for n in files]
        args = [mode, *([str(layer)] if layer else []), *map(str,indexes)]
        dest, proc = invoke_isolated_tool(bundle, binding['decoder'], TOOL, binding['limits'], step, step, mode, files,
                                          args, lambda:False, observe=True, private_tmp=True, bind_inputs=True)
        stderr = local_file(step,mode+'.stderr').read_text()
        processes.append({'mode':mode,'layer':layer,'process':proc})
        require(proc['status']=='completed' and proc['returncode']==0 and not stderr,
                f'PBEPLA isolated {mode}: {proc["status"]}: {stderr[:400]}')
        log = [parse_json(line,'PBEPLA repaired native observation')
               for line in local_file(step,mode+'.stdout').read_text().splitlines()]
        rows = log[:-1:2]
        require(len(log)==2*len(indexes)+1 and log[-1]['units']==len(indexes) and [r['index'] for r in rows]==indexes,
                'PBEPLA changed native control observation population')
        expected = set()
        for i,r in zip(indexes,rows,strict=True):
            if r['status']=='failed':
                require(bool(r['reason']), 'PBEPLA native refusal had no reason')
            elif layer:
                require(r['status']=='restored' and r['layer']==layer, 'PBEPLA detached restore changed layer')
                expected.add(f'{i}-{layer}')
            else:
                require(r['status']=='encoded' and 8*r['rows']==len(inputs[str(i)]), 'PBEPLA changed input geometry')
                expected.update(f'{i}-{k}' for k in LAYERS)
        require({p.name for p in dest.iterdir()}==expected,'PBEPLA output set differs from its native terminal')
        products = {}
        for name in expected:
            f = local_file(dest,name)
            require(not (dest/name).is_symlink() and 0 < f.stat().st_size <= CAP,'PBEPLA output exceeds declared file bound')
            products[name] = f.read_bytes()
        return rows,products


def assess(raw, frames, restored, observed, replay):
    n = len(raw)//8
    parsed = [parse_prefix(w,n,k) for k,w in zip(LAYERS,frames,strict=True)]
    geometry,bits,sizes,body = parsed[-1]
    require(all(g==geometry and b==bits[:k] and z==sizes[:k] and p==body[:len(p)]
                for k,(g,b,z,p) in zip(LAYERS,parsed,strict=True)), 'PBEPLA prefixes are not one nested stream')
    if geometry[0]==1:
        return _quality_layers(raw,frames,restored,observed,replay)
    layers = []
    _,_,_,eps,_ = geometry
    for k, wire, values in zip(LAYERS,frames,restored,strict=True):
        error, metrics = quality(raw,values)
        payload = len(parsed[k-1][3])
        layers.append({'layer':k, 'requested_eps':EPS[k-1], 'effective_eps':eps[k-1], **metrics,
                       'quality_passed':error<=Fraction(eps[k-1]), 'frame_sha256':sha256(wire).hexdigest(),
                       'bytes':len(wire), 'header_bytes':len(wire)-payload, 'payload_bytes':payload,
                       'layer_payload_bytes':sizes[k-1], 'pbep_version':2})
    full = len(frames[-1]); io = observed['replay']; payload = len(body)
    require(observed['rows']==n and observed['native_full_bytes']==full,'PBEPLA v2 native extent differs')
    if replay:
        retries = io['native_numerical_retries']
        require(type(retries) is int and retries >= 0,'PBEPLA v2 replay retries not observed')
        passes = 3+retries
        expected = {'result':0, 'rewind_calls':passes, 'eof_passes':passes, 'native_passes':passes,
                    'first_sink_after_pass':passes, 'source_bytes_read':8*n*passes, 'native_value_count':n,
                    'native_buffer_slots':3*(64+2), 'sink_bytes':full,'temp_bytes_read':3*payload, 'temp_seeks':9,
                    'temp_files_created':3*(1+retries),'temp_files_closed':3*(1+retries),'same_bytes_as_batch':True}
        require(all(io[k]==v for k,v in expected.items()) and io['first_sink_ns']>0 and io['sink_calls']>=1 and
                io['temp_bytes_written']>=io['temp_peak_live_bytes']>=payload and
                (retries or io['temp_bytes_written']==io['temp_peak_live_bytes']==payload),'PBEPLA v2 replay traffic differs')
    else:
        require(io is None,'PBEPLA v2 batch route reported replay activity')
    return {'layers':layers,'quality_passed':all(x['quality_passed'] for x in layers),'full_frame_bytes':full,
            'full_frame_sha256':layers[-1]['frame_sha256'],'replay':io}


def _group(bundle,binding,work,raw,replay,processes):
    rows, products = _native(bundle,binding,work,'replay' if replay else 'progressive',
                              {str(i):x for i,x in enumerate(raw)},processes)
    recovery, failures = {}, {}
    for k in LAYERS:
        inputs = {f'{r["index"]}-{k}':products[f'{r["index"]}-{k}'] for r in rows if r['status']=='encoded'}
        if not inputs:
            break
        observations, values = _native(bundle,binding,work,'restore-callback' if replay else 'restore-batch',inputs,processes,k)
        recovery.update(values)
        for r in observations:
            if r['status']=='failed':
                failures.setdefault(r['index'],r['reason'])
    for r in rows:
        i = r['index']
        frames = [products[f'{i}-{k}'] for k in LAYERS] if r['status']=='encoded' else None
        if r['status']=='failed' or i in failures:
            yield {'status':'failed','reason':r.get('reason',failures.get(i))},frames
            continue
        try:
            proof = assess(raw[i],frames,[recovery[f'{i}-{k}'] for k in LAYERS],r,replay)
        except ContractError as exc:
            yield {'status':'failed','reason':str(exc)},frames
        else:
            yield {'status':'verified' if proof['quality_passed'] else 'quality_rejected',**proof},frames


def run_corpus(root, plan, item, partner, entry, work, run):
    binding = plan['build']['pbepla_repair']
    folder = run/'pbepla-repaired-runtime'
    if not folder.exists():
        folder.mkdir()
        stage_recovery(root,folder,binding['decoder'])
    replay = item['route']==REPLAY
    progressive,replay_item = (partner,item) if replay else (item,partner)
    require((progressive['route'],replay_item['route'])==(PROGRESSIVE,REPLAY),'mismatched PBEPLA pair')
    units, retained, groups = [], {}, []
    with staged_windows(root,entry,progressive,replay_item,work) as source:
        while group := list(islice(source,GROUP)):
            calls = []
            groups.append({'first_unit':len(units),'units':len(group),'operations':calls})
            try:
                rows = list(_group(folder/DIRECTORY,binding,work,[data for _,data in group],replay,calls))
            except (ContractError,OSError) as exc:
                rows = [({'status':'failed','reason':str(exc)},None)]*len(group)
            for (window,raw),(proof,frames) in zip(group,rows,strict=True):
                scope = {'column':window.column,'row_range':[window.start,window.end],'window_ordinal':window.ordinal,
                         'logical_input_bytes':len(raw),'input_sha256':sha256(raw).hexdigest()}
                units.append({**scope,**proof})
                status = proof['status']
                if frames and status not in retained:
                    rel = Path('retained')/item['work_item_id']/status
                    (run/rel).mkdir(parents=True)
                    parts = []
                    for k,wire in zip(LAYERS,frames,strict=True):
                        path = rel/f'L{k}.pbep'; (run/path).write_bytes(wire)
                        parts.append({'path':path.as_posix(),'bytes':len(wire),'sha256':sha256(wire).hexdigest()})
                    retained[status] = {**scope,'parts':parts}
    counts = item['input']['size_estimate']
    logical = sum(u['logical_input_bytes'] for u in units)
    require((len(units),logical)==(counts['input_units'],counts['native_input_bytes_one_pass']),
            'PBEPLA repaired window population differs from M0')
    return {'driver':DRIVER,'implementation':binding['implementation'],'native_groups':groups,'units':units,
            'input_bytes_one_pass':logical,'framing':'native_pbep_rank1_f64_implicit_axis','retained_samples':retained,
            'failed_units':sum(u['status']=='failed' for u in units),
            'quality_rejected_units':sum(u['status']=='quality_rejected' for u in units),
            'full_frame_bytes':sum(u.get('full_frame_bytes',0) for u in units),
            'verify_each_detached_prefix':True,'timing_admitted':False,
            'replay_scope':'finite_rewindable_source_callbacks_and_logical_temp_stdio_not_physical_io' if replay else None}
