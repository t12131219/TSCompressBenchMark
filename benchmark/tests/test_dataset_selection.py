"""Projection keeps value bytes, validity and channel meaning aligned."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tsbench.data import array_order, load_dataset, project, raw_bytes, validate_selection_spec
from tsbench.schemes import ObjectScheme, decode_once
from tsbench.validate import verify


def test_csv_joint_column_window_projection_and_standalone_recovery(tmp_path):
    path = tmp_path / 'records.csv'
    path.write_text('t,a,b,c\n10,1,,3\n20,,5,6\n30,7,8,\n40,10,11,12\n')
    spec = {'path': path.name, 'format': 'csv', 'dtype': '<f8', 'columns': ['a', 'b', 'c'],
            'timestamp_column': 't', 'missing': 'mask', 'fill_value': -0.0,
            'start': 1, 'stop': 4, 'step': 2, 'columns_indices': [2, 0], 'order': 'F'}
    original = load_dataset(spec, tmp_path)
    assert original.schema['columns'] == ['c', 'a']
    assert original.components['V'].tolist() == [[6, -0.0], [12, 10]]
    assert original.components['mask'].tolist() == [[1, 0], [1, 1]]
    assert original.components['T'].tolist() == [20, 40]
    assert np.signbit(original.components['V'][0, 1])
    assert array_order(original.components['V']) == array_order(original.components['mask']) == 'F'
    assert all(not array.flags.writeable for array in original.components.values())
    assert raw_bytes(project(original, {'kind': 'values'})) == 36
    assert raw_bytes(original) == 52
    assert original.lineage['parse_rule']['columns'] == ['a', 'b', 'c']
    assert original.lineage['selection']['windows']['T']['selected_rows'] == 2
    restored = decode_once(ObjectScheme({'codec': 'raw-store'}).encode_once(original))
    assert restored.schema['columns'] == ['c', 'a']
    assert verify(original, restored, {'fidelity': 'bitwise'})['passed']


def test_npz_joint_projection_schema_and_mask_payload(tmp_path):
    values = np.arange(12, dtype='<i2').reshape(4, 3)
    mask = np.array([[1, 0, 1], [0, 1, 1], [1, 1, 0], [0, 0, 1]], dtype='u1')
    timestamps = np.arange(4, dtype='<i8')
    np.savez(tmp_path / 'records.npz', values=values, validity=mask, time=timestamps)
    original = load_dataset({'path': 'records.npz', 'components': {'V': 'values', 'mask': 'validity', 'T': 'time'},
                             'columns_indices': [1, 0], 'schema': {'columns': ['x', 'y', 'z']},
                             'start': 0, 'stop': 4, 'step': 2}, tmp_path)
    assert original.components['V'].tolist() == [[1, 0], [7, 6]]
    assert original.components['mask'].tolist() == [[0, 1], [1, 1]]
    assert original.schema['columns'] == ['y', 'x']
    assert original.components['T'].tolist() == [0, 2]


@pytest.mark.parametrize('start,stop', [(0, 0), (3, 3)])
def test_zero_length_window_is_explicit_and_valid(tmp_path, start, stop):
    np.save(tmp_path / 'source.npy', np.arange(6, dtype='<f4').reshape(3, 2))
    original = load_dataset({'path': 'source.npy', 'start': start, 'stop': stop,
                             'columns_indices': [1], 'schema': {'columns': ['a', 'b']}}, tmp_path)
    assert original.components['V'].shape == (0, 1)
    assert original.schema['columns'] == ['b']
    assert original.lineage['selection']['windows']['V']['selected_rows'] == 0
    assert verify(original, decode_once(ObjectScheme({'codec': 'raw-store'}).encode_once(original)), {'fidelity': 'bitwise'})['passed']


def test_empty_source_and_explicit_zero_channels_preserve_shape(tmp_path):
    np.save(tmp_path / 'empty.npy', np.empty((0, 3), dtype='<f8'))
    loaded = load_dataset({'path': 'empty.npy', 'columns_indices': []}, tmp_path)
    assert loaded.components['V'].shape == (0, 0)
    assert loaded.lineage['selection']['windows']['V']['source_rows'] == 0


@pytest.mark.parametrize('format,order', [('npy', 'C'), ('npy', 'F'), ('npz', 'C'), ('npz', 'F')])
def test_projection_and_strided_window_preserve_source_order_by_default(tmp_path, format, order):
    values = np.array(np.arange(20, dtype='<f8').reshape(5, 4), order=order)
    path = tmp_path / ('source.' + format)
    if format == 'npy':
        np.save(path, values)
    else:
        np.savez(path, V=values)
    original = load_dataset({'path': path.name, 'start': 0, 'stop': 5, 'step': 2,
                             'columns_indices': [3, 1]}, tmp_path)
    assert array_order(original.components['V']) == order
    assert original.components['V'].tolist() == [[3, 1], [11, 9], [19, 17]]


@pytest.mark.parametrize('spec', [
    {'start': True}, {'start': 0.0}, {'start': '0'}, {'start': -1},
    {'stop': False}, {'stop': 1.0}, {'stop': -1}, {'start': 2, 'stop': 1},
    {'step': True}, {'step': 1.0}, {'step': 0}, {'step': -1},
    {'columns_indices': [True]}, {'columns_indices': [0.0]}, {'columns_indices': '1'},
    {'columns_indices': [-1]}, {'columns_indices': [1, 1]}, {'order': 'A'}, {'order': None}, {'order': []},
])
def test_selection_controls_reject_silent_index_coercion(spec):
    with pytest.raises(ValueError):
        validate_selection_spec(spec)


@pytest.mark.parametrize('selection', [{'start': 4}, {'stop': 4}, {'start': 3, 'stop': 4}, {'columns_indices': [2]}])
def test_source_bounds_are_not_silently_clipped(tmp_path, selection):
    np.save(tmp_path / 'source.npy', np.arange(6, dtype='<i2').reshape(3, 2))
    with pytest.raises(ValueError, match='bounds'):
        load_dataset({'path': 'source.npy', **selection}, tmp_path)


def test_projection_rejects_misaligned_source_mask_and_names(tmp_path):
    np.savez(tmp_path / 'bad.npz', V=np.ones((3, 2)), mask=np.ones((3, 3), dtype='u1'))
    with pytest.raises(ValueError, match='before column selection'):
        load_dataset({'path': 'bad.npz', 'components': {'V': 'V', 'mask': 'mask'}, 'columns_indices': [0]}, tmp_path)
    np.save(tmp_path / 'matrix.npy', np.ones((3, 2)))
    with pytest.raises(ValueError, match='original V channel count'):
        load_dataset({'path': 'matrix.npy', 'columns_indices': [0], 'schema': {'columns': ['wrong']}}, tmp_path)
    np.save(tmp_path / 'vector.npy', np.ones(3))
    with pytest.raises(ValueError, match='rank-2'):
        load_dataset({'path': 'vector.npy', 'columns_indices': [0]}, tmp_path)


def test_worker_build_evidence_keeps_actual_compilers_and_commands(tmp_path, monkeypatch):
    from tsbench.worker import Worker
    import tsbench.worker
    import tsbench.schemes
    import tsbench.data
    root = Path(__file__).resolve().parents[2]
    lib = tmp_path / 'codec.so'
    lib.write_bytes(b'fixture')
    record = {'compilers': {'cc': {'version': 'fixture', 'sha256': 'exact'}},
              'commands': [['cc', '-O3', '-fPIC', '-c', 'fixture.c']], 'profile': 'release'}
    (tmp_path / 'build.json').write_text(json.dumps(record))
    np.save(tmp_path / 'source.npy', np.arange(3, dtype='<f8'))
    monkeypatch.setattr(tsbench.schemes, 'capability', lambda *args, **kwargs: {'supported': True, 'library_paths': [str(lib)]})
    monkeypatch.setattr(tsbench.schemes.ObjectScheme, 'prepare', lambda *args: None)
    monkeypatch.setattr(tsbench.worker, 'implementation_identity', lambda *args: 'fixture-identity')
    worker = Worker(lambda event: None)
    assert worker.dispatch({'op': 'init', 'method': {'codec': 'raw-store'}, 'task': {'kind': 'values','boundary':'object_memory'},
                            'profile': {}, 'execution': {'memory_limit_mb': None}, 'asset_root': str(root),
                            'build_root': str(tmp_path), 'base_dir': str(tmp_path)})['status'] == 'ok'
    evidence = worker.dispatch({'op': 'prepare', 'dataset': {'path': 'source.npy'}})['build_evidence'][0]
    assert evidence['compilers'] == record['compilers']
    assert evidence['commands'] == record['commands']
