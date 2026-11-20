"""Exact whole-file SFB1 diagnostics with separate native and durable file clocks."""
from collections import defaultdict
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import HEADER, ROWS, _stage
from .m3_sprintz_timing import (LIMITS, OPS, ROUNDS, _column_names, _native, _verify_archive, _verify_columns,
                                check, ref, relative, schedule)
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-sprintz-durable-corpus/1'
TOOL = 'sprintz-grouped'
GROUP_BYTES = 6 << 20
CODE = ('src/tsbench/application/m3_sprintz_durable.py', 'tools/m3_sprintz_durable.py',
        'src/tsbench/application/m3_sprintz_timing.py', 'src/tsbench/application/m3_sprintz_query.py',
        'src/tsbench/application/m3_sealed_ledger.py', 'src/tsbench/corpus_ingress.py',
        'src/tsbench/application/m3_metric_details.py', 'src/tsbench/recovery.py',
        'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/supervisor/isolated_worker.py', 'plugins/codecs/sprintz-fire/corpus_query_control.cpp',
        'plugins/codecs/sprintz-fire/native_profile.hpp', 'native/measurement/sprintz_grouped/CMakeLists.txt')
POLICY = {'sample': 'one_fresh_isolated_process_per_whole_file_direction_round', 'native_context': 'one_per_whole_file',
          'encode': 'locked_original_ingress_stage_encode_verify_fsync_outputs',
          'decode': 'immutable_verified_archive_decode_verify_fsync_canonical_value_columns',
          'query': 'immutable_verified_archive_both_native_reductions_verify_no_durable_output',
          'durability': 'fsync_outputs_and_parent_directories_not_crash_recovery_proof',
          'untimed': 'reference_archive_reconstruction_preflight_and_trial_directory_cleanup'}


def archive_name(ordinal):
    return f'archive-{ordinal:04d}.sfb1'


def groups(rows, cols, units):
    """Partition only between complete columns, preserving every native frame."""
    stride = (rows + ROWS - 1) // ROWS
    require(rows * 8 <= LIMITS['file_bytes'] and len(units) == cols * stride and len(units) * 1024 < LIMITS['file_bytes'],
            'Sprintz column or JSON observation exceeds isolation limit')
    first, length, out = 0, 0, []
    for c in range(cols):
        n = sum(u['frame_bytes'] for u in units[c*stride:(c+1)*stride])
        require(0 < n <= GROUP_BYTES, 'Sprintz one column exceeds archive extent limit')
        if length + n > GROUP_BYTES:
            out.append({'name': archive_name(len(out)), 'columns': [first, c], 'bytes': length})
            first, length = c, 0
        length += n
    require(length > 0, 'Sprintz does not allow an empty file in this diagnostic')
    return [*out, {'name': archive_name(len(out)), 'columns': [first, cols], 'bytes': length}]


