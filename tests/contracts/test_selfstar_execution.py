from pathlib import Path
import unittest

from tsbench.planner.selfstar import INPUT_REJECTIONS, PLUGIN, sha
from tsbench.planner.selfstar_execution import (LIMITS, LIVE, LIVE_ENCODE, READ, STATE, TOOL, check_selfstar_slots,
                                               operations, selfstar_inputs)

ROOT = Path(__file__).resolve().parents[2]


class OrderedExecutionContract(unittest.TestCase):
    def test_case_inputs_bind_both_mechanisms_no_reuse_of_passes(self):
        mapping, cases = selfstar_inputs(ROOT)
        self.assertEqual(len(mapping),25)
        self.assertEqual(len(cases),9)
        rows = [s for s,_ in mapping.values()]
        check_selfstar_slots({'slots':rows})
        self.assertEqual({s['name']:s['expected_status'] for s in rows if s['expected_status']},INPUT_REJECTIONS)
        self.assertEqual({i for _,ids in cases.values() for i in ids},set(mapping))
        for row,a in mapping.values():
            self.assertEqual(sha(a.columns[0]),row['original']['sha256'])
            self.assertEqual(sha(a.schema),row['original']['schema_sha256'])
            if row['method']==LIVE:
                order = operations(row)
                self.assertEqual(order[0],(LIVE_ENCODE,TOOL))
                self.assertIn((READ,TOOL),order)
                self.assertEqual((STATE,TOOL) in order,row['count']>512)
                self.assertEqual((LIMITS,TOOL) in order,row['name']=='fixture-1591')
                self.assertTrue(all(driver==TOOL for _,driver in order))
            else:
                self.assertEqual(row['method'],PLUGIN)
