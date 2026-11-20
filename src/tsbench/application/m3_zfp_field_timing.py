"""ZFP r40 reversible-field clocks and separate whole-field block-work observation."""
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from random import Random
from statistics import median
from struct import Struct
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns
from uuid import uuid4
import os
import shutil

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_zfp import DRIVER
from ..planner.zfp_execution import THREAD_ENV
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource, zfp_field_grouped as launch
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import _stage
from .m3_zfp import PROFILES, _field_record
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-zfp-field-timing-plan/1'
LANES = {'baseline': ('field-baseline', 'serial'), 'modes': ('field-modes', 'serial'),
         **{f'openmp-{p}': ('openmp-encode', p) for p in PROFILES}}
ROUTES = tuple(dict.fromkeys(r for r, _ in LANES.values()))
OBSERVED = tuple(k for k, (r, _) in LANES.items() if r == 'openmp-encode')
DIRECTIONS = ('encode', 'decode')
WARMUPS, REPEATS, SEED = 1, 3, 117593
HEAD, LENGTH = Struct('<4sII'), Struct('<I')
POLICY = {'warmups': WARMUPS, 'repeats': REPEATS, 'order_seed': SEED, 'thread_environment': THREAD_ENV,
          'population': 'three reversible-field routes; other mode and fixed-rate-array obligations are separate',
          'affinity': 'same two distinct physical cores on one NUMA node in every arm; kernel and runtime placement not controlled',
          'active_threads': 'separate interposed same-work encode/decode coverage per column; no interposed sample contributes timing',
          'fixed': 'one per file and lane, every native frame checked against r40; detached recovery sees no source',
          'scope': 'one full-file child per lane/direction/repeat; fresh context per complete value column',
          'api': 'sum of native API call walls and process CPU per field, no parallel wall summation, excludes context and I/O',
          'durable': 'fresh read of verified original or fixed ZFG1 through product validation and file plus directory fsync',
          'cache': 'inherited, no cold-cache claim', 'reservation': resource.RESERVATION, 'exclusive_cpu': False,
          'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


def _facts(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _stamp(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def _amounts(ref):
    return {k: ref[k] for k in ('bytes', 'sha256')}


def _cpus(cpus):
    require(len(cpus) == len(set(cpus)) == 2 and cpus == sorted(cpus), 'supply two distinct CPU IDs in increasing order')
    a, b = values = [resource.environment(cpu) for cpu in cpus]
    require(a['package_id'] == b['package_id'] and a['core_id'] != b['core_id'] and
            len(a['cpu_numa_nodes']) == 1 and a['cpu_numa_nodes'] == b['cpu_numa_nodes'],
            'ZFP thread comparison needs two different physical cores on the same NUMA node')
    return values


def _population(source, ledger, entries):
    by_file = defaultdict(dict)
    for row, item in full_run_rows(source, ledger):
        if row.get('entry_kind') is not None or item['selection'] != 31 or item['route'] not in ROUTES:
            continue
        ds, route = item['dataset_id'], item['route']
        entry, e, scope = entries[ds], row['evidence'], item['input']
        rows, cols = entry['rows'], entry['value_count']
        logical = rows * cols * 8
        require(row['status'] == 'verified' and route not in by_file[ds] and item['applicability'] == 'input_domain_matches' and
                e['driver'] == DRIVER and e['quality_rejected_units'] == 0 and not e['timing_admitted'] and
                e['input_domain'] == 'full_reversible_columns' and e['columns'] == len(e['units']) == cols and
                e['input_bytes_one_pass'] == logical == scope['size_estimate']['native_input_bytes_one_pass'] and
                scope['size_estimate']['input_units'] == cols and scope['representation'] == 'f64_columns' and
                scope['full_extent_of_file_rows_and_value_columns'] and scope['value_column_range'] == [0, cols] and
                scope['slice_extent']['max_per_unit'] is None and item['canonical_object_id'] == entry['canonical']['object_id'] and
                scope['row_ranges'] == [{'partition': 'full', 'start': 0, 'end': rows, 'object_id': item['canonical_object_id']}] and
                0 < rows <= 131072 and 0 < cols <= 4096 and logical <= launch.FILE_CEILING, 'r40 ZFP field population differs')
        profiles = tuple(p for r, p in LANES.values() if r == route)
        payloads = {p: [] for p in profiles}
        raw_units = []
        metadata = _stamp(canonical_bytes({'format': 'zfp-raw-reversible-v1', 'type': 'f64', 'shape': [rows]}))
        for i, u in enumerate(e['units']):
            raw = u['same_field']
            require((u['column'], u['row_range'], u['logical_input_bytes']) == (i, [0, rows], rows*8) and raw['bytes'] == rows*8 and
                    set(u['profiles']) == set(profiles), 'r40 ZFP field geometry or profiles differ')
            raw_units.append(raw)
            for p in profiles:
                anchor = u['profiles'][p]
                wire = anchor['frame']
                n = wire['bytes']
                require(0 < n <= 4 << 20 and n % 8 == 0 and anchor['encode'] == _field_record(rows, n, p) and
                        anchor['restore'] == _field_record(rows, n, 'serial') and anchor['restored'] == raw and
                        anchor['metadata'] == metadata and anchor['artifact_bytes'] == n + metadata['bytes'],
                        'r40 ZFP native field bytes, configurations or restoration differ')
                payloads[p].append(wire)
        require(e['artifact_bytes'] == {p: sum(f['bytes'] for f in fs) + cols*metadata['bytes'] for p,fs in payloads.items()},
                'r40 ZFP frame billing differs')
        variant = {k: item[k] for k in ('work_item_id', 'route', 'canonical_object_id', 'operation_config_id')}
        variant['configuration'] = scope
        by_file[ds][route] = variant, raw_units, payloads, metadata
    require(len(by_file) == len(entries) == 23 and set(by_file) == set(entries), 'missing frozen ZFP field files')
    out, rng = [], Random(SEED)
    for ds, entry in entries.items():
        variations = by_file[ds]
        require(set(variations) == set(ROUTES), 'missing frozen ZFP field route')
        _, raw, _, metadata = variations[ROUTES[0]]
        require(all(v[1] == raw and v[3] == metadata for v in variations.values()), 'ZFP routes do not use identical full columns')
        lanes = {k: variations[route][2][p] for k, (route,p) in LANES.items()}
        cols, rows = entry['value_count'], entry['rows']
        require(all(HEAD.size + cols*LENGTH.size + sum(f['bytes'] for f in fs) <= launch.FILE_CEILING for fs in lanes.values()),
                'ZFP full archive exceeds launch ceiling')
        body = {'dataset_id': ds, 'source': entry['file'], 'columns': cols, 'rows': rows, 'raw_units': raw,
                'old_metadata_bytes_per_column': metadata['bytes'], 'lanes': lanes, 'variants': {r: v[0] for r,v in variations.items()},
                'order': [rng.sample(tuple(LANES), len(LANES)) for _ in range(WARMUPS+REPEATS)]}
        out.append({**body, 'case_id': content_id(body)})
    return out


def freeze(root, plan_path, source_run, timing, observer, cpus):
    source = load_json(plan_path)
    ledger, seal = full_run_source(source, source_run)
    definition = source['definition']['plan']
    entries = _entry_map(root, load_json(_file(root, definition)))
    binding = source['build']['zfp_corpus']
    for name in ('executable', 'dependency'):
        _file(root, binding[name])
    tools = {k: _ref(root, p) for k,p in (('timing', timing), ('observer', observer))}
    require(tools['timing']['sha256'] != tools['observer']['sha256'], 'observer and timed build must differ')
    runtime = plan_recovery(root, {}, (), tools={k: {n: v[n] for n in ('path', 'sha256')} for k,v in tools.items()},
                            libraries=[binding['dependency']])
    require(runtime['tools'] == launch.TOOLS and all(launch.LIBRARY.split('/')[-1] in runtime['files'][x]['needed']
            for x in launch.TOOLS.values()), 'ZFP tools do not share the frozen native library')
    code = ('src/tsbench/application/m3_zfp_field_timing.py', 'src/tsbench/supervisor/zfp_field_grouped.py',
            'src/tsbench/application/m3_zfp.py', 'src/tsbench/application/m3_sprintz_query.py',
            'src/tsbench/corpus_ingress.py', 'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py',
            'tools/m3_zfp_field_timing.py', 'tests/isolation/zfp_field_grouped_smoke.py',
            *(f'native/measurement/zfp_field_grouped/{n}' for n in ('main.cpp', 'observe.cpp', 'CMakeLists.txt')))
    body = {'schema': SCHEMA, 'source_plan': _ref(root, plan_path), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'definition': definition, 'tools': tools, 'runtime': runtime, 'policy': POLICY,
            'environment': _cpus(cpus), 'launchers': launcher_lock(), 'cases': _population(source, ledger, entries),
            'code': [_ref(root, local_file(root, f)) for f in code]}
    return {**body, 'plan_content_id': content_id(body)}


def _verify_raw(path, c):
    h = sha256()
    with path.open('rb') as f:
        for ref in c['raw_units']:
            value = f.read(ref['bytes'])
            require(_stamp(value) == ref, 'ZFP recovered column differs from r40')
            h.update(value)
        require(not f.read(1), 'ZFP recovered columns have trailing bytes')
    return {'bytes': c['columns']*c['rows']*8, 'sha256': h.hexdigest()}


def _stage_raw(root, c, entry, folder):
    require(c['source'] == entry['file'], 'ZFP original identity differs')
    paths = _stage(root, entry, folder / 'columns')
    h, output = sha256(), folder / 'raw'
    with output.open('xb') as f:
        for p, expected in zip(paths, c['raw_units'], strict=True):
            b = p.read_bytes()
            require(_stamp(b) == expected, 'ZFP staged column differs from r40')
            f.write(b)
            h.update(b)
            p.unlink()
    return output, {'bytes': output.stat().st_size, 'sha256': h.hexdigest()}


def _archive_bytes(c, lane):
    return HEAD.size + c['columns']*LENGTH.size + sum(f['bytes'] for f in c['lanes'][lane])


def _verify_archive(path, c, lane):
    h = sha256()
    with path.open('rb') as f:
        head = f.read(HEAD.size)
        require(head == HEAD.pack(b'ZFG1', c['columns'], c['rows']), 'ZFG1 geometry differs')
        h.update(head)
        for ref in c['lanes'][lane]:
            n = f.read(LENGTH.size)
            require(n == LENGTH.pack(ref['bytes']), 'ZFG1 frame size differs from r40')
            b = f.read(ref['bytes'])
            require(_stamp(b) == ref, 'ZFG1 native bits differ from r40')
            h.update(n)
            h.update(b)
        require(not f.read(1), 'trailing bytes after final ZFP frame')
    return {'bytes': _archive_bytes(c, lane), 'sha256': h.hexdigest()}


def _native(c, lane, op, stdout, arm):
    profile = LANES[lane][1] if op == 'encode' else 'serial'
    counts, wall, cpu = Counter(), 0, 0
    full, tail = divmod(c['rows'], 4)
    with stdout.open(encoding='utf-8') as f:
        for col, frame in enumerate(c['lanes'][lane]):
            o = parse_json(next(f, ''), 'ZFP native field row')
            want = {'column': col, **_field_record(c['rows'], frame['bytes'], profile)}
            extra = {'call_wall_ns', 'call_cpu_ns'} if arm == 'timing' else {'caller_tid', 'block_workers'}
            require(set(o) == set(want) | extra and all(o[k] == v for k,v in want.items()), 'ZFP field native configuration differs')
            if arm == 'timing':
                require(type(o['call_wall_ns']) is int and o['call_wall_ns'] > 0 and type(o['call_cpu_ns']) is int and o['call_cpu_ns'] >= 0,
                        'ZFP field operation clocks missing')
                wall += o['call_wall_ns']
                cpu += o['call_cpu_ns']
            else:
                workers = o['block_workers']
                require(isinstance(workers, list) and 1 <= len(workers) <= want['configured_threads'] and
                        type(o['caller_tid']) is int and o['caller_tid'] > 0 and all(set(w) == {'tid', 'full', 'tail'} and
                        type(w['tid']) is int and w['tid'] > 0 and type(w['full']) is int and type(w['tail']) is int and
                        w['full'] >= 0 and 0 <= w['tail'] <= 1 and w['full'] + w['tail'] > 0 for w in workers) and
                        len({w['tid'] for w in workers}) == len(workers) and sum(w['full'] for w in workers) == full and
                        sum(w['tail'] for w in workers) == bool(tail) and
                        (profile == 'omp2' or workers[0]['tid'] == o['caller_tid']), 'native ZFP full/tail worker coverage differs')
                counts[str(len(workers))] += 1
        require(next(f, None) is None, 'extra ZFP column observation')
    return ({'api_wall_ns': wall, 'api_process_cpu_ns': cpu, 'configured_threads': PROFILES[profile][1]}
            if arm == 'timing' else {'whole_columns_by_participating_threads': dict(counts),
                                     'full_blocks_per_column': full, 'tail_blocks_per_column': int(bool(tail)),
                                     'configured_threads': PROFILES[profile][1]})


def _sync(path):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _call(run, plan, c, lane, op, place, source, arm):
    place.mkdir()
    n = _archive_bytes(c, lane) if op == 'encode' else c['columns']*c['rows']*8
    profile = LANES[lane][1] if op == 'encode' else 'serial'
    product, proc = launch.run(run / 'runtime', plan['runtime'], place, source, op, profile, c['columns'], c['rows'], n, arm)
    logs = [place / f'native.{k}' for k in ('stdout', 'stderr')]
    require(proc['status'] == 'completed', f"ZFP {arm} {lane}/{op}: {proc['status']}; see {logs[1]}")
    require(logs[1].stat().st_size == 0 and product.is_file() and list(product.parent.iterdir()) == [product] and
            product.stat().st_size == n, 'ZFP grouped product inventory differs')
    return product, proc, logs


def _done(out, c, lane, op):
    return _verify_archive(out, c, lane) if op == 'encode' else _verify_raw(out, c)


def _mount(raw, wire, op):
    return {'columns': raw} if op == 'encode' else {'archive': _amounts(wire)}


def _expected_product(raw, wire, op):
    return _amounts(wire) if op == 'encode' else raw


def _result(run, place, lane, op, arm, obs, proc, logs, facts):
    return {'arm': arm, 'lane': lane, 'op': op, 'path': place.relative_to(run).as_posix(),
            'native': obs, 'process': proc, 'logs': [_ref(run, p) for p in logs], 'product': facts}


def _prepare(root, run, plan, c, entry):
    place = run / 'cases' / c['case_id']
    fixed = place / 'fixed'
    observed = place / 'observer'
    fixed.mkdir(parents=True)
    observed.mkdir()
    anchors, observations = {}, {}
    with TemporaryDirectory(dir=place, prefix='reference-') as temp:
        w = Path(temp)
        source, raw = _stage_raw(root, c, entry, w)
        for lane in LANES:
            out, proc, logs = _call(run, plan, c, lane, 'encode', w / f'{lane}-anchor', source, 'timing')
            require(proc['input_mounts'] == {'columns': raw}, 'ZFP anchor used the wrong canonical columns')
            _native(c, lane, 'encode', logs[0], 'timing')
            target = fixed / f'{lane}.zfg'
            facts = _verify_archive(out, c, lane)
            out.rename(target)
            anchors[lane] = {'path': target.relative_to(run).as_posix(), **facts}
            _sync(target)
        for lane in OBSERVED:
            archive = local_file(run, anchors[lane]['path'])
            for op in DIRECTIONS:
                path = observed / f'{lane}-{op}'
                out, proc, logs = _call(run, plan, c, lane, op, path, source if op == 'encode' else archive, 'observer')
                facts = _done(out, c, lane, op)
                require(proc['input_mounts'] == _mount(raw, anchors[lane], op) and facts == _expected_product(raw, anchors[lane], op),
                        'instrumented ZFP run does not do the same full work')
                obs = _native(c, lane, op, logs[0], 'observer')
                observations[f'{lane}-{op}'] = _result(run, path, lane, op, 'observer', obs, proc, logs, facts)
                out.unlink()
                out.parent.rmdir()
    for p in (fixed, observed, place):
        _sync(p)
    return {'raw': raw, 'anchors': anchors, 'observations': observations}


def _schedule(c):
    for r, lanes in enumerate(c['order']):
        for op in DIRECTIONS:
            for lane in lanes:
                yield {'lane': lane, 'op': op, 'repeat': r, 'phase': 'warmup' if r < WARMUPS else 'measure',
                       'path': f"cases/{c['case_id']}/{r:02d}-{lane}-{op}", 'case_id': c['case_id']}


def _trial(root, run, plan, c, entry, setup, slot):
    lane, op, place = slot['lane'], slot['op'], run / slot['path']
    a, b = monotonic_ns(), process_time_ns()
    ingress = None
    raw = setup['raw']
    archive = setup['anchors'][lane]
    if op == 'encode':
        with TemporaryDirectory(dir=place.parent, prefix='stage-') as tmp:
            source, proof = _stage_raw(root, c, entry, Path(tmp))
            ingress = monotonic_ns()-a
            require(proof == raw, 'ZFP restaged original columns differ')
            out, proc, logs = _call(run, plan, c, lane, op, place, source, 'timing')
    else:
        out, proc, logs = _call(run, plan, c, lane, op, place, local_file(run, archive['path']), 'timing')
    facts = _done(out, c, lane, op)
    native = _native(c, lane, op, logs[0], 'timing')
    for p in (out, out.parent, place):
        _sync(p)
    wall, cpu = monotonic_ns()-a, process_time_ns()-b
    return {**slot, **_result(run, place, lane, op, 'timing', native, proc, logs, facts), 'ingress_wall_ns': ingress,
            'source_original': c['source'] if op == 'encode' else None, 'durable_wall_ns': wall, 'controller_cpu_ns': cpu}, out


def _check(run, c, setup, row, arm, sessions, *, slot=None, lane=None, op=None):
    keys = {'arm', 'lane', 'op', 'path', 'native', 'process', 'logs', 'product'}
    if arm == 'timing':
        lane, op, path = slot['lane'], slot['op'], slot['path']
        require(set(row) == keys | set(slot) | {'ingress_wall_ns', 'source_original', 'durable_wall_ns', 'controller_cpu_ns'} and
                all(row[k] == v for k,v in slot.items()), 'ZFP trial order differs from plan')
    else:
        path = f"cases/{c['case_id']}/observer/{lane}-{op}"
        require(set(row) == keys and (row['lane'], row['op']) == (lane, op), 'ZFP observer coordinates differ')
    require(row['arm'] == arm and row['path'] == path, 'ZFP observation/timing arms mixed')
    raw, wire = setup['raw'], setup['anchors'][lane]
    proc, native = row['process'], row['native']
    require(proc['status'] == 'completed' and proc['operation'] == 'native' and proc['returncode'] == 0 and not proc['reason'] and
            type(proc['pid']) is int and proc['pid'] > 0 and isinstance(proc['session_id'], str) and proc['session_id'] not in sessions and
            proc['input_mounts'] == _mount(raw, wire, op) and row['product'] == _expected_product(raw, wire, op),
            'ZFP result isolation, detached output or fresh process differs')
    sessions.add(proc['session_id'])
    require([ref['path'] for ref in row['logs']] == [f'{path}/native.{k}' for k in ('stdout', 'stderr')] and
            row['logs'][1]['bytes'] == 0, 'ZFP native log coordinates differ')
    stdout, _ = (_file(run, ref) for ref in row['logs'])
    require(native == _native(c, lane, op, stdout, arm), 'ZFP native observation differs on recomputation')
    if arm == 'timing':
        t, usage = row['ingress_wall_ns'], proc['child_usage']
        require(row['source_original'] == (c['source'] if op == 'encode' else None) and
                (type(t) is int and t > 0 if op == 'encode' else t is None) and type(proc['process_wall_ns']) is int and
                native['api_wall_ns'] <= proc['process_wall_ns'] and type(row['durable_wall_ns']) is int and
                (t or 0) + proc['process_wall_ns'] <= row['durable_wall_ns'] and type(row['controller_cpu_ns']) is int and
                row['controller_cpu_ns'] > 0 and set(usage) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and
                all(type(x) is int and x >= 0 for x in usage.values()) and usage['maxrss_bytes'] > 0, 'invalid ZFP timing boundary')
    else:
        require(not ({'child_usage', 'process_wall_ns'} & set(proc)), 'instrumented operation must not publish a timing sample')


def _dist(values):
    return {'min': min(values), 'median': median(values), 'max': max(values)}


def _summary(c, setup, rows):
    result = {}
    logical = setup['raw']['bytes']
    for lane, (route, profile) in LANES.items():
        wire = setup['anchors'][lane]['bytes']
        native_n = sum(x['bytes'] for x in c['lanes'][lane])
        entry = {**c['variants'][route], 'encoder_profile': profile, 'decoder_profile': 'serial', 'billing': {
            'complete_zfg1_bytes': wire, 'native_frame_bytes': native_n, 'zfg1_wrapper_bytes': wire - native_n,
            'r40_separate_json_shape_bytes': c['old_metadata_bytes_per_column']*c['columns'],
            'logical_bytes': logical, 'logical_over_complete': logical/wire}}
        for op in DIRECTIONS:
            xs = [x for x in rows if (x['lane'], x['op'], x['phase']) == (lane, op, 'measure')]
            require(len(xs) == REPEATS, 'ZFP measurement count differs')
            nwall, dwall = [x['native']['api_wall_ns'] for x in xs], [x['durable_wall_ns'] for x in xs]
            entry[op] = {'samples': len(xs), 'native_api_wall_ns': _dist(nwall), 'durable_wall_ns': _dist(dwall),
                         'native_process_cpu_ns': _dist([x['native']['api_process_cpu_ns'] for x in xs]),
                         'controller_cpu_ns': _dist([x['controller_cpu_ns'] for x in xs]),
                         'process_wall_ns': _dist([x['process']['process_wall_ns'] for x in xs]),
                         'ingress_wall_ns': _dist([x['ingress_wall_ns'] for x in xs]) if op == 'encode' else None,
                         'child_usage': {k: _dist([x['process']['child_usage'][k] for x in xs]) for k in xs[0]['process']['child_usage']},
                         'logical_mib_s': {k: _dist([logical*1e9 / ((1 << 20)*t) for t in durations])
                                           for k,durations in (('native', nwall), ('durable', dwall))},
                         'configured_threads': xs[0]['native']['configured_threads'], 'timed_trial_block_thread_count': None,
                         'separate_block_observation': setup['observations'].get(f'{lane}-{op}', {}).get('native')}
        result[lane] = entry
    return result


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and len(plan['cases']) == 23, 'ZFP diagnostic plan contract differs')
    setups, env = (load_json(local_file(run, f'{n}.json')) for n in ('setup', 'environment'))
    require(set(setups) == {c['case_id'] for c in plan['cases']} and set(env) == {'before', 'after'} and
            all(e['affinity'] == [x['cpu'] for x in plan['environment']] for e in env.values()), 'ZFP setup or resource environment differs')
    rng, timed, seen, result = Random(SEED), set(), set(), []
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for c in plan['cases']:
            _identity(c, 'case_id')
            require(c['order'] == [rng.sample(tuple(LANES), len(LANES)) for _ in range(WARMUPS+REPEATS)], 'ZFP matched schedule differs')
            setup = setups[c['case_id']]
            require(set(setup) == {'raw', 'anchors', 'observations'} and setup['raw']['bytes'] == c['columns']*c['rows']*8 and
                    set(setup['anchors']) == set(LANES) and set(setup['observations']) == {f'{k}-{op}' for k in OBSERVED for op in DIRECTIONS},
                    'ZFP fixed records or observer population differs')
            for lane, ref in setup['anchors'].items():
                require(ref['path'] == f"cases/{c['case_id']}/fixed/{lane}.zfg" and
                        _verify_archive(local_file(run, ref['path']), c, lane) == _amounts(ref), 'ZFP fixed frame failed recomputation')
            for lane in OBSERVED:
                for op in DIRECTIONS:
                    _check(run, c, setup, setup['observations'][f'{lane}-{op}'], 'observer', seen, lane=lane, op=op)
            rows = []
            for slot in _schedule(c):
                row = parse_json(next(f, ''), 'ZFP field trial')
                _check(run, c, setup, row, 'timing', timed, slot=slot)
                rows.append(row)
            result.append({'case_id': c['case_id'], 'dataset_id': c['dataset_id'], 'whole_columns': c['columns'],
                           'rows_per_column': c['rows'], 'lanes': _summary(c, setup, rows)})
        require(next(f, None) is None, 'extra ZFP field trial rows')
    require(not timed.intersection(seen), 'timed and instrumented process identities overlap')
    return {'schema': 'bmk.m3-zfp-field-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'source_seal': plan['source_seal'], 'policy': POLICY, 'environment': env, 'cases': result,
            'verified_trials': len(timed), 'separate_observer_operations': len(seen),
            'file_routes': dict(Counter(r for c in plan['cases'] for r in c['variants'])),
            'qualification_granted': False, 'stage_accepted': False, 'timing_admitted': False}


def _seal(run):
    body = {'schema': 'bmk.m3-zfp-field-timing-seal/1', 'run_id': run.name, 'files': [
        _ref(run, local_file(run, n)) for n in ('plan.json', 'setup.json', 'environment.json', 'trials.jsonl', 'report.json')]}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    require(output.is_absolute() and output.is_relative_to(root), 'ZFP diagnostic output must be project-local')
    cpus = [p['cpu'] for p in plan['environment']]
    with resource.reserve():
        require(freeze(root, _file(root, plan['source_plan']), _folder(root, plan['source_run']),
                       *(_file(root, plan['tools'][arm]) for arm in ('timing', 'observer')), cpus) == plan, 'frozen ZFP plan differs')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        output.mkdir(parents=True, exist_ok=True)
        require(shutil.disk_usage(output).free >= 5*(1 << 30), 'insufficient storage for the frozen full-file ZFP archive population')
        with _affinity(cpus):
            run = output / uuid4().hex
            run.mkdir()
            write_new(run / 'plan.json', plan)
            stage_recovery(root, run, plan['runtime'], directory='runtime')
            def observe():
                return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshots': [resource.observe(n) for n in cpus]}
            before, setups, sessions = observe(), {}, set()
            with (run / 'trials.jsonl').open('xb') as f:
                for c in plan['cases']:
                    entry = entries[c['dataset_id']]
                    setup = setups[c['case_id']] = _prepare(root, run, plan, c, entry)
                    for slot in _schedule(c):
                        row, product = _trial(root, run, plan, c, entry, setup, slot)
                        _check(run, c, setup, row, 'timing', sessions, slot=slot)
                        _line(f, row)
                        product.unlink()
                        product.parent.rmdir()
            write_new(run / 'setup.json', setups)
            write_new(run / 'environment.json', {'before': before, 'after': observe()})
            write_new(run / 'report.json', _report(run, plan))
            write_new(run / 'completion.json', _seal(run))
            _sync(run)
    return run


def verify(run):
    root = Path(__file__).resolve().parents[3]
    require(load_json(local_file(run, 'completion.json')) == _seal(run), 'ZFP field diagnostic seal differs')
    plan = load_json(local_file(run, 'plan.json'))
    source = load_json(_file(root, plan['source_plan']))
    ledger, seal = full_run_source(source, _folder(root, plan['source_run']))
    require(plan['source_seal'] == seal and plan['definition'] == source['definition']['plan'] and
            plan['cases'] == _population(source, ledger, _entry_map(root, load_json(_file(root, plan['definition'])))),
            'ZFP measured inputs differ from sealed r40')
    for name, asset in plan['runtime']['files'].items():
        _file(run, {'path': f'runtime/{name}', **asset})
    report = _report(run, plan)
    require(report == load_json(local_file(run, 'report.json')), 'ZFP field report differs on recomputation')
    return report
