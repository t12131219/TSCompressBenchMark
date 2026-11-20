from copy import deepcopy
import os
from pathlib import Path

import pytest

from tsbench.application.m3_pbepla_specialized import audit_specialized, run_specialized
from tsbench.assets import ContractError, load_json
from tsbench.planner.m3_pbepla_specialized import bind

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r25-20261119/plan.json'


@pytest.fixture
def accepted():
    if not PLAN.is_file():
        pytest.skip('PBEPLA real-corpus development evidence not present')
    plan = load_json(PLAN)
    build = load_json(ROOT / plan['build']['lock']['path'])
    obligations = [o for o in plan['obligations'] if o['selection'] == 87]
    return build, obligations, plan['build']['pbepla_corpus']


def test_frozen_named_cases_map_to_required_products(accepted):
    build, obligations, corpus = accepted
    binding = bind(ROOT, build, obligations, corpus)
    assert len(binding['obligation_slots']) == len(obligations) == 9
    assert sum(len(o['planned_case_inputs']) for o in obligations) == 33
    assert len(binding['slots']) == 13
    assert set().union(*binding['obligation_slots'].values()) == set(binding['slots'])
    assert sum(s['variant'] in ('input-negatives', 'budget-over') for s in binding['slots'].values()) == 2
    bad = deepcopy(obligations)
    bad[0]['planned_case_inputs'][0]['case_name'] += '-changed'
    with pytest.raises(ContractError, match='named case'):
        bind(ROOT, build, bad, corpus)


@pytest.mark.skipif(os.environ.get('TSBENCH_M3_PBEPLA_ISOLATION') != '1', reason='requires Bubblewrap namespaces')
def test_isolated_products_expected_rejections_and_detached_replay(accepted, tmp_path):
    build, obligations, corpus = accepted
    binding = bind(ROOT, build, obligations, corpus)
    rows = [{k: o[k] for k in ('route', 'selection', 'obligation_id', 'kind', 'check')} for o in obligations]
    main_ledger = []
    report = run_specialized(ROOT, tmp_path, binding, rows, main_ledger.append)
    assert [(r['check'], r['reason']) for r in rows if r['status'] != 'verified'] == []
    assert report['statuses'] == {'verified': 11, 'expected_rejection': 2}
    assert main_ledger == [{'entry_kind': 'specialized_product', 'selection': 87, **p}
                           for p in report['fixtures'].values()]
    assert not list(tmp_path.rglob('completion.json'))
    audited = audit_specialized(tmp_path, binding, rows, report, replay=True)
    assert audited['verified_obligations'] == 9 and len(audited['replayed']) == 13
    assert {p['variant'] for p in audited['replayed']} >= {'input-negatives', 'budget-over'}

    tampered = deepcopy(report)
    replay = next(p for p in tampered['fixtures'].values() if binding['slots'][p['product_slot']]['method'] == 'pbepla-replay')
    replay['pbepla']['native_sha256'] = '0' * 64
    with pytest.raises(ContractError, match='specialist did not validate'):
        audit_specialized(tmp_path, binding, rows, tampered)
