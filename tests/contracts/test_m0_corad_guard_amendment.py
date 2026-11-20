from copy import deepcopy
from pathlib import Path
from struct import pack

import pytest

from tsbench.application.m3_corad_specialized_v2 import _io, verdict
from tsbench.assets import ContractError
from tsbench.planner.corad_corpus import INFERENCE
from tsbench.planner.corad_deployment import NATIVE
from tsbench.planner.corad_execution import is_corad, split_deployment
from tsbench.planner.m0_corad_guard_amendment import CHECKS, controls
from tsbench.planner.m3_corad_specialized import fixture_inputs
from tsbench.qualification.corad_inference import HEADER
from tsbench.qualification.corad_wire import interpret

ROOT = Path(__file__).resolve().parents[2]


def _inputs():
    (slot, _), = (v for v in fixture_inputs(ROOT)[0].values() if is_corad(v[0]))
    policy = {'amendment_id': 'guard', 'controls': controls(ROOT, slot)}
    return slot, policy


def test_bad_reference_constructed_only_from_positive_fixture():
    slot, policy = _inputs()
    safe, unsafe = policy['controls']
    assert (safe['expected_references'], unsafe['expected_references']) == (1, 0)
    schema, model = split_deployment(safe['deployment'])
    sparse = pack('<HHdHd', 2, 0, 1., 2, 2.)
    copy = pack('<HH', 65535, 0)
    other = pack('<HHdHd', 2, 1, 1., 3, 2.)
    tail = pack('<9d', 4,5,6,7,8,9,10,11,12)
    body = model[NATIVE.size:]+sparse+copy+other+tail
    payload = NATIVE.pack(b'CRD1', 7, 3, 4, 4, 2, 0.9, NATIVE.size+len(body))+body
    frame = HEADER.pack(b'BMKCRD\x01\0', len(schema), 0, len(payload))+schema+payload
    mounts, expected = _io(slot, policy, {'safe-reference.bmk': frame}, 'bad-reference')
    assert not expected and mounts['frame'] != frame and len(mounts['frame']) == len(frame)
    with pytest.raises(ContractError, match='invalid CRD1 reference'):
        interpret(mounts['frame'][HEADER.size+len(schema):])


def test_mechanism_success_cannot_rescue_failed_heldout_quality():
    check = 'bound_predeclared_before_formal_run'
    row = {'selection': 80, 'route': INFERENCE, 'check': check, 'obligation_id': 'quality'}
    b = {'driver': 'corad-specialized/1', 'obligation_slots': {'quality': {'fixture_slot': 'inference', 'case_inputs': []}}}
    a = {'contract': {'amendment_id': 'guard', 'obligations': {'quality': {'evidence': CHECKS[check]}}}}
    quality = {'heldout': {'c-lars': {'decision': 'quality_rejected'}}}
    products = {'inference': {'status': 'verified', 'corad': {'quality_gate': quality, 'quality_comparable': False,
                                                           'reference_controls': {'safe': 'verified', 'unsafe': 'verified'}}}}
    result = verdict(b, a, row, products)
    assert result['status'] == 'quality_rejected' and result['evidence']['quality_gate'] == quality
    assert result['evidence']['amendment_id'] == 'guard'
    failed_product = deepcopy(products)
    failed_product['inference'].update(status='validation_failed', reason='missing native control')
    assert verdict(b,a,row,failed_product)['status'] == 'failed'
