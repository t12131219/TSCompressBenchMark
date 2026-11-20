"""Whole-file repeats of frozen pcodec page-group work, without per-group launches."""
from collections import Counter, defaultdict
from contextlib import ExitStack
from hashlib import sha256
import os
from pathlib import Path
from random import Random
import shutil
from statistics import median
from struct import Struct
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns
from uuid import uuid4

import numpy as np

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..corpus_ingress import read_batches
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import pcodec_pages_grouped as launch, timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_pcodec_page_timing import _frame, _semantic
from .m3_pcodec_pages import CHUNK_ROWS
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-pcodec-grouped-timing-plan/1'
SEAL = 'bmk.m3-pcodec-grouped-timing-seal/1'
LANES = {'source': 'source-pages', 'native': 'native-pages'}
DIRECTIONS = ('encode', 'decode')
HEAD, SIZE = Struct('<8sII'), Struct('<I')
RAW, FRAME = b'PGF1RAW\x00', b'PGF1PAGE'
WARMUPS, ROUNDS, SEED = 1, 3, 195202
POLICY = {'warmups': WARMUPS, 'rounds': ROUNDS, 'seed': SEED, 'group_rows': CHUNK_ROWS,
          'unit': 'one isolated process per file lane direction and repeat, fresh page context per frozen group',
          'reference': 'one fixed PGF1 per lane; each PM3PAGE1 must match r40 before use',
          'native': 'sum of group API wall and self CPU spans, exclude PGF1 I/O and untimed checks',
          'rss': 'wait4 covers supervised process path; group RSS is process high-water not a per-group allocation',
          'ingress': 'each encode passes original CSV/TXT through registered parser and packages V in frozen group order',
          'verified_durable': 'from original input or fixed lane PGF1 through semantic validation plus file and directory fsync',
          'cache': 'inherited unaffected by explicit eviction; no cold-cache claim',
          'resource': resource.RESERVATION, 'exclusive_cpu': False,
          'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}


def _groups(cols, rows):
    return ((c, lo, min(lo + CHUNK_ROWS, rows)) for c in range(cols) for lo in range(0, rows, CHUNK_ROWS))


def _archive_bytes(n, payload):
    return HEAD.size + n * SIZE.size + payload


def _population(plan, ledger, entries):
    by_file = defaultdict(dict)
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') is not None or item['route'] not in LANES.values():
            continue
        ds, route = item['dataset_id'], item['route']
        key = next(k for k in LANES if LANES[k] == route)
        require(item['selection'] == 11 and item['applicability'] == 'input_domain_matches' and row['status'] == 'verified' and
                key not in by_file[ds], 'pcodec grouped requires one verified frozen decision per lane and file')
        e, extent, entry = row['evidence'], item['input'], entries[ds]
        cols, rows = entry['value_count'], entry['rows']
        count = cols * ((rows + CHUNK_ROWS - 1) // CHUNK_ROWS)
        require(e['driver'] == 'pcodec-pages-control/1' and e['lane'] == key and e['columns'] == cols and
                0 < cols <= 4096 and 0 < rows <= 10000000 and len(e['units']) == count and
                extent['value_column_range'] == [0, cols] and extent['full_extent_of_file_rows_and_value_columns'] and
                len(extent['row_ranges']) == 1 and [extent['row_ranges'][0][k] for k in ('start', 'end')] == [0, rows] and
                extent['slice_extent']['max_per_unit'] == CHUNK_ROWS and extent['size_estimate']['input_units'] == count and
                extent['size_estimate']['native_input_bytes_one_pass'] == e['input_bytes'] == cols * rows * 8 and
                item['canonical_object_id'] == entry['canonical']['object_id'], 'pcodec grouped footprint differs from sealed plan')
        units = []
        for (col, start, end), raw in zip(_groups(cols, rows), e['units'], strict=True):
            require(raw['column'] == col and raw['row_range'] == [start, end] and raw['input_bytes'] == (end - start) * 8,
                    'pcodec grouped unit geometry differs')
            units.append({'frame': {'bytes': raw['artifact_bytes'], 'sha256': raw['artifact_sha256']},
                          'semantics': {op: _semantic(raw[op]) for op in DIRECTIONS}})
        require(e['artifact_bytes'] == sum(u['frame']['bytes'] for u in units), 'pcodec native frame cost differs')
        by_file[ds][key] = {k: item[k] for k in ('route', 'work_item_id', 'operation_config_id', 'canonical_object_id')}
        by_file[ds][key].update(units=units, original_native_frame_bytes=e['artifact_bytes'],
                                frame_archive_bytes=_archive_bytes(count, e['artifact_bytes']))
    require(len(by_file) == 23 and all(set(v) == set(LANES) for v in by_file.values()), 'pcodec grouped is not the full 23×2 cohort')
    rng = Random(SEED)
    cases = []
    for ds, variants in sorted(by_file.items()):
        e = entries[ds]
        cols, rows = e['value_count'], e['rows']
        n = cols * ((rows + CHUNK_ROWS - 1) // CHUNK_ROWS)
        raw_n = _archive_bytes(n, cols * rows * 8)
        require(max(raw_n, *(v['frame_archive_bytes'] for v in variants.values())) <= launch.FILE_CEILING,
                'pcodec grouped file exceeds tool-specific budget; do not truncate')
        c = {'dataset_id': ds, 'columns': cols, 'rows': rows, 'group_count': n, 'logical_bytes': cols * rows * 8,
             'input_archive_bytes': raw_n, 'source': e['file'], 'canonical_object_id': e['canonical']['object_id'],
             'variants': variants, 'order': [rng.sample(tuple(LANES), len(LANES)) for _ in range(WARMUPS + ROUNDS)]}
        cases.append({**c, 'case_id': content_id(c)})
    return cases


def freeze(root, plan_path, source_run, tool, cpu):
    source = load_json(plan_path)
    ledger, seal = full_run_source(source, source_run)
    definition = source['definition']['plan']
    cases = _population(source, ledger, _entry_map(root, load_json(_file(root, definition))))
    binding = source['build']['pcodec_pages']
    archive = _ref(root, tool)
    for ref in binding.values():
        _file(root, ref)
    runtime = plan_recovery(root, {}, (), tools={launch.NAME: {k: archive[k] for k in ('path', 'sha256')}},
                            libraries=[binding['dependency']])
    require(runtime['tools'] == {launch.NAME: launch.TOOL} and launch.LIBRARY in
            [f"lib/{n}" for n in runtime['files'][launch.TOOL]['needed']], 'grouped pcodec ELF binding differs')
    common = 'native/measurement/pcodec_pages_grouped/'
    code = ('src/tsbench/application/m3_pcodec_grouped_timing.py', 'src/tsbench/application/m3_pcodec_page_timing.py',
            'src/tsbench/application/m3_pcodec_pages.py', 'src/tsbench/application/m3_sealed_ledger.py',
            'src/tsbench/supervisor/pcodec_pages_grouped.py', 'src/tsbench/supervisor/process.py',
            'src/tsbench/corpus_ingress.py', 'plugins/codecs/pcodec/pages_control.cpp',
            'tools/m3_pcodec_grouped_timing.py', *(common+n for n in ('main.cpp', 'CMakeLists.txt', 'grouped-io.patch')))
    body = {'schema': SCHEMA, 'source_plan': _ref(root, plan_path), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'definition': definition, 'cases': cases, 'runtime': runtime, 'tool': archive,
            'policy': POLICY, 'environment': resource.environment(cpu), 'launchers': launcher_lock(),
            'code': [_ref(root, local_file(root, name)) for name in code]}
    return {**body, 'plan_content_id': content_id(body)}


def _stage(root, case, entry, work):
    """Read and validate the original once, transpose bounded batches, then stream the PGF1 view."""
    require(entry['file'] == case['source'] and entry['canonical']['object_id'] == case['canonical_object_id'],
            'pcodec original or canonical object differs')
    cols, rows = case['columns'], case['rows']
    output = work / 'raw.pgf'
    with TemporaryDirectory(prefix='columns-', dir=work) as tmp:
        paths = [Path(tmp) / f'{i:04d}.bin' for i in range(cols)]
        observed = 0
        with ExitStack() as stack:
            handles = [stack.enter_context(p.open('xb')) for p in paths]
            for b in read_batches(root, entry):
                require(b.start == observed, 'pcodec staged batches out of order')
                vals = np.frombuffer(b.values, dtype='V8').reshape(b.rows, cols)
                for i, f in enumerate(handles):
                    f.write(vals[:, i].tobytes())
                observed += b.rows
        require(observed == rows, 'pcodec staged row extent differs')
        with output.open('xb') as dst:
            dst.write(HEAD.pack(RAW, cols, rows))
            for p in paths:
                with p.open('rb') as src:
                    for lo in range(0, rows, CHUNK_ROWS):
                        n = min(rows - lo, CHUNK_ROWS) * 8
                        raw = src.read(n)
                        require(len(raw) == n, 'pcodec staged column truncated')
                        dst.write(SIZE.pack(n))
                        dst.write(raw)
                    require(not src.read(1), 'pcodec staged column has trailing bytes')
    require(output.stat().st_size == case['input_archive_bytes'], 'pcodec raw archive size differs')
    return output


def _amounts(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _inspect_frames(case, lane, path):
    ref = case['variants'][lane]
    require(path.stat().st_size == ref['frame_archive_bytes'], 'pcodec frame archive size differs')
    h = sha256()
    with path.open('rb') as f:
        header = f.read(HEAD.size)
        require(header == HEAD.pack(FRAME, case['columns'], case['rows']), 'pcodec archive framing differs')
        h.update(header)
        for unit in ref['units']:
            n = unit['frame']['bytes']
            prefix = f.read(SIZE.size)
            require(prefix == SIZE.pack(n), 'pcodec grouped frame length differs from r40')
            wire = f.read(n)
            require(len(wire) == n and sha256(wire).hexdigest() == unit['frame']['sha256'],
                    'pcodec grouped PM3PAGE1 bytes differ from r40')
            _frame(wire, unit['semantics']['encode'])
            h.update(prefix)
            h.update(wire)
        require(not f.read(1), 'pcodec grouped frame archive has trailing bytes')
    return {'bytes': ref['frame_archive_bytes'], 'sha256': h.hexdigest()}


def _metrics(case, lane, op, stdout):
    stats = {'group_api_wall_ns': 0, 'group_api_self_cpu_ns': 0, 'reported_child_hwm_bytes': 0}
    with stdout.open(encoding='utf-8') as f:
        for u in case['variants'][lane]['units']:
            obj = parse_json(next(f, ''), 'pcodec grouped native observation')
            wall, cpu, rss = (obj.get(k) for k in ('operation_wall_ns', 'operation_cpu_ns', 'process_peak_rss_bytes'))
            require(type(wall) is int and wall > 0 and type(cpu) is int and cpu >= 0 and type(rss) is int and rss > 0 and
                    _semantic(obj) == u['semantics'][op], 'pcodec grouped native operation or times differ from frozen unit')
            stats['group_api_wall_ns'] += wall
            stats['group_api_self_cpu_ns'] += cpu
            stats['reported_child_hwm_bytes'] = max(stats['reported_child_hwm_bytes'], rss)
        require(next(f, None) is None, 'extra pcodec grouped native observation')
    return stats


def _sync(path):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _call(run, plan, case, lane, op, path, source):
    path.mkdir(parents=True)
    wanted = case['variants'][lane]['frame_archive_bytes'] if op == 'encode' else case['input_archive_bytes']
    cap = max(4096, wanted, 1024 * case['group_count'])
    start = monotonic_ns()
    output, proc = launch.run(run / 'runtime', plan['runtime'], path, source, lane, op, case['columns'], case['rows'], cap)
    require(proc['status'] == 'completed', f"pcodec grouped {lane} {op}: {proc['status']}; see {path / 'native.stderr'}")
    stdout, stderr = path / 'native.stdout', path / 'native.stderr'
    require(stderr.stat().st_size == 0 and output.is_file() and output.stat().st_size == wanted and
            list(output.parent.iterdir()) == [output], 'pcodec grouped native product inventory differs')
    spans = _metrics(case, lane, op, stdout)
    _sync(output)
    _sync(output.parent)
    _sync(path)
    return output, {'process': proc, 'native': spans, 'logs': [_ref(run, p) for p in (stdout, stderr)],
                    'prepared_to_sync_wall_ns': monotonic_ns() - start}


def _schedule(case):
    for i, lanes in enumerate(case['order']):
        for op in DIRECTIONS:
            for lane in lanes:
                yield {'case_id': case['case_id'], 'phase': 'warmup' if i < WARMUPS else 'measure', 'repeat': i,
                       'lane': lane, 'direction': op, 'path': f"cases/{case['case_id']}/{i:02d}-{op}-{lane}"}


def _trial(root, run, plan, case, entry, setup, item):
    lane, op = item['lane'], item['direction']
    scratch = run / item['path']
    start, cpu = monotonic_ns(), process_time_ns()
    ingress = None
    if op == 'encode':
        with TemporaryDirectory(prefix='stage-', dir=scratch.parent) as d:
            source = _stage(root, case, entry, Path(d))
            ingress = monotonic_ns() - start
            output, facts = _call(run, plan, case, lane, op, scratch, source)
        expected_mount = setup['raw']
        proof = _inspect_frames(case, lane, output)
        expected = {k: setup['fixed'][lane][k] for k in ('bytes', 'sha256')}
    else:
        anchor = setup['fixed'][lane]
        source = local_file(run, anchor['path'])
        output, facts = _call(run, plan, case, lane, op, scratch, source)
        expected_mount = {k: anchor[k] for k in ('bytes', 'sha256')}
        proof, expected = _amounts(output), setup['raw']
    require(facts['process']['input_mounts'] == {'object': expected_mount} and proof == expected,
            'pcodec grouped trial changed input archive, frame or restored f64 bytes')
    # Write/fsync and semantic verification both occurred inside this wall interval.
    return {**item, **facts, 'input_original': case['source'] if op == 'encode' else None, 'result': proof,
            'ingress_wall_ns': ingress, 'verified_durable_wall_ns': monotonic_ns() - start,
            'controller_cpu_ns': process_time_ns() - cpu}, output


def _check_trial(run, case, setup, item, row, sessions):
    op, lane = item['direction'], item['lane']
    enc = op == 'encode'
    require(all(row.get(k) == v for k, v in item.items()) and row['input_original'] == (case['source'] if enc else None),
            'pcodec grouped trial differs from frozen schedule or original')
    ingress = row['ingress_wall_ns']
    require((type(ingress) is int and ingress > 0) if enc else ingress is None, 'pcodec grouped direction ingress differs')
    proc, spans = row['process'], row['native']
    child = proc['child_usage']
    wire = {k: setup['fixed'][lane][k] for k in ('bytes', 'sha256')}
    want_in, want_out = (setup['raw'], wire) if enc else (wire, setup['raw'])
    require(proc['operation'] == 'native' and proc['status'] == 'completed' and not proc['reason'] and proc['returncode'] == 0 and
            isinstance(proc['session_id'], str) and proc['session_id'] not in sessions and proc['pid'] > 0 and
            proc['input_mounts'] == {'object': want_in} and row['result'] == want_out and
            set(child) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and all(type(v) is int and v >= 0 for v in child.values()) and
            child['maxrss_bytes'] > 0 and 0 < spans['group_api_wall_ns'] <= proc['process_wall_ns'] <= row['prepared_to_sync_wall_ns'] and
            row['prepared_to_sync_wall_ns'] + (ingress or 0) <= row['verified_durable_wall_ns'] and row['controller_cpu_ns'] > 0,
            'pcodec grouped trial lacks independent process, native measurement or validated boundary')
    sessions.add(proc['session_id'])
    require([x['path'] for x in row['logs']] == [f"{item['path']}/native.{name}" for name in ('stdout', 'stderr')] and
            row['logs'][1]['bytes'] == 0, 'pcodec grouped logs differ from frozen trial')
    stdout, _ = (_file(run, ref) for ref in row['logs'])
    require(_metrics(case, lane, op, stdout) == spans, 'pcodec grouped clock does not recompute from native log')


def _distribution(xs):
    return {'min': min(xs), 'median': median(xs), 'max': max(xs)}


def _summarize(case, rows):
    out = {}
    for lane in LANES:
        native = case['variants'][lane]
        summary = {k: native[k] for k in ('route', 'work_item_id', 'operation_config_id')}
        logical = case['logical_bytes']
        written = native['frame_archive_bytes']
        summary['billing'] = {'logical_value_bytes': logical, 'canonical_raw_pgf1_bytes': case['input_archive_bytes'],
                              'original_file_bytes': case['source']['bytes'], 'complete_pgf1_bytes': written,
                              'native_pm3page1_bytes': native['original_native_frame_bytes'],
                              'pgf1_harness_bytes': written - native['original_native_frame_bytes'],
                              'logical_over_complete': logical / written}
        for k in ('meta_bytes', 'payload_bytes', 'container_bytes'):
            summary['billing']['pm3page1_' + k] = sum(r['semantics']['encode'][k] for r in native['units'])
        for op in DIRECTIONS:
            selected = [r for r in rows if r['lane'] == lane and r['direction'] == op and r['phase'] == 'measure']
            require(len(selected) == ROUNDS, 'pcodec grouped missing measured repeat')
            summary[op] = {'samples': len(selected),
                           'native': {k: _distribution([r['native'][k] for r in selected]) for k in selected[0]['native']},
                           'wall_ns': {k: _distribution([r[k] for r in selected]) for k in
                                       ('prepared_to_sync_wall_ns', 'verified_durable_wall_ns')},
                           'ingress_wall_ns': _distribution([r['ingress_wall_ns'] for r in selected]) if op == 'encode' else None,
                           'child_usage': {k: _distribution([r['process']['child_usage'][k] for r in selected]) for k in
                                           ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes')},
                           'process_wall_ns': _distribution([r['process']['process_wall_ns'] for r in selected]),
                           'controller_cpu_ns': _distribution([r['controller_cpu_ns'] for r in selected]),
                           'logical_mib_s': {k: _distribution([logical * 1e9 / ((1 << 20) * n) for n in ns]) for k, ns in (
                               ('group_api', [r['native']['group_api_wall_ns'] for r in selected]),
                               ('verified_durable', [r['verified_durable_wall_ns'] for r in selected]))}}
        summary['native_backends'] = sorted({u['semantics']['encode']['state']['backend'] for u in native['units']})
        out[lane] = summary
    return out


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and len(plan['cases']) == 23,
            'pcodec grouped plan contract differs')
    env = load_json(local_file(run, 'environment.json'))
    require(set(env) == {'before', 'after'} and all(e['affinity'] == [plan['environment']['cpu']] for e in env.values()),
            'pcodec grouped environment affinity differs')
    setups = load_json(local_file(run, 'setup.json'))
    require(set(setups) == {c['case_id'] for c in plan['cases']}, 'pcodec grouped setup population differs')
    rng, summaries, sessions = Random(SEED), [], set()
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for c in plan['cases']:
            _identity(c, 'case_id')
            require(c['order'] == [rng.sample(tuple(LANES), len(LANES)) for _ in range(WARMUPS + ROUNDS)],
                    'pcodec grouped matched schedule differs')
            setup = setups[c['case_id']]
            require(set(setup) == {'raw', 'fixed'} and set(setup['fixed']) == set(LANES) and
                    setup['raw']['bytes'] == c['input_archive_bytes'], 'pcodec grouped anchor inventory differs')
            for lane, ref in setup['fixed'].items():
                require(ref['path'] == f"cases/{c['case_id']}/fixed/{lane}.pgf", 'pcodec grouped anchor coordinates differ')
                require(_inspect_frames(c, lane, local_file(run, ref['path'])) == {k: ref[k] for k in ('bytes', 'sha256')},
                        'pcodec grouped retained frame does not recompute')
            rows = []
            for item in _schedule(c):
                row = parse_json(next(f, ''), 'pcodec grouped trial')
                _check_trial(run, c, setup, item, row, sessions)
                rows.append(row)
            summaries.append({'case_id': c['case_id'], 'dataset_id': c['dataset_id'], 'rows': c['rows'], 'columns': c['columns'],
                              'group_count_per_lane': c['group_count'], 'lanes': _summarize(c, rows)})
        require(next(f, None) is None, 'extra pcodec grouped trial rows')
    return {'schema': 'bmk.m3-pcodec-grouped-timing-report/1', 'run_id': run.name, 'source_seal': plan['source_seal'],
            'plan_content_id': plan['plan_content_id'], 'environment': env, 'policy': POLICY, 'cases': summaries,
            'verified_trials': len(sessions), 'file_routes': dict(Counter(lane['route'] for c in summaries for lane in c['lanes'].values())),
            'effective_native_thread_count': None, 'thread_observation': 'singleton process affinity; native threads not sampled',
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


def _seal(run):
    files = ('plan.json', 'environment.json', 'setup.json', 'trials.jsonl', 'report.json')
    body = {'schema': SEAL, 'run_id': run.name, 'files': [_ref(run, local_file(run, name)) for name in files]}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    require(output.is_absolute() and output.is_relative_to(root), 'grouped pcodec needs project-local output')
    cpu = plan['environment']['cpu']
    with resource.reserve():
        require(freeze(root, _file(root, plan['source_plan']), _folder(root, plan['source_run']), _file(root, plan['tool']), cpu) == plan,
                'pcodec grouped definition, source, runtime or frozen plan changed')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        with _affinity([cpu]):
            output.mkdir(parents=True, exist_ok=True)
            require(shutil.disk_usage(output).free >= 2 * (1 << 30), 'insufficient space for grouped pcodec retained and trial archives')
            run = output / uuid4().hex
            run.mkdir()
            write_new(run / 'plan.json', plan)
            stage_recovery(root, run, plan['runtime'], directory='runtime')
            def env():
                return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshot': resource.observe(cpu)}
            before, setups, sessions = env(), {}, set()
            with (run / 'trials.jsonl').open('xb') as f:
                for c in plan['cases']:
                    entry = entries[c['dataset_id']]
                    case_dir = run / 'cases' / c['case_id']
                    fixed = case_dir / 'fixed'
                    fixed.mkdir(parents=True)
                    with TemporaryDirectory(prefix='reference-', dir=case_dir) as folder:
                        scratch = Path(folder)
                        raw = _stage(root, c, entry, scratch)
                        setup = {'raw': _amounts(raw), 'fixed': {}}
                        for lane in LANES:
                            archive, proc = _call(run, plan, c, lane, 'encode', scratch / f'{lane}-encode', raw)
                            require(proc['process']['input_mounts'] == {'object': setup['raw']}, 'pcodec anchor mounted different input')
                            proof = _inspect_frames(c, lane, archive)
                            anchor = fixed / f'{lane}.pgf'
                            archive.rename(anchor)
                            restored, dec = _call(run, plan, c, lane, 'decode', scratch / f'{lane}-decode', anchor)
                            require(dec['process']['input_mounts'] == {'object': proof} and _amounts(restored) == setup['raw'],
                                    'pcodec fixed frame does not detach and restore all V bits')
                            setup['fixed'][lane] = {'path': anchor.relative_to(run).as_posix(), **proof}
                        _sync(fixed)
                        _sync(case_dir)
                    setups[c['case_id']] = setup
                    for item in _schedule(c):
                        row, product = _trial(root, run, plan, c, entry, setup, item)
                        _check_trial(run, c, setup, item, row, sessions)
                        _line(f, row)
                        product.unlink()
                        product.parent.rmdir()
            write_new(run / 'setup.json', setups)
            write_new(run / 'environment.json', {'before': before, 'after': env()})
            write_new(run / 'report.json', _report(run, plan))
            write_new(run / 'completion.json', _seal(run))
            _sync(run)
    return run


def verify(run):
    require(load_json(local_file(run, 'completion.json')) == _seal(run), 'pcodec grouped run seal differs')
    plan = load_json(local_file(run, 'plan.json'))
    for name, ref in plan['runtime']['files'].items():
        _file(run, {'path': f'runtime/{name}', **ref})
    report = _report(run, plan)
    require(report == load_json(local_file(run, 'report.json')), 'pcodec grouped report differs from sealed trials')
    return report
