from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from verify_m3_sprintz_full_ledger import BATCH, DRIVER, QUERY, _file_only, project, same_first_unit
from tsbench.assets import ContractError


def fixture(tmp, which):
    suffix, driver = ('batch-sample.bmk', DRIVER) if which == BATCH else ('query-sample.sfb1', 'sprintz-corpus-query/1')
    n = 'batch' if which == BATCH else 'query'
    item = {'selection': which[0], 'route': which[1], 'work_item_id': n, 'input':
            {'slice_extent': {'max_per_unit': 8192}, 'size_estimate': {'input_units': 1},
             'row_ranges': [{'start': 0, 'end': 2}], 'value_column_range': [0, 1]}}
    raw = n.encode()
    path = tmp / 'retained' / n / suffix
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    identity = sha256(raw).hexdigest()
    unit = {'column': 0, 'row_start': 0, 'row_end': 2, 'raw_bytes': 16, 'restored_sha256': 'same',
            'frame_sha256': identity, 'artifact_bytes' if which == BATCH else 'frame_bytes': len(raw)}
    if which == BATCH:
        unit.update(sfb1_bytes=5, sfb1_sha256=sha256(b'query').hexdigest())
    sample = {'path': path.relative_to(tmp).as_posix(), 'bytes': len(raw), 'sha256': identity, 'observation': dict(unit)}
    return item, {'dataset_id': 'test', 'evidence': {'driver': driver, 'units': [unit], 'retained_sample': sample}}


def test_retained_first_unit_projects_both_routes_and_requires_parity(tmp_path):
    b, bp = project(tmp_path, *fixture(tmp_path, BATCH))
    q, qp = project(tmp_path, *fixture(tmp_path, QUERY))
    assert b['rows'] == q['rows'] == 2 and bp.suffix == '.bmk' and qp.suffix == '.sfb1'
    same_first_unit(b, q)
    b['units'][0]['sfb1_bytes'] += 1
    with pytest.raises(ContractError, match='embedded frame'):
        same_first_unit(b, q)


def test_retained_first_unit_does_not_replace_a_different_sealed_sample(tmp_path):
    item, row = fixture(tmp_path, QUERY)
    row['evidence']['retained_sample']['observation']['row_start'] = 1
    with pytest.raises(ContractError, match='first retained frame identity'):
        project(tmp_path, item, row)


def test_replay_must_mount_only_the_sealed_frame_in_a_fresh_process(tmp_path):
    case, _ = project(tmp_path, *fixture(tmp_path, QUERY))
    art = {k: case['artifact'][k] for k in ('bytes', 'sha256')}
    mounts = {'archive.sfb1': art}
    proc = {'status': 'completed', 'returncode': 0, 'session_id': 'x', 'input_mounts': mounts}
    seen = set()
    _file_only(case, 'archive.sfb1', proc, seen)
    with pytest.raises(ContractError, match='fresh frame-only'):
        _file_only(case, 'archive.sfb1', proc, seen)
    with pytest.raises(ContractError, match='fresh frame-only'):
        _file_only(case, 'archive.sfb1', {**proc, 'input_mounts': {**mounts, 'raw.csv': art}}, set())
