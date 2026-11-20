"""Whole-file Sprintz FIRE and Huff0 FEC1 repeats using exact sealed ABI frames."""
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
import json
import os
from pathlib import Path
from random import Random
import struct
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..corpus_ingress import read_batches
from ..planner.m3_huff0_fec1 import KEY as FEC1
from ..planner.m3_sprintz import BATCH as FIRE
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_worker, launcher_lock
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import ROWS, _stage as columns
from .m3_sprintz_timing import check, ref, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-abi-whole-corpus-repeats/1'
CODECS = {FIRE: 'sprintz-fire', FEC1: 'huff0-reference'}
LIMITS = {'address_space_bytes': 384 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 60}
GROUP_BYTES = 6 << 20
ROUNDS = 3
OPS = ('encode', 'decode')
BASIS = 'one_fresh_isolated_process_per_whole_dataset_direction_round'
CODE = ('native/measurement/abi_corpus/main.cpp', 'native/measurement/abi_corpus/CMakeLists.txt',
        'native/runtime/plugin_loader.cpp', 'native/runtime/plugin_loader.hpp', 'include/tsbench/plugin_abi.h',
        'src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py',
        'src/tsbench/recovery.py', 'src/tsbench/corpus_ingress.py', 'src/tsbench/application/m3_sealed_ledger.py',
        'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/application/m3_sprintz_timing.py',
        'src/tsbench/application/m3_abi_corpus_timing.py', 'tools/m3_abi_corpus_timing.py')


