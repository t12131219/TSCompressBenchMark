from copy import deepcopy
from hashlib import sha256
from itertools import count

import pytest

from tsbench.application.m3_fixed_batch import _publish_sample
from tsbench.application.m3_ledger_census import _unit_census, check_retention
from tsbench.assets import ContractError, canonical_bytes
from tsbench.planner.m3_fixed_batch import AUTO, DRIVER, LIMITS, RETENTION, SCALAR, sample_indices, units


def _work_item(*, byte_view=False):
    return {
        'view': 'v_bytes_interleaved' if byte_view else 'f64_columns',
        'selection': 40 if byte_view else 9,
        'route': 'zstd-baseline' if byte_view else 'decode-backends',
        'operation': 'roundtrip' if byte_view else 'decode_common_frame',
        'plugin': 'zstd' if byte_view else 'alp-auto',
        'input': {
            'full_extent_of_file_rows_and_value_columns': True, 'skipped_row_ranges': [],
            'row_ranges': [{'start': 0, 'end': 69680}], 'value_column_range': [0, 7],
            'column_grouping': 'all_values_interleaved' if byte_view else 'one_work_unit_series_per_value_column',
            'slice_extent': {'unit': 'byte_span' if byte_view else 'row_span', 'max_per_unit': 65536},
            'size_estimate': {'input_units': 60 if byte_view else 14, 'native_input_bytes_one_pass': 3902080,
                              'largest_input_unit_bytes': 65536 if byte_view else 524288},
        },
    }


def test_frozen_batch_geometry_splits_columns_and_interleaved_bytes_differently():
    assert list(units(_work_item())) == [
        {'column': c, 'row_range': [a, b], 'input_bytes': (b - a) * 8}
        for c in range(7) for a, b in ((0, 65536), (65536, 69680))]
    byte_units = list(units(_work_item(byte_view=True)))
    assert len(byte_units) == 60
    assert byte_units[0] == {'byte_range': [0, 65536], 'input_bytes': 65536}
    assert byte_units[-1] == {'byte_range': [3866624, 3902080], 'input_bytes': 35456}
    assert all(left['byte_range'][1] == right['byte_range'][0] for left, right in zip(byte_units, byte_units[1:]))


@pytest.fixture
def alp_evidence():
    item = _work_item()
    binding = {'decoder': {'recovery_id': 'recovery'}, 'limits': LIMITS}
    seq = count(1)

    def operation(label, backend, mounts, native):
        i = next(seq)
        return {'process': {'operation': label, 'status': 'completed', 'returncode': 0, 'pid': i,
                            'session_id': f'{i:032x}', 'reason': '', 'input_mounts': deepcopy(mounts),
                            'options': {'decode_backend': backend}}, 'native': native}

    rows = []
    for unit in units(item):
        n = unit['input_bytes'] // 8
        schema = canonical_bytes({'role': 'value', 'dtype': 'f64', 'rows': n})
        source = {'dtype': 10, 'count': n,
                  'raw': {'bytes': unit['input_bytes'], 'sha256': 'a' * 64},
                  'schema': {'bytes': len(schema), 'sha256': sha256(schema).hexdigest()}}
        frame = {'bytes': 100, 'sha256': 'c' * 64}
        rows.append({**unit, 'original': source, 'artifact': frame,
                     'encode': operation('encode', SCALAR, {k: source[k] for k in ('raw', 'schema')},
                                         {'backend': 'alpn-auto-encoder'}),
                     'decodes': {tag: {**operation(f'decode-{tag}', tag, {'frame': frame},
                                                   {'requested_backend': tag, 'backend': backend}),
                                       'restored': deepcopy(source)}
                                 for tag, backend in ((SCALAR, SCALAR), (AUTO, 'falp-avx2'))}})
    return item, {'selection': 9, 'route': 'decode-backends', 'status': 'verified',
                  'evidence': {'driver': DRIVER, 'recovery_id': 'recovery', 'units': rows,
                               'process_timing_scope': 'isolated_process_diagnostic_not_m2_measurement',
                               'timing_admitted': False}}, binding


def test_census_proves_same_frame_in_separate_sessions(alp_evidence):
    observed = _unit_census(*alp_evidence)
    assert observed['matches_frozen_units']
    assert observed['shared_artifact_reuse_proved']
    assert observed['decode_scope'] == 'isolated_process_frame_only'


@pytest.mark.parametrize('change', ['mount', 'extra-mount', 'session', 'tail', 'restored', 'legacy'])
def test_census_rejects_substituted_detached_evidence(alp_evidence, change):
    item, row, binding = alp_evidence
    unit = row['evidence']['units'][1]
    decoder = unit['decodes'][AUTO]['process']
    if change == 'mount':
        decoder['input_mounts']['frame']['sha256'] = 'd' * 64
    elif change == 'extra-mount':
        decoder['input_mounts']['raw'] = unit['original']['raw']
    elif change == 'session':
        decoder['session_id'] = unit['encode']['process']['session_id']
    elif change == 'tail':
        unit['row_range'] = [65535, 69679]
    elif change == 'restored':
        unit['decodes'][AUTO]['restored']['schema']['sha256'] = 'e' * 64
    else:
        row['evidence']['driver'] = 'legacy'
    with pytest.raises(ContractError):
        _unit_census(item, row, binding)


def test_sample_geometry_and_released_byte_accounting(alp_evidence):
    item, row, binding = alp_evidence
    assert sample_indices(item) == (0, 1)
    assert sample_indices(_work_item(byte_view=True)) == (0, 59)
    small = deepcopy(item)
    small['input']['row_ranges'][0]['end'] = 8
    assert sample_indices(small) == (0,)
    evidence = row['evidence']
    artifact = evidence['units'][0]['artifact']
    path = f"{RETENTION['directory']}/{artifact['sha256']}.bmk"
    evidence['retained_samples'] = [{'unit_index': i, 'path': path, **artifact} for i in (0, 1)]
    evidence['released_frames'] = {'count': 12, 'bytes': 1200}
    assert len(check_retention(item, evidence)) == 2
    assert _unit_census(item, row, {**binding, 'retention': RETENTION})['shared_artifact_reuse_proved']
    for key, replacement in (('retained_samples', evidence['retained_samples'][1:]),
                             ('released_frames', {'count': 12, 'bytes': 1199})):
        with pytest.raises(ContractError, match='retention or released byte accounting'):
            check_retention(item, {**evidence, key: replacement})


def test_sample_store_shares_identical_frames_and_rejects_existing_wrong_content(tmp_path):
    data = b'test frame'
    src = tmp_path / 'source.bmk'
    src.write_bytes(data)
    digest = sha256(data).hexdigest()
    ref = {'path': f"{RETENTION['directory']}/{digest}.bmk", 'sha256': digest, 'bytes': len(data)}
    _publish_sample(tmp_path, src, ref)
    _publish_sample(tmp_path, src, ref)
    assert list((tmp_path / RETENTION['directory']).iterdir()) == [tmp_path / ref['path']]
    (tmp_path / ref['path']).write_bytes(b'wrong')
    with pytest.raises(ContractError, match='retained batch frame differs'):
        _publish_sample(tmp_path, src, ref)
