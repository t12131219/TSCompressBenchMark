import json
from pathlib import Path
import unittest

from tsbench.application.m2_real_corpus_acceptance import audit_m2_real_corpus
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    plan="results/m2-real-r8-20261119/plan.json",
    report_a="results/m2-cache-formal-20261119-r2/recomputed-21d70ffa80554cd5909094ebf2c4277a.json",
    report_b="results/m2-cache-formal-20261119-r2/recomputed-f270cd6ac428487fbe4cfb3e7bc403ac.json",
    repeat="results/m2-cache-formal-20261119-r2/repeat-comparison.json",
    controls="results/m2-real-r8-20261119/controls.json",
)


class M2RealCorpusAcceptanceTests(unittest.TestCase):
    def test_updated_receipt_binds_m0_m1_and_keeps_ranking_closed(self):
        receipt = audit_m2_real_corpus(ROOT, **ARGS)
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["timing_admitted"])
        self.assertEqual(receipt["receipt_id"], content_id({k: v for k, v in receipt.items() if k != "receipt_id"}))
        self.assertEqual(receipt["coverage"]["verified_batches"], 288)
        load_contract(ROOT, "m2-real-corpus-stage-receipt").validate(receipt, "receipt")

    def test_updated_receipt_rejects_stale_predecessor_binding(self):
        original = json.loads((ROOT / ARGS["plan"]).read_text())
        original["predecessors"]["m1_real_corpus_receipt"]["receipt_id"] = "0" * 64
        original["plan_content_id"] = content_id({k: v for k, v in original.items() if k != "plan_content_id"})
        local = ROOT / "results" / ".m2-real-test-plan.json"
        try:
            local.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ContractError):
                audit_m2_real_corpus(ROOT, **{**ARGS, "plan": "results/.m2-real-test-plan.json"})
        finally:
            local.unlink(missing_ok=True)
