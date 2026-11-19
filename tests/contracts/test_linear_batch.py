from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tsbench.application.batch_execution import _decode_inputs, _restore
from tsbench.assets import ContractError, digest
from tsbench.planner.linear_batch import linear_inputs
from tsbench.qualification.linear_batch import inspect_linear, mutations, wrap

ROOT = Path(__file__).resolve().parents[2]


class LinearBatchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products, cls.binds = linear_inputs(ROOT, 1 << 20)

    def test_same_ledger_sources_keep_native_type_and_rejection_contracts(self):
        slots = [row for row, _ in self.products.values()]
        self.assertEqual(Counter(r['method'] for r in slots), {'zstd':9, 'alp-auto':15})
        upstream, = [r for r in slots if r['upstream_zstd']]
        self.assertEqual(upstream['original']['columns'], [{'dtype':2,'count':65536}])
        rejects = [r['original']['column_bytes'] for r in slots if r['expected_status'] == 7]
        self.assertEqual(rejects, [[65544]])
        self.assertEqual({r['original']['columns'][0]['dtype'] for r in slots if r['method']=='alp-auto'}, {9,10})
        self.assertEqual({sid for _,ids in self.binds.values() for sid in ids}, set(self.products))

    def test_exact_zstd_frame_validation_uses_inner_size_and_no_trailing_data(self):
        slot, sample = next(x for x in self.products.values() if x[0]['name'] == 'zstd-legacy-0.zst')
        payload = b'\x28\xb5\x2f\xfd\x20\x00\x01\x00\x00'  # single-segment empty raw final block
        normal = wrap(slot,sample.schema,payload)
        self.assertEqual(inspect_linear(normal,slot)['wire']['content_size'], 0)
        for changed in mutations(normal,slot).values():
            with self.assertRaises(ContractError):
                inspect_linear(changed,slot)

    def test_restore_worker_is_single_column_and_checks_exact_digest(self):
        slot, sample = next(x for x in self.products.values() if x[0]['name'] == 'zstd-legacy-1.zst')
        method = {'plugin':'zstd','options':{}}
        plan = {'schema':'bmk.lossless-batch-execution/3','methods':{'zstd':method},'decoder':{},'limits':{}}
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            artifact = work/'artifact'
            artifact.touch()
            output = work/'out'
            output.mkdir()
            (output/'schema').write_bytes(sample.schema)
            (output/'v').write_bytes(sample.columns[0])
            (work/'decode-columns.stdout').write_text('{"columns":[{"dtype":2,"count":1}]}\n{}\n')
            with patch('tsbench.application.batch_execution.invoke_isolated_worker',
                       return_value=(output, {'status':'completed','reason':''})) as invoke:
                self.assertEqual(_restore(work,plan,slot,artifact,work,work,lambda:False), slot['original'])
                call = invoke.call_args.args
                self.assertEqual(call[2],method)
                self.assertEqual(call[7], {'frame':artifact})
                self.assertEqual(call[8], _decode_inputs(slot))
                (output/'v').write_bytes(b'\xff')
                self.assertNotEqual(digest(output/'v'),slot['original']['column_sha256'][0])
                with self.assertRaises(ContractError):
                    _restore(work,plan,slot,artifact,work,work,lambda:False)
