from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError
from tsbench.planner import titchy_execution as access, titchy_stream as stream
from tsbench.planner.linear_batch import ACCESS, STREAM, batch_limits, protocol_methods
from tsbench.planner.titchy_native import sha

ROOT = Path(__file__).resolve().parents[2]


class TitchyStreamExecutionTests(unittest.TestCase):
    def test_stream_reuses_cases_but_charges_separate_wire_and_config(self):
        products,cases = stream.stream_inputs(ROOT)
        sid, = products
        slot,raw = products[sid]
        self.assertEqual(len(cases),6)
        self.assertEqual(len({source for source,_ in cases.values()}),1)
        self.assertTrue(all(ids==[sid] for _,ids in cases.values()))
        self.assertEqual(slot['original']['sha256'],sha(raw.columns[0]))
        self.assertEqual(slot['original']['bytes'],32104)
        self.assertEqual(slot['parts'],{'archive':128<<10,'config':32})
        self.assertEqual(stream.operations(slot),[('packet-encode',stream.TOOL),('packet-decode',stream.TOOL)])
        siblings,_ = access.access_inputs(ROOT)
        plan = {'slots':[slot,*[s for s,_ in siblings.values()]]}
        stream.check_slots(plan)
        for key in ('parts','policy','status_policy'):
            bad = deepcopy(plan)
            del bad['slots'][0][key][next(iter(slot[key]))]
            with self.subTest(key=key), self.assertRaisesRegex(ContractError,'stream wire/resource policy'):
                stream.check_slots(bad)

    def test_stream_protocol_and_limit_do_not_relabel_archived_access_suite(self):
        self.assertNotIn(stream.METHOD,protocol_methods(ACCESS))
        self.assertIn(stream.METHOD,protocol_methods(STREAM))
        slot = {'protocol':stream.PROTOCOL,'method':stream.METHOD}
        self.assertEqual(batch_limits({'suite':STREAM,'limits':{'file_bytes':1<<20}},slot)['file_bytes'],128<<10)
        with self.assertRaisesRegex(ContractError,'ceiling exceeds'):
            batch_limits({'suite':STREAM,'limits':{'file_bytes':1}},slot)
