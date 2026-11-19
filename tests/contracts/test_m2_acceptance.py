import json
from pathlib import Path
import unittest

from tsbench.application.m2_acceptance import audit_m2
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    plan="results/m2-cache-formal-20261119-r2/timing-plan.json",
    report_a="results/m2-cache-formal-20261119-r2/recomputed-21d70ffa80554cd5909094ebf2c4277a.json",
    report_b="results/m2-cache-formal-20261119-r2/recomputed-f270cd6ac428487fbe4cfb3e7bc403ac.json",
    repeat="results/m2-cache-formal-20261119-r2/repeat-comparison.json",
    negative_controls="results/m2-cache-formal-20261119-r2/negative-controls.json",
)


class M2AcceptanceTests(unittest.TestCase):
    def test_receipt_accepts_protocol_but_keeps_timing_closed(self):
        receipt = audit_m2(ROOT, **ARGS)
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["qualification_granted"])
        self.assertFalse(receipt["timing_admitted"])
        self.assertEqual(receipt["receipt_id"], content_id({k: v for k, v in receipt.items() if k != "receipt_id"}))
        self.assertIn("exclusive_cpu=false", "\n".join(receipt["open_items"]))
        load_contract(ROOT, "m2-stage-receipt").validate(receipt, "receipt")

    def test_receipt_rejects_incomplete_repeat(self):
        original = json.loads((ROOT / ARGS["report_b"]).read_text())
        original["statuses"] = {"verified": 143}
        local = ROOT / "results" / ".m2-test-report.json"
        try:
            local.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ContractError):
                audit_m2(ROOT, **{**ARGS, "report_b": "results/.m2-test-report.json"})
        finally:
            local.unlink(missing_ok=True)
