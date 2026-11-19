from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError
from tsbench.planner import pcodec_intmult as im
from tsbench.planner.linear_batch import INTMULT, STREAM, batch_limits, protocol_methods
from tsbench.planner.pcodec import identity

ROOT = Path(__file__).resolve().parents[2]


class IntMultExecutionTests(unittest.TestCase):
    def test_cases_pin_requested_and_emitted_modes_without_float_conversion(self):
        products,bindings = im.execution_inputs(ROOT)
        self.assertEqual(sorted(len(slots) for _,slots in bindings.values()),[1,1,1,3])
        slots = {s['name']:s for s,_ in products.values()}
        self.assertEqual(slots['wide-base']['base'],9007199254740993)
        self.assertEqual(slots['wide-base']['wire'],{'mode':1,'base':9007199254740993})
        fallback = slots['high-entropy']
        self.assertEqual(fallback['base'],4093)
        self.assertEqual(fallback['wire'],{'mode':0,'base':None})
        plan = {'slots':list(slots.values())}
        im.check_slots(plan)
        bad = deepcopy(plan)
        next(s for s in bad['slots'] if s['name']=='wide-base')['base'] = int(float(slots['wide-base']['base']))
        with self.assertRaisesRegex(ContractError,'IntMult fixture or parameter'):
            im.check_slots(bad)
        for slot,sample in products.values():
            if slot['expected_status']:
                self.assertEqual(im.negative_input(slot),sample.columns[0])
                self.assertEqual(identity(sample.columns[0]),slot['original'])
                self.assertEqual(slot['parts'],{})
                self.assertEqual(im.operations(slot),[('intmult-encode',im.TOOL)])

    def test_protocol_bounds_are_versioned(self):
        self.assertNotIn(im.METHOD,protocol_methods(STREAM))
        self.assertIn(im.METHOD,protocol_methods(INTMULT))
        slot = {'method':im.METHOD,'protocol':im.PROTOCOL}
        self.assertEqual(batch_limits({'suite':INTMULT,'limits':{'file_bytes':1<<20}},slot)['file_bytes'],im.FILE_LIMIT)
        with self.assertRaisesRegex(ContractError,'ceiling exceeds'):
            batch_limits({'suite':INTMULT,'limits':{'file_bytes':4}},slot)
