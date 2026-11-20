"""Repeat native packet-stream calls on exact frozen whole-column Titchy inputs."""
from collections import Counter
from pathlib import Path
import re
import shutil
import uuid

from ..assets import content_id, digest, load_json, local_file, require
from ..qualification.titchy_wire import decode_tstr
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_full_custody import _first_column
from .m3_lzbench_timing import _affinity, _file, _folder, _functional, _identity, _ref
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_titchy_stream import POLICY as NATIVE_POLICY, SPEC as NATIVE_SPEC, validate_stream
from .smoke import _line, _rows, utc, write_new

WARMUPS, ROUNDS = 2, 7
SCHEMA, SEAL = 'bmk.m3-titchy-stream-timing-plan/1', 'bmk.m3-titchy-stream-timing-seal/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}
DIRECTIONS = ('encode', 'decode')
PARTS = {'tstr': 'archive', 'tsc1': 'policy'}
TOOL = 'titchy-stream'
COST = ('artifact_bytes', 'payload_bytes', 'config_bytes', 'archive_framing_bytes', 'packets_before_finish',
        'first_packet_phase', 'finish_chunks', 'finish_logical_samples', 'padding_samples')
CLOCKS = {'wall_ns', 'first_packet_ns'}
POLICY = {'warmups': WARMUPS, 'measured_rounds': ROUNDS, 'unit': 'first_full_value_column_per_file_no_projected_row_window',
          'primary_clock': 'native_driver_push_pop_finish_or_archive_decode_excludes_io_setup_and_validation_replay',
          'process_clock': 'isolated_startup_and_file_io_includes_native_reset_and_backpressure_replay',
          'first_packet_clock': 'from_start_of_in_memory_push_loop_to_first_pop_excludes_io_and_replay',
          'decode_input': 'same_exact_tstr_and_tsc1_in_all_independent_trials', 'parallel_trials': 1,
          'affinity': 'inherited_one_cpu_no_system_exclusivity', 'cache': 'uncontrolled',
          'full_file_or_native_batch_comparison': False}


def _facts(doc):
    return {k: v for k, v in doc.items() if k not in CLOCKS}


