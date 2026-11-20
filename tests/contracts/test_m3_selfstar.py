"""Corpus SElf* is whole-column, not independent fixture-sized chunks."""
from pathlib import Path

import pytest

from tsbench.application.m3_selfstar import launch, restore, validate_profiles, wire_facts
from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_selfstar import DRIVERS
from tsbench.planner.selfstar import BLOCK, fixture
from tsbench.qualification.selfstar_wire import read_frame

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r21-20261119/plan.json'


def test_r21_preserves_denominator_and_other_frozen_drivers():
    plan = load_json(PLAN)
    prior = load_json(ROOT / 'results/m3-real-r20-20261119/plan.json')
    check_m3_real_corpus_plan(ROOT, plan)
    load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    for k in ('definition', 'coverage', 'build', 'work_items', 'obligations'):
        assert prior[k] == plan[k]
    for r in plan['routes']:
        key = r['selection'], r['route']
        if key in DRIVERS:
            assert r['driver'] == DRIVERS[key]
        else:
            assert r in prior['routes']
    assert {k: v for k, v in plan['specialized'].items() if k != 'selfstar'} == prior['specialized']
    binding = plan['specialized']['selfstar']
    assert len(binding['obligation_slots']) == 9 and len(binding['slots']) == 25
    assert sum(bool(slot['expected_status']) for slot in binding['slots'].values()) == 7


def test_rehash_does_not_allow_changing_selfstar_obligation():
    plan = load_json(PLAN)
    mapping = plan['specialized']['selfstar']['obligation_slots']
    mapping[next(iter(mapping))] = []
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match=r'SElf\*'):
        check_m3_real_corpus_plan(ROOT, plan)


def test_complete_column_cross_api_parity_and_native_tail(tmp_path):
    binding = load_json(PLAN)['specialized']['selfstar']
    n = 10017  # Beyond the specialist control's 4096 rows; requires state across 20 blocks.
    raw = fixture(64, n)
    schema = b'{"role":"value"}'
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'raw').write_bytes(raw)
    (source / 'schema').write_bytes(schema)
    enc, _ = launch(ROOT, binding, True, source, 'live', ['raw', 'schema', 'live.bmk'])
    abi, _ = launch(ROOT, binding, False, source, 'encode', ['10', 'raw', 'schema', 'batch.bmk'])
    (source / 'raw').write_bytes(raw[8*BLOCK:16*BLOCK])
    launch(ROOT, binding, True, source, 'live', ['raw', 'schema', 'reset-mid-column.bmk'])
    wire = (source / 'live.bmk').read_bytes()
    assert wire == (source / 'batch.bmk').read_bytes()
    # Starting a new native context for block two does not yield that block's bytes.
    assert read_frame(wire, 64, n, schema)[1] != read_frame((source / 'reset-mid-column.bmk').read_bytes(), 64, BLOCK, schema)[0]
    (source / 'raw').unlink()
    (source / 'schema').unlink()
    facts = wire_facts(wire, n, schema)
    assert (facts['blocks'], facts['last_block_rows']) == (20, 289)
    with pytest.raises(ContractError):
        wire_facts(wire[:-1], n, schema)
    for lane, observed, src in ((True, enc, 'batch.bmk'), (False, abi, 'live.bmk')):
        detached = tmp_path / f'decoder-{lane}'
        detached.mkdir()
        frame = detached / 'frame'
        (source / src).rename(frame)
        decoded, _ = restore(ROOT, binding, lane, detached, frame)
        assert (detached / 'raw').read_bytes() == raw
        assert (detached / 'schema').read_bytes() == schema
        validate_profiles(observed, decoded, lane, n, facts)
