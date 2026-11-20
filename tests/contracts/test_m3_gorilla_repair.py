"""Opt-in C11 state repair cannot rewrite the M0 denominator or original TV closure."""
from pathlib import Path

import pytest

from tsbench.assets import ContractError, content_id, load_json
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
REPAIR = ROOT / 'results/m3-real-r19-20261119/plan.json'


def test_r19_opt_in_and_unmodified_r17():
    original = load_json(ROOT / 'results/m3-real-r17-20261119/plan.json')
    repaired = load_json(REPAIR)
    for plan in (original, repaired):
        check_m3_real_corpus_plan(ROOT, plan)
        load_contract(ROOT, 'm3-real-corpus-plan').validate(plan, 'plan')
    for key in ('definition', 'coverage', 'routes', 'work_items', 'obligations'):
        assert original[key] == repaired[key]
    assert 'gorilla_state_repair' not in original['build']
    assert original['build']['gorilla_corpus'] == repaired['build']['gorilla_corpus']
    assert original['specialized']['pcodec_intmult'] == repaired['specialized']['pcodec_intmult']
    control = repaired['specialized']['gorilla']
    tv, state = control['obligation_slots']['tv-batch'], control['obligation_slots']['state']
    assert (len(tv), len(state), len(set().union(*state.values()))) == (4, 8, 4)
    dependency = 'lib/libgorilla_c.so'
    assert control['tv_batch']['decoder']['files'][dependency]['sha256'] == original['build']['gorilla_corpus']['dependency']['sha256']
    assert control['state']['decoder']['files'][dependency]['sha256'] == repaired['build']['gorilla_state_repair']['repair_build']['dependency']['sha256']


@pytest.mark.parametrize('tamper', ('state_uses_original', 'change_batch_controller', 'empty_case', 'widen_scope'))
def test_rehash_cannot_change_repair_routes_or_evidence_binding(tamper):
    plan = load_json(REPAIR)
    control = plan['specialized']['gorilla']
    repair = plan['build']['gorilla_state_repair']
    if tamper == 'state_uses_original':
        control['state']['decoder'] = control['tv_batch']['decoder']
    elif tamper == 'change_batch_controller':
        plan['build']['gorilla_corpus']['executable'] = repair['repair_build']['programs']['tsbench_gorilla_corpus_control']
    elif tamper == 'empty_case':
        state = control['obligation_slots']['state']
        state[next(iter(state))] = []
    else:
        repair['routes'].append('tv-batch')
    plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
    with pytest.raises(ContractError, match='Gorilla'):
        check_m3_real_corpus_plan(ROOT, plan)
