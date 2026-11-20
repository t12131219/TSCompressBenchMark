"""Matched two-direction diagnostics for the frozen pcodec page-chunk routes."""
from collections import defaultdict
from contextlib import contextmanager
from hashlib import sha256
import os
import re
from pathlib import Path
from random import Random
from struct import unpack_from
import uuid

import numpy as np

from ..assets import content_id, digest, load_json, local_file, relative_parts, require, verify_asset
from ..corpus_ingress import read_batches
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_metric_details import distribution
from .m3_pcodec_pages import CHUNK_ROWS, PAGE_ROWS, _verify_chunk
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, _rows, utc, write_new

SCHEMA = 'bmk.m3-pcodec-page-timing-plan/1'
LANES = {'source': 'source-pages', 'native': 'native-pages'}
DIRECTIONS = ('encode', 'decode')
CLOCKS = ('operation_wall_ns', 'operation_cpu_ns', 'process_peak_rss_bytes')
WARMUPS, ROUNDS, SEED = 2, 7, 20261120
RUNTIME, TOOL = 'runtime', 'pcodec-pages'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}
POLICY = {'warmups': WARMUPS, 'matched_rounds': ROUNDS, 'seed': SEED, 'native_call_per_child': 1,
          'native_scope': {'encode': 'chunk_training_and_metadata_page_payload_extraction',
                           'decode': 'decoder_open_page_start_and_drain_including_restored_buffer_copies'},
          'process_scope': 'isolated_tool_launch_including_sandbox_and_tool_file_io_not_source_ingress',
          'thread_observation': 'singleton_affinity_inherited_from_supervisor_not_sampled_inside_worker',
          'direction_order': list(DIRECTIONS),
          'decode_input': 'same_frozen_frame_for_every_attempt_of_each_lane',
          'lifecycle': 'fresh_isolated_child_single_page_group_no_inner_loop', 'cache': 'uncontrolled',
          'parallel_trials': 1, 'source_file_ingress_timing': False}
IDENTITY = ('schema', 'run_id', 'plan_content_id', 'report_sha256')
FULL_SCOPE = 'complete_sealed_main_ledger_projection'
COHORT = 'all_page_groups_in_first_complete_value_column_of_every_applicable_file'


