"""Repeated, detached SElf* whole-corpus batch and ordered incremental diagnostics."""
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import groupby
import os
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_selfstar import DRIVERS
from ..planner.selfstar import BLOCK
from ..planner.selfstar_execution import PLUGIN, LIVE
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_worker, launcher_lock
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_selfstar import _live_adds, wire_facts
from .m3_sprintz_query import _stage
from .m3_sprintz_timing import check, ref, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-selfstar-whole-corpus-repeats/1'
LIMITS = {'address_space_bytes': 384<<20, 'file_bytes': 8<<20, 'wall_seconds': 60}
OPS = ('encode', 'decode')
ROUNDS = 3
POLICY = {'batch': 'timed_public_ABI_call_with_in_memory_object_or_frame',
          'incremental': 'timed_ordered_native_driver_begin_add_finish_or_read_next_drain_including_memory_framing',
          'lifecycle': 'one_fresh_context_per_column_direction_one_isolated_process_per_whole_file_direction_round',
          'outer': 'from_prepared_column_or_frame_inputs_through_child_and_output_digest_verification',
          'comparison': 'not_same_clock_no_ranking'}
CODE = ('src/tsbench/application/m3_selfstar_timing.py','tools/m3_selfstar_timing.py',
        'native/measurement/selfstar_corpus/main.cpp','native/measurement/selfstar_corpus/CMakeLists.txt',
        'plugins/codecs/selfstar-batch/corpus_control.cpp','native/runtime/plugin_loader.cpp','native/runtime/plugin_loader.hpp',
        'include/tsbench/plugin_abi.h','src/tsbench/application/m3_selfstar.py','src/tsbench/application/m3_sprintz_query.py',
        'src/tsbench/qualification/selfstar_wire.py','src/tsbench/recovery.py','src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/process.py','src/tsbench/supervisor/timing_resource.py','src/tsbench/corpus_ingress.py',
        'src/tsbench/application/m3_sealed_ledger.py','src/tsbench/application/m3_metric_details.py')


def schedule():
    rng = Random(20261120)
    return [{'round': i, 'phase': 'warmup' if not i else 'measured', 'operation': op}
            for i in range(ROUNDS+1) for op in rng.sample(OPS,len(OPS))]


def schema(rows, col):
    return canonical_bytes({'role':'value','dtype':'f64','rows':rows,'column_index':col,'state':'ordered-per-column',
                            'native_block_values':BLOCK})


