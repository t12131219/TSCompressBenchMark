"""M3 Sprintz uses the frozen public ABI and separate compressed-domain route."""
from pathlib import Path
import struct

import pytest

from tsbench.application.m3_sprintz import _call, verify_frame
from tsbench.application.m3_sprintz_query import SprintzHardwarePending
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_sprintz import BATCH, DRIVER
from tsbench.planner.sprintz_execution import PLUGIN, TOOL

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r20-20261119/plan.json'


def test_r20_sprintz_scope_and_same_frozen_denominator():
    current = load_json(PLAN)
    previous = load_json(ROOT / 'results/m3-real-r19-20261119/plan.json')
    check_m3_real_corpus_plan(ROOT, current)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(current, 'plan')
    for key in ('coverage', 'definition', 'build', 'obligations', 'work_items'):
        assert current[key] == previous[key]
    for old, now in zip(previous['routes'], current['routes'], strict=True):
        if (old['selection'], old['route']) == BATCH:
            assert now['driver'] == DRIVER
            assert {k: v for k, v in now.items() if k != 'driver'} == {k: v for k, v in old.items() if k != 'driver'}
        else:
            assert now == old
    special = current['specialized']['sprintz']
    assert (len(special['obligation_slots']), len(special['slots'])) == (10, 20)
    assert sum(bool(s['expected_status']) for s in special['slots'].values()) == 2
    assert {k: v for k, v in current['specialized'].items() if k != 'sprintz'} == previous['specialized']


@pytest.mark.parametrize('mutate', ('slot_mapping', 'dependency'))
def test_rehash_cannot_change_frozen_sprintz_binding(mutate):
    plan = load_json(PLAN)
    special = plan['specialized']['sprintz']
    if mutate == 'slot_mapping':
        special['obligation_slots'][next(iter(special['obligation_slots']))] = []
    else:
        special['decoder']['files']['lib/librepaired_codec.so']['sha256'] = '0' * 64
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='Sprintz'):
        check_m3_real_corpus_plan(ROOT, plan)


def test_public_abi_recovers_opaque_f64_limb_tail_from_frame_only(tmp_path):
    spec = load_json(PLAN)['specialized']['sprintz']['decoder']
    worker, library, direct = [ROOT / spec['files'][p]['source'] for p in
                               (spec['worker'], spec['plugins'][PLUGIN], spec['tools'][TOOL])]
    source, detached = tmp_path / 'source', tmp_path / 'detached'
    source.mkdir()
    detached.mkdir()
    raw = struct.pack('<3Q', 0x8000000000000000, 0x7ff8000000000001, 0x0011223344556677)
    schema = b'{"role":"value","dtype":"u16","rows":3,"lanes":4}'
    (source / 'raw').write_bytes(raw)
    (source / 'schema').write_bytes(schema)
    try:
        _call(worker, library, direct, source, 'encode', '4', 'raw', 'schema', 'frame')
    except SprintzHardwarePending as exc:
        pytest.skip(str(exc))
    (source / 'frame').rename(detached / 'frame')
    (source / 'raw').unlink()
    (source / 'schema').unlink()
    source.rmdir()
    wire = (detached / 'frame').read_bytes()
    assert verify_frame(wire, raw, schema).startswith(b'SFB1')
    with pytest.raises(ContractError):
        verify_frame(wire + b'!', raw, schema)
    report, _ = _call(worker, library, direct, detached, 'decode-columns', 'frame', 'schema', 'raw')
    assert report[0] == {'columns': [{'count': 12, 'dtype': 4}]}
    assert (detached / 'raw').read_bytes() == raw
    assert (detached / 'schema').read_bytes() == schema