def _ident(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def freeze(root, main_path, source_path, source_run, dataset_ids, cpu, overlap):
    root = root.resolve(strict=True)
    main_path, source_path, source_run = (p.resolve(strict=True) for p in (main_path, source_path, source_run))
    require(all(p.is_relative_to(root) for p in (main_path, source_path, source_run)), 'Titchy plan references must stay in project')
    main, source = load_json(main_path), load_json(source_path)
    for p in (main, source):
        _identity(p, 'plan_content_id')
    binding = main['build']['titchy_stream']
    require(binding == source['build']['titchy_stream'] and main['definition']['plan_content_id'] == source['definition']['plan_content_id'],
            'Titchy stream source and primary build/definition differ')
    for ref in binding.values():
        _file(root, ref)
    seal, raw_rows = _functional(source, source_run)
    wanted = {i['dataset_id']: i for i in main['work_items'] if i['route'] == 'packet-stream' and i['applicability'] == 'input_domain_matches'}
    require(not dataset_ids or len(set(dataset_ids)) == len(dataset_ids) and set(dataset_ids) <= set(wanted),
            'unknown or duplicated Titchy timing dataset')
    ref_rows = {r['work_item_id']: r for r in raw_rows if r.get('route') == 'packet-stream' and r.get('status') == 'verified'
                and 'work_item_id' in r}
    cases = []
    for ds in (dataset_ids or list(wanted)):
        work = wanted[ds]
        require(work['work_item_id'] in ref_rows and ref_rows[work['work_item_id']]['dataset_id'] == ds, 'Titchy has no exact verified work item')
        proof = ref_rows[work['work_item_id']]['evidence']
        n = work['input']['row_ranges'][0]['end']
        sample, u = proof['retained_sample'], proof['units'][0]
        require(proof['driver'] == 'titchy-stream-control/1' and sample['column'] == u['column'] == 0 and
                sample['row_range'] == u['row_range'] == [0, n] and n * 8 == u['logical_input_bytes'] and
                sample['restored_sha256'] == u['restored_sha256'] and sample['parts'].keys() == PARTS.keys(),
                'Titchy source unit is not a full frozen column sample')
        frame = {name: _file(source_run, ref).read_bytes() for name, ref in sample['parts'].items()}
        billing = validate_stream(n, frame['tstr'], frame['tsc1'], u['encode'], u['decode'])
        require(billing == {k: u[k] for k in COST} and sample['parts']['tstr']['sha256'] == u['archive_sha256'] and
                sample['parts']['tsc1']['sha256'] == u['config_sha256'] and
                max(u['logical_input_bytes'], *(p['bytes'] for p in sample['parts'].values())) <= LIMITS['file_bytes'],
                'Titchy frame, policy or diagnostic file limit differs')
        details = {'dataset_id': ds, 'work_item_id': work['work_item_id'], 'operation_config_id': work['operation_config_id'],
                   'canonical_object_id': work['canonical_object_id'], 'range': [0, n], 'value_column': 0,
                   'original': {'bytes': n * 8, 'sha256': u['restored_sha256']}, 'parts': sample['parts'],
                   'expected_native': {op: _facts(u[op]) for op in DIRECTIONS}, 'billing': billing}
        cases.append({**details, 'case_id': content_id(details)})
    require(cases, 'Titchy timing selection is empty')
    runtime = plan_recovery(root, {}, (), tools={TOOL: {k: binding['executable'][k] for k in ('path', 'sha256')}},
                            libraries=[binding['dependency']])
    files = ('src/tsbench/application/m3_titchy_stream_timing.py', 'src/tsbench/application/m3_titchy_stream.py',
             'src/tsbench/application/m3_full_custody.py', 'src/tsbench/qualification/titchy_wire.py',
             'src/tsbench/application/m3_lzbench_timing.py', 'src/tsbench/supervisor/isolated_worker.py',
             'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py')
    body = {'schema': SCHEMA, 'main_plan': _ref(root, main_path), 'source_plan': _ref(root, source_path),
            'source_run': source_run.relative_to(root).as_posix(), 'source_seal': seal['seal_id'], 'definition': main['definition']['plan'],
            'cases': cases, 'policy': POLICY, 'limits': LIMITS, 'runtime': runtime, 'environment': resource.environment(cpu),
            'declared_overlap': _folder(root, overlap).relative_to(root).as_posix() if overlap else None,
            'protocol': {'code': {p: digest(local_file(root, p)) for p in files}, 'launchers': launcher_lock()},
            'formal_performance': False, 'qualification_granted': False}
    return {**body, 'plan_content_id': content_id(body)}


def _trials(case):
    for i in range(WARMUPS + ROUNDS):
        for op in DIRECTIONS:
            yield {'case': case['case_id'], 'phase': 'warmup' if i < WARMUPS else 'measured',
                   'round': i + 1 if i < WARMUPS else i + 1 - WARMUPS, 'direction': op,
                   'folder': f"cases/{case['case_id']}/{i+1:02d}-{op}"}


def _input_files(case, at):
    return {name: at / name for name in ('original', *PARTS.values())}


def _expected(case, direction):
    parts = {name: {k: case['parts'][p][k] for k in ('bytes', 'sha256')} for p, name in PARTS.items()}
    original = {'original': case['original']}
    return (original, parts) if direction == 'encode' else (parts, original)


def _verify_trial(case, row, sessions):
    op = row['direction']
    mounts, outputs = _expected(case, op)
    doc, proc = row['native'], row['process']
    require(row['outputs'] == outputs and proc['input_mounts'] == mounts and _facts(doc) == case['expected_native'][op],
            'Titchy trial mounts, output or native settings differ')
    require(proc['operation'] == 'stream' and proc['status'] == 'completed' and proc['returncode'] == 0 and
            proc['reason'] == '' and type(proc['pid']) is int and proc['pid'] > 0 and
            re.fullmatch('[a-f0-9]{32}', proc['session_id'] or '') and proc['session_id'] not in sessions and
            type(doc['wall_ns']) is int and type(proc['process_wall_ns']) is int and 0 < doc['wall_ns'] <= proc['process_wall_ns'],
            'Titchy trial lacks a fresh complete process or correctly scoped clocks')
    sessions.add(proc['session_id'])
    usage = proc['child_usage']
    require(set(usage) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and usage['maxrss_bytes'] > 0 and
            all(type(v) is int and v >= 0 for v in usage.values()), 'Titchy trial invalid supervised resources')
    if op == 'encode':
        require(type(doc['first_packet_ns']) is int and 0 < doc['first_packet_ns'] <= doc['wall_ns'], 'Titchy first packet clock outside encode')


def _trial(run, plan, case, t, files, sessions):
    scratch = run / t['folder']
    scratch.mkdir()
    op = t['direction']
    mounts, outputs = _expected(case, op)
    argv = (['encode', '/inputs/original', '/out/archive', '/out/policy'] if op == 'encode' else
            ['decode', '/inputs/archive', '/inputs/policy', '/out/original'])
    out, proc = invoke_isolated_tool(run / 'runtime', plan['runtime'], TOOL, LIMITS, scratch, scratch, 'stream',
                                     {n: files[n] for n in mounts}, argv, lambda: False, observe=True)
    stdout, stderr = (scratch / ('stream.' + s) for s in ('stdout', 'stderr'))
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and set(p.name for p in out.iterdir()) == set(outputs) and
            stderr.stat().st_size == 0, 'isolated Titchy ' + op + ' failed: ' + stderr.read_text()[:500])
    for n in outputs:
        require((out / n).read_bytes() == files[n].read_bytes(), 'Titchy measured output differs byte for byte')
    row = {**t, 'native': load_json(stdout), 'process': proc, 'outputs': {n: _ident(out / n) for n in outputs},
           'logs': [_ref(run, f) for f in (stdout, stderr)]}
    _verify_trial(case, row, sessions)
    for n in outputs:
        (out / n).unlink()
    out.rmdir()
    return row


