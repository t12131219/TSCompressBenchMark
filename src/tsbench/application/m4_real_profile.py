"""M4 matched three-arm profiling bound to real M3 units, not synthetic fixtures."""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import shutil
from struct import pack
from tempfile import TemporaryDirectory
from random import Random
import uuid

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require, verify_asset
from ..contracts import compile_contract
from ..planner.m3_batch_timing import MAGIC, _frame_cost, reference, checked_file
from ..supervisor import timing_resource as resource
from ..supervisor.process import invoke
from .profiling import CAP, DIRECTIONS, PASSES, ROUNDS, ROUTES, SEED, _check_native, _repeats, _snapshot
from .smoke import _line, _rows, write_new

PLAN = 'bmk.m4-real-profile-plan/1'
SEAL = 'bmk.m4-real-profile-seal/1'
NATIVE_ROUTE = {'alp-fused': 'alp-fused', 'zstd-mt': 'zstd-mt-real', 'xz-opaque': 'xz-opaque'}
CODE = ('src/tsbench/application/m4_real_profile.py', 'src/tsbench/application/profiling.py',
        'src/tsbench/analysis/trace.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/supervisor/timing_resource.py', 'native/measurement/profile_driver.cpp',
        'plugins/codecs/zstd/corpus_worker_control.cpp', 'tools/build_m4_real_profile.py')
EXTENT = 'staged_input_then_allocate_prepare_native_operation_cleanup_serialize_and_close'


def _id(d, k):
    require(d[k] == content_id({a: v for a, v in d.items() if a != k}), f'M4 invalid {k}')