def _ref(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _project_ref(root, path):
    return {'path': path.relative_to(root).as_posix(), **_ref(path)}


def _check_ref(root, ref):
    p = verify_asset(root, ref)
    require(p.stat().st_size == ref['bytes'], 'pcodec timing asset has wrong size')
    return p


def _protocol(root):
    files = ('src/tsbench/application/m3_pcodec_page_timing.py', 'src/tsbench/application/m3_pcodec_pages.py',
             'src/tsbench/application/m3_real_corpus_execution.py', 'src/tsbench/supervisor/isolated_worker.py',
             'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/recovery.py',
             'src/tsbench/application/m3_sealed_ledger.py', 'src/tsbench/corpus_ingress.py')
    return {'code': {p: digest(local_file(root, p)) for p in files}, 'launchers': launcher_lock()}


def _plan_id(d, field='plan_content_id'):
    require(d.get(field) == content_id({k: v for k, v in d.items() if k != field}), f'pcodec timing {field} differs')


def _history(plan, location):
    seal = load_json(location / 'completion.json')
    _plan_id(seal, 'seal_id')
    expected = dict(zip(IDENTITY, ('bmk.m3-real-corpus-run-seal/1', location.name, plan['plan_content_id'],
                                   digest(location / 'report.json')), strict=True))
    require(all(seal.get(k) == v for k, v in expected.items()), 'pcodec source run seal differs')
    scope = 'legacy_sealed_report_only'
    if 'ledger_sha256' in seal:
        require(seal['ledger_sha256'] == digest(location / 'ledger.jsonl'), 'pcodec source main ledger differs')
        scope = 'sealed_report_and_main_ledger'
    report = load_json(location / 'report.json')
    require(report['run_id'] == location.name and report['plan_content_id'] == plan['plan_content_id'], 'pcodec source report identity differs')
    return report, seal, scope


def _semantic(info):
    return {k: v for k, v in info.items() if k not in CLOCKS}


def _read_columns(root, definition, geometries):
    entries = _entry_map(root, definition)
    grouped = defaultdict(list)
    data = {}
    for g in geometries:
        dataset, column, lo, hi = g
        entry = entries[dataset]
        require(g not in data and 0 <= column < entry['value_count'] and 0 <= lo < hi <= entry['rows'] and
                hi - lo <= CHUNK_ROWS, 'pcodec timing geometry exceeds canonical input or is duplicated')
        grouped[dataset].append(g)
        data[g] = bytearray()
    for dataset, spans in grouped.items():
        entry = entries[dataset]
        # Exhaust ingestion so the source hash and extent are checked. Emit
        # only requested slices, preserving every binary64 word verbatim.
        for batch in read_batches(root, entry):
            matrix = np.frombuffer(batch.values, dtype='V8').reshape(batch.rows, entry['value_count'])
            for g in spans:
                _, column, lo, hi = g
                lo, hi = max(0, lo - batch.start), min(hi - batch.start, batch.rows)
                if lo < hi:
                    data[g].extend(matrix[lo:hi, column].tobytes())
    require(all(len(raw) == (g[3] - g[2]) * 8 for g, raw in data.items()), 'pcodec timing input is truncated')
    return {g: bytes(raw) for g, raw in data.items()}


def _complete_cohort(plan):
    lanes = {r: {} for r in LANES.values()}
    for item in plan['work_items']:
        if item['route'] not in lanes or item['applicability'] != 'input_domain_matches':
            continue
        extent = item['input']
        span, = extent['row_ranges']
        lane, dataset = lanes[item['route']], item['dataset_id']
        require(dataset not in lane and item['selection'] == 11 and extent['full_extent_of_file_rows_and_value_columns'] and
                span['partition'] == 'full' and span['start'] == 0 and span['end'] > 0 and
                extent['value_column_range'][0] == 0 and extent['slice_extent']['max_per_unit'] == CHUNK_ROWS,
                'pcodec cohort needs one full source extent per file and lane')
        lane[dataset] = span['end']
    source, native = (lanes[r] for r in LANES.values())
    require(source and source == native, 'pcodec cohort applicable files or full row extents differ by lane')
    return {'selection': COHORT, 'files': [{'dataset_id': ds, 'rows': n} for ds, n in source.items()]}


def _cohort_geometry(cohort):
    return [(f['dataset_id'], 0, start, min(start + CHUNK_ROWS, f['rows'])) for f in cohort['files']
            for start in range(0, f['rows'], CHUNK_ROWS)]


def _check_cohort(plan):
    cohort = plan.get('cohort')
    require((cohort is not None) == (plan['functional']['scope'] == FULL_SCOPE), 'pcodec cohort source scope differs')
    if cohort is not None:
        files = cohort['files']
        require(cohort['selection'] == COHORT and files and len({r['dataset_id'] for r in files}) == len(files) and
                all(type(r['rows']) is int and r['rows'] > 0 for r in files), 'invalid pcodec frozen cohort population')
        actual = [(r['dataset_id'], r['column'], *r['rows']) for r in plan['cases']]
        require(actual == _cohort_geometry(cohort), 'pcodec timing cases omit or alter frozen cohort extents')
    return cohort


def freeze(root, m3_path, source_plan_path, source_run, selectors, cpu, overlap_run=None, *, full_corpus=False):
    root = root.resolve(strict=True)
    m3_path, source_plan_path, source_run = (p.resolve(strict=True) for p in (m3_path, source_plan_path, source_run))
    require(all(p.is_relative_to(root) for p in (m3_path, source_plan_path, source_run)),
            'pcodec functional reference must be in the project')
    if overlap_run is not None:
        overlap_run = _run_dir(root, overlap_run).relative_to(root).as_posix()
    require((not selectors and m3_path == source_plan_path) if full_corpus else 0 < len(selectors or ()) <= 8,
            'pcodec full cohort requires the identical frozen source plan and no manual cases; otherwise provide 1 to 8 cases')
    main, old = load_json(m3_path), load_json(source_plan_path)
    _plan_id(main); _plan_id(old)
    for side in (main, old):
        for k in ('executable', 'dependency', 'adapter'):
            _check_ref(root, side['build']['pcodec_pages'][k])
    require(main['definition']['plan_content_id'] == old['definition']['plan_content_id'] and
            main['build']['pcodec_pages'] == old['build']['pcodec_pages'], 'pcodec functional reference and M3 page binding differ')
    if full_corpus:
        cohort = _complete_cohort(main)
        selectors = [(ds, col, lo) for ds, col, lo, _ in _cohort_geometry(cohort)]
        ledger, seal_id = full_run_source(old, source_run)
        source_rows = (r for r, item in full_run_rows(old, ledger) if r.get('entry_kind') is None and item['selection'] == 11)
        evidence_scope = FULL_SCOPE
    else:
        cohort = None
        report, seal, evidence_scope = _history(old, source_run)
        source_rows, seal_id = report['rows'], seal['seal_id']
    rows = {(r['dataset_id'], r['route']): r for r in source_rows if r['route'] in LANES.values() and r['status'] == 'verified'}
    frozen = {(r['dataset_id'], r['route']): r for r in main['work_items'] if r['route'] in LANES.values()}
    geoms, kinds = {}, []
    for dataset, col, start in selectors:
        require((dataset, col, start) not in geoms, 'duplicate pcodec timing selector')
        variants = {}
        ends = set()
        for lane, route in LANES.items():
            require((dataset, route) in frozen and (dataset, route) in rows,
                    f'no verified pcodec function for {dataset}/{route}')
            item, row = frozen[dataset, route], rows[dataset, route]
            require(row['work_item_id'] == item['work_item_id'] and item['applicability'] == 'input_domain_matches' and
                    row['evidence']['lane'] == lane and row['evidence']['driver'] == 'pcodec-pages-control/1',
                    'pcodec frozen decision identity differs')
            matches = [u for u in row['evidence']['units'] if u['column'] == col and u['row_range'][0] == start]
            require(len(matches) == 1, 'pcodec timing span is not a unique frozen work unit')
            unit = matches[0]
            ends.add(unit['row_range'][1])
            variants[lane] = {'work_item_id': item['work_item_id'], 'operation_config_id': item['operation_config_id'],
                              'route': route, 'frame': {'bytes': unit['artifact_bytes'], 'sha256': unit['artifact_sha256']},
                              'semantics': {op: _semantic(unit[op]) for op in DIRECTIONS}}
        require(len(ends) == 1, 'pcodec timing lanes differed in geometry')
        geom = (dataset, col, start, ends.pop())
        kinds.append((geom, variants))
        geoms[dataset, col, start] = geom
    require(kinds, 'empty pcodec timing plan')
    definition = load_json(_check_ref(root, main['definition']['plan']))
    raw = _read_columns(root, definition, geoms.values())
    rng = Random(SEED)
    cases = []
    for geom, variants in kinds:
        dataset, col, lo, hi = geom
        require({ref['semantics']['encode']['rows'] for ref in variants.values()} == {hi - lo}, 'pcodec timing lane rows differ')
        row = {'dataset_id': dataset, 'column': col, 'rows': [lo, hi], 'variants': variants,
               'original': {'bytes': len(raw[geom]), 'sha256': sha256(raw[geom]).hexdigest()},
               'order': [rng.sample(list(LANES), len(LANES)) for _ in range(WARMUPS + ROUNDS)]}
        cases.append({**row, 'case_id': content_id(row)})
    binding = main['build']['pcodec_pages']
    runtime = plan_recovery(root, {}, (), tools={TOOL: {k: binding['executable'][k] for k in ('path', 'sha256')}},
                            libraries=[binding['dependency']])
    body = {'schema': SCHEMA, 'policy': POLICY, 'limits': LIMITS, 'cases': cases, 'runtime': runtime,
            'functional': {'plan': _project_ref(root, m3_path), 'source_plan': _project_ref(root, source_plan_path),
                           'source_run': source_run.relative_to(root).as_posix(), 'source_seal': seal_id, 'scope': evidence_scope},
            'definition': main['definition']['plan'], 'environment': resource.environment(cpu), 'protocol': _protocol(root),
            'declared_overlapping_functional_run': overlap_run,
            'timing_admitted': False, 'qualification_granted': False}
    if cohort is not None:
        body['cohort'] = cohort
        _check_cohort(body)
    return {**body, 'plan_content_id': content_id(body)}


def _frame(wire, expected):
    require(len(wire) >= 16 and wire[:8] == b'PM3PAGE1', 'pcodec timed frame format differs')
    size, meta = unpack_from('<II', wire, 8)
    header = 16 + 8 * size
    require(1 <= size <= 16 and len(wire) >= header, 'pcodec timed frame directory is invalid')
    geometry = [unpack_from('<II', wire, 16 + 8*i) for i in range(size)]
    payload = sum(n for _, n in geometry)
    require(all(rows == PAGE_ROWS for rows, _ in geometry[:-1]) and 0 < geometry[-1][0] <= PAGE_ROWS and
            len(wire) == header + meta + payload and
            (sum(n for n, _ in geometry), size, meta, payload, header, sum(v == 0 for _, v in geometry)) ==
            tuple(expected[k] for k in ('rows', 'pages', 'meta_bytes', 'payload_bytes', 'container_bytes', 'zero_payload_pages')),
            'pcodec timed frame byte accounting differs')
    return {'native_page_payload_bytes': payload, 'page_metadata_bytes': meta, 'group_header_bytes': header,
            'complete_frame_bytes': len(wire)}


@contextmanager
def _pinned(cpu):
    was = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {cpu})
    try:
        require(os.sched_getaffinity(0) == {cpu}, 'failed to pin pcodec timing process')
        yield
    finally:
        os.sched_setaffinity(0, was)