def br(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def schedule():
    rng = Random(20261120)
    return [{'operation': op, 'round': i, 'phase': 'warmup' if i == 0 else 'measured'}
            for i in range(ROUNDS + 1) for op in rng.sample(OPS, len(OPS))]


def schema(entry, plugin, unit):
    if plugin == 'sprintz-fire':
        return json.dumps({'role': 'value', 'dtype': 'u16', 'layout': 'f64-le-limbs-row-major', 'lanes': 4,
                           'rows': unit['row_end'] - unit['row_start']}, sort_keys=True, separators=(',', ':')).encode()
    return json.dumps({'role': 'bytes', 'dtype': 'u8', 'rows': entry['rows']}, separators=(',', ':')).encode()


def project(proof, entry, item, plugin):
    if plugin == 'sprintz-fire':
        records = proof['units']
        units = [{'column': u['column'], 'row_start': u['row_start'], 'row_end': u['row_end'],
                  'original': {'bytes': u['raw_bytes'], 'sha256': u['restored_sha256']},
                  'artifact': {'bytes': u['artifact_bytes'], 'sha256': u['frame_sha256']},
                  'cost': {'abi_envelope': u['abi_envelope_bytes'], 'sfb1': u['sfb1_bytes']},
                  'schema': {'sha256': u['schema_sha256'], 'bytes': u['abi_envelope_bytes'] - 32}} for u in records]
        expected = [(col, a, min(entry['rows'], a + ROWS)) for col in range(entry['value_count'])
                    for a in range(0, entry['rows'], ROWS)]
        require(expected == [(u['column'], u['row_start'], u['row_end']) for u in units] and
                all(u['original']['bytes'] == (u['row_end']-u['row_start'])*8 for u in units), 'FIRE scope differs')
        artifact_sum = proof['artifact_bytes']
    else:
        units = []
        offset = 0
        for g in proof['groups']:
            require(g['offset'] == offset, 'FEC1 source group offset differs')
            for u in g['frames']:
                cost = Counter({'abi_header': 32, 'schema': proof['schema']['bytes'], 'fec_header': 24,
                                'record_headers': 13 * len(u['records'])})
                modes = Counter()
                for r in u['records']:
                    cost[r['mode'] + '_body'] += r['body_bytes']
                    modes[r['mode']] += 1
                n = u['decoded']['bytes']
                units.append({'value_bytes': [offset, offset+n], 'original': u['decoded'], 'artifact': u['frame'],
                              'schema': proof['schema'], 'cost': dict(cost), 'modes': dict(modes)})
                offset += n
        require(offset == proof['input']['bytes'] and all(u['original']['bytes'] == min(65536, offset-u['value_bytes'][0])
                for u in units), 'FEC1 source byte extent differs')
        artifact_sum = proof['complete_bytes']
    extent = item['input']
    logical = entry['rows'] * entry['value_count'] * 8
    require(extent['full_extent_of_file_rows_and_value_columns'] and item['canonical_object_id'] == entry['canonical']['object_id'] and
            len(units) == extent['size_estimate']['input_units'] and
            sum(u['original']['bytes'] for u in units) == logical == extent['size_estimate']['native_input_bytes_one_pass'] and
            sum(u['artifact']['bytes'] for u in units) == artifact_sum and
            all(sum(u['cost'].values()) == u['artifact']['bytes'] and br(schema(entry, plugin, u)) == u['schema'] for u in units),
            'ABI units, schema, or billing differ from frozen extent')
    return units


def groups(units):
    first, raw, wire = 0, 0, 0
    for i, u in enumerate(units):
        added = u['original']['bytes'] + u['schema']['bytes'] + 8
        charged = u['artifact']['bytes']
        require(0 < added <= GROUP_BYTES and 0 < charged <= GROUP_BYTES, 'unit exceeds ABI diagnostic group budget')
        if max(raw + added, wire + charged) > GROUP_BYTES:
            yield (first, i)
            first, raw, wire = i, 0, 0
        raw += added
        wire += charged
    if raw:
        yield (first, len(units))


def freeze(root, source, run, worker, cpu):
    plan = load_json(source)
    ledger, seal = full_run_source(plan, run)
    entries = _entry_map(root, load_json(check(root, plan['definition']['plan'])))
    cases, terminals = [], []
    for row, item in full_run_rows(plan, ledger):
        key = row.get('selection'), row.get('route')
        if item is None or 'entry_kind' in row or key not in CODECS:
            continue
        plugin = CODECS[key]
        fields = {k: row[k] for k in ('dataset_id', 'work_item_id', 'route', 'selection', 'operation')}
        if row['status'] != 'verified':
            terminals.append({**fields, 'status': row['status'], 'reason': row['reason']})
            continue
        entry = entries[row['dataset_id']]
        proof = row['evidence']
        units = project(proof, entry, item, plugin)
        body = {**fields, 'plugin': plugin, 'source_file': entry['file'], 'configuration': item['input'],
                'canonical_object_id': item['canonical_object_id'], 'units': units}
        if key == FIRE:
            sample = proof['retained_sample']
            require(sample['observation'] == proof['units'][0] and {k: sample[k] for k in ('sha256', 'bytes')} == units[0]['artifact'],
                    'FIRE historical sample not bound to its first frame')
            body['historical_first_frame'] = relative(root, check(run, sample))
        cases.append({**body, 'case_id': content_id(body)})
    require(cases and {r['plugin'] for r in cases} == set(CODECS.values()), 'both ABI routes must have verified corpus input')
    target = relative(root, worker)
    frozen_build = load_json(check(root, plan['build']['lock']))
    require(frozen_build['build_id'] == plan['build']['build_id'], 'ABI build lock identity differs')
    modules = {v: frozen_build['plugins'][v] for v in CODECS.values()}
    build = {'worker': target, 'plugins': modules, 'build_id': content_id({'worker': target, 'plugins': modules})}
    methods = {p: {'plugin': p, 'options': {}} for p in modules}
    body = {'schema': SCHEMA, 'source_plan': relative(root, source), 'source_run': run.relative_to(root).as_posix(),
            'source_seal': seal, 'worker': target, 'runtime': plan_recovery(root, build, methods),
            'launchers': launcher_lock(), 'limits': LIMITS, 'case_order': 'frozen_ledger_order', 'group_bytes': GROUP_BYTES,
            'schedule': schedule(), 'env': resource.environment(cpu), 'cases': cases, 'excluded': terminals,
            'code': {name: digest(local_file(root, name)) for name in CODE}}
    return {**body, 'plan_id': content_id(body)}


def name(i):
    return f'g{i:05d}.bin'


def files(folder, n):
    paths = {name(i): local_file(folder, name(i)) for i in range(n)}
    require(set(p.name for p in folder.iterdir()) == paths.keys(), 'ABI group output file set differs')
    return paths


def prepare_values(root, entry, case, folder):
    """Read the locked original to EOF, then verify every staged unit independently of decode."""
    plugin, units = case['plugin'], case['units']
    if plugin == 'sprintz-fire':
        paths = columns(root, entry, folder / 'columns')
    else:
        p = folder / 'interleaved'
        with p.open('xb') as stream:
            for batch in read_batches(root, entry):
                stream.write(batch.values)
        require(ref(p) == {'sha256': entry['canonical']['values_sha256'], 'bytes': entry['rows'] * entry['value_count'] * 8},
                'FEC1 canonical values differ')
        paths = [p]
    out = folder / 'values'
    out.mkdir()
    with ExitStack() as stack:
        inputs = [stack.enter_context(p.open('rb')) for p in paths]
        for g, (a, b) in enumerate(groups(units)):
            with (out / name(g)).open('xb') as stream:
                for u in units[a:b]:
                    bits = inputs[u.get('column', 0)].read(u['original']['bytes'])
                    s = schema(entry, plugin, u)
                    require(br(bits) == u['original'] and br(s) == u['schema'], 'ABI original unit differs from sealed ledger')
                    stream.write(struct.pack('<II', len(bits), len(s)))
                    stream.write(s)
                    stream.write(bits)
        require(all(not f.read(1) for f in inputs), 'ABI staging left unread values')
    return files(out, g+1)


def identities(paths):
    return {n: ref(p) for n, p in paths.items()}


def verify_frames(paths, units):
    for index, (a, b) in enumerate(groups(units)):
        with paths[name(index)].open('rb') as stream:
            for u in units[a:b]:
                require(br(stream.read(u['artifact']['bytes'])) == u['artifact'], 'reconstructed ABI frame differs from sealed ledger')
            require(not stream.read(1), 'reconstructed ABI group has trailing bytes')
    return identities(paths)


def invoke(run, plan, case, t, inputs, work):
    op, plugin = t['operation'], case['plugin']
    work.mkdir()
    tick = monotonic_ns()
    out, proc = invoke_isolated_worker(run / 'runtime', plan['runtime'], {'plugin': plugin, 'options': {}}, LIMITS,
                                       work, work, op, inputs, ['/inputs', '/out', str(len(inputs))], lambda: False,
                                       observe=True, file_ceiling=LIMITS['file_bytes'])
    error = (work / (op + '.stderr')).read_text()
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and not error,
            f"{case['dataset_id']} {plugin} {op}: {proc['status']}: {error[:400]}")
    paths = files(out, len(inputs))
    output = identities(paths)
    obs = load_json(work / (op + '.stdout'))
    return paths, {'case_id': case['case_id'], **t, 'output': output, 'process': proc, 'native': obs,
                   'staged_supervision_and_verification_wall_ns': monotonic_ns() - tick}


