"""Repeat Sprintz FIRE SFB1 encode, decode and compressed-domain query on r40 evidence."""
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
from random import Random
import os
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require, verify_asset
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import BACKEND, HEADER, ROWS, _oracle, _read_frame, _stage
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-sprintz-query-repeat/1'
TOOL = 'sprintz-query'
OPS = ('encode', 'decode', 'query')
ROUNDS = 3
LIMITS = {'address_space_bytes': 512 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 60}
UNMEASURED = ('formal_system_exclusivity', 'standalone_query_backend_process_wall', 'full_source_pipeline_wall')
COLD = 'fresh_process_context_natural_os_cache'
PROTOCOL = ('src/tsbench/application/m3_sprintz_timing.py', 'src/tsbench/application/m3_sprintz_query.py',
            'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py',
            'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/application/m3_sealed_ledger.py',
            'src/tsbench/application/m3_metric_details.py', 'src/tsbench/corpus_ingress.py',
            'tools/m3_sprintz_query_timing.py')


def ref(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def relative(root, path):
    return {'path': path.relative_to(root).as_posix(), **ref(path)}


def check(root, item):
    p = verify_asset(root, item)
    require(p.stat().st_size == item['bytes'], 'Sprintz repeat asset size differs')
    return p


def schedule():
    rng = Random(20261120)
    return [{'round': i, 'phase': 'warmup' if i == 0 else 'measured', 'operation': op}
            for i in range(ROUNDS + 1) for op in rng.sample(OPS, len(OPS))]


def _facts(row):
    return {k: v for k, v in row.items() if k != 'native_wall_ns'}


def freeze(root, source_plan, run, scope, cpu):
    require(scope in ('retained', 'whole-bounded'), 'invalid Sprintz repeat scope')
    plan = load_json(source_plan)
    ledger, seal = full_run_source(plan, run)
    spec = plan['build']['sprintz_query']
    for item in spec.values():
        check(root, item)
    definition = load_json(check(root, plan['definition']['plan']))
    entries = _entry_map(root, definition)
    cases, excluded = [], []
    for row, item in full_run_rows(plan, ledger):
        if item is None or 'entry_kind' in row or row.get('selection') != 19 or row.get('route') != 'query':
            continue
        dataset = row['dataset_id']
        if row['status'] != 'verified':
            excluded.append({'dataset_id': dataset, 'reason': row['status']})
            continue
        evidence, extent = row['evidence'], item['input']
        entry = entries[dataset]
        rows, cols = entry['rows'], entry['value_count']
        units = evidence['units']
        require(rows == evidence['rows'] and cols == evidence['columns'] and
                extent['full_extent_of_file_rows_and_value_columns'] and
                [(u['column'], u['row_start'], u['row_end']) for u in units] ==
                [(c, s, min(rows, s + ROWS)) for c in range(cols) for s in range(0, rows, ROWS)] and
                len(units) == extent['size_estimate']['input_units'], 'Sprintz frozen query extent differs')
        sample = evidence['retained_sample']
        require(sample['observation'] == units[0] and sample['sha256'] == units[0]['frame_sha256'] and
                sample['bytes'] == units[0]['frame_bytes'], 'Sprintz query retained reference differs')
        if scope == 'whole-bounded' and max(evidence['artifact_bytes'], rows * 8, len(units) * 1024) > LIMITS['file_bytes']:
            excluded.append({'dataset_id': dataset, 'reason': 'bounded_isolated_control_per_file_limit'})
            continue
        if scope == 'retained':
            rows, cols, units = units[0]['row_end'], 1, units[:1]
        require(sum(u['raw_bytes'] for u in units) == rows * cols * 8 and
                all(u['frame_bytes'] == HEADER.size + u['payload_bytes'] for u in units),
                'Sprintz logical input or frame charge differs')
        case = {'dataset_id': dataset, 'work_item_id': item['work_item_id'], 'configuration': item['input'],
                'canonical_object_id': item['canonical_object_id'], 'source_file': entry['file'],
                'reference_sample': relative(root, check(run, sample)), 'rows': rows, 'columns': cols,
                'units': [_facts(u) for u in units], 'workspace_bytes': evidence['codec_workspace_bytes']}
        cases.append({**case, 'case_id': content_id(case)})
    require(cases, 'no eligible Sprintz timing cases')
    decoder = plan_recovery(root, {}, [], tools={TOOL: {k: spec['executable'][k] for k in ('path', 'sha256')}},
                            libraries=[spec['dependency']])
    body = {'schema': SCHEMA, 'scope': scope, 'source_plan': relative(root, source_plan), 'source_seal': seal,
            'source_run': run.relative_to(root).as_posix(), 'environment': resource.environment(cpu), 'runtime': decoder,
            'launchers': launcher_lock(), 'limits': LIMITS, 'schedule': schedule(), 'lifecycle': COLD,
            'protocol': {p: digest(local_file(root, p)) for p in PROTOCOL}, 'cases': cases, 'excluded': excluded}
    return {**body, 'plan_id': content_id(body)}


def _invoke(bundle, plan, case, work, op, inputs):
    work.mkdir()
    inp = '/inputs' if op == 'encode' else '/inputs/archive.sfb1'
    target = {'encode': '/out/archive.sfb1', 'decode': '/out', 'query': '-'}[op]
    cols, rows = str(case['columns']), str(case['rows'])
    out, process = invoke_isolated_tool(bundle, plan['runtime'], TOOL, LIMITS, work, work, op, inputs,
                                       [op, inp, cols, rows, target], lambda: False,
                                       observe=True, file_ceiling=LIMITS['file_bytes'])
    log = work / (op + '.stdout')
    error = work / (op + '.stderr')
    require(process['status'] == 'completed' and process['returncode'] == 0 and not error.stat().st_size,
            f"isolated Sprintz {op}: {process['status']}: {error.read_text()[:400]}")
    return out, process, load_json(log)


def _column_names(case):
    return [f'column-{i:04d}.bin' for i in range(case['columns'])]


def _verify_archive(case, archive):
    require(archive.stat().st_size == sum(u['frame_bytes'] for u in case['units']), 'Sprintz repeated archive size differs')
    with archive.open('rb') as stream:
        for u in case['units']:
            wire = _read_frame(stream)
            require(len(wire) == u['frame_bytes'] and sha256(wire).hexdigest() == u['frame_sha256'],
                    'Sprintz historical SFB1 frame hash differs')
        require(not stream.read(1), 'Sprintz repeated archives have trailing bytes')
    return ref(archive)


def _verify_columns(case, out, *, oracle=False):
    require({p.name for p in out.iterdir()} == set(_column_names(case)), 'Sprintz restored column set differs')
    result = {}
    at = 0
    for name in _column_names(case):
        path = local_file(out, name)
        with path.open('rb') as source:
            for _ in range(0, case['rows'], ROWS):
                u = case['units'][at]
                bits = source.read(u['raw_bytes'])
                require(len(bits) == u['raw_bytes'] and sha256(bits).hexdigest() == u['restored_sha256'],
                        'Sprintz repeated column differs from sealed original bits')
                if oracle:
                    expected = _oracle(bits)
                    require(all(u[mode] == {"backend": backend, **expected} for mode, backend in
                                (("auto", "upstream_simd"), ("scalar", "scalar"))),
                            "Sprintz sealed reductions differ from independent u16 oracle")
                at += 1
            require(not source.read(1), 'Sprintz repeated columns have trailing bytes')
        result[name] = ref(path)
    require(at == len(case['units']), 'Sprintz repeated columns are incomplete')
    return result


def _native(case, op, doc):
    require(doc['backend'] == BACKEND and doc['workspace_bytes'] == case['workspace_bytes'] and
            len(doc['units']) == len(case['units']), 'Sprintz repeated backend, workspace or unit count differs')
    modes = ('auto', 'scalar') if op == 'query' else (op,)
    times = Counter()
    for native, u in zip(doc['units'], case['units'], strict=True):
        require(all(native[k] == u[k] for k in ('column', 'row_start', 'raw_bytes', 'frame_bytes')),
                'Sprintz repeated native geometry differs')
        if op == 'query':
            require(all(native[m] == u[m] for m in modes), 'Sprintz repeated native reduction differs')
        for m in modes:
            ns = native[m + '_wall_ns']
            require(type(ns) is int and ns > 0, 'Sprintz repeated native latency is absent')
            times[m] += ns
    return dict(times)


def _prepare(root, bundle, plan, case, work, entries):
    sample = check(root, case['reference_sample'])
    stage = work / 'stage'
    if plan['scope'] == 'retained':
        out, _, _ = _invoke(bundle, plan, case, work / 'recover-historical', 'decode', {'archive.sfb1': sample})
        stage = out
        archive = sample
    else:
        _stage(root, entries[case['dataset_id']], stage)
        inputs = {name: stage / name for name in _column_names(case)}
        out, _, _ = _invoke(bundle, plan, case, work / 'reconstruct', 'encode', inputs)
        archive = out / 'archive.sfb1'
    columns = _verify_columns(case, stage, oracle=True)
    art = _verify_archive(case, archive)
    return {'columns': columns, 'archive': art}, stage, archive


def _trial(bundle, plan, case, prep, stage, archive, t, work):
    op = t['operation']
    inputs = ({name: stage / name for name in prep['columns']} if op == 'encode' else {'archive.sfb1': archive})
    start = monotonic_ns()
    out, process, doc = _invoke(bundle, plan, case, work, op, inputs)
    if op == 'encode':
        require({p.name for p in out.iterdir()} == {'archive.sfb1'}, 'unexpected Sprintz encode output')
        verified = _verify_archive(case, out / 'archive.sfb1')
    elif op == 'decode':
        verified = _verify_columns(case, out)
    else:
        require(not any(out.iterdir()), 'unexpected Sprintz query output')
        verified = None
    ns = _native(case, op, doc)
    outer = monotonic_ns() - start
    return {'case_id': case['case_id'], **t, 'process': process, 'native': doc, 'native_totals_ns': ns,
            'supervision_and_verification_wall_ns': outer, 'verified_output': verified}


def _validate(case, t, row, prep, seen):
    op = t['operation']
    proc = row['process']
    expected_mounts = prep['columns'] if op == 'encode' else {'archive.sfb1': prep['archive']}
    expected_output = {'encode': prep['archive'], 'decode': prep['columns'], 'query': None}[op]
    native = _native(case, op, row['native'])
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()) and
            row['verified_output'] == expected_output and row['native_totals_ns'] == native and
            proc['input_mounts'] == expected_mounts and proc['operation'] == op and proc['status'] == 'completed' and
            proc['returncode'] == 0 and not proc['reason'] and proc['session_id'] and proc['session_id'] not in seen and
            type(proc['pid']) is int and proc['pid'] > 0 and proc['child_usage']['maxrss_bytes'] > 0 and
            0 < sum(native.values()) <= proc['process_wall_ns'] <= row['supervision_and_verification_wall_ns'],
            'Sprintz repeated mounts, outputs, clocks or process identity differ')
    seen.add(proc['session_id'])