def _invoke(run, plan, op, lane, inp, scratch):
    scratch.mkdir()
    out, proc = invoke_isolated_tool(run / RUNTIME, plan['runtime'], TOOL, plan['limits'], scratch, scratch, 'page',
                                     {'object': inp}, [f'corpus-{op}', lane, '/inputs/object', '/out/object'],
                                     lambda: False, observe=True)
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and set(p.name for p in out.iterdir()) == {'object'},
            f'pcodec {lane} {op} failed: ' + (scratch / 'page.stderr').read_text()[:500])
    doc = load_json(scratch / 'page.stdout')
    return out / 'object', {'native': doc, 'process': proc}


def _run_dir(root, relative):
    folder = root.joinpath(*relative_parts(relative)).resolve(strict=True)
    require(folder.is_relative_to(root) and folder.is_dir(), 'invalid pcodec evidence run path')
    return folder


def _observations(root, plan):
    overlap = plan['declared_overlapping_functional_run']
    state = None
    if overlap is not None:
        folder = _run_dir(root, overlap)
        ledger = local_file(folder, 'ledger.jsonl')
        state = {'path': overlap, 'ledger_bytes': ledger.stat().st_size, 'sealed': (folder / 'completion.json').is_file()}
    return {'utc': utc(), 'resource': resource.observe(plan['environment']['cpu']), 'declared_functional_run': state}


