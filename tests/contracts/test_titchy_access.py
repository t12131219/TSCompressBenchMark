from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tsbench.assets import ContractError, content_id, digest, load_json
from tsbench.planner.titchy_access import CONFIG, logical_result_bits, plan_titchy_access
from tsbench.qualification.titchy_access import verify_titchy_access
from tsbench.runtime import SCHEMA

ROOT = Path(__file__).resolve().parents[2]


class TitchyAccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.config, _ = plan_titchy_access(ROOT)

    def test_access_policy_validates_requests_and_freezes_budget(self):
        for name, change, reason in (
            ('bad-budget', {'policy': {**self.config['reader']['policy'], 'point': True}}, 'budget'),
            ('bad-bit', {'bits': [4013 * 64]}, 'outside frozen input'),
            ('duplicate-bit', {'bits': [0, 0]}, 'outside frozen input'),
            ('bad-range', {'range': [4012, 2]}, 'outside frozen input'),
        ):
            cfg = deepcopy(self.config)
            cfg['reader'].update(change)
            with self.subTest(name=name), patch('tsbench.planner.titchy_access.load_json', return_value=cfg), \
                    self.assertRaisesRegex(ContractError, reason):
                plan_titchy_access(ROOT)
        cfg = load_json(ROOT / CONFIG)
        cfg['reader']['policy']['point'] -= 1
        with patch('tsbench.planner.titchy_access.load_json', return_value=cfg):
            bundle, _, _ = plan_titchy_access(ROOT)
        self.assertNotEqual(bundle['bundle_id'], self.bundle['bundle_id'])
        self.assertNotEqual(bundle['cases'][1]['case_id'], self.bundle['cases'][1]['case_id'])
        self.assertEqual(bundle['cases'][0]['case_id'], self.bundle['cases'][0]['case_id'])

    def test_access_evidence_is_rechecked_without_running_decoder(self):
        bundle = self.bundle
        oracle, _, span = bundle['cases']
        results = oracle['criteria']['expected']
        build = {name: char * 64 for name, char in (('worker', 'a'), ('adapter', 'b'), ('native', 'c'))}
        def ref(name):
            return {'path': name, 'sha256': build[name]}
        lock = {'schema': SCHEMA, 'worker': ref('worker'), 'plugins': {'titchy-batch': {
            'manifest_id': 'test', 'options_schema_id': 'test', 'library': ref('adapter'), 'dependencies': [ref('native')],
        }}}
        lock['build_id'] = content_id(lock)
        def read(calls, bits=None):
            size = sum(c[1] for c in calls)
            entry = {'calls': calls, 'requested_bytes': size, 'successful_bytes': size}
            if bits is not None:
                entry['result_logical_bits'] = bits
            return entry
        budget = {label: read([[90, 8, True], [90, 8, True]], logical_bits) for label, logical_bits in
                  logical_result_bits(oracle['criteria']['request']).items()}
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            backing = out / bundle['backing_path']
            # Stand-in header/body for structural verification, not a decoder test.
            frame = bytearray(512)
            frame[:6] = b'TCHY\x02\x40'
            frame[22:30] = oracle['window']['count'].to_bytes(8, 'little')
            frame[34:38] = b'\x02\0\0\0'
            backing.write_bytes(frame)
            driver = 'd' * 64
            doc = {'schema': 'bmk.m0-titchy-control/2', 'definitions': driver, 'build': lock,
                   'formal_qualification': False, 'formal_performance': False, 'config_id': bundle['config_id'],
                   'access_bundle_id': bundle['bundle_id'], 'access_case_ids': [c['case_id'] for c in bundle['cases']],
                   'batch': [{'case': 'traffic-split-and-tail', 'window': oracle['window'], 'transform': oracle['transform'],
                              'input_sha256': oracle['input_sha256'], 'count': oracle['window']['count'], 'bit_exact': True,
                              'native_bytes': len(frame), 'native_sha256': digest(backing)}],
                   'access': {'backing_path': backing.name, 'backing_bytes': len(frame), 'backing_sha256': digest(backing),
                              'counts_scope': bundle['cases'][1]['criteria']['scope'], 'splits': 2,
                              'open_read_at': read([[0, 38, True], [38, 48, True]]), 'query_read_at': budget,
                              'repeated_query_read_at': deepcopy(budget), 'read_at_results': [results, results],
                              'detached_file_results': deepcopy(results), 'detached_file_queries_bit_exact': True,
                              'stateless_range': {'bit_exact': True, 'result': list(span['criteria']['expected'])}}}
            report = out / bundle['evidence_path']
            sealed = {report.name, backing.name}
            report.write_text(json.dumps(doc))
            verify_titchy_access(bundle, build, driver, out, sealed_paths=sealed)
            for name, reason in (
                ('input', 'frozen batch input'), ('budget', 'budget or accounting'), ('undercount', 'budget or accounting'),
                ('offset', 'invalid Titchy read call'), ('detached', 'loaded reader results'),
                ('stateless', 'stateless range'), ('driver', 'frozen cases and driver'), ('build', 'probe bindings'),
            ):
                bad = deepcopy(doc)
                access = bad['access']
                match name:
                    case 'input': bad['batch'][0]['input_sha256'] = '0' * 64
                    case 'budget': access['query_read_at']['point'] = read([[80, 65, True]], 64)
                    case 'undercount': access['query_read_at']['point']['requested_bytes'] = 8
                    case 'offset': access['repeated_query_read_at']['point']['calls'][0][0] = len(frame)
                    case 'detached': access['detached_file_results']['point'] ^= 1
                    case 'stateless': access['stateless_range']['result'].pop()
                    case 'driver': bad['definitions'] = '0' * 64
                    case 'build':
                        changed = bad['build']
                        changed['plugins']['titchy-batch']['dependencies'][0]['sha256'] = '0' * 64
                        changed['build_id'] = content_id({k: v for k, v in changed.items() if k != 'build_id'})
                report.write_text(json.dumps(bad))
                with self.subTest(name=name), self.assertRaisesRegex(ContractError, reason):
                    verify_titchy_access(bundle, build, driver, out, sealed_paths=sealed)
            report.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ContractError, 'not sealed'):
                verify_titchy_access(bundle, build, driver, out, sealed_paths={report.name})
            frame[-1] ^= 1
            backing.write_bytes(frame)
            with self.assertRaisesRegex(ContractError, 'digest|SHA|hash'):
                verify_titchy_access(bundle, build, driver, out, sealed_paths=sealed)
