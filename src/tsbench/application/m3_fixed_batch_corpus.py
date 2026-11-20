"""Replay exact r40 pcodec and Zstd/XZ fixed batches across the full value extent."""
from collections import Counter
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
from struct import pack
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_fixed_batch import DRIVER, ROUTES as FUNCTIONAL, units as geometry
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_column_batch as batch
from . import m3_column_batch_timing as timing
from .m3_real_corpus_execution import _stage_dataset
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-fixed-batch-corpus/1'
ROUTES = {key: FUNCTIONAL[key][0] for key in ((11, 'source-auto'), (11, 'c-native-auto'),
                                             (39, 'xz-baseline'), (40, 'zstd-baseline'))}
POLICY = {**timing.POLICY, 'durable_completion': 'artifact validation then output files and directories synced through run root',
          'retention': 'one verified typed source and fixed frame group set per case; no per-trial product retention'}
CODE = (*batch.CODE, *timing.CODE, 'src/tsbench/planner/m3_fixed_batch.py',
        'src/tsbench/application/m3_real_corpus_execution.py', 'src/tsbench/application/m3_fixed_batch_corpus.py',
        'native/measurement/fixed_batch/main.cpp', 'native/measurement/fixed_batch/CMakeLists.txt',
        'tools/m3_fixed_batch_corpus.py')
BASIS = ('dataset_id', 'route', 'selection', 'plugin', 'canonical_object_id', 'work_item_id', 'operation_config_id', 'operation')