def freeze(root, source, run, worker, cpu):
    plan = load_json(source)
    ledger, seal = full_run_source(plan, run)
    entries = _entry_map(root,load_json(check(root,plan['definition']['plan'])))
    cases, excluded = [], []
    for row,item in full_run_rows(plan,ledger):
        if item is None or 'entry_kind' in row or (row.get('selection'),row.get('route')) not in DRIVERS:
            continue
        ds = row['dataset_id']
        if row['status'] != 'verified':
            excluded.append({'dataset_id':ds,'route':row['route'],'status':row['status'],'reason':row['reason']})
            continue
        proof, entry = row['evidence'], entries[ds]
        rows, cols = entry['rows'], entry['value_count']
        scope = item['input']
        require((proof['rows'],proof['columns']) == (rows,cols) and proof['input_bytes'] == rows*cols*8 and
                scope['full_extent_of_file_rows_and_value_columns'] and scope['representation'] == 'f64_columns'
                and scope['column_grouping'] == 'one_work_unit_series_per_value_column' and item['canonical_object_id'] == entry['canonical']['object_id'],
                'SElf* exact full-column extent differs')
        variant = 'incremental' if row['route']==LIVE else 'batch'
        units = [{k:v for k,v in u.items() if k!='process_wall_ns'} for u in proof['units']]
        require([u['column'] for u in units] == list(range(cols)) and all(
                u['row_range']==[0,rows] and u['input_bytes']==rows*8<=LIMITS['file_bytes'] and
                sha256(schema(rows,u['column'])).hexdigest()==u['schema_sha256'] and
                0<u['artifact_bytes']<=LIMITS['file_bytes'] and
                (u['lifecycle'] is not None if variant=='incremental' else u['lifecycle'] is None) and
                u['artifact_bytes']==u['native_payload_bytes']+u['block_header_bytes']+u['object_envelope_bytes'] for u in units)
                and proof['artifact_bytes']==sum(u['artifact_bytes'] for u in units), 'SElf* sealed column billing or lifecycle differs')
        case = {'dataset_id':ds,'work_item_id':item['work_item_id'],'canonical_object_id':item['canonical_object_id'],
                'source_file':entry['file'],'configuration':scope,'rows':rows,'cols':cols,'route':row['route'],'variant':variant,'units':units}
        cases.append({**case,'case_id':content_id(case)})
    cases.sort(key=lambda c:(c['dataset_id'],c['variant']))
    require(cases, 'no SElf* verified cases')
    for _, sequence in groupby(cases,key=lambda c:c['dataset_id']):
        batch, live = list(sequence)
        require((batch['variant'],live['variant'])==('batch','incremental') and all(
                {k:v for k,v in a.items() if k!='lifecycle'}=={k:v for k,v in b.items() if k!='lifecycle'}
                for a,b in zip(batch['units'],live['units'],strict=True)), 'SElf* cannot share a reference across nonidentical routes')
    build = load_json(check(root,plan['build']['lock']))
    require(build['build_id']==plan['build']['build_id'], 'SElf* source codec build differs')
    exe = relative(root,worker)
    parts = {'worker':exe,'plugins':{PLUGIN:build['plugins'][PLUGIN]}}
    runtime = plan_recovery(root,{**parts,'build_id':content_id(parts)},{PLUGIN:{'plugin':PLUGIN,'options':{}}})
    body = {'schema':SCHEMA,'source':relative(root,source),'source_run':run.relative_to(root).as_posix(), 'source_seal':seal,
            'runtime':runtime,'worker':exe,'launchers':launcher_lock(),'limits':LIMITS,'policy':POLICY,'schedule':schedule(),
            'environment':resource.environment(cpu),'cases':cases,'excluded':excluded,'code':{p:digest(local_file(root,p)) for p in CODE}}
    return {**body,'plan_id':content_id(body)}


def names(c):
    return f'column-{c:04d}.bin', f'schema-{c:04d}.json', f'frame-{c:04d}.bmk'


def refs(case):
    raw, wire = {}, {}
    for u in case['units']:
        c = u['column']; data, meta, frame = names(c)
        raw[data] = {'bytes':u['input_bytes'],'sha256':u['restored_sha256']}
        raw[meta] = {'bytes':len(schema(case['rows'],c)),'sha256':u['schema_sha256']}
        wire[frame] = {'bytes':u['artifact_bytes'],'sha256':u['frame_sha256']}
    return raw,wire


def verified(directory,wanted):
    require(set(p.name for p in directory.iterdir())==wanted.keys(),'SElf* output file set differs')
    require(all(ref(local_file(directory,n))==a for n,a in wanted.items()),'SElf* bytes differ from sealed output')
    return wanted


def invoke(bundle,plan,case,op,paths,work):
    work.mkdir()
    out,p = invoke_isolated_worker(bundle,plan['runtime'],{'plugin':PLUGIN,'options':{}},LIMITS,
                                   work,work,op,paths,[case['variant'],'/inputs','/out',str(case['cols'])],lambda:False,
                                   observe=True,file_ceiling=LIMITS['file_bytes'])
    e = (work/(op+'.stderr')).read_text()
    require(p['status']=='completed' and p['returncode']==0 and not e, f"SElf* {case['dataset_id']}/{op}: {p['status']} {e[:400]}")
    return out,p,load_json(work/(op+'.stdout'))


def prepare_case(root,bundle,plan,case,entry,path):
    path.mkdir()
    d = path/'stage'; _stage(root,entry,d)
    a,b = refs(case)
    for n in range(case['cols']):
        (d/names(n)[1]).write_bytes(schema(case['rows'],n))
    verified(d,a)
    archive,p,native = invoke(bundle,plan,case,'encode',{n:d/n for n in a},path/'reference')
    require(p['input_mounts']==a and totals(plan,case,'encode',native),'SElf* untimed reference differs')
    verified(archive,b)
    for u in case['units']:
        c = u['column']
        result = wire_facts((archive/names(c)[2]).read_bytes(),case['rows'],schema(case['rows'],c))
        require(result=={k:u[k] for k in result},'SElf* exact block/wire layout differs')
    return d,archive


