"""Real-corpus Sprintz frame boundaries, native query, and detached restoration."""
from pathlib import Path
import struct

import pytest

from tsbench.application.m3_sprintz_query import ROWS, SprintzHardwarePending, _observe, _read_frame, invoke
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / 'build/m3-real-r8/plugins/codecs/sprintz-fire/tsbench_sprintz_corpus_query_control'
PLAN = ROOT / 'results/m3-real-r16-20261119/plan.json'


@pytest.mark.skipif(not CONTROL.exists(), reason='build tsbench_sprintz_corpus_query_control')
@pytest.mark.parametrize('rows', [1, 17, ROWS, ROWS + 1])
def test_query_is_archive_only_and_decode_recovers_full_columns(tmp_path, rows):
    detached = tmp_path / 'detached'
    detached.mkdir()
    staging = tmp_path / 'staging'
    staging.mkdir()
    output = detached / 'restored'
    output.mkdir()
    columns = [b''.join(struct.pack('<4H', 0xffff ^ (i & 31), 0x8000, (i * 7) & 65535, mask)
                        for i in range(rows)) for mask in (0x7ff8, 0xfff0)]
    for col, data in enumerate(columns):
        (staging / f'column-{col:04d}.bin').write_bytes(data)
    archive = detached / 'archive'
    try:
        encoded, _ = invoke(CONTROL, tmp_path, 'encode', 'staging', 2, rows, archive)
    except SprintzHardwarePending as exc:
        pytest.skip(str(exc))
    for p in staging.iterdir():
        p.unlink()
    staging.rmdir()
    queried, _ = invoke(CONTROL, detached, 'query', 'archive', 2, rows, '-')
    decoded, _ = invoke(CONTROL, detached, 'decode', 'archive', 2, rows, 'restored')
    records = iter(zip(encoded['units'], queried['units'], decoded['units'], strict=True))
    with archive.open('rb') as stream:
        for col, raw in enumerate(columns):
            assert (output / f'column-{col:04d}.bin').read_bytes() == raw
            for start in range(0, rows, ROWS):
                frame = _read_frame(stream)
                e, q, d = next(records)
                span = raw[start * 8:(start + ROWS) * 8]
                seen = _observe(span, frame, e, q, d, col, start)
                assert seen['auto']['count'] == [len(span) // 8] * 4
                assert seen['auto']['sum'][1] == 0x8000 * (len(span) // 8)
                assert seen['auto']['max'][3] == (0x7ff8 if col == 0 else 0xfff0)
                invalid = {**q, 'auto': {**q['auto'], 'max': [0] * 4}}
                with pytest.raises(ContractError, match='unsigned count/sum/max differs'):
                    _observe(span, frame, e, invalid, d, col, start)
        assert not stream.read(1)
    assert next(records, None) is None
    valid = archive.read_bytes()
    for bad in (valid[:-1], valid + b'\0', valid[:24] + bytes([valid[24] ^ 1]) + valid[25:]):
        (detached / 'bad').write_bytes(bad)
        with pytest.raises(ContractError, match='Sprintz query failed'):
            invoke(CONTROL, detached, 'query', 'bad', 2, rows, '-')


@pytest.mark.skipif(not PLAN.exists(), reason='requires r16 real-corpus plan')
def test_binding_rejects_resealed_query_control_mutation():
    plan = load_json(PLAN)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    binding = next(r for r in plan['routes'] if (r['selection'], r['route']) == (19, 'query'))
    assert binding['driver'] == 'sprintz-corpus-query/1'
    plan['build']['sprintz_query']['dependency']['sha256'] = '0' * 64
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='M3 Sprintz query control binding is stale'):
        check_m3_real_corpus_plan(ROOT, plan)
