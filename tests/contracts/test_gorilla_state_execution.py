from pathlib import Path
import unittest

from tsbench.planner import gorilla_state as state
from tsbench.planner.gorilla import DUPLICATE, TRAFFIC
from tsbench.planner.linear_batch import GORILLA_STATE, INTMULT, batch_limits, protocol_methods

ROOT = Path(__file__).resolve().parents[2]


class GorillaStateExecutionTests(unittest.TestCase):
    def test_native_case_partition_retains_full_snapshot_and_two_final_frames(self):
        products,bindings = state.state_inputs(ROOT)
        self.assertEqual(sorted(len(ids) for _,ids in bindings.values()),[1]*6+[2]*2)
        by = {(s['method'],s['name']):s for s,_ in products.values()}
        a = by[state.APPEND,TRAFFIC]
        b = by[state.ITER,TRAFFIC]
        self.assertEqual(a['original'],b['original'])
        self.assertNotEqual(a['product_slot'],b['product_slot'])
        self.assertEqual(a['prefix']['rows'],23)
        self.assertEqual(a['tail']['bytes'],489*16)
        self.assertEqual(set(a['parts']),{'snapshot','uninterrupted','resumed'})
        self.assertEqual({label for label,tool in state.operations(a) if tool==state.TOOL},
                         {'prefix-work','full-work','trailing-work'})
        dupe = by[state.ITER,DUPLICATE]
        self.assertEqual(dupe['seek'][1][3][0],dupe['seek'][2][3][0])
        self.assertNotEqual(dupe['seek'][1][3][1],dupe['seek'][2][3][1])

    def test_state_protocol_is_versioned(self):
        self.assertNotIn(state.APPEND,protocol_methods(INTMULT))
        self.assertIn(state.APPEND,protocol_methods(GORILLA_STATE))
        slot = {'method':state.APPEND,'protocol':state.PROTOCOL}
        self.assertEqual(batch_limits({'suite':GORILLA_STATE,'limits':{'file_bytes':1<<20}},slot)['file_bytes'],16384)
