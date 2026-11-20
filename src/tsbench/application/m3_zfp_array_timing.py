"""Run and audit grouped fixed-rate ZFP window clocks without erasing quality rejection."""
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
from random import Random
from struct import Struct
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns
from uuid import uuid4
import os
import shutil

import numpy as np

from ..assets import canonical_bytes, content_id, load_json, local_file, parse_json, require
from ..planner.m3_zfp import DRIVER
from ..planner.zfp_execution import THREAD_ENV
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource, zfp_array_grouped as launch
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import _stage
from .m3_zfp import ARRAY_LAYOUT, _quality, array_evidence, array_windows
from .m3_zfp_field_timing import _amounts, _dist, _stamp, _sync
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-zfp-array-timing-plan/1'
ROUTE = 'fixed-rate-array'
OPERATIONS = launch.OPERATIONS
WARMUPS, REPEATS, SEED = 1, 3, 147726
HEAD, WINDOW, RATES = Struct('<4sIII'), Struct('<III'), Struct('<II')
RAW, WIRE, VALUES = b'ZAR1', b'ZAG1', b'ZAV1'
ARCHIVE_ROLES = ('initial', 'updated')
PHASES = {'update': ('create', 'initial_export', 'point_range_flush', 'updated_export'),
          'reopen_initial': ('import', 'read_ranges'), 'reopen_updated': ('import', 'read_ranges')}
POLICY = {'warmups': WARMUPS, 'repeats': REPEATS, 'seed': SEED, 'thread_environment': THREAD_ENV,
          'layout': ARRAY_LAYOUT, 'scope': 'one isolated process per file/operation/repeat, one fresh array per original frozen window',
          'update': 'starts from original via verified parser, both snapshots compared byte-for-byte with r40 and fixed recovery fixtures',
          'reopen': 'one input mount of the fixed initial or updated ZAG1 only, validated in the original domain outside the worker',
          'native': 'per-window native array create/export/mutate/flush and import/range spans; spans exclude file I/O and destruction',
          'process': 'isolated process wall, wait4 CPU and RSS; no observed native thread count',
          'durable': 'complete update/reopen input path through output verification and file/directory fsync',
          'quality': 'all 23 declared files run; any rejected window preserves the whole-file rejection and suppresses coverage admission',
          'billing': 'updated ZAG1 alone recovers final state; initial is a separate validation artifact, wrapper and old shape cost disclosed',
          'reservation': resource.RESERVATION, 'exclusive_cpu': False, 'cache': 'inherited, not cold',
          'qualification_granted': False, 'stage_accepted': False, 'timing_admitted': False}


def _shape(c):
    return len(c['units']), c['columns'], c['rows']


def _extent(c, tag):
    wrapper = HEAD.size + len(c['units'])*WINDOW.size + (RATES.size if tag == WIRE else 0)
    return wrapper + (c['native_frame_bytes'] if tag == WIRE else c['logical_bytes'])