def _sha(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def _artifact(data, case):
    if case['plugin'] is None:
        return data
    schema = _schema(case)
    raw = case['original']
    require(_sha(schema) == raw['schema'], 'M4 source schema differs from M3')
    return MAGIC[case['plugin']] + pack('<IQIQ', raw['dtype'], raw['count'], len(schema), len(data)) + schema + data


def _schema(case):
    count = case['original']['count']
    return canonical_bytes({'role': 'value', 'dtype': 'f64', 'rows': count} if case['plugin'] == 'alp-auto'
                           else {'role': 'bytes', 'dtype': 'u8', 'bytes': count})


def _schedule():
    rng = Random(SEED)
    order = [(route, i, mode, CAP if mode == 'profiled' else 0) for route in ROUTES
             for i in range(1, ROUNDS + 1) for mode in rng.sample(PASSES, len(PASSES))]
    order.append(('alp-fused', 0, 'profiled', 2))
    return [{'slot': f'v{j:02d}', 'case': route, 'round': i, 'mode': mode, 'capacity': cap}
            for j, (route, i, mode, cap) in enumerate(order, 1)]


def _build(root, ref, m3):
    d = load_json(checked_file(root, ref))
    require(d['schema'] == 'bmk.m4-real-profile-driver-build/1' and set(d['arms']) == {'plain', 'profile'} and
            d['compiler']['sha256'] == digest(Path(d['compiler']['path'])), 'M4 driver build record differs')
    for p, h in d['source'].items():
        verify_asset(root, {'path': p, 'sha256': h})
    lock = load_json(checked_file(root, m3['build']['lock']))
    declared = {p['path'].split('/')[-1]: p['sha256'] for k in ('alp-auto', 'xz-baseline', 'zstd')
                for p in lock['plugins'][k]['dependencies']}
    assets = {}
    for arm, r in d['arms'].items():
        for p, h in r['sources'].items():
            verify_asset(root, {'path': p, 'sha256': h})
        runtime = {Path(p).name: r['sources'][p] for p in r['runtime']}
        require(set(runtime) == set(declared) | ({'libtsbench_trace.so'} if arm == 'profile' else set()),
                'M4 native closure differs from planned codec dependencies')
        if arm == 'plain':
            require(runtime == declared, 'M4 pristine codec build does not match M3 byte for byte')
        else:
            require(all(runtime[k] != h for k, h in declared.items()), 'M4 overlay did not change intended native libraries')
        assets[arm] = [reference(root, local_file(root, p)) for p in (r['driver'], *r['runtime'])]
    return assets


def _work(plan, dataset, route):
    rows = [x for x in plan['work_items'] if (x['dataset_id'], x['route']) == (dataset, route)]
    require(len(rows) == 1 and rows[0]['applicability'] == 'input_domain_matches', 'M4 case is not one applicable M3 item')
    return rows[0]


def _hist(root, m3, item, src_plan, src_run):
    from .m3_lzbench_timing import _functional

    old = load_json(src_plan)
    _id(old, 'plan_content_id')
    require(old['definition']['plan_content_id'] == m3['definition']['plan_content_id'] and
            old['build']['lock'] == m3['build']['lock'] and
            item == _work(old, item['dataset_id'], item['route']), 'M4 historical work/build/definition binding differs')
    seal, rows = _functional(old, src_run)
    matched = [r for r in rows if r.get('work_item_id') == item['work_item_id']]
    require(len(matched) == 1 and matched[0]['status'] == 'verified' and
            all(matched[0][k] == item[k] for k in ('route', 'dataset_id', 'operation', 'applicability')),
            'M4 needs one verified exact source work unit')
    return matched[0]['evidence'], {'plan': reference(root, src_plan), 'seal': reference(root, src_run / 'completion.json'),
                                    'run': src_run.relative_to(root).as_posix(), 'seal_id': seal['seal_id']}


def _case(item, **body):
    record = {k: item[k] for k in ('dataset_id', 'route', 'operation_config_id', 'work_item_id', 'canonical_object_id', 'view')}
    record.update(body)
    return {**record, 'case_content_id': content_id(record)}


def freeze(root, *, m3, build, alp, zstd, xz, cpus, overlap=None):
    from .m3_batch_timing import report_timing

    root = root.resolve(strict=True)
    m3, build = (p.resolve(strict=True) for p in (m3, build))
    dataset, col, start, alp_plan, alp_run = alp
    zs_dataset, zs_plan, zs_run = zstd
    xz_dataset, xz_lo, xz_run = xz
    alp_plan, alp_run, zs_plan, zs_run, xz_run = (p.resolve(strict=True) for p in (alp_plan, alp_run, zs_plan, zs_run, xz_run))
    require(all(p.is_relative_to(root) for p in (m3, build, alp_plan, alp_run, zs_plan, zs_run, xz_run)),
            'M4 references must stay in project')
    main = load_json(m3)
    _id(main, 'plan_content_id')
    buildref = reference(root, build)
    assets = _build(root, buildref, main)
    env = [resource.environment(cpu) for cpu in cpus]
    require(len(env) == 3 and len({(e['package_id'], e['core_id']) for e in env}) == 3, 'M4 requires three distinct physical cores')

    a = _work(main, dataset, 'decode-backends')
    evidence, binding = _hist(root, main, a, alp_plan, alp_run)
    hits = [u for u in evidence['units'] if u['column'] == col and u['row_range'][0] == start]
    require(len(hits) == 1, 'missing requested real ALP column/range')
    unit = hits[0]
    dec = unit['decodes']['falp-auto']['native']
    require(dec['backend'] == 'falp-avx2' and dec['threads'] == 1 and dec['falp_avx2_vectors'] > 2,
            'M4 ALP case lacks actual fused AVX2 work or pressure-control extent')
    a_case = _case(a, plugin='alp-auto', geometry={k: unit[k] for k in ('column', 'row_range')},
                   original=unit['original'], expected_m3_frame=unit['artifact'], native_frame=None,
                   native_config={'encode': 'ALPN_AUTO', 'decode': 'ALPN_FALP_AVX2',
                                  'm3_decode_dispatch': 'falp-auto', 'effective_backend': dec['backend'],
                                  'fused_vectors': dec['falp_avx2_vectors'], 'threads': 1},
                   reference=binding)

    z = _work(main, zs_dataset, 'zstd-workers')
    evidence, binding = _hist(root, main, z, zs_plan, zs_run)
    require(main['build']['lzbench_workers'] == load_json(zs_plan)['build']['lzbench_workers'], 'M4 differs from M3 worker control build')
    enc, dec = evidence['encode']['2'], evidence['decode_own']['2']
    source = evidence['source']
    require(source['bytes'] + source['bytes'] // 10 + 65536 + 65521 <= 16 << 20 and
            enc['observed']['jobs']['worker_threads'] == 2 and enc['observed']['effective_parameters']['checksum'] == 0 and
            enc['observed']['effective_parameters']['job_size'] == 524288 and enc['observed']['effective_parameters']['level'] == 3 and
            dec['observed']['jobs']['worker_threads'] == 0 and dec['source_frame'] == enc['frame'] and dec['restored'] == source,
            'M4 Zstd exact native worker profile differs')
    retained = evidence['retained'].get('2')
    require(retained is not None and {k: retained[k] for k in ('bytes', 'sha256')} == enc['frame'],
            'M4 requires retained two-worker reference frame')
    z_case = _case(z, plugin=None, geometry={'byte_range': [0, source['bytes']]}, original={'raw': source},
                   expected_m3_frame=enc['frame'], native_frame=reference(root, checked_file(zs_run, retained)),
                   native_config={'encode': enc['observed']['effective_parameters'], 'decode': dec['observed']['effective_parameters'],
                                  'span_bytes': {'encode': [262139, 65521], 'decode': [1048576, 131071]}, 'jobs': enc['observed']['jobs']},
                   reference=binding)

    x = _work(main, xz_dataset, 'xz-baseline')
    timed = report_timing(xz_run)
    paired = load_json(xz_run / 'plan.json')
    require(checked_file(root, paired['functional']['plan']) == m3, 'M4 XZ paired measurement targets a different M3 plan')
    hits = [c for c in paired['cases'] if c['work_item_id'] == x['work_item_id'] and c['geometry']['byte_range'][0] == xz_lo]
    require(len(hits) == 1 and timed['status_counts'].keys() == {'verified'}, 'M4 XZ needs exact verified M3 timing input')
    xc = hits[0]
    c = xc['expected_native']
    require(c['encode']['preset'] == 6 and all(v['check'] == 'none' and v['threads'] == 1 for v in c.values()),
            'M4 XZ direct config differs from M3')
    wire = checked_file(root, xc['frame']).read_bytes()
    _frame_cost(wire, xc['plugin'], xc['original'])
    x_case = _case(x, plugin=xc['plugin'], geometry=xc['geometry'], original=xc['original'],
                   expected_m3_frame={k: xc['frame'][k] for k in ('bytes', 'sha256')}, native_frame=None,
                   native_config=c, reference={'timing_run': xz_run.relative_to(root).as_posix(), 'seal_id': timed['seal_id'],
                                              'timing_case_id': xc['case_id'], 'sealed_bmk_frame': xc['frame']})
    trace_schema = reference(root, local_file(root, 'schemas/trace.schema.json'))
    overlap = (root / overlap).resolve(strict=True).relative_to(root).as_posix() if overlap else None
    if overlap:
        local_file(root, overlap + '/ledger.jsonl')
    body = {'schema': PLAN, 'm3_plan': reference(root, m3), 'build': buildref, 'assets': assets,
            'definition': main['definition']['plan'], 'inputs': dict(zip(ROUTES, (a_case, z_case, x_case), strict=True)),
            'schedule': _schedule(), 'trace_schema': trace_schema, 'environment': env, 'overlap_run': overlap,
            'code': {p: digest(local_file(root, p)) for p in CODE}, 'prlimit': digest(Path(resource.PRLIMIT)),
            'extent': EXTENT, 'formal_performance': False, 'qualification_granted': False}
    return {**body, 'plan_content_id': content_id(body)}


@contextmanager
def _pinned(cpus):
    was = os.sched_getaffinity(0)
    os.sched_setaffinity(0, cpus)
    try:
        require(os.sched_getaffinity(0) == set(cpus), 'M4 inherited affinity not established')
        yield
    finally:
        os.sched_setaffinity(0, was)


def _env(root, plan):
    other = None
    if (relative := plan['overlap_run']):
        ledger = local_file(root, relative + '/ledger.jsonl')
        other = {'path': relative, 'ledger_bytes': ledger.stat().st_size,
                 'sealed': (ledger.parent / 'completion.json').is_file()}
    return {'cpus': sorted(os.sched_getaffinity(0)), 'snapshots': [resource.observe(e['cpu']) for e in plan['environment']],
            'overlap': other}


def _args(program, trial, op, original, inp, out):
    return [resource.PRLIMIT, '--core=0:0', '--as=536870912:536870912', '--fsize=16777216:16777216', '--', program,
            trial['mode'], NATIVE_ROUTE[trial['case']], op, str(original), inp, out, str(trial['capacity'])]


def _run(program, trial, op, original, inp, out, logs, label):
    proc = invoke(_args(program, trial, op, original, inp, out), out.parent, logs, label, 25, lambda: False,
                  environment={'LC_ALL': 'C', 'LD_LIBRARY_PATH': str(program.parent)}, observe_process=True, capture_usage=True)
    err = logs / f'{label}.stderr'
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and out.is_file() and err.stat().st_size == 0,
            f'M4 profiling {label} failed: ' + (err.read_text()[:500] if err.is_file() else proc['reason']))
    return proc