def _summary(case, rows):
    charge = sum(u['frame_bytes'] for u in case['units'])
    payload = sum(u['payload_bytes'] for u in case['units'])
    logical = case['rows'] * case['columns'] * 8
    result = {}
    for op in OPS:
        clocks = defaultdict(list)
        for r in rows:
            if r['phase'] != 'measured' or r['operation'] != op:
                continue
            proc = r['process']
            for mode, elapsed in r['native_totals_ns'].items():
                clocks['native_' + mode + '_wall_ns'].append(elapsed)
            clocks['process_wall_ns'].append(proc['process_wall_ns'])
            clocks['staged_supervision_and_verification_wall_ns'].append(r['supervision_and_verification_wall_ns'])
            for k in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'):
                clocks[k].append(proc['child_usage'][k])
        result[op] = {'repeat_distributions': {k: {**distribution(v), "sample_basis": COLD} for k, v in clocks.items()},
                      'logical_mib_per_second': {k: logical * len(v) * 1e9 / (sum(v) * (1 << 20))
                                                 for k, v in clocks.items() if k.endswith('_wall_ns') and op != 'query'}}
    return {'case_id': case['case_id'], 'dataset_id': case['dataset_id'], 'work_item_id': case['work_item_id'],
            'row_range': [0, case['rows']], 'value_column_range': [0, case['columns']], 'units': len(case['units']),
            'logical_bytes': logical, 'artifact_bytes': charge, 'header_bytes': charge - payload,
            'payload_bytes': payload, 'ratio': logical / charge, 'directions': result}


