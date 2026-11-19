"""Sprintz case/validator closure, independent of a build and host ISA."""
from copy import deepcopy
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from zlib import crc32

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError, canonical_bytes, content_id
from tsbench.planner.sprintz import REPORT, plain, plan_sprintz, ref, retained_paths
from tsbench.qualification.sprintz import reductions, verify_sprintz


class SprintzTests(unittest.TestCase):
    def test_cases_differentiate_backend_and_unsigned_accumulator(self):
        bundle = plan_sprintz()
        specs = {s['name']: s for s in bundle['shapes']}
        self.assertEqual(bundle['bundle_id'], content_id({k: v for k, v in bundle.items() if k != 'bundle_id'}))
        self.assertEqual(len(retained_paths(bundle)), 13)
        s = specs['u16-wide-sum']
        got = reductions(plain(s['name'], s['width'], s['dims'], s['count']), s['width'], s['dims'])
        self.assertEqual(got, {'count': [66001, 66000, 66000], 'sum': [4325375535, 4325244000, 4325178000],
                               'max': [65535, 65534, 65533]})
        self.assertTrue(all(value > 0xffffffff for value in got['sum']))
        self.assertEqual({s['name'] for s in specs.values() if s['worker_frame']},
                         {'empty', 'sub-row', 'worker-tail', 'worker-cap'})

    def test_replay_refuses_mutated_backend_lanes_recovery_and_wire(self):
        # Hand-assembled, valid literal-only FIRE/u16 SFB1. Real packed groups
        # are exercised by the unified native slot, not simulated here.
        def wire(raw, literal):
            payload = struct.pack('<IHH', 0, 3, 4) + literal
            return struct.pack('<4s4B6I', b'SFB1', 1, 16, 0, 0, 4, len(raw), len(payload),
                               crc32(raw), crc32(payload), 0) + payload

        bundle = plan_sprintz()
        spec = next(s for s in bundle['shapes'] if s['name'] == 'sub-row')
        bundle = {**bundle, 'shapes': [spec]}
        bundle['bundle_id'] = content_id({k: v for k, v in bundle.items() if k != 'bundle_id'})
        raw = plain('sub-row', 16, 4, 3)
        sfb1 = wire(raw, raw)
        schema = canonical_bytes(bundle['worker_schema'])
        bmk = struct.pack('<8sIQIQ', b'BMKSPR\x01\x00', 4, 3, len(schema), len(sfb1)) + schema + sfb1
        names = {REPORT, 'sub-row.sfb1', 'sub-row.bmk'}
        build = {'tsbench_sprintz_control': '9'*64}
        info = {'algorithm': 'fire', 'lanes': 4, 'path': 'generic_rle', 'threads': 1}
        exact = {'count': [1, 1, 1, 0], 'max': [0, 40001, 14466, 0], 'sum': [0, 40001, 14466, 0]}
        report = {'schema': 'bmk.m0-sprintz-control/2', 'bundle_id': bundle['bundle_id'],
                  'formal_qualification': False, 'formal_performance': False, 'build_sha256': build,
                  'driver_sha256': '8'*64, 'native_rejected': bundle['native_rejections'],
                  'worker_rejected': bundle['worker_rejections'],
                  'native': {'sub-row': {'native_frame': ref('sub-row.sfb1', sfb1), 'restored': spec['original'],
                                         'reductions': {'auto': {'backend': 'upstream_simd', **exact},
                                                        'scalar': {'backend': 'scalar', **exact},
                                                        'query_rejections': ['truncated', 'trailing', 'wrong_raw_length',
                                                                             'above_message_limit', 'odd_u16_raw_length'],
                                                        'lowdim_forced_simd_rejected': None}}},
                  'worker': {'sub-row': {'frame': ref('sub-row.bmk', bmk), 'restored': spec['original'],
                                         'schema': ref('schema.json', schema),
                                         'encode': {**info, 'operation': 'encode'}, 'decode': {**info, 'operation': 'decode'},
                                         'rejected': bundle['decode_rejections']}}}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'sub-row.sfb1').write_bytes(sfb1)
            (out / 'sub-row.bmk').write_bytes(bmk)

            def replay(document, sealed=names):
                (out / REPORT).write_bytes(canonical_bytes(document))
                verify_sprintz(bundle, build, '8'*64, out, sealed_paths=sealed)

            replay(report)
            with self.assertRaisesRegex(ContractError, 'not sealed'):
                replay(report, names - {'sub-row.sfb1'})
            for kind in ('backend', 'lane-sum', 'missing-reject', 'recovery', 'build'):
                edited = deepcopy(report)
                case = edited['native']['sub-row']['reductions']
                if kind == 'backend':
                    case['auto']['backend'] = 'scalar'
                elif kind == 'lane-sum':
                    case['scalar']['sum'] = [40001, 0, 14466, 0]
                elif kind == 'missing-reject':
                    case['query_rejections'].pop()
                elif kind == 'recovery':
                    edited['worker']['sub-row']['restored']['sha256'] = '0'*64
                else:
                    edited['build_sha256'] = {}
                with self.subTest(kind=kind), self.assertRaises(ContractError):
                    replay(edited)
            # Alter a literal, then recompute the CRC and all frame references.
            wrong = wire(raw, raw[:-1] + bytes([raw[-1] ^ 1]))
            wrapped = bmk[:-len(sfb1)] + wrong
            edited = deepcopy(report)
            edited['native']['sub-row']['native_frame'] = ref('sub-row.sfb1', wrong)
            edited['worker']['sub-row']['frame'] = ref('sub-row.bmk', wrapped)
            (out / 'sub-row.sfb1').write_bytes(wrong)
            (out / 'sub-row.bmk').write_bytes(wrapped)
            with self.assertRaisesRegex(ContractError, 'literal-tail'):
                replay(edited)
