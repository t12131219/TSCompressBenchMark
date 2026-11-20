"""Dispatch CORAD producer/consumer groups once and account them in one M3 ledger."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
from multiprocessing import get_context
import os

from ..assets import ContractError, content_id, require
from ..planner.corad_corpus import INFERENCE, TRAINERS
from ..planner.corad_training import plan_corad_training
from ..planner.corad_training_execution import bridge_bytes
from ..planner.m3_corad import DRIVER, FOLDER
from ..planner.m3_corad_ingress import bind_cohorts
from ..recovery import stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from .corad_corpus_execution import execute_cohort

SUCCESSFUL_RESTORES = {'verified', 'quality_rejected'}


def stage(root, run, driver):
    folder = run / FOLDER
    folder.mkdir()
    source, _ = plan_corad_training(root)
    bridge = bridge_bytes(root, source)
    require(launcher_lock() == driver['launchers'] and sha256(bridge).hexdigest() == driver['source_bridge_sha256'],
            'CORAD Source bridge or isolation launchers changed')
    stage_recovery(root, folder, driver['decoder'])
    return bridge


def prepare(root, entry, items):
    routes = {INFERENCE, *TRAINERS}
    require(items.keys() == routes and all(item['dataset_id'] == entry['id'] and item['selection'] == 80 and
            item['applicability'] == 'input_domain_matches' for item in items.values()),
            'CORAD requires all three applicable decisions for the same source')
    contract = items[INFERENCE]['input']['corad_contract']
    for route in routes:
        other = items[route]['input']['corad_contract']
        require(all(other[k] == contract[k] for k in ('cohorts', 'layout', 'quality', 'training_access', 'recovery_access')) and
                other['deployment']['eligible_producers'] == (list(TRAINERS) if route == INFERENCE else [route]),
                'CORAD producer/consumer input or model dependency differs')
    cohorts = bind_cohorts(root, entry, [c for c in contract['cohorts'] if c['state'] == 'eligible'], contract['layout'])
    ntrain = sum(len(train) for _, train, _ in cohorts)
    ntest = sum(len(raw) for _, _, tests in cohorts for raw in tests)
    frames = sum(len(tests) for _, _, tests in cohorts)
    require(len({b['input_binding_id'] for b, _, _ in cohorts}) == len(cohorts) and
            all((items[route]['input']['size_estimate']['native_input_bytes_one_pass'],
                 items[route]['input']['size_estimate']['input_units']) == value for route, value in
                {INFERENCE: (2*ntest, 2*frames), **{r: (ntrain, len(cohorts)) for r in TRAINERS}}.items()),
            'CORAD materialized work differs from the frozen byte or unit census')
    return cohorts


def _job(folder, driver, material, bridge):
    b, train, tests = material
    terminals = []
    error = ''
    try:
        terminals.extend(execute_cohort(folder, driver, b, train, tests, bridge))
    except (ContractError, OSError, ValueError, KeyError) as exc:
        error = str(exc) or type(exc).__name__
    return {'input_binding': b, 'terminals': terminals, 'execution_error': error}


def _status(cases, failed, rejected):
    if failed:
        return 'failed', f'{failed} CORAD execution, dependency or validation failures; {rejected} quality rejections'
    if rejected:
        return 'quality_rejected', f'{rejected} of {cases} detached CORAD frames exceeded train-only quality gates'
    return 'verified', ''


def project(items, groups):
    """Split a producer/consumer transcript without billing a held-out frame twice."""
    bindings = [g['input_binding'] for g in groups]
    errors = {g['input_binding']['input_binding_id']: g['execution_error'] for g in groups if g['execution_error']}
    expected = {b['input_binding_id']: b for b in bindings}
    require(len(expected) == len(bindings), 'duplicate CORAD input bindings')
    evaluations, fits = {r: [] for r in TRAINERS}, {r: [] for r in TRAINERS}
    for b, group in zip(bindings, groups, strict=True):
        keys = set()
        for row in group['terminals']:
            require(row['input_binding_id'] == b['input_binding_id'] and row['dataset'] == b['source'] and
                    row['producer'] in TRAINERS and row['producer_binding_id'] == b['producer_binding_ids'][row['producer']] and
                    row['operation'] in {'train', 'heldout'}, 'CORAD terminal binding differs')
            key = (row['producer'], row['operation'], tuple(row.get('frame_range', [])))
            require(key not in keys, 'duplicate CORAD native terminal')
            keys.add(key)
            if row['operation'] == 'train':
                require('frame_range' not in row, 'CORAD fit contains an evaluation range')
                fits[row['producer']].append(row)
            else:
                require(row['frame_range'] in [f['absolute_rows'] for f in b['test_frames']], 'CORAD evaluated an unplanned row range')
                evaluations[row['producer']].append(row)
        require(len(keys) <= 2*(1+len(b['test_frames'])) and
                (len(keys) == 2*(1+len(b['test_frames'])) or b['input_binding_id'] in errors),
                'CORAD native terminal denominator differs')
    common = {'driver': DRIVER, 'artifact_root': FOLDER, 'cohort_ids': list(expected), 'execution_errors': errors,
              'timing_admitted': False}
    frames_per_producer = sum(len(b['test_frames']) for b in bindings)
    inference_counts = {p: dict(Counter(r['status'] for r in evaluations[p])) for p in TRAINERS}
    rejected = sum(v.get('quality_rejected', 0) for v in inference_counts.values())
    inference_frames = [r for p in TRAINERS for r in evaluations[p] if 'frame' in r]
    valid = sum(v.get('verified', 0)+v.get('quality_rejected', 0) for v in inference_counts.values())
    failed = 2*frames_per_producer - valid
    status, reason = _status(2*frames_per_producer, max(failed, len(errors)), rejected)
    result = {INFERENCE: {'status': status, 'reason': reason, 'evidence': {**common, 'operation': 'heldout',
              'input_bindings': bindings, 'evaluations': evaluations, 'frame_statuses': inference_counts,
              'complete_frame_bytes': sum(r['frame']['bytes'] for r in inference_frames),
              'logical_restored_value_bytes': sum(r['logical_value_bytes'] for r in inference_frames if r['status'] in SUCCESSFUL_RESTORES),
              'training_decisions': {p: items[p]['work_item_id'] for p in TRAINERS}, 'expected_frames': 2*frames_per_producer}}}
    for p in TRAINERS:
        models = [r for r in fits[p] if r['status'] == 'verified']
        c = inference_counts[p]
        rejected = c.get('quality_rejected', 0)
        failed = len(bindings)-len(models) + frames_per_producer-c.get('verified', 0)-rejected
        status, reason = _status(frames_per_producer, max(failed, len(errors)), rejected)
        result[p] = {'status': status, 'reason': reason, 'evidence': {**common, 'operation': 'train',
                     'producer': p, 'fits': fits[p], 'expected_fits': len(bindings),
                     'fit_statuses': dict(Counter(r['status'] for r in fits[p])),
                     'model_bytes': sum(r['deployment']['model']['bytes'] for r in models),
                     'deployment_metadata_bytes': sum(r['deployment_asset']['bytes'] for r in models),
                     'diagnostic_training_asset_bytes': sum(a['bytes'] for r in models for a in r['training_assets'].values()),
                     'heldout_statuses': c, 'heldout_inference_decision': items[INFERENCE]['work_item_id'],
                     'heldout_product_charge': 'inference_only'}}
    return result


def run_file(root, plan, entry, items, run, bridge):
    materials = prepare(root, entry, items)
    driver = plan['build']['corad_corpus']
    frozen_parallelism = driver['parallel_cohorts_max']
    workers = min(len(os.sched_getaffinity(0)), len(materials), frozen_parallelism)
    if workers == 1:
        groups = [_job(run / FOLDER, driver, material, bridge) for material in materials]
    else:
        # Spawn isolates controllers from the parent's plugin state; only the
        # parent publishes decisions. Decode/fit operations are separately sandboxed.
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn')) as pool:
            pending = [pool.submit(_job, run / FOLDER, driver, material, bridge) for material in materials]
            groups = [task.result() for task in pending]
    return project(items, groups)
