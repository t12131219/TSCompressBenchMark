from pathlib import Path
import unittest

from tsbench.application.m1_real_corpus_acceptance import audit_m1_real_corpus
from tsbench.assets import ContractError

ROOT = Path(__file__).resolve().parents[2]


class UpdatedM1RealCorpusReceiptTests(unittest.TestCase):
    def test_current_receipt_is_recomputed(self):
        receipt = audit_m1_real_corpus(
            ROOT,
            predecessor="results/m0-real-corpus-acceptance-20261119-r1/receipt.json",
            plan="results/m1-real-r8-20261119/plan.json",
            report="results/4ffa8acb258a4a29a4a50c354003c0f9/derived/report.json",
            restore="results/4ffa8acb258a4a29a4a50c354003c0f9/restore.json",
            controls="results/m1-real-r8-20261119/controls.json",
        )
        self.assertTrue(receipt["stage_accepted"])
        self.assertEqual(receipt["coverage"]["slots"], 6)
        self.assertEqual(receipt["coverage"]["restored_verified_slots"], 6)

    def test_wrong_plan_is_rejected(self):
        with self.assertRaises(ContractError):
            audit_m1_real_corpus(
                ROOT,
                predecessor="results/m0-real-corpus-acceptance-20261119-r1/receipt.json",
                plan="results/m1-formal-freeze-20261119-r3/plan.json",
                report="results/4ffa8acb258a4a29a4a50c354003c0f9/derived/report.json",
                restore="results/4ffa8acb258a4a29a4a50c354003c0f9/restore.json",
                controls="results/m1-real-r8-20261119/controls.json",
            )


if __name__ == "__main__":
    unittest.main()