def _trials(case):
    for i, order in enumerate(case['order']):
        for op in DIRECTIONS:
            for lane in order:
                yield {'case_id': case['case_id'], 'round': i + 1 if i < WARMUPS else i + 1 - WARMUPS,
                       'phase': 'warmup' if i < WARMUPS else 'measured', 'direction': op, 'lane': lane,
                       'path': f"cases/{case['case_id']}/{i + 1:02d}-{op}-{lane}"}


def _case_files(run, case, lane):
    folder = run / 'cases' / case['case_id']
    return folder / 'original.f64', folder / f'{lane}.pm3page'


def _verify_trial(run, case, trial, row, sessions):
    require(row.keys() == trial.keys() | {'native', 'process', 'files'} and
            all(row[k] == v for k, v in trial.items()), 'pcodec timing ledger differs from frozen schedule')
    op, lane = trial['direction'], trial['lane']
    raw, fixed_frame = _case_files(run, case, lane)
    variant = case['variants'][lane]
    scratch = run / trial['path']
    stdout, stderr, product = (scratch / n for n in ('page.stdout', 'page.stderr', 'out/object'))
    for name, path in (('stdout', stdout), ('stderr', stderr), ('product', product)):
        require(_check_ref(run, {**row['files'][name], 'path': path.relative_to(run).as_posix()}) == path,
                'pcodec trial file differs')
    require(set(row['files']) == {'stdout', 'stderr', 'product'} and row['files']['stderr']['bytes'] == 0,
            'pcodec tool produced unexpected diagnostics')
    doc, proc = row['native'], row['process']
    require(load_json(stdout) == doc and _semantic(doc) == variant['semantics'][op],
            'pcodec native route semantics changed')
    require(proc.keys() == {'operation', 'status', 'returncode', 'pid', 'session_id', 'reason', 'process_wall_ns',
                            'child_usage', 'input_mounts'}, 'missing pcodec supervision fields')
    require(proc['operation'] == 'page' and proc['status'] == 'completed' and proc['returncode'] == 0 and
            proc['reason'] == '' and type(proc['pid']) is int and proc['pid'] > 0 and
            isinstance(proc['session_id'], str) and re.fullmatch('[0-9a-f]{32}', proc['session_id']) and
            proc['session_id'] not in sessions, 'pcodec isolated trial launcher identity differs')
    sessions.add(proc['session_id'])
    require(proc['input_mounts'] == {'object': case['original'] if op == 'encode' else variant['frame']},
            'pcodec isolated input identity differs')
    usage = proc['child_usage']
    require(usage.keys() == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and
            all(type(v) is int and v >= 0 for v in usage.values()) and usage['maxrss_bytes'] > 0 and
            type(proc['process_wall_ns']) is int and proc['process_wall_ns'] > 0 and
            all(type(doc.get(k)) is int for k in CLOCKS) and
            0 < doc['operation_wall_ns'] <= proc['process_wall_ns'] and
            doc['operation_cpu_ns'] >= 0 and doc['process_peak_rss_bytes'] > 0,
            'pcodec isolated trial clocks or resource counters differ')
    expected_output = variant['frame'] if op == 'encode' else case['original']
    require(row['files']['product'] == expected_output, 'pcodec timed output differs from frozen identity')
    frame_wire = fixed_frame.read_bytes()
    if op == 'encode':
        require(product.read_bytes() == frame_wire, 'pcodec repeated encoding differs from its lane reference frame')
    raw_bytes = raw.read_bytes()
    _verify_chunk(raw_bytes, product.read_bytes() if op == 'decode' else raw_bytes, len(frame_wire),
                  variant['semantics']['encode'], variant['semantics']['decode'])
    return _frame(frame_wire, variant['semantics']['encode'])


