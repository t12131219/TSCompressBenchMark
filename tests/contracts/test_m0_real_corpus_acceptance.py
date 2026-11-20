import json
from pathlib import Path
import unittest

from tsbench.application.m0_real_corpus_acceptance import audit_m0_real_corpus
from tsbench.assets import ContractError

ROOT = Path(__file__).resolve().parents[2]


class UpdatedM0RealCorpusReceiptTests(unittest.TestCase):
    def test_current_binding_is_accepted_without_execution(self):
        receipt = audit_m0_real_corpus(
            ROOT,
            predecessor="results/m0-acceptance-20261119-r2/receipt.json",
            corpus_check="results/m0-full-corpus-intake-20261119-r2/check.json",
            native_definition="results/m0-native-corpus-definition-20261119-r8/plan.json",
            binding="results/m0-full-corpus-intake-20261119-r2/manifest-binding.json",
        )
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["qualification_granted"])
        self.assertEqual(receipt["coverage"]["routes"], 36)
        self.assertEqual(receipt["coverage"]["required_obligations"], 180)

    def test_stale_binding_is_rejected(self):
        path = ROOT / "results/m0-full-corpus-intake-20261119-r2/manifest-binding.json"
        doc = json.loads(path.read_text())
        doc["native_definition"]["plan_content_id"] = "0" * 64
        path_text = json.dumps(doc)
        temp = ROOT / "results/m0-full-corpus-intake-20261119-r2/.test-stale-binding.json"
        temp.write_text(path_text)
        try:
            with self.assertRaises(ContractError):
                audit_m0_real_corpus(
                    ROOT,
                    predecessor="results/m0-acceptance-20261119-r2/receipt.json",
                    corpus_check="results/m0-full-corpus-intake-20261119-r2/check.json",
                    native_definition="results/m0-native-corpus-definition-20261119-r8/plan.json",
                    binding="results/m0-full-corpus-intake-20261119-r2/.test-stale-binding.json",
                )
        finally:
            temp.unlink()


if __name__ == "__main__":
    unittest.main()