def _check_link(case, direction, observed):
    counters = observed['native_counters']
    if case['plugin'] == 'alp-auto' and direction == 'decode':
        require(counters['alp_fused_vectors'] == case['native_config']['fused_vectors'],
                'profiled AVX2 vector count differs from M3 effective dispatch')
    if case['route'] == 'zstd-workers' and direction == 'encode':
        jobs = case['native_config']['jobs']
        require(counters['native_jobs'] == jobs['jobs'] and counters['native_worker_threads'] == jobs['worker_threads'] and
                counters['native_caller_jobs'] == jobs['caller_jobs'], 'profiled Zstd jobs differ from M3 worker control')


def _stage_values(root, plan, folder):
    from .m3_real_corpus_execution import _entry_map, _stage_dataset

    entries = _entry_map(root, load_json(checked_file(root, plan['definition'])))
    for route, case in plan['inputs'].items():
        work = folder / route
        work.mkdir(parents=True)
        with TemporaryDirectory(prefix='m4-real-ingress-') as tmp:
            source = _stage_dataset(root, entries[case['dataset_id']], Path(tmp), case['view'])
            geom = case['geometry']
            if case['view'] == 'f64_columns':
                lo, hi = (n * 8 for n in geom['row_range'])
            else:
                lo, hi = geom['byte_range']
            with source['paths'][geom.get('column', 0)].open('rb') as f:
                f.seek(lo)
                data = f.read(hi - lo)
            require(len(data) == hi - lo and _sha(data) == case['original']['raw'], 'M4 real canonical input does not match M3')
            (work / 'original').write_bytes(data)


