from collections import Counter
from pathlib import Path
import unittest

from tsbench.assets import ContractError
from tsbench.planner.typed_batch import TITCHY, ZFP, typed_inputs
from tsbench.qualification.linear_batch import inspect_linear, mutations, wrap
from tsbench.qualification.titchy_wire import TCHY
from tsbench.planner.titchy_native import BATCH_POLICY

ROOT = Path(__file__).resolve().parents[2]


class TypedBatchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products, cls.binds = typed_inputs(ROOT, 1 << 20)

    def test_closed_positive_and_rejected_scope(self):
        slots = [r for r,_ in self.products.values()]
        self.assertEqual(Counter((r['method'], r['expected_status']) for r in slots),
                         {(TITCHY,0):12,(ZFP,0):11,(TITCHY,1):1,(TITCHY,3):1,(TITCHY,7):1,(ZFP,1):2,(ZFP,3):1})
        self.assertEqual({sid for _,rows in self.binds.values() for sid in rows},set(self.products))
        self.assertEqual(len(self.binds),9)
        self.assertTrue(all('negative_options' not in s for s in slots if s['expected_status']==0))
        oversize, = [r for r in slots if r['expected_status'] == 7]
        self.assertEqual(oversize['original']['column_bytes'], [1000001])

    def test_empty_titchy_cap_and_effective_container_count(self):
        slot, sample = next((r,x) for r,x in self.products.values() if r['method']==TITCHY and r['name']=='empty')
        p = BATCH_POLICY
        payload = TCHY.pack(b'TCHY',2,64,p['chunk'],p['endian'],p['split'],p['threshold_ppm'],p['active_bytes'],0,0,0)
        frame = wrap(slot,sample.schema,payload)
        self.assertEqual(inspect_linear(frame,slot)['wire']['splits'],[])
        self.assertEqual(set(mutations(frame,slot)),set(slot['reject_statuses']))
        for bad in mutations(frame,slot).values():
            with self.assertRaises(ContractError):
                inspect_linear(bad,slot)

    def test_zfp_boundary_mutations_are_metadata_only(self):
        slot, sample = next((r,x) for r,x in self.products.values() if r['method']==ZFP and r['name']=='weather-5')
        # Opaque fixture tests the envelope contract only, not upstream decode.
        frame = wrap(slot,sample.schema,bytes(16))
        result = inspect_linear(frame,slot)
        self.assertEqual(result['wire']['raw_payload_scope'],'trusted_payload_with_locked_schema')
        for bad in mutations(frame,slot).values():
            with self.assertRaises(ContractError):
                inspect_linear(bad,slot)