def freeze(root, source, source_run, worker, cpu):
    plan = load_json(source)
    ledger, seal = full_run_source(plan, source_run)
    entries = _entry_map(root, load_json(check(root, plan['definition']['plan'])))
    cases, missing = [], []
    for row, item in full_run_rows(plan, ledger):
        if item is None or 'entry_kind' in row or (row.get('selection'), row.get('route')) != (19, 'query'):
            continue
        dataset = row['dataset_id']
        if row['status'] != 'verified':
            missing.append({'dataset_id': dataset, 'status': row['status'], 'reason': row['reason']})
            continue
        p, e, extent = row['evidence'], entries[dataset], item['input']
        rows, cols = e['rows'], e['value_count']
        units = [{k: v for k, v in u.items() if k != 'native_wall_ns'} for u in p['units']]
        require((p['rows'], p['columns']) == (rows, cols) and extent['full_extent_of_file_rows_and_value_columns'] and
                item['canonical_object_id'] == e['canonical']['object_id'] and
                [(u['column'], u['row_start'], u['row_end']) for u in units] ==
                [(c, a, min(rows, a+ROWS)) for c in range(cols) for a in range(0, rows, ROWS)] and
                all(u['raw_bytes'] == (u['row_end']-u['row_start'])*8 and u['frame_bytes'] == HEADER.size+u['payload_bytes']
                    for u in units) and p['input_bytes'] == rows*cols*8 and p['artifact_bytes'] == sum(u['frame_bytes'] for u in units),
                'Sprintz full extent, input identity or wire costs differ from r40')
        case = {'dataset_id': dataset, 'work_item_id': item['work_item_id'], 'canonical_object_id': item['canonical_object_id'],
                'source_file': e['file'], 'configuration': extent, 'rows': rows, 'columns': cols, 'units': units,
                'groups': groups(rows, cols, units), 'workspace_bytes': p['codec_workspace_bytes']}
        cases.append({**case, 'case_id': content_id(case)})
    require(cases, 'no verified Sprintz query cases')
    lib = plan['build']['sprintz_query']['dependency']
    check(root, lib)
    exe = relative(root, worker)
    runtime = plan_recovery(root, {}, [], tools={TOOL: {k: exe[k] for k in ('path', 'sha256')}}, libraries=[lib])
    tool, = runtime['tools'].values()
    require(Path(lib['path']).name in runtime['files'][tool]['needed'], 'grouped Sprintz worker does not link frozen codec')
    body = {'schema': SCHEMA, 'source': relative(root, source), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'worker': exe, 'runtime': runtime, 'launchers': launcher_lock(),
            'limits': LIMITS, 'policy': POLICY, 'schedule': schedule(), 'cases': cases, 'excluded': missing,
            'environment': resource.environment(cpu), 'code': {p: digest(local_file(root, p)) for p in CODE}}
    return {**body, 'plan_id': content_id(body)}


def verify_archives(case, directory):
    require({p.name for p in directory.iterdir()} == {g['name'] for g in case['groups']}, 'Sprintz archive file set differs')
    stride = (case['rows'] + ROWS - 1) // ROWS
    refs = {}
    for g in case['groups']:
        a, b = g['columns']
        obj = {'units': case['units'][a*stride:b*stride]}
        refs[g['name']] = _verify_archive(obj, local_file(directory, g['name']))
        require(refs[g['name']]['bytes'] == g['bytes'], 'Sprintz archive group charge differs')
    return refs


def invoke(bundle, plan, case, op, paths, work):
    work.mkdir()
    ends = ','.join(str(g['columns'][1]) for g in case['groups'])
    argv = [op, '/inputs', str(case['columns']), str(case['rows']), '-' if op == 'query' else '/out', ends]
    out, proc = invoke_isolated_tool(bundle, plan['runtime'], TOOL, LIMITS, work, work, op, paths, argv, lambda: False,
                                     observe=True, file_ceiling=LIMITS['file_bytes'])
    err = (work / (op + '.stderr')).read_text()
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and not err,
            f"Sprintz grouped {case['dataset_id']}/{op}: {proc['status']}: {err[:400]}")
    return out, proc, load_json(work / (op + '.stdout'))