def totals(plan,case,op,doc):
    require(doc['route']==case['variant'] and doc['cpu_endpoints']==[plan['environment']['cpu']]*2 and
            len(doc['columns'])==case['cols'],'SElf* native population/CPU differs')
    acc = Counter()
    for u,n in zip(case['units'],doc['columns'],strict=True):
        common = {k:u[k] for k in ('blocks','native_bits','native_payload_bytes')}
        if case['variant']=='batch':
            expected = {**common,'mode':'batch','operation':op,'backend':'selfstar-c-scalar','threads':1,'fallback':False,
                        'block_values':BLOCK,'block_header_bytes':u['block_header_bytes']}
        elif op=='encode':
            lifecycle = u['lifecycle']
            require(lifecycle['add_calls']==_live_adds(case['rows']) and 0<lifecycle['prefinish_bits']<u['native_bits'],
                    'SElf* ordered add/finish lifecycle differs')
            expected = {**common,**lifecycle,'mode':'live','rows':case['rows']}
        else:
            expected = {**common,'mode':'read-finalized','rows':case['rows'],'add_calls':0,'prefinish_bits':0}
        require(n['column']==u['column'] and n['execution']==expected,'SElf* ordered native profile differs')
        for k in ('context_create_wall_ns','direction_call_wall_ns'):
            require(type(n[k]) is int and n[k]>0,'SElf* native timestamp missing or invalid')
            acc[k]+=n[k]
    return dict(acc)


def observe(bundle,plan,c,t,src,archive,path):
    op = t['operation']; a,b = refs(c)
    mounted,expected,folder = (a,b,src) if op=='encode' else (b,a,archive)
    start = monotonic_ns()
    out,p,doc = invoke(bundle,plan,c,op,{n:folder/n for n in mounted},path)
    output = verified(out,expected)
    native = totals(plan,c,op,doc)
    return {'case_id':c['case_id'],**t,'process':p,'native':doc,'native_totals_ns':native,'output':output,
            'staged_supervision_and_verification_wall_ns':monotonic_ns()-start}


def validate(plan,c,t,row,seen):
    op = t['operation']; a,b = refs(c)
    m,o = (a,b) if op=='encode' else (b,a)
    p = row['process']; native = totals(plan,c,op,row['native'])
    require(row['case_id']==c['case_id'] and all(row[k]==v for k,v in t.items()) and row['output']==o and
            p['input_mounts']==m and p['operation']==op and p['status']=='completed' and p['returncode']==0 and not p['reason'] and
            p['pid']>0 and p['session_id'] and p['session_id'] not in seen and p['child_usage']['maxrss_bytes']>0 and
            row['native_totals_ns']==native and 0<sum(native.values())<=p['process_wall_ns']<=row['staged_supervision_and_verification_wall_ns'],
            'SElf* whole-direction trial mounts/resources/timing differ')
    seen.add(p['session_id'])


def summarize(c,rows):
    counts = Counter(); result = {}
    for u in c['units']:
        counts.update({k:u[k] for k in ('blocks','input_bytes','artifact_bytes','native_bits','native_payload_bytes',
                                       'block_header_bytes','object_envelope_bytes')})
    for op in OPS:
        chosen = [r for r in rows if r['phase']=='measured' and r['operation']==op]
        require(len(chosen)==ROUNDS,'SElf* independent repeats differ')
        d = defaultdict(list)
        for r in chosen:
            for k,n in r['native_totals_ns'].items():
                d[k].append(n)
            p = r['process']; d['process_wall_ns'].append(p['process_wall_ns'])
            d['staged_wall_ns'].append(r['staged_supervision_and_verification_wall_ns'])
            for k,n in p['child_usage'].items():
                d['supervised_child_'+k].append(n)
        result[op] = {'distributions': {k:{**distribution(v),'sample_basis':POLICY['lifecycle']} for k,v in d.items()},
                      'logical_mib_per_second':{k:counts['input_bytes']*ROUNDS*1e9/(sum(d[k])*(1<<20)) for k in
                                               ('direction_call_wall_ns','process_wall_ns','staged_wall_ns')}}
    return {k:c[k] for k in ('dataset_id','work_item_id','route','variant','configuration')} | {
        'clock_extent':POLICY[c['variant']],'rows':[0,c['rows']],'columns':[0,c['cols']], 'backend':'selfstar-c-scalar',
        'native_threads':1,'counts':dict(counts),'ratio':counts['input_bytes']/counts['artifact_bytes'],'directions':result}


