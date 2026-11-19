import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tsbench.application.m0_acceptance import audit_m0
from tsbench.assets import ContractError, content_id
from tsbench.contracts import load_contract

ROOT = Path(__file__).resolve().parents[2]
ARGS = dict(
    native_submission='results/m0-native-empty-v20-20261119-r1/submission-report.json',
    service_plan='results/m0-service-scope-20261119-r2/plan.json',
    corpus_check='results/m0-corpus-closure-20261119-r1/corpus-check.json',
    feature_report='results/m0-corpus-closure-20261119-r1/corpus-feature-report.json',
    source_check='results/m0-corpus-closure-20261119-r1/source-check.json',
    build_result='results/m0-native-empty-v20-20261119-r1',
)


class M0AcceptanceTests(unittest.TestCase):
    def test_receipt_recomputes_real_evidence_and_keeps_qualification_closed(self):
        receipt = audit_m0(ROOT, **ARGS)
        self.assertTrue(receipt['stage_accepted'])
        self.assertFalse(receipt['qualification_granted'])
        self.assertFalse(receipt['timing_admitted'])
        self.assertEqual(receipt['receipt_id'], content_id({k: v for k, v in receipt.items() if k != 'receipt_id'}))
        self.assertIn('ALP AVX512BW', '\n'.join(receipt['open_items']))
        self.assertIn('M5', '\n'.join(receipt['open_items']))
        load_contract(ROOT, 'stage-receipt').validate(receipt, 'receipt')

    def test_receipt_rejects_tampered_submission_without_writing(self):
        local = ROOT / 'results' / '.m0-test-submission.json'
        original = json.loads((ROOT / ARGS['native_submission']).read_text())
        original['stage_accepted'] = True
        try:
            local.write_text(json.dumps(original), encoding='utf-8')
            with self.assertRaisesRegex(ContractError, 'not a complete unaccepted candidate'):
                audit_m0(ROOT, **{**ARGS, 'native_submission': 'results/.m0-test-submission.json'})
        finally:
            local.unlink(missing_ok=True)

    def test_receipt_rejects_service_denominator_drift(self):
        original = json.loads((ROOT / ARGS['service_plan']).read_text())
        original['scope_id'] = '0' * 64
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / 'plan.json'
            fake_rel = fake.relative_to(ROOT) if fake.is_relative_to(ROOT) else None
            # Use a project-local temporary file so the same asset path rules apply.
            local = ROOT / 'results' / '.m0-test-service-plan.json'
            try:
                local.write_text(json.dumps(original), encoding='utf-8')
                with self.assertRaises(ContractError):
                    audit_m0(ROOT, **{**ARGS, 'service_plan': 'results/.m0-test-service-plan.json'})
            finally:
                local.unlink(missing_ok=True)
