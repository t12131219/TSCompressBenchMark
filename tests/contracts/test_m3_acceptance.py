import json
from pathlib import Path
import unittest

from tsbench.application.m3_acceptance import audit_m3
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    native_report="results/m0-native-empty-v20-20261119-r1/report.json",
    gorilla_report="results/m3-gorilla-roles-20261119-r2/recomputed.json",
    gorilla_restore="results/m3-gorilla-roles-20261119-r2/restore.json",
    composition_report="results/m3-tv-composition-20261119-r2/report.json",
    composition_restore="results/m3-tv-composition-20261119-r2/restore.json",
    composition_controls="results/m3-tv-composition-20261119-r2/controls.json",
    cross_format_report="results/m3-tv-cross-format-20261119-r2/report.json",
    cross_format_restore="results/m3-tv-cross-format-20261119-r2/restore.json",
    cross_format_controls="results/m3-tv-cross-format-20261119-r2/controls.json",
    limbs_report="results/m3-tv-limbs-20261119-r2/report.json",
    limbs_restore="results/m3-tv-limbs-20261119-r2/restore.json",
    limbs_controls="results/m3-tv-limbs-20261119-r2/controls.json",
)


class M3AcceptanceTests(unittest.TestCase):
    def test_receipt_accepts_coverage_but_keeps_qualification_closed(self):
        receipt = audit_m3(ROOT, **ARGS)
        self.assertTrue(receipt["stage_accepted"])
        self.assertFalse(receipt["qualification_granted"])
        self.assertFalse(receipt["timing_admitted"])
        self.assertEqual(receipt["receipt_id"], content_id({k: v for k, v in receipt.items() if k != "receipt_id"}))
        self.assertIn("AVX512BW", "\n".join(receipt["open_items"]))
        load_contract(ROOT, "m3-stage-receipt").validate(receipt, "receipt")

    def test_receipt_rejects_native_denominator_drift(self):
        original = json.loads((ROOT / ARGS["native_report"]).read_text())
        original["planned_products"] = 199
        local = ROOT / "results" / ".m3-test-native-report.json"
        try:
            local.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(ContractError):
                audit_m3(ROOT, **{**ARGS, "native_report": "results/.m3-test-native-report.json"})
        finally:
            local.unlink(missing_ok=True)
