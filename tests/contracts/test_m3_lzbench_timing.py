"""The isolated lzbench repeat contract does not turn configured workers into work."""
import copy

import pytest

from tsbench.application.m3_lzbench_timing import ROUNDS, _summary, _verify_native
from tsbench.assets import ContractError


def group():
    raw = {'bytes': 2048, 'sha256': '0' * 64}
    frame1 = {'bytes': 221, 'sha256': '1' * 64}
    frame2 = {'bytes': 225, 'sha256': '2' * 64}
    native = {'entry': 'lzbench_native::session::process', 'input_bytes': 225, 'output_bytes': 2048,
              'calls': 8, 'jobs': {'jobs': 8, 'worker_threads': 1, 'caller_jobs': 0},
              'effective_parameters': {'threads': 1}}
    pc = {'operation': 'native', 'returncode': 0, 'status': 'completed', 'reason': '', 'pid': 75,
          'input_mounts': {'object': frame2}, 'session_id': 'f' * 32, 'process_wall_ns': 31,
          'child_usage': {'user_cpu_ns': 11, 'system_cpu_ns': 14, 'maxrss_bytes': 8192}}
    variants = {'1': {'expected': {'decode': native, 'encode': native}, 'frame': frame1, 'decode_anchor': '2'},
                '2': {'expected': {'decode': native, 'encode': native}, 'frame': frame2, 'decode_anchor': '2'}}
    case = {'variants': variants, 'source': raw, 'case_id': 'case', 'dataset_id': 'dataset', 'route': 'xz-workers',
            'work_item_id': 'item', 'operation_config_id': 'config'}
    trial = {'direction': 'decode', 'lane': '1'}
    return case, trial, native, pc


def test_shared_xz_decode_product_bound_to_two_worker_frame():
    case, trial, native, proc = group()
    assert _verify_native(case, trial, native, proc, set()) == case['source']
    wrong = {**proc, 'input_mounts': {'object': case['variants']['1']['frame']}}
    with pytest.raises(ContractError, match='fixed input mount'):
        _verify_native(case, trial, native, wrong, set())
    other = {**proc, 'input_mounts': {**proc['input_mounts'], 'original': case['source']}}
    with pytest.raises(ContractError, match='fixed input mount'):
        _verify_native(case, trial, native, other, set())


def test_configured_thread_is_not_enough_and_clock_not_invented():
    case, trial, native, proc = group()
    wrong = copy.deepcopy(native)
    wrong['jobs']['worker_threads'] = 0
    with pytest.raises(ContractError, match='observed labor'):
        _verify_native(case, trial, wrong, proc, set())
    rows = [{**trial, 'lane': lane, 'direction': op, 'phase': 'measured', 'native': native, 'process': proc}
            for lane in case['variants'] for op in ('encode', 'decode') for _ in range(ROUNDS)]
    warm = {**rows[0], 'phase': 'warmup', 'process': {**proc, 'process_wall_ns': 5000}}
    result = _summary(case, [warm, *rows])['lanes']['1']['directions']['encode']
    assert result['native_operation_wall_ns'] is None
    assert result['first_output'] is None
    assert result['first_output_missing'] == 'worker_control_does_not_record_first_output'
    assert result['observed_background_workers'] == {'1': ROUNDS}
    assert result['distributions']['process_wall_ns']['sum'] == 31 * ROUNDS


def test_zstd_worker_decodes_the_own_lane_frame_but_runs_zero_worker_mode():
    from tsbench.application.m3_lzbench_timing import _variant
    a, b = {'sha256': 'a' * 64, 'bytes': 105}, {'sha256': 'b' * 64, 'bytes': 110}
    obs = {'jobs': {'jobs': 0, 'worker_threads': 0, 'caller_jobs': 0}}
    proof = {'codec': 'zstd', 'encode': {'0': {'frame': a, 'observed': obs, 'wire': {}},
                                       '2': {'frame': b, 'observed': obs, 'wire': {}}},
             'decode_own': {'0': {'source_frame': a, 'observed': obs}, '2': {'source_frame': b, 'observed': obs}},
             'retained': {}}
    got = _variant(proof, '2')
    assert got['retain'] is None and got['decode_anchor'] == '2' and got['frame'] == b
    proof['decode_own']['2']['source_frame'] = a
    with pytest.raises(ContractError, match='reference frame differs'):
        _variant(proof, '2')
