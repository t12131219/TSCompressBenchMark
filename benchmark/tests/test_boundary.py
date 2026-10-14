"""Boundary evidence and statistics checks; no benchmark or native compile."""
import importlib.util
from pathlib import Path
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('boundary_experiment', Path(__file__).parents[1] / 'tools/boundary_experiment.py')
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)


def test_fixture_reproducible_typed_bytes_and_lengths():
    for length in (0, 1, 257):
        first = boundary.fixture(length, 20261013)
        assert first.dtype.str == '|u1'
        assert first.shape == (length,)
        assert len(first.tobytes()) == length
        assert first.tobytes() == boundary.fixture(length, 20261013).tobytes()
        assert not first.size or first.max() < 16
    with pytest.raises(ValueError, match='negative'):
        boundary.fixture(-1, 1)


def test_primary_statistics_use_independent_session_medians():
    rows = [{'status': 'ok', 'codec': 'x', 'length': 1, 'session': session,
             'boundaries': {'direct_c': {'encode_ns': value, 'decode_ns': value + 1, 'encode_prepare_ns': 7}}}
            for session, value in [(0, 1), (0, 3), (0, 5), (1, 100)]]
    rows.append({'status': 'error'})
    stats = boundary.summarize(rows)
    encoded = next(item for item in stats if item['operation'] == 'encode_ns')
    assert encoded['independent_session_summary']['n'] == 2
    assert encoded['independent_session_summary']['median'] == 51.5
    assert encoded['all_rounds_descriptive']['median'] == 4
    assert [item['rounds'] for item in encoded['session_medians']] == [3, 1]
    assert any(item['operation'] == 'encode_prepare_ns' for item in stats)


def test_paired_ratios_remain_separate_from_object_wire():
    rows = [{'status': 'ok', 'codec': 'x', 'length': 0, 'session': 0,
             'boundaries': {'object_wire': {'encode_ns': 100, 'decode_ns': 90}},
             'paired_ratios': {'encode_ns': 1.25, 'decode_ns': 2.0}}]
    stats = boundary.summarize(rows)
    ratios = [item for item in stats if item['operation'].endswith('_ratio')]
    assert len(ratios) == 2
    assert all(item['boundary'] == 'python_native_api/direct_c' for item in ratios)
    assert boundary.distribution([])['median'] is None


def paired_row(directory):
    raw = boundary.preserve(directory, b'input')
    payload = boundary.preserve(directory, b'compressed')
    header = boundary.preserve(directory, b'header')
    wire = boundary.preserve(directory, b'headercompressed')
    obj = {'payload': payload, 'restored': raw, 'header': header, 'wire': wire,
           'actual_native_input': {'content_sha256': raw['sha256']}, 'codec_input_bytes': raw['nbytes']}
    return {'actual_input': raw, 'typed_input': dict(raw),
            'boundaries': {'direct_c': {'payload': payload, 'restored': raw},
                           'python_native_api': {'payload': payload, 'restored': raw}, 'object_wire': obj}}


def test_all_retained_products_are_rehashed_and_wire_reconstructed(tmp_path):
    row = paired_row(tmp_path)
    assert boundary.verify_round_artifacts(row) == 10
    Path(row['boundaries']['object_wire']['wire']['path']).write_bytes(b'corruption')
    with pytest.raises(AssertionError, match='artifact differs'):
        boundary.verify_round_artifacts(row)


def test_input_pairing_and_content_addressed_corruption_rejected(tmp_path):
    row = paired_row(tmp_path)
    row['boundaries']['object_wire']['actual_native_input']['content_sha256'] = 'different'
    with pytest.raises(AssertionError, match='native input differs'):
        boundary.verify_round_artifacts(row)
    record = boundary.preserve(tmp_path, b'unique')
    Path(record['path']).write_bytes(b'changed')
    with pytest.raises(AssertionError, match='collision'):
        boundary.preserve(tmp_path, b'unique')


def test_subprocess_crash_and_timeout_become_diagnostic_failures():
    with pytest.raises(RuntimeError, match='returncode=4'):
        boundary.checked_process([sys.executable, '-c', 'raise SystemExit(4)'], timeout=5)
    with pytest.raises(RuntimeError, match='timeout'):
        boundary.checked_process([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=0.05)
    done = boundary.checked_process([sys.executable, '-c', 'print("ok")'], timeout=5)
    assert done.stdout.strip() == 'ok'


def test_actual_runtime_overlap_compares_hashes_without_prefix():
    python = [{'path': '/conda/libgcc_s.so.1', 'sha256': 'sha256:abc'}]
    native = [{'path': '/system/libgcc_s.so.1', 'sha256': 'abc'}]
    assert boundary.runtime_overlap(python, native)['hashes_equal'] is True
    native[0]['sha256'] = 'other'
    result = boundary.runtime_overlap(python, native)
    assert result['hashes_equal'] is False
    assert result['differences'][0]['name'] == 'libgcc_s'
