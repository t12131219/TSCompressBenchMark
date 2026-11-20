"""Run bounded whole-file, detached ALP/Titchy repeats and replay their evidence."""
from collections import Counter
from contextlib import contextmanager
import os
from pathlib import Path
from random import Random
from statistics import median
from struct import unpack
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_column_batch as batch
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-column-batch-timing/1'
CODE = ('src/tsbench/application/m3_column_batch_timing.py', 'tools/m3_column_batch_timing.py',
        'src/tsbench/supervisor/timing_resource.py')
POLICY = {'seed': 228114, 'warmups': 1, 'measured_rounds': 3,
          'abi': 'sum of public ABI encode or decode spans, one new context per original frame; no group I/O or validation',
          'context': 'create separately; context destruction and result release only included in process and durable boundaries',
          'encode_path': 'verified parse of locked original through frame validation and file/directory fsync',
          'decode_path': 'fixed frame groups only through typed original validation and file/directory fsync',
          'group_files': 'concatenated recoverable ABI frames; staging headers are not charged as compressed data',
          'statistics': 'one fresh isolated process per file/configuration/direction/round; inner frames are not independent rounds',
          'cache': 'inherited; not a cold OS cache measurement', 'reservation': resource.RESERVATION,
          'exclusive_cpu': False, 'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


def _id(doc, key):
    require(doc[key] == content_id({k: v for k, v in doc.items() if k != key}), f'invalid column batch {key}')


def freeze(root, population, cpu, dataset=None):
    pop = load_json(population)
    _id(pop, 'population_id')
    require(pop['schema'] == batch.SCHEMA and pop['limits'] == batch.LIMITS and pop['launchers'] == batch.launcher_lock() and
            all(digest(local_file(root, p)) == h for p, h in pop['code'].items()), 'column batch population or runtime changed')
    require(dataset is None or dataset in {c['dataset_id'] for c in pop['cases']}, 'unknown column batch projection')
    body = {'schema': SCHEMA, 'population': batch.relative(root, population), 'population_id': pop['population_id'],
            'source_plan': pop['source_plan'], 'source_seal': pop['source_seal'], 'dataset_projection': dataset,
            'environment': resource.environment(cpu), 'policy': POLICY,
            'code': {p: digest(local_file(root, p)) for p in CODE}}
    return {**body, 'plan_content_id': content_id(body)}


def _cases(plan, pop):
    return [c for c in pop['cases'] if plan['dataset_projection'] in (None, c['dataset_id'])]


def _schedule(case):
    rng = Random(POLICY['seed'] ^ int(case['case_id'][:16], 16))
    slots = ['encode', *case['decode_backends']]
    for i in range(POLICY['warmups'] + POLICY['measured_rounds']):
        for slot in rng.sample(slots, len(slots)):
            yield {'round': i, 'phase': 'warmup' if i == 0 else 'measured', 'slot': slot}


@contextmanager
def _pin(cpu):
    saved = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {cpu})
    try:
        yield
    finally:
        os.sched_setaffinity(0, saved)


def _sync(paths):
    for path in (*paths.values(), next(iter(paths.values())).parent):
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _validate(case, cpu, t, row, raw, wire, seen):
    proc, obs = row['process'], row['native']
    slot = t['slot']
    encode = slot == 'encode'
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()) and
            proc['operation'] == ('encode' if encode else 'decode') and proc['status'] == 'completed' and
            proc['returncode'] == 0 and not proc['reason'] and proc['session_id'] and proc['session_id'] not in seen and
            proc['input_mounts'] == (raw if encode else wire) and row['product'] == (wire if encode else raw) and
            proc['child_usage']['maxrss_bytes'] > 0 and 0 < proc['pid'] and
            0 < obs['abi_wall_ns'] + obs['context_create_wall_ns'] <= proc['process_wall_ns'] <= row['durable_wall_ns'] and
            row['durable_wall_ns'] >= row['fsync_wall_ns'] > 0, 'column batch trial resources or results differ')
    batch.verify_census(case, slot, obs, cpu)
    seen.add(proc['session_id'])


def _raw_geometry(case, raw):
    expected = {batch.name(i): sum(8+u['schema']['bytes']+u['original']['bytes'] for u in case['units'][a:b])
                for i, (a, b) in enumerate(batch.groups(case['units']))}
    require({k: v['bytes'] for k,v in raw.items()} == expected, 'column batch raw group length differs')


