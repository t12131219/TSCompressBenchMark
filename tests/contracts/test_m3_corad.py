from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_corad import prepare, project
from tsbench.assets import ContractError, load_json
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.corad_corpus import C, INFERENCE, SOURCE, TRAINERS
from tsbench.planner.m3_corad import ROUTES, check_route

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT/'results/m3-real-r33-20261119/plan.json'
PROBE = ROOT/'results/m0-corad-real-corpus-20261119-r1/run'


@pytest.fixture(scope='module')
def sample():
    if not (PLAN.is_file() and (PROBE/'ledger.jsonl').is_file()):
        pytest.skip('requires frozen local CORAD corpus evidence')
    import json
    plan = load_json(PLAN)
    definition = load_json(ROOT/plan['definition']['plan']['path'])
    manifest = load_full_manifest(ROOT, definition['bindings']['manifest'], parse=False)
    dataset = 'etth1'
    entry = next(e for e in manifest['datasets'] if e['id'] == dataset)
    items = {i['route']: i for i in plan['work_items'] if i['dataset_id'] == dataset and (i['selection'], i['route']) in ROUTES}
    (binding, train, tests), = prepare(ROOT, entry, items)
    rows = [r for line in (PROBE/'ledger.jsonl').read_text().splitlines() if (r := json.loads(line))['dataset'] == dataset]
    return entry, items, {'input_binding': binding, 'terminals': rows, 'execution_error': ''}


def test_training_model_and_inference_charges_reconcile(sample):
    _, items, group = sample
    output = project(items, [group])
    assert set(output) == {INFERENCE, *TRAINERS}
    inference = output[INFERENCE]['evidence']
    assert inference['expected_frames'] == 2
    assert inference['complete_frame_bytes'] == sum(r['frame']['bytes'] for r in group['terminals'] if r['operation'] == 'heldout')
    for producer in TRAINERS:
        train = output[producer]['evidence']
        assert train['fit_statuses'] == {'verified': 1}
        assert train['model_bytes'] == train['fits'][0]['deployment']['model']['bytes']
        assert train['heldout_inference_decision'] == items[INFERENCE]['work_item_id']
        assert train['heldout_product_charge'] == 'inference_only'
        assert 'complete_frame_bytes' not in train
    assert all(row['status'] == 'quality_rejected' for row in output.values())


def test_group_requires_all_producers_and_disjoint_input(sample):
    entry, items, _ = sample
    with pytest.raises(ContractError, match='all three applicable'):
        prepare(ROOT, entry, {k:v for k,v in items.items() if k != C})
    bad = deepcopy(items)
    bad[SOURCE]['input']['corad_contract']['deployment']['eligible_producers'] = [C]
    with pytest.raises(ContractError, match='model dependency differs'):
        prepare(ROOT, entry, bad)


def test_reject_unbound_or_duplicate_result(sample):
    _, items, original = sample
    bad = deepcopy(original)
    bad['terminals'].append(bad['terminals'][0])
    with pytest.raises(ContractError, match='duplicate CORAD native terminal'):
        project(items, [bad])
    bad = deepcopy(original)
    bad['terminals'][1]['producer_binding_id'] = 'different-train-only-model'
    with pytest.raises(ContractError, match='native terminal binding differs|terminal binding differs'):
        project(items, [bad])


def test_declared_route_profile_rejects_heldout_retuning():
    if not PLAN.is_file():
        pytest.skip('requires frozen local CORAD definition')
    plan = load_json(PLAN)
    definition = load_json(ROOT/plan['definition']['plan']['path'])
    for r in definition['routes']:
        rule = r['binding']
        if (rule['selection'], rule['route']) in ROUTES:
            check_route(rule)
            rule['corad_layout']['threshold'] /= 2
            with pytest.raises(ContractError, match='profile differs'):
                check_route(rule)