def verify(run):
    plan = load_json(local_file(run, 'plan.json'))
    seal = load_json(local_file(run, 'completion.json'))
    require(plan['schema'] == SCHEMA and plan['plan_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_id'}) and
            plan['schedule'] == schedule() and plan['limits'] == LIMITS and plan['lifecycle'] == COLD and
            seal['plan_id'] == plan['plan_id'] and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json', 'preparation.json', 'environment.json', 'trials.jsonl'},
            'Sprintz repeat plan or completion seal differs')
    for f in seal['files'].values():
        check(run, f)
    for name, item in plan['runtime']['files'].items():
        check(run, {'path': 'runtime/' + name, **{k: item[k] for k in ('bytes', 'sha256')}})
    env = load_json(run / 'environment.json')
    require(env['affinity'] == [plan['environment']['cpu']], 'Sprintz repeat CPU affinity differs')
    prep = load_json(run / 'preparation.json')
    require(prep.keys() == {c['case_id'] for c in plan['cases']}, 'Sprintz preparation scope differs')
    seen, results = set(), []
    with (run / 'trials.jsonl').open('rb') as stream:
        for case in plan['cases']:
            require(case['case_id'] == content_id({k: v for k, v in case.items() if k != 'case_id'}),
                    'Sprintz repeat case ID differs')
            rows = []
            for t in plan['schedule']:
                r = parse_json(stream.readline(), 'Sprintz repeat trial')
                _validate(case, t, r, prep[case['case_id']], seen)
                rows.append(r)
            results.append(_summary(case, rows))
        require(not stream.read(1), 'extra Sprintz repeat trials')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'seal_id': seal['seal_id'],
            'source_seal': plan['source_seal'], 'scope': plan['scope'], 'environment': env, 'results': results,
            'native_threads': 1, 'query_modes': ['upstream_simd', 'scalar'], 'query_scope': 'four_unsigned_u16_limbs_not_f64',
            'query_process_order': 'auto_then_scalar_per_frame_shared_process_not_independent_pipeline',
            'not_measured': list(UNMEASURED), 'excluded': plan['excluded'], 'verified_trials': len(seen),
            'historical_retained_frames_recovered': len(results) if plan['scope'] == 'retained' else 0,
            'qualification_granted': False, 'formal_performance': False, 'stage_accepted': False}


