"""Contract checks for dedicated page repetitions without optional build outputs."""
from struct import pack

import pytest

from tsbench.application.m3_pcodec_page_timing import (
    ROUNDS, _case_files, _direction, _frame, _ref, _semantic, _verify_trial,
)
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError


@pytest.fixture
def case(tmp_path):
    encode = {'rows': 17, 'pages': 1, 'meta_bytes': 2, 'payload_bytes': 0,
              'container_bytes': 24, 'zero_payload_pages': 1}
    decode = {'rows': 17, 'pages': 1, 'read_calls': 1, 'request_values': 257,
              'unaligned_request_status': 1, 'effective_read_capacity': 256, 'zero_payload_pages': 1}
    case = {'case_id': 'case', 'variants': {}}
    raw, reference = _case_files(tmp_path, case, 'native')
    raw.parent.mkdir(parents=True)
    raw.write_bytes(bytes(17 * 8))
    reference.write_bytes(b'PM3PAGE1' + pack('<IIII', 1, 2, 17, 0) + b'\0\0')
    case['original'] = _ref(raw)
    case['variants']['native'] = {'frame': _ref(reference), 'semantics': {'encode': encode, 'decode': decode}}
    trial = {'case_id': 'case', 'round': 1, 'phase': 'measured', 'direction': 'decode', 'lane': 'native', 'path': 'one'}
    scratch = tmp_path / trial['path']
    out = scratch / 'out'
    out.mkdir(parents=True)
    product = out / 'object'
    product.write_bytes(raw.read_bytes())
    native = {**decode, 'operation_wall_ns': 10, 'operation_cpu_ns': 0, 'process_peak_rss_bytes': 512}
    proc = {'operation': 'page', 'status': 'completed', 'returncode': 0, 'pid': 42,
            'session_id': '0' * 32, 'reason': '', 'process_wall_ns': 25,
            'child_usage': {'user_cpu_ns': 20, 'system_cpu_ns': 10, 'maxrss_bytes': 1024},
            'input_mounts': {'object': _ref(reference)}}
    write_new(scratch / 'page.stdout', native)
    (scratch / 'page.stderr').touch()
    row = {**trial, 'native': native, 'process': proc, 'files': {
        'stdout': _ref(scratch / 'page.stdout'), 'stderr': _ref(scratch / 'page.stderr'), 'product': _ref(product)}}
    return case, trial, row, reference, product


def test_decoding_only_mounts_lane_frame_not_plaintext(tmp_path, case):
    frozen, trial, row, _, _ = case
    seen = set()
    assert _verify_trial(tmp_path, frozen, trial, row, seen)['native_page_payload_bytes'] == 0
    with pytest.raises(ContractError, match='launcher identity'):
        _verify_trial(tmp_path, frozen, trial, row, seen)
    row['process']['input_mounts']['original'] = frozen['original']
    with pytest.raises(ContractError, match='input identity'):
        _verify_trial(tmp_path, frozen, trial, row, set())


def test_rehashed_product_and_bad_page_extent_are_rejected(tmp_path, case):
    frozen, trial, row, reference, product = case
    altered = b'\xff' + product.read_bytes()[1:]
    product.write_bytes(altered)
    row['files']['product'] = _ref(product)
    with pytest.raises(ContractError, match='timed output differs'):
        _verify_trial(tmp_path, frozen, trial, row, set())
    expected = frozen['variants']['native']['semantics']['encode']
    assert _frame(reference.read_bytes(), expected)['complete_frame_bytes'] == 26
    with pytest.raises(ContractError, match='byte accounting'):
        _frame(reference.read_bytes() + b'\0', expected)