def verify(run):
    plan,seal = (load_json(local_file(run,n)) for n in ('plan.json','completion.json'))
    require(plan['schema']==SCHEMA and plan['policy']==POLICY and plan['schedule']==schedule() and plan['limits']==LIMITS and
            plan['plan_id']==content_id({k:v for k,v in plan.items() if k!='plan_id'}) and seal['schema']==SCHEMA+'-seal' and
            seal['plan_id']==plan['plan_id'] and seal['run_id']==run.name and
            seal['seal_id']==content_id({k:v for k,v in seal.items() if k!='seal_id'}) and
            seal['files'].keys()=={'plan.json','environment.json','trials.jsonl'},'SElf* timing seal differs')
    for value in seal['files'].values():
        check(run,value)
    for n,r in plan['runtime']['files'].items():
        check(run,{'path':'runtime/'+n,'bytes':r['bytes'],'sha256':r['sha256']})
    env = load_json(run/'environment.json'); require(env['affinity']==[plan['environment']['cpu']],'SElf* CPU binding differs')
    results,seen = [],set()
    with (run/'trials.jsonl').open('rb') as f:
        for c in plan['cases']:
            require(c['case_id']==content_id({k:v for k,v in c.items() if k!='case_id'}),'SElf* case extent differs')
            batch = []
            for t in plan['schedule']:
                row = parse_json(f.readline(),'SElf* timing trial')
                validate(plan,c,t,row,seen)
                batch.append(row)
            results.append(summarize(c,batch))
        require(not f.read(1),'SElf* ledger contains extra trials')
    return {'schema':SCHEMA+'-report','run_id':run.name,'seal_id':seal['seal_id'],'source_seal':plan['source_seal'],
            'policy':POLICY,'environment':env,'results':results,'excluded':plan['excluded'],'verified_trials':len(seen),
            'not_measured':{'original_to_durable':'both original ingress and fsync are outside these clocks',
                            'incremental_pure_C_call_sum':'clock encloses stream scheduling and memory framing',
                            'system_exclusivity':'only cooperative CPU reservation'},
            'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}


def execute(root,plan,output):
    source = check(root,plan['source']); source_run = (root/plan['source_run']).resolve(strict=True)
    cpu = plan['environment']['cpu']
    require(output.is_relative_to(root) and source_run.is_relative_to(root) and
            freeze(root,source,source_run,check(root,plan['worker']),cpu)==plan,'SElf* timing source, build or host changed')
    entries = _entry_map(root,load_json(check(root,load_json(source)['definition']['plan'])))
    output.mkdir(parents=True,exist_ok=True)
    with resource.reserve():
        run = output/uuid4().hex; run.mkdir(); print(f'run={run}',flush=True)
        write_new(run/'plan.json',plan)
        bundle=run/'runtime'; stage_recovery(root,run,plan['runtime'],directory=bundle.name)
        affinity,seen = os.sched_getaffinity(0),set()
        try:
            os.sched_setaffinity(0,{cpu}); env = {'affinity':sorted(os.sched_getaffinity(0)),'before':resource.observe(cpu)}
            with (run/'trials.jsonl').open('xb') as log:
                for ds,sequence in groupby(plan['cases'],key=lambda c:c['dataset_id']):
                    cases = list(sequence)
                    with TemporaryDirectory(prefix='selfstar-',dir=run) as tmp:
                        p = Path(tmp)
                        src,archive = prepare_case(root,bundle,plan,cases[0],entries[ds],p/'prepare')
                        for c in cases:
                            for t in plan['schedule']:
                                with TemporaryDirectory(prefix='trial-',dir=p) as scratch:
                                    row = observe(bundle,plan,c,t,src,archive,Path(scratch)/'work')
                                    validate(plan,c,t,row,seen)
                                    _line(log,row)
                            print(f"verified {ds} {c['route']} ({c['cols']} columns)",flush=True)
            env['after']=resource.observe(cpu)
        finally:
            os.sched_setaffinity(0,affinity)
        write_new(run/'environment.json',env)
        seal = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_id':plan['plan_id'],
                'files':{n:relative(run,run/n) for n in ('plan.json','environment.json','trials.jsonl')}}
        write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    write_new(run/'report.json',verify(run))
    return run
