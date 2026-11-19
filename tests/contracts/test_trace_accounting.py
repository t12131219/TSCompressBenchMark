from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.analysis.trace import summarize_trace
from tsbench.assets import ContractError
from tsbench.contracts import load_contract


def span(index, parent, tid, stage, begin, end):
    return {'span_id': index, 'parent_id': parent, 'thread_id': tid, 'stage': stage,
            'start_ns': begin, 'end_ns': end}


class TraceAccountingTest(unittest.TestCase):
    def setUp(self):
        self.data = {'capacity_per_thread': 8, 'dropped': 0, 'spans': [
            span(1, 0, 42, 1, 100, 200), span(2, 1, 42, 2, 101, 110),
            span(3, 1, 42, 3, 110, 190), span(4, 1, 42, 4, 190, 198),
            span(257, 1, 97, 6, 125, 165), span(513, 1, 98, 6, 145, 185)]}
        self.stats = {'pid': 42, 'wall_ns': 120, 'native_jobs': 2, 'native_worker_threads': 2, 'native_caller_jobs': 0}

    def summarize(self, data):
        load_contract(ROOT, 'trace').validate(data, 'test trace')
        return summarize_trace(data, 8, self.stats, 'zstd-mt', 'encode')

    def test_cross_thread_union_never_subtracted_from_caller(self):
        summary = self.summarize(self.data)
        jobs = summary['stages'][-1]
        self.assertEqual(jobs['sum_thread_interval_ns_not_wall'], 80)
        self.assertEqual(jobs['observed_union_ns'], 60)
        self.assertEqual(jobs['observed_overlap_ns'], 20)
        self.assertEqual(jobs['max_observed_concurrency'], 2)
        self.assertEqual(summary['caller_unattributed_ns'], 3)

    def test_missing_trace_never_fills_exclusive_duration(self):
        trace = deepcopy(self.data)
        trace['spans'].pop()
        trace['dropped'] = 1
        summary = self.summarize(trace)
        self.assertIsNone(summary['caller_unattributed_ns'])
        self.assertFalse(summary['stages'][-1]['complete_for_instrumented_points'])
        trace['dropped'] = 0
        with self.assertRaisesRegex(ContractError, 'coverage differs'):
            self.summarize(trace)

    def test_reject_crossing_and_outside_root(self):
        trace = deepcopy(self.data)
        trace['spans'][1]['end_ns'] = 115
        with self.assertRaisesRegex(ContractError, 'crossing'):
            self.summarize(trace)
        trace = deepcopy(self.data)
        trace['spans'][-1]['end_ns'] = 201
        with self.assertRaisesRegex(ContractError, 'outside L0'):
            self.summarize(trace)
