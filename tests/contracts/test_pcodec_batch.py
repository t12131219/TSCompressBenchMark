from collections import Counter
from pathlib import Path
import unittest

from tsbench.assets import ContractError
from tsbench.planner.linear_batch import EXTENDED_PCO, _suite_definition
from tsbench.planner.pcodec import C_NATIVE, SOURCE
from tsbench.planner.pcodec_batch import pcodec_inputs
from tsbench.qualification.linear_batch import inspect_linear, mutations, wrap
from tsbench.qualification.pcodec_batch import direct_observation

ROOT = Path(__file__).resolve().parents[2]


class PcodecBatchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products, cls.binds = pcodec_inputs(ROOT)

    def test_two_routes_share_selection_not_method_and_rejection_is_separate(self):
        _, routes, _ = _suite_definition(EXTENDED_PCO)
        self.assertEqual({k:v for k,v in routes.items() if k[0] == 11},
                         {(11,'source-auto'):SOURCE,(11,'c-native-auto'):C_NATIVE})
        self.assertEqual(Counter((r['method'],r['expected_status']) for r,_ in self.products.values()),
                         {(SOURCE,0):13,(C_NATIVE,0):12,(C_NATIVE,1):1})
        self.assertEqual(len(self.binds),11)
        self.assertEqual({sid for _,ids in self.binds.values() for sid in ids},set(self.products))
        refusal, = [r for r,_ in self.products.values() if r['expected_status']]
        source, = [r for r,_ in self.products.values() if r['method']==SOURCE and r['name']==refusal['name']]
        self.assertEqual(refusal['original'],source['original'])
        self.assertNotEqual(refusal['product_slot'],source['product_slot'])
        self.assertEqual(direct_observation(refusal,None)['status'],5)

    def test_empty_prefix_and_outer_negative_shape(self):
        slot,original = next((r,s) for r,s in self.products.values() if r['method']==SOURCE and r['name']=='empty')
        payload = b'pco!\x03\x00\x00\x04\x01\x00'
        frame = wrap(slot,original.schema,payload)
        info = inspect_linear(frame,slot)['wire']
        self.assertEqual((info['count_hint'],info['first_chunk_count']),(0,None))
        negatives = mutations(frame,slot)
        self.assertNotIn('count_too_small',negatives)
        self.assertEqual(negatives['other_format'][8:],frame[8:])
        self.assertNotEqual(negatives['other_format'][:8],frame[:8])
        for bad in negatives.values():
            with self.assertRaises(ContractError):
                inspect_linear(bad,slot)

    def test_count_or_type_disagreement_in_nonempty_metadata(self):
        slot,original = next((r,s) for r,s in self.products.values() if r['method']==SOURCE and r['name']=='f16-extreme-bits')
        n = slot['original']['columns'][0]['count']
        # Bounded prefix fixture only: native decoder, not this parser, validates entropy body.
        hint = ((n << 6) | (n.bit_length()-1)).to_bytes(2,'little')
        prefix = b'pco!\x03\x00' + hint + b'\x04\x01'
        payload = prefix + bytes([9]) + (n-1).to_bytes(3,'little') + b'\x01\x00'
        info = inspect_linear(wrap(slot,original.schema,payload),slot)['wire']
        self.assertEqual((info['native_type'],info['first_chunk_count']),(9,n))
        for changed in (prefix + b'\x06' + payload[len(prefix)+1:],
                        prefix + bytes([9]) + n.to_bytes(3,'little') + b'\x01\x00'):
            with self.assertRaises(ContractError):
                inspect_linear(wrap(slot,original.schema,changed),slot)
        self.assertEqual(slot['reject_statuses']['count_too_small'],7)
