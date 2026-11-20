"""Native wall-clock boundaries are distinct and tied to the sealed operation."""
from copy import deepcopy

import pytest

from tsbench.application.m3_lzbench_corpus_clock import _schedule, _verify_clocks
from tsbench.assets import ContractError


def fixture(lane='synchronous', op='encode'):
    source = {'bytes': 131080, 'sha256': 'a' * 64}
    frame = {'bytes': 131200, 'sha256': 'b' * 64}
    xz2 = {**frame, 'sha256': 'c' * 64}
    a, b = (source, frame) if op == 'encode' else (xz2, source)
    is_xz_sync = lane == 'synchronous' and op == 'encode'
    functional = {'entry': 'lzma_block_encoder' if is_xz_sync else 'lzbench_native::session::process',
                  'input_bytes': a['bytes'], 'output_bytes': b['bytes'], 'effective_parameters': {'check': 4},
                  'calls': 2 if is_xz_sync else 8, 'jobs': {'jobs': 0 if is_xz_sync else 5,
                  'worker_threads': 0 if is_xz_sync else 1, 'caller_jobs': 0},
                  'blocks': 2 if is_xz_sync else 0, 'uncompressed_fallback_blocks': 1 if is_xz_sync else 0}
    variants = {lane: {'expected': {op: functional}, 'frame': frame, 'decode_anchor': '2'}, '2': {'frame': xz2}}
    c = {'variants': variants, 'source': source}
    t = {'direction': op, 'lane': lane}
    def bucket(n):
        return {'calls': n, 'wall_ns': 10 * n}
    clock = {'functional': deepcopy(functional), 'driver_wall_ns': 800, 'first_driver_output_wall_ns': 30,
             'first_driver_output_bytes': 12, 'native_setup': bucket(4 if is_xz_sync else 2),
             'native_process': bucket(9 if is_xz_sync else 8), 'native_framing': bucket(13 if is_xz_sync else 0),
             'native_cleanup': bucket(3 if is_xz_sync else 1)}
    proc = {'operation': 'native', 'returncode': 0, 'status': 'completed', 'reason': '', 'pid': 33,
            'input_mounts': {'object': a}, 'session_id': 'd' * 32, 'process_wall_ns': 1000,
            'child_usage': {'user_cpu_ns': 900, 'system_cpu_ns': 120, 'maxrss_bytes': 8192}}
    path = {'source_to_synced_output_wall_ns': 1300, 'output_fsync_wall_ns': 200}
    return c, t, clock, proc, path, b


def test_xz_synchronous_requires_stream_block_and_index_work_even_with_fallback():
    c, t, clock, proc, path, want = fixture()
    assert _verify_clocks(c, t, clock, proc, path, set()) == want
    clock['native_framing']['calls'] -= 1
    with pytest.raises(ContractError, match='synchronous native operation coverage'):
        _verify_clocks(c, t, clock, proc, path, set())


def test_worker_timing_keeps_input_mount_and_actual_native_job_counts():
    c, t, clock, proc, path, want = fixture('1', 'decode')
    assert _verify_clocks(c, t, clock, proc, path, set()) == want
    with pytest.raises(ContractError, match='fixed input mount'):
        _verify_clocks(c, t, clock, {**proc, 'input_mounts': {'object': c['variants']['1']['frame']}}, path, set())
    clock['functional']['jobs']['jobs'] -= 1
    with pytest.raises(ContractError, match='worker-hook job accounting'):
        _verify_clocks(c, t, clock, proc, path, set())


def test_fsync_is_outside_native_process_and_included_in_staged_path():
    c, t, clock, proc, path, _ = fixture()
    with pytest.raises(ContractError, match='durable path clock'):
        _verify_clocks(c, t, clock, proc, {**path, 'source_to_synced_output_wall_ns': 1100}, set())
    with pytest.raises(ContractError, match='clock scopes'):
        _verify_clocks(c, t, {**clock, 'driver_wall_ns': 1001}, proc, path, set())


def test_externally_paired_schedule_keeps_warmup_out_of_three_measured_rounds():
    c = {'case_id': 'a', 'order': [['1', '2'], ['2', '1'], ['1', '2'], ['2', '1']]}
    rows = list(_schedule(c))
    assert len(rows) == len({r['path'] for r in rows}) == 16
    assert [r['direction'] for r in rows[:4]] == ['encode', 'encode', 'decode', 'decode']
    assert [r['phase'] for r in rows].count('warmup') == 4
    assert [r['round'] for r in rows if r['phase'] == 'measured'] == [1] * 4 + [2] * 4 + [3] * 4


def test_xz_mt_decode_hook_entries_vary_with_resume_scheduling():
    c, t, clock, proc, path, want = fixture('1', 'decode')
    c['codec'] = 'xz'
    clock['functional']['jobs']['jobs'] += 4
    assert _verify_clocks(c, t, clock, proc, path, set()) == want
    clock['functional']['jobs']['worker_threads'] = 2
    with pytest.raises(ContractError, match='observed labor'):
        _verify_clocks(c, t, clock, proc, path, set())
