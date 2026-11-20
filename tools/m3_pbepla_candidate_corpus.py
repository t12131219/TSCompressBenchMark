#!/usr/bin/env python3
"""Single-ledger full-corpus validation of the unregistered exact PBEP candidate."""
from argparse import ArgumentParser
from collections import Counter
from contextlib import ExitStack
from fractions import Fraction
from itertools import islice
from pathlib import Path
from shutil import disk_usage
from tempfile import TemporaryDirectory
from time import sleep

from m3_pbepla_wide_grid import ROOT, LAYERS, call, frame, identity, ref
from tsbench.application.m3_pbepla import GROUP, quality, staged_windows
from tsbench.application.m3_pbepla_grouped_timing import _parts, _read_pack
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_source
from tsbench.application.smoke import _line, write_new
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.planner.m3_pbepla import PROGRESSIVE, REPLAY
from tsbench.recovery import stage_recovery
from tsbench.supervisor import timing_resource
from tsbench.supervisor.isolated_worker import launcher_lock

SCHEMA = 'bmk.m3-pbepla-candidate-corpus/1'
GROUPED = ('plan.json','population.json','trials.jsonl','environment.json','report.json')
PRODUCTS = ('plan.json','windows.jsonl','products.bin','report.json')
MODES = {PROGRESSIVE: ('progressive','restore-batch'), REPLAY: ('replay','restore-callback')}


def checked(reference):
    path = verify_asset(ROOT,reference)
    require(path.stat().st_size==reference['bytes'],'candidate source asset changed size')
    return path


def signed(doc,key):
    require(doc[key]==content_id({k:v for k,v in doc.items() if k!=key}),f'{key} differs from content')


def freeze(lock_path,source_run,anchor,pilot,projection):
    lock = load_json(lock_path)
    signed(lock,'build_id')
    candidate = load_json(checked(lock['candidate']))
    signed(candidate,'candidate_id')
    require(candidate['contract']['absolute_error_comparison']=='binary64_exact_boundary_for_native_batch_and_replay',
            'full candidate run must use the exact-bound build')
    source = load_json(checked(lock['source_plan']))
    _,source_seal = full_run_source(source,source_run)
    pop = load_json(checked(lock['population']))
    require(pop['source_seal']==source_seal and pop['source_plan']==lock['source_plan'], 'grouped population not derived from r40')
    old = load_json(local_file(anchor,'completion.json'))
    signed(old,'seal_id')
    ap = load_json(local_file(anchor,'plan.json'))
    require(old['run_id']==anchor.name and old['plan_content_id']==ap['plan_content_id'] and
            old['schema']=='bmk.m3-pbepla-grouped-timing/1-seal' and set(old['files'])==set(GROUPED) and
            old['files']['population.json']['sha256']==lock['population']['sha256'] and
            ap['source_seal']==source_seal and ap['dataset_projection'] is None and
            digest(local_file(anchor,'plan.json'))==old['files']['plan.json']['sha256'],
            'legacy frame anchors are not the full sealed r40 PBEPLA population')
    pre = load_json(local_file(pilot,'completion.json'))
    signed(pre,'seal_id')
    pp = load_json(checked(pre['files']['plan.json']))
    pr = load_json(checked(pre['files']['report.json']))
    require(pre['plan_id']==pr['plan_id']==content_id(pp) and pp['build']==ref(lock_path) and pp['source_seal']==source_seal and
            'input_switch' in pp and len(pr['windows'])==10 and all(w['status']=='verified' for w in pr['windows']),
            'full candidate build has no completed exact-window/NOAA preflight')
    entries = _entry_map(ROOT,load_json(checked(source['definition']['plan'])))
    items = {w['work_item_id']:w for w in source['work_items']}
    pairs = {}
    for c in pop['cases']:
        p = pairs.setdefault(c['dataset_id'],{})
        require(c['route'] not in p,'legacy window population duplicates a route')
        p[c['route']] = c
    require(len(pairs)==23 and sum(len(p[PROGRESSIVE]['units']) for p in pairs.values())==20524 and
            all(set(p)==set(MODES) for p in pairs.values()), 'not the 23-file M3 PBEPLA denominator')
    for ds,pair in pairs.items():
        p,r = (pair[k] for k in MODES)
        require(p['canonical_object_id']==r['canonical_object_id']==entries[ds]['canonical']['object_id'] and
                len(p['units'])==len(r['units']) and
                all({k:v for k,v in x.items() if k!='replay'}=={k:v for k,v in y.items() if k!='replay'}
                    for x,y in zip(p['units'],r['units'],strict=True)), 'frozen native routes disagree about PBEPLA windows')
    require(projection is None or projection in pairs,'unknown PBEPLA dataset projection')
    population = [(ds,p) for ds,p in pairs.items() if projection is None or ds==projection]
    body = {'schema':SCHEMA+'-plan','build':ref(lock_path),'primary_run':source_run.relative_to(ROOT).as_posix(),
            'source_seal':source_seal,'anchor_seal':ref(anchor/'completion.json'),'pilot_seal':ref(pilot/'completion.json'),
            'dataset_projection':projection,'datasets':{ds:len(p[PROGRESSIVE]['units']) for ds,p in population},
            'windows':sum(len(p[PROGRESSIVE]['units']) for _,p in population),'group_limit':GROUP,'launchers':launcher_lock(),
            'code':{ref(Path(__file__).resolve())['path']:digest(Path(__file__)),
                    'tools/m3_pbepla_wide_grid.py':digest(ROOT/'tools/m3_pbepla_wide_grid.py')},
            'scope':'unregistered candidate; original geometry and quality; mismatch remains rejected; no timing admission'}
    return {**body,'plan_id':content_id(body)},lock,population,entries,items


