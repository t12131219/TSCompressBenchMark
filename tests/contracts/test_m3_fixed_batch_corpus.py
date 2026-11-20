from copy import deepcopy
from hashlib import sha256

import pytest

from tsbench.application import m3_fixed_batch_corpus as corpus
from tsbench.application.m3_measurement_inventory import _exact_extent
from tsbench.assets import ContractError
from tsbench.planner.m3_fixed_batch import DRIVER


def frame_id(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def fixture(view):
    column = view == 'f64_columns'
    route = (11, 'source-auto') if column else (39, 'xz-baseline')
    extent = {'representation': view, 'full_extent_of_file_rows_and_value_columns': True,
              'row_ranges': [{'object_id': 'object', 'partition': 'full', 'start': 0, 'end': 8193}],
              'value_column_range': [0, 1], 'skipped_row_ranges': [],
              'slice_extent': {'max_per_unit': 65536, 'unit': 'row_span' if column else 'byte_span'},
              'column_grouping': 'one_work_unit_series_per_value_column' if column else 'all_values_interleaved',
              'size_estimate': {'input_units': 1 if column else 2, 'native_input_bytes_one_pass': 65544}}
    entry = {'canonical': {'object_id': 'object'}, 'rows': 8193, 'value_count': 1}
    item = {'selection': route[0], 'route': route[1], 'plugin': corpus.ROUTES[route], 'operation': 'roundtrip',
            'canonical_object_id': 'object', 'view': view, 'input': extent}
    proof = {'driver': DRIVER, 'recovery_id': 'frozen', 'units': []}
    for unit in corpus.geometry(item):
        n = unit['input_bytes']
        original = {'raw': frame_id(b'x' * n), 'schema': frame_id(corpus.unit_schema(view, n)),
                    'dtype': 10 if column else 2, 'count': n // 8 if column else n}
        proof['units'].append({**unit, 'original': original, 'artifact': frame_id(bytes(256)),
                               'encode': {'native': {'operation': 'encode'}},
                               'decodes': {'default': {'native': {'operation': 'decode'}, 'restored': deepcopy(original)}}})
    return item, entry, proof


@pytest.mark.parametrize('view', ('v_bytes_interleaved', 'f64_columns'))
def test_fixed_batch_extent_billing_and_replay(view):
    item, entry, proof = fixture(view)
    units = corpus.project(item, entry, proof, 'frozen')
    assert sum(u['input_bytes'] for u in units) == 65544
    assert all(sum(u['cost'].values()) == u['artifact']['bytes'] for u in units)
    case = {'configuration': item['input'], 'view': view, 'units': units}
    assert _exact_extent('fixed-batch-corpus', case, item)
    assert not _exact_extent('fixed-batch-corpus', {**case, 'units': units[:-1]}, item)
    if view == 'v_bytes_interleaved':
        assert units[-1]['byte_range'] == [65536, 65544]
    proof['units'][-1]['decodes']['default']['restored']['raw']['sha256'] = 'wrong'
    with pytest.raises(ContractError, match='recovery'):
        corpus.project(item, entry, proof, 'frozen')


def test_fixed_batch_refuses_foreign_recovery_and_extent():
    item, entry, proof = fixture('f64_columns')
    with pytest.raises(ContractError, match='frozen extent'):
        corpus.project(item, entry, proof, 'foreign')
    entry['rows'] += 1
    with pytest.raises(ContractError, match='frozen extent'):
        corpus.project(item, entry, proof, 'frozen')


def test_durable_sync_requires_run_ancestry(tmp_path):
    run = tmp_path / 'run'
    folder = run / 'case' / 'out'
    folder.mkdir(parents=True)
    artifact = folder / 'group'
    artifact.write_bytes(b'frame')
    corpus._sync({'group': artifact}, run)
    with pytest.raises(ContractError, match='escaped'):
        corpus._sync({'group': artifact}, tmp_path / 'foreign')
