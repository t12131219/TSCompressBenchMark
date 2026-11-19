from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tsbench.assets import ContractError
from tsbench.contracts import load_contract
from tsbench.qualification.native_evidence import _obligations, _products, audit_native_qualification

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    driver = {'configuration':{'mode':'test'},'operations':[{'program':'tool/test'}], 'primary_restore_programs':['tool/test']}
    return ({'slots':[{'product_slot':k,'method':'test'} for k in ('ok','neg','ignored','err')],
             'execution_binding':{'drivers':{k:driver for k in ('ok','neg','ignored','err')}}},
            [{'product_slot':k,'status':state,'reason':'' if state=='verified' else 'diagnostic'}
             for k,state in (('ok','verified'),('neg','expected_rejection'),('ignored','expected_rejection'),('err','crash'))],
            {'products':[{'product_slot':'ok'}], 'pcodec_input_rejections':[{'product_slot':'neg'}], 'restored_products':1})


class NativeQualificationTests(unittest.TestCase):
    def test_detached_and_ledger_only_outcomes_remain_distinct(self):
        plan, ledger, replay = fixture()
        result = _products(plan,ledger,replay)
        self.assertEqual({k:v['audit_state'] for k,v in result.items()},
                         {'ok':'restored','neg':'rejection_replayed','ignored':'rejection_validated_in_ledger_only',
                          'err':'not_applicable_nonpassing_terminal'})
        self.assertIsNone(result['ignored']['detached_observation'])
        self.assertEqual(result['neg']['detached_observation']['observation_kind'],'pcodec_input_rejections')

    def test_duplicate_omission_or_false_negative_proof_are_rejected(self):
        plan, ledger, replay = fixture()
        for changes, reason in (
                ({'selfstar_ordered_products':[{'product_slot':'ok'}]},'duplicate slot'),
                ({'products':[], 'restored_products':0},'did not cover every verified product'),
                ({'pcodec_input_rejections':[{'product_slot':'err'}]},'no matching original terminal')):
            with self.subTest(changes=changes), self.assertRaisesRegex(ContractError,reason):
                _products(plan,ledger,{**replay,**changes})

    def test_quality_rejection_and_conditional_pending_gate_are_preserved(self):
        plan, ledger, replay = fixture()
        route = {'route_contract_id':'route-id','selection':1,'route':'test','source_identity':{},'out_of_scope':[],
                 'domain':{},'quality':{},'access':{},'retention':{}}
        base = {'route_contract_id':'route-id','selection':1,'route':'test'}
        plan['admission_definition'] = {'routes':[route],'coverage':{'total_obligations':2}, 'obligations':[
            {**base,'kind':'required','check':'quality','obligation_id':'required-id'},
            {**base,'kind':'conditional','check':'isa','obligation_id':'conditional-id','condition_case':{'predicate':'hardware'}}]}
        plan['execution_binding'].update(bound_obligations={'required-id':{},'conditional-id':{}},unbound_obligations={})
        report = {'obligation_evidence':{
            '1/test/quality':{'obligation_id':'required-id','route_contract_id':'route-id','product_slots':['ok'],
                              'state':'quality_rejected','reason':'bounds_exceeded'},
            '1/test/isa':{'obligation_id':'conditional-id','route_contract_id':'route-id','product_slots':['ok'],
                          'state':'pending_supported_runtime'}}}
        products = _products(plan,ledger,replay)
        routes, obligations = _obligations(plan,report,products)
        self.assertEqual(routes['route-id']['required_counts'],{'quality_rejected':1})
        self.assertEqual(routes['route-id']['qualification'],'not_qualified')
        self.assertEqual(obligations['required-id']['reason'],'bounds_exceeded')
        self.assertEqual(obligations['conditional-id']['predicate'],'hardware')
        fake = deepcopy(report)
        fake['obligation_evidence']['1/test/quality']['state']='pending_supported_runtime'
        with self.assertRaisesRegex(ContractError,'unconditional obligation'):
            _obligations(plan,fake,products)

    def test_schema_cannot_grant_formal_status_and_plan_alone_is_invalid(self):
        schema = load_contract(ROOT,'qualification')
        for k in ('qualification_granted','timing_admitted','stage_accepted'):
            self.assertTrue(any(e.validator=='const' and list(e.path)==[k]
                                for e in schema.validator.iter_errors({k:True})))
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage/'plan.json').write_text('{"schema":"bmk.native-admission-plan/1"}')
            with self.assertRaisesRegex(ContractError,'requires a frozen unified candidate'):
                audit_native_qualification(ROOT,stage)