def _repeat_distribution(values):
    return {**distribution(values), 'sample_basis': 'fresh_isolated_process_per_matched_measured_round'}


def _direction(rows, op, lane, logical):
    measured = [r for r in rows if r['phase'] == 'measured' and (r['direction'], r['lane']) == (op, lane)]
    require(len(measured) == ROUNDS, 'missing pcodec measured repetitions')
    native = [{k: r['native'][k] for k in CLOCKS} for r in measured]
    process = [{'wall_ns': p['process_wall_ns'], **p['child_usage']} for p in (r['process'] for r in measured)]
    def summary(samples, wall):
        distributions = {k: _repeat_distribution([sample[k] for sample in samples]) for k in samples[0]}
        return {'distributions_ns_or_bytes': distributions,
                'mib_per_second_from_sum_wall_ns': logical * len(samples) * 1e9 / (distributions[wall]['sum'] * (1 << 20))}
    return {'native_operation': summary(native, 'operation_wall_ns'),
            'supervised_process_tree_wait4': summary(process, 'wall_ns')}


def _recompute(run, plan):
    _plan_id(plan)
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['limits'] == LIMITS and
            plan['timing_admitted'] is False and plan['qualification_granted'] is False,
            'unexpected pcodec timing plan identity or qualification')
    cohort = _check_cohort(plan)
    for path, row in plan['runtime']['files'].items():
        _check_ref(run, {'path': f'{RUNTIME}/{path}', 'bytes': row['bytes'], 'sha256': row['sha256']})
    raw_rows = iter(_rows(run / 'trials.jsonl'))
    environment = load_json(run / 'environment.json')
    require(environment['pinned_supervisor_affinity'] == [plan['environment']['cpu']] and
            environment['frozen'] == plan['environment'], 'pcodec observed affinity differs from plan')
    cases, seen, rng = [], set(), Random(SEED)
    for case in plan['cases']:
        _plan_id(case, 'case_id')
        require(case['order'] == [rng.sample(list(LANES), len(LANES)) for _ in range(WARMUPS + ROUNDS)],
                'pcodec timing lane order differs from frozen policy')
        for lane in LANES:
            original, frame = _case_files(run, case, lane)
            for path, facts in ((original, case['original']), (frame, case['variants'][lane]['frame'])):
                _check_ref(run, {'path': path.relative_to(run).as_posix(), **facts})
        accounting, rows = defaultdict(dict), []
        for trial in _trials(case):
            row = next(raw_rows, None)
            require(row is not None, 'missing pcodec ledger trial')
            accounting[trial['lane']] = _verify_trial(run, case, trial, row, seen)
            rows.append(row)
        counts = {'dataset_id': case['dataset_id'], 'column': case['column'], 'row_range': case['rows'],
                  'logical_bytes': case['original']['bytes'], 'attempts': len(rows), 'lanes': {}}
        for lane, variant in case['variants'].items():
            byte_counts = accounting[lane]
            counts['lanes'][lane] = {'route': variant['route'], 'work_item_id': variant['work_item_id'],
                                     'operation_config_id': variant['operation_config_id'], 'frame': variant['frame'],
                                     'bytes': byte_counts, 'compression_ratio': counts['logical_bytes'] / byte_counts['complete_frame_bytes'],
                                     'directions': {op: _direction(rows, op, lane, counts['logical_bytes']) for op in DIRECTIONS}}
        cases.append(counts)
    require(next(raw_rows, None) is None and cases, 'unexpected additional or no pcodec timing trials')
    overlap = plan['declared_overlapping_functional_run']
    return {'schema': 'bmk.m3-pcodec-page-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'functional_basis': plan['functional'], 'verified_trials': len(seen), 'cases': cases,
            **({'cohort': cohort} if cohort is not None else {}),
            'workload_interference': 'declared_concurrent_functional_run_not_isolated_from_host_load' if overlap else 'not_controlled_at_host_level',
            'environment': environment, 'policy': plan['policy'], 'timing_admitted': False, 'qualification_granted': False}


