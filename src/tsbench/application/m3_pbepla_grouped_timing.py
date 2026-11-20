"""Full-extent independent file rounds over the same bounded PBEP windows."""
from collections import Counter, defaultdict
from contextlib import ExitStack
from itertools import islice
import os
from pathlib import Path
from random import Random
from struct import Struct
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_pbepla import PROGRESSIVE, REPLAY
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_abi_corpus_timing import br
from .m3_column_batch_timing import _id, _pin, distribution
from .m3_pbepla import GROUP, staged_windows
from .m3_real_corpus_execution import _entry_map
from .m3_sprintz_timing import check, ref, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-pbepla-grouped-timing/1'
POP = 'bmk.m3-pbepla-grouped-population/1'
TOOL = 'pbepla-grouped'
LAYERS = (1, 2, 3)
OPERATIONS = ('encode', 'restore-L1', 'restore-L2', 'restore-L3')
RECORD = Struct('<II')
CODE = ('src/tsbench/application/m3_pbepla_grouped_timing.py', 'tools/m3_pbepla_grouped_timing.py',
        'src/tsbench/application/m3_column_batch_timing.py', 'src/tsbench/supervisor/timing_resource.py')
POLICY = {'seed':119781, 'warmups':1, 'measured_rounds':3, 'group_max_windows':GROUP,
          'sampling':'independent file/route/phase rounds with a fresh isolated process per bounded internal group; groups not replicates',
          'encoding_replay_control':'batch comparison from same window timed separately, not charged to native replay',
          'restore':'one fixed exact prefix per window in each detached session; original only available to host validator',
          'durable':'original source parse or immutable prefix archive through product verification and sync of grouped output and directory',
          'archive':'experiment pack has 8-byte ordinal and extent per record; native compression accounting excludes the pack; layers stand alone',
          'failed_files':'keep actual failure and partial coverage; missing prefixes skip decode explicitly; no admitted summaries from failed files',
          'cache':'inherited, not cold', 'reservation':resource.RESERVATION, 'exclusive_cpu':False,
          'stage_accepted':False, 'timing_admitted':False, 'qualification_granted':False}


def freeze(root, pop_path, cpu, datasets=()):
    pop = load_json(pop_path)
    _id(pop,'population_id')
    require(pop['schema']==POP and pop['launchers']==launcher_lock() and
            all(digest(local_file(root,k))==h for k,h in pop['code'].items()),'PBEPLA population contract changed')
    require(len(set(datasets))==len(datasets) and set(datasets)<={c['dataset_id'] for c in pop['cases']},'unknown PBEPLA projection')
    body = {'schema':SCHEMA,'population':relative(root,pop_path),'population_id':pop['population_id'],
            'source_plan':pop['source_plan'],'source_seal':pop['source_seal'],'dataset_projection':sorted(datasets) or None,
            'policy':POLICY,'environment':resource.environment(cpu),'code':{k:digest(local_file(root,k)) for k in CODE}}
    return {**body,'plan_content_id':content_id(body)}


def _cases(pop,plan):
    return [c for c in pop['cases'] if plan['dataset_projection'] is None or c['dataset_id'] in plan['dataset_projection']]


def schedule(case):
    rng = Random(POLICY['seed'] ^ int(case['case_id'][:16],16))
    for r in range(POLICY['warmups']+POLICY['measured_rounds']):
        for op in rng.sample(OPERATIONS,len(OPERATIONS)):
            yield {'operation':op,'round':r,'phase':'warmup' if r==0 else 'measured'}


def groups(case, layer=None):
    """Return original file-local IDs even when failed windows have no prefix."""
    rows = [(i,u) for i,u in enumerate(case['units']) if layer is None or u['status']!='failed']
    for start in range(0,len(rows),GROUP):
        yield rows[start:start+GROUP]