def unit_schema(view, nbytes):
    if view == 'v_bytes_interleaved':
        return canonical_bytes({'role': 'bytes', 'dtype': 'u8', 'bytes': nbytes})
    require(view == 'f64_columns' and nbytes % 8 == 0, 'unexpected fixed batch value view')
    return canonical_bytes({'role': 'value', 'dtype': 'f64', 'rows': nbytes // 8})


def project(item, entry, proof, recovery_id):
    plugin = ROUTES[item['selection'], item['route']]
    view = 'f64_columns' if item['selection'] == 11 else 'v_bytes_interleaved'
    extent = item['input']
    object_id = entry['canonical']['object_id']
    require(proof['driver'] == DRIVER and proof['recovery_id'] == recovery_id and item['plugin'] == plugin and
            item['operation'] == 'roundtrip' and item['view'] == extent['representation'] == view and
            item['canonical_object_id'] == object_id and extent['row_ranges'] ==
            [{'object_id': object_id, 'partition': 'full', 'start': 0, 'end': entry['rows']}] and
            extent['value_column_range'] == [0, entry['value_count']], 'fixed batch anchor does not bind frozen extent')
    units = []
    for pos, row in zip(geometry(item), proof['units'], strict=True):
        nbytes = pos['input_bytes']
        schema = batch.br(unit_schema(view, nbytes))
        dtype, width = (10, 8) if view == 'f64_columns' else (2, 1)
        original, artifact = row['original'], row['artifact']
        require(all(row[k] == v for k, v in pos.items()) and original['schema'] == schema and
                original['raw']['bytes'] == nbytes and original['dtype'] == dtype and original['count'] == nbytes // width and
                set(row['decodes']) == {'default'} and row['decodes']['default']['restored'] == original and
                artifact['bytes'] > 32 + schema['bytes'], 'fixed batch unit geometry, recovery or billing differs')
        units.append({**pos, 'schema': schema, 'original': original['raw'], 'artifact': artifact,
                      'native': {'encode': row['encode']['native'], 'default': row['decodes']['default']['native']},
                      'cost': {'abi_envelope': 32 + schema['bytes'], 'native_frame': artifact['bytes'] - 32 - schema['bytes']}})
    require(len(units) == extent['size_estimate']['input_units'] and
            sum(u['input_bytes'] for u in units) == extent['size_estimate']['native_input_bytes_one_pass'] ==
            entry['rows'] * entry['value_count'] * 8, 'fixed batch extent total differs from frozen plan')
    return units


def freeze(root, source_file, source_run, worker, cpu, dataset=None):
    source = load_json(source_file)
    ledger, seal = full_run_source(source, source_run)
    entries = batch._entry_map(root, load_json(batch.check(root, source['definition']['plan'])))
    require(dataset is None or dataset in entries, 'unknown fixed batch dataset projection')
    cases, terminals = [], []
    for row, item in full_run_rows(source, ledger):
        if 'entry_kind' in row or (row['selection'], row['route']) not in ROUTES or dataset not in (None, row['dataset_id']):
            continue
        fields = {k: item[k] for k in BASIS}
        if row['status'] != 'verified':
            terminals.append({**fields, 'status': row['status'], 'reason': row['reason']})
            continue
        entry = entries[item['dataset_id']]
        units = project(item, entry, row['evidence'], source['build']['fixed_batch']['decoder']['recovery_id'])
        case = {**fields, 'configuration': item['input'], 'view': item['view'], 'source_file': entry['file'],
                'units': units, 'group_count': len(list(batch.groups(units))), 'decode_backends': ['default']}
        cases.append({**case, 'case_id': content_id(case)})
    wanted = {(d, *key) for d in (entries if dataset is None else [dataset]) for key in ROUTES}
    ids = [(c['dataset_id'], c['selection'], c['route']) for c in (*cases, *terminals)]
    require(cases and len(ids) == len(wanted) and set(ids) == wanted, 'fixed batch corpus decision population differs')
    frozen = load_json(batch.check(root, source['build']['lock']))
    require(frozen['build_id'] == source['build']['build_id'], 'fixed batch codec build identity differs')
    worker_ref = batch.relative(root, worker)
    modules = {plugin: frozen['plugins'][plugin] for plugin in ROUTES.values()}
    build = {'worker': worker_ref, 'plugins': modules, 'source_build_id': frozen['build_id']}
    runtime = plan_recovery(root, {**build, 'build_id': content_id(build)}, {p: {} for p in modules})
    body = {'schema': SCHEMA, 'source_plan': batch.relative(root, source_file), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'worker': worker_ref, 'runtime': runtime, 'cases': cases, 'excluded': terminals,
            'dataset_projection': dataset, 'environment': resource.environment(cpu), 'policy': POLICY, 'limits': batch.LIMITS,
            'launchers': batch.launcher_lock(), 'code': {p: digest(local_file(root, p)) for p in CODE}}
    return {**body, 'plan_content_id': content_id(body)}


def prepare(root, entry, case, work):
    require(entry['file'] == case['source_file'] and entry['canonical']['object_id'] == case['canonical_object_id'],
            'fixed batch original identity differs')
    paths = _stage_dataset(root, entry, work, case['view'])['paths']
    folder = work / 'groups'
    folder.mkdir()
    units = case['units']
    with ExitStack() as stack:
        streams = [stack.enter_context(p.open('rb')) for p in paths]
        for i, (a, b) in enumerate(batch.groups(units)):
            with (folder / batch.name(i)).open('xb') as out:
                for unit in units[a:b]:
                    f = streams[unit.get('column', 0)]
                    offset = unit['row_range'][0] * 8 if 'row_range' in unit else unit['byte_range'][0]
                    require(f.tell() == offset, 'fixed batch staging offset differs')
                    bits, schema = f.read(unit['input_bytes']), unit_schema(case['view'], unit['input_bytes'])
                    require(batch.br(bits) == unit['original'] and batch.br(schema) == unit['schema'],
                            'fixed batch staging bits or schema differ')
                    out.write(pack('<II', len(bits), len(schema)))
                    out.write(schema)
                    out.write(bits)
        require(all(not f.read(1) for f in streams), 'fixed batch staging has unread values')
    return batch.files(folder, case['group_count'])


def _sync(paths, root):
    folder = next(iter(paths.values())).parent
    while folder != root:
        require(folder.is_relative_to(root), 'fixed batch output escaped run root')
        folder = folder.parent
    parent = next(iter(paths.values())).parent
    directories = [parent, *(p for p in parent.parents if p == root or p.is_relative_to(root))]
    for path in (*paths.values(), *directories):
        flag = os.O_DIRECTORY if path in directories else 0
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | flag)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _plan_again(root, plan):
    worker = batch.check(root, plan['worker'])
    source = batch.check(root, plan['source_plan'])
    run = (root / plan['source_run']).resolve(strict=True)
    require(run.is_relative_to(root), 'fixed batch source run escaped workspace')
    require(freeze(root, source, run, worker, plan['environment']['cpu'], plan['dataset_projection']) == plan,
            'fixed batch plan does not recompute from sealed source')
    return load_json(source)


def _recompute(run, plan):
    for path, asset in plan['runtime']['files'].items():
        batch.check(run, {'path': 'runtime/' + path, **{k: asset[k] for k in ('bytes', 'sha256')}})
    env = load_json(local_file(run, 'environment.json'))
    cpu = plan['environment']['cpu']
    require(env['affinity'] == [cpu] and set(env) == {'affinity', 'before', 'after'}, 'fixed batch environment differs')
    cases, seen = [], set()
    with local_file(run, 'trials.jsonl').open('rb') as ledger:
        for case in plan['cases']:
            base = run / 'cases' / case['case_id']
            values = batch.files(base / 'raw', case['group_count'])
            timing._verify_staged(values, case)
            raw = batch.identities(values)
            wire = batch.verify_frames(batch.files(base / 'wire', case['group_count']), case['units'])
            by_slot = {'encode': [], 'default': []}
            for idx, t in enumerate(timing._schedule(case)):
                row = parse_json(ledger.readline(), 'fixed batch corpus trial')
                op = row['process']['operation']
                require(op in ('encode', 'decode') and load_json(local_file(base, f'logs/{idx}/{op}.stdout')) == row['native'] and
                        local_file(base, f'logs/{idx}/{op}.stderr').stat().st_size == 0, 'fixed batch trial log differs')
                timing._validate(case, cpu, t, row, raw, wire, seen)
                if t['phase'] == 'measured':
                    by_slot[t['slot']].append(row)
            cases.append(timing._summarize(case, by_slot))
        require(not ledger.read(1), 'fixed batch ledger has extra trials')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'], 'environment': env,
            'source_plan': plan['source_plan'], 'source_seal': plan['source_seal'], 'dataset_projection': plan['dataset_projection'],
            'verified_trials': len(seen), 'cases': cases, 'file_routes': dict(Counter(c['route'] for c in cases)),
            'excluded': plan['excluded'], 'policy': POLICY, **{k: False for k in ('timing_admitted', 'qualification_granted', 'stage_accepted')}}