def _config(n):
    return {'rows': n, 'frame_bytes': 16*((n+3)//4), 'requested_rate': 18, 'effective_rate': 32}


def _population(source, ledger, entries):
    rng, cases = Random(SEED), []
    for row, item in full_run_rows(source, ledger):
        if row.get('entry_kind') is not None or (item['selection'], item['route']) != (31, ROUTE):
            continue
        ds, scope, ev = item['dataset_id'], item['input'], row['evidence']
        entry = entries[ds]
        cols, rows = entry['value_count'], entry['rows']
        sizes, geometry = scope['size_estimate'], list(array_windows(scope['array_contract'], cols, rows))
        require(row['status'] in ('verified', 'quality_rejected') and item['applicability'] == 'input_domain_matches' and
                ev['input_domain'] == 'bounded_balanced_windows' and ev['driver'] == DRIVER and not ev['timing_admitted'] and
                scope['representation'] == 'f64_columns' and scope['value_column_range'] == [0, cols] and ev['columns'] == cols and
                scope['row_ranges'] == [{'partition': 'full', 'start': 0, 'end': rows, 'object_id': entry['canonical']['object_id']}] and
                item['canonical_object_id'] == entry['canonical']['object_id'] and
                len(geometry) == len(ev['units']) == sizes['input_units'] and 0 < len(geometry) <= 25000,
                'r40 ZFP array work, scope, or source differs')
        native_bytes, meta_bytes, logical, rejected = 0, 0, 0, 0
        for (c, a, b), u in zip(geometry, ev['units'], strict=True):
            n = b-a
            config = _config(n)
            meta = _stamp(canonical_bytes({'format': 'zfp-array-rank1-v1', 'type': 'f64', 'shape': [n],
                                           'requested_rate': 18, 'effective_rate': 32}))
            require((u['column'], u['row_range'], u['logical_input_bytes']) == (c, [a,b], n*8) and u['config'] == config and
                    u['before_frame']['bytes'] == u['after_frame']['bytes'] == config['frame_bytes'] and
                    u['input']['bytes'] == u['restored']['bytes'] == u['exact_mutated_reference']['bytes'] == n*8 and
                    u['metadata'] == meta and u['artifact_bytes'] == config['frame_bytes'] + meta['bytes'] and
                    u['unchanged_native_blocks'] == (config['frame_bytes']-32)//16 and
                    u['quality_passed'] == (u['before']['accepted'] and u['after']['accepted']),
                    'r40 ZFP array window facts or quality verdict differ')
            native_bytes += config['frame_bytes']
            meta_bytes += meta['bytes']
            logical += n*8
            rejected += not u['quality_passed']
        require(logical == ev['input_bytes_one_pass'] == sizes['native_input_bytes_one_pass'] and
                meta_bytes + native_bytes == ev['artifact_bytes'] and rejected == ev['quality_rejected_units'] and
                (row['status'] == 'quality_rejected') == bool(rejected), 'r40 array status or accounting differs')
        body = {k: item[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation_config_id', 'canonical_object_id')}
        body.update(source=entry['file'], columns=cols, rows=rows, configuration=scope, status=row['status'], reason=row['reason'],
                    rejected_windows=rejected, units=ev['units'], logical_bytes=logical, native_frame_bytes=native_bytes,
                    old_json_shape_bytes=meta_bytes, order=[rng.sample(OPERATIONS, len(OPERATIONS)) for _ in range(WARMUPS+REPEATS)])
        require(max(_extent(body, tag) for tag in (RAW, WIRE, VALUES)) <= launch.FILE_CEILING, 'ZFP array exceeds launcher ceiling')
        cases.append({**body, 'case_id': content_id(body)})
    require(len(cases) == len(entries) == 23 and {x['dataset_id'] for x in cases} == set(entries), 'array plan must include every frozen file')
    return cases


def freeze(root, source_path, source_run, tool, cpu):
    source = load_json(source_path)
    ledger, seal = full_run_source(source, source_run)
    definition, binding = source['definition']['plan'], source['build']['zfp_corpus']
    entries = _entry_map(root, load_json(_file(root, definition)))
    _file(root, binding['dependency'])
    _file(root, binding['executable'])
    binary = _ref(root, tool)
    runtime = plan_recovery(root, {}, (), tools={launch.NAME: {k: binary[k] for k in ('path', 'sha256')}},
                            libraries=[binding['dependency']])
    require(runtime['tools'] == {launch.NAME: launch.TOOL} and
            launch.LIBRARY.split('/')[-1] in runtime['files'][launch.TOOL]['needed'], 'array tool does not bind frozen native library')
    code = ('src/tsbench/application/m3_zfp_array_timing.py', 'src/tsbench/supervisor/zfp_array_grouped.py',
            'src/tsbench/application/m3_zfp.py', 'src/tsbench/application/m3_zfp_field_timing.py',
            'src/tsbench/application/m3_sprintz_query.py', 'src/tsbench/corpus_ingress.py',
            'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py',
            'tools/m3_zfp_array_timing.py', 'tests/isolation/zfp_array_grouped_smoke.py',
            'native/measurement/zfp_array_grouped/main.cpp', 'native/measurement/zfp_array_grouped/CMakeLists.txt')
    body = {'schema': SCHEMA, 'source_plan': _ref(root, source_path), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'definition': definition, 'tool': binary, 'policy': POLICY, 'runtime': runtime,
            'environment': resource.environment(cpu), 'launchers': launcher_lock(), 'cases': _population(source, ledger, entries),
            'code': [_ref(root, local_file(root, p)) for p in code]}
    return {**body, 'plan_content_id': content_id(body)}


class Reader:
    def __init__(self, stream, c, tag):
        self.stream, self.c, self.tag = stream, c, tag
        self.hash, self.total = sha256(), 0
        require(self.take(HEAD.size) == HEAD.pack(tag, *_shape(c)), 'array capsule header or shape differs')
        if tag == WIRE:
            require(self.take(RATES.size) == RATES.pack(18, 32), 'array archive rate differs')

    def take(self, size):
        b = self.stream.read(size)
        require(len(b) == size, 'truncated ZFP array capsule')
        self.hash.update(b)
        self.total += size
        return b

    def window(self, u):
        col, (a,b) = u['column'], u['row_range']
        require(self.take(WINDOW.size) == WINDOW.pack(col,a,b-a), 'array capsule window coordinates differ')
        return self.take(u['before_frame']['bytes'] if self.tag == WIRE else u['logical_input_bytes'])

    def finish(self):
        require(self.stream.read(1) == b'' and self.total == _extent(self.c, self.tag), 'trailing array bytes or mismatched extent')
        return {'bytes': self.total, 'sha256': self.hash.hexdigest()}


def _staging(root, c, entry, path):
    require(entry['file'] == c['source'], 'ZFP array staging source identity differs')
    paths = _stage(root, entry, path / 'columns')
    digest_ = sha256()
    dest = path / 'windows.zar'
    with dest.open('xb') as out:
        def append(b):
            out.write(b)
            digest_.update(b)
        append(HEAD.pack(RAW, *_shape(c)))
        i = 0
        for col, column in enumerate(paths):
            with column.open('rb') as f:
                while i < len(c['units']) and c['units'][i]['column'] == col:
                    u = c['units'][i]
                    lo, hi = u['row_range']
                    f.seek(lo*8)
                    data = f.read((hi-lo)*8)
                    require(_stamp(data) == u['input'], 'array staged source window differs from r40')
                    append(WINDOW.pack(col,lo,hi-lo))
                    append(data)
                    i += 1
            column.unlink()
        require(i == len(c['units']), 'array staged source does not match window denominator')
    require(dest.stat().st_size == _extent(c, RAW), 'packed source array extent differs')
    return dest, {'bytes': dest.stat().st_size, 'sha256': digest_.hexdigest()}


def _archives(c, paths):
    with ExitStack() as stack:
        readers = [Reader(stack.enter_context(paths[k].open('rb')), c, WIRE) for k in ARCHIVE_ROLES]
        for u in c['units']:
            initial, updated = (r.window(u) for r in readers)
            require(_stamp(initial) == u['before_frame'] and _stamp(updated) == u['after_frame'] and
                    initial[32:] == updated[32:], 'array native frames or untouched blocks differ from r40')
        return {k: r.finish() for k,r in zip(ARCHIVE_ROLES, readers, strict=True)}


def _quality_proof(c, role):
    key = 'before' if role == 'initial' else 'after'
    facts = [u[key] for u in c['units']]
    return {'compared_windows': len(facts), 'rejected_windows': sum(not x['accepted'] for x in facts), 'details_id': content_id(facts)}


def _reopened(c, role, source, path):
    with source.open('rb') as s, path.open('rb') as f:
        raw, restored = Reader(s,c,RAW), Reader(f,c,VALUES)
        for u in c['units']:
            x, y = raw.window(u), restored.window(u)
            require(_stamp(x) == u['input'], 'original-domain validator received non-frozen array windows')
            expected, result = np.frombuffer(x, dtype='<f8'), np.frombuffer(y, dtype='<f8')
            if role == 'updated':
                expected = expected.copy()
                expected[1] = expected[-1]
                expected[3:7] = np.frombuffer(x, dtype='<f8')[:4]
                require(_stamp(y) == u['restored'] and _stamp(expected.tobytes()) == u['exact_mutated_reference'],
                        'ZFP updated restore or exact mutated reference differs from r40')
            require(_quality(expected, result) == u['before' if role == 'initial' else 'after'],
                    'array reopened original-domain quality differs from r40')
        raw.finish()
        return restored.finish(), _quality_proof(c, role)


def _check_pair(c, raw_path, archives, reopened):
    with ExitStack() as stack:
        def reader(path, tag):
            return Reader(stack.enter_context(path.open('rb')), c, tag)
        raw, before, after, old, new = (reader(raw_path, RAW), reader(archives['initial'], WIRE), reader(archives['updated'], WIRE),
                                        reader(reopened['initial'], VALUES), reader(reopened['updated'], VALUES))
        for u in c['units']:
            verdict = array_evidence(*(r.window(u) for r in (raw,before,after,old,new)))
            require(verdict == {k: u[k] for k in verdict}, 'array two-side untouched-byte or quality reconciliation differs')
        for r in (raw,before,after,old,new):
            r.finish()


def _native(c, op, stdout):
    phases = PHASES[op]
    totals = {name: {'wall_ns': 0, 'process_cpu_ns': 0} for name in phases}
    with stdout.open(encoding='utf-8') as f:
        for u in c['units']:
            row = parse_json(next(f, ''), 'ZFP array native window')
            want = {'column': u['column'], 'row_start': u['row_range'][0], **u['config']}
            require(set(row) == set(want) | set(phases) and all(row[k] == v for k,v in want.items()),
                    'ZFP array worker geometry, rate or active phases differ')
            for name, accum in totals.items():
                observed = row[name]
                require(set(observed) == set(accum) and type(observed['wall_ns']) is int and observed['wall_ns'] > 0 and
                        type(observed['process_cpu_ns']) is int and observed['process_cpu_ns'] >= 0, 'ZFP array call clocks differ')
                for k in accum:
                    accum[k] += observed[k]
        require(next(f, None) is None, 'extra ZFP array native window evidence')
    return totals


def _call(run, plan, c, place, op, source):
    is_update = op == 'update'
    place.mkdir()
    wanted = _extent(c, WIRE if is_update else VALUES)
    out, proc = launch.run(run/'runtime', plan['runtime'], place, source, op, input_bytes=_extent(c, RAW if is_update else WIRE),
                           output_bytes=wanted, windows=len(c['units']))
    logs = [place/f'native.{n}' for n in ('stdout','stderr')]
    require(proc['status'] == 'completed', f"ZFP array {op}: {proc['status']}; see {logs[1]}")
    names = ARCHIVE_ROLES if is_update else ('values',)
    outputs = {n: out/n for n in names}
    require(set(out.iterdir()) == set(outputs.values()) and all(p.is_file() and p.stat().st_size == wanted for p in outputs.values()) and
            logs[1].stat().st_size == 0, 'ZFP array isolated product inventory differs')
    return outputs, proc, logs


def _prepare(root, run, plan, c, entry, ref_dir):
    place = run/'cases'/c['case_id']
    fixed = place/'fixed'
    fixed.mkdir(parents=True)
    source, raw = _staging(root, c, entry, ref_dir)
    frames, proc, _ = _call(run, plan, c, ref_dir/'update', 'update', source)
    require(proc['input_mounts'] == {'windows': raw}, 'array fixed update input differs')
    facts = _archives(c, frames)
    archives, recovered, recovery_facts = {}, {}, {}
    for role in ARCHIVE_ROLES:
        archive = archives[role] = fixed/f'{role}.zag'
        frames[role].rename(archive)
        outputs, proc, _ = _call(run, plan, c, ref_dir/f'reopen-{role}', f'reopen_{role}', archive)
        require(proc['input_mounts'] == {role: facts[role]}, 'array fixed recovery was not detached from raw windows')
        path = recovered[role] = outputs['values']
        result, quality = _reopened(c, role, source, path)
        recovery_facts[role] = {'product': result, 'quality': quality}
        _sync(archive)
    _check_pair(c, source, archives, recovered)
    for p in (fixed, place):
        _sync(p)
    return source, {'raw': raw, 'archives': {k: {'path': p.relative_to(run).as_posix(), **facts[k]} for k,p in archives.items()},
                    'recovery': recovery_facts}


def _schedule(c):
    for r, ops in enumerate(c['order']):
        for op in ops:
            yield {'op': op, 'repeat': r, 'phase': 'warmup' if r < WARMUPS else 'measure', 'case_id': c['case_id'],
                   'path': f"cases/{c['case_id']}/{r:02d}-{op}"}


def _trial(root, run, plan, c, entry, ref_source, setup, slot):
    op, place = slot['op'], run/slot['path']
    ingress, quality, a,b = None, None, monotonic_ns(), process_time_ns()
    if op == 'update':
        with TemporaryDirectory(dir=place.parent, prefix='array-source-') as tmp:
            source, raw = _staging(root, c, entry, Path(tmp))
            ingress = monotonic_ns()-a
            require(raw == setup['raw'], 'restaged array windows differ')
            outputs, proc, logs = _call(run, plan, c, place, op, source)
        products = _archives(c, outputs)
    else:
        role = op.removeprefix('reopen_')
        source = local_file(run, setup['archives'][role]['path'])
        outputs, proc, logs = _call(run, plan, c, place, op, source)
        facts, quality = _reopened(c, role, ref_source, outputs['values'])
        products = {'values': facts}
    clocks = _native(c, op, logs[0])
    for p in (*outputs.values(), place/'out', place):
        _sync(p)
    wall,cpu = monotonic_ns()-a, process_time_ns()-b
    return {**slot, 'source_original': c['source'] if op == 'update' else None, 'ingress_wall_ns': ingress,
            'process': proc, 'native': clocks, 'products': products, 'quality': quality, 'durable_wall_ns': wall,
            'controller_cpu_ns': cpu, 'quality_status': c['status'], 'logs': [_ref(run,p) for p in logs]}, outputs


def _check_trial(run, c, setup, slot, row, sessions):
    require(set(row) == set(slot) | {'source_original', 'ingress_wall_ns', 'process', 'native', 'products', 'quality', 'durable_wall_ns',
                                    'controller_cpu_ns', 'quality_status', 'logs'} and all(row[k] == v for k,v in slot.items()) and
            row['quality_status'] == c['status'], 'array trial or status differs from frozen schedule')
    op = slot['op']
    a = {k: _amounts(v) for k,v in setup['archives'].items()}
    ingress = row['ingress_wall_ns']
    if op == 'update':
        mounts, products, quality = {'windows': setup['raw']}, a, None
        require(type(ingress) is int and ingress > 0 and row['source_original'] == c['source'], 'array update must stage original')
    else:
        role = op.removeprefix('reopen_')
        proof = setup['recovery'][role]
        mounts, products, quality = {role: a[role]}, {'values': proof['product']}, proof['quality']
        require(ingress is None and row['source_original'] is None, 'array reopen must not mount original')
    proc, phases = row['process'], row['native']
    usage = proc['child_usage']
    require(proc['operation'] == 'native' and proc['status'] == 'completed' and proc['returncode'] == 0 and not proc['reason'] and
            type(proc['pid']) is int and proc['pid'] > 0 and isinstance(proc['session_id'], str) and proc['session_id'] not in sessions and
            proc['input_mounts'] == mounts and row['products'] == products and row['quality'] == quality and
            type(proc['process_wall_ns']) is int and 0 < sum(x['wall_ns'] for x in phases.values()) <= proc['process_wall_ns'] and
            type(row['durable_wall_ns']) is int and (ingress or 0) + proc['process_wall_ns'] <= row['durable_wall_ns'] and
            type(row['controller_cpu_ns']) is int and row['controller_cpu_ns'] > 0 and
            set(usage) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and all(type(x) is int and x >= 0 for x in usage.values()) and
            usage['maxrss_bytes'] > 0, 'array trial does not prove native work, clock boundary or detached recovery')
    sessions.add(proc['session_id'])
    require([x['path'] for x in row['logs']] == [f"{slot['path']}/native.{n}" for n in ('stdout','stderr')] and
            row['logs'][1]['bytes'] == 0, 'array trial log path differs')
    stdout, _ = (_file(run, r) for r in row['logs'])
    require(_native(c, op, stdout) == phases, 'array native phase clocks do not recompute')


def _summary(c, setup, rows):
    wire = _extent(c, WIRE)
    r = {k: c[k] for k in ('case_id', 'dataset_id', 'route', 'canonical_object_id', 'operation_config_id', 'work_item_id',
                          'status', 'reason', 'configuration', 'rejected_windows')}
    r['window_count'] = len(c['units'])
    r['billing'] = {'logical_window_bytes': c['logical_bytes'], 'native_final_frame_bytes': c['native_frame_bytes'],
                    'z_ag1_wrapping_bytes_per_state': wire-c['native_frame_bytes'], 'final_recovery_bytes': wire,
                    'separate_initial_validation_bytes': wire, 'both_distinct_archives_bytes': 2*wire,
                    'r40_final_shape_sidecar_bytes': c['old_json_shape_bytes'], 'logical_over_final': c['logical_bytes']/wire}
    r['quality_by_state'] = {k: v['quality'] for k,v in setup['recovery'].items()}
    directions = {}
    for op in OPERATIONS:
        xs = [x for x in rows if x['op'] == op and x['phase'] == 'measure']
        require(len(xs) == REPEATS, 'array measured repeat denominator differs')
        native_wall = [sum(s['wall_ns'] for s in x['native'].values()) for x in xs]
        durable_wall = [x['durable_wall_ns'] for x in xs]
        directions[op] = {'samples': len(xs), 'native_phases': {p: {k: _dist([x['native'][p][k] for x in xs])
                            for k in ('wall_ns','process_cpu_ns')} for p in PHASES[op]},
                          'isolated_process_wall_ns': _dist([x['process']['process_wall_ns'] for x in xs]),
                          'controller_cpu_ns': _dist([x['controller_cpu_ns'] for x in xs]),
                          'resources': {k: _dist([x['process']['child_usage'][k] for x in xs]) for k in xs[0]['process']['child_usage']},
                          'native_sequential_phase_wall_ns': _dist(native_wall), 'durable_wall_ns': _dist(durable_wall),
                          'ingress_wall_ns': _dist([x['ingress_wall_ns'] for x in xs]) if op == 'update' else None,
                          'logical_work_mib_s': {kind: _dist([c['logical_bytes']*1e9 / ((1<<20)*t) for t in durations])
                                                 for kind,durations in (('native',native_wall), ('durable',durable_wall))},
                          'backend': 'frozen_c11_zfp_rank1_f64_array', 'actual_thread_count': None,
                          'thread_count_unavailable_reason': 'measured process constrained to one CPU; no TID-native array hook'}
    r['directions' if c['status'] == 'verified' else 'quality_rejected_direction_diagnostics'] = directions
    return r


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and len(plan['cases']) == 23, 'array plan contract differs')
    setups, env = [load_json(local_file(run, f'{n}.json')) for n in ('setup','environment')]
    require(set(setups) == {c['case_id'] for c in plan['cases']} and set(env) == {'before','after'} and
            all(x['affinity'] == [plan['environment']['cpu']] for x in env.values()), 'array setup or affinity differs')
    rng, summaries, sessions = Random(SEED), [], set()
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for c in plan['cases']:
            _identity(c, 'case_id')
            require(c['order'] == [rng.sample(OPERATIONS, len(OPERATIONS)) for _ in range(WARMUPS+REPEATS)], 'array trial randomization differs')
            s = setups[c['case_id']]
            require(set(s) == {'raw','archives','recovery'} and s['raw']['bytes'] == _extent(c,RAW) and
                    set(s['archives']) == set(s['recovery']) == set(ARCHIVE_ROLES), 'array fixed evidence inventory differs')
            paths = {}
            for role, ref in s['archives'].items():
                require(ref['path'] == f"cases/{c['case_id']}/fixed/{role}.zag" and
                        s['recovery'][role]['quality'] == _quality_proof(c, role) and
                        s['recovery'][role]['product']['bytes'] == _extent(c,VALUES), 'array fixed recovery denominator differs')
                paths[role] = local_file(run, ref['path'])
            require(_archives(c, paths) == {k: _amounts(ref) for k,ref in s['archives'].items()}, 'array fixed archives do not recompute')
            rows = []
            for slot in _schedule(c):
                row = parse_json(next(f,''), 'ZFP array trial')
                _check_trial(run, c, s, slot, row, sessions)
                rows.append(row)
            summaries.append(_summary(c,s,rows))
        require(next(f,None) is None, 'excess ZFP array trial rows')
    eligible = sum(c['status'] == 'verified' for c in summaries)
    return {'schema': 'bmk.m3-zfp-array-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'source_seal': plan['source_seal'], 'policy': POLICY, 'environment': env, 'cases': summaries,
            'reconciled_trials': len(sessions), 'verified_file_scope_trials': eligible*len(OPERATIONS)*(WARMUPS+REPEATS),
            'file_status': dict(Counter(c['status'] for c in summaries)), 'window_count': sum(c['window_count'] for c in summaries),
            'rejected_windows': sum(c['rejected_windows'] for c in summaries), 'qualification_granted': False,
            'stage_accepted': False, 'timing_admitted': False}


def _seal(run):
    body = {'schema': 'bmk.m3-zfp-array-timing-seal/1', 'run_id': run.name, 'files': [
        _ref(run, local_file(run, n)) for n in ('plan.json','setup.json','environment.json','trials.jsonl','report.json')]}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    require(output.is_absolute() and output.is_relative_to(root), 'array results must be project-local')
    cpu = plan['environment']['cpu']
    with resource.reserve():
        require(freeze(root, _file(root,plan['source_plan']), _folder(root,plan['source_run']), _file(root,plan['tool']), cpu) == plan,
                'grouped array frozen plan differs')
        entries = _entry_map(root, load_json(_file(root,plan['definition'])))
        output.mkdir(parents=True, exist_ok=True)
        require(shutil.disk_usage(output).free >= 2*(1<<30), 'insufficient array diagnostic disk reserve')
        with _affinity([cpu]):
            run = output/uuid4().hex
            run.mkdir()
            write_new(run/'plan.json', plan)
            stage_recovery(root, run, plan['runtime'], directory='runtime')
            def observe():
                return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshot': resource.observe(cpu)}
            before, setups, sessions = observe(),{},set()
            with (run/'trials.jsonl').open('xb') as f:
                for c in plan['cases']:
                    entry = entries[c['dataset_id']]
                    with TemporaryDirectory(prefix='prepared-',dir=run) as tmp:
                        source, setup = _prepare(root,run,plan,c,entry,Path(tmp))
                        setups[c['case_id']] = setup
                        for slot in _schedule(c):
                            row, outputs = _trial(root,run,plan,c,entry,source,setup,slot)
                            _check_trial(run,c,setup,slot,row,sessions)
                            _line(f,row)
                            for p in outputs.values():
                                p.unlink()
                            (run/slot['path']/'out').rmdir()
            write_new(run/'setup.json', setups)
            write_new(run/'environment.json', {'before': before,'after': observe()})
            write_new(run/'report.json', _report(run,plan))
            write_new(run/'completion.json', _seal(run))
            _sync(run)
    return run


def verify(run):
    root = Path(__file__).resolve().parents[3]
    require(load_json(local_file(run,'completion.json')) == _seal(run), 'ZFP array diagnostic run seal differs')
    plan = load_json(local_file(run,'plan.json'))
    source = load_json(_file(root,plan['source_plan']))
    ledger, seal = full_run_source(source,_folder(root,plan['source_run']))
    require(plan['source_seal'] == seal and plan['definition'] == source['definition']['plan'] and
            plan['cases'] == _population(source,ledger,_entry_map(root,load_json(_file(root,plan['definition'])))),
            'ZFP array diagnostic geometry or quality status differs from r40')
    for name,asset in plan['runtime']['files'].items():
        _file(run,{'path': f'runtime/{name}', **asset})
    report = _report(run,plan)
    require(report == load_json(local_file(run,'report.json')), 'grouped array report differs on recomputation')
    return report