def test_independent_wall_clocks_do_not_mix_with_warmups(case):
    _, _, row, _, _ = case
    measured = [{**row, 'round': i} for i in range(1, ROUNDS + 1)]
    results = _direction([*measured, {**row, 'phase': 'warmup'}], 'decode', 'native', 136)
    native = results['native_operation']['distributions_ns_or_bytes']
    process = results['supervised_process_tree_wait4']['distributions_ns_or_bytes']
    assert native['operation_wall_ns']['sum'] == 10 * ROUNDS
    assert native['operation_cpu_ns']['count'] == ROUNDS
    assert native['operation_wall_ns']['sample_basis'] == 'fresh_isolated_process_per_matched_measured_round'
    assert process['wall_ns']['sum'] == 25 * ROUNDS
    assert _semantic(row['native'])['request_values'] == 257
    with pytest.raises(ContractError, match='missing pcodec measured'):
        _direction(measured[1:], 'decode', 'native', 136)


def test_complete_cohort_includes_tail_but_not_extra_column_or_padding():
    from tsbench.application.m3_pcodec_page_timing import CHUNK_ROWS, FULL_SCOPE, _check_cohort, _complete_cohort

    def work(dataset, route, rows):
        return {'selection': 11, 'route': route, 'dataset_id': dataset, 'applicability': 'input_domain_matches',
                'input': {'full_extent_of_file_rows_and_value_columns': True, 'slice_extent': {'max_per_unit': CHUNK_ROWS},
                          'row_ranges': [{'partition': 'full', 'start': 0, 'end': rows}], 'value_column_range': [0, 3]}}

    work_items = [work(d, lane, n) for d, n in [('small', 90), ('tall', CHUNK_ROWS + 17)]
                  for lane in ('source-pages', 'native-pages')]
    cohort = _complete_cohort({'work_items': work_items})
    cases = [{'dataset_id': d, 'column': 0, 'rows': span} for d, span in [
        ('small', [0, 90]), ('tall', [0, CHUNK_ROWS]), ('tall', [CHUNK_ROWS, CHUNK_ROWS + 17])]]
    overlay = {'functional': {'scope': FULL_SCOPE}, 'cases': list(cases), 'cohort': cohort}
    assert _check_cohort(overlay) == cohort
    with pytest.raises(ContractError, match='omit or alter'):
        _check_cohort({**overlay, 'cases': cases[:-1]})
    with pytest.raises(ContractError, match='omit or alter'):
        _check_cohort({**overlay, 'cases': [*cases[:-1], {**cases[-1], 'column': 1}]})
    with pytest.raises(ContractError, match='omit or alter'):
        _check_cohort({**overlay, 'cases': [*cases[:-1], {**cases[-1], 'rows': [CHUNK_ROWS, 2 * CHUNK_ROWS]}]})
    with pytest.raises(ContractError, match='extents differ by lane'):
        _complete_cohort({'work_items': work_items[:-1]})


def test_canonical_projection_preserves_bits_and_exhausts_source(tmp_path, monkeypatch):
    from tsbench.application import m3_pcodec_page_timing as timing
    from tsbench.corpus_ingress import CorpusBatch

    entry = {'rows': 3, 'value_count': 2}
    words = [pack('<Q', x) for x in (1 << 63, 1, 0, 2, 3, 4)]
    consumed = []

    def source(root, actual):
        assert root == tmp_path and entry == actual
        yield CorpusBatch(0, 2, b'', b''.join(words[:4]))
        yield CorpusBatch(2, 1, b'', b''.join(words[4:]))
        consumed.append(True)

    monkeypatch.setattr(timing, '_entry_map', lambda r, d: {'file': entry})
    monkeypatch.setattr(timing, 'read_batches', source)
    specs = [('file', 0, 0, 2), ('file', 0, 2, 3), ('file', 1, 1, 3)]
    assert timing._read_columns(tmp_path, None, specs) == {
        specs[0]: words[0] + words[2], specs[1]: words[4], specs[2]: words[3] + words[5]}
    assert consumed == [True]
    with pytest.raises(ContractError, match='duplicated'):
        timing._read_columns(tmp_path, None, [specs[0], specs[0]])