def jobs(population,entries,items,anchor,temp):
    for ds,pair in population:
        before,replay = (pair[k] for k in MODES)
        old = anchor/'cases'/ds
        streams = {k:_read_pack(local_file(old,f'L{k}'),_parts(before,k)) for k in LAYERS}
        with TemporaryDirectory(prefix='source-',dir=temp) as work, \
                staged_windows(ROOT,entries[ds],items[before['work_item_id']],items[replay['work_item_id']],Path(work)) as source:
            def windows():
                for i,((geometry,raw),unit) in enumerate(zip(source,before['units'],strict=True)):
                    key = {'column':geometry.column,'window_ordinal':geometry.ordinal,'row_range':[geometry.start,geometry.end],
                           'logical_input_bytes':len(raw),'input_sha256':identity(raw)['sha256']}
                    require(all(unit[k]==v for k,v in key.items()), f'{ds}: frozen PBEPLA input differs at {i}')
                    prior = {k:next(streams[k]) for k in LAYERS} if unit['status']!='failed' else {}
                    yield i,key,unit,raw,prior
            batches = windows()
            while group := list(islice(batches,GROUP)):
                yield ds,group
        require(all(next(s,None) is None for s in streams.values()), 'unconsumed legacy anchor frames')


class Operations:
    """Keep one grouped ledger and one payload file; deduplicate only within a bounded group."""
    def __init__(self,run,lock,pack,workspace,saved=None,seen=None):
        self.run,self.lock,self.pack,self.workspace,self.saved,self.seen = run,lock,pack,workspace,saved,seen
        self.calls,self.cache,self.index = [],{},0

    def invoke(self,lane,mode,inputs,layer=None):
        sequence = list(inputs)
        require(sequence and len(sequence)<=GROUP, 'invalid planned PBEPLA group population')
        expected_in = {k:identity(v) for k,v in inputs.items()}
        prefix = {'lane':lane,'mode':mode,'layer':layer}
        outputs = {}
        if self.saved is None:
            with TemporaryDirectory(prefix='process-',dir=self.workspace) as tmp:
                work = Path(tmp)
                files = {}
                for n,raw in inputs.items():
                    p = work/n
                    p.write_bytes(raw)
                    files[n] = p
                dest,rows = call(self.run/lane,self.lock['closures'][lane],work/'step',mode,files,layer)
                state = load_json(local_file(work/'step','process.json'))
                for p in sorted(dest.iterdir()):
                    wire = local_file(dest,p.name).read_bytes()
                    meta = identity(wire)
                    key = (meta['bytes'],meta['sha256'])
                    if key not in self.cache:
                        self.cache[key] = {'offset':self.pack.tell(),**meta}
                        self.pack.write(wire)
                    outputs[p.name] = wire
                out_refs = {n:self.cache[(len(raw),identity(raw)['sha256'])] for n,raw in outputs.items()}
        else:
            ob = self.saved[self.index]
            require(all(ob[k]==v for k,v in prefix.items()), 'candidate operation order differs')
            state,rows,out_refs = (ob[k] for k in ('process','native','products'))
            for n,meta in sorted(out_refs.items()):
                offset = meta['offset']
                if offset not in self.cache:
                    require(self.pack.tell()==offset and 0<meta['bytes']<=131072,'invalid/gapped candidate product reference')
                    self.cache[offset] = self.pack.read(meta['bytes'])
                outputs[n] = self.cache[offset]
                require(identity(outputs[n])=={k:meta[k] for k in ('bytes','sha256')}, 'candidate product digest differs')
            require(state['session_id'] not in self.seen,'candidate reused an isolated process')
            self.seen.add(state['session_id'])
        require(state['status']=='completed' and state['returncode']==0 and state['operation']==mode and
                state['pid'] and state['session_id'] and state['input_mounts']==expected_in and
                [r['index'] for r in rows]==[int(n.split('-')[0]) for n in sequence], 'candidate operation input or terminal differs')
        wanted = set()
        for n,r in zip(sequence,rows,strict=True):
            if r['status']=='failed':
                require(bool(r['reason']), 'candidate failure lacks a reason')
            elif layer is None:
                require(r['status']=='encoded' and r['rows']*8==len(inputs[n]), 'candidate encode extent differs')
                wanted.update(f'{n}-{k}' for k in LAYERS)
                if mode=='replay':
                    require(r['replay']['same_bytes_as_batch'], 'native replay did not match its serialized control')
            else:
                require(r['status']=='restored' and r['layer']==layer, 'candidate restore did not consume detached prefix')
                wanted.add(n)
        require(wanted==set(outputs), 'candidate native process returned unexpected products')
        self.calls.append({**prefix,'process':state,'native':rows,'products':out_refs})
        self.index += 1
        return outputs,{n:r for n,r in zip(sequence,rows,strict=True)}