def _verify_staged(paths, case):
    for i, (a, b) in enumerate(batch.groups(case['units'])):
        with paths[batch.name(i)].open('rb') as stream:
            for u in case['units'][a:b]:
                lengths = stream.read(8)
                want = u['original']['bytes'], u['schema']['bytes']
                require(len(lengths) == 8 and unpack('<II', lengths) == want and
                        batch.br(stream.read(want[1])) == u['schema'] and batch.br(stream.read(want[0])) == u['original'],
                        'column batch retained original/schema differs')
            require(not stream.read(1), 'column batch retained original has trailing bytes')


def distribution(values):
    return {'count':len(values),'min':min(values),'median':median(values),'max':max(values),
            'sample_basis':'independent_file_direction_rounds'}


def _summarize(case, by_slot):
    cost = Counter()
    for unit in case['units']:
        cost.update(unit['cost'])
    logical = sum(u['original']['bytes'] for u in case['units'])
    slots = {}
    for slot, rows in by_slot.items():
        require(len(rows) == POLICY['measured_rounds'], 'missing independent measured round')
        ns = {key: [r['native'][key] for r in rows] for key in ('abi_wall_ns', 'context_create_wall_ns')}
        ns.update(process_wall_ns=[r['process']['process_wall_ns'] for r in rows],
                  durable_wall_ns=[r['durable_wall_ns'] for r in rows], fsync_wall_ns=[r['fsync_wall_ns'] for r in rows])
        slots[slot] = {'time_ns': {k: distribution(v) for k,v in ns.items()},
                       'mib_per_s': {k: distribution([logical*1e9/(s*(1<<20)) for s in ns[k]])
                                     for k in ('abi_wall_ns','process_wall_ns','durable_wall_ns')},
                       'process_usage': {k: distribution([r['process']['child_usage'][k] for r in rows])
                                         for k in ('user_cpu_ns','system_cpu_ns','maxrss_bytes')},
                       'native_execution_census': rows[0]['native']['execution_census']}
    keys = ('work_item_id','dataset_id','route','plugin','canonical_object_id','operation_config_id','configuration')
    return {**{k:case[k] for k in keys}, 'case_id': case['case_id'], 'units': len(case['units']), 'logical_bytes': logical,
            'artifact_bytes': sum(cost.values()), 'byte_cost': dict(cost), 'ratio': logical/sum(cost.values()), 'slots': slots}


