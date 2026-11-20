import os
from pathlib import Path
import struct

import pytest

from tsbench.application.m3_zfp import ARRAY_LAYOUT, array_evidence, array_unit, array_windows, field_unit
from tsbench.assets import ContractError


def test_array_windows_respect_locked_gaps_and_balanced_tail():
    def group(spans, gaps):
        return {'accepted_spans': [{'rows': [a, b], 'windows': parts, 'base_rows': (b-a)//parts,
                                   'first_windows_with_one_extra_row': (b-a)%parts} for a,b,parts in spans],
                'excluded_spans': [{'rows': [a, b]} for a,b in gaps]}
    spec = {'layout': ARRAY_LAYOUT, 'row_coordinates': 'absolute_zero_based_half_open',
            'default_column': group([(0, 8189, 2)], []),
            'column_overrides': [{'value_column_index': 1, **group([(0, 17, 2), (18, 8189, 2)], [(17, 18)])}]}
    assert list(array_windows(spec, 2, 8189)) == [(0, 0, 4095), (0, 4095, 8189), (1, 0, 9), (1, 9, 17),
                                                (1, 18, 4104), (1, 4104, 8189)]
    spec['column_overrides'][0]['excluded_spans'] = []
    with pytest.raises(ContractError, match='gap or overlap'):
        list(array_windows(spec, 2, 8189))


def test_array_quality_uses_mutated_original_and_checks_untouched_tail():
    original = list(map(float, range(13)))
    changed = original.copy()
    changed[1] = original[-1]
    changed[3:7] = original[:4]
    pack = lambda xs: struct.pack('<13d', *xs)
    wire = bytes(64)
    ok = array_evidence(pack(original), wire, wire, pack(original), pack(changed))
    assert ok['quality_passed'] and ok['unchanged_native_blocks'] == 2
    assert not array_evidence(pack(original), wire, wire, pack(original), pack(original))['quality_passed']
    with pytest.raises(ContractError, match='untouched'):
        array_evidence(pack(original), wire, wire[:-1]+b'\x01', pack(original), pack(changed))


@pytest.fixture
def control():
    path = os.environ.get('TSBENCH_ZFP_CORPUS_CONTROL')
    if not path:
        pytest.skip('set TSBENCH_ZFP_CORPUS_CONTROL to the built native corpus executable')
    return Path(path).resolve(strict=True)


def test_native_tail_and_three_field_policies_on_identical_bytes(control, tmp_path):
    # The last four words are -0, +inf, -inf, and a NaN with payload bits.
    words = [0x3ff0000000000000 + i for i in range(1025)] + [
        0x8000000000000000, 0x7ff0000000000000, 0xfff0000000000000, 0x7ff8000000000001]
    raw = struct.pack(f'<{len(words)}Q', *words)
    report, parts = field_unit(control, tmp_path, raw, openmp=True)
    assert list(parts) == ['serial', 'omp1', 'omp2']
    assert report['identical_payloads']
    assert all(p['restored'] == report['same_field'] for p in report['profiles'].values())


def test_native_array_update_and_two_independent_reopens(control, tmp_path):
    raw = struct.pack('<13d', *range(13))
    report, parts = array_unit(control, tmp_path, raw)
    assert report['quality_passed'] and set(parts) == {'before', 'after', 'metadata.json'}
    assert parts['before'] != parts['after']
    assert report['config']['effective_rate'] == 32
    with pytest.raises(ContractError, match='retained sentinel'):
        array_unit(control, tmp_path, struct.pack('<13d', -9999, *range(12)), retained_sentinel=True)


def test_r23_frozen_plan_has_full_fields_and_exact_array_denominator():
    from tsbench.assets import load_json
    from tsbench.contracts import load_contract
    from tsbench.planner.m3_zfp import DRIVER, ROUTES

    root = Path(__file__).resolve().parents[2]
    plan_file = root / 'results/m3-real-r23-20261119/plan.json'
    if not plan_file.is_file():
        pytest.skip('real-corpus r23 evidence not present')
    plan = load_json(plan_file)
    load_contract(root, 'm3-real-corpus-plan').validate(plan, 'r23')
    assert {(r['selection'], r['route']) for r in plan['routes'] if r['driver'] == DRIVER} == ROUTES
    array_units = 0
    for selection, route in ROUTES:
        items = [r for r in plan['work_items'] if (r['selection'], r['route']) == (selection, route)]
        assert len(items) == 23
        for row in items:
            scope = row['input']
            assert row['applicability'] == 'input_domain_matches'
            assert scope['value_column_range'][0] == 0
            cols = scope['value_column_range'][1]
            assert len(scope['row_ranges']) == 1 and scope['row_ranges'][0]['start'] == 0
            n = scope['row_ranges'][0]['end']
            observed = scope['size_estimate']
            if route == 'fixed-rate-array':
                windows = list(array_windows(scope['array_contract'], cols, n))
                array_units += len(windows)
                assert len(windows) == observed['input_units']
                assert 8*sum(b-a for _, a, b in windows) == observed['native_input_bytes_one_pass']
            else:
                assert scope['full_extent_of_file_rows_and_value_columns'] is True
                assert observed['input_units'] == cols and observed['native_input_bytes_one_pass'] == 8*n*cols
    assert array_units == 20520