def _seal(run, plan):
    names = ('plan.json', 'trials.jsonl', 'report.json', 'environment.json')
    body = {'schema': SCHEMA + '-seal', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'files': {n: batch.relative(run, local_file(run, n)) for n in names}}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    source = _plan_again(root, plan)
    require(output.is_relative_to(root), 'fixed batch output escaped workspace')
    cpu = plan['environment']['cpu']
    entries = batch._entry_map(root, load_json(batch.check(root, source['definition']['plan'])))
    with resource.reserve(), timing._pin(cpu):
        output.mkdir(parents=True, exist_ok=True)
        retained = sum(sum(u['original']['bytes'] + u['schema']['bytes'] + 8 + u['artifact']['bytes'] for u in c['units'])
                       for c in plan['cases'])
        largest = max(sum(u['original']['bytes'] + u['schema']['bytes'] + 8 + u['artifact']['bytes'] for u in c['units'])
                      for c in plan['cases'])
        require(shutil.disk_usage(output).free > retained + 3 * largest + (256 << 20), 'fixed batch free disk budget is too small')
        run = output / uuid4().hex
        run.mkdir()
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        write_new(run / 'plan.json', plan)
        env = {'affinity': [cpu], 'before': resource.observe(cpu)}
        seen = set()
        with (run / 'trials.jsonl').open('xb') as ledger:
            for case in plan['cases']:
                base = run / 'cases' / case['case_id']
                (base / 'logs').mkdir(parents=True)
                entry = entries[case['dataset_id']]
                with TemporaryDirectory(dir=base, prefix='anchor-') as tmp:
                    b = Path(tmp)
                    inputs = prepare(root, entry, case, b)
                    got, _, _ = batch.invoke(plan, run / 'runtime', case, 'encode', inputs, b / 'call')
                    raw, wire = batch.identities(inputs), batch.verify_frames(got, case['units'])
                    next(iter(inputs.values())).parent.rename(base / 'raw')
                    next(iter(got.values())).parent.rename(base / 'wire')
                fixed = batch.files(base / 'wire', case['group_count'])
                for i, t in enumerate(timing._schedule(case)):
                    with TemporaryDirectory(dir=base, prefix='trial-') as tmp:
                        b = Path(tmp)
                        tick = monotonic_ns()
                        encode = t['slot'] == 'encode'
                        inputs = prepare(root, entry, case, b) if encode else fixed
                        got, native, proc = batch.invoke(plan, run / 'runtime', case, t['slot'], inputs, b / 'call')
                        product = batch.verify_frames(got, case['units']) if encode else batch.identities(got)
                        require(product == (wire if encode else raw), 'fixed batch directional product differs')
                        sync = monotonic_ns()
                        _sync(got, run)
                        end = monotonic_ns()
                        log = base / 'logs' / str(i)
                        log.mkdir()
                        for p in (b / 'call').glob('*.std*'):
                            p.rename(log / p.name)
                        row = {**t, 'case_id': case['case_id'], 'native': native, 'process': proc, 'product': product,
                               'durable_wall_ns': end - tick, 'fsync_wall_ns': end - sync}
                        timing._validate(case, cpu, t, row, raw, wire, seen)
                        _line(ledger, row)
                print(f"verified {case['dataset_id']} {case['route']} ({len(case['units'])} frames)", flush=True)
        write_new(run / 'environment.json', {**env, 'after': resource.observe(cpu)})
        write_new(run / 'report.json', _recompute(run, plan))
        write_new(run / 'completion.json', _seal(run, plan))
    return run


def verify(root, run):
    plan = load_json(local_file(run, 'plan.json'))
    require(load_json(local_file(run, 'completion.json')) == _seal(run, plan), 'fixed batch corpus seal differs')
    _plan_again(root, plan)
    doc = _recompute(run, plan)
    require(doc == load_json(local_file(run, 'report.json')), 'fixed batch corpus report differs from replay')
    return doc