def _prepare_programs(root, run, plan):
    programs = {}
    for arm, assets in plan['assets'].items():
        folder = run / 'runtime' / arm
        folder.mkdir(parents=True)
        for ref in assets:
            p = checked_file(root, ref)
            out = folder / p.name
            shutil.copy2(p, out)
            checked_file(folder, {'path': out.name, 'bytes': ref['bytes'], 'sha256': ref['sha256']})
        programs[arm] = folder / Path(assets[0]['path']).name
    return programs


def _anchors(root, work, plan, programs, logs):
    for route, case in plan['inputs'].items():
        directory = work / route
        result = directory / 'native.frame'
        original = directory / 'original'
        if case['native_frame'] is not None:
            shutil.copyfile(checked_file(root, case['native_frame']), result)
        elif case['plugin'] == 'xz-baseline':
            wire = checked_file(root, case['reference']['sealed_bmk_frame']).read_bytes()
            sizes = _frame_cost(wire, case['plugin'], case['original'])
            result.write_bytes(wire[32 + sizes['schema_bytes']:])
        else:
            trial = {'case': route, 'mode': 'timing_only', 'capacity': 0}
            _run(programs['plain'], trial, 'encode', case['original']['raw']['bytes'], original, result, logs, 'alp-anchor-encode')
        require(_sha(_artifact(result.read_bytes(), case)) == case['expected_m3_frame'],
                f'{route} native product does not map exactly to frozen M3 frame')


