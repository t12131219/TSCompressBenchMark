"""Check grouped transport, exact native output, and nested clock boundaries."""
from hashlib import sha256
import json
from pathlib import Path
import struct
import subprocess

import pytest

from tsbench.application import m3_huff0_etb1_timing as etb1, m3_sprintz_durable as sprintz
from tsbench.assets import ContractError

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/m3-real-r8/plugins/codecs'


def test_sprintz_group_limit_cuts_columns_not_frames(monkeypatch):
    monkeypatch.setattr(sprintz, 'GROUP_BYTES', 130)
    rows = sprintz.ROWS + 7
    units = [{'frame_bytes': n} for n in (49, 30, 18, 22, 34, 52)]
    assert sprintz.groups(rows, 3, units) == [
        {'name': 'archive-0000.sfb1', 'columns': [0, 2], 'bytes': 119},
        {'name': 'archive-0001.sfb1', 'columns': [2, 3], 'bytes': 86},
    ]
    with pytest.raises(ContractError, match='one column'):
        sprintz.groups(rows, 1, [{'frame_bytes': 100}, {'frame_bytes': 100}])


def _invoke(exe, lib, *args):
    # Historical native executable/DSO test only. Real runs use detached Bubblewrap.
    return subprocess.run([exe, *map(str, args)], env={'LC_ALL': 'C', 'LD_LIBRARY_PATH': str(lib)},
                          text=True, capture_output=True, timeout=30, check=False)


def _success(p):
    if p.returncode == 77:
        pytest.skip(p.stderr.strip())
    assert p.returncode == 0 and not p.stderr, p.stderr
    return json.loads(p.stdout)


def test_sprintz_one_context_preserves_legacy_wire_query_and_restore(tmp_path):
    lib = BASE / 'sprintz-fire'
    exe = ROOT / 'build/m3-sprintz-grouped-diagnostic/tsbench_sprintz_grouped'
    legacy = lib / 'tsbench_sprintz_corpus_query_control'
    if not exe.is_file() or not legacy.is_file():
        pytest.skip('requires prepared frozen Sprintz and grouped builds')
    source, group, restored = (tmp_path/n for n in ('source', 'group', 'restored'))
    for folder in (source, group, restored):
        folder.mkdir()
    rows = sprintz.ROWS + 3
    names = [f'column-{i:04d}.bin' for i in range(3)]
    values = [b''.join(struct.pack('<Q', i + col * rows) for i in range(rows)) for col in range(3)]
    for name, data in zip(names, values):
        (source/name).write_bytes(data)
    whole = tmp_path/'whole'
    before = _success(_invoke(legacy, lib, 'encode', source, 3, rows, whole))
    after = _success(_invoke(exe, lib, 'encode', source, 3, rows, group, '1,3'))
    assert b''.join(p.read_bytes() for p in sorted(group.iterdir())) == whole.read_bytes()
    assert before['workspace_bytes'] == after['workspace_bytes'] and [u['column'] for u in after['units']] == [0,0,1,1,2,2]
    old_query = _success(_invoke(legacy, lib, 'query', whole, 3, rows, '-'))
    new_query = _success(_invoke(exe, lib, 'query', group, 3, rows, '-', '1,3'))
    def facts(d):
        return [{k: v for k, v in u.items() if not k.endswith('_ns')} for u in d['units']]
    assert facts(old_query) == facts(new_query)
    _success(_invoke(exe, lib, 'decode', group, 3, rows, restored, '1,3'))
    assert [(restored/n).read_bytes() for n in names] == values
    assert _invoke(exe, lib, 'query', group, 3, rows, '-', '1,1,3').returncode != 0
    p = group/'archive-0000.sfb1'
    p.write_bytes(p.read_bytes()+b'x')
    assert 'trailing input' in _invoke(exe, lib, 'query', group, 3, rows, '-', '1,3').stderr


def test_etb1_table_construct_clock_and_detached_group_parity(tmp_path):
    lib = BASE/'huff0-reference'
    legacy = lib/'tsbench_huff0_corpus_table_control'
    exe = ROOT/'build/m3-huff0-etb1-diagnostic/tsbench_huff0_etb1_timing'
    if not legacy.is_file() or not exe.is_file():
        pytest.skip('requires prepared frozen Huff0 and ETB1 timing builds')
    train, held, model, old_model, whole = (tmp_path/p for p in ('train', 'held', 'model', 'old-model', 'whole'))
    source, wire, restored = (tmp_path/p for p in ('source', 'wire', 'decoded'))
    for path in (source, wire, restored):
        path.mkdir()
    a, b = b'ab' * (etb1.BLOCK//2), b'xyz' * 7
    train.write_bytes(b'abx' * 342)
    held.write_bytes(a+b)
    (source/'g00000.bin').write_bytes(a)
    (source/'g00001.bin').write_bytes(b)
    old = _success(_invoke(legacy, lib, 'train', 4, train, old_model))
    timed = _success(_invoke(exe, lib, 'train', 4, train, model))
    assert model.read_bytes() == old_model.read_bytes()
    assert {k: timed[k] for k in old} == old and timed['table_wall_ns'] > 0 and timed['block_calls_wall_ns'] == 0
    _success(_invoke(legacy, lib, 'encode', old_model, held, whole))
    setup = _success(_invoke(exe, lib, 'encode', model, source, wire, '1,1'))
    assert b''.join(p.read_bytes() for p in sorted(wire.iterdir())) == whole.read_bytes()
    for p in source.iterdir():
        p.unlink()
    source.rmdir()
    probe = _success(_invoke(exe, lib, 'decode', model, wire, restored, '1,1'))
    assert probe['table_wall_ns'] > 0 and probe['block_calls_wall_ns'] > 0 and probe['context_count'] == 1
    assert probe['blocks'] == setup['blocks'] == 2 and probe['raw_bytes'] == setup['raw_bytes'] == len(a+b)
    assert b''.join(p.read_bytes() for p in sorted(restored.iterdir())) == a+b
    p = wire/'g00000.bin'; p.write_bytes(p.read_bytes() + b'x')
    assert 'trailing ETB1 group bytes' in _invoke(exe, lib, 'decode', model, wire, restored, '1,1').stderr


def test_etb1_reconstructed_order_hash_not_a_set(tmp_path, monkeypatch):
    monkeypatch.setattr(etb1, 'GROUP_BLOCKS', 1)
    a, b = b'1', b'2'
    blocks = [{'original_bytes': 1, 'body_bytes': 1} for _ in range(2)]
    case = {'groups': etb1.groups(blocks), 'holdout': {'bytes': 2, 'sha256': sha256(a+b).hexdigest()}}
    (tmp_path/'g00000.bin').write_bytes(b)
    (tmp_path/'g00001.bin').write_bytes(a)
    with pytest.raises(ContractError, match='whole sequence digest'):
        etb1.verify_group_files(case, tmp_path, 'raw')