def _measurements(case, rows):
    result = {}
    for op in DIRECTIONS:
        measured = [r for r in rows if r['phase'] == 'measured' and r['direction'] == op]
        require(len(measured) == ROUNDS, 'Titchy repeat count differs')
        clocks = {'native_driver_wall_ns': [r['native']['wall_ns'] for r in measured],
                  'process_wall_ns': [r['process']['process_wall_ns'] for r in measured]}
        if op == 'encode':
            clocks['first_packet_native_driver_wall_ns'] = [r['native']['first_packet_ns'] for r in measured]
        for key in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'):
            clocks[key] = [r['process']['child_usage'][key] for r in measured]
        result[op] = {'distributions': {k: {**distribution(v), 'sample_basis': 'fresh_isolated_process_per_measured_round'} for k, v in clocks.items()},
                      'logical_mib_per_second': {k: case['original']['bytes'] * ROUNDS * 1e9 / (sum(clocks[k]) * (1 << 20))
                                                 for k in ('native_driver_wall_ns', 'process_wall_ns')}}
    b = case['billing']
    return {k: case[k] for k in ('dataset_id', 'work_item_id', 'operation_config_id', 'range', 'value_column')} | {
        'logical_input_bytes': case['original']['bytes'], 'byte_accounting': b, 'ratio': case['original']['bytes'] / b['artifact_bytes'],
        'first_packet_after_push': case['expected_native']['encode']['first_packet_after_push'], 'directions': result}


def _env(root, plan):
    overlap = None
    if p := plan['declared_overlap']:
        directory = _folder(root, p)
        overlap = {'run': p, 'sealed': (directory / 'completion.json').is_file(),
                   'ledger_bytes': local_file(directory, 'ledger.jsonl').stat().st_size}
    return {'utc': utc(), 'readings': resource.observe(plan['environment']['cpu']), 'overlap': overlap}


def _components(plan, case, files, *, independent):
    enc, dec = _expected(case, 'encode')
    require({n: _ident(files[n]) for n in files} == {**enc, **dec}, 'Titchy retained input or two-part frame differs')
    if independent:
        raw, packets = decode_tstr(files['archive'].read_bytes(), files['policy'].read_bytes(),
                                   {**NATIVE_SPEC, 'count': case['range'][1]}, NATIVE_POLICY)
        require(raw == files['original'].read_bytes() and len(packets) == case['expected_native']['encode']['packets'],
                'Titchy independent wire recovery differs from canonical input')


