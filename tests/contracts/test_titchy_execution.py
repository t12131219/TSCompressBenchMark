from pathlib import Path
import unittest

from tsbench.planner import titchy_execution as t

ROOT = Path(__file__).resolve().parents[2]


class TitchyAccessExecutionTests(unittest.TestCase):
    def test_distinct_driver_and_response_for_same_frozen_window(self):
        products,by_case = t.access_inputs(ROOT)
        self.assertEqual(len(by_case),11)
        by_method = {s['method']:(s,b) for s,b in products.values()}
        a,raw_a = by_method[t.LOADED]
        b,raw_b = by_method[t.RANGE]
        self.assertEqual(a['original'],b['original'])
        self.assertEqual(a['expected']['range'],b['expected'])
        self.assertEqual(raw_a,raw_b)
        self.assertNotEqual(a['product_slot'],b['product_slot'])
        self.assertEqual([op for op,_ in t.operations(a)],['tchy-encode','loaded','file'])
        self.assertEqual([op for op,_ in t.operations(b)],['tchy-encode','range'])
        self.assertEqual(a['parts'],{'backing':t.FILE_LIMIT,'answer':t.RESULT_LIMIT})
        t.check_slots({'slots':[a,b]})
