import json
from pathlib import Path
import unittest

from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "results/m3-real-r9-20261119/plan.json"


class M3RealCorpusPlanTests(unittest.TestCase):
    def test_plan_binds_updated_m0_m1_m2_and_full_denominator(self):
        plan = json.loads(PLAN.read_text())
        check_m3_real_corpus_plan(ROOT, plan)
        self.assertEqual(plan["coverage"]["file_route_decisions"], 828)
        self.assertEqual(plan["coverage"]["executable_work_items"], 724)
        self.assertEqual(plan["coverage"]["required_obligations"], 180)
        load_contract(ROOT, "m3-real-corpus-plan").validate(plan, "plan")

    def test_plan_id_tampering_is_rejected(self):
        plan = json.loads(PLAN.read_text())
        plan["coverage"]["executed_work_items"] = 1
        with self.assertRaises(ContractError):
            check_m3_real_corpus_plan(ROOT, plan)