def _parts(case, layer=None, restored=False):
    for i,u in enumerate(case['units']):
        if layer is None:
            yield i,{'bytes':u['logical_input_bytes'],'sha256':u['input_sha256']}
        elif u['status'] != 'failed':
            t = u['layers'][layer-1]
            yield i,{'bytes':u['logical_input_bytes'] if restored else t['bytes'],
                     'sha256':t['restored_sha256' if restored else 'frame_sha256']}


def _append(stream, i, payload):
    stream.write(RECORD.pack(i,len(payload)))
    stream.write(payload)


def _read_pack(path, expected):
    with path.open('rb') as f:
        for i,identity in expected:
            h = f.read(RECORD.size)
            require(len(h)==RECORD.size and RECORD.unpack(h)==(i,identity['bytes']),'PBEPLA packed frame length or ordinal differs')
            raw = f.read(identity['bytes'])
            require(br(raw)==identity,'PBEPLA packed bytes differ from r40 identity')
            yield raw
        require(not f.read(1),'unexpected trailing PBEPLA pack bytes')


def _mode(case, layer):
    replay = case['route']==REPLAY
    return ('replay' if replay else 'progressive') if layer is None else ('restore-callback' if replay else 'restore-batch')


def _run_worker(run,pop,cpu,mode,layer,inputs,work):
    work.mkdir()
    indexes = [name if layer is None else name.split('-',1)[0] for name in inputs]
    argv = [mode,*([str(layer)] if layer is not None else []),*indexes]
    out,proc = invoke_isolated_tool(run/'runtime',pop['runtime'],TOOL,pop['limits'],work,work,mode,inputs,argv,lambda:False,
                                    observe=True,file_ceiling=pop['limits']['file_bytes'],private_tmp=True)
    stdout,stderr = (work/(mode+'.'+ext) for ext in ('stdout','stderr'))
    require(proc['status']=='completed' and proc['returncode']==0 and not stderr.stat().st_size,
            f'PBEPLA {mode}: {proc["status"]}: {stderr.read_text()[:300]}')
    lines = [parse_json(row,'PBEPLA grouped worker') for row in stdout.read_text().splitlines()]
    require(len(lines)==2*len(inputs)+1 and lines[-1]=={'units':len(inputs),'cpu_endpoints':[cpu]*2},
            'PBEPLA isolated group did not cover planned units/CPU')
    return out,{'process':proc,'cpu_endpoints':lines[-1]['cpu_endpoints'],'observations':[
        {'result':a,'clock':b} for a,b in zip(lines[:-1:2],lines[1:-1:2],strict=True)]}


def _names(units, layer=None, inputs=False):
    if inputs:
        for j,(i,u) in enumerate(units):
            field = {'bytes':u['logical_input_bytes'],'sha256':u['input_sha256']} if layer is None else {
                'bytes':u['layers'][layer-1]['bytes'],'sha256':u['layers'][layer-1]['frame_sha256']}
            yield str(j) if layer is None else f'{j}-{layer}', i, field
    else:
        for j,(i,u) in enumerate(units):
            if u['status']=='failed':
                continue
            if layer is None:
                for k,t in enumerate(u['layers'],1):
                    yield f'{j}-{k}',i,{'bytes':t['bytes'],'sha256':t['frame_sha256']}
            else:
                yield f'{j}-{layer}',i,{'bytes':u['logical_input_bytes'],'sha256':u['layers'][layer-1]['restored_sha256']}


