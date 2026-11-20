from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_corad_specialized import scope, verdict
from tsbench.assets import ContractError, load_json
from tsbench.planner.corad_corpus import C, INFERENCE, SOURCE
from tsbench.planner.corad_execution import QUALITY_CHECK
from tsbench.planner.m3_corad_specialized import bind_obligations, fixture_inputs, route

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT/'results/m3-real-r34-20261119/plan.json'


@pytest.fixture(scope='module')
def data():
    if not PLAN.is_file():
        pytest.skip('requires frozen local CORAD obligations')
    obs = [o for o in load_json(PLAN)['obligations'] if o['selection'] == 80]
    fixtures, cases = fixture_inputs(ROOT)
    slots = {p:s for p,(s,_) in fixtures.items()}
    mapping = bind_obligations(obs, slots, cases)
    return obs, cases, {'driver': 'corad-specialized/1', 'slots': slots, 'obligation_slots': mapping}


def test_frozen_case_partition(data):
    obs, _, binding = data
    assert len(obs) == 17
    assert set(scope(binding, obs)) == binding['slots'].keys()
    assert {route(s) for s in binding['slots'].values()} == {INFERENCE, C, SOURCE}
    assert sum(len(r['case_inputs']) for r in binding['obligation_slots'].values()) == 20


def test_wrong_case_bundle_or_trimmed_route_is_rejected(data):
    obs, cases, binding = data
    changed = deepcopy(obs)
    changed[0]['planned_case_inputs'][0]['bundle_id'] = '0'*64
    with pytest.raises(ContractError, match='binding differs'):
        bind_obligations(changed, binding['slots'], cases)
    with pytest.raises(ContractError, match='denominator differs'):
        bind_obligations(obs[:-1], binding['slots'], cases)


def test_quality_rejection_not_masked_by_functional_verification(data):
    obs, _, binding = data
    q, = [r for r in obs if r['check'] == QUALITY_CHECK]
    p = binding['obligation_slots'][q['obligation_id']]['fixture_slot']
    result = {p:{'status':'verified', 'corad':{'quality_comparable':False,
                           'quality_gate':{'heldout':{'c-lars':{'decision':'rejected'}}}}}}
    assert verdict(binding, q, result)['status'] == 'quality_rejected'
    structural = next(r for r in obs if r['route'] == INFERENCE and r['check'] == 'isolated_crd1_restore')
    assert verdict(binding, structural, result)['status'] == 'verified'
    result[p] = {'status':'validation_failed', 'reason':'native comparison failed'}
    assert verdict(binding, q, result)['status'] == 'failed'
    assert verdict(binding, structural, result)['status'] == 'failed'