def expected_modes(units):
    return Counter((u['modes'].get('raw', 0), u['modes'].get('rle', 0), u['modes'].get('huffman', 0)) for u in units)


def validate(plan, case, t, row, mounts, outputs, seen):
    op, units, plugin = t['operation'], case['units'], case['plugin']
    native, proc = row['native'], row['process']
    live_ns = native['abi_wall_ns'] + native['context_create_wall_ns']
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()) and
            proc['status'] == 'completed' and proc['operation'] == op and proc['returncode'] == 0 and not proc['reason'] and
            isinstance(proc['session_id'], str) and proc['session_id'] not in seen and proc['session_id'] and
            type(proc['pid']) is int and proc['pid'] > 0 and proc['input_mounts'] == mounts and row['output'] == outputs and
            min(native['abi_wall_ns'], native['context_create_wall_ns']) > 0 and
            live_ns <= proc['process_wall_ns'] <= row['staged_supervision_and_verification_wall_ns'] and
            proc['child_usage']['maxrss_bytes'] > 0 and native['cpu_endpoints'] == [plan['env']['cpu']] * 2 and
            native['frames'] == len(units) and native['groups'] == len(mounts) == len(outputs) == len(list(groups(units))) and
            native['raw_bytes'] == sum(u['original']['bytes'] for u in units) and
            native['archive_bytes'] == sum(u['artifact']['bytes'] for u in units), 'ABI trial coverage, resource or outputs differ')
    observed = Counter()
    for r in native['execution_census']:
        d, n = r['info'], r['count']
        require(type(n) is int and n > 0 and d['threads'] == 1 and d['operation'] == op, 'ABI backend observation differs')
        if plugin == 'sprintz-fire':
            require(d == {'operation': op, 'threads': 1, 'path': 'generic_rle', 'algorithm': 'fire', 'lanes': 4},
                    'FIRE ABI profile differs from frozen options')
            observed[()] += n
        else:
            mode = tuple(d[k] for k in ('raw_blocks', 'rle_blocks', 'huffman_blocks'))
            backend = d['backend']
            require(d['mode'] == 'batch' and d['blocks'] == sum(mode) and d['fallback'] is bool(mode[0]) and
                    (backend == 'huff0-reference-encode' if op == 'encode' else
                     backend in ('runtime-bmi2', 'runtime-portable', 'portable') if mode[-1] else backend == 'no-huffman-decode'),
                    'FEC1 backend or raw fallback metadata differs')
            observed[mode] += n
    require(observed == (Counter({(): len(units)}) if plugin == 'sprintz-fire' else expected_modes(units)),
            'ABI route observation census fails the sealed unit population')
    seen.add(proc['session_id'])