def sync_outputs(out, names):
    for name in names:
        with local_file(out, name).open('rb') as f:
            os.fsync(f.fileno())
    for directory in (out, out.parent, out.parent.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def prepare(root, bundle, plan, case, entry, path):
    path.mkdir()
    _stage(root, entry, path / 'stage')
    staged = _verify_columns(case, path / 'stage', oracle=True)
    inputs = {col: path / 'stage' / col for col in staged}
    fixed, p, doc = invoke(bundle, plan, case, 'encode', inputs, path / 'reference')
    require(p['input_mounts'] == staged and _native(case, 'encode', doc), 'Sprintz reference wrapper evidence differs')
    archive = verify_archives(case, fixed)
    return fixed, {'columns': staged, 'archives': archive}


def trial(root, bundle, plan, case, entry, fixed, ready, t, work):
    op = t['operation']
    start = monotonic_ns()
    ingress = None
    if op == 'encode':
        _stage(root, entry, work / 'stage')
        paths = {name: work / 'stage' / name for name in ready['columns']}
        ingress = monotonic_ns() - start
    else:
        paths = {name: fixed / name for name in ready['archives']}
    out, proc, doc = invoke(bundle, plan, case, op, paths, work / 'operation')
    if op == 'encode':
        output = verify_archives(case, out)
    elif op == 'decode':
        output = _verify_columns(case, out)
    else:
        require(not any(out.iterdir()), 'Sprintz query created unexpected output')
        output = None
    native = _native(case, op, doc)
    flush = None
    if output is not None:
        tick = monotonic_ns()
        sync_outputs(out, output)
        flush = monotonic_ns() - tick
    return {'case_id': case['case_id'], **t, 'process': proc, 'native': doc, 'native_totals_ns': native,
            'source_ingress_and_staging_wall_ns': ingress, 'output_fsync_wall_ns': flush,
            'whole_operation_wall_ns': monotonic_ns()-start, 'verified_output': output}


def validate(case, t, row, ready, seen):
    op, p = t['operation'], row['process']
    native = _native(case, op, row['native'])
    wall, ingest, flush = (row[k] for k in ('whole_operation_wall_ns', 'source_ingress_and_staging_wall_ns', 'output_fsync_wall_ns'))
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()) and native == row['native_totals_ns'] and
            p['input_mounts'] == ready['columns' if op == 'encode' else 'archives'] and p['operation'] == op and
            row['verified_output'] == {'encode': ready['archives'], 'decode': ready['columns'], 'query': None}[op] and
            p['status'] == 'completed' and p['returncode'] == 0 and not p['reason'] and isinstance(p['session_id'], str) and
            p['session_id'] and p['session_id'] not in seen and p['pid'] > 0 and p['child_usage']['maxrss_bytes'] > 0 and
            (type(ingest) is int and ingest > 0 if op == 'encode' else ingest is None) and
            (flush is None if op == 'query' else type(flush) is int and flush > 0) and
            0 < sum(native.values()) <= p['process_wall_ns'] <= wall-(ingest or 0)-(flush or 0),
            'Sprintz whole-file clock, direction, mount or output differs')
    seen.add(p['session_id'])


def report_case(case, rows):
    logical = case['rows'] * case['columns'] * 8
    charge = sum(u['frame_bytes'] for u in case['units'])
    payload = sum(u['payload_bytes'] for u in case['units'])
    directions = {}
    for op in OPS:
        d = defaultdict(list)
        chosen = [r for r in rows if r['phase'] == 'measured' and r['operation'] == op]
        require(len(chosen) == ROUNDS, 'Sprintz diagnostic repeat scope differs')
        for r in chosen:
            process = r['process']
            for mode, ns in r['native_totals_ns'].items():
                d[f'native_{mode}_wall_ns'].append(ns)
            d['process_wall_ns'].append(process['process_wall_ns'])
            for k, value in process['child_usage'].items():
                d['supervised_child_' + k].append(value)
            for k in ('source_ingress_and_staging_wall_ns', 'output_fsync_wall_ns', 'whole_operation_wall_ns'):
                if r[k] is not None:
                    d[k].append(r[k])
        directions[op] = {'distributions': {k: {**distribution(v), 'sample_basis': POLICY['sample']} for k, v in d.items()},
                          'mib_per_second': {k: logical * ROUNDS * 1e9 / ((1 << 20)*sum(d[k])) for k in
                                             (f'native_{op}_wall_ns', 'process_wall_ns', 'whole_operation_wall_ns')} if op != 'query' else None}
    return {'dataset_id': case['dataset_id'], 'work_item_id': case['work_item_id'], 'configuration': case['configuration'],
            'rows': [0, case['rows']], 'columns': [0, case['columns']], 'logical_bytes': logical,
            'source_file_bytes': case['source_file']['bytes'], 'payload_bytes': payload, 'header_bytes': charge-payload,
            'complete_artifact_bytes': charge, 'ratio': logical/charge, 'units': len(case['units']),
            'archive_files': case['groups'], 'query': {'scope': 'all_four_u16_limbs_not_f64', 'order': ['upstream_simd', 'scalar'],
                'compressed_bytes_scanned_once_for_both_modes': charge, 'physical_read_bytes': None}, 'directions': directions}


