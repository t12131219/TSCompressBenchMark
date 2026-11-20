"""Native packet clocks and two-part decode mounts stay separate from wrappers."""
import copy
from pathlib import Path

import pytest

from tsbench.application.m3_titchy_stream_timing import _measurements, _verify_trial, verify, ROUNDS
from tsbench.assets import ContractError, load_json

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'results/m3-titchy-stream-timing-20261120-r1/runs/d33a945ce2ad4168a1b8e8daa900cc4e'


def _case():
    raw = {'bytes': 128, 'sha256': '0' * 64}
    archive = {'bytes': 142, 'sha256': '1' * 64}
    policy = {'bytes': 32, 'sha256': '2' * 64}
    enc, dec = {'first_packet_after_push': 16}, {'packets': 1}
    case = {'original': raw, 'parts': {'tstr': archive, 'tsc1': policy}, 'expected_native': {'encode': enc, 'decode': dec},
            'billing': {'artifact_bytes': 174, 'first_packet_phase': 'finish'}, 'dataset_id': 'd',
            'work_item_id': 'w', 'operation_config_id': 'c', 'range': [0, 16], 'value_column': 0}
    process = {'operation': 'stream', 'status': 'completed', 'returncode': 0, 'reason': '', 'pid': 12,
               'session_id': 'a' * 32, 'input_mounts': {'archive': archive, 'policy': policy}, 'process_wall_ns': 90,
               'child_usage': {'user_cpu_ns': 20, 'system_cpu_ns': 11, 'maxrss_bytes': 8192}}
    decode = {'phase': 'measured', 'direction': 'decode', 'native': {**dec, 'wall_ns': 27},
              'process': process, 'outputs': {'original': raw}}
    encode = {'phase': 'measured', 'direction': 'encode', 'native': {**enc, 'wall_ns': 41, 'first_packet_ns': 31},
              'process': {**process, 'input_mounts': {'original': raw}, 'session_id': 'b' * 32},
              'outputs': {'archive': archive, 'policy': policy}}
    return case, encode, decode


def test_decode_mount_is_two_part_not_original_and_encode_first_packet_clock_has_scope():
    case, encode, decode = _case()
    unique = set()
    _verify_trial(case, decode, unique)
    _verify_trial(case, encode, unique)
    wrong = copy.deepcopy(decode)
    wrong['process']['input_mounts']['original'] = case['original']
    with pytest.raises(ContractError, match='mounts'):
        _verify_trial(case, wrong, set())
    with pytest.raises(ContractError, match='fresh complete process'):
        _verify_trial(case, decode, unique)
    encode['native']['first_packet_ns'] = 49
    with pytest.raises(ContractError, match='outside encode'):
        _verify_trial(case, encode, set())


def test_driver_and_process_clock_are_not_merged_and_warmup_is_excluded():
    case, encode, decode = _case()
    warmup = {**encode, 'phase': 'warmup'}
    report = _measurements(case, [warmup, *([encode, decode] * ROUNDS)])
    assert report['byte_accounting']['artifact_bytes'] == 174
    clk = report['directions']['encode']['distributions']
    assert clk['first_packet_native_driver_wall_ns']['sum'] == 31 * ROUNDS
    assert clk['native_driver_wall_ns']['sum'] == 41 * ROUNDS
    assert clk['process_wall_ns']['sum'] == 90 * ROUNDS
    assert 'first_packet_native_driver_wall_ns' not in report['directions']['decode']['distributions']


@pytest.mark.skipif(not RUN.is_dir(), reason='requires locally sealed real-packet evidence')
def test_real_two_dataset_evidence_recomputes():
    report = verify(RUN)
    assert report == load_json(RUN / 'report.json')
    assert report['verified_trials'] == 36
    assert not report['formal_performance']
