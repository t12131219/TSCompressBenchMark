#!/usr/bin/env python3
"""Compare predeclared native CORAD OMP budgets using only training/development."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from contextlib import ExitStack
from hashlib import sha256
from itertools import groupby, islice
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import sleep

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.corad_corpus_execution import TOOL, _identity, _native, judge_quality
from tsbench.application.m3_corad_guard_corpus import COST, TRAINERS, _elf, _seal, check, ref
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.smoke import _line, write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.corpus_ingress import MAX_LINE_BYTES, _identity as canonical_identity, read_batches
from tsbench.planner.corad_corpus import calibrate_quality
from tsbench.qualification.corad_wire import HEADER, interpret
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import launcher_lock

SCHEMA = 'bmk.corad-native-sparse-development/1'
BUDGETS = (2, 3, 4)
CONTROL = 'plugins/codecs/corad-frozen/corpus_control.c'


def build(guard_run, output):
    plan = load_json(local_file(guard_run,'plan.json'))
    require(load_json(local_file(guard_run,'completion.json'))==_seal(guard_run,plan),'invalid CORAD guard source seal')
    c = plan['closures']['candidate']
    library = _elf(c['files']['lib/libcorad_c.so'])
    program = _elf(c['files'][c['tools'][TOOL]])
    require(output.is_relative_to(ROOT/'build'),'CORAD development build escaped workspace')
    output.mkdir(parents=True)
    source = local_file(ROOT,CONTROL)
    text = source.read_text()
    for a,b in (('FRAME_CAP (256u * 1024u)','FRAME_CAP (512u * 1024u)'),
                ('uint32_t rows, uint32_t cols) {\n    uint8_t model_blob','uint32_t rows, uint32_t cols, uint16_t budget) {\n    uint8_t model_blob'),
                ('corad_model_config(model, rows, 2, 0.9','corad_model_config(model, rows, budget, 0.9'),
                ('argc == 6 && !strcmp(argv[1], "encode")','argc == 7 && !strcmp(argv[1], "encode")'),
                ('MAX_TEST_ROWS), dimension(argv[5], 2, MAX_COLUMNS));','MAX_TEST_ROWS), dimension(argv[5], 2, MAX_COLUMNS), dimension(argv[6], 2, 4));')):
        require(text.count(a)==1,'checked corpus controller does not support derived budget tool')
        text = text.replace(a,b)
    require(digest(source)==plan['code'][CONTROL], 'frozen CORAD corpus control changed')
    derived = output/'corad_sparse.c'
    derived.write_text(text)
    obj = output/'corad_sparse'
    checked_build = load_json(check(ROOT,plan['build_lock']))
    old_base = verify_asset(ROOT,checked_build['base_dependency'])
    lib = check(ROOT,{'bytes':c['files']['lib/libcorad_c.so']['bytes'],**library})
    header = local_file(old_base.parent,'source/corad-native/include/corad.h')
    subprocess.run(['/usr/bin/cc','-std=c11','-O2','-fno-fast-math','-ffp-contract=off','-Wall','-Wextra','-Werror',
                    '-I',str(header.parent),str(derived),str(lib),'-Wl,-rpath,$ORIGIN','-o',str(obj)],check=True)
    dec = plan['closures']['original']
    require(program['sha256']==dec['files'][dec['tools'][TOOL]]['sha256'], 'original restore control differs from candidate baseline')
    encode = plan_recovery(ROOT,{},(),tools={TOOL:{k:v for k,v in ref(ROOT,obj).items() if k!='bytes'}},libraries=[library])
    body = {'schema':SCHEMA+'-build','candidate_guard':ref(ROOT,guard_run/'completion.json'),'budgets':list(BUDGETS),
            'derived':ref(ROOT,derived),'control_source':ref(ROOT,source),'header':ref(ROOT,header),
            'encode':encode,'restore':dec,'launchers':launcher_lock()}
    write_new(output/'build-lock.json',{**body,'build_id':content_id(body)})


def train_dev_matrix(root, entry, scratch):
    """Project the still-frozen physical prefix; only parse train/development rows."""
    train,dev,test = entry['partitions']
    require([p['name'] for p in (train,dev,test)]==['train','development','test'] and
            train['start']==0 and train['end']==dev['start'] and dev['end']==test['start'],
            'CORAD development partition crosses the held-out boundary')
    original = local_file(root,entry['file']['path'])
    require(original.stat().st_size==entry['file']['bytes'],'CORAD development raw object differs')
    prefix = scratch/'prefix.csv'
    h = sha256()
    with original.open('rb') as f,prefix.open('xb') as out:
        for line in islice(iter(lambda:f.readline(MAX_LINE_BYTES+1),b''),dev['end']+1):
            require(0<len(line)<=MAX_LINE_BYTES,'invalid CORAD physical prefix line')
            h.update(line)
            out.write(line)
    source = {**entry,'file':{'bytes':prefix.stat().st_size,'sha256':h.hexdigest(),'path':'prefix.csv'},'rows':dev['end']}
    fingerprints = [(sha256(),sha256()) for _ in (train,dev)]
    width = entry['value_count']
    data = np.empty((dev['end'],width),dtype='<f8')
    for batch in read_batches(scratch,source):
        end = batch.start+batch.rows
        data[batch.start:end] = np.frombuffer(batch.values,dtype='<f8').reshape(batch.rows,width)
        for p,(a,v) in zip((train,dev),fingerprints,strict=True):
            lo,hi = max(p['start']-batch.start,0),min(p['end'],end)-batch.start
            if lo<hi:
                a.update(batch.axis[lo*8:hi*8]); v.update(batch.values[lo*width*8:hi*width*8])
    require(all(canonical_identity(entry,p['end']-p['start'],a,v)==p['canonical']
                for p,(a,v) in zip((train,dev),fingerprints,strict=True)), 'canonical train/development identity differs')
    return data


def binding(guard_run,lock_file,dataset):
    src = load_json(local_file(guard_run,'plan.json'))
    require(load_json(local_file(guard_run,'completion.json'))==_seal(guard_run,src) and src['dataset_projection'] is None,
            'development requires full frozen CORAD model custody')
    lock = load_json(lock_file)
    require(lock['build_id']==content_id({k:v for k,v in lock.items() if k!='build_id'}) and
            lock['candidate_guard']==ref(ROOT,guard_run/'completion.json') and lock['budgets']==list(BUDGETS) and
            lock['launchers']==launcher_lock(),'CORAD development executable or policy changed')
    main = load_json(check(ROOT,src['source_plan']))
    entries = _entry_map(ROOT,load_json(check(ROOT,main['definition']['plan'])))
    from tsbench.application.m3_corad import FOLDER
    source_run = ROOT/src['source_run']/FOLDER
    for case in src['cases']:
        ds = case['dataset_id']
        if dataset is not None and ds!=dataset:
            continue
        # Deliberately project only train/model metadata into the development plan.
        grouped = []
        entry = entries[ds]
        for m in case['members']:
            b = m['binding']
            cols = [entry['columns'].index(n)-1 for n in b['ordered_columns']]
            require(min(cols)>=0 and cols==list(range(min(cols),max(cols)+1)),'unplanned development column group')
            grouped.append({'columns':cols,'column_names':b['ordered_columns'],'id':b['input_binding_id'],
                            'train':b['train'],'gates':b['train_only_quality_bounds'],
                            'models':{p:ref(ROOT,check(source_run,m['producers'][p]['model'])) for p in TRAINERS}})
        yield entry,grouped,lock


def jobs(guard_run,lock_file,dataset,work):
    for entry,groups,_ in binding(guard_run,lock_file,dataset):
        ds = entry['id']
        with TemporaryDirectory(prefix='train-development-',dir=work) as temp:
            data = train_dev_matrix(ROOT,entry,Path(temp))
            dev = entry['partitions'][1]
            for b in groups:
                a,z = b['train']['absolute_rows']
                columns = b['columns']
                train = data[a:z,columns].T.tobytes()
                require(_identity(train)==b['train']['values'] and b['gates']==calibrate_quality(train,count=z-a,width=len(columns)),
                        'development changed the trained model source or the original gates')
                eligible = np.ones(dev['end']-dev['start'],dtype=bool)
                if entry['parser']['missing']=='retain_source_minus_9999':
                    eligible &= ~np.any(data[dev['start']:dev['end'],columns]==-9999,axis=1)
                for include,frames in groupby(enumerate(eligible,dev['start']),key=lambda r:r[1]):
                    indices = [i for i,_ in frames]
                    if not include:
                        continue
                    for lo in range(indices[0],indices[-1]+1,4096):
                        hi = min(lo+4096,indices[-1]+1)
                        raw = data[lo:hi,columns].T.tobytes()
                        for producer,model in b['models'].items():
                            key = {'dataset_id':ds,'input_binding_id':b['id'],'producer':producer,'development_rows':[lo,hi],
                                   'development_input':_identity(raw),'model':model,'columns':b['column_names']}
                            for nz in BUDGETS:
                                yield {**key,'nonzero':nz},raw,b['gates']


def plan_for(guard,build_file,dataset):
    frozen = list(binding(guard,build_file,dataset))
    require(len(frozen)==(1 if dataset else 13),'unknown or incomplete CORAD development dataset scope')
    _,_,lock = frozen[0]
    plan = {'schema':SCHEMA+'-plan','source_guard':ref(ROOT,guard/'completion.json'),'build':ref(ROOT,build_file),
            'launchers':launcher_lock(),'dataset_projection':dataset,'budgets':list(BUDGETS),
            'files':{e['id']:{'development':e['partitions'][1],'cohorts':len(groups)} for e,groups,_ in frozen},
            'threshold':0.9,'candidate_selection':'on full development only; require no false terminals, then minimize full CRD1 bytes; fixed tie to lower nonzero',
            'excludes':'no test rows mounted or read into optimization; no model fitting or change of gates',
            'code':digest(Path(__file__))}
    return {**plan,'plan_id':content_id(plan)},lock


def seal(run,plan):
    base = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_id':plan['plan_id'],
            'files':{n:ref(ROOT,local_file(run,n)) for n in ('plan.json','trials.jsonl','report.json')}}
    return {**base,'seal_id':content_id(base)}


def produce(run,lock,key,raw,index,temp):
    logs = run/'steps'/str(index); logs.mkdir(parents=True)
    native = {}
    a,b = key['development_rows']; rows = str(b-a); cols = str(len(key['columns']))
    model = check(ROOT,key['model'])
    p = temp/'development.bin'; p.write_bytes(raw)
    frame_bytes,_ = _native(run/'encoder',{'decoder':lock['encode']},temp,logs,'encode',{'model':model,'development':p},
                            ['encode','/inputs/model','/inputs/development',rows,cols,str(key['nonzero'])],'frame',native)
    if frame_bytes is None:
        return {'key':key,'status':'native_encode_failed','processes':native}
    dest = run/'frames'/f'{index}.crd1'
    dest.write_bytes(frame_bytes)
    restored,_ = _native(run/'decoder',{'decoder':lock['restore']},temp,logs,'restore',{'frame':dest},
                         ['decode','/inputs/frame',rows,cols],'values',native)
    result = {'key':key,'processes':native,'frame':ref(ROOT,dest)}
    if restored is None:
        return {**result,'status':'native_restore_failed'}
    return {**result,'restore':_identity(restored),'status':'native_restored'}


def explain(run,key,row,raw,gates,index,seen):
    require(key==row['key'],'CORAD development observation different from frozen order')
    states = row['processes']
    require(set(states)==({'encode','restore'} if 'frame' in row else {'encode'}),'CORAD development process population differs')
    file = run/'frames'/f'{index}.crd1'
    if 'frame' in row:
        require(check(ROOT,row['frame'])==file,'foreign candidate development frame')
        wire = file.read_bytes()
    else:
        require(not file.exists(),'failed development unexpectedly retained output')
        wire = b''
    for name,proc in states.items():
        wanted = {'model':{k:key['model'][k] for k in ('bytes','sha256')},'development':_identity(raw)} if name=='encode' else {'frame':_identity(wire)}
        require(proc['operation']==name,'wrong native development phase')
        if proc['pid'] is not None:
            require(proc['session_id'] and proc['session_id'] not in seen and proc['input_mounts']==wanted,
                    'CORAD development sandbox reused or mounted an unplanned file')
            seen.add(proc['session_id'])
        if 'native' in proc:
            n = proc['native']
            require(n==load_json(local_file(run/'steps'/str(index),name+'.stdout')) and
                    not local_file(run/'steps'/str(index),name+'.stderr').stat().st_size and
                    n['rows']==key['development_rows'][1]-key['development_rows'][0] and n['columns']==len(key['columns']),
                    'CORAD development native transcript differs')
            success = bool(wire) if name=='encode' else 'restore' in row
            require((n['native_status']==0) is success and n['output_bytes']==((len(wire) if name=='encode' else len(raw)) if success else 0),
                    'CORAD development native status or byte count differs')
        else:
            require(proc['status']!='completed' and not ('frame' in row if name=='encode' else 'restore' in row),
                    'CORAD missing native transcript unexpectedly succeeded')
    if row['status']!='native_restored':
        require('restore' not in row and row['status']==('native_restore_failed' if wire else 'native_encode_failed'),
                'CORAD development native failure changed')
        return {'terminal':row['status'],'bytes':len(wire)}
    restored,meta,embedded = interpret(wire,max_values=131072)
    actual = HEADER.unpack_from(wire)
    model = check(ROOT,key['model']).read_bytes()
    require(actual[2:5]==HEADER.unpack_from(model)[2:5] and embedded==model[HEADER.size:] and
            actual[5]==key['nonzero'] and actual[6]==0.9 and _identity(restored)==row['restore'],
            'CORAD development changed model, budget, threshold or recovery')
    charges = {k:meta[k] for k in COST}
    require(sum(charges.values())==len(wire),'CORAD development full-byte accounting differs')
    quality,ok = judge_quality(raw,restored,key['columns'],gates)
    return {'terminal':'verified' if ok else 'quality_rejected','bytes':len(wire),'accounting':charges,'quality':quality}


def audit(run,plan,lock,guard,build_file,append):
    per_file = defaultdict(lambda:defaultdict(Counter)); seen = set(); count = 0
    with (run/'trials.jsonl').open('xb' if append else 'rb') as stream, TemporaryDirectory(prefix='development-audit-',dir=run.parent) as scratch:
        top = Path(scratch)
        last = None
        for i,(key,raw,gates) in enumerate(jobs(guard,build_file,plan['dataset_projection'],top)):
            ds = key['dataset_id']
            if last is not None and ds!=last:
                print('accounted development:',last,flush=True)
            last = ds
            if append:
                with TemporaryDirectory(prefix='corad-dev-trial-',dir=top) as tmp:
                    row = produce(run,lock,key,raw,i,Path(tmp))
                decision = explain(run,key,row,raw,gates,i,seen)
                _line(stream,{**row,'decision':decision})
            else:
                row = parse_json(stream.readline(),'CORAD development evidence')
                decision = explain(run,key,row,raw,gates,i,seen)
                require(row['decision']==decision,'CORAD development independent quality did not recompute')
            count += 1
            acc = per_file[ds][str(key['nonzero'])]
            acc['frames'] += 1
            acc['logical_bytes'] += len(raw)
            acc['billed_bytes'] += decision['bytes']
            acc[decision['terminal']] += 1
        if not append:
            require(not stream.read(1),'extra CORAD development trials after frozen extent')
    require(set(per_file)==set(plan['files']) and count>0,'incomplete CORAD development coverage')
    totals = {str(n):sum((v[str(n)] for v in per_file.values()),Counter()) for n in BUDGETS}
    require(len({v['frames'] for v in totals.values()})==1,'unmatched development trial denominators')
    eligible = [n for n in BUDGETS if totals[str(n)]['verified']==totals[str(n)]['frames']]
    pick = min(eligible,key=lambda n:(totals[str(n)]['billed_bytes'],n)) if eligible and plan['dataset_projection'] is None else None
    return {'schema':SCHEMA+'-report','plan_id':plan['plan_id'],'stratified':per_file,'totals':totals,
            'native_processes':len(seen),'development_trials':count,'selected_nonzero_on_full_development':pick,
            'held_out_run':False,'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


def execute(guard,build_file,dataset,output,wait_resource=False):
    from tsbench.supervisor.timing_resource import reserve
    plan, lock = plan_for(guard,build_file,dataset)
    require(output.is_relative_to(ROOT/'results'),'CORAD development output escaped workspace results')
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(reserve())
                break
            except ContractError as e:
                if not wait_resource or str(e)!='measurement resource is already reserved by another TSBench run':
                    raise
                print('waiting for the TSBench measurement reservation',flush=True)
                sleep(20)
        output.mkdir(parents=True)
        for name,key in (('encoder','encode'),('decoder','restore')):
            lane = output/name; lane.mkdir(); stage_recovery(ROOT,lane,lock[key])
        (output/'frames').mkdir()
        write_new(output/'plan.json',plan)
        report = audit(output,plan,lock,guard,build_file,True)
        write_new(output/'report.json',report)
        write_new(output/'completion.json',seal(output,plan))
    print(dict(report['totals']),flush=True)


def verify(run):
    plan = load_json(local_file(run,'plan.json'))
    require(seal(run,plan)==load_json(local_file(run,'completion.json')),'CORAD development seal differs')
    guard,build_file = check(ROOT,plan['source_guard']).parent, check(ROOT,plan['build'])
    regenerated,lock = plan_for(guard,build_file,plan['dataset_projection'])
    require(regenerated==plan,'CORAD development plan did not refreeze')
    for name,key in (('encoder','encode'),('decoder','restore')):
        for path,entry in lock[key]['files'].items():
            check(run/name/'recovery',{'path':path,'bytes':entry['bytes'],'sha256':entry['sha256']})
    report = audit(run,plan,lock,guard,build_file,False)
    require(report==load_json(local_file(run,'report.json')),'CORAD development summary differs from recomputation')
    print(dict(report['totals']),flush=True)


if __name__=='__main__':
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode',required=True)
    for k in ('build','run'):
        s = sub.add_parser(k)
        s.add_argument('--guard', type=Path, required=True)
        s.add_argument('--out', type=Path, required=True)
        if k=='run':
            s.add_argument('--build',type=Path,required=True)
            s.add_argument('--dataset')
            s.add_argument('--wait-resource',action='store_true')
    sub.add_parser('verify').add_argument('--run',type=Path,required=True)
    a = p.parse_args()
    try:
        if a.mode=='build':
            build(a.guard.resolve(strict=True),a.out.resolve())
        elif a.mode=='run':
            execute(a.guard.resolve(strict=True),a.build.resolve(strict=True),a.dataset,a.out.resolve(),a.wait_resource)
        else:
            verify(a.run.resolve(strict=True))
    except (OSError,ValueError,subprocess.CalledProcessError) as e:
        p.exit(1,f'{e}\n')