def _record(case, units, layer, row, cpu, seen):
    mode, replay = _mode(case,layer), case['route']==REPLAY
    proc = row['process']
    expected_in = {n:v for n,_,v in _names(units,layer,True)}
    expected_out = {n:v for n,_,v in _names(units,layer)}
    require(row['indices']==[i for i,_ in units] and row['cpu_endpoints']==[cpu]*2 and proc['input_mounts']==expected_in and
            row['outputs']==expected_out and proc['operation']==mode and proc['status']=='completed' and proc['returncode']==0 and
            not proc['reason'] and proc['pid']>0 and proc['session_id'] and proc['session_id'] not in seen and
            proc['child_usage']['maxrss_bytes']>0 and len(row['observations'])==len(units),'PBEPLA group status/scope differs')
    seen.add(proc['session_id'])
    tally, sink = Counter(), []
    for j,((_,u),e) in enumerate(zip(units,row['observations'],strict=True)):
        obs, doc = e['result'],e['clock']
        calls = doc['native_calls']
        require(obs['index']==doc['index']==j and all(type(x['wall_ns']) is int and x['wall_ns']>0 and
                    type(x['result']) is int for x in calls),'PBEPLA native clock census differs')
        if layer is not None:
            wanted = [('detached_prefix_inspect',0),('callback_restore' if replay else 'batch_restore',layer)]
            require(obs=={'index':j,'status':'restored','layer':layer},'PBEPLA detached prefix was not restored')
        elif u['status']=='failed':
            wanted = [('replay_encode' if replay else 'batch_encode',0)]
            require(obs=={'index':j,'status':'failed','reason':u['reason']},'PBEPLA failure changed or got a synthetic prefix')
        else:
            wanted = ([('replay_encode',0)] if replay else [])+[('batch_encode',0)]+[('prefix_materialize',k) for k in LAYERS]
            require(obs['status']=='encoded' and obs['rows']*8==u['logical_input_bytes'] and
                    obs['native_full_bytes']==u['layers'][-1]['bytes'],'PBEPLA generated different output')
            io = obs['replay']
            require(({k:v for k,v in io.items() if k!='first_sink_ns'} if io else None)==u['replay'],'PBEPLA actual replay work differs')
            if replay:
                require(type(io['first_sink_ns']) is int and 0<io['first_sink_ns']<=proc['process_wall_ns'],'PBEPLA first sink was not observed')
                sink.append(io['first_sink_ns'])
        rejected = layer is None and u['status']=='failed'
        require([(a['part'],a['layer']) for a in calls]==wanted and all((a['result']!=0)==rejected for a in calls),
                'PBEPLA native phase or exit status differs')
        for a in calls:
            category = a['part']
            if rejected:
                category = 'failed_'+category
            if replay and category=='batch_encode':
                category = 'batch_validation_control'
            if category=='prefix_materialize':
                category += '_L'+str(a['layer'])
            tally[category]+=a['wall_ns']
    require(0<sum(tally.values())<=proc['process_wall_ns'],'PBEPLA native phase clocks overlap or exceed group time')
    return tally,sink


