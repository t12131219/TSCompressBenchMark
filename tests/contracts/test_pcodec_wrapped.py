from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError, canonical_bytes
from tsbench.planner.pcodec import PAGE_CHECKS
from tsbench.planner.pcodec_pages import METHODS, PROTOCOL, ROUTES, check_wrapped_slots, pcodec_page_inputs
from tsbench.qualification.pcodec_pages import check_slot, expect_decode, expect_diagnosis, expect_missing, geometry

ROOT = Path(__file__).resolve().parents[2]


class PcodecWrappedContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products, cls.binds = pcodec_page_inputs(ROOT)
        cls.by_method = {s['method']:s for s,_ in cls.products.values()}

    def test_slots_lock_original_domain_parts_and_denominator(self):
        self.assertEqual(self.by_method.keys(),METHODS.keys())
        self.assertEqual(len(self.binds),12)
        self.assertEqual({sid for _,slots in self.binds.values() for sid in slots},set(self.products))
        for s, data in self.products.values():
            self.assertEqual(s['protocol'],PROTOCOL)
            self.assertEqual(len(data.columns[0]),6184)
            check_slot(s)
            changed = {**s,'counts':[260,513]}
            with self.assertRaises(ContractError):
                check_slot(changed)

    def test_detached_requires_actual_completion_and_frozen_span_geometry(self):
        slot = self.by_method['pcodec-source-pages']
        sizes = geometry(slot,{'meta':{'bytes':79},'page-0':{'bytes':175},'page-1':{'bytes':103}})
        state = {'backend':'source-rust-repaired','mode':0,'delta':0}
        obs = {'index':0,'rows':513,'meta_bytes':79,'page_bytes':175,'finished':True,
               'spans':[256,256,1],'state':state}
        answer = expect_decode(slot,sizes,state,0,obs)
        self.assertEqual(answer['native_input_bytes'],254)
        self.assertEqual(answer['restored'],slot['page_originals'][0])
        for altered in ({**obs,'finished':False},{**obs,'spans':[256,257]},{**obs,'index':1}):
            with self.assertRaises(ContractError):
                expect_decode(slot,sizes,state,0,altered)
        self.assertRaises(ContractError,expect_missing,slot,sizes,
                          {'metadata_bytes':0,'available_page_bytes':175,'status':1,'decoder_null':True})

    def test_quota_scope_and_ownership_not_interchangeable(self):
        src,nat = (self.by_method[f'pcodec-{route}'] for route in ('source-pages','native-pages'))
        obs = {'first_page_small_quota':6,'early_next_page':1,'read_capacity_255':1,'after_first_with_second_quota':0,
               'trailing_at_drain':4,'read_after_error':1,'truncated_page':{'stage':'drain','status':3,'prefix_rows':256},
               'overwrote_caller_buffer':False}
        self.assertIsNone(expect_diagnosis(src,obs)['ownership_restored'])
        with self.assertRaises(ContractError):
            expect_diagnosis(nat,obs)
        native = expect_diagnosis(nat,{**obs,'after_first_with_second_quota':6,'overwrote_caller_buffer':True})
        self.assertEqual(native['ownership_restored'],nat['page_originals'][0])

    def test_page_obligation_cannot_be_dropped_or_assigned_to_different_route(self):
        plan = {'slots':list(self.by_method.values()),'methods':{},'route_contracts':{},'obligation_bindings':{}}
        for (selection,route),method in ROUTES.items():
            plan['route_contracts'][route] = {'selection':selection,'route':route}
            for check in PAGE_CHECKS[route]:
                plan['obligation_bindings'][f'{selection}/{route}/{check}'] = {
                    'route_contract_id':route,'product_slots':[self.by_method[method]['product_slot']]}
        check_wrapped_slots(plan)
        removed = deepcopy(plan)
        key = '11/native-pages/cumulative_decoder_quota'
        del removed['obligation_bindings'][key]
        with self.assertRaises(ContractError):
            check_wrapped_slots(removed)
        swapped = deepcopy(plan)
        swapped['obligation_bindings'][key]['product_slots'] = [self.by_method['pcodec-source-pages']['product_slot']]
        self.assertNotEqual(canonical_bytes(plan),canonical_bytes(swapped))
        with self.assertRaises(ContractError):
            check_wrapped_slots(swapped)
