from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from audit_m3_primary_closeout import _decision, _denominator, audit
from tsbench.assets import ContractError


def _plan():
    domains = ['input_domain_matches'] * 724 + ['outside_declared_domain'] * 74 + ['condition_not_triggered'] * 30
    work = [{'work_item_id': str(i), 'dataset_id': str(i % 23), 'selection': (i // 23) % 12,
             'route': str(i // 23), 'applicability': s, 'operation': 'decode', 'operation_config_id': 'cfg'}
            for i, s in enumerate(domains)]
    population = {i['work_item_id']: {'status': 'scheduled', 'adapter': 'test', 'case_id': i['work_item_id']}
                  if i['applicability'] == 'input_domain_matches' else {'status': i['applicability']} for i in work}
    return {'work_items': work, 'measurement': {'population': population},
            'obligations': [{'kind': k} for k in ['required'] * 180 + ['conditional'] * 6]}


def test_closeout_rejects_missing_adapter_obligation_or_seal(tmp_path):
    plan = _plan()
    assert _denominator(plan) == ({'input_domain_matches': 724, 'outside_declared_domain': 74, 'condition_not_triggered': 30},
                                  {'required': 180, 'conditional': 6})
    with pytest.raises(ContractError, match='plan identity'):
        audit(tmp_path, {**plan, 'plan_content_id': 'wrong'}, tmp_path)
    changed = deepcopy(plan)
    changed['obligations'].pop()
    with pytest.raises(ContractError, match='denominator'):
        _denominator(changed)
    changed = deepcopy(plan)
    changed['measurement']['population']['50'] = {'status': 'measurement_adapter_not_integrated'}
    with pytest.raises(ContractError, match='applicable decision'):
        _denominator(changed)


@pytest.mark.parametrize('functional,state,functional_reason,reason,trials,summary', [
    ('verified', 'measured_and_verified', None, None, {'measured:measured_as_declared': 6}, {'seconds': 1}),
    ('verified', 'measured_and_verified', None, None,
     {'warmup:measured_as_declared': 6, 'measure:measured_as_declared': 18}, {'seconds': 1}),
    ('quality_rejected', 'measured_quality_rejected', 'error above bound', None,
     {'warmup:measured_as_declared': 1, 'measured:measured_as_declared': 3}, {'seconds': 1}),
    ('failed', 'functional_dependency_not_verified', 'codec return code 1', 'failed', {}, None),
    ('verified', 'measurement_failed', None, 'failed to sync',
     {'warmup:measured_as_declared': 1, 'measured:measurement_failed': 1, 'measured:not_run_after_measurement_failure': 2}, None),
])
def test_keep_functional_and_measurement_reasons_independent(functional, state, functional_reason, reason, trials, summary):
    item = _plan()['work_items'][0]
    row = {**item, 'status': functional, 'reason': functional_reason}
    measurement = {'status': state, 'reason': reason}
    checked = {**item, 'functional_status': functional, 'measurement_status': state, 'trials': trials, 'summary': summary}
    d = _decision(item, row, measurement, checked)
    assert d['functional_reason'] == functional_reason and d['measurement_reason'] == reason
    assert d['measurement_summary'] == summary and d['trials'] == trials
    with pytest.raises(ContractError, match='disagree'):
        _decision(item, row, measurement, {**checked, 'functional_status': 'not_run'})


def test_quality_rejection_cannot_promote_to_verified_measurement():
    item = _plan()['work_items'][0]
    row = {**item, 'status':'quality_rejected', 'reason':'bound exceeded'}
    with pytest.raises(ContractError, match='inconsistent sample scope'):
        _decision(item, row, {'status':'measured_and_verified'},
                  {**item, 'functional_status':'quality_rejected', 'measurement_status':'measured_and_verified',
                   'trials':{'measured:measured_as_declared':3}, 'summary':{'seconds':1}})


@pytest.mark.parametrize('samples', [
    {'warmup:measured_as_declared':3},
    {'measure:measured_as_declared':3, 'calibration:measured_as_declared':1},
    {'measure:measured_as_declared':3, 'measured:measured_as_declared':-1},
])
def test_success_requires_a_measured_phase_with_positive_declared_counts(samples):
    item = _plan()['work_items'][0]
    state = 'measured_and_verified'
    with pytest.raises(ContractError,match='inconsistent sample scope'):
        _decision(item,{**item,'status':'verified','reason':''},{'status':state},
                  {**item,'functional_status':'verified','measurement_status':state,'trials':samples,'summary':{}})
