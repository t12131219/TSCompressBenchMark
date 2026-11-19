"""The sealed timing diagnostic rejects schedule/work/retention substitutions."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError, canonical_bytes, load_json  # noqa: E402
from tsbench.planner.frame_batches import CONFIG, LANES, choose_loops, materialize, plan_frame_batches, reference_path  # noqa: E402
from tsbench.qualification.frame_batches import verify_frame_batches  # noqa: E402


class FrameBatchTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        config = load_json(ROOT / CONFIG)
        config['cases'] = [{'id': 'example', 'rows': 31, 'methods': ['raw-store']}]
        (self.root / CONFIG).parent.mkdir(parents=True)
        (self.root / CONFIG).write_bytes(canonical_bytes(config))
        self.plan = plan_frame_batches(self.root)
        self.build = {'probe': 'a' * 64}
        self.report = self.root / self.plan['evidence_path']
        self.report.parent.mkdir()
        self.frame = self.report.parent / reference_path('example', 'raw-store')
        self.sealed = {p.relative_to(self.root).as_posix() for p in (self.report, self.frame)}
        values, schema = materialize(self.plan['cases'][0])
        self.wire = struct.pack('<8sIQI', b'BMKRAW\x01\x00', 10, 31, len(schema)) + schema + values
        self.frame.write_bytes(self.wire)
        logical = len(values) + len(schema)
        frame_size = len(self.wire)
        checksum = sha256(self.wire).hexdigest()

        def sample(group, lane, loops):
            return {'lane': lane, 'lifecycle': group['lifecycle'], 'pid': 1, 'loops': loops,
                    'warmups': config['warmups'], 'encoded_verified': loops, 'decoded_verified': loops,
                    'encode_batch_ns': 30001 * loops, 'decode_batch_ns': 100001 * loops, 'release_ns': loops,
                    'frame_bytes_each': frame_size, 'frame_capacity_total': frame_size * loops,
                    'decoded_logical_and_schema_total': logical * loops, 'budget_bytes': config['retention_budget_bytes'],
                    'encode_cpu_endpoints': [0, 0], 'decode_cpu_endpoints': [0, 0], 'reference_sha256': checksum,
                    **{'warmup_' + op + '_info': {'operation': op, 'mode': 'batch', 'threads': 1, 'fallback': False,
                                                 'backend': 'copy'} for op in ('encode', 'decode')}}

        groups = []
        for group in self.plan['groups']:
            pilots = [sample(group, lane, 1) for lane in LANES]
            loops = choose_loops(config, logical, pilots)
            groups.append({'group_id': group['group_id'], 'calibration': pilots, 'loops': loops,
                           'rounds': [[sample(group, lane, loops) for lane in order] for order in group['round_lane_order']]})
        self.body = {'schema': 'bmk.frame-batches-evidence/1', 'plan_id': self.plan['plan_id'], 'build_sha256': self.build,
                     'environment': {'allowed_cpu_ids': [0], 'kernel_release': 'test', 'clock': 'std::chrono::steady_clock',
                                     'exclusive_cpu': 'not_reserved', 'numa_placement': 'not_measured', 'cache': config['cache'],
                                     'frequency_and_interference': 'not_measured'},
                     'groups': groups, 'formal_performance': False, 'qualification_granted': False}

    def verify(self, report=None, *, sealed=None):
        self.report.write_bytes(canonical_bytes(self.body if report is None else report))
        verify_frame_batches(self.plan, self.build, self.root, sealed_paths=self.sealed if sealed is None else sealed)

    def test_replay_and_refuse_edited_order_and_calibration(self):
        self.verify()
        wrong = deepcopy(self.body)
        wrong['groups'][0]['rounds'][0].reverse()
        with self.assertRaisesRegex(ContractError, 'batch order'):
            self.verify(wrong)
        wrong = deepcopy(self.body)
        for row in wrong['groups'][0]['calibration']:
            row['encode_batch_ns'] *= 2
        with self.assertRaisesRegex(ContractError, 'loops do not replay'):
            self.verify(wrong)

    def test_refuse_wrong_validation_count_checksum_capacity_and_backend(self):
        for field, value, why in (
            ('decoded_verified', 0, 'counts'), ('reference_sha256', '1' * 64, 'accounting'),
            ('frame_capacity_total', 1234567890, 'accounting'),
            ('warmup_decode_info', {'backend': 'other'}, 'backend'),
        ):
            with self.subTest(field=field):
                wrong = deepcopy(self.body)
                wrong['groups'][1]['rounds'][0][0][field] = value
                with self.assertRaisesRegex(ContractError, why):
                    self.verify(wrong)

    def test_refuse_changed_reference_or_missing_sealed_record(self):
        with self.assertRaisesRegex(ContractError, 'sealed batch sample set'):
            self.verify(sealed={self.plan['evidence_path']})
        self.frame.write_bytes(self.wire[:-1] + bytes([self.wire[-1] ^ 1]))
        with self.assertRaisesRegex(ContractError, 'does not reproduce the fixture'):
            self.verify()

    def test_calibration_keeps_distinct_rounds_and_enforces_retention_cap(self):
        config = self.plan['config']
        pilots = [{'frame_capacity_total': 2**24, 'frame_bytes_each': 2**24,
                   'encode_batch_ns': 50000, 'decode_batch_ns': 1000}] * 2
        self.assertEqual(choose_loops(config, 2**26, pilots), 1)
        self.assertEqual(len(self.plan['groups'][0]['round_lane_order']), config['matched_rounds'])
        with self.assertRaisesRegex(ContractError, 'cannot fit one retained operation'):
            choose_loops(config, 2**27, pilots)
