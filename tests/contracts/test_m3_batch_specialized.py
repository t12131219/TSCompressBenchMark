from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_batch_specialized import scope, verdict
from tsbench.assets import ContractError, load_json
from tsbench.planner.m3_batch_specialized import FAMILIES, LZBENCH, PCODEC, _declared, _obligations, inputs

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / 'results/m3-real-r37-20261120/plan.json'


@pytest.fixture(params=(PCODEC, LZBENCH))
def family(request):
    key = request.param
    _, routes, n_checks, n_products, _ = FAMILIES[key]
    if not REFERENCE.is_file():
        pytest.skip('requires frozen local M3 obligations')
    rows = [r for r in load_json(REFERENCE)['obligations'] if (r['selection'], r['route']) in routes]
    products, refs = inputs(ROOT, key)
    declared = _declared(ROOT, key)
    mapping = _obligations(rows, key, products, refs, declared)
    assert len(mapping) == n_checks and len(products) == n_products
    return key, rows, products, refs, declared, mapping


def test_frozen_scope_and_required_expected_rejection(family):
    name, rows, products, _, _, mapping = family
    driver, _, _, _, _ = FAMILIES[name]
    slots = {sid: slot for sid, (slot, _) in products.items()}
    binding = {'driver': driver, 'obligation_slots': mapping, 'slots': slots}
    assert set(scope(binding, rows)) == products.keys()
    assert Counter(s['method'] for s in slots.values()) == (
        {'pcodec-source-auto': 13, 'pcodec-c-native-auto': 13, 'pcodec-source-pages': 1, 'pcodec-native-pages': 1}
        if name == PCODEC else {'zstd': 9, 'xz-baseline': 5})
    negatives = {sid for sid, s in slots.items() if s.get('expected_status')}
    assert len(negatives) == (1 if name == PCODEC else 2)
    for ob in rows:
        actual = {p: {'status': 'expected_rejection' if p in negatives else 'verified'} for p in scope(binding, [ob])}
        assert verdict(binding, ob, actual)['status'] == 'verified'
        for p in actual.keys() & negatives:
            before = actual[p]['status']
            actual[p]['status'] = 'verified'
            assert verdict(binding, ob, actual)['status'] == 'failed'
            actual[p]['status'] = before


def test_wrong_frozen_case_identity_rejected(family):
    name, rows, products, refs, declared, _ = family
    changed = deepcopy(rows)
    changed[0]['planned_case_inputs'][0]['bundle_id'] = '0' * 64
    with pytest.raises(ContractError, match='frozen case identity differs'):
        _obligations(changed, name, products, refs, declared)
