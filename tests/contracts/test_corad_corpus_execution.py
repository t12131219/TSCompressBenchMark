from copy import deepcopy
from pathlib import Path
import struct
import unittest

from tsbench.application.corad_corpus_execution import judge_quality
from tsbench.assets import ContractError, load_json
from tsbench.planner.corad_corpus import calibrate_quality, plan_cohorts
from tsbench.planner.corad_corpus_execution import bind_cohort
from tsbench.planner.native_corpus import POLICY
from tsbench.corpus_ingress import MANIFEST

ROOT = Path(__file__).resolve().parents[2]


class CoradCorpusExecutionTests(unittest.TestCase):
    def test_new_input_binding_uses_ordered_shape_and_disjoint_times(self):
        corpus = load_json(ROOT/MANIFEST)
        entry = next(x for x in corpus['datasets'] if x['id']=='national-illness')
        layout = next(r['corad_layout'] for r in load_json(ROOT/POLICY)['routes'] if r['route']=='corad-inference')
        cohort, = plan_cohorts(entry,layout,{})
        b, train, test = bind_cohort(ROOT,entry,cohort,layout)
        self.assertEqual(b['ordered_columns'],entry['columns'][1:])
        self.assertEqual(len(train), 8*7*129)
        self.assertEqual([len(raw) for raw in test], [8*7*194])
        self.assertLess(b['train']['last_tick'], b['test_frames'][0]['first_tick'])
        self.assertEqual(b['train_only_quality_bounds'],calibrate_quality(train,count=129,width=7))
        bad = deepcopy(cohort)
        bad['ordered_column_names'].reverse()
        with self.assertRaisesRegex(ContractError,'ordered columns'):
            bind_cohort(ROOT,entry,bad,layout)
        bad = deepcopy(cohort)
        bad['train']['rows'] = [772,901]
        with self.assertRaisesRegex(ContractError,'overlap or differ'):
            bind_cohort(ROOT,entry,bad,layout)

    def test_quality_gates_are_inclusive_and_keep_column_failures(self):
        train = struct.pack('<4d',0,2,10,10)
        bounds = calibrate_quality(train,count=2,width=2)
        expected = struct.pack('<4d',3,5,10,10)
        boundary = struct.pack('<4d',4,4,10,10)
        _, accepted = judge_quality(expected,boundary,['a','b'],bounds)
        self.assertTrue(accepted)
        bad = struct.pack('<4d',4,4,10,10.000000000000002)
        rows, accepted = judge_quality(expected,bad,['a','b'],bounds)
        self.assertFalse(accepted)
        self.assertEqual(rows[0]['exact_mse'],'1')
        self.assertFalse(rows[1]['max_abs_error_within_bound'])
