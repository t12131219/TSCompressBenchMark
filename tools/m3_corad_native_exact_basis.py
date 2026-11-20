#!/usr/bin/env python3
"""Run the C11 exact-basis candidate on frozen development inputs only."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from time import sleep

import m3_corad_exact_basis_development as oracle
import m3_corad_sparse_development as base
from build_m3_corad_exact_basis import SCHEMA as BUILD
from tsbench.application.smoke import _line, write_new
from tsbench.assets import ContractError, content_id, load_json, local_file, parse_json, require
from tsbench.recovery import stage_recovery
from tsbench.supervisor.timing_resource import reserve

ROOT = base.ROOT
SCHEMA = 'bmk.corad-native-exact-basis-development/1'
FLAGS = {'held_out_run':False,'budget_selected':False,'qualification_granted':False,
         'timing_admitted':False,'stage_accepted':False}


def plan_for(development, build_file, dataset):
    plan = load_json(local_file(development,'plan.json'))
    completion = local_file(development,'completion.json')
    require(plan['dataset_projection'] is None and base.seal(development,plan)==load_json(completion),
            'CORAD native exact basis requires an intact full development run')
    lock = load_json(build_file)
    require(lock['schema']==BUILD and lock['build_id']==content_id({k:v for k,v in lock.items() if k!='build_id'}) and
            lock['source_development']==base.ref(ROOT,completion) and lock['base_build']==plan['build'] and
            lock['base_guard']==plan['source_guard'] and lock['launchers']==base.launcher_lock(),
            'CORAD native candidate closure differs')
    origin = load_json(base.check(ROOT,plan['build']))
    require(lock['restore']==origin['restore'],'CORAD must use the unchanged native decoder')
    spec = load_json(base.check(ROOT,lock['candidate']))
    require(spec['contract']['development_only'] and spec['contract']['width']==spec['contract']['nonzero']==4,
            'CORAD candidate is not the budget-4 development method')
    totals = load_json(local_file(development,'report.json'))
    files = {k:v['4']['frames'] for k,v in totals['stratified'].items() if dataset in (None,k)}
    require(bool(files) and set(files)<=plan['files'].keys() and not totals['held_out_run'],'invalid CORAD development projection')
    body = {'schema':SCHEMA+'-plan','development':base.ref(ROOT,completion),'build':base.ref(ROOT,build_file),
            'dataset_projection':dataset,'files':files,'nonzero':4,
            'sources':[base.ref(ROOT,Path(p).resolve()) for p in (__file__,oracle.__file__,base.__file__)],**FLAGS}
    return {**body,'plan_id':content_id(body)},lock,plan


def source_trials(development, origin, plan, scratch):
    seen = Counter()
    with local_file(development,'trials.jsonl').open('rb') as source:
        recorded = (r for line in source for r in [parse_json(line)]
                    if r['key']['nonzero']==4 and r['key']['dataset_id'] in plan['files'])
        expected = ((k,raw,gates) for k,raw,gates in base.jobs(base.check(ROOT,origin['source_guard']).parent,
                    base.check(ROOT,origin['build']),plan['dataset_projection'],scratch) if k['nonzero']==4)
        for old,(key,raw,gates) in zip(recorded,expected,strict=True):
            require(old['key']==key and old['status']=='native_restored','candidate source trial changed')
            seen[key['dataset_id']] += 1
            result = oracle.evaluate(base.check(ROOT,old['frame']).read_bytes(),raw,key['columns'],gates,old['restore'])
            yield old,key,raw,gates,result
    require(dict(seen)==plan['files'],'candidate development frame population differs')


def produce(run, lock, key, raw, mask, i, scratch):
    native = {}
    logs = run/'steps'/str(i); logs.mkdir(parents=True)
    values = scratch/'development.bin'; values.write_bytes(raw)
    rows = str(key['development_rows'][1]-key['development_rows'][0]); cols = str(len(key['columns']))
    encoded,_ = base._native(run/'encoder',{'decoder':lock['encode']},scratch,logs,'encode',
        {'model':base.check(ROOT,key['model']),'development':values},
        ['encode','/inputs/model','/inputs/development',rows,cols,str(mask)],'frame',native)
    row = {'key':key,'mask':mask,'processes':native}
    def bind_logs(name):
        for ext in ('stdout','stderr'):
            native[name][f'log_{ext}'] = base.ref(ROOT,local_file(logs,name+'.'+ext))
    bind_logs('encode')
    if encoded is None:
        return {**row,'status':'native_encode_failed'}
    saved = run/'frames'/f'{i}.crd1'; saved.write_bytes(encoded)
    restored,_ = base._native(run/'decoder',{'decoder':lock['restore']},scratch,logs,'restore',{'frame':saved},
                             ['decode','/inputs/frame',rows,cols],'values',native)
    bind_logs('restore')
    row['frame'] = base.ref(ROOT,saved)
    if restored is None:
        return {**row,'status':'native_restore_failed'}
    return {**row,'restore':base._identity(restored),'status':'native_restored'}


def decide(run, i, observed, old, key, raw, gates, mask, oracle_result, seen):
    require(observed['key']==key and observed['mask']==mask,'CORAD candidate executed different key or mask')
    has_frame, has_restore = 'frame' in observed, 'restore' in observed
    wire = b''
    path = run/'frames'/f'{i}.crd1'
    if has_frame:
        require(base.check(ROOT,observed['frame'])==path,'foreign candidate CRD1 output')
        wire = path.read_bytes()
    else:
        require(not path.exists() and not has_restore,'failed encoder has a product')
    mounts = {'encode':{'model':{k:key['model'][k] for k in ('bytes','sha256')},'development':base._identity(raw)}}
    if has_frame:
        mounts['restore'] = {'frame':base._identity(wire)}
    require(set(observed['processes'])==set(mounts),'wrong native candidate process population')
    for name, proc in observed['processes'].items():
        require(proc['operation']==name,'wrong native candidate operation')
        if proc['pid'] is not None:
            require(proc['session_id'] and proc['session_id'] not in seen and proc['input_mounts']==mounts[name],
                    'native candidate sandbox reused or mounted foreign input')
            seen.add(proc['session_id'])
        success = has_frame if name=='encode' else has_restore
        logs = run/'steps'/str(i)
        require({f'log_{ext}':base.ref(ROOT,local_file(logs,name+'.'+ext)) for ext in ('stdout','stderr')}==
                {k:proc[k] for k in ('log_stdout','log_stderr')},'native candidate logs changed')
        if 'native' in proc:
            n = proc['native']
            require(proc['pid'] is not None and proc['status']=='completed' and proc['returncode']==0 and
                    n==load_json(local_file(logs,name+'.stdout')) and proc['log_stderr']['bytes']==0 and
                    n['rows']==key['development_rows'][1]-key['development_rows'][0] and n['columns']==len(key['columns']) and
                    (n['native_status']==0) is success and n['output_bytes']==((len(wire) if name=='encode' else len(raw)) if success else 0),
                    'candidate native transcript differs')
        else:
            require(not success and (proc['status']!='completed' or proc['returncode']!=0), 'missing native candidate transcript')
    status = 'native_restored' if has_restore else ('native_restore_failed' if has_frame else 'native_encode_failed')
    require(observed['status']==status,'wrong candidate native outcome')
    matches = base._identity(wire)==oracle_result['candidate_frame'] if has_frame else None
    result = {'terminal':status,'frame_matches_reference':matches,'bytes':len(wire),
              'base_terminal':old['decision']['terminal'],'base_bytes':old['frame']['bytes']}
    if not has_restore:
        return result
    if not matches:
        return {**result,'terminal':'candidate_frame_differs'}
    restored,meta,_ = oracle.interpret(wire,max_values=131072)
    require(base._identity(restored)==observed['restore'],'unchanged native decoder and independent reader differ')
    quality,ok = base.judge_quality(raw,restored,key['columns'],gates)
    charges = {k:meta[k] for k in base.COST}
    require(ok==oracle_result['verified'] and quality==oracle_result['quality'] and oracle_result['candidate_accounting']==charges and
            sum(charges.values())==len(wire),'candidate quality or accounting differs from reference interpretation')
    return {**result,'terminal':'verified' if ok else 'quality_rejected','quality':quality,'accounting':charges,
            'zero_gate_values':oracle_result['zero_gate_values'],'zero_gate_different_bits':oracle_result['zero_gate_different_bits']}


def audit(run, plan, lock, origin, development, *, execute):
    seen = set(); totals = Counter(); per_file = {k:Counter() for k in plan['files']}
    with (run/'trials.jsonl').open('xb' if execute else 'rb') as stream, TemporaryDirectory(prefix='corad-c11-development-') as tmp:
        for i,(old,key,raw,gates,expected) in enumerate(source_trials(development,origin,plan,Path(tmp))):
            mask = sum(1 << j for j,g in enumerate(gates) if oracle.zero_gate(g))
            if execute:
                with TemporaryDirectory(prefix='trial-',dir=tmp) as temp:
                    row = produce(run,lock,key,raw,mask,i,Path(temp))
            else:
                row = parse_json(stream.readline(),'CORAD candidate trial')
            d = decide(run,i,row,old,key,raw,gates,mask,expected,seen)
            if execute:
                _line(stream,{**row,'decision':d})
            else:
                require(d==row['decision'],'CORAD candidate decision did not recompute')
            per_file[key['dataset_id']].update({'frames':1,'logical_bytes':len(raw),'base_bytes':d['base_bytes'],
                'candidate_bytes':d['bytes'],f"{d['base_terminal']}_to_{d['terminal']}":1})
        if not execute:
            require(not stream.read(1),'extra CORAD native candidate trials')
    for ds, values in per_file.items():
        require(values['frames']==plan['files'][ds],'CORAD candidate summary denominator changed')
        totals.update(values)
    return {'schema':SCHEMA+'-report','plan_id':plan['plan_id'],'stratified':per_file,'totals':totals,
            'native_processes':len(seen),**FLAGS}


def seal(run, plan):
    body = {'schema':SCHEMA+'-seal','plan_id':plan['plan_id'],
            'files':{n:base.ref(ROOT,local_file(run,n)) for n in ('plan.json','trials.jsonl','report.json')}}
    return {**body,'seal_id':content_id(body)}


def execute(run, development, build_file, dataset, wait):
    require(run.is_relative_to(ROOT/'results'),'CORAD native candidate output outside workspace results')
    plan,lock,origin = plan_for(development,build_file,dataset)
    while True:
        try:
            with reserve():
                run.mkdir(parents=True,exist_ok=False)
                for lane,key in (('encoder','encode'),('decoder','restore')):
                    path = run/lane; path.mkdir(); stage_recovery(ROOT,path,lock[key])
                (run/'frames').mkdir()
                write_new(run/'plan.json',plan)
                report = audit(run,plan,lock,origin,development,execute=True)
                write_new(run/'report.json',report)
                write_new(run/'completion.json',seal(run,plan))
            return report
        except ContractError as exc:
            if not wait or str(exc)!='measurement resource is already reserved by another TSBench run':
                raise
            print('waiting for the TSBench measurement reservation',flush=True)
            sleep(30)


def verify(run):
    plan = load_json(local_file(run,'plan.json'))
    require(seal(run,plan)==load_json(local_file(run,'completion.json')),'CORAD native candidate seal differs')
    dev = base.check(ROOT,plan['development']).parent
    regen,lock,origin = plan_for(dev,base.check(ROOT,plan['build']),plan['dataset_projection'])
    require(regen==plan,'CORAD native candidate plan changed')
    for lane,key in (('encoder','encode'),('decoder','restore')):
        for path,f in lock[key]['files'].items():
            base.check(run/lane/'recovery',{'path':path,'bytes':f['bytes'],'sha256':f['sha256']})
    report = audit(run,plan,lock,origin,dev,execute=False)
    require(report==load_json(local_file(run,'report.json')),'CORAD native candidate report differs')
    return report


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='op',required=True)
    start = sub.add_parser('execute')
    for name in ('run','development','build'):
        start.add_argument('--'+name,type=Path,required=True)
    start.add_argument('--dataset')
    start.add_argument('--wait-resource',action='store_true')
    sub.add_parser('verify').add_argument('--run',type=Path,required=True)
    a = p.parse_args()
    try:
        if a.op=='execute':
            r = execute(a.run.resolve(),a.development.resolve(strict=True),a.build.resolve(strict=True),a.dataset,a.wait_resource)
        else:
            r = verify(a.run.resolve(strict=True))
        print(r['totals'],flush=True)
    except (OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
