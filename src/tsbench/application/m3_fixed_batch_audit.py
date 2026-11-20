"""Check retention closure and replay the prescribed M3 batch samples."""
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import load_json, local_file, require, verify_asset
from ..planner.m3_fixed_batch import DIRECTORY, RETENTION, ROUTES
from ..supervisor.isolated_worker import launcher_lock
from .m3_fixed_batch import restore_frame
from .m3_ledger_census import census, check_retention
from .m3_sealed_ledger import full_run_rows, full_run_source


def _files(directory):
    require(directory.is_dir() and not directory.is_symlink(), 'missing or linked M3 retention directory')
    files = set()
    for p in directory.rglob('*'):
        require(not p.is_symlink() and (p.is_file() or p.is_dir()), 'invalid file in M3 retention closure')
        if p.is_file():
            files.add(p.relative_to(directory).as_posix())
    return files


def sealed_batch_scope(root, plan, run, *, full_ledger=False):
    """Read ordered (observation, frozen work item) pairs from one functional source."""
    if full_ledger:
        ledger, seal_id = full_run_source(plan, run)
        return (seal_id, None, ((row, item) for row, item in full_run_rows(plan, ledger)
                                if row.get('entry_kind') is None))
    summary = census(root, plan, run)
    report = load_json(local_file(run, 'report.json'))
    items = {r['work_item_id']: r for r in plan['work_items']}
    return summary['seal_id'], report['partial_preflight'], ((row, items[row['work_item_id']]) for row in report['rows'])


def audit_fixed_batch(root, plan, run, *, replay=False, full_ledger=False):
    seal_id, partial_preflight, rows = sealed_batch_scope(root, plan, run, full_ledger=full_ledger)
    binding = plan['build'].get('fixed_batch', {})
    require(binding.get('retention') == RETENTION, 'M3 plan did not freeze batch retention')
    bundle = run / DIRECTORY
    runtime = binding['decoder']['files']
    require(_files(bundle) == runtime.keys(), 'M3 retained runtime file closure differs')
    for name, info in runtime.items():
        path = verify_asset(bundle, {'path': name, 'sha256': info['sha256']})
        require(path.stat().st_size == info['bytes'], 'M3 retained runtime bytes differ')
    references, results, other_terminals = {}, [], []
    released, verified = {'count': 0, 'bytes': 0}, 0
    for row, item in rows:
        if (item['selection'], item['route']) not in ROUTES:
            continue
        if row['status'] != 'verified':
            other_terminals.append({k: row[k] for k in ('work_item_id', 'status', 'reason')})
            continue
        evidence = row['evidence']
        require(evidence['driver'] == binding['driver'] and evidence['recovery_id'] == binding['decoder']['recovery_id'],
                'M3 retained batch sample does not bind the planned recovery runtime')
        refs = check_retention(item, evidence)
        verified += 1
        for key in released:
            released[key] += evidence['released_frames'][key]
        for ref in refs:
            rel = ref['path']
            file_ref = {k: ref[k] for k in ('path', 'bytes', 'sha256')}
            require(references.get(rel, file_ref) == file_ref, 'conflicting M3 content-addressed references')
            references[rel] = file_ref
            results.append((item, ref, evidence['units'][ref['unit_index']]))
    require(verified and results, 'M3 run has no verified fixed batch samples')
    directory = RETENTION['directory']
    require(_files(run / directory) == {Path(p).name for p in references}, 'M3 batch sample file closure differs')
    files = {rel: verify_asset(run, ref) for rel, ref in references.items()}
    require(all(files[rel].stat().st_size == ref['bytes'] for rel, ref in references.items()),
            'M3 retained batch frame byte counts differ')
    restored, sessions = [], set()
    if replay:
        require(launcher_lock() == binding['launchers'], 'M3 batch replay launchers differ from the plan')
        for item, ref, unit in results:
            with TemporaryDirectory(prefix='m3-fixed-batch-replay-') as temp:
                artifact, original = unit['artifact'], unit['original']
                _, _, backends = ROUTES[item['selection'], item['route']]
                for backend in backends:
                    recovery = restore_frame(bundle, binding, item, backend, Path(temp) / backend, files[ref['path']],
                                             artifact, original)
                    process = recovery['process']
                    require(process['session_id'] not in sessions and process['session_id'] not in
                            {unit['encode']['process']['session_id'],
                             *(d['process']['session_id'] for d in unit['decodes'].values())},
                            'M3 batch replay did not use a new process session')
                    sessions.add(process['session_id'])
                    restored.append({'work_item_id': item['work_item_id'], 'dataset_id': item['dataset_id'],
                                     'route': item['route'], 'unit_index': ref['unit_index'],
                                     'decode_backend': backend, 'artifact': ref, **recovery})
    return {'schema': 'bmk.m3-fixed-batch-retention-audit/1', 'run_id': run.name, 'seal_id': seal_id,
            'plan_content_id': plan['plan_content_id'], 'sample_references': len(results),
            'unique_retained_frames': len(files), 'unique_retained_frame_bytes': sum(r['bytes'] for r in references.values()),
            'released_frames': released, 'verified_case_count': verified, 'other_terminals': other_terminals,
            'replay_performed': replay, 'replayed': restored, 'partial_preflight': partial_preflight,
            **({'source_projection': 'complete_frozen_population_from_sealed_ledger'} if full_ledger else {}),
            'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
