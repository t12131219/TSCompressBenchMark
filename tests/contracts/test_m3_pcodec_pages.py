"""Regression checks for the real-input pcodec page driver and detached recovery."""
import json
from pathlib import Path
import tempfile
import unittest

from tsbench.application.m3_pcodec_pages import _invoke, _verify_chunk
from tsbench.assets import ContractError, content_id
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / 'results/m3-real-r12-20261119/plan.json'
CONTROL = ROOT / 'build/m3-real-r8/plugins/codecs/pcodec/tsbench_pcodec_pages_control'


class PcodecCorpusPagesTests(unittest.TestCase):
    @unittest.skipUnless(CONTROL.is_file(), 'build tsbench_pcodec_pages_control for native regression')
    def test_both_native_lanes_restore_multiple_pages_and_tail_without_source(self):
        # 4096 and 513 rows exercise complete pages, multiple drain calls and tail.
        source = b''.join(x.to_bytes(8, 'little') for x in range(4096 + 513))
        for lane in ('source', 'native'):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                path = work / 'source.f64'
                path.write_bytes(source)
                encode, _ = _invoke([str(CONTROL), 'corpus-encode', lane, path.name, 'frame'], work)
                path.unlink()
                frame = (work / 'frame').read_bytes()
                decode, _ = _invoke([str(CONTROL), 'corpus-decode', lane, 'frame', 'output.f64'], work)
                _verify_chunk(source, (work / 'output.f64').read_bytes(), len(frame), encode, decode)
                with self.assertRaisesRegex(ContractError, 'restoration|recovery'):
                    _verify_chunk(source, b'\0' * len(source), len(frame), encode, decode)

                for invalid in (frame[:-1], frame + b'\0'):
                    (work / 'bad-frame').write_bytes(invalid)
                    with self.assertRaises(ContractError):
                        _invoke([str(CONTROL), 'corpus-decode', lane, 'bad-frame', 'bad-output'], work)
                    self.assertFalse((work / 'bad-output').exists())

    @unittest.skipUnless(CONTROL.is_file(), 'build tsbench_pcodec_pages_control for native regression')
    def test_native_zero_payload_pages_are_not_treated_as_missing_pages(self):
        source = b'\0' * (8 * 4200)
        for lane in ('source', 'native'):
            with self.subTest(lane=lane), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                (work / 'source.f64').write_bytes(source)
                encode, _ = _invoke([str(CONTROL), 'corpus-encode', lane, 'source.f64', 'frame'], work)
                (work / 'source.f64').unlink()
                decode, _ = _invoke([str(CONTROL), 'corpus-decode', lane, 'frame', 'output.f64'], work)
                _verify_chunk(source, (work / 'output.f64').read_bytes(), (work / 'frame').stat().st_size, encode, decode)
                self.assertEqual(encode['zero_payload_pages'], 2)

    @unittest.skipUnless(PLAN.is_file(), 'requires locally frozen r12 plan')
    def test_control_hash_tamper_is_rejected_even_with_rehashed_plan(self):
        plan = json.loads(PLAN.read_text())
        plan['build']['pcodec_pages']['executable']['sha256'] = '0' * 64
        plan['plan_content_id'] = content_id({k: v for k, v in plan.items() if k != 'plan_content_id'})
        with self.assertRaisesRegex(ContractError, 'pcodec pages control binding is stale'):
            check_m3_real_corpus_plan(ROOT, plan)
