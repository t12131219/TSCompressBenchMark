"""Gorilla C11 corpus route/state controls and millisecond binding."""
from pathlib import Path
import struct

import numpy as np
import pytest

from tsbench.application.m3_gorilla import (HEADER, MAGIC, PAIR, ROWS, MAX_SECONDS, MIN_SECONDS, invoke,
                                          milliseconds, read_frame, restore_independent)
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / 'build/m3-real-r8/plugins/codecs/gorilla-tv/tsbench_gorilla_corpus_control'
PLAN = ROOT / 'results/m3-real-r17-20261119/plan.json'


def test_civil_millisecond_scaling_and_i64_limits():
    a = np.array([MIN_SECONDS, -2, 0, 2, MAX_SECONDS], dtype='<i8')
    assert milliseconds(a).tolist() == [int(s) * 1000 for s in a]
    for bad in (MIN_SECONDS - 1, MAX_SECONDS + 1):
        with pytest.raises(ContractError, match='exceeds i64'):
            milliseconds(np.array([bad], dtype='<i8'))


@pytest.mark.skipif(not CONTROL.exists(), reason='build tsbench_gorilla_corpus_control')
@pytest.mark.parametrize('mode', ['tv-batch', 'append-resume', 'iterator'])
def test_state_iter_and_bit_preservation_without_source_files(tmp_path, mode):
    n = ROWS + 1
    ts = [(j // 2 - 8) * 1000 for j in range(n)]  # duplicate timestamps, including per-block seek midpoint
    v = [0x8000000000000000, 0x7ff8000000000051, 2, 0x7ff0000000000000] * 129
    source = tmp_path / 'columns'
    source.mkdir()
    (source / 'axis.ms').write_bytes(struct.pack(f'<{n}q', *ts))
    (source / 'column-0000.bin').write_bytes(struct.pack(f'<{n}Q', *v[:n]))
    work = tmp_path / 'detached'
    work.mkdir()
    archive = work / 'full'
    state = mode == 'append-resume'
    encoded, _ = invoke(CONTROL, tmp_path, 'encode', mode, 'columns', 1, n, archive, work / 'snap' if state else '-')
    for p in source.iterdir():
        p.unlink()
    source.rmdir()
    (work / 'restored').mkdir()
    decoded, _ = invoke(CONTROL, work, 'decode', mode, 'full', 'restored')
    expected = b''.join(PAIR.pack(t, x) for t, x in zip(ts, v))
    assert (work / 'restored' / 'column-0000.tv').read_bytes() == expected
    with archive.open('rb') as f:
        assert f.read(HEADER.size) == HEADER.pack(MAGIC, 1, n)
        full, tail = read_frame(f, ROWS), read_frame(f, 1)
        assert not f.read(1)
    assert restore_independent(full, ROWS) + restore_independent(tail, 1) == expected
    if state:
        (work / 'prefix').mkdir()
        records, _ = invoke(CONTROL, work, 'decode', 'snapshots', 'snap', 'prefix')
        assert [o[2] for o in records['units']] == [256, 0]
        assert (work / 'prefix' / 'column-0000.tv').read_bytes() == expected[:256 * 16]
        assert [o[4] for o in encoded['units']] == [256, 0]
    if mode == 'iterator':
        # The target is the timestamp of row 256. The first of the equal T
        # group must be returned, and an ordinary tail still drains to EOF.
        assert decoded['units'][0][-3:] == [ts[256], ts[256], v[256]]
        assert decoded['units'][1][-3:] == [ts[512], ts[512], v[512]]
    raw = archive.read_bytes()
    for invalid in (raw[:-1], raw + b'\0', raw[:HEADER.size] + b'\xff' * 4 + raw[HEADER.size + 4:]):
        (work / 'invalid').write_bytes(invalid)
        with pytest.raises(ContractError, match='Gorilla.*failed'):
            invoke(CONTROL, work, 'decode', mode, 'invalid', 'restored')


@pytest.mark.skipif(not PLAN.exists(), reason='requires r17 plan')
def test_plan_binds_three_routes_and_rejects_resealed_c_dependency_swap():
    plan = load_json(PLAN)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    routes = [r for r in plan['routes'] if r['selection'] == 7]
    assert len(routes) == 3 and all(r['driver'] == 'gorilla-corpus-control/1' for r in routes)
    plan['build']['gorilla_corpus']['dependency']['sha256'] = '0' * 64
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='Gorilla TV control binding is stale'):
        check_m3_real_corpus_plan(ROOT, plan)


@pytest.mark.skipif(not CONTROL.exists(), reason='build tsbench_gorilla_corpus_control')
def test_frozen_unique_resume_failure_when_prefix_does_not_define_xor_window(tmp_path):
    stage = tmp_path / 'columns'
    stage.mkdir()
    (stage / 'axis.ms').write_bytes(struct.pack('<4q', 0, 1000, 2000, 3000))
    (stage / 'column-0000.bin').write_bytes(struct.pack('<4Q', 0, 0, 1, 1))
    with pytest.raises(ContractError, match='resumed result differs from batch bytes'):
        invoke(CONTROL, tmp_path, 'encode', 'append-resume', 'columns', 1, 4, 'result', 'snapshots')