def _flush(streams, head):
    for f in streams:
        f.flush()
        os.fsync(f.fileno())
    fd = os.open(head,os.O_RDONLY|os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _drive(run,pop,case,layer,cpu,dest,values,streams,seen):
    mode = _mode(case,layer)
    result = []
    dest.mkdir()
    for group in groups(case,layer):
        with TemporaryDirectory(prefix='group-',dir=dest) as tmp:
            work = Path(tmp)
            inputs = {}
            for name,_,identity in _names(group,layer,True):
                data = next(values,b'')
                require(br(data)==identity,'PBEPLA group original/prefix identity differs before launch')
                p = work/name
                p.write_bytes(data)
                inputs[name] = p
            out,row = _run_worker(run,pop,cpu,mode,layer,inputs,work/'call')
            expected = list(_names(group,layer))
            require({p.name for p in out.iterdir()}=={n for n,_,_ in expected},'PBEPLA unexpected or missing product')
            row['outputs'],row['indices'] = {},[i for i,_ in group]
            for name,i,_ in expected:
                wire = local_file(out,name).read_bytes()
                row['outputs'][name] = br(wire)
                target = int(name.split('-')[1]) if layer is None else layer
                _append(streams[target],i,wire)
            _record(case,group,layer,row,cpu,seen)
            result.append(row)
    require(next(values,None) is None,'PBEPLA file execution left unconsumed unit data')
    return result


def _source(root, entry, pair, case, work):
    with staged_windows(root,entry,pair[PROGRESSIVE],pair[REPLAY],work) as source:
        for ((w,raw),(i,ident)) in zip(source,_parts(case),strict=True):
            unit = case['units'][i]
            require((w.column,w.ordinal,[w.start,w.end])==(unit['column'],unit['window_ordinal'],unit['row_range']) and
                    br(raw)==ident,'PBEPLA loaded source geometry differs')
            yield raw


def _make_anchor(root,run,pop,case,entry,pair,cpu,dest):
    dest.mkdir(parents=True)
    with TemporaryDirectory(prefix='anchor-',dir=dest) as tmp, ExitStack() as stack:
        folder = Path(tmp)
        vals = stack.enter_context((dest/'raw').open('xb'))
        source = _source(root,entry,pair,case,folder)
        def capture():
            for i,data in enumerate(source):
                _append(vals,i,data)
                yield data
        streams = {k:stack.enter_context((dest/f'L{k}').open('xb')) for k in LAYERS}
        _drive(run,pop,case,None,cpu,folder/'work',capture(),streams,set())
        _flush([vals,*streams.values()],dest)
    _verify_anchors(case,dest)


def _verify_anchors(case,base):
    for path,k in [('raw',None),*((f'L{i}',i) for i in LAYERS)]:
        for _ in _read_pack(local_file(base,path),_parts(case,k)):
            pass


def _trial(root,run,pop,case,entry,pair,anchor,cpu,t,seen):
    op = t['operation']
    layer = None if op=='encode' else int(op[-1])
    flag = layer is not None and not any(u['status']!='failed' for u in case['units'])
    row = {**t,'case_id':case['case_id'],'status':'not_run_no_valid_prefix' if flag else 'measured_as_declared'}
    if flag:
        return {**row,'durable_wall_ns':None,'fsync_wall_ns':None,'groups':[]}
    with TemporaryDirectory(prefix='repeat-',dir=anchor) as tmp, ExitStack() as stack:
        folder = Path(tmp)
        started = monotonic_ns()
        vals = _source(root,entry,pair,case,folder) if layer is None else _read_pack(anchor/f'L{layer}',_parts(case,layer))
        streams = {k:stack.enter_context((folder/f'result-L{k}').open('xb')) for k in (LAYERS if layer is None else (layer,))}
        measured = _drive(run,pop,case,layer,cpu,folder/'work',vals,streams,seen)
        sync = monotonic_ns()
        _flush(streams.values(),folder)
        finished = monotonic_ns()
        return {**row,'durable_wall_ns':finished-started,'fsync_wall_ns':finished-sync,'groups':measured}


def _validate_trial(case,cpu,t,row,seen):
    require(row['case_id']==case['case_id'] and all(row[k]==v for k,v in t.items()),'PBEPLA scheduled slot differs')
    layer = None if t['operation']=='encode' else int(t['operation'][-1])
    expected = list(groups(case,layer))
    require(len(expected)==len(row['groups']),'PBEPLA file round omitted a group')
    if not expected:
        require(row['status']=='not_run_no_valid_prefix' and row['durable_wall_ns'] is None and row['fsync_wall_ns'] is None,
                'PBEPLA absent prefix cannot create measured latency')
        return None
    native, sink, process, cpu_times, rss = Counter(), [], 0, Counter(), []
    for start,rec in zip(expected,row['groups'],strict=True):
        ns,first = _record(case,start,layer,rec,cpu,seen)
        native.update(ns)
        sink.extend(first)
        process += rec['process']['process_wall_ns']
        u = rec['process']['child_usage']
        cpu_times.update({k:u[k] for k in ('user_cpu_ns','system_cpu_ns')})
        rss.append(u['maxrss_bytes'])
    require(row['status']=='measured_as_declared' and 0<process<=row['durable_wall_ns'] and
            0<row['fsync_wall_ns']<=row['durable_wall_ns'],'PBEPLA file durable clock differs')
    return {'native_category_ns':dict(native),'first_sink_ns_min_max':{'min':min(sink),'max':max(sink),'per_window_count':len(sink)} if sink else None,
            'summed_group_process_wall_ns':process,'durable_wall_ns':row['durable_wall_ns'],'fsync_wall_ns':row['fsync_wall_ns'],
            'group_cpu_ns':dict(cpu_times),'max_group_rss_bytes':max(rss)}


def _summarize(case, rounds):
    out = {}
    counts = dict(Counter(u['status'] for u in case['units']))
    logical = sum(u['logical_input_bytes'] for u in case['units'])
    for op, entries in rounds.items():
        require(len(entries)==POLICY['measured_rounds'],'PBEPLA independent file rounds missing')
        if case['status']!='verified':
            out[op] = {'measured_rounds':sum(m is not None for m in entries),'scope':'unadmitted_incomplete_file','clock_distributions_ns':None}
            continue
        columns = defaultdict(list)
        for m in entries:
            for k,v in m['native_category_ns'].items():
                columns[k].append(v)
            for k in ('summed_group_process_wall_ns','durable_wall_ns','fsync_wall_ns','max_group_rss_bytes'):
                columns[k].append(m[k])
            for k,v in m['group_cpu_ns'].items():
                columns[k].append(v)
        native = ('replay_encode' if case['route']==REPLAY else 'batch_encode') if op=='encode' else (
                  'callback_restore' if case['route']==REPLAY else 'batch_restore')
        out[op] = {'clock_distributions_ns':{k:distribution(v) for k,v in columns.items() if k!='max_group_rss_bytes'},
                   'peak_group_rss_bytes':distribution(columns['max_group_rss_bytes']),
                   'logical_mib_per_s':{k:distribution([logical*1e9/(ns*(1<<20)) for ns in columns[k]]) for k in (native,'durable_wall_ns')},
                   'first_sink_ns_by_independent_round':[m['first_sink_ns_min_max'] for m in entries]}
    layers = []
    for k in LAYERS:
        prefix = [u['layers'][k-1] for u in case['units'] if u['status']!='failed']
        layers.append({'layer':k,'prefix_bytes':sum(t['bytes'] for t in prefix),'header_bytes':sum(t['header_bytes'] for t in prefix),
                       'payload_bytes':sum(t['payload_bytes'] for t in prefix),'reusable_pack_overhead_bytes':RECORD.size*len(prefix),
                       'ratio':logical/sum(t['bytes'] for t in prefix) if case['status']=='verified' else None})
    keys = ('case_id','work_item_id','dataset_id','route','canonical_object_id','operation_config_id','configuration','status','reason')
    return {**{k:case[k] for k in keys},'window_status':counts,'original_logical_bytes':logical,'layers':layers,'directions':out}


def recompute(run,plan):
    _id(plan,'plan_content_id')
    pop = load_json(check(run,{**plan['population'],'path':'population.json'}))
    _id(pop,'population_id')
    require(plan['schema']==SCHEMA and plan['policy']==POLICY and pop['population_id']==plan['population_id'] and
            all(plan[k]==pop[k] for k in ('source_plan','source_seal')),'PBEPLA replay binds different population')
    for n,v in pop['runtime']['files'].items():
        check(run,{'path':'runtime/'+n,'sha256':v['sha256'],'bytes':v['bytes']})
    cpu = plan['environment']['cpu']
    env = load_json(local_file(run,'environment.json'))
    require(env['affinity']==[cpu] and set(env)=={'affinity','before','after'},'PBEPLA recorded affinity differs')
    seen, output, counts, verified = set(), [], Counter(), set()
    with local_file(run,'trials.jsonl').open('r',encoding='utf-8') as f:
        for case in _cases(pop,plan):
            _id(case,'case_id')
            if case['dataset_id'] not in verified:
                _verify_anchors(case,run/'cases'/case['dataset_id'])
                verified.add(case['dataset_id'])
            rounds = {op:[] for op in OPERATIONS}
            for t in schedule(case):
                row = parse_json(f.readline(),'PBEPLA whole-file round')
                stat = _validate_trial(case,cpu,t,row,seen)
                counts[row['status']]+=1
                if t['phase']=='measured':
                    rounds[t['operation']].append(stat)
            output.append(_summarize(case,rounds))
        require(not f.read(1),'PBEPLA ledger has extra trials')
    return {'schema':SCHEMA+'-report','run_id':run.name,'plan_content_id':plan['plan_content_id'],'source_seal':plan['source_seal'],
            'cases':output,'trial_states':dict(counts),'isolated_group_operations':len(seen),'environment':env,'policy':POLICY,
            'dataset_projection':plan['dataset_projection'],'stage_accepted':False,'qualification_granted':False,'timing_admitted':False}


def execute(root,plan,dest):
    pop_path = check(root,plan['population'])
    cpu = plan['environment']['cpu']
    require(plan==freeze(root,pop_path,cpu,plan['dataset_projection'] or ()) and dest.is_relative_to(root),'PBEPLA execution no longer matches plan')
    pop = load_json(pop_path)
    source = load_json(check(root,plan['source_plan']))
    entries = _entry_map(root,load_json(check(root,source['definition']['plan'])))
    binding = defaultdict(dict)
    for w in source['work_items']:
        if w['selection']==87 and w['route'] in (PROGRESSIVE,REPLAY):
            binding[w['dataset_id']][w['route']] = w
    scope = _cases(pop,plan)
    progressive = {c['dataset_id']:c for c in scope if c['route']==PROGRESSIVE}
    with resource.reserve(),_pin(cpu):
        run = dest/uuid4().hex
        run.mkdir(parents=True)
        stage_recovery(root,run,pop['runtime'],directory='runtime')
        write_new(run/'plan.json',plan)
        write_new(run/'population.json',pop)
        env = {'affinity':[cpu],'before':resource.observe(cpu)}
        seen = set()
        with (run/'trials.jsonl').open('xb') as ledger:
            for case in scope:
                ds = case['dataset_id']
                work = run/'cases'/ds
                if not work.exists():
                    _make_anchor(root,run,pop,progressive[ds],entries[ds],binding[ds],cpu,work)
                for t in schedule(case):
                    row = _trial(root,run,pop,case,entries[ds],binding[ds],work,cpu,t,seen)
                    _line(ledger,row)
                print(f"reconciled {ds} {case['route']} ({len(case['units'])} windows, {case['status']})",flush=True)
        env['after'] = resource.observe(cpu)
        write_new(run/'environment.json',env)
        write_new(run/'report.json',recompute(run,plan))
        files = {n:relative(run,run/n) for n in ('plan.json','population.json','trials.jsonl','environment.json','report.json')}
        seal = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_content_id':plan['plan_content_id'],'files':files}
        write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    return run


def verify(run):
    seal = load_json(local_file(run,'completion.json'))
    _id(seal,'seal_id')
    require(seal['schema']==SCHEMA+'-seal' and seal['run_id']==run.name and
            set(seal['files'])=={'plan.json','population.json','trials.jsonl','environment.json','report.json'},'PBEPLA seal differs')
    for name,v in seal['files'].items():
        require(check(run,v)==local_file(run,name),'PBEPLA seal references another path')
    plan = load_json(local_file(run,'plan.json'))
    require(seal['plan_content_id']==plan['plan_content_id'],'PBEPLA seal binds wrong plan')
    report = recompute(run,plan)
    require(report==load_json(local_file(run,'report.json')),'PBEPLA stored report differs from replay')
    return report
