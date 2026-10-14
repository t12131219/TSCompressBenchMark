"""Pure synthetic evidence tests; these never build or execute a codec."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

from tsbench.records import append, write_json
from tsbench.study import analyze, scheduled_rows, trial_coverage


def tool_module(name):
    path = Path(__file__).resolve().parents[1] / 'tools' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(run_id='one'):
    profile = {'id': 'cpu', 'device': 'cpu', 'native_threads': 1, 'object_workers': 1,
               'memory_limit_mb': 64}
    task = {'kind': 'values', 'fidelity': 'bitwise', 'boundary': 'object_memory',
            'lifecycle': 'independent_object', 'cache_policy': 'natural'}
    cases = []
    rows = []
    schedule = []
    for source in ('a', 'b'):
        for method in ('zstd-frame', 'candidate'):
            case_id = source + '-' + method
            cases.append({'case_id': case_id, 'dataset_id': source, 'dataset': {'source': source},
                          'method_id': method, 'codec': method, 'profile_id': 'cpu', 'profile': copy.deepcopy(profile),
                          'method': {'id': method, 'codec': method, 'params': {'level': 1}},
                          'task': 'values', 'raw_object_id': source, 'raw_bytes': 128, 'status': 'ready',
                          **{key: task[key] for key in ('boundary', 'lifecycle', 'cache_policy')}})
            for round_index in (0, 1):
                schedule.append({'case_id': case_id, 'session': 0, 'round': round_index})
                rows.append({'case_id': case_id, 'session': 0, 'round': round_index, 'attempt': 0,
                             'phase': 'measurement', 'event': 'terminal', 'status': 'ok',
                             'encode_ns': 100 if method == 'zstd-frame' else 50, 'decode_ns': 20,
                             'stored_bytes': 40, 'payload_bytes': 30, 'header_bytes': 10,
                             'verification': {'max_abs': 0, 'rmse': 0}})
    return {'run_id': run_id, 'cases': cases, 'schedule': schedule, 'state': 'complete',
            'environment': {'python': 'test', 'numpy': '1', 'platform': 'synthetic'},
            'resolved_config': {'task': task, 'execution': {'sessions': 1, 'rounds': 2, 'warmup_objects': 0}}}, rows


def save_run(root, manifest, rows):
    root.mkdir(parents=True)
    write_json(root / 'manifest.json', manifest)
    for row in rows:
        append(root / 'observations.jsonl', row)
    return root


def test_exact_schedule_rejects_extra_success_in_place_of_missing_trial():
    manifest, rows = evidence()
    rows[0]['round'] = 9
    with pytest.raises(ValueError, match='unscheduled measurement'):
        scheduled_rows(manifest, rows)
    manifest, rows = evidence()
    manifest['schedule'].append(manifest['schedule'][0])
    with pytest.raises(ValueError, match='duplicate scheduled trial'):
        scheduled_rows(manifest, rows)


def test_missing_trial_and_successful_retry_do_not_complete_original_failure():
    manifest, rows = evidence()
    original = rows.pop(0)
    selected, planned = scheduled_rows(manifest, rows)
    result = trial_coverage(original['case_id'], selected, planned)
    assert not result['complete'] and result['missing_trial_keys'] == [{'session': 0, 'round': 0}]
    rows.extend([{**original, 'status': 'error'}, {**original, 'attempt': 1}])
    selected, planned = scheduled_rows(manifest, rows)
    result = trial_coverage(original['case_id'], selected, planned)
    assert not result['complete'] and result['trial_status_counts'] == {'error': 1, 'ok': 1}


@pytest.mark.parametrize('change', ['environment', 'execution', 'profile', 'candidate_params', 'baseline_params', 'task', 'pass_kind'])
def test_source_effects_keep_different_conditions_separate(tmp_path, change):
    first, rows = evidence('first')
    second = copy.deepcopy(first)
    second['run_id'] = 'second'
    if change == 'environment':
        second['environment']['numpy'] = '2'
    elif change == 'execution':
        second['resolved_config']['execution']['warmup_objects'] = 1
    elif change == 'profile':
        for case in second['cases']:
            case['profile']['memory_limit_mb'] = 128
    elif change == 'task':
        second['resolved_config']['task']['special_values'] = 'preserve'
    elif change == 'pass_kind':
        second['pass_kind'] = 'profile'
    else:
        method = 'candidate' if change == 'candidate_params' else 'zstd-frame'
        for case in second['cases']:
            if case['method_id'] == method:
                case['method']['params']['level'] = 2
    a = save_run(tmp_path / 'a', first, rows)
    b = save_run(tmp_path / 'b', second, rows)
    before = [(path / 'observations.jsonl').read_bytes() for path in (a, b)]
    report = analyze([a, b], tmp_path / 'analysis')
    effects = report['source_cluster_effects']
    assert len(effects) == 6 and len({effect['group_id'] for effect in effects}) == 2
    assert all(effect['requested_pairs'] == 2 and effect['source_count'] == 2 for effect in effects)
    assert before == [(path / 'observations.jsonl').read_bytes() for path in (a, b)]


def test_pairing_requires_full_profile_and_matching_effective_allocation(tmp_path):
    manifest, rows = evidence()
    for case in manifest['cases']:
        if case['method_id'] == 'candidate':
            case['profile']['memory_limit_mb'] = 128
    root = save_run(tmp_path / 'run', manifest, rows)
    result = analyze([root], tmp_path / 'analysis')
    assert not any(pair['pair_available'] for pair in result['paired_comparisons'])
    manifest, rows = evidence('effective')
    for case in manifest['cases']:
        case['effective_profile'] = {'effective_native_threads': 1 if case['method_id'] == 'zstd-frame' else 2}
    root = save_run(tmp_path / 'effective', manifest, rows)
    result = analyze([root], tmp_path / 'effective-analysis')
    assert all(pair['reason'] == 'effective resource allocations differ' for pair in result['paired_comparisons'])


def test_oracle_frontier_does_not_mix_fidelity_conditions(tmp_path):
    first, rows = evidence('bounded')
    first['resolved_config']['task'].update(fidelity='bounded_abs', error_bound='0.1')
    second = copy.deepcopy(first)
    second['run_id'] = 'empirical'
    second['resolved_config']['task'].pop('error_bound')
    second['resolved_config']['task']['fidelity'] = 'empirical_quality'
    worse = [{**row, 'stored_bytes': 80, 'encode_ns': 200,
              'verification': {'max_abs': 1, 'rmse': 1}} for row in rows]
    a = save_run(tmp_path / 'bounded', first, rows)
    b = save_run(tmp_path / 'empirical', second, worse)
    report = analyze([a, b], tmp_path / 'analysis')
    assert any(case['empirical_oracle_pareto'] for case in report['cases'] if case['run_id'] == 'empirical')


def test_environment_comparison_marks_partial_metrics_and_rejects_changed_profile(tmp_path):
    compare = tool_module('compare_environments')
    base, rows = evidence('base')
    alternate = copy.deepcopy(base)
    alternate['run_id'] = 'alternate'
    a = save_run(tmp_path / 'base', base, rows)
    b = save_run(tmp_path / 'alternate', alternate, rows[1:])
    result = compare.compare([(a, b)], tmp_path / 'analysis')
    partial = next(case for case in result['pairs'][0]['cases'] if case['alternate_coverage']['missing_trials'])
    assert not partial['alternate_coverage']['complete']
    assert partial['alternate_coverage']['missing_trials'] == 1
    assert partial['alternate_performance_scope'] == 'conditional on successful primary trials'
    alternate['cases'][0]['profile']['memory_limit_mb'] = 128
    write_json(b / 'manifest.json', alternate)
    with pytest.raises(ValueError, match='semantics/input differs'):
        compare.compare([(a, b)], tmp_path / 'changed')


def test_source_drift_invalidates_complete_performance_across_all_analyses(tmp_path):
    from tsbench.report import generate
    manifest, rows = evidence()
    manifest['execution_source_unchanged'] = False
    root = save_run(tmp_path / 'drifted', manifest, rows)
    descriptive = generate(root)
    assert not any(case['complete_case'] for case in descriptive['cases'])
    assert all(case['performance_scope'].startswith('diagnostic only') for case in descriptive['cases'])
    study = analyze([root], tmp_path / 'study')
    assert study['complete_cases'] == 0
    assert not any(pair['pair_available'] for pair in study['paired_comparisons'])
    compare = tool_module('compare_environments')
    _, _, coverage = compare.load_run(root)
    assert coverage['complete_cases'] == 0
    replay = tool_module('replay_environment')
    result = replay.summarize_run(root)
    assert not result['all_planned_trials_ok'] and result['complete_cases'] == 0
    assert all(case['invalidity_reason'] == 'execution_source_changed_during_run' for case in result['coverage'].values())


def test_replay_preflight_rejects_existing_run_directory_before_build(tmp_path, monkeypatch):
    replay = tool_module('replay_environment')
    config = tmp_path / 'experiment.toml'
    config.write_text('synthetic')
    output = tmp_path / 'output'
    (output / 'experiment').mkdir(parents=True)
    monkeypatch.setattr(replay, 'build_all', lambda *args, **kwargs: pytest.fail('preflight must precede build'))
    with pytest.raises(FileExistsError, match='run directory exists'):
        replay.main([str(config), '--build-root', str(tmp_path / 'build'), '--output-root', str(output)])
    assert not (output / 'replay.json').exists()


def test_replay_checkpoint_preserves_finished_run_and_later_failure(tmp_path, monkeypatch):
    replay = tool_module('replay_environment')
    configs = [tmp_path / name for name in ('first.toml', 'second.toml')]
    for config in configs:
        config.write_text('synthetic')
    monkeypatch.setattr(replay, 'load', lambda path: {})

    def fake_run(config, destination):
        if destination.name == 'second':
            raise RuntimeError('synthetic later failure')
        manifest, rows = evidence('first')
        return save_run(destination, manifest, rows)

    monkeypatch.setattr(replay, 'run', fake_run)
    output = tmp_path / 'output'
    with pytest.raises(RuntimeError, match='synthetic later failure'):
        replay.main([*(str(path) for path in configs), '--build-root', str(tmp_path / 'build'),
                     '--output-root', str(output), '--skip-build'])
    report = json.loads((output / 'replay.json').read_text())
    assert report['status'] == 'failed' and report['failure']['stage'] == 'run'
    assert report['runs'][0]['status'] == 'complete' and report['runs'][0]['trials'] == {'ok': 8}
    assert report['runs'][1]['status'] == 'failed'


def test_replay_build_failure_keeps_overall_and_build_evidence(tmp_path, monkeypatch):
    replay = tool_module('replay_environment')
    config = tmp_path / 'one.toml'
    config.write_text('synthetic')
    monkeypatch.setattr(replay, 'load', lambda path: {})
    monkeypatch.setattr(replay, 'build_all', lambda *args, **kwargs: [{'status': 'error'}])
    output = tmp_path / 'output'
    with pytest.raises(RuntimeError, match='independent builds failed'):
        replay.main([str(config), '--build-root', str(tmp_path / 'build'), '--output-root', str(output)])
    report = json.loads((output / 'replay.json').read_text())
    assert report['status'] == 'failed' and report['failure']['stage'] == 'build'
    assert report['build']['statuses'] == {'error': 1}
    assert report['runs'][0]['status'] == 'pending'
