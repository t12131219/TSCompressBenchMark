from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.api import PlanRequest, plan, plan_native_requirements
from tsbench.assets import ContractError, content_id, digest, load_json
from tsbench.planner.method_boundaries import plan_boundary_cases
from tsbench.planner.native_requirements import CONTRACT
from tsbench.qualification.method_boundaries import verify_boundary_evidence


class NativeRequirementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = plan(ROOT, PlanRequest()).document
        cls.bundle, cls.cases = plan_boundary_cases(ROOT)

    def planned(self):
        return plan_native_requirements(ROOT, scope=self.scope, boundary_cases=self.bundle)

    def test_closed_scope_retains_unbound_requirements(self):
        plan_doc = self.planned()
        self.assertEqual({'selections': 12, 'routes': 36, 'required_checks': 180,
                          'checks_with_bound_development_cases': 180, 'checks_without_case_binding': 0,
                          'conditional_checks': 6, 'explicitly_out_of_scope_claims': 26,
                          'bound_development_cases': 215, 'qualified_routes': 0}, plan_doc['coverage'])
        self.assertFalse(plan_doc['runnable'] or plan_doc['qualification_granted'])
        self.assertTrue(all(r['qualification'] == 'not_run' for r in plan_doc['routes']))
        self.assertTrue(all(c['resolution'] == 'requires_build_and_workload_evidence'
                            for r in plan_doc['routes'] for c in r['conditional']))
        self.assertTrue(all(c['cases'] for r in plan_doc['routes'] if r['selection'] == 9 for c in r['required']))
        workers = next(r for r in plan_doc['routes'] if r['route'] == 'xz-workers')
        self.assertTrue(all(c['cases'] for c in workers['required']))
        self.assertTrue(workers['conditional'])
        pcodec = [c for r in plan_doc['routes'] if r['selection'] == 11 for c in r['required']]
        self.assertEqual(27,len(pcodec))
        self.assertTrue(all(c['cases'] for c in pcodec))
        self.assertEqual(12, sum(x['artifact_basename'] is not None for x in self.bundle['cases']))
        self.assertEqual(content_id({k: v for k, v in plan_doc.items() if k != 'plan_content_id'}), plan_doc['plan_content_id'])
        by = {d['row']['case']: d for d in self.bundle['cases']}
        self.assertEqual((65544, 'resource_limit_7'), (by['zstd-plus']['row']['input_bytes'], by['zstd-plus']['row']['expected']))
        self.assertEqual(([7, 10], 'whole_object'), (by['gorilla-tv-at']['abi_types'], by['gorilla-tv-at']['task']))
        self.assertEqual(('values_only', 'bytes'), (by['ceda-cmip6-gsat-zstd']['task'], by['ceda-cmip6-gsat-zstd']['plugin_role']))
        self.assertEqual(2, by['alp-auto-plus']['expected_aln1_vectors'])
        corad = next(r for r in plan_doc['routes'] if r['route']=='corad-inference')
        self.assertTrue(all(c['cases'] for c in corad['required']))
        self.assertTrue(all(c['cases'] for r in plan_doc['routes'] if r['selection'] == 7 for c in r['required']))
        self.assertTrue(all(c['cases'] for r in plan_doc['routes'] if r['selection'] == 87 for c in r['required']))

    def test_alp_retains_avx512_as_conditional_native_route(self):
        routes = self.planned()["routes"]
        dec = next(r for r in routes if r["selection"] == 9 and r["route"] == "decode-backends")
        avx = next(x for x in dec["conditional"] if x["predicate"] == "alp_f64_avx512bw_available")
        self.assertEqual("avx512bw_decimal_with_effective_dispatch", avx["require"])
        self.assertEqual("requires_build_and_workload_evidence", avx["resolution"])
        self.assertEqual(["avx512f", "avx512bw", "avx512dq"], avx["verification"]["cpu_features_all_of"])
        self.assertEqual("pending_supported_runtime", avx["verification"]["runtime_unavailable"])
        self.assertNotIn(avx["require"], [x["claim"] for x in dec["out_of_scope"]])
        self.assertEqual("not_run", dec["qualification"])

    def test_cli_and_api_freeze_identical_case_requirements(self):
        completed = subprocess.run([sys.executable, '-B', ROOT / 'bmk', 'native-contract-plan'], cwd='/',
                                   capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(completed.stdout), self.planned())

    def test_route_replacement_and_case_misdirection_fail_closed(self):
        original = load_json(ROOT / CONTRACT)
        for mutant, reason in [('route', 'route closure'), ('case', 'mismatched route'), ('check', 'undeclared required check'),
                               ('overlap', 'ambiguous'), ('denominator', 'not all method boundary cases'),
                               ('titchy-swap', 'mismatched route'), ('pbepla-omission', 'not all PBEPLA cases')]:
            cfg = deepcopy(original)
            match mutant:
                case 'route': cfg['groups'][0]['route'] = 'wrong-entry'
                case 'case': cfg['boundary_contracts'][0]['checks']['f32_special_bits'] = ['zstd-at']
                case 'check': cfg['boundary_contracts'][0]['checks']['unknown_check'] = ['alp-auto-at']
                case 'overlap': cfg['groups'][1]['required'].append(cfg['groups'][1]['conditional'][0]['require'])
                case 'denominator': cfg['boundary_contracts'].pop()
                case 'pbepla-omission': cfg['pbepla_contracts'][0]['checks']['rational_error_each_level'].pop()
                case 'titchy-swap':
                    checks = cfg['titchy_access_contracts'][0]['checks']
                    checks['point_bit_range_oracle'], checks['log_open_and_request_bytes'] = (
                        checks['log_open_and_request_bytes'], checks['point_bit_range_oracle'])
            def patched(path):
                return cfg if path == ROOT / CONTRACT else load_json(path)
            with self.subTest(mutant=mutant), patch('tsbench.planner.native_requirements.load_json', side_effect=patched):
                with self.assertRaisesRegex(ContractError, reason):
                    self.planned()

    def test_evidence_crosschecks_input_restore_build_and_artifacts(self):
        chosen = [c for c in self.bundle['cases'] if c['row']['case'] in {'zstd-at', 'zstd-plus'}]
        body = {**self.bundle, 'cases': chosen}
        body.pop('bundle_id')
        bundle = {**body, 'bundle_id': content_id(body)}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            report_path = out / bundle['evidence_path']
            report_path.parent.mkdir()
            case, refusal = chosen
            base = case['row']
            frame = report_path.parent / case['artifact_basename']
            frame.write_bytes(b'stand-in bytes for verifier unit test')
            ok = {**base, 'case_id': case['case_id'], 'actual': 'verified', 'encode_exit': 0,
                  'artifact': {'path': frame.name, 'bytes': frame.stat().st_size, 'sha256': digest(frame)},
                  'restored': {'descriptor': {'dtype': 10, 'count': base['rows']}, 'schema_sha256': base['schema_sha256'],
                               'columns_sha256': base['input_column_sha256']}}
            for op in ('encode', 'decode'):
                ok[op+'_info'] = {'operation': op, 'mode': 'batch', 'backend': 'ln-zstd-baseline', 'threads': 1}
            rejected = {**refusal['row'], 'case_id': refusal['case_id'], 'actual': 'resource_limit_7', 'encode_exit': 3,
                        'artifact': None, 'diagnostic': 'plugin status 7: fixture rejection'}
            build = {'worker': 'f'*64}
            doc = {'schema': 'bmk.m0-method-boundary-report/2', 'config_id': bundle['config_id'],
                   'bundle_id': bundle['bundle_id'], 'build_sha256': build, 'formal_qualification': False,
                   'formal_performance': False, 'rows': [ok, rejected]}
            report_path.write_text(json.dumps(doc))
            sealed = {str(frame.relative_to(out))}
            verify_boundary_evidence(bundle, build, out, sealed_paths=sealed)
            for mutation, reason in [('build', 'not bound'), ('order', 'frozen input'), ('restore', 'restored data'),
                                     ('artifact', 'SHA-256 mismatch'), ('threads', 'unexpected encode path'),
                                     ('false_success', 'unexpected method-boundary outcome')]:
                bad = deepcopy(doc)
                match mutation:
                    case 'build': bad['build_sha256']['worker'] = '0'*64
                    case 'order': bad['rows'].reverse()
                    case 'restore': bad['rows'][0]['restored']['columns_sha256'] = ['0'*64]
                    case 'artifact': bad['rows'][0]['artifact']['sha256'] = '0'*64
                    case 'threads': bad['rows'][0]['encode_info']['threads'] = True
                    case 'false_success': bad['rows'][1]['actual'] = 'verified'
                report_path.write_text(json.dumps(bad))
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ContractError, reason):
                    verify_boundary_evidence(bundle, build, out, sealed_paths=sealed)
            report_path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ContractError, 'frame denominator'):
                verify_boundary_evidence(bundle, build, out, sealed_paths=set())
            (report_path.parent/'zstd-plus.bmk').write_bytes(b'not allowed for refusal')
            with self.assertRaisesRegex(ContractError, 'expected resource refusal'):
                verify_boundary_evidence(bundle, build, out, sealed_paths=sealed)
