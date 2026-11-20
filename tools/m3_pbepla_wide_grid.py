#!/usr/bin/env python3
"""Run the versioned wide-grid candidate on the exact failing M3 inputs."""
from argparse import ArgumentParser
from fractions import Fraction
from hashlib import sha256
from math import isfinite, ldexp
from pathlib import Path
from struct import Struct, pack, unpack_from
import sys
from tempfile import TemporaryDirectory
from zlib import crc32

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.m3_pbepla import quality, staged_windows
from tsbench.application.m3_pbepla_grouped_timing import TOOL
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.planner.m3_pbepla import PROGRESSIVE, REPLAY
from tsbench.recovery import stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, launcher_lock

LAYERS = (1, 2, 3)
EPS = (16, 4, 1)
HEADER = Struct('<4sBBBBQIdd')
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 30}
BASELINE_ERROR = 'RrGrid: no resolution up to 30 bits gives a block narrow enough'
NEGATIVE = 'RrGrid: no resolution up to 52 bits gives a block narrow enough'


def frame(wire, count, expected_layer):
    header_len = HEADER.size + 9*len(EPS) + 8*expected_layer + 8
    require(header_len <= len(wire) <= 131072, 'PBEP candidate frame extent differs')
    magic, version, flags, layers, stored, n, delay, lo, hi = HEADER.unpack_from(wire)
    require((magic, flags, layers, stored, n, delay) == (b'PBEP', 1, 3, expected_layer, count, 64) and
            isfinite(lo) and isfinite(hi) and isfinite(hi-lo) and lo < hi, 'PBEP candidate geometry differs')
    bounds = unpack_from('<3d', wire, HEADER.size)
    require(all(isfinite(x) and 0 < x <= e for x, e in zip(bounds, EPS, strict=True)) and
            bounds[0] > bounds[1] > bounds[2], 'PBEP candidate exceeds the frozen error bounds')
    bits_off = HEADER.size + 8*layers
    resolutions = list(wire[bits_off:bits_off+layers])
    maximum = max(resolutions)
    require(maximum <= 52 and version == (1 if maximum <= 30 else 2), 'PBEP candidate version or grid limit differs')
    spans = (hi-lo, 2*bounds[0]+2*bounds[1], 2*bounds[1]+2*bounds[2])
    require(all(0 < ldexp(s, -r) <= 2*e and (r == 0 or ldexp(s, 1-r) > 2*e)
                for s, r, e in zip(spans, resolutions, bounds, strict=True)), 'PBEP candidate grid is not the minimum fitting resolution')
    layer_bits = unpack_from(f'<{stored}Q', wire, bits_off+layers)
    payload = wire[header_len:]
    body_crc, head_crc = unpack_from('<II', wire, header_len-8)
    require(all(b > 0 for b in layer_bits) and sum((b+7)//8 for b in layer_bits)==len(payload) and
            (crc32(payload), crc32(wire[:header_len-4]))==(body_crc, head_crc), 'PBEP candidate payload length or CRC differs')
    return {'version':version, 'grid':[lo,hi], 'resolutions':resolutions, 'bounds':bounds, 'layer_bits':layer_bits,
            'header_bytes':header_len, 'payload_bytes':len(payload)}, payload


def identity(blob):
    return {'bytes':len(blob), 'sha256':sha256(blob).hexdigest()}


def ref(path):
    return {'path':path.relative_to(ROOT).as_posix(), 'bytes':path.stat().st_size, 'sha256':digest(path)}


def sealed_assets(output):
    return {p.relative_to(output).as_posix(): ref(p) for p in sorted(output.rglob('*'))
            if p.is_file() and 'recovery' not in p.relative_to(output).parts and p != output/'completion.json'}


def switch_windows(switch_plan, switch_run, main, work):
    plan = load_json(switch_plan)
    binding = plan['input_switch']
    require(binding['baseline']==main and binding['does_not_replace_full_corpus_or_specialists'],
            'wide-grid switch not anchored on the same main plan')
    ledger,seal = full_run_source(plan,switch_run)
    entries = _entry_map(ROOT,load_json(verify_asset(ROOT,plan['definition']['plan'])))
    require(len(entries)==1 and plan['coverage']['datasets']==1,'pilot switch must have one bound real input')
    pairs = {row['route']:(row,item) for row,item in full_run_rows(plan,ledger) if row['selection']==87}
    require(set(pairs)=={PROGRESSIVE,REPLAY},'pilot switch omits a PBEPLA mechanism')
    (before,prog),(replay,stream) = (pairs[k] for k in (PROGRESSIVE,REPLAY))
    ds = before['dataset_id']
    require(ds==replay['dataset_id'] and before['status']==replay['status']=='quality_rejected',
            'pilot switch did not bind the quality-rejected inputs')
    work.mkdir()
    sources = []
    with staged_windows(ROOT,entries[ds],prog,stream,work) as rows:
        for (window,raw),u,v in zip(rows,before['evidence']['units'],replay['evidence']['units'],strict=True):
            key = {'column':window.column,'row_range':[window.start,window.end],'input_sha256':identity(raw)['sha256'],
                   'logical_input_bytes':len(raw),'window_ordinal':window.ordinal}
            require(all(u[k]==v[k]==p for k,p in key.items()) and u['status']==v['status'] and
                    u['layers']==v['layers'] and u['status'] in {'verified','quality_rejected'},
                    'wide-grid switch inputs differ from the two executed native routes')
            sources.append(({'dataset_id':ds,**key,'before':u['status'],'baseline':u['layers']},raw))
    require(len(sources)==6 and sum(s['before']=='quality_rejected' for s,_ in sources)==1,
            'pilot switch omits a frozen window or quality rejection')
    return {'plan':ref(switch_plan),'run':switch_run.relative_to(ROOT).as_posix(),'seal':seal},sources


def population(lock_file, source_run, work, switch=None):
    lock = load_json(lock_file)
    require(lock['build_id']==content_id({k:v for k,v in lock.items() if k!='build_id'}), 'wide-grid build lock identity differs')
    spec = load_json(verify_asset(ROOT,lock['candidate']))
    require(spec['contract']['requested_eps']==list(EPS) and spec['contract']['max_delay']==64, 'wide-grid contract differs')
    plan = load_json(verify_asset(ROOT,lock['source_plan']))
    _, seal = full_run_source(plan, source_run)
    pop = load_json(verify_asset(ROOT,lock['population']))
    require(pop['source_seal']==seal and pop['source_plan']==lock['source_plan'], 'wide-grid pilot changed frozen scope')
    entries = _entry_map(ROOT,load_json(verify_asset(ROOT,plan['definition']['plan'])))
    items = {w['work_item_id']:w for w in plan['work_items']}
    pairs = {}
    for c in pop['cases']:
        pairs.setdefault(c['dataset_id'],{})[c['route']]=c
    sources = []
    for ds,pair in sorted(pairs.items()):
        before, replay = (pair[x] for x in (PROGRESSIVE,REPLAY))
        selected = {i for i,w in enumerate(before['units']) if w['status']=='failed'}
        if ds == 'etth1':
            selected.add(0)
        if not selected:
            continue
        (work/ds).mkdir()
        with staged_windows(ROOT,entries[ds],items[before['work_item_id']],items[replay['work_item_id']],work/ds) as rows:
            for i,(window,raw) in enumerate(rows):
                if i not in selected:
                    continue
                u, v = before['units'][i], replay['units'][i]
                key = {'column':window.column,'row_range':[window.start,window.end],'input_sha256':identity(raw)['sha256'],
                       'logical_input_bytes':len(raw),'window_ordinal':window.ordinal}
                require(all(u[k]==v[k]==p for k,p in key.items()) and u['status']==v['status'] and
                        (u.get('reason')==v.get('reason')==BASELINE_ERROR if u['status']=='failed' else u['layers']==v['layers']),
                        'wide-grid pilot inputs differ from both frozen native routes')
                sources.append(({'dataset_id':ds,**key,'before':u['status'],'baseline':u.get('layers',[])},raw))
    require(len(sources)==4 and sum(s['before']=='failed' for s,_ in sources)==3, 'pilot omits a frozen failure or legacy control')
    expected = {'schema':'bmk.pbepla-wide-grid-pilot/1', 'source_run':source_run.relative_to(ROOT).as_posix(), 'source_seal':seal,
                'build':ref(lock_file), 'launchers':launcher_lock(), 'limits':LIMITS, 'windows':[x for x,_ in sources]}
    if switch:
        expected['input_switch'], supplemental = switch_windows(*switch, lock['source_plan'], work/'switch')
        sources.extend(supplemental)
        expected['windows'] = [s for s,_ in sources]
    return lock, expected, sources


def call(lane, closure, address, mode, inputs, layer=None):
    address.mkdir(parents=True)
    indexes = [name.split('-')[0] for name in inputs]
    args = [mode, *([str(layer)] if layer is not None else []), *indexes]
    out, proc = invoke_isolated_tool(lane/'recovery',closure,TOOL,LIMITS,address,address,mode,inputs,args,lambda:False,
                                    private_tmp=True,bind_inputs=True)
    require(proc['status']=='completed' and proc['returncode']==0 and not (address/(mode+'.stderr')).stat().st_size,
            f'isolated {mode}: {proc["status"]}: '+(address/(mode+'.stderr')).read_text()[:400])
    rows = (address/(mode+'.stdout')).read_text().splitlines()
    log = [parse_json(r,'wide-grid native observation') for r in rows]
    require(len(log)==2*len(inputs)+1 and log[-1]['units']==len(inputs) and
            [r['index'] for r in log[:-1:2]]==[int(i) for i in indexes], 'native control omitted a pilot unit')
    write_new(address/'process.json',proc)
    return out,log[:-1:2]


def run(build, source_run, output, switch=None):
    require(output.is_relative_to(ROOT/'results'), 'pilot output outside workspace results')
    output.mkdir(parents=True)
    with TemporaryDirectory(prefix='materialize-',dir=output) as tmp:
        lock, plan, sources = population(build,source_run,Path(tmp),switch)
    write_new(output/'plan.json',plan)
    closures = lock['closures']
    for name,closure in closures.items():
        lane = output/name
        lane.mkdir()
        stage_recovery(ROOT,lane,closure)
    work = output/'inputs'; work.mkdir()
    raw_paths = {str(i):work/str(i) for i in range(len(sources))}
    for path,(_,raw) in zip(raw_paths.values(),sources,strict=True):
        path.write_bytes(raw)
    summary = [{'source':s,'legacy':{},'candidate':{},'restores':{}} for s,_ in sources]
    enc = {}
    for name,closure in closures.items():
        for mode in ('progressive','replay'):
            out,rows = call(output/name,closure,output/'steps'/name/mode,mode,raw_paths)
            enc[name,mode] = out
            for destination,row in zip(summary,rows,strict=True):
                destination[name][mode]=row
    for i,(source,raw) in enumerate(sources):
        row = summary[i]
        want_legacy = 'failed' if source['before']=='failed' else 'encoded'
        require(all(r['status']==want_legacy and (want_legacy=='encoded' or r['reason']==BASELINE_ERROR)
                    for r in row['legacy'].values()), 'legacy did not reproduce frozen native status')
        statuses = {r['status'] for r in row['candidate'].values()}
        if statuses != {'encoded'}:
            row['status']='candidate_native_failed'
            continue
        previous = b''
        for k in LAYERS:
            n = f'{i}-{k}'
            encoded = local_file(enc['candidate','progressive'],n)
            wire = encoded.read_bytes()
            require(local_file(enc['candidate','replay'],n).read_bytes()==wire, 'candidate native replay differs from progressive bytes')
            fields,payload = frame(wire,len(raw)//8,k)
            require(payload.startswith(previous), 'candidate payload not nested')
            previous = payload
            if want_legacy=='encoded':
                old = local_file(enc['legacy','progressive'],n)
                require(fields['version']==1 and local_file(enc['legacy','replay'],n).read_bytes()==old.read_bytes() and
                        digest(old)==source['baseline'][k-1]['frame_sha256'], 'legacy PBEP v1 did not reproduce history')
                if source['before']=='verified':
                    require(old.read_bytes()==wire,'candidate changed historically verified PBEP v1 control bytes')
            else:
                require(fields['version']==2, 'wide output incorrectly labeled PBEP v1')
            restored = {}
            for mode in ('restore-batch','restore-callback'):
                dest, obs = call(output/'candidate',closures['candidate'],output/'steps'/'candidate'/f'{i}-{k}-{mode}',
                                 mode,{n:encoded},k)
                require(obs[0]['status']=='restored',f'candidate did not restore detached prefix: {obs[0]}')
                restored[mode] = local_file(dest,n).read_bytes()
            recovered = restored['restore-batch']
            require(recovered==restored['restore-callback'], 'candidate detached batch/callback results differ')
            err, metrics = quality(raw,recovered)
            row['restores'][str(k)]={'frame':identity(wire), 'restore':identity(recovered), 'wire':fields, **metrics,
                                      'quality_passed':err<=Fraction(fields['bounds'][k-1])}
            if source['before']=='verified':
                require(identity(recovered)['sha256']==source['baseline'][k-1]['restored_sha256'], 'old recovered PBEP v1 differs')
            elif want_legacy=='failed':
                _, obs = call(output/'legacy',closures['legacy'],output/'steps'/'legacy'/f'{i}-{k}-reject-v2',
                              'restore-batch',{n:encoded},k)
                require(obs[0]['status']=='failed' and 'unsupported container version' in obs[0]['reason'], 'legacy accepted wide PBEP v2')
            else:
                out, obs = call(output/'legacy',closures['legacy'],output/'steps'/'legacy'/f'{i}-{k}-restore-candidate-v1',
                                'restore-batch',{n:encoded},k)
                require(obs[0]['status']=='restored' and local_file(out,n).read_bytes()==recovered,
                        'legacy decoder cannot recover compatibility-version PBEP v1 candidate')
                out, obs = call(output/'legacy',closures['legacy'],output/'steps'/'legacy'/f'{i}-{k}-restore-baseline-v1',
                                'restore-batch',{n:old},k)
                legacy_restored = local_file(out,n).read_bytes()
                _, q = quality(raw,legacy_restored)
                require(obs[0]['status']=='restored' and identity(legacy_restored)['sha256']==source['baseline'][k-1]['restored_sha256'] and
                        q['exact_max_abs_error']==source['baseline'][k-1]['exact_max_abs_error'],
                        'legacy v1 quality rejection no longer reproduces')
        row['status']='verified' if all(r['quality_passed'] for r in row['restores'].values()) else 'quality_rejected'
    index = str(len(sources))
    beyond = work/index; beyond.write_bytes(pack('<2d',0,2.0**60))
    _, limit = call(output/'candidate',closures['candidate'],output/'steps'/'candidate'/'limit','progressive',{index:beyond})
    require(limit[0]['status']=='failed' and limit[0]['reason']==NEGATIVE,'candidate did not reject impossible 52-bit geometry')
    result = {'schema':'bmk.pbepla-wide-grid-pilot-report/1', 'plan_id':content_id(plan), 'windows':summary,
              'resolution_limit_rejection':limit[0], 'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}
    write_new(output/'report.json',result)
    body = {'schema':'bmk.pbepla-wide-grid-pilot-seal/1','files':sealed_assets(output),'plan_id':result['plan_id']}
    write_new(output/'completion.json',{**body,'seal_id':content_id(body)})
    print([(r['source']['dataset_id'],r['source']['row_range'],r['status']) for r in summary])


def verify(output):
    plan = load_json(local_file(output,'plan.json'))
    plan_id = content_id(plan)
    body = {'schema':'bmk.pbepla-wide-grid-pilot-seal/1','files':sealed_assets(output),'plan_id':plan_id}
    require(load_json(local_file(output,'completion.json'))=={**body,'seal_id':content_id(body)}, 'wide-grid pilot seal differs')
    build = verify_asset(ROOT,plan['build'])
    switch = plan.get('input_switch')
    inputs = (verify_asset(ROOT,switch['plan']), ROOT/switch['run']) if switch else None
    with TemporaryDirectory(prefix='pbepla-wide-verify-') as tmp:
        lock, regenerated, sources = population(build,ROOT/plan['source_run'],Path(tmp),inputs)
    require(regenerated==plan,'wide-grid pilot plan does not independently refreeze')
    for name,closure in lock['closures'].items():
        for path,file in closure['files'].items():
            p = verify_asset(output/name/'recovery',{'path':path,'sha256':file['sha256']})
            require(p.stat().st_size==file['bytes'],'wide-grid staged executable closure differs')
    seen = set()

    def terminal(lane, step, mode, mounts):
        directory = output/'steps'/lane/step
        state = load_json(local_file(directory,'process.json'))
        require(state['status']=='completed' and state['returncode']==0 and state['operation']==mode and
                type(state['pid']) is int and state['session_id'] and state['session_id'] not in seen and
                state['input_mounts']==mounts and not local_file(directory,mode+'.stderr').stat().st_size,
                'wide-grid process terminal or input-only isolation differs')
        seen.add(state['session_id'])
        lines = [parse_json(r) for r in local_file(directory,mode+'.stdout').read_text().splitlines()]
        require(len(lines)==2*len(mounts)+1 and lines[-1]['units']==len(mounts) and
                [r['index'] for r in lines[:-1:2]]==[int(i.split('-')[0]) for i in mounts],
                'wide-grid native terminal population differs')
        return directory/'out',lines[:-1:2]

    mounts = {}
    for i,(_,raw) in enumerate(sources):
        require(local_file(output/'inputs',str(i)).read_bytes()==raw,'wide-grid source bytes differ from r40')
        mounts[str(i)] = identity(raw)
    result = load_json(local_file(output,'report.json'))
    require(result['plan_id']==plan_id and len(result['windows'])==len(sources) and
            all(result[k] is False for k in ('stage_accepted','qualification_granted','timing_admitted')),
            'wide-grid report scope differs')
    enc = {(lane,mode):terminal(lane,mode,mode,mounts) for lane in ('legacy','candidate') for mode in ('progressive','replay')}
    for i,((source,raw),record) in enumerate(zip(sources,result['windows'],strict=True)):
        require(source==record['source'],'wide-grid report window differs')
        for (lane,mode),(_,rows) in enc.items():
            require(rows[i]==record[lane][mode],'wide-grid encode transcript differs')
        legacy = source['before']!='failed'
        require(all(r['status']=='encoded' if legacy else r['status']=='failed' and r['reason']==BASELINE_ERROR
                    for r in record['legacy'].values()), 'wide-grid baseline terminal differs')
        if any(r['status']!='encoded' for r in record['candidate'].values()):
            require(record['status']=='candidate_native_failed' and not record['restores'],'candidate native failure replaced')
            continue
        assessed, previous = {}, b''
        for k in LAYERS:
            n = f'{i}-{k}'
            wire = local_file(enc['candidate','progressive'][0],n).read_bytes()
            require(local_file(enc['candidate','replay'][0],n).read_bytes()==wire,'retained replay differs')
            fields,payload = frame(wire,len(raw)//8,k)
            require(fields['version']==(1 if legacy else 2) and payload.startswith(previous),'wide-grid detached prefix scope differs')
            previous = payload
            mounted = {n:identity(wire)}
            outputs = []
            for mode in ('restore-batch','restore-callback'):
                out,obs = terminal('candidate',f'{i}-{k}-{mode}',mode,mounted)
                require(obs==[{'index':i,'status':'restored','layer':k}], 'wide-grid detached native restore terminal differs')
                outputs.append(local_file(out,n).read_bytes())
            require(outputs[0]==outputs[1], 'candidate recoveries differ')
            error,metrics = quality(raw,outputs[0])
            assessed[str(k)] = {'frame':identity(wire),'restore':identity(outputs[0]),'wire':fields,**metrics,
                                'quality_passed':error<=Fraction(fields['bounds'][k-1])}
            if legacy:
                baseline_wire = local_file(enc['legacy','progressive'][0],n).read_bytes()
                baseline = source['baseline'][k-1]
                require(local_file(enc['legacy','replay'][0],n).read_bytes()==baseline_wire and
                        identity(baseline_wire)['sha256']==baseline['frame_sha256'],'legacy v1 source replay differs')
                if source['before']=='verified':
                    require(baseline_wire==wire and identity(outputs[0])['sha256']==baseline['restored_sha256'], 'legacy byte equivalence differs')
                else:
                    for label, expected in (('candidate',wire),('baseline',baseline_wire)):
                        out,obs = terminal('legacy',f'{i}-{k}-restore-{label}-v1','restore-batch',{n:identity(expected)})
                        require(obs==[{'index':i,'status':'restored','layer':k}],'legacy v1 restore terminal differs')
                        legacy_values = local_file(out,n).read_bytes()
                        if label=='candidate':
                            require(legacy_values==outputs[0],'candidate PBEP v1 is not backward compatible')
                        else:
                            exact, q = quality(raw,legacy_values)
                            require(q['exact_max_abs_error']==baseline['exact_max_abs_error'] and
                                    identity(legacy_values)['sha256']==baseline['restored_sha256'] and
                                    (exact<=Fraction(baseline['effective_eps'])) is baseline['quality_passed'],
                                    'historical PBEP quality rejection did not reproduce')
            else:
                out,obs = terminal('legacy',f'{i}-{k}-reject-v2','restore-batch',mounted)
                require(obs==[{'index':i,'status':'failed','reason':'pbepla_rr: unsupported container version'}] and
                        not any(out.iterdir()), 'legacy wide-grid rejection differs')
        want = 'verified' if all(r['quality_passed'] for r in assessed.values()) else 'quality_rejected'
        require(canonical_bytes(assessed)==canonical_bytes(record['restores']) and record['status']==want,
                'original-domain error or per-prefix accounting did not recompute')
    negative = pack('<2d',0,2.0**60)
    index = str(len(sources))
    require(local_file(output/'inputs',index).read_bytes()==negative,'negative grid control differs')
    out,obs = terminal('candidate','limit','progressive',{index:identity(negative)})
    require(obs==[result['resolution_limit_rejection']]==[{'index':len(sources),'status':'failed','reason':NEGATIVE}] and
            not any(out.iterdir()), 'out-of-limit grid terminal differs')
    require({p.parent for p in (output/'steps').rglob('process.json')} and
            len(list((output/'steps').rglob('process.json')))==len(seen), 'wide-grid contains unexpected process transcripts')
    print({'windows':len(sources),'independent_processes':len(seen),'statuses':[r['status'] for r in result['windows']]})


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    for name in ('build','source-run','out'):
        p.add_argument('--'+name,type=Path)
    p.add_argument('--verify',type=Path)
    p.add_argument('--switch',nargs=2,type=Path,metavar=('PLAN','RUN'))
    args = p.parse_args()
    try:
        if args.verify and not any((args.build,args.source_run,args.out,args.switch)):
            verify(args.verify.resolve(strict=True))
        elif not args.verify and all((args.build,args.source_run,args.out)):
            switch = tuple(p.resolve(strict=True) for p in args.switch) if args.switch else None
            run(args.build.resolve(strict=True),args.source_run.resolve(strict=True),args.out.resolve(),switch)
        else:
            p.error('pass --verify RUN or all of --build, --source-run and --out')
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