def _try(root, run, plan, trial, programs, schema):
    case = plan['inputs'][trial['case']]
    mode, slot = trial['mode'], trial['slot']
    logs = run / 'logs'
    products = run / 'cases' / trial['case']
    anchor, original = (products / name for name in ('native.frame', 'original'))
    program = programs['plain' if mode == 'timing_only' else 'profile']
    facts = []
    n = case['original']['raw']['bytes']
    for op in DIRECTIONS:
        src, want = (original, anchor) if op == 'encode' else (anchor, original)
        output = products / (slot + '-' + op)
        label = slot + '-' + op
        proc = _run(program, trial, op, n, src, output, logs, label)
        size = _sha(output.read_bytes())
        expected = _sha(want.read_bytes())
        require(size == expected, f'M4 {trial["case"]} {mode} {op} does not match the fixed M3 input or frame')
        doc = _snapshot(logs / f'{label}.stdout')
        obs = _check_native(doc, proc, op, trial, case['original']['raw'],
                            {'bytes': anchor.stat().st_size}, schema)
        _check_link(case, op, obs)
        output.unlink()
        facts.append({'direction': op, 'output': size, 'input': _sha(src.read_bytes()), 'process': proc})
    return {'slot': slot, 'operations': facts, 'status': 'verified'}


def execute(root, plan, dest):
    root = root.resolve(strict=True)
    a, z, x = (plan['inputs'][k] for k in ROUTES)
    g, j, k = a['geometry'], z['reference'], x['reference']
    frozen = freeze(root, m3=checked_file(root, plan['m3_plan']), build=checked_file(root, plan['build']),
                    alp=(a['dataset_id'], g['column'], g['row_range'][0], checked_file(root, a['reference']['plan']), root / a['reference']['run']),
                    zstd=(z['dataset_id'], checked_file(root, j['plan']), root / j['run']),
                    xz=(x['dataset_id'], x['geometry']['byte_range'][0], root / k['timing_run']),
                    cpus=[r['cpu'] for r in plan['environment']], overlap=plan['overlap_run'])
    require(frozen == plan, 'M4 execution plan no longer matches source evidence')
    dest = dest.resolve()
    require(dest.is_relative_to(root), 'M4 outputs must remain in project')
    with resource.reserve():
        dest.mkdir(parents=True, exist_ok=True)
        run = dest / uuid.uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        shutil.copyfile(checked_file(root, plan['trace_schema']), run / 'trace.schema.json')
        schema = compile_contract('trace', load_json(run / 'trace.schema.json'))
        programs = _prepare_programs(root, run, plan)
        logs = run / 'logs'
        logs.mkdir()
        work = run / 'cases'
        _stage_values(root, plan, work)
        with _pinned([r['cpu'] for r in plan['environment']]), (run / 'trials.jsonl').open('xb') as stream:
            before = _env(root, plan)
            _anchors(root, work, plan, programs, logs)
            for trial in plan['schedule']:
                _line(stream, _try(root, run, plan, trial, programs, schema))
            after = _env(root, plan)
        write_new(run / 'environment.json', {'before': before, 'after': after})
        evidence = sorted(p for p in run.rglob('*') if p.is_file())
        body = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [reference(run, p) for p in evidence]}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
        report = recompute(run)
        write_new(run / 'report.json', report)
        return run