def execute(root, plan, output_root):
    """Run a read-only frozen plan; never merge these diagnostics into the M3 main ledger."""
    root = root.resolve(strict=True)
    functional = plan['functional']
    cohort = _check_cohort(plan)
    selectors = None if cohort is not None else [(c['dataset_id'], c['column'], c['rows'][0]) for c in plan['cases']]
    require(freeze(root, _check_ref(root, functional['plan']), _check_ref(root, functional['source_plan']),
                   _run_dir(root, functional['source_run']), selectors, plan['environment']['cpu'],
                   plan['declared_overlapping_functional_run'], full_corpus=cohort is not None) == plan,
            'pcodec timing plan does not match functional source or protocol')
    output_root = output_root.resolve()
    require(output_root.is_relative_to(root), 'pcodec timing output must stay in the project')
    with resource.reserve():
        output_root.mkdir(parents=True, exist_ok=True)
        run = output_root / uuid.uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory=RUNTIME)
        definition = load_json(_check_ref(root, plan['definition']))
        cases = plan['cases']
        geoms = [(c['dataset_id'], c['column'], *c['rows']) for c in cases]
        columns = _read_columns(root, definition, geoms)
        cpu = plan['environment']['cpu']
        seen = set()
        with (run / 'trials.jsonl').open('xb') as ledger, _pinned(cpu):
            before = _observations(root, plan)
            cpus = sorted(os.sched_getaffinity(0))
            for case, geom in zip(cases, geoms, strict=True):
                original, _ = _case_files(run, case, 'source')
                original.parent.mkdir(parents=True)
                original.write_bytes(columns[geom])
                require(_ref(original) == case['original'], 'pcodec canonical slice differs at execution')
                for trial in _trials(case):
                    op, lane = trial['direction'], trial['lane']
                    _, reference = _case_files(run, case, lane)
                    scratch = run / trial['path']
                    product, facts = _invoke(run, plan, op, lane, original if op == 'encode' else reference, scratch)
                    if op == 'encode' and trial['phase'] == 'warmup' and trial['round'] == 1:
                        require(_ref(product) == case['variants'][lane]['frame'], 'first lane frame differs from functional source')
                        with reference.open('xb') as frame:
                            frame.write(product.read_bytes())
                    row = {**trial, **facts, 'files': {'stdout': _ref(scratch / 'page.stdout'),
                           'stderr': _ref(scratch / 'page.stderr'), 'product': _ref(product)}}
                    _verify_trial(run, case, trial, row, seen)
                    _line(ledger, row)
            after = _observations(root, plan)
        write_new(run / 'environment.json', {'frozen': plan['environment'], 'pinned_supervisor_affinity': cpus,
                                              'before': before, 'after': after})
        report = _recompute(run, plan)
        write_new(run / 'report.json', report)
        seal = {'schema': 'bmk.m3-pcodec-page-timing-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': {key: _ref(run / key) for key in ('plan.json', 'environment.json', 'trials.jsonl', 'report.json')}}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
        return run


def verify_report(run):
    run = run.resolve(strict=True)
    seal = load_json(run / 'completion.json')
    _plan_id(seal, 'seal_id')
    require(seal['schema'] == 'bmk.m3-pcodec-page-timing-seal/1' and seal['run_id'] == run.name and
            set(seal['files']) == {'plan.json', 'environment.json', 'trials.jsonl', 'report.json'}, 'pcodec timing seal differs')
    for key, ref in seal['files'].items():
        _check_ref(run, {'path': key, **ref})
    plan = load_json(run / 'plan.json')
    require(seal['plan_content_id'] == plan['plan_content_id'], 'pcodec timing plan is not the sealed plan')
    report = _recompute(run, plan)
    require(load_json(run / 'report.json') == report, 'pcodec timing report differs from sealed trials')
    return report
