import json

import pytest

from tsbench.application import m3_zfp_field_timing as z
from tsbench.application.m3_measurement_inventory import _case_parts, _exact_extent
from tsbench.assets import ContractError


def make_case(rows=142):
    return {'case_id': 'field-file', 'rows': rows, 'columns': 1,
            'lanes': {k: [{'bytes': 48}] for k in z.LANES}, 'order': [list(z.LANES)]*4}


def write_line(path, row):
    path.write_text(json.dumps(row) + '\n')


def test_counts_actual_full_and_tail_work_not_configured_threads(tmp_path):
    c, lane, path = make_case(), 'openmp-omp2', tmp_path / 'observer.stdout'
    meta = {'column': 0, **z._field_record(142, 48, 'omp2')}
    one = {'tid': 9, 'full': 35, 'tail': 1}
    write_line(path, {**meta, 'caller_tid': 9, 'block_workers': [one]})
    result = z._native(c, lane, 'encode', path, 'observer')
    assert result == {'whole_columns_by_participating_threads': {'1': 1}, 'full_blocks_per_column': 35,
                      'tail_blocks_per_column': 1, 'configured_threads': 2}
    write_line(path, {**meta, 'caller_tid': 9, 'block_workers': [one, {'tid': 10, 'full': 0, 'tail': 1}]})
    with pytest.raises(ContractError, match='full/tail'):
        z._native(c, lane, 'encode', path, 'observer')
    write_line(path, {**meta, 'caller_tid': 9, 'block_workers': [{**one, 'tail': 0}]})
    with pytest.raises(ContractError, match='full/tail'):
        z._native(c, lane, 'encode', path, 'observer')


def test_no_instrumentation_clock_can_be_laundered_as_timing(tmp_path):
    c, lane, path = make_case(), 'openmp-omp2', tmp_path / 'worker.stdout'
    meta = {'column': 0, **z._field_record(142, 48, 'serial')}
    write_line(path, {**meta, 'caller_tid': 9, 'block_workers': [{'tid': 9, 'full': 35, 'tail': 1}],
                      'call_wall_ns': 20, 'call_cpu_ns': 22})
    for arm in ('observer', 'timing'):
        with pytest.raises(ContractError, match='configuration differs'):
            z._native(c, lane, 'decode', path, arm)
    write_line(path, {**meta, 'call_wall_ns': 20, 'call_cpu_ns': 22})
    assert z._native(c, lane, 'decode', path, 'timing') == {
        'api_wall_ns': 20, 'api_process_cpu_ns': 22, 'configured_threads': 1}


def test_same_work_requires_distinct_frozen_routes_and_complete_columns():
    c = make_case()
    scope = {'value_column_range': [0, 1], 'row_ranges': [{'start': 0, 'end': 142}],
             'size_estimate': {'native_input_bytes_one_pass': 1136, 'input_units': 1}}
    c['variants'] = {route: {'route': route, 'work_item_id': str(i), 'configuration': scope} for i, route in enumerate(z.ROUTES)}
    parts = list(_case_parts('zfp-field', c))
    assert len(parts) == 3 and all(part is None and _exact_extent('zfp-field', variant, {'input': scope}) for variant, part in parts)
    assert not _exact_extent('zfp-field', {**parts[0][0], 'rows': 141}, {'input': scope})
    slots = list(z._schedule(c))
    assert len(slots) == 40 and len({s['path'] for s in slots}) == 40
    assert len([s for s in slots if s['lane'] == 'openmp-omp2' and s['op'] == 'encode' and s['phase'] == 'measure']) == 3