def verify(run):
    plan, seal = (load_json(local_file(run, n)) for n in ('plan.json', 'completion.json'))
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['schedule'] == schedule() and plan['limits'] == LIMITS and
            plan['plan_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_id'}) and seal['schema'] == SCHEMA + '-seal' and
            seal['plan_id'] == plan['plan_id'] and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json', 'environment.json', 'reference.json', 'trials.jsonl'}, 'Sprintz durable seal differs')
    for f in seal['files'].values():
        check(run, f)
    for n, a in plan['runtime']['files'].items():
        check(run, {'path': 'runtime/' + n, 'bytes': a['bytes'], 'sha256': a['sha256']})
    env = load_json(run / 'environment.json')
    require(env['affinity'] == [plan['environment']['cpu']], 'Sprintz durable CPU affinity differs')
    refs = load_json(run / 'reference.json')
    require(refs.keys() == {c['case_id'] for c in plan['cases']}, 'Sprintz reference case set differs')
    seen, result = set(), []
    with (run / 'trials.jsonl').open('rb') as stream:
        for case in plan['cases']:
            require(case['case_id'] == content_id({k: v for k, v in case.items() if k != 'case_id'}) and
                    case['groups'] == groups(case['rows'], case['columns'], case['units']), 'Sprintz durable case groups differ')
            ready = refs[case['case_id']]
            require({k: v['bytes'] for k, v in ready['columns'].items()} == {n: case['rows']*8 for n in _column_names(case)} and
                    {k: v['bytes'] for k, v in ready['archives'].items()} == {g['name']: g['bytes'] for g in case['groups']},
                    'Sprintz reference extent differs')
            rows = []
            for t in plan['schedule']:
                r = parse_json(stream.readline(), 'Sprintz durable trial')
                validate(case, t, r, ready, seen)
                rows.append(r)
            result.append(report_case(case, rows))
        require(not stream.read(1), 'Sprintz durable run contains extra trials')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'source_seal': plan['source_seal'], 'seal_id': seal['seal_id'],
            'environment': env, 'policy': POLICY, 'verified_trials': len(seen), 'results': result, 'excluded': plan['excluded'],
            'not_measured': {'query_backend_standalone_process_cost': 'both query modes share process and archive traversal',
                             'overall_cpu_rss': 'only supervised child usage measured; parent ingest and fsync not included',
                             'system_exclusivity': 'cooperative reservation and affinity only'},
            'timing_admitted': False, 'qualification_granted': False, 'stage_accepted': False}


def execute(root, plan, output):
    source = check(root, plan['source'])
    source_run = (root / plan['source_run']).resolve(strict=True)
    cpu = plan['environment']['cpu']
    require(output.is_relative_to(root) and source_run.is_relative_to(root) and
            freeze(root, source, source_run, check(root, plan['worker']), cpu) == plan, 'Sprintz durable source/runtime changed')
    entries = _entry_map(root, load_json(check(root, load_json(source)['definition']['plan'])))
    output.mkdir(parents=True, exist_ok=True)
    with resource.reserve():
        run = output / uuid4().hex
        run.mkdir()
        print(f'run={run}', flush=True)
        write_new(run / 'plan.json', plan)
        bundle = run / 'runtime'
        stage_recovery(root, run, plan['runtime'], directory=bundle.name)
        affinity, seen, refs = os.sched_getaffinity(0), set(), {}
        try:
            os.sched_setaffinity(0, {cpu})
            env = {'affinity': sorted(os.sched_getaffinity(0)), 'before': resource.observe(cpu)}
            with (run / 'trials.jsonl').open('xb') as ledger:
                for case in plan['cases']:
                    entry = entries[case['dataset_id']]
                    with TemporaryDirectory(prefix='case-', dir=run) as name:
                        p = Path(name)
                        fixed, reference = prepare(root, bundle, plan, case, entry, p / 'prepare')
                        refs[case['case_id']] = reference
                        for t in plan['schedule']:
                            with TemporaryDirectory(prefix='trial-', dir=p) as temp:
                                row = trial(root, bundle, plan, case, entry, fixed, reference, t, Path(temp))
                                validate(case, t, row, reference, seen)
                                _line(ledger, row)
                    print(f"verified {case['dataset_id']} ({len(case['groups'])} archive files, {len(case['units'])} frames)", flush=True)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0, affinity)
        write_new(run / 'reference.json', refs)
        write_new(run / 'environment.json', env)
        seal = {'schema': SCHEMA + '-seal', 'plan_id': plan['plan_id'], 'run_id': run.name,
                'files': {n: relative(run, run / n) for n in ('plan.json', 'environment.json', 'reference.json', 'trials.jsonl')}}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
    write_new(run / 'report.json', verify(run))
    return run
