from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_huff0_specialized import obligation, scope
from tsbench.assets import ContractError, load_json
from tsbench.planner import huff0_bmi2 as bmi2
from tsbench.planner import huff0_execution as huff
from tsbench.planner.m3_huff0_specialized import bind_obligations

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r32-20261119/plan.json'


@pytest.fixture(scope='module')
def data():
    if not PLAN.is_file():
        pytest.skip('requires local real-corpus definition projection')
    fixtures, cases = huff.huff0_inputs(ROOT, compare_bmi2=True)
    slots = {p: s for p, (s, _) in fixtures.items()}
    return load_json(PLAN)['obligations'], slots, cases


def test_cross_route_boundary_uses_both_stream_configurations(data):
    obs, slots, cases = data
    required, condition = bind_obligations(ROOT, obs, slots, cases)
    boundary, = (r for r in obs if r['selection'] == 29 and r['check'] == 'fec1_fixed_4x_etb1_stream_boundary')
    members = [slots[p] for p in required[boundary['obligation_id']]]
    assert len(required) == 11
    assert len(condition['slots']) == 9
    assert {s['streams'] for s in members if s['method'] == huff.SHARED} == {1, 4}
    assert any(s['method'] == huff.PLUGIN and 'huffman' in s['modes'] for s in members)
    assert not any(s['expected_status'] for s in members)


def test_plan_rejects_changed_condition_criteria(data):
    obs, slots, cases = data
    obs = deepcopy(obs)
    row, = (r for r in obs if bmi2.supports_condition(r))
    row['condition_case']['criteria']['entries'].pop()
    with pytest.raises(ContractError, match='condition definition differs'):
        bind_obligations(ROOT, obs, slots, cases)


def test_absent_portable_runtime_cannot_pass_condition(data):
    obs, slots, cases = data
    required, condition = bind_obligations(ROOT, obs, slots, cases)
    row, = (r for r in obs if bmi2.supports_condition(r))
    binding = {'driver': 'huff0-specialized/1', 'slots': slots, 'required_slots': required, 'condition': condition}
    assert scope(binding, [row]) == []
    assert obligation(binding, row, {})['status'] == 'not_run'
    binding[bmi2.KEY] = {}
    assert scope(binding, [row]) == condition['slots']
    incomplete = {p: {'status': 'verified'} for p in scope(binding, [row])}
    incomplete[condition['slots'][0]]['status'] = 'failed'
    assert obligation(binding, row, incomplete)['status'] == 'failed'