def recompute(run, plan):
    _id(plan, 'plan_content_id')
    pop = load_json(local_file(run, 'population.json'))
    _id(pop, 'population_id')
    ref = batch.relative(run, run / 'population.json')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['population_id'] == pop['population_id'] and
            all(plan[k] == pop[k] for k in ('source_plan','source_seal')) and
            all(ref[k] == plan['population'][k] for k in ('sha256','bytes')),
            'column batch replay population differs')
    for path, asset in pop['runtime']['files'].items():
        batch.check(run, {'path': 'runtime/' + path, **{k:asset[k] for k in ('bytes','sha256')}})
    cpu = plan['environment']['cpu']
    env = load_json(local_file(run, 'environment.json'))
    require(env['affinity'] == [cpu] and set(env) == {'affinity','before','after'}, 'column batch replay environment differs')
    cases, seen = [], set()
    with local_file(run, 'trials.jsonl').open('rb') as ledger:
        for case in _cases(plan, pop):
            _id(case,'case_id')
            base = run / 'cases' / case['case_id']
            raw_paths = batch.files(base/'raw', case['group_count'])
            raw = batch.identities(raw_paths)
            wire = batch.verify_frames(batch.files(base/'wire', case['group_count']), case['units'])
            _verify_staged(raw_paths, case)
            by_slot = {s:[] for s in ('encode', *case['decode_backends'])}
            for idx, t in enumerate(_schedule(case)):
                row = parse_json(ledger.readline(), 'column batch trial')
                op = 'encode' if t['slot'] == 'encode' else 'decode'
                logs = base/'logs'/str(idx)
                require(load_json(local_file(logs, op+'.stdout')) == row['native'] and
                        local_file(logs, op+'.stderr').stat().st_size == 0, 'column batch replay logs differ')
                _validate(case,cpu,t,row,raw,wire,seen)
                if t['phase'] == 'measured':
                    by_slot[t['slot']].append(row)
            cases.append(_summarize(case,by_slot))
        require(not ledger.read(1), 'column batch ledger has extra trials')
    return {'schema': SCHEMA+'-report', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'], 'environment': env,
            'source_seal': plan['source_seal'], 'source_plan': plan['source_plan'], 'dataset_projection': plan['dataset_projection'],
            'verified_trials': len(seen), 'cases':cases, 'excluded':pop['excluded'], 'policy':POLICY,
            'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}


def verify(run):
    seal = load_json(local_file(run,'completion.json'))
    _id(seal,'seal_id')
    require(seal['schema'] == SCHEMA+'-seal' and seal['run_id'] == run.name and
            set(seal['files']) == {'plan.json','population.json','environment.json','trials.jsonl','report.json'},
            'column batch seal structure differs')
    for name, ref in seal['files'].items():
        require(batch.check(run,ref) == local_file(run,name), 'column batch seal contains a foreign file')
    plan = load_json(local_file(run,'plan.json'))
    require(seal['plan_content_id'] == plan['plan_content_id'], 'column batch seal plan differs')
    report = recompute(run, plan)
    require(report == load_json(run / 'report.json'), 'column batch stored report differs from replay')
    return report


def execute(root, plan, output):
    pop_file = batch.check(root, plan['population'])
    cpu = plan['environment']['cpu']
    require(plan == freeze(root,pop_file,cpu,plan['dataset_projection']), 'column batch frozen timing plan changed')
    require(output.is_relative_to(root), 'column batch run outside project')
    pop = load_json(pop_file)
    source = load_json(batch.check(root, plan['source_plan']))
    entries = batch._entry_map(root, load_json(batch.check(root, source['definition']['plan'])))
    with resource.reserve(), _pin(cpu):
        run = output / uuid4().hex
        run.mkdir(parents=True, exist_ok=False)
        stage_recovery(root,run,pop['runtime'],directory='runtime')
        write_new(run/'plan.json',plan)
        write_new(run/'population.json',pop)
        env = {'affinity':[cpu], 'before':resource.observe(cpu)}
        seen = set()
        with (run/'trials.jsonl').open('xb') as ledger:
            for case in _cases(plan,pop):
                base = run/'cases'/case['case_id']
                base.mkdir(parents=True)
                (base/'logs').mkdir()
                entry = entries[case['dataset_id']]
                with TemporaryDirectory(dir=base,prefix='setup-') as tmp:
                    b = Path(tmp)
                    raws = batch.prepare_values(root,entry,case,b)
                    wires, _, _ = batch.invoke(pop,run/'runtime',case,'encode',raws,b/'anchor')
                    raw = batch.identities(raws)
                    _raw_geometry(case,raw)
                    wire = batch.verify_frames(wires,case['units'])
                    next(iter(raws.values())).parent.rename(base/'raw')
                    next(iter(wires.values())).parent.rename(base/'wire')
                fixed = batch.files(base/'wire',case['group_count'])
                for i,t in enumerate(_schedule(case)):
                    with TemporaryDirectory(dir=base,prefix='operation-') as tmp:
                        b, slot = Path(tmp), t['slot']
                        tick = monotonic_ns()
                        inputs = batch.prepare_values(root,entry,case,b) if slot == 'encode' else fixed
                        got, native, proc = batch.invoke(pop,run/'runtime',case,slot,inputs,b/'call')
                        product = batch.verify_frames(got,case['units']) if slot == 'encode' else batch.identities(got)
                        require(product == (wire if slot == 'encode' else raw), 'column batch directional output differs')
                        sync = monotonic_ns()
                        _sync(got)
                        end = monotonic_ns()
                        worklog = base/'logs'/str(i)
                        worklog.mkdir()
                        for path in (b/'call').glob('*.std*'):
                            path.rename(worklog/path.name)
                        row = {**t,'case_id':case['case_id'],'native':native,'process':proc,'product':product,
                               'durable_wall_ns':end-tick,'fsync_wall_ns':end-sync}
                        _validate(case,cpu,t,row,raw,wire,seen)
                        _line(ledger,row)
                print(f"verified {case['dataset_id']} {case['route']} ({len(case['units'])} frames)",flush=True)
        env['after'] = resource.observe(cpu)
        write_new(run/'environment.json',env)
        report = recompute(run,plan)
        write_new(run/'report.json',report)
        files = {n:batch.relative(run,run/n) for n in ('plan.json','population.json','environment.json','trials.jsonl','report.json')}
        seal = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_content_id':plan['plan_content_id'],'files':files}
        write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    return run
