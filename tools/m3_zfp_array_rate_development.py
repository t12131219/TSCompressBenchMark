#!/usr/bin/env python3
"""Execute and audit the frozen ZFP fixed-rate development sweep, never held-out data."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

import m3_corad_sparse_development as prefix
import prepare_m3_zfp_array_rate_development as frozen
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_zfp import ARRAY_LAYOUT, _quality
from tsbench.application.smoke import write_new
from tsbench.assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.recovery import DIRECTORY, stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from tsbench.supervisor.timing_resource import reserve

ROOT, TOOL = frozen.ROOT, frozen.TOOL
SCHEMA = 'bmk.m3-zfp-array-rate-development-run/1'
LIMITS = {'address_space_bytes':128 << 20,'file_bytes':64 << 10,'wall_seconds':15}
STEPS = {'update':('array-update','input',('before','after')),
         'before':('array-reopen','frame',('values',)), 'after':('array-reopen','frame',('values',))}
FLAGS = {'held_out_read':False,'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}


def identity(b):
    return {'bytes':len(b),'sha256':sha256(b).hexdigest()}


def ref(root,p):
    return {'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}


def check(root,row):
    f = verify_asset(root,row)
    require(f.stat().st_size==row['bytes'],'ZFP preserved byte extent changed')
    return f


def configuration(rows,requested,effective):
    require(8<=rows<=ARRAY_LAYOUT['max_rows'] and (requested,effective) in frozen.RATES,'unfrozen ZFP array rate or geometry')
    return {'rows':rows,'requested_rate':requested,'effective_rate':effective,'frame_bytes':((rows+3)//4)*(effective//2)}


def evaluate(config,raw,before,after,baseline,restored):
    n,block_bytes = config['rows'],config['effective_rate']//2
    require(len(raw)==len(baseline)==len(restored)==8*n and len(before)==len(after)==config['frame_bytes'],
            'ZFP output extent differs from shape and rate')
    original = np.frombuffer(raw,dtype='<f8')
    expected = original.copy()
    expected[1] = original[-1]
    expected[3:7] = original[:4]
    unchanged = before[2*block_bytes:]==after[2*block_bytes:] and baseline[64:]==restored[64:]
    initial = _quality(original,np.frombuffer(baseline,dtype='<f8'))
    updated = _quality(expected,np.frombuffer(restored,dtype='<f8'))
    meta = canonical_bytes({'format':'zfp-array-rank1-v1','type':'f64','shape':[n],
                            **{k:config[k] for k in ('requested_rate','effective_rate')}})
    status = ('untouched_block_changed' if not unchanged else 'verified' if initial['accepted'] and updated['accepted']
              else 'quality_rejected')
    return {'status':status,'quality_before':initial,'quality_after':updated,'untouched_native_blocks_match':unchanged,
            'metadata':identity(meta),'published_frame_bytes':len(after),'complete_billed_bytes':len(after)+len(meta),
            'separate_before_diagnostic_bytes':len(before),'logical_bytes':len(raw)}


def execution_for(plan_path,dataset):
    plan = load_json(plan_path)
    require(plan['schema']=='bmk.m3-zfp-array-rate-development/1' and
            plan['plan_id']==content_id({k:v for k,v in plan.items() if k!='plan_id'}) and plan['geometry_policy'] and
            all(plan[k] is v for k,v in FLAGS.items()) and plan['launchers']==launcher_lock() and
            plan['rates']==[{'requested':a,'expected_effective':b} for a,b in frozen.RATES] and
            plan['quality']==ARRAY_LAYOUT['quality'] and plan['recovery_mounts']==['frame'], 'invalid ZFP rate development plan')
    for k in ('base_plan','definition','source_control','header','control','builder'):
        check(ROOT,plan[k])
    origin = load_json(check(ROOT,plan['base_plan']))
    definition = load_json(check(ROOT,plan['definition']))
    entries = _entry_map(ROOT,definition)
    work = {w['dataset_id']:w for w in origin['work_items'] if (w['selection'],w['route'])==(31,'fixed-rate-array')}
    require(set(entries)==set(work)==set(plan['cases']) and len(entries)==23 and dataset in (None,*entries),
            'ZFP development projection outside frozen population')
    for ds,c in plan['cases'].items():
        entry,w = entries[ds],work[ds]
        train,dev,test = entry['partitions']
        require(train['end']==dev['start'] and dev['end']==test['start'] and dev['name']=='development' and
                c['source']==entry['file'] and c['development']==dev and w['work_item_id']==c['work_item_id'],
                'ZFP candidate source or development interval differs')
        kept,short = frozen.project_windows(w['input']['array_contract'],entry['value_count'],entry['rows'],dev['start'],dev['end'])
        require((kept,short)==(c['windows'],c['excluded_short_fragments']),'ZFP candidate development geometry differs')
    files = {k:len(v['windows']) for k,v in plan['cases'].items() if dataset in (None,k)}
    body = {'schema':SCHEMA+'-execution','plan':ref(ROOT,plan_path),'plan_id':plan['plan_id'],'dataset_projection':dataset,
            'files':files,'limits':LIMITS,'runner':ref(ROOT,Path(__file__).resolve()),
            'prefix_reader':ref(ROOT,Path(prefix.__file__).resolve()),**FLAGS}
    return {**body,'execution_id':content_id(body)},plan,entries


def windows(plan,entries,files,scratch):
    for ds in files:
        with TemporaryDirectory(prefix='zfp-prefix-',dir=scratch) as d:
            data = prefix.train_dev_matrix(ROOT,entries[ds],Path(d))
        for i,(c,a,b) in enumerate(plan['cases'][ds]['windows']):
            raw = data[a:b,c].tobytes()
            values = np.frombuffer(raw,dtype='<f8')
            require(np.all(np.isfinite(values)) and (entries[ds]['parser']['missing']!='retain_source_minus_9999' or
                    not np.any(values==-9999)), 'ZFP candidate window leaves the frozen finite domain')
            yield {'dataset_id':ds,'window':i,'column':c,'rows':[a,b],'source':identity(raw)},raw


def invoke(run, runtime, step, work, logs, config, input_file):
    op,mount,outputs = STEPS[step]
    result,proc = invoke_isolated_tool(run/DIRECTORY,runtime,TOOL,LIMITS,work,logs,step,{mount:input_file},
        [op,str(config['rows']),f'/inputs/{mount}',str(config['requested_rate'])],lambda:False,observe=True)
    require(proc['status']!='sandbox_failed','ZFP development Bubblewrap setup failed; see preserved stderr')
    record = {k:proc[k] for k in ('status','reason','returncode','pid','session_id')}
    if proc['pid'] is not None:
        record['input_mounts'] = proc['input_mounts']
    record['logs'] = {ext:ref(run,local_file(logs,step+'.'+ext)) for ext in ('stdout','stderr')}
    if proc['status']!='completed' or proc['returncode']!=0:
        return {},record
    require(result.is_dir() and {f.name for f in result.iterdir()}==set(outputs),'ZFP candidate output closure differs')
    return {name:local_file(result,name).read_bytes() for name in outputs},record


def produce(run, runtime, case, config, raw, i, scratch):
    path = run/'products'/str(i); path.mkdir(parents=True)
    raw_path = scratch/'input'; raw_path.write_bytes(raw)
    processes,products = {},{}
    for step,stem in (('update',None),('before','before'),('after','after')):
        work = scratch/step; work.mkdir()
        output, processes[step] = invoke(run,runtime,step,work,path,config,raw_path if stem is None else path/stem)
        if not output:
            break
        for tag,value in output.items():
            name = tag if stem is None else 'restored-'+stem
            f = path/name; f.write_bytes(value); products[name] = ref(run,f)
    return {'case':case,'config':config,'processes':processes,'products':products}


def decide(run, row, case, config, raw, i, sessions):
    require(row['case']==case and row['config']==config,'ZFP trial differs from frozen window and rate')
    commands,products = row['processes'],row['products']
    folder = f'products/{i}'
    sequence = [step for step in STEPS if step in commands]
    require(sequence and sequence==list(STEPS)[:len(sequence)] and len(sequence)==len(commands),'unexpected ZFP candidate command prefix')
    used = set(); failed = None
    for step in sequence:
        c = commands[step]
        op,mount,outputs = STEPS[step]
        require(failed is None,'ZFP launched a process after failure')
        expected_product = ('restored-'+step,) if mount=='frame' else outputs
        if c['pid'] is not None:
            wanted = {k:products[step][k] for k in ('bytes','sha256')} if mount=='frame' else identity(raw)
            require(c['pid']>0 and c['session_id'] and c['session_id'] not in sessions and c['input_mounts']=={mount:wanted},
                    'ZFP development process reuse or changed input mounts')
            sessions.add(c['session_id'])
        logs = {}
        for ext in ('stdout','stderr'):
            log = c['logs'][ext]
            require(log['path']==f'{folder}/{step}.{ext}','ZFP log escaped trial namespace')
            logs[ext] = check(run,log)
        if c['status']=='completed' and c['returncode']==0:
            require(c['pid'] is not None and logs['stderr'].stat().st_size==0 and load_json(logs['stdout'])==config,
                    f'ZFP {op} did not report the expected effective rate or geometry')
            used.update(expected_product)
        else:
            failed = step
    require(set(products)==used,'ZFP trial product population differs')
    buf = {}
    for name,p in products.items():
        require(p['path']==f'{folder}/{name}','ZFP product escaped trial namespace')
        buf[name] = check(run,p).read_bytes()
    require({p.name for p in (run/folder).iterdir()}==set(products)|{f'{s}.{e}' for s in commands for e in ('stdout','stderr')},
            'ZFP trial directory contains unbound products or logs')
    if failed:
        return {'status':'native_failed','failed_step':failed,'logical_bytes':len(raw),'complete_billed_bytes':None}
    require(sequence==list(STEPS),'ZFP candidate trial is missing a required native operation')
    return evaluate(config,raw,buf['before'],buf['after'],buf['restored-before'],buf['restored-after'])


def selected_rate(files, totals, *, projected):
    if projected:
        return None
    n = sum(files.values())
    eligible = [a for a,_ in frozen.RATES if totals[str(a)]['verified']==n]
    return min(eligible,key=lambda a:(totals[str(a)]['complete_billed_bytes'],a)) if eligible else None


def reconcile(run, execution, plan, entries, *, record):
    totals = {str(a):Counter() for a,_ in frozen.RATES}
    by_file = {ds:{str(a):Counter() for a,_ in frozen.RATES} for ds in execution['files']}
    sessions = set(); count = 0
    with (run/'trials.jsonl').open('xb' if record else 'rb') as stream, TemporaryDirectory(prefix='zfp-development-') as tmp:
        for case,raw in windows(plan,entries,execution['files'],Path(tmp)):
            for requested,effective in frozen.RATES:
                cfg = configuration(case['rows'][1]-case['rows'][0],requested,effective)
                if record:
                    with TemporaryDirectory(prefix='trial-',dir=tmp) as scratch:
                        row = produce(run,plan['runtime'],case,cfg,raw,count,Path(scratch))
                else:
                    row = parse_json(stream.readline(),'ZFP development trial')
                decision = decide(run,row,case,cfg,raw,count,sessions)
                if record:
                    stream.write(canonical_bytes({**row,'decision':decision})+b'\n')
                else:
                    require(row['decision']==decision,'ZFP development decision did not recompute')
                row_count = {'trials':1,decision['status']:1,'logical_bytes':len(raw),
                             'complete_billed_bytes':decision['complete_billed_bytes'] or 0}
                totals[str(requested)].update(row_count)
                by_file[case['dataset_id']][str(requested)].update(row_count)
                count += 1
        if record:
            stream.flush(); os.fsync(stream.fileno())
        else:
            require(not stream.read(1),'extra trials after the frozen ZFP population')
    require(count==sum(execution['files'].values())*len(frozen.RATES) and
            {p.name for p in (run/'products').iterdir()}=={str(i) for i in range(count)},'ZFP development trial population differs')
    return {'schema':SCHEMA+'-report','execution_id':execution['execution_id'],'trial_count':count,'native_sessions':len(sessions),
            'selected_requested_rate_on_full_development':selected_rate(execution['files'],totals,projected=execution['dataset_projection'] is not None),
            'by_file':by_file,'totals':totals,**FLAGS}


def seal(run):
    body = {'schema':SCHEMA+'-seal','files':{k:ref(run,local_file(run,k)) for k in ('execution.json','trials.jsonl','report.json')}}
    return {**body,'seal_id':content_id(body)}


def execute(plan_path, run, dataset):
    require(run.is_relative_to(ROOT/'results') and not run.exists(),'ZFP candidate requires new project-local run directory')
    with reserve():
        execution,plan,entries = execution_for(plan_path,dataset)
        stat = os.statvfs(ROOT/'results')
        count = sum(execution['files'].values())
        values = sum(b-a for k in execution['files'] for _,a,b in plan['cases'][k]['windows'])
        require(stat.f_bavail*stat.f_frsize > (1<<30)+values*16*len(frozen.RATES)*2+count*(256<<10) and
                stat.f_favail > 1000+count*len(frozen.RATES)*12,'insufficient workspace space or inodes for retained ZFP development trials')
        run.mkdir(parents=True); (run/'products').mkdir()
        stage_recovery(ROOT,run,plan['runtime'])
        write_new(run/'execution.json',execution)
        result = reconcile(run,execution,plan,entries,record=True)
        write_new(run/'report.json',result)
        write_new(run/'completion.json',seal(run))
    return result


def verify(run):
    require(seal(run)==load_json(local_file(run,'completion.json')),'ZFP development run seal differs')
    e = load_json(local_file(run,'execution.json'))
    current,plan,entries = execution_for(check(ROOT,e['plan']),e['dataset_projection'])
    require(current==e,'ZFP development execution binding changed')
    for name,info in plan['runtime']['files'].items():
        check(run/DIRECTORY,{'path':name,**{k:info[k] for k in ('bytes','sha256')}})
    result = reconcile(run,e,plan,entries,record=False)
    require(result==load_json(local_file(run,'report.json')),'ZFP development report did not recompute')
    return result


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command',required=True)
    start = sub.add_parser('execute'); check_cmd = sub.add_parser('verify')
    for action in (start,check_cmd):
        action.add_argument('--run',type=Path,required=True)
    start.add_argument('--plan',type=Path,required=True)
    start.add_argument('--dataset')
    args = p.parse_args()
    try:
        result = (execute(args.plan.resolve(strict=True),args.run.resolve(),args.dataset) if args.command=='execute'
                  else verify(args.run.resolve(strict=True)))
        print(result['trial_count'],result['totals'],result['selected_requested_rate_on_full_development'])
    except (OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')
