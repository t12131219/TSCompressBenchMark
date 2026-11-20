from copy import deepcopy
from pathlib import Path

import pytest

from tsbench.application.m3_alp_specialized import scope, verdict
from tsbench.assets import ContractError, load_json
from tsbench.planner.alp import AVX512
from tsbench.planner.alp_decode import is_decode
from tsbench.planner.m3_alp_specialized import LIMITS, bind, inputs
from tsbench.planner.linear_batch import _fenv_path
from tsbench.supervisor.isolated_worker import validate_limits

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r35-20261120/plan.json'


def test_fixture_denominator_and_specialized_branch_separation():
    validate_limits(LIMITS)
    products, cases = inputs(ROOT)
    assert len(cases) == 15
    assert len(products) == 24
    assert sum(is_decode(s) for s, _ in products.values()) == 9
    assert sum(len(s.get('reject_decodes', [])) for s, _ in products.values()) == 4


@pytest.fixture(scope='module')
def frozen():
    if not PLAN.is_file():
        pytest.skip('requires a local M3 definition')
    plan = load_json(PLAN)
    build = load_json(ROOT / plan['build']['lock']['path'])
    if not (ROOT / _fenv_path(build)).is_file():
        pytest.skip('requires ALP C11 rounding control')
    rows = [r for r in plan['obligations'] if r['selection'] == 9]
    binding = bind(ROOT, build, rows)
    assert binding is not None
    return rows, binding, build


def test_frozen_binding_covers_both_routes_and_rejects_wrong_bundle(frozen):
    rows, binding, build = frozen
    assert set(scope(binding, rows)) == binding['slots'].keys()
    assert len(rows) == 14
    assert sum(len(r.get('case_inputs', [])) for r in binding['obligation_slots'].values()) == 15
    changed = deepcopy(rows)
    changed[0]['planned_case_inputs'][0]['bundle_key'] = 'alp_cases'
    with pytest.raises(ContractError, match='case binding differs'):
        bind(ROOT, build, changed)
    changed = deepcopy(rows)
    changed[-1]['condition_case']['criteria']['requests'] = [AVX512]
    with pytest.raises(ContractError, match='same-run condition differs'):
        bind(ROOT, build, changed)


def test_compiled_backend_cannot_pass_without_runtime_work(frozen):
    rows, binding, _ = frozen
    row = next(r for r in rows if r['check'] == 'avx512bw_decimal_with_effective_dispatch')
    p, = scope(binding, [row])
    requests = {AVX512: {'capability': {'built_for_width': True, 'available': False, 'reason': 'runtime_unavailable'}},
                'falp-auto': {'state': 'restored_bit_exact', 'dispatch': 'falp-avx2'}}
    product = {'status': 'verified', 'decode_backends': {'requests': requests}}
    assert verdict(binding, row, {p: product})['status'] == 'pending_supported_runtime'
    product['status'] = 'sandbox_failed'
    assert verdict(binding, row, {p: product})['status'] == 'failed'