def assess_group(group,operations):
    sources = {str(i):w for i,w in enumerate(group)}
    raw = {n:w[3] for n,w in sources.items()}
    results = {n:{'ordinal':w[0],'input':w[1],'baseline_status':w[2]['status'],'routes':{},'compatibility':{}}
               for n,w in sources.items()}
    wires, restorations = {},{}
    for route,(encode,decode) in MODES.items():
        wire,obs = operations.invoke('candidate',encode,raw)
        wires[route] = wire
        restored = restorations.setdefault(route,{})
        failures = {}
        for layer in LAYERS:
            inputs = {f'{n}-{layer}':wire[f'{n}-{layer}'] for n in sources if f'{n}-{layer}' in wire}
            if inputs:
                out,term = operations.invoke('candidate',decode,inputs,layer)
                restored.update(out)
                failures.update({n:r['reason'] for n,r in term.items() if r['status']=='failed'})
        for n,w in sources.items():
            entry = {'encode':obs[n],'layers':[]}
            status = 'native_encode_failed' if obs[n]['status']=='failed' else 'verified'
            prior = b''
            for k in LAYERS:
                address = f'{n}-{k}'
                if address not in wire:
                    continue
                meta,payload = frame(wire[address],len(w[3])//8,k)
                require(payload.startswith(prior), 'non-nested candidate PBEP layers')
                prior = payload
                assessment = {'wire':meta,'frame':identity(wire[address])}
                if address not in restored:
                    assessment['restore_failed'] = failures[address]
                    status = 'native_restore_failed'
                else:
                    error,q = quality(w[3],restored[address])
                    assessment.update(q,quality_passed=error<=Fraction(meta['bounds'][k-1]))
                    if not assessment['quality_passed'] and status=='verified':
                        status = 'quality_rejected'
                entry['layers'].append(assessment)
            results[n]['routes'][route] = {**entry,'status':status}
    batch = wires[PROGRESSIVE]
    for k in LAYERS:
        legacy_mounts, candidate_mounts = {},{}
        for n,(_,_,old,_,previous) in sources.items():
            name = f'{n}-{k}'
            if name not in batch or name not in restorations[PROGRESSIVE]:
                continue
            if k in previous and batch[name]==previous[k]:
                require(identity(restorations[PROGRESSIVE][name])['sha256']==old['layers'][k-1]['restored_sha256'],
                        'candidate no longer restores an unchanged legacy frame')
                results[n]['compatibility'][str(k)] = 'legacy_v1_frame_and_restore_unchanged'
                continue
            if k in previous:
                candidate_mounts[name] = previous[k]
            legacy_mounts[name] = batch[name]
        if candidate_mounts:
            decoded,ss = operations.invoke('candidate','restore-batch',candidate_mounts,k)
            require(all(r['status']=='restored' and identity(decoded[n])['sha256']==sources[n.split('-')[0]][2]['layers'][k-1]['restored_sha256']
                        for n,r in ss.items()), 'new decoder cannot restore historical v1 frame')
        if legacy_mounts:
            decoded,ss = operations.invoke('legacy','restore-batch',legacy_mounts,k)
            for name,r in ss.items():
                n = name.split('-')[0]
                if legacy_mounts[name][4]==1:
                    require(r['status']=='restored' and decoded[name]==restorations[PROGRESSIVE][name], 'historical decoder cannot restore a version-1 candidate frame')
                    results[n]['compatibility'][str(k)] = 'new_v1_cross_decoded'
                else:
                    require(r['status']=='failed' and r['reason']=='pbepla_rr: unsupported container version', 'v1 decoder accepted candidate v2')
                    results[n]['compatibility'][str(k)] = 'legacy_rejected_v2'
    for n,r in results.items():
        prefix = n+'-'
        r['native_prefix_bytes_equal'] = all(wires[PROGRESSIVE].get(prefix+str(k))==wires[REPLAY].get(prefix+str(k)) for k in LAYERS)
        r['native_restore_bytes_equal'] = all(restorations[PROGRESSIVE].get(prefix+str(k))==restorations[REPLAY].get(prefix+str(k)) for k in LAYERS)
        r['verified'] = all(lane['status']=='verified' for lane in r['routes'].values()) and r['native_prefix_bytes_equal'] and r['native_restore_bytes_equal']
    return list(results.values())


def seal(run,plan):
    body = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_id':plan['plan_id'],'files':{n:ref(local_file(run,n)) for n in PRODUCTS}}
    return {**body,'seal_id':content_id(body)}


def traverse(run,plan,lock,population,entries,items,anchor,temp,reading):
    totals,per_file,seen = Counter(),{},set()
    with (run/'windows.jsonl').open('rb' if reading else 'xb') as ledger, (run/'products.bin').open('rb' if reading else 'xb') as pack:
        printed = None
        for dataset,group in jobs(population,entries,items,anchor,temp):
            if printed is not None and printed!=dataset:
                print('reconciled',printed,per_file[printed]['windows'],flush=True)
            printed = dataset
            old = parse_json(ledger.readline(),'candidate window group') if reading else None
            operations = Operations(run,lock,pack,temp,old['processes'] if reading else None,seen)
            results = assess_group(group,operations)
            row = {'dataset_id':dataset,'first_ordinal':group[0][0],'windows':results,'processes':operations.calls}
            if reading:
                require(canonical_bytes(row)==canonical_bytes(old),'candidate group terminal or metrics did not recompute')
            else:
                _line(ledger,row)
            counts = per_file.setdefault(dataset,Counter())
            counts['native_processes'] += len(operations.calls)
            for r in results:
                counts['windows'] += 1
                counts['verified_windows'] += int(r['verified'])
                counts['baseline_native_failed_windows'] += int(r['baseline_status']=='failed')
                counts['baseline_native_failed_now_verified'] += int(r['baseline_status']=='failed' and r['verified'])
                counts.update('compatibility:'+x for x in r['compatibility'].values())
                counts.update(f'{route}:{value["status"]}' for route,value in r['routes'].items())
        if printed:
            print('reconciled',printed,per_file[printed]['windows'],flush=True)
        if reading:
            require(not ledger.read(1) and not pack.read(1),'unplanned candidate ledger or packed products')
        products_bytes = pack.tell()
    require({ds:x['windows'] for ds,x in per_file.items()}==plan['datasets'], 'candidate corpus not completely accounted')
    for counts in per_file.values():
        totals.update(counts)
    return {'schema':SCHEMA+'-report','plan_id':plan['plan_id'],'run_id':run.name,'totals':totals,'by_file':per_file,
            'products_bytes':products_bytes,'dataset_projection':plan['dataset_projection'],
            'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


def verify(run):
    plan = load_json(local_file(run,'plan.json'))
    require(load_json(local_file(run,'completion.json'))==seal(run,plan),'candidate corpus seal differs')
    anchor,pilot = (checked(plan[k]).parent for k in ('anchor_seal','pilot_seal'))
    regenerated,lock,pop,entries,items = freeze(checked(plan['build']),ROOT/plan['primary_run'],anchor,pilot,plan['dataset_projection'])
    require(regenerated==plan,'candidate plan does not independently refreeze')
    for name,closure in lock['closures'].items():
        for path,asset in closure['files'].items():
            p = verify_asset(run/name/'recovery',{'path':path,'sha256':asset['sha256']})
            require(p.stat().st_size==asset['bytes'],'candidate staged native asset size differs')
    with TemporaryDirectory(prefix='pbepla-corpus-replay-',dir=run.parent) as tmp:
        result = traverse(run,plan,lock,pop,entries,items,anchor,Path(tmp),True)
    require(result==load_json(local_file(run,'report.json')),'candidate corpus totals did not recompute')
    print(dict(result['totals']),flush=True)


def run(args):
    output = args.out.resolve()
    require(output.is_relative_to(ROOT/'results') and not output.exists(),'candidate out must be an unused workspace results path')
    anchor = args.anchor.resolve(strict=True)
    plan,lock,pop,entries,items = freeze(args.build.resolve(strict=True),args.source_run.resolve(strict=True),anchor,
                                         args.pilot.resolve(strict=True),args.dataset)
    require(disk_usage(ROOT).free>(1<<30)+plan['windows']*(6*131072+6*32768), 'candidate corpus worst-case disk budget unavailable')
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(timing_resource.reserve())
                break
            except ContractError as e:
                if not args.wait_resource or str(e)!='measurement resource is already reserved by another TSBench run':
                    raise
                print('waiting for the TSBench measurement reservation',flush=True)
                sleep(20)
        output.mkdir(parents=True)
        for lane,closure in lock['closures'].items():
            (output/lane).mkdir()
            stage_recovery(ROOT,output/lane,closure)
        write_new(output/'plan.json',plan)
        with TemporaryDirectory(prefix='candidate-corpus-',dir=output) as tmp:
            result = traverse(output,plan,lock,pop,entries,items,anchor,Path(tmp),False)
        write_new(output/'report.json',result)
        write_new(output/'completion.json',seal(output,plan))
    print(dict(result['totals']),flush=True)


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action',required=True)
    execute = sub.add_parser('run')
    for n in ('build','source-run','anchor','pilot','out'):
        execute.add_argument('--'+n,type=Path,required=True)
    execute.add_argument('--dataset')
    execute.add_argument('--wait-resource',action='store_true')
    sub.add_parser('verify').add_argument('--run',type=Path,required=True)
    a = p.parse_args()
    try:
        run(a) if a.action=='run' else verify(a.run.resolve(strict=True))
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
