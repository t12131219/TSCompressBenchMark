import json
from pathlib import Path
import unittest

from tsbench.application.m1_acceptance import audit_m1
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    plan="results/m1-formal-freeze-20261119-r3/plan.json",
    report="results/e3cd0ecca7a44c66a27770fdeeda517b/derived/report.json",
    restore="results/e3cd0ecca7a44c66a27770fdeeda517b/derived/restore.json",
)


class M1AcceptanceTests(unittest.TestCase):
    def test_receipt_recomputes_formal_vertical_slice_without_granting_qualification(self):
        receipt = audit_m1(ROOT, **ARGS)
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["qualification_granted"])
        self.assertFalse(receipt["timing_admitted"])
        self.assertEqual(receipt["receipt_id"], content_id({k: v for k, v in receipt.items() if k != "receipt_id"}))
        self.assertIn("M2", "\n".join(receipt["open_items"]))
        load_contract(ROOT, "m1-stage-receipt").validate(receipt, "receipt")

    def test_receipt_rejects_tampered_report(self):
        original = json.loads((ROOT / ARGS["report"]).read_text())
        original["planned_slots"] = 17
        local = ROOT / "results" / ".m1-test-report.json"
        try:
            local.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ContractError):
                audit_m1(ROOT, **{**ARGS, "report": "results/.m1-test-report.json"})
        finally:
            local.unlink(missing_ok=True)