def execute(root, plan, output):
    require(output.is_relative_to(root), 'Sprintz repeat output is outside project')
    source = local_file(root, plan['source_plan']['path'])
    source_run = (root / plan['source_run']).resolve(strict=True)
    require(source_run.is_relative_to(root) and
            freeze(root, source, source_run, plan['scope'], plan['environment']['cpu']) == plan,
            'Sprintz repeat plan no longer matches source, runtime, policy or host')
    definition = load_json(check(root, load_json(source)['definition']['plan']))
    entries = _entry_map(root, definition)
    cpu = plan['environment']['cpu']
    output.mkdir(parents=True, exist_ok=True)
    with resource.reserve():
        run = output / uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        affinity = os.sched_getaffinity(0)
        prep, seen = {}, set()
        try:
            os.sched_setaffinity(0, {cpu})
            env = {'affinity': sorted(os.sched_getaffinity(0)), 'before': resource.observe(cpu)}
            with (run / 'trials.jsonl').open('xb') as ledger:
                for case in plan['cases']:
                    with TemporaryDirectory(prefix='sprintz-', dir=run) as tmp:
                        work = Path(tmp)
                        ready, stage, archive = _prepare(root, run / 'runtime', plan, case, work, entries)
                        prep[case['case_id']] = ready
                        for i, t in enumerate(plan['schedule']):
                            row = _trial(run / 'runtime', plan, case, ready, stage, archive, t, work / str(i))
                            _validate(case, t, row, ready, seen)
                            _line(ledger, row)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0, affinity)
        write_new(run / 'preparation.json', prep)
        write_new(run / 'environment.json', env)
        seal = {'schema': SCHEMA + '-seal', 'run_id': run.name, 'plan_id': plan['plan_id'],
                'files': {name: relative(run, run / name) for name in
                          ('plan.json', 'preparation.json', 'environment.json', 'trials.jsonl')}}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
    write_new(run / 'report.json', verify(run))
    return run
