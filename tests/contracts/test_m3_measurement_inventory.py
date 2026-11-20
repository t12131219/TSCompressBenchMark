import pytest

from tsbench.application.m3_measurement_inventory import _exact_extent, _slice_scope
from tsbench.assets import ContractError


def test_first_full_column_is_not_multi_column_extent():
    scope = {'value_column_range': [0, 2], 'row_ranges': [{'start': 0, 'end': 69680}]}
    prefix = [{'column': 0, 'rows': [0, 65536]}, {'column': 0, 'rows': [65536, 69680]}]
    assert _slice_scope(prefix, scope) == 'projected_extent'
    assert _slice_scope(prefix + [{'column': 1, 'rows': [0, 69680]}], scope) == 'frozen_extent'
    # A case with only one applicable value column really is full-scope.
    assert _slice_scope(prefix, {**scope, 'value_column_range': [0, 1]}) == 'frozen_extent'
    assert _slice_scope([prefix[0], {'column': 1, 'rows': [0, 69680]}], scope) == 'projected_extent'


def test_timed_gap_is_not_filled_by_a_projection_or_overrun():
    scope = {'value_column_range': [0, 1], 'row_ranges': [{'start': 0, 'end': 2048}, {'start': 3072, 'end': 4096}]}
    parts = [{'column': 0, 'rows': [0, 2048]}, {'column': 0, 'rows': [3072, 4096]}]
    assert _slice_scope(parts, scope) == 'frozen_extent'
    assert _slice_scope(parts[:1], scope) == 'projected_extent'
    with pytest.raises(ContractError, match='outside'):
        _slice_scope([{'column': 0, 'rows': [0, 4096]}], scope)
    with pytest.raises(ContractError, match='outside'):
        _slice_scope([{'column': 1, 'rows': [0, 2048]}], scope)


def test_gorilla_full_rows_do_not_substitute_for_full_units_or_shared_tv():
    item = {'input': {'value_column_range': [0, 2], 'row_ranges': [{'start': 0, 'end': 530}],
                      'size_estimate': {'input_units': 4, 'native_input_bytes_one_pass': 16960}}}
    c = {'columns': 2, 'rows': 530, 'units': 4, 'input_bytes': 16960}
    assert _exact_extent('gorilla', c, item)
    assert not _exact_extent('gorilla', {**c, 'units': 2}, item)
    assert not _exact_extent('gorilla', {**c, 'columns': 1}, item)
    assert not _exact_extent('gorilla', {**c, 'input_bytes': 12720}, item)


def test_titchy_cross_seal_projection_keeps_wire_identity_and_native_work():
    from copy import deepcopy
    from tsbench.application import m3_measurement_inventory as inventory
    from tsbench.application import m3_titchy_stream_timing as stream

    pieces = {'tstr': {'path': 'here.tstr', 'bytes': 77, 'sha256': 'a' * 64},
              'tsc1': {'path': 'here.tsc1', 'bytes': 32, 'sha256': 'b' * 64}}
    geometry = {'column': 0, 'row_range': [0, 8], 'restored_sha256': 'c' * 64}
    unit = {**geometry, **dict.fromkeys(stream.COST, 1), 'logical_input_bytes': 64,
            'archive_sha256': pieces['tstr']['sha256'], 'config_sha256': pieces['tsc1']['sha256'],
            'encode': {'wall_ns': 100, 'first_packet_ns': 33, 'first_packet_after_push': 7},
            'decode': {'wall_ns': 200, 'logical_samples': 8}}
    row = {'route': 'packet-stream', 'status': 'verified', 'evidence': {'driver': 'titchy-stream-control/1',
                                                                           'units': [unit],
                                                                           'retained_sample': {**geometry, 'parts': pieces}}}
    compare = lambda r: inventory._titchy_facts(inventory._titchy_column(r))
    other = deepcopy(row)
    other['evidence']['retained_sample']['parts']['tstr']['path'] = 'old/anchor.tstr'
    other['evidence']['units'][0]['encode']['wall_ns'] = 180
    assert compare(other) == compare(row)
    other['evidence']['units'][0]['encode']['first_packet_after_push'] = 8
    assert compare(other) != compare(row)
    other['evidence']['retained_sample']['parts']['tstr']['sha256'] = 'd' * 64
    with pytest.raises(ContractError, match='sample differs'):
        compare(other)


def test_column_batch_coverage_requires_all_columns_and_original_windows():
    cfg = {'value_column_range': [0, 2], 'row_ranges': [{'start': 0, 'end': 4}],
           'slice_extent': {'max_per_unit': 3}, 'size_estimate': {'native_input_bytes_one_pass': 64, 'input_units': 4}}
    units = [{'column': col, 'row_range': [start, end], 'original': {'bytes': (end-start)*8}}
             for col in range(2) for start, end in ((0, 3), (3, 4))]
    c = {'configuration': cfg, 'units': units}
    assert _exact_extent('column-batch', c, {'input': cfg})
    assert not _exact_extent('column-batch', {**c, 'units': units[:2] * 2}, {'input': cfg})
    swapped = [units[1], units[0], *units[2:]]
    assert not _exact_extent('column-batch', {**c, 'units': swapped}, {'input': cfg})
