"""Independent process rounds for three native Titchy file-local mechanisms."""
from collections import Counter, defaultdict
import os
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_titchy_grouped as titchy
from .m3_column_batch_timing import _id, _pin, _sync, distribution
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-titchy-grouped-timing/1'
CODE = ('src/tsbench/application/m3_titchy_grouped_timing.py','tools/m3_titchy_grouped_timing.py',
        'src/tsbench/application/m3_column_batch_timing.py','src/tsbench/supervisor/timing_resource.py')
POLICY = {'seed':185701, 'warmup_rounds':1,'measured_rounds':3, 'cache':'inherited, not cold',
          'boundary':'one isolated file/direction process per round with fresh native sessions per frozen unit',
          'native_stream':'push/pop/finish and detached decode, per-unit first packet; reset checks excluded from primary native clock',
          'native_access':'open/point/bit/range clocks separate from full-validation recovery; callback-request bytes are not physical file reads',
          'encode_durable':'starts from re-read locked source; ends after validation and syncing file and directory',
          'decode_durable':'starts from fixed frame mounts; includes required query and recovery validation, including output sync',
          'grouping':'execution only; no change to original file window or native stream boundaries',
          'reservation':resource.RESERVATION,'exclusive_cpu':False,'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}


def freeze(root, pop_file, cpu, datasets=()):
    pop = load_json(pop_file)
    _id(pop,'population_id')
    require(pop['schema']==titchy.SCHEMA and pop['limits']==titchy.LIMITS and pop['launchers']==titchy.launcher_lock() and
            all(digest(local_file(root,p))==h for p,h in pop['code'].items()),'Titchy grouped population or runtime changed')
    require(len(datasets)==len(set(datasets)) and set(datasets)<={c['dataset_id'] for c in pop['cases']},'invalid Titchy grouped dataset projection')
    body = {'schema':SCHEMA,'population':titchy.relative(root,pop_file),'population_id':pop['population_id'],
            'source_plan':pop['source_plan'],'source_seal':pop['source_seal'],'dataset_projection':sorted(datasets) or None,
            'policy':POLICY,'environment':resource.environment(cpu),'code':{p:digest(local_file(root,p)) for p in CODE}}
    return {**body,'plan_content_id':content_id(body)}


def _cases(pop, plan):
    selected = plan['dataset_projection']
    return [c for c in pop['cases'] if not selected or c['dataset_id'] in selected]


def schedule(case):
    rng = Random(POLICY['seed'] ^ int(case['case_id'][:16],16))
    for i in range(POLICY['warmup_rounds']+POLICY['measured_rounds']):
        for op in rng.sample(titchy.DIRS,len(titchy.DIRS)):
            yield {'direction':op,'round':i,'phase':'warmup' if i<POLICY['warmup_rounds'] else 'measured'}


def metrics(case, direction, records):
    clocks, secondary = defaultdict(list), defaultdict(list)
    def add(key, ns):
        require(type(ns) is int and ns>0,f'Titchy {key} requires a positive wall clock')
        clocks[key].append(ns)
    for obs in records:
        if direction=='encode' or titchy.is_stream(case):
            add('native_operation_wall_ns',obs['wall_ns'])
            if titchy.is_stream(case) and direction=='encode':
                ns = obs['first_packet_ns']
                require(type(ns) is int and 0<ns<=obs['wall_ns'],'Titchy first packet outside native stream encode')
                secondary['first_packet_wall_ns'].append(ns)
        else:
            add('full_validation_restore_wall_ns',obs['restore']['wall_ns'])
            if case['route']=='batch-range':
                add('stateless_range_with_container_validation_wall_ns',obs['wall_ns'])
            else:
                for mode in ('callback','file'):
                    add(mode+'_open_wall_ns',obs[mode+'_open']['wall_ns'])
                    q = obs[mode+'_queries']
                    for name in ('point','bit'):
                        for x in q[name+'_observations']:
                            add(mode+'_'+name+'_wall_ns',x['wall_ns'])
                    add(mode+'_range_wall_ns',q['range_observation']['wall_ns'])
            require(type(obs['process_peak_rss_bytes']) is int and obs['process_peak_rss_bytes']>0,'Titchy access RSS missing')
    return {'native_category_ns':{key:sum(parts) for key,parts in clocks.items()},
            'per_unit_not_independent_repeats':{key:{'count':len(parts),'min':min(parts),'max':max(parts)} for key,parts in secondary.items()}}


def _check(case,cpu,t,row,obs,seen):
    d, proc = t['direction'], row['process']
    raw, wire = titchy.expected(case,'raw'), titchy.expected(case,'wire')
    m = metrics(case,d,obs)
    require(all(row[k]==v for k,v in t.items()) and row['case_id']==case['case_id'] and row['observations']==m and
            proc['operation']==d and proc['status']=='completed' and proc['returncode']==0 and not proc['reason'] and
            proc['session_id'] and proc['session_id'] not in seen and proc['pid']>0 and proc['child_usage']['maxrss_bytes']>0 and
            proc['input_mounts']==(raw if d=='encode' else wire) and row['outputs']==(wire if d=='encode' else raw) and
            0<sum(m['native_category_ns'].values())<=proc['process_wall_ns']<=row['durable_wall_ns'] and
            0<row['fsync_wall_ns']<=row['durable_wall_ns'], 'Titchy grouped process, clock or detached outputs differ')
    seen.add(proc['session_id'])


def _summarize(case, measured):
    cost = Counter()
    for unit in case['units']:
        cost.update(unit['cost'])
    logical = sum(u['original']['bytes'] for u in case['units'])
    summary = {}
    for direction, rows in measured.items():
        require(len(rows)==POLICY['measured_rounds'],'Titchy independent repeats missing')
        clocks = defaultdict(list)
        for r in rows:
            for k,v in r['observations']['native_category_ns'].items():
                clocks[k].append(v)
            for key in ('durable_wall_ns','fsync_wall_ns'):
                clocks[key].append(r[key])
            clocks['process_wall_ns'].append(r['process']['process_wall_ns'])
        item = {'clock_distributions_ns':{k:distribution(v) for k,v in clocks.items()},
                'usage':{k:distribution([r['process']['child_usage'][k] for r in rows])
                         for k in ('user_cpu_ns','system_cpu_ns','maxrss_bytes')}}
        if direction=='encode' or titchy.is_stream(case):
            item['logical_mib_per_s'] = {k:distribution([logical*1e9/(n*(1<<20)) for n in clocks[k]])
                                         for k in ('native_operation_wall_ns','process_wall_ns','durable_wall_ns')}
        else:
            item['logical_mib_per_s'] = None  # Query bundle is not full decompression throughput.
        if titchy.is_stream(case) and direction=='encode':
            item['first_packet_wall_ns_by_round'] = [r['observations']['per_unit_not_independent_repeats']['first_packet_wall_ns'] for r in rows]
        summary[direction] = item
    counters = None
    if case['route']=='loaded-file-access':
        counters = Counter()
        for u in case['units']:
            q = u['native']['decode']
            counter = q['callback_queries']
            for name, rows in [('open',[q['callback_open']]),('point',counter['point_observations']),
                               ('bit',counter['bit_observations']),('range',[counter['range_observation']])]:
                for r in rows:
                    counters[name+'_calls']+=r['calls']
                    counters[name+'_bytes']+=r['requested_bytes']
    keys = ('work_item_id','route','dataset_id','operation_config_id','canonical_object_id','configuration','case_id')
    return {**{k:case[k] for k in keys},'directions':summary,'logical_bytes':logical,'cost':dict(cost),
            'artifact_bytes':sum(cost.values()),'ratio':logical/sum(cost.values()),'native_units':len(case['units']),
            'callback_reads':dict(counters) if counters is not None else None,'physical_file_read_bytes':None}


def recompute(run, plan):
    _id(plan,'plan_content_id')
    pop = load_json(titchy.check(run,{**plan['population'],'path':'population.json'}))
    _id(pop,'population_id')
    require(plan['schema']==SCHEMA and plan['policy']==POLICY and plan['population_id']==pop['population_id'] and
            all(plan[k]==pop[k] for k in ('source_plan','source_seal')),'Titchy replay population differs')
    for name,a in pop['runtime']['files'].items():
        titchy.check(run,{'path':'runtime/'+name,**{k:a[k] for k in ('bytes','sha256')}})
    env = load_json(local_file(run,'environment.json'))
    cpu = plan['environment']['cpu']
    require(set(env)=={'affinity','before','after'} and env['affinity']==[cpu],'Titchy replay environment differs')
    seen, cases = set(), []
    with local_file(run,'trials.jsonl').open('r',encoding='utf-8') as f:
        for case in _cases(pop,plan):
            _id(case,'case_id')
            base = run/'cases'/case['case_id']
            for folder in ('raw','wire'):
                titchy.files(base/folder,titchy.expected(case,folder))
            measured = {d:[] for d in titchy.DIRS}
            for i,t in enumerate(schedule(case)):
                row = parse_json(f.readline(),'Titchy grouped trial')
                d = t['direction']
                logs = base/'logs'/str(i)
                obs = titchy.read_observations(case,d,local_file(logs,d+'.stdout'),cpu)
                require(local_file(logs,d+'.stderr').stat().st_size==0,'Titchy replay stderr differs')
                _check(case,cpu,t,row,obs,seen)
                if t['phase']=='measured':
                    measured[d].append(row)
            cases.append(_summarize(case,measured))
        require(not f.read(1),'Titchy ledger has extra trials')
    return {'schema':SCHEMA+'-report','run_id':run.name,'plan_content_id':plan['plan_content_id'],'source_seal':plan['source_seal'],
            'verified_trials':len(seen),'cases':cases,'dataset_projection':plan['dataset_projection'],'environment':env,'policy':POLICY,
            'excluded':pop['excluded'],'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}


def execute(root, plan, dest):
    popfile = titchy.check(root,plan['population'])
    cpu = plan['environment']['cpu']
    require(plan==freeze(root,popfile,cpu,plan['dataset_projection'] or ()) and dest.is_relative_to(root),'Titchy group runtime changed')
    pop = load_json(popfile)
    entries = titchy._entry_map(root,load_json(titchy.check(root,pop['definition'])))
    with resource.reserve(),_pin(cpu):
        run = dest/uuid4().hex
        run.mkdir(parents=True)
        runtime = run/'runtime'
        stage_recovery(root,run,pop['runtime'],directory='runtime')
        write_new(run/'plan.json',plan)
        write_new(run/'population.json',pop)
        env = {'affinity':[cpu],'before':resource.observe(cpu)}
        seen = set()
        with (run/'trials.jsonl').open('xb') as ledger:
            for case in _cases(pop,plan):
                base = run/'cases'/case['case_id']
                (base/'logs').mkdir(parents=True)
                entry = entries[case['dataset_id']]
                with TemporaryDirectory(dir=base,prefix='setup-') as tmp:
                    work = Path(tmp)
                    raw = titchy.prepare(root,entry,case,work)
                    wire,en,_ = titchy.invoke(pop,runtime,case,'encode',raw,work/'anchor')
                    restored,de,_ = titchy.invoke(pop,runtime,case,'decode',wire,work/'oracle')
                    titchy.certify(case,raw,wire,restored,en,de)
                    next(iter(raw.values())).parent.rename(base/'raw')
                    next(iter(wire.values())).parent.rename(base/'wire')
                fixed = titchy.files(base/'wire',titchy.expected(case,'wire'))
                for i,t in enumerate(schedule(case)):
                    d = t['direction']
                    work = base/'logs'/str(i)
                    with TemporaryDirectory(dir=base,prefix='repeat-') as tmp:
                        tick = monotonic_ns()
                        inputs = titchy.prepare(root,entry,case,Path(tmp)) if d=='encode' else fixed
                        products,obs,proc = titchy.invoke(pop,runtime,case,d,inputs,work)
                        ids = {n:titchy.ref(p) for n,p in products.items()}
                        sync = monotonic_ns()
                        _sync(products)
                        end = monotonic_ns()
                        row = {**t,'case_id':case['case_id'],'outputs':ids,'process':proc,'observations':metrics(case,d,obs),
                               'durable_wall_ns':end-tick,'fsync_wall_ns':end-sync}
                        _check(case,cpu,t,row,obs,seen)
                        _line(ledger,row)
                        # Accepted identity is sealed, not a second copy per measurement.
                        for p in products.values():
                            p.unlink()
                        (work/'out').rmdir()
                print(f"verified {case['dataset_id']} {case['route']} ({len(case['units'])} units)",flush=True)
        env['after'] = resource.observe(cpu)
        write_new(run/'environment.json',env)
        write_new(run/'report.json',recompute(run,plan))
        files = {n:titchy.relative(run,run/n) for n in ('plan.json','population.json','environment.json','trials.jsonl','report.json')}
        seal = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_content_id':plan['plan_content_id'],'files':files}
        write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    return run


def verify(run):
    seal = load_json(local_file(run,'completion.json'))
    _id(seal,'seal_id')
    require(seal['schema']==SCHEMA+'-seal' and seal['run_id']==run.name and
            set(seal['files'])=={'plan.json','population.json','environment.json','trials.jsonl','report.json'},'Titchy invalid seal')
    for name,ref in seal['files'].items():
        require(titchy.check(run,ref)==local_file(run,name),'Titchy seal references another file')
    plan = load_json(local_file(run,'plan.json'))
    require(plan['plan_content_id']==seal['plan_content_id'],'Titchy timing seal plan differs')
    output = recompute(run,plan)
    require(output==load_json(local_file(run,'report.json')),'Titchy timing report differs from replay')
    return output
