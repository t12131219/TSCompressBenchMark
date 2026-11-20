"""Native TCHY range/indexed checks against source bits, away from source files."""
from pathlib import Path
import struct
import tempfile
import unittest

from tsbench.application.m3_titchy_access import WIRE_POLICY, invoke, validate_access
from tsbench.assets import ContractError, content_id, load_json
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.qualification.titchy_wire import decode_tchy

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / 'build/m3-real-r8/plugins/codecs/titchy-batch/tsbench_titchy_corpus_access_control'
PLAN = ROOT / 'results/m3-real-r13-20261119/plan.json'


class TitchyM3AccessTests(unittest.TestCase):
    @unittest.skipUnless(CONTROL.is_file(), 'build tsbench_titchy_corpus_access_control for this regression')
    def test_access_and_full_recovery_with_short_tail_and_multiple_splits(self):
        for count in (1, 8001):
            with self.subTest(rows=count), tempfile.TemporaryDirectory() as td:
                work = Path(td)
                source = work / 'source'
                vals = (0x8000000000000000, 0x7ff8000000000051, 0x3ff0000000000000, 0x8000000100000000)
                raw = b''.join(struct.pack('<Q', vals[i % 4] ^ (i // 4)) for i in range(count))
                source.write_bytes(raw)
                encoded, _ = invoke(CONTROL, work, 'encode', 'source', 'frame')
                source.unlink()
                wire = (work / 'frame').read_bytes()
                decoded, _ = decode_tchy(wire, 64, count, WIRE_POLICY)
                self.assertEqual(decoded, raw)
                for mode in ('batch-range', 'loaded-file-access'):
                    observed, _ = invoke(CONTROL, work, mode, 'frame', str(count), 'output')
                    restored = (work / 'output').read_bytes()
                    self.assertEqual(validate_access(mode, raw, wire, restored, encoded, observed)['artifact_bytes'], len(wire))
                observed['file_queries']['points'][0] ^= 1
                with self.assertRaisesRegex(ContractError, 'file responses'):
                    validate_access('loaded-file-access', raw, wire, restored, encoded, observed)
                # A malformed index must fail in the indexed reader and the stateless range, before restoration.
                broken = bytearray(wire)
                broken[38] ^= 1
                (work / 'broken').write_bytes(broken)
                for mode in ('batch-range', 'loaded-file-access'):
                    with self.assertRaisesRegex(ContractError, 'native (stateless range|callback open)'):
                        invoke(CONTROL, work, mode, 'broken', str(count), 'broken-output')
                    self.assertFalse((work / 'broken-output').exists())

    @unittest.skipUnless(PLAN.is_file(), 'requires locally frozen r13 plan')
    def test_control_hash_tamper_rejected_even_with_rehashed_plan(self):
        plan = load_json(PLAN)
        plan['build']['titchy_access']['adapter']['sha256'] = '0' * 64
        plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
        with self.assertRaisesRegex(ContractError, 'Titchy access control binding is stale'):
            check_m3_real_corpus_plan(ROOT, plan)

    @unittest.skipUnless(PLAN.is_file(), 'requires locally frozen r13 plan')
    def test_rehashed_plan_cannot_turn_intmult_float_input_into_applicable_case(self):
        plan = load_json(PLAN)
        item = next(x for x in plan['work_items'] if x['route'] == 'intmult')
        self.assertEqual(item['applicability'], 'outside_declared_domain')
        item['applicability'] = 'input_domain_matches'
        item['execution_state'] = 'not_run'
        plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
        with self.assertRaisesRegex(ContractError, 'corpus decision.*differs'):
            check_m3_real_corpus_plan(ROOT, plan)
