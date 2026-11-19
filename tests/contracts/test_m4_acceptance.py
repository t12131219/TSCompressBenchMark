import json
from pathlib import Path
import unittest

from tsbench.application.m4_acceptance import audit_m4
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    plan="results/m4-native-profile-20261119-r2/plan.json",
    report="results/m4-native-profile-20261119-r2/recomputed.json",
    controls="results/m4-native-profile-20261119-r2/controls.json",
)


class M4AcceptanceTests(unittest.TestCase):
    def test_receipt_accepts_profiling_controls_without_admission(self):
        receipt = audit_m4(ROOT, **ARGS)
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["qualification_granted"])
        self.assertFalse(receipt["timing_admitted"])
        self.assertEqual(receipt["receipt_id"], content_id({k: v for k, v in receipt.items() if k != "receipt_id"}))
        self.assertIn("opaque", "\n".join(receipt["open_items"]))
        load_contract(ROOT, "m4-stage-receipt").validate(receipt, "receipt")

    def test_receipt_rejects_plain_profile_schedule_drift(self):
        plan = json.loads((ROOT / ARGS["plan"]).read_text())
        plan["schedule"] = plan["schedule"][:-1]
        local = ROOT / "results" / ".m4-test-plan.json"
        try:
            local.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaises(ContractError):
                audit_m4(ROOT, **{**ARGS, "plan": "results/.m4-test-plan.json"})
        finally:
            local.unlink(missing_ok=True)
