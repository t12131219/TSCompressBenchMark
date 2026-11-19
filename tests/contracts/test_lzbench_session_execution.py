from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError, content_id
from tsbench.planner import lzbench_session as session
from tsbench.planner.linear_batch import (GORILLA_STATE, LZBENCH_SESSION, _check_method_limits,
                                         _suite_definition, protocol_methods)
from tsbench.planner.lzbench import byte_identity, plan_lzbench
from tsbench.qualification.lzbench import xz_blocks
from tsbench.qualification.lzbench_session import verify_restore

ROOT = Path(__file__).resolve().parents[2]


class NativeByteSessionTests(unittest.TestCase):
    def test_versioned_binding_and_case_denominator(self):
        products, bindings = session.execution_inputs(ROOT)
        bundle = plan_lzbench(ROOT)
        self.assertEqual(len(products),2)
        self.assertEqual(set(bindings),{c['case_id'] for c in bundle['cases'] if (c['selection'],c['route']) in session.ROUTES})
        for case in bundle['cases']:
            if (case['selection'],case['route']) not in session.ROUTES:
                continue
            bid,(sid,) = bindings[case['case_id']]
            slot,inputs = products[sid]
            self.assertEqual((bid,slot['method']),(bundle['bundle_id'],case['route']))
            self.assertEqual([byte_identity(raw) for raw in inputs.columns],
                             [{k:v[k] for k in ('bytes','sha256')} for v in slot['inputs'].values()])
        self.assertEqual(set(protocol_methods(LZBENCH_SESSION))-set(protocol_methods(GORILLA_STATE)),set(session.METHODS))
        self.assertEqual(set(_suite_definition(LZBENCH_SESSION)[1])-set(_suite_definition(GORILLA_STATE)[1]),set(session.ROUTES))

    def test_resigned_span_or_budget_changes_are_denied(self):
        products,_ = session.execution_inputs(ROOT)
        plan = {'slots':[s for s,_ in products.values()]}
        session.check_slots(plan)
        for key,value in [('level',3),('restore_spans',[65536,65536]),('call_limit',session.CALL_LIMIT+1),('budget_frame',None)]:
            edited = deepcopy(plan)
            xz = next(s for s in edited['slots'] if s['method']=='xz-session')
            xz[key] = value
            xz['product_slot'] = content_id({k:v for k,v in xz.items() if k!='product_slot'})
            with self.subTest(key=key), self.assertRaisesRegex(ContractError,'fixture, spans or retained budget differs'):
                session.check_slots(edited)

    def test_restore_span_requires_finish_and_consumption(self):
        slot = {'call_limit':2,'inputs':{'first':{'bytes':5}},'restore_spans':[17,127]}
        calls = [[3,3,4,1,0],[0,0,1,1,1]]
        self.assertEqual(verify_restore(slot,'first',b'abc',calls),{
            'calls':2,'first_output_call':0,'finish_calls':2,'zero_input_finish_output':True,'input_bytes':3,'output_bytes':5})
        for invalid in ([[3,2,4,1,0],[0,0,1,1,1]],[[3,3,4,1,0],[0,0,1,1,0]]):
            with self.assertRaisesRegex(ContractError,'span or finish accounting differs'):
                verify_restore(slot,'first',b'abc',invalid)
        with self.assertRaisesRegex(ContractError,'exceeds call limit'):
            verify_restore(slot,'first',b'abc',calls+calls)

    def test_budget_fixture_is_xz_lzma2_not_a_native_allocation(self):
        block, = xz_blocks(session.BUDGET_FRAME)
        self.assertEqual((block['raw'],block['filters']),(1,[(0x21,b'\x21')]))
        xz_policy = {'limits':{'address_space_bytes':128<<20,'file_bytes':1<<20,'wall_seconds':5},
                     'gorilla_file_bytes':1<<14,'method_address_space_bytes':{'xz-baseline':256<<20,'xz-session':256<<20}}
        _check_method_limits(xz_policy,LZBENCH_SESSION)
        del xz_policy['method_address_space_bytes']['xz-session']
        with self.assertRaisesRegex(ContractError,'distinct bounded XZ address space'):
            _check_method_limits(xz_policy,LZBENCH_SESSION)
