#!/usr/bin/env python3
"""Independently reopen every ZFP array window in one sealed M3 run's grouped anchors."""
from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_in_run_zfp as same_run, m3_zfp_array_timing as array
from tsbench.application.m3_lzbench_timing import _file, _ref
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, require
from tsbench.recovery import check_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import launcher_lock
from tsbench.supervisor.timing_resource import reserve

SCHEMA = 'bmk.m3-zfp-array-anchor-replay/1'
FLAGS = {'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


def runtime_binding(root, plan):
    binding = plan['measurement']['zfp']['array']
    require(binding['launchers'] == launcher_lock(), 'ZFP grouped replay launchers changed')
    binary = binding['tools'][array.launch.NAME]
    _file(root, binary)
    library = plan['build']['zfp_corpus']['dependency']
    _file(root, library)
    tools = {array.launch.NAME: {k: binary[k] for k in ('path', 'sha256')}}
    check_recovery(binding['runtime'], {}, (), tools=tools, libraries=[library])
    return binding


def reopened(run, binding, case, setup, raw, archives, scratch, sessions):
    values, provenance = {}, {}
    for role in array.ARCHIVE_ROLES:
        op = 'reopen_' + role
        outputs, proc, logs = array._call(scratch.parent, binding, case, scratch / op, op, archives[role])
        session = proc['session_id']
        expected = {k: setup['archives'][role][k] for k in ('bytes', 'sha256')}
        require(proc['returncode'] == 0 and session and session not in sessions and
                proc['input_mounts'] == {role: expected}, 'ZFP grouped replay was not a fresh archive-only process')
        array._native(case, op, logs[0])  # validates per-window coordinates, rows and aligned rates
        values[role] = outputs['values']
        product, quality = array._reopened(case, role, raw, values[role])
        require(setup['recovery'][role] == {'product': product, 'quality': quality},
                'ZFP grouped replay differs from original anchor restoration')
        sessions.add(session)
        provenance[role] = {'archive': _ref(run, archives[role]), 'session_id': session,
                            'input_mounts': proc['input_mounts'], 'product': product, 'quality': quality,
                            'logs': {p.suffix[1:]: {'bytes': p.stat().st_size, 'sha256': digest(p)} for p in logs}}
    array._check_pair(case, raw, archives, values)
    return provenance


def replay_case(root, plan, run, item, entry, row, binding, directory, sessions):
    measurement = row['measurement']
    result = {k: item[k] for k in ('dataset_id', 'work_item_id', 'canonical_object_id', 'operation_config_id')}
    result.update(functional_status=row['status'], functional_reason=row['reason'],
                  measurement_status=measurement['status'], measurement_reason=measurement['reason'],
                  planned_windows=item['input']['size_estimate']['input_units'])
    planned = plan['measurement']['population'][item['work_item_id']]
    cid = planned['case_id']
    require(measurement['case_id'] == cid and measurement['adapter'] == planned['adapter'] and
            measurement['timing_admitted'] is False,
            'ZFP grouped replay measurement identity differs')
    base = run / same_run.D
    setup = measurement.get('anchors')
    if setup is None:
        require(measurement['status'] in ('measurement_failed', 'functional_dependency_not_verified') and
                measurement['reason'] and
                not (run / same_run.DIRECTORY / cid).exists(), 'ZFP grouped replay missing anchors without recorded failure')
        return {**result, 'replay_status': 'no_anchor', 'compared_windows': 0, 'quality_rejected_windows': None, 'states': {}}
    case = same_run._case(item, row, entry, cid)
    terminal = 'measured_quality_rejected' if case['rejected_windows'] else 'measured_and_verified'
    require(measurement['status'] in (terminal, 'measurement_failed'), 'ZFP grouped replay measurement terminal differs')
    archive_paths = same_run._anchors(root, case, entry, base, setup, set(), False)
    require(archive_paths == {r['path'] for r in setup['archives'].values()}, 'ZFP grouped replay anchor paths differ')
    archives = {role: _file(base, ref) for role, ref in setup['archives'].items()}
    require(all(archives[role] == base / ref['path'] for role, ref in setup['archives'].items()) and
            array._archives(case, archives) == {role: {k: ref[k] for k in ('bytes', 'sha256')}
                                               for role, ref in setup['archives'].items()},
            'ZFP grouped replay archive identity differs')
    with TemporaryDirectory(prefix='array-case-', dir=directory) as tmp:
        scratch = Path(tmp)
        raw, raw_ref = array._staging(root, case, entry, scratch)
        require(raw_ref == setup['raw'], 'ZFP grouped replay source differs from original anchor source')
        states = reopened(run, binding, case, setup, raw, archives, scratch, sessions)
    rejected = [{k: u[k] for k in ('column', 'row_range', 'before', 'after')} for u in case['units'] if not u['quality_passed']]
    require(len(rejected) == case['rejected_windows'], 'ZFP grouped replay rejection count differs')
    return {**result, 'replay_status': 'recomputed', 'compared_windows': len(case['units']),
            'quality_rejected_windows': len(rejected), 'rejected_windows': rejected, 'states': states}


def audit(root, plan, run):
    ledger, seal = full_run_source(plan, run)
    entries = _entry_map(root, load_json(_file(root, plan['definition']['plan'])))
    binding = runtime_binding(root, plan)
    sessions, results = set(), []
    with reserve(), TemporaryDirectory(prefix='m3-zfp-grouped-replay-') as tmp:
        directory = Path(tmp)
        stage_recovery(root, directory, binding['runtime'], directory='runtime')
        for row, item in full_run_rows(plan, ledger):
            if item is not None and (item.get('selection'), item['route']) == (31, array.ROUTE):
                results.append(replay_case(root, plan, run, item, entries[item['dataset_id']],
                                           row, binding, directory, sessions))
    require(len(results) == len({r['dataset_id'] for r in results}) == 23 and
            len(sessions) == 2 * sum(r['replay_status'] == 'recomputed' for r in results),
            'ZFP grouped replay denominator differs from the full 23-file plan')
    out = {'schema': SCHEMA, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'], 'run_seal_id': seal,
           'scope': 'grouped_initial_and_updated_anchors_all_windows_archive_only_decode_no_timing_admission',
           'recovery_id': binding['runtime']['recovery_id'], 'launchers': binding['launchers'],
           'isolated_processes': len(sessions), 'decisions': results,
           'replay_statuses': dict(Counter(r['replay_status'] for r in results)),
           'planned_windows': sum(r['planned_windows'] for r in results),
           'compared_windows': sum(r['compared_windows'] for r in results),
           'quality_rejected_windows_among_replayed': sum(r['quality_rejected_windows'] or 0 for r in results), **FLAGS}
    return {**out, 'audit_id': content_id(out)}


def main():
    p = ArgumentParser(description=__doc__)
    for name in ('plan', 'run', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    args = p.parse_args()
    try:
        result = audit(ROOT, load_json(args.plan), args.run.resolve(strict=True))
        write_new(args.out, result)
        print(result['audit_id'], result['replay_statuses'], result['compared_windows'],
              result['quality_rejected_windows_among_replayed'])
    except (OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
