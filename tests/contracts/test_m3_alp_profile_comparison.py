"""Exact-profile timing does not conflate geometry, backend, or clock boundaries."""
from pathlib import Path
import sys

import pytest

from tsbench.assets import ContractError, content_id
from tsbench.planner.m3_batch_timing import CONFIG, POLICY, PROFILE_EXACT, SCHEMA, _groups, check_plan

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import m3_alp_profile_pipeline_timing as pipeline


def _comparison():
    case = {'work_item_id': 'case', 'unit_index': 1, 'geometry': {'column': 5, 'row_range': [0, 100]},
            'original': {'raw': {'bytes': 800, 'sha256': '56'}}, 'frame': {'path': 'exact.bmk', 'bytes': 300, 'sha256': '78'},
            'plugin': 'alp-auto', 'route': 'decode-backends'}
    source = {k: {} for k in ('logically_matched_profile_seal', 'profile_plan', 'profile_reference_seal', 'ledger',
                               'runtime_reference_seal', 'anchor', 'plan', 'report', 'seal_id')}
    source['source_projection'] = PROFILE_EXACT
    return {'schema': SCHEMA, 'config': CONFIG, 'policy': POLICY, 'functional': source, 'seed': 3,
            'diagnostic_only': True, 'performance_admitted': False}, case


def _two_cases(plan, a, b):
    cases = [{**case, 'case_id': content_id(case)} for case in (a, b)]
    result = {**plan, 'cases': cases, 'groups': _groups(cases, plan['seed']), 'expected_batches': 32}
    return {**result, 'plan_content_id': content_id(result)}


def test_exact_comparison_rejects_wrong_column_even_with_a_valid_plan_hash():
    plan, case = _comparison()
    a, b = [{**case, 'decode_backend': k} for k in ('scalar-unfused', 'falp-auto')]
    check_plan(_two_cases(plan, a, b))
    with pytest.raises(ContractError, match='both ALP decoders on one frame'):
        check_plan(_two_cases(plan, a, {**b, 'geometry': {**b['geometry'], 'column': 0}}))


def test_pipeline_decode_rejects_source_in_child_boundary_and_impossible_outer_wall():
    _, case = _comparison()
    case.update(decode_backend='falp-auto', expected_native={'decode': {'backend': 'falp-avx2'}})
    trial = {'index': 2, 'phase': 'measured', 'direction': 'decode'}
    process = {'input_mounts': {'frame': {'bytes': 300, 'sha256': '78'}}, 'operation': 'decode-falp-auto',
               'status': 'completed', 'returncode': 0, 'reason': '', 'session_id': 's', 'process_wall_ns': 50,
               'child_usage': {'maxrss_bytes': 10}}
    row = {**trial, 'wall_ns': 100, 'native': case['expected_native']['decode'], 'worker': process,
           'output': case['original'], 'replay': None, 'parts_ns': {'supervise_decode_and_verify': 90, 'sync_checked_outputs': 10}}
    pipeline._validate(row, trial, case, set())
    with pytest.raises(ContractError, match='mount'):
        pipeline._validate({**row, 'worker': {**process, 'input_mounts': {**process['input_mounts'], 'raw': case['original']['raw']}}},
                           trial, case, set())
    with pytest.raises(ContractError, match='parent timestamps'):
        pipeline._validate({**row, 'wall_ns': 99}, trial, case, set())


def test_pipeline_schedule_two_warmups_and_seven_independent_rounds_per_direction():
    rows = list(pipeline._schedule())
    for direction in ('encode', 'decode'):
        assert [r['phase'] for r in rows if r['direction'] == direction] == ['warmup'] * 2 + ['measured'] * 7