def historical_case(case):
    return {**case, 'units': case['units'][:1]}


def _counts(case, raw):
    # The packed input metadata are transport, not codec logical or charged bytes.
    units = case['units']
    for i, (a, b) in enumerate(groups(units)):
        v = units[a:b]
        require(raw[name(i)]['bytes'] == sum(8 + u['original']['bytes'] + u['schema']['bytes'] for u in v),
                'ABI staging transport extent differs')


def summarize(case, rows):
    directions = {}
    for op in OPS:
        population = [r for r in rows if r['phase'] == 'measured' and r['operation'] == op]
        require(len(population) == ROUNDS, 'ABI repeats lack measured rounds')
        clocks = {k: [r['native'][k] for r in population] for k in ('abi_wall_ns', 'context_create_wall_ns')}
        clocks['process_wall_ns'] = [r['process']['process_wall_ns'] for r in population]
        clocks['staged_supervision_and_verification_wall_ns'] = [r['staged_supervision_and_verification_wall_ns'] for r in population]
        clocks.update({k: [r['process']['child_usage'][k] for r in population] for k in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes')})
        n = population[0]['native']['raw_bytes']
        census = population[0]['native']['execution_census']
        require(all(r['native']['execution_census'] == census for r in population), 'ABI execution profile changed across repeats')
        directions[op] = {'repeat_distributions': {k: {**distribution(v), 'sample_basis': BASIS} for k, v in clocks.items()},
                          'logical_mib_per_second': {clock: n * ROUNDS * 1e9 / (sum(clocks[clock]) * (1 << 20))
                              for clock in ('abi_wall_ns', 'process_wall_ns', 'staged_supervision_and_verification_wall_ns')},
                          'execution_census': census}
    cost = Counter()
    for u in case['units']:
        cost.update(u['cost'])
    n = sum(u['original']['bytes'] for u in case['units'])
    return {k: case[k] for k in ('dataset_id', 'work_item_id', 'plugin', 'route', 'canonical_object_id', 'configuration')} | {
        'file_scope': 'all_rows_all_value_columns_only', 'native_frames': len(case['units']), 'byte_cost': dict(cost),
        'logical_bytes': n, 'artifact_bytes': sum(cost.values()), 'ratio': n / sum(cost.values()), 'directions': directions}


def verify(run):
    plan, seal = (load_json(local_file(run, n)) for n in ('plan.json', 'completion.json'))
    require(plan['schema'] == SCHEMA and plan['plan_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_id'}) and
            plan['group_bytes'] == GROUP_BYTES and plan['limits'] == LIMITS and plan['schedule'] == schedule() and
            seal['schema'] == SCHEMA + '-seal' and seal['run_id'] == run.name and seal['plan_id'] == plan['plan_id'] and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json', 'environment.json', 'trials.jsonl'}, 'ABI timing plan or seal differs')
    for asset in seal['files'].values():
        check(run, asset)
    for path, asset in plan['runtime']['files'].items():
        check(run, {'path': 'runtime/' + path, 'bytes': asset['bytes'], 'sha256': asset['sha256']})
    env = load_json(run / 'environment.json')
    require(env['affinity'] == [plan['env']['cpu']], 'ABI selected CPU affinity differs')
    result, seen, recovered = [], set(), []
    with (run / 'trials.jsonl').open('rb') as stream:
        take = lambda: parse_json(stream.readline(), 'ABI corpus trial')
        for case in plan['cases']:
            require(case['case_id'] == content_id({k: v for k, v in case.items() if k != 'case_id'}), 'ABI case identity differs')
            setup = take()
            raw = setup['process']['input_mounts']
            wire = setup['output']
            _counts(case, raw)
            for i, (a, b) in enumerate(groups(case['units'])):
                require(wire[name(i)]['bytes'] == sum(u['artifact']['bytes'] for u in case['units'][a:b]),
                        'ABI reconstructed group sizes differ')
            validate(plan, case, {'operation': 'encode', 'phase': 'reconstruct', 'round': -1}, setup, raw, wire, seen)
            if 'historical_first_frame' in case:
                row = take()
                mounted = {name(0): {k: case['historical_first_frame'][k] for k in ('bytes', 'sha256')}}
                require(row['historical_recovered'] == case['units'][0]['original'] and
                        row['historical_schema'] == case['units'][0]['schema'], 'FIRE historical restore metadata differs')
                _counts(historical_case(case), row['output'])
                validate(plan, historical_case(case), {'operation': 'decode', 'phase': 'historical_sample', 'round': -1},
                         row, mounted, row['output'], seen)
                recovered.append(case['historical_first_frame'])
            rows = []
            for t in plan['schedule']:
                row = take()
                m, o = (raw, wire) if t['operation'] == 'encode' else (wire, raw)
                validate(plan, case, t, row, m, o, seen)
                rows.append(row)
            result.append(summarize(case, rows))
        require(not stream.read(1), 'ABI corpus has extra attempts')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'seal_id': seal['seal_id'], 'source_seal': plan['source_seal'],
            'environment': env, 'verified_calls': len(seen), 'results': result, 'excluded': plan['excluded'],
            'historical_sprintz_samples_replayed': recovered,
            'not_measured': {'end_to_end_source_path': 'ingress, staging and durable output are not timed',
                             'native_cpu_rss': 'wait4 reports the supervised process, not ABI-internal resource use',
                             'system_exclusivity': 'only cooperative lock and process CPU affinity observed'},
            'clock': 'one_wall_interval_per_public_ABI_call_summed_across_serial_frames_context_creation_separate',
            'qualification_granted': False, 'timing_admitted': False, 'stage_accepted': False}


def execute(root, plan, output):
    src = check(root, plan['source_plan'])
    src_run = (root / plan['source_run']).resolve(strict=True)
    worker = check(root, plan['worker'])
    cpu = plan['env']['cpu']
    require(src_run.is_relative_to(root) and output.is_relative_to(root) and freeze(root, src, src_run, worker, cpu) == plan,
            'ABI plan differs from current sealed run, build, or resource identity')
    entries = _entry_map(root, load_json(check(root, load_json(src)['definition']['plan'])))
    output.mkdir(parents=True, exist_ok=True)
    with resource.reserve():
        run = output / uuid4().hex
        run.mkdir()
        print(f'run={run}', flush=True)
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        saved = os.sched_getaffinity(0)
        seen = set()
        try:
            os.sched_setaffinity(0, {cpu})
            env = {'affinity': sorted(os.sched_getaffinity(0)), 'before': resource.observe(cpu)}
            with (run / 'trials.jsonl').open('xb') as ledger:
                for case in plan['cases']:
                    entry = entries[case['dataset_id']]
                    with TemporaryDirectory(prefix='abi-', dir=run) as directory:
                        base = Path(directory)
                        raw = prepare_values(root, entry, case, base)
                        verified_raw = identities(raw)
                        _counts(case, verified_raw)
                        t = {'operation': 'encode', 'phase': 'reconstruct', 'round': -1}
                        wire, trial = invoke(run, plan, case, t, raw, base / 'archive')
                        verified_wire = verify_frames(wire, case['units'])
                        validate(plan, case, t, trial, verified_raw, verified_wire, seen)
                        _line(ledger, trial)
                        if 'historical_first_frame' in case:
                            t = {'operation': 'decode', 'phase': 'historical_sample', 'round': -1}
                            historical = {name(0): check(root, case['historical_first_frame'])}
                            got, row = invoke(run, plan, historical_case(case), t, historical, base / 'historical')
                            staged = got[name(0)].read_bytes()
                            n, s = struct.unpack_from('<II', staged)
                            row['historical_schema'] = br(staged[8:8+s])
                            row['historical_recovered'] = br(staged[8+s:])
                            unit = case['units'][0]
                            require(n+s+8 == len(staged) and row['historical_schema'] == unit['schema'] and
                                    row['historical_recovered'] == unit['original'], 'FIRE first retained frame recovery differs')
                            validate(plan, historical_case(case), t, row, identities(historical), row['output'], seen)
                            _line(ledger, row)
                        for i, t in enumerate(plan['schedule']):
                            inp, m, o = ((raw, verified_raw, verified_wire) if t['operation'] == 'encode' else
                                         (wire, verified_wire, verified_raw))
                            with TemporaryDirectory(prefix='trial-', dir=base) as scratch:
                                _, trial = invoke(run, plan, case, t, inp, Path(scratch) / 'work')
                                validate(plan, case, t, trial, m, o, seen)
                                _line(ledger, trial)
                    print(f"verified {case['dataset_id']} {case['route']} ({len(case['units'])} frames)", flush=True)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0, saved)
        write_new(run / 'environment.json', env)
        sealed = {'schema': SCHEMA + '-seal', 'run_id': run.name, 'plan_id': plan['plan_id'],
                  'files': {n: relative(run, run / n) for n in ('plan.json', 'trials.jsonl', 'environment.json')}}
        write_new(run / 'completion.json', {**sealed, 'seal_id': content_id(sealed)})
    write_new(run / 'report.json', verify(run))
    return run