def recompute(run):
    run = run.resolve(strict=True)
    seal = load_json(run / 'completion.json')
    _id(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name, 'M4 invalid run seal')
    files = {r['path']: r for r in seal['files']}
    require(len(files) == len(seal['files']), 'M4 duplicate sealed paths')
    used = set()

    def get(path):
        require(path in files, f'M4 required evidence missing: {path}')
        used.add(path)
        return checked_file(run, files[path])

    plan = load_json(get('plan.json'))
    _id(plan, 'plan_content_id')
    require(plan['schema'] == PLAN and plan['plan_content_id'] == seal['plan_content_id'] and plan['schedule'] == _schedule() and
            plan['formal_performance'] is False and plan['qualification_granted'] is False, 'M4 sealed plan differs')
    for arm, assets in plan['assets'].items():
        for ref in assets:
            staged = get(f"runtime/{arm}/{Path(ref['path']).name}")
            require(_sha(staged.read_bytes()) == {k: ref[k] for k in ('bytes', 'sha256')}, 'M4 staged profile binary differs')
    schema_path = get('trace.schema.json')
    require(digest(schema_path) == plan['trace_schema']['sha256'], 'M4 closed trace schema differs')
    schema = compile_contract('trace', load_json(schema_path))
    env = load_json(get('environment.json'))
    for snapshot in env.values():
        require(snapshot['cpus'] == sorted(e['cpu'] for e in plan['environment']) and
                (snapshot['overlap'] or {}).get('path') == plan['overlap_run'], 'M4 recorded affinity or overlap differs')
    anchor = {}
    for route, case in plan['inputs'].items():
        _id(case, 'case_content_id')
        raw, native = (get(f'cases/{route}/{n}').read_bytes() for n in ('original', 'native.frame'))
        require(_sha(raw) == case['original']['raw'] and _sha(_artifact(native, case)) == case['expected_m3_frame'],
                'M4 retained canonical input or native frame differs')
        anchor[route] = _sha(native)
    get('logs/alp-anchor-encode.stdout')
    require(get('logs/alp-anchor-encode.stderr').stat().st_size == 0, 'M4 anchor diagnostic failed')
    measurements, seen = [], set()
    for trial, row in zip(plan['schedule'], _rows(get('trials.jsonl')), strict=True):
        require(row['slot'] == trial['slot'] and row['status'] == 'verified' and
                [d['direction'] for d in row['operations']] == list(DIRECTIONS), 'M4 ledger schedule differs')
        route = trial['case']
        case = plan['inputs'][route]
        raw, frame = case['original']['raw'], anchor[route]
        observations = []
        for event in row['operations']:
            op, proc = event['direction'], event['process']
            want = (raw, frame) if op == 'encode' else (frame, raw)
            label = f"{trial['slot']}-{op}"
            require(proc['operation'] == label and proc['status'] == 'completed' and proc['returncode'] == 0 and
                    proc['pid'] > 0 and proc['session_id'] not in seen and (event['input'], event['output']) == want and
                    get(f'logs/{label}.stderr').stat().st_size == 0, 'M4 action recovery or process identity differs')
            seen.add(proc['session_id'])
            obs = _check_native(_snapshot(get(f'logs/{label}.stdout')), proc, op, trial, raw, frame, schema)
            _check_link(case, op, obs)
            observations.append(obs)
        measurements.append({**trial, 'status': 'verified', 'observations': observations})
    require(used == set(files), 'M4 seal has undeclared evidence')
    return {'schema': 'bmk.m4-real-profile-report/1', 'run_id': run.name, 'seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], 'verified_operations': len(seen), 'inputs': plan['inputs'],
            'trials': measurements, 'perturbation': _repeats(measurements), 'environment': env,
            'extent': EXTENT, 'scope': 'independent_native_diagnostics_not_a_framework_overhead_subtraction',
            'pristine_driver_boundaries_differ_from_m3': 'no_abi_wrap_or_ingress_clock_and_zstd_buffered_write',
            'formal_performance': False, 'qualification_granted': False, 'stage_accepted': False}