def recompute(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['limits'] == LIMITS and
            plan['formal_performance'] is False and plan['qualification_granted'] is False, 'Titchy repeat plan contract differs')
    for path, ref in plan['runtime']['files'].items():
        _file(run, {'path': f'runtime/{path}', **{k: ref[k] for k in ('bytes', 'sha256')}})
    env = load_json(run / 'environment.json')
    require(env['cpu_affinity'] == [plan['environment']['cpu']] and
            all((env[k]['overlap'] or {}).get('run') == plan['declared_overlap'] for k in ('before', 'after')),
            'Titchy CPU or overlapping work evidence differs')
    sessions, summary = set(), []
    records = iter(_rows(run / 'trials.jsonl'))
    for case in plan['cases']:
        _identity(case, 'case_id')
        files = _input_files(case, run / 'cases' / case['case_id'])
        _components(plan, case, files, independent=False)
        rows = []
        for trial in _trials(case):
            r = next(records, None)
            require(r is not None and all(r[k] == v for k, v in trial.items()), 'Titchy raw trial scope differs')
            require([ref['path'] for ref in r['logs']] == [f"{trial['folder']}/stream.{s}" for s in ('stdout', 'stderr')],
                    'Titchy log files differ from attempt')
            stdout, stderr = (_file(run, f) for f in r['logs'])
            require(load_json(stdout) == r['native'] and stderr.stat().st_size == 0, 'Titchy retained stdout/stderr differs')
            _verify_trial(case, r, sessions)
            rows.append(r)
        summary.append(_measurements(case, rows))
    require(summary and next(records, None) is None, 'unexpected extra or empty Titchy timing evidence')
    return {'schema': 'bmk.m3-titchy-stream-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'verified_trials': len(sessions), 'environment': env, 'cases': summary, 'policy': plan['policy'],
            'first_packet_phases': dict(Counter(c['byte_accounting']['first_packet_phase'] for c in summary)),
            'stage_accepted': False, 'formal_performance': False, 'qualification_granted': False}


def execute(root, plan, output):
    root = root.resolve(strict=True)
    require(freeze(root, _file(root, plan['main_plan']), _file(root, plan['source_plan']), _folder(root, plan['source_run']),
                   [c['dataset_id'] for c in plan['cases']], plan['environment']['cpu'], plan['declared_overlap']) == plan,
            'Titchy repeat source or configuration changed')
    output = output.resolve()
    require(output.is_relative_to(root), 'Titchy diagnostics must stay inside project')
    with resource.reserve():
        output.mkdir(parents=True, exist_ok=True)
        run = output / uuid.uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        prepared = []
        for case in plan['cases']:
            place = run / 'cases' / case['case_id']
            place.mkdir(parents=True)
            files = _input_files(case, place)
            files['original'].write_bytes(_first_column(root, entries[case['dataset_id']], case['range'][1]))
            for part, name in PARTS.items():
                shutil.copyfile(_file(_folder(root, plan['source_run']), case['parts'][part]), files[name])
            _components(plan, case, files, independent=True)
            prepared.append((case, files))
        with _affinity([plan['environment']['cpu']]), (run / 'trials.jsonl').open('xb') as ledger:
            before = _env(root, plan)
            sessions = set()
            for case, files in prepared:
                for t in _trials(case):
                    _line(ledger, _trial(run, plan, case, t, files, sessions))
            after = _env(root, plan)
        write_new(run / 'environment.json', {'before': before, 'after': after, 'cpu_affinity': [plan['environment']['cpu']]})
        write_new(run / 'report.json', recompute(run, plan))
        body = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, run / p) for p in ('plan.json', 'environment.json', 'trials.jsonl', 'report.json')]}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
        return run


def verify(run):
    run = run.resolve(strict=True)
    seal = load_json(run / 'completion.json')
    _identity(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name and [f['path'] for f in seal['files']] ==
            ['plan.json', 'environment.json', 'trials.jsonl', 'report.json'], 'Titchy repeat seal differs')
    for ref in seal['files']:
        _file(run, ref)
    plan = load_json(run / 'plan.json')
    require(seal['plan_content_id'] == plan['plan_content_id'], 'Titchy run differs from sealed plan')
    report = recompute(run, plan)
    require(report == load_json(run / 'report.json'), 'Titchy derived report differs from raw observation recomputation')
    return report
