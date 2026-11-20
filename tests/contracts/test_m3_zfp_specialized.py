from collections import Counter
from copy import deepcopy
import os
from pathlib import Path

import pytest

from tsbench.application.m3_zfp_specialized import audit_specialized, run_specialized
from tsbench.assets import ContractError, load_json
from tsbench.planner.m3_zfp_specialized import bind
from tsbench.planner.zfp_execution import OMP, is_zfp

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r23-20261119/plan.json'


@pytest.fixture
def accepted():
    if not PLAN.is_file():
        pytest.skip('ZFP real-corpus development evidence not present')
    plan = load_json(PLAN)
    build = load_json(ROOT / plan['build']['lock']['path'])
    corpus = plan['build']['zfp_corpus']
    obligations = [r for r in plan['obligations'] if r['selection'] == 31]
    return build, corpus, obligations


def test_bind_all_zfp_cases_and_do_not_substitute_configuration_for_worker_work(accepted):
    b, c, obs = accepted
    binding = bind(ROOT, b, obs, c)
    assert len(binding['obligation_slots']) == len(binding['slots']) == 20
    assert Counter(is_zfp(s) for s in binding['slots'].values()) == {False: 14, True: 6}
    positives = [s for s in binding['slots'].values() if not is_zfp(s) and not s['expected_status']]
    assert {s['original']['columns'][0]['dtype'] for s in positives} == {5, 7, 9, 10}
    condition, = (o for o in obs if o['kind'] == 'conditional')
    slot, = binding['obligation_slots'][condition['obligation_id']]
    assert binding['slots'][slot]['method'] == OMP
    bad = deepcopy(obs)
    next(o for o in bad if o['kind'] == 'conditional')['condition_case']['criteria']['encoding_tids'] = [1, 1, 1]
    with pytest.raises(ContractError, match='worker policy'):
        bind(ROOT, b, bad, c)


@pytest.mark.skipif(os.environ.get('TSBENCH_M3_ZFP_ISOLATION') != '1', reason='requires Bubblewrap namespaces')
def test_execute_and_replay_specialists_without_a_second_run_receipt(accepted, tmp_path):
    b, c, obs = accepted
    binding = bind(ROOT, b, obs, c)
    rows = [{k: ob[k] for k in ('route','selection','obligation_id','kind','check')} for ob in obs]
    main_ledger = []
    report = run_specialized(ROOT, tmp_path, binding, rows, main_ledger.append)
    errors = [(r['check'], r['reason']) for r in rows if r['status'] != 'verified']
    assert errors == []
    assert len(main_ledger) == 20 and all(r['entry_kind'] == 'specialized_product' for r in main_ledger)
    assert report['statuses'] == {'verified': 17, 'expected_rejection': 3}
    conditional, = [r for r in rows if r['kind'] == 'conditional']
    assert conditional['evidence']['native_work'] == {'encode_participants': {'serial': 1,'1': 1,'2': 2},
                                                     'decode_on_caller': True, 'same_payload': True}
    assert not list(tmp_path.rglob('completion.json'))
    audited = audit_specialized(ROOT, tmp_path, binding, rows, report, replay=True)
    assert audited['verified_obligations'] == 20 and len(audited['replayed']) == 20
