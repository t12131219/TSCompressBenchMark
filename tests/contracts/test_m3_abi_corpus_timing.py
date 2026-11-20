"""Transport grouping does not change original ABI frames or their charge."""
from copy import deepcopy
from pathlib import Path
import struct
import subprocess

import pytest

from tsbench.application import m3_abi_corpus_timing as timing
from tsbench.assets import ContractError, load_json

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / 'build/m3-abi-corpus-diagnostic/tsbench_abi_corpus'
LOCK = ROOT / 'results/m3-real-r8-20261119/build-lock.json'


def test_groups_keep_atomic_frames_and_bound_both_lanes(monkeypatch):
    monkeypatch.setattr(timing, 'GROUP_BYTES', 100)
    def row(raw, wire):
        return {'original': {'bytes': raw}, 'schema': {'bytes': 1}, 'artifact': {'bytes': wire}}
    units = [row(51, 20), row(31, 40), row(10, 70), row(32, 30)]
    assert list(timing.groups(units)) == [(0, 2), (2, 4)]
    with pytest.raises(ContractError, match='exceeds ABI diagnostic group budget'):
        list(timing.groups([row(1, 101)]))


def test_exact_frame_verification_rejects_reordering_and_trailing_bytes(tmp_path):
    a, b = b'first', b'secon'
    units = [{'original': {'bytes': 8}, 'schema': {'bytes': 1}, 'artifact': timing.br(f)} for f in (a, b)]
    p = tmp_path / timing.name(0)
    p.write_bytes(a+b)
    assert timing.verify_frames({p.name: p}, units) == {p.name: timing.br(a+b)}
    p.write_bytes(b+a)
    with pytest.raises(ContractError, match='frame differs'):
        timing.verify_frames({p.name: p}, units)
    p.write_bytes(a+b+b'x')
    with pytest.raises(ContractError, match='trailing bytes'):
        timing.verify_frames({p.name: p}, units)


def test_fec1_validation_rejects_backend_drift_and_original_mount():
    unit = {'original': {'bytes': 16}, 'artifact': {'bytes': 90}, 'schema': {'bytes': 7}, 'modes': {'huffman': 1}}
    case = {'case_id': 'test', 'plugin': 'huff0-reference', 'units': [unit]}
    plan = {'env': {'cpu': 6}}
    wire, raw = {'g00000.bin': timing.br(bytes(90))}, {'g00000.bin': timing.br(bytes(31))}
    t = {'operation': 'decode', 'phase': 'measured', 'round': 1}
    row = {**t, 'case_id': 'test', 'output': raw, 'staged_supervision_and_verification_wall_ns': 80,
           'process': {'status': 'completed', 'operation': 'decode', 'returncode': 0, 'reason': '', 'pid': 11,
                       'session_id': '1', 'input_mounts': wire, 'process_wall_ns': 70, 'child_usage': {'maxrss_bytes': 5}},
           'native': {'abi_wall_ns': 25, 'context_create_wall_ns': 2, 'cpu_endpoints': [6, 6], 'frames': 1, 'groups': 1,
                      'raw_bytes': 16, 'archive_bytes': 90, 'execution_census': [{'count': 1, 'info': {
                          'operation': 'decode', 'threads': 1, 'mode': 'batch', 'backend': 'runtime-bmi2', 'fallback': False,
                          'blocks': 1, 'raw_blocks': 0, 'rle_blocks': 0, 'huffman_blocks': 1}}]}}
    timing.validate(plan, case, t, row, wire, raw, set())
    wrong = deepcopy(row)
    wrong['native']['execution_census'][0]['info']['backend'] = 'no-huffman-decode'
    with pytest.raises(ContractError, match='backend or raw fallback'):
        timing.validate(plan, case, t, wrong, wire, raw, set())
    wrong = deepcopy(row)
    wrong['process']['input_mounts']['original'] = timing.br(bytes(16))
    with pytest.raises(ContractError, match='coverage, resource or outputs'):
        timing.validate(plan, case, t, wrong, wire, raw, set())


@pytest.mark.skipif(not NATIVE.is_file() or not LOCK.is_file(), reason='requires ABI corpus wrapper and frozen modules')
@pytest.mark.parametrize('plugin', ('huff0-reference', 'sprintz-fire'))
def test_native_multiple_groups_use_only_wire_on_decode(tmp_path, plugin):
    build = load_json(LOCK)['plugins'][plugin]
    library = ROOT / build['library']['path']
    raw, encoded, decoded = (tmp_path / s for s in ('raw', 'encoded', 'decoded'))
    for p in (raw, encoded, decoded):
        p.mkdir()
    expected = {}
    for g, ns in enumerate(([65536, 8], [8, 24])):
        blocks = []
        for n in ns:
            schema = b'{"test":"bounded-group"}'
            blocks.append(struct.pack('<II', n, len(schema)) + schema + bytes([g + 4]) * n)
        expected[timing.name(g)] = b''.join(blocks)
        (raw / timing.name(g)).write_bytes(expected[timing.name(g)])
    def run(op, src, dst):
        return subprocess.run([NATIVE, op, library, plugin, '{}', src, dst, '2'], timeout=10,
                              text=True, capture_output=True, check=False)
    made = run('encode', raw, encoded)
    if plugin == 'sprintz-fire' and 'Sprintz requires' in made.stderr:
        pytest.skip(made.stderr.strip())
    assert made.returncode == 0, made.stderr
    for p in raw.iterdir():
        p.unlink()
    raw.rmdir()
    got = run('decode', encoded, decoded)
    assert got.returncode == 0, got.stderr
    assert {p.name: p.read_bytes() for p in decoded.iterdir()} == expected
    (encoded / timing.name(1)).write_bytes((encoded / timing.name(1)).read_bytes()[:-1])
    broken = run('decode', encoded, decoded)
    assert broken.returncode != 0 and 'ABI envelope geometry' in broken.stderr
