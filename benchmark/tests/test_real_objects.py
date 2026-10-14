"""Real-object study preserves source, temporal and semantic distinctions."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import tomllib

import numpy as np
import pytest

TOOLS = Path(__file__).resolve().parents[1]/'tools'
sys.path.insert(0, str(TOOLS))
from characterize_data import floating_column, lexical_precision, object_profile, sha256, source_profile, timestamps
from generate_real_objects import EVALUATION_START, LENGTHS, build_configs, freeze_text, render_config
from tsbench.config import resolve
from tsbench.data import load_dataset, project


def test_lexical_precision_is_token_evidence_and_distinguishes_missing_specials():
    evidence = lexical_precision(['1.2300', '1e-3', '3', '-0.00', '', 'NaN', 'inf'])
    assert evidence['decimal_places_histogram'] == {'0': 1, '2': 1, '3': 1, '4': 1}
    assert evidence['scientific_notation_count'] == 1
    assert evidence['missing_token_count'] == 2
    assert evidence['nonfinite_token_count'] == 1
    assert evidence['negative_zero_token_count'] == 1


def test_float_profile_preserves_special_counts_and_does_not_join_missing_pairs():
    a = np.array([0.0, -0.0, np.nextafter(0.0, 1.0), np.nan, np.inf, -np.inf], dtype='<f8')
    result = floating_column(a)
    assert result['positive_zero_count'] == result['negative_zero_count'] == result['subnormal_count'] == 1
    assert result['nan_count'] == result['positive_infinity_count'] == result['negative_infinity_count'] == 1
    assert result['adjacent_finite_pairs'] == 2
    assert result['adjacent_equal_pairs'] == 1
    assert result['finite_unique_numeric_values'] == 2
    assert floating_column(np.array([2., 2., 2.]))['lag1_correlation'] is None
    json.dumps(result, allow_nan=False)


def test_timestamp_deltas_never_overflow_int64_and_no_deduplication():
    a = np.array([np.iinfo(np.int64).min, np.iinfo(np.int64).max,
                  np.iinfo(np.int64).max, 0], dtype='<i8')
    result = timestamps(a, 'ns')
    assert result['delta_max'] == 2**64-1
    assert result['negative_deltas'] == 1
    assert result['adjacent_duplicates'] == result['duplicate_occurrences_global'] == 1
    assert result['count'] == 4


def fixture_catalog(tmp_path, rows):
    path = tmp_path/'fixture.csv'
    header = ['date', 'OT', 'T (degC)', 'Tdew (degC)', 'Tlog (degC)']
    lines = [','.join(header)]
    origin = datetime(2020, 1, 1)
    for row in range(rows):
        lines.append((origin + timedelta(minutes=row)).strftime('%Y-%m-%d %H:%M:%S')+f',{row}.00,2.0,3.0,4.0')
    path.write_text('\n'.join(lines)+'\n')
    entry = {'id': 'weather', 'file': {'name': path.name, 'sha256': sha256(path),
                                      'bytes': path.stat().st_size, 'rows': rows, 'columns': header}}
    return path, entry


def test_exact_source_hash_and_strict_field_count_are_enforced(tmp_path):
    path, entry = fixture_catalog(tmp_path, 4)
    result = source_profile(entry, tmp_path, 1, 4)
    assert result['evaluation_timestamp_profile']['delta_mode'] == 60_000_000_000
    assert result['columns']['OT']['evaluation_lexical_precision']['maximum_decimal_places'] == 2
    path.write_text(path.read_text()+'untracked edit')
    with pytest.raises(ValueError, match='identity drift'):
        source_profile(entry, tmp_path, 1, 4)
    path.write_text('date,OT,T (degC),Tdew (degC),Tlog (degC)\n2020-01-01 00:00:00,1,2,3,4,5\n')
    entry['file'].update(sha256=sha256(path), bytes=path.stat().st_size, rows=1)
    with pytest.raises(ValueError, match='field count'):
        source_profile(entry, tmp_path, 0, 1)


def test_grid_task_routes_layout_and_window_are_prespecified(tmp_path):
    path, entry = fixture_catalog(tmp_path, EVALUATION_START+max(LENGTHS))
    sources = [{'id': key, 'header': entry['file']['columns'], 'path': str(path)} for key in ('etth1', 'weather')]
    configs = build_configs(sources, tmp_path/'runs')
    assert [len(c['datasets'])*len(c['methods']) for c in configs] == [56, 20, 40, 18, 18]
    assert sum(len(c['datasets'])*len(c['methods']) for c in configs)*3*7 == 3192
    for config in configs:
        loaded = resolve(tomllib.loads(render_config(config)), tmp_path)
        for dataset in loaded['datasets']:
            assert dataset['start'] == EVALUATION_START > 1536
            assert dataset['stop'] in (2176, 2560)
            assert dataset['missing'] == 'reject'
        assert '_v4' not in config['output']
    lossless = configs[0]
    c, f = (project(load_dataset(spec), {'kind': 'values'}) for spec in lossless['datasets'][:2])
    np.testing.assert_array_equal(c.components['V'], f.components['V'])
    assert object_profile(c, 'C')['raw_object_id'] != object_profile(f, 'F')['raw_object_id']
    assert c.components['V'].flags.c_contiguous
    assert f.components['V'].flags.f_contiguous
    normalized_routes = configs[2]['methods'][3:]
    assert all(m['components']['T']['transform'] == 'integer_affine_gcd' for m in normalized_routes)
    assert all(m['codec'] == 'chimp128' for m in normalized_routes)
    assert {m['chunk_rows'] for m in lossless['methods'] if 'chunk_rows' in m} == {64, 256}
    assert configs[3]['datasets'][0]['columns'] == ['OT']
    assert configs[3]['datasets'][2]['columns'] == ['T (degC)', 'Tdew (degC)', 'Tlog (degC)']


def test_frozen_artifacts_refuse_rewriting_existing_evidence(tmp_path):
    path = tmp_path/'frozen.json'
    freeze_text(path, 'original\n')
    freeze_text(path, 'original\n')
    with pytest.raises(ValueError, match='fixed artifact differs'):
        freeze_text(path, 'changed\n')
    assert path.read_text() == 'original\n'


def analysis_fixture(tmp_path, provenance=True, failure_retry=False):
    from analyze_real_objects import component_identity
    from tsbench.records import append, write_json
    root = tmp_path/'raw-run'
    root.mkdir()
    cases, objects, rows, schedule = [], [], [], []
    values = np.arange(12, dtype='<f8').reshape(6, 2)
    for order in ('C', 'F'):
        path = tmp_path/(order+'.npy')
        np.save(path, np.array(values, order=order))
        spec = {'id': 'values-'+order, 'path': str(path), 'source': 'etth1', 'order': order}
        obj = project(load_dataset(spec), {'kind': 'values'})
        identity = object_profile(obj, spec['id'])
        objects.append({'experiment': 'real-mts-lossless', 'dataset_id': spec['id'],
                        'raw_object_id': identity['raw_object_id'], 'raw_bytes': identity['raw_bytes'],
                        'component_layouts': {'V': order}, **component_identity(obj)})
        for method in ('zstd-frame', 'raw-store'):
            case_id = spec['id']+'/'+method
            case = {'case_id': case_id, 'status': 'ready', 'dataset_id': spec['id'], 'dataset': spec,
                    'method_id': method, 'codec': method, 'method': {'id': method, 'codec': method, 'params': {}},
                    'profile_id': 'cpu-single', 'profile': {'id': 'cpu-single', 'native_threads': 1},
                    'effective_profile': {'device': 'cpu', 'effective_native_threads': 1},
                    'implementation_id': 'fixture-'+method, 'raw_object_id': identity['raw_object_id'],
                    'raw_bytes': identity['raw_bytes'], 'boundary': 'object_memory', 'lifecycle': 'independent_object',
                    'cache_policy': 'natural'}
            cases.append(case)
            for round_index in range(2):
                schedule.append({'case_id': case_id, 'session': 0, 'round': round_index})
                row = {'run_id': 'synthetic-real-objects', 'phase': 'measurement', 'event': 'terminal',
                       'case_id': case_id, 'session': 0, 'round': round_index, 'attempt': 0, 'status': 'ok',
                       'encode_ns': 100 if method == 'zstd-frame' else 50, 'decode_ns': 100,
                       'stored_bytes': 200, 'raw_object_id': case['raw_object_id'],
                       'implementation_id': case['implementation_id']}
                if failure_retry and order == 'F' and method == 'raw-store' and round_index == 0:
                    rows.append({**row, 'status': 'error', 'stage': 'verify', 'reason': 'fixture failure'})
                    row['attempt'] = 1
                rows.append(row)
    manifest = {'schema': 'tsbench.run/1', 'name': 'real-mts-lossless', 'run_id': 'synthetic-real-objects',
                'cases': cases, 'schedule': schedule, 'execution_source_unchanged': provenance,
                'environment': {'cpu': 'fixture'},
                'resolved_config': {'task': {'kind': 'values', 'fidelity': 'bitwise'},
                                    'execution': {'sessions': 1, 'rounds': 2},
                                    'methods': [{'id': key, 'codec': key} for key in ('zstd-frame', 'raw-store')]}}
    write_json(root/'manifest.json', manifest)
    for row in rows:
        append(root/'observations.jsonl', row)
    components = tmp_path/'components.json'
    write_json(components, {'objects': objects})
    return root, components


def test_readonly_analysis_pairs_schemes_and_layouts_with_distinct_exact_objects(tmp_path):
    from analyze_real_objects import analyze
    from tsbench.records import file_hash
    root, components = analysis_fixture(tmp_path)
    before = [file_hash(root/file) for file in ('manifest.json', 'observations.jsonl')]
    result = analyze([root], tmp_path/'analysis', components)
    assert result['requested_cases'] == result['complete_cases'] == 4
    assert result['planned_trials'] == 8
    assert result['available_pair_counts'] == {'scheme': 2, 'layout': 2}
    assert all(pair['object_identity_differs'] for pair in result['paired_comparisons'] if pair['pair_kind'] == 'layout')
    assert all(not pair['object_identity_differs'] for pair in result['paired_comparisons'] if pair['pair_kind'] == 'scheme')
    assert all(pair['session_ratios']['encode_ns'][0]['ratio'] == 2 for pair in result['paired_comparisons'] if pair['pair_kind'] == 'scheme')
    assert before == [file_hash(root/file) for file in ('manifest.json', 'observations.jsonl')]
    assert len(result['cases'][0]['all_attempts_trace']) == 2
    assert result['runs'][0]['schedule']


def test_analysis_keeps_earliest_failure_and_full_retry_status_counts(tmp_path):
    from analyze_real_objects import analyze
    root, components = analysis_fixture(tmp_path, failure_retry=True)
    result = analyze([root], tmp_path/'analysis', components)
    assert result['complete_cases'] == 3
    assert result['available_pair_counts'] == {'scheme': 1, 'layout': 1}
    assert result['runs'][0]['all_terminal_status_counts'] == {'ok': 8, 'error': 1}
    failed = next(point for point in result['cases'] if point['case_id'] == 'values-F/raw-store')
    assert failed['primary_trace'][0]['status'] == 'error'
    assert failed['primary_trace'][0]['attempt'] == 0
    assert len(failed['all_attempts_trace']) == 3


def test_analysis_provenance_invalidates_complete_pairs_and_preserves_denominator(tmp_path):
    from analyze_real_objects import analyze
    root, components = analysis_fixture(tmp_path, provenance=False)
    result = analyze([root], tmp_path/'analysis', components)
    assert result['complete_cases'] == 0
    assert result['planned_trials'] == 8
    assert result['requested_pair_counts'] == {'scheme': 2, 'layout': 2}
    assert result['available_pair_counts'] == {}
    assert all(not point['execution_source_valid'] for point in result['cases'])


@pytest.mark.parametrize('corruption', ['duplicate', 'extra', 'wrong_context', 'duplicate_run', 'invalid_baseline'])
def test_analysis_rejects_bad_evidence_before_writing(tmp_path, corruption):
    from analyze_real_objects import analyze
    from tsbench.records import append
    root, components = analysis_fixture(tmp_path)
    row = json.loads((root/'observations.jsonl').read_text().splitlines()[0])
    roots, baselines = [root], None
    if corruption in ('duplicate', 'extra', 'wrong_context'):
        if corruption == 'extra':
            row['round'] = 99
        elif corruption == 'wrong_context':
            row['attempt'] = 1
            row['implementation_id'] = 'corrupted'
        append(root/'observations.jsonl', row)
    elif corruption == 'duplicate_run':
        roots.append(root)
    else:
        baselines = {'real-mts-lossless': 'invented-method'}
    destination = tmp_path/'analysis'
    with pytest.raises(ValueError):
        analyze(roots, destination, components, baselines)
    assert not destination.exists()


def test_readonly_analysis_rejects_output_inside_run_and_component_drift(tmp_path):
    from analyze_real_objects import analyze
    root, components = analysis_fixture(tmp_path)
    with pytest.raises(ValueError, match='separate'):
        analyze([root], root/'analysis', components)
    evidence = json.loads(components.read_text())
    evidence['objects'][0]['raw_object_id'] = 'changed'
    components.write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match='no matching frozen'):
        analyze([root], tmp_path/'analysis', components)
