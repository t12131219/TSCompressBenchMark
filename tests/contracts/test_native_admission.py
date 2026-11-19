import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from tsbench.api import plan_native_requirements
from tsbench.assets import ContractError, content_id, load_json
from tsbench.planner import native_admission as admission

ROOT = Path(__file__).resolve().parents[2]


class NativeAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.requirements = plan_native_requirements(ROOT)
        cls.document = admission.compile_native_admission(ROOT,cls.requirements)

    def test_closed_obligations_quality_condition_and_restore(self):
        p = self.document
        self.assertEqual((12,36,180,6,186,215),tuple(p['coverage'][k] for k in (
            'selections','routes','required_checks','conditional_checks','total_obligations','bound_development_cases')))
        self.assertFalse(p['runnable'] or p['stage_accepted'] or p['qualification_granted'])
        self.assertEqual(0,p['coverage']['formal_execution_bindings'])
        self.assertEqual(186,len({s['obligation_id'] for s in p['obligations']}))
        self.assertTrue(all(r['retention']['restore']=='fresh_process_product_and_declared_assets_only' for r in p['routes']))
        routes = {r['route']:r for r in p['routes']}
        self.assertIn('file_and_chunk_metadata',routes['source-pages']['retention']['required'])
        self.assertIn('dictionary_or_decode_table_bytes_and_identity',routes['zstd-dictionary']['retention']['required'])
        self.assertEqual([0.5,0.1,0.5,0], [r['max_abs_error'] for r in routes['field-modes']['quality']['bounds']])
        self.assertEqual([16,4,1], next(x['requested_epsilon'] for x in routes['pbepla-replay']['quality']['bounds'] if x['name']=='weather'))
        corad = routes['corad-inference']['quality']
        self.assertEqual(2,len(corad['deployments']))
        self.assertEqual('reject_quality_not_comparable',corad['on_failure'])
        self.assertEqual('train_only_never_heldout',corad['tuning'])
        self.assertEqual('report_only_not_an_inference_pass',routes['corad-source-training']['quality']['heldout_use'])
        avx = next(s for s in p['obligations'] if s['check']=='avx512bw_decimal_with_effective_dispatch')
        self.assertEqual('requires_runtime_evidence',avx['state'])
        self.assertEqual('pending_supported_runtime',avx['condition_case']['verification']['runtime_unavailable'])
        self.assertFalse(any(s['state']=='passed' for s in p['obligations']))

    def test_scope_and_unknown_policy_fail_closed(self):
        source = load_json(ROOT/admission.POLICY)
        for edit,reason in ((lambda p:p['routes'].pop(),'route denominator'),
                            (lambda p:p['routes'].append(p['routes'][0]),'route denominator'),
                            (lambda p:p['protocols'].pop('native_query'),'protocol denominator'),
                            (lambda p:p['routes'][0].update(allow_unverified=True),'violates native-admission-policy schema')):
            cfg = copy.deepcopy(source)
            edit(cfg)
            with patch.object(admission,'load_json',side_effect=lambda path:cfg if path==ROOT/admission.POLICY else load_json(path)):
                with self.assertRaisesRegex(ContractError,reason):
                    admission.compile_native_admission(ROOT,self.requirements)
        altered = copy.deepcopy(self.requirements)
        altered['pbepla_cases']['inputs'][0]['requested_eps'] = [50]
        with self.assertRaisesRegex(ContractError,'plan identity'):
            admission.compile_native_admission(ROOT,altered)
        altered = copy.deepcopy(self.requirements)
        altered['routes'][0]['required'][0]['cases'][0] = altered['routes'][1]['required'][0]['cases'][0]
        altered['plan_content_id'] = content_id({k:v for k,v in altered.items() if k!='plan_content_id'})
        with self.assertRaisesRegex(ContractError,'wrong obligation'):
            admission.compile_native_admission(ROOT,altered)

    def test_cli_and_api_use_same_plan(self):
        result = subprocess.run([sys.executable,'-I','-B',str(ROOT/'bmk'),'native-admission-plan'],cwd='/',
                                check=True,capture_output=True,timeout=40)
        self.assertEqual(self.document,json.loads(result.stdout))
