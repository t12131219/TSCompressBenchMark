import json
from pathlib import Path
import unittest

from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "results/m3-real-runs/e90c45085d4e462e8cd26aa71deca94a/report.json"


class M3RealCorpusExecutionTests(unittest.TestCase):
    def test_preflight_is_current_and_not_an_acceptance(self):
        report = json.loads(REPORT.read_text())
        self.assertFalse(report["stage_accepted"])
        self.assertTrue(report["partial_preflight"])
        self.assertEqual(report["planned_work_items"], 828)
        self.assertEqual(report["selected_work_items"], 46)
        self.assertEqual(report["statuses"], {"verified": 46})
        load_contract(ROOT, "m3-real-corpus-run").validate(report, "report")
