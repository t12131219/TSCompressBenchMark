from copy import deepcopy
import json
from pathlib import Path

import pytest

from tsbench.application.m3_ledger_census import _project
from tsbench.assets import ContractError, load_json
from tsbench.planner.m3_binding_coverage import binding_coverage

ROOT = Path(__file__).resolve().parents[2]
R37 = ROOT / 'results/m3-real-r37-20261120'
R38 = ROOT / 'results/m3-real-r38-20261120'


def test_binding_census_closes_exactly_186_and_rejects_duplicate():
    if not (R38 / 'plan.json').is_file():
        pytest.skip('requires the local integrated M3 plan')
    plan = load_json(R38 / 'plan.json')
    counts = binding_coverage(plan)
    assert counts['bound'] == {'conditional': 6, 'required': 180}
    assert counts['unbound'] == {'conditional': 0, 'required': 0}
    pcodec, alp = (plan['specialized'][k]['obligation_slots'] for k in ('pcodec_auto_pages', 'alp'))
    duplicate = next(iter(pcodec))
    alp[duplicate] = None
    with pytest.raises(ContractError, match='duplicate or unknown specialist'):
        binding_coverage(plan)


@pytest.fixture(scope='module')
def alp():
    if not (R37 / 'plan.json').is_file():
        pytest.skip('requires a local sealed targeted run')
    run, = (R37 / 'runs').iterdir()
    return (load_json(R37 / 'plan.json'), load_json(run / 'report.json'),
            [json.loads(line) for line in (run / 'ledger.jsonl').read_text().splitlines()])


def test_census_reports_pending_supported_runtime_separately(alp):
    plan, report, entries = alp
    result = _project(plan, report, entries)
    assert result['corpus_statuses'] == {'verified': 46}
    assert result['obligation_statuses'] == {'required': {'verified': 12}, 'conditional': {'verified': 1, 'pending_supported_runtime': 1}}
    assert result['specialist_product_statuses'] == {'verified': 24}
    assert not result['all_frozen_decisions_and_obligations_accounted'] and not result['no_unbound_obligations']
    assert len({d['operation_config_id'] for d in result['decisions']}) == 2
    assert {(d['dataset_id'], d['route']) for d in result['decisions'] if d['work_item_id'] in result['batch_unit_mismatches']} == {
        (d, r) for d in ('ettm1', 'ettm2') for r in ('auto-batch', 'decode-backends')}
    assert all(d['batch_unit_observation']['shared_artifact_reuse_proved'] is False
               for d in result['decisions'] if d['route'] == 'decode-backends')


def test_census_fails_product_omission_or_dataset_identity_substitution(alp):
    plan, report, entries = alp
    cut = len(report['rows'])
    with pytest.raises(ContractError, match='omits specialist'):
        _project(plan, report, [*entries[:cut], *entries[cut + 1:]])
    changed = deepcopy(report)
    changed['rows'][0]['dataset_id'] = 'different'
    with pytest.raises(ContractError, match='identity differs'):
        _project(plan, changed, [*changed['rows'], *entries[cut:]])
