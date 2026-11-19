import lzma
from pathlib import Path
import unittest

from tsbench.assets import ContractError
from tsbench.planner.linear_batch import EXTENDED, EXTENDED_XZ, batch_limits, binding_key
from tsbench.planner.xz_batch import METHOD, xz_inputs
from tsbench.qualification.linear_batch import inspect_linear, mutations, parts, wrap
from tsbench.qualification.lzbench import xz_blocks
from tsbench.qualification.xz_batch import direct_observation

ROOT = Path(__file__).resolve().parents[2]


class XzBatchContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products, cls.binds = xz_inputs(ROOT)

    def test_boundary_triplet_and_case_closure(self):
        slots = [row for row,_ in self.products.values()]
        self.assertEqual([(row['original']['column_bytes'][0],row['expected_status']) for row in slots],
                         [(0,0),(1,0),(65535,0),(65536,0),(65537,7)])
        self.assertEqual(len(self.binds),5)
        self.assertEqual({sid for _,ids in self.binds.values() for sid in ids},set(self.products))
        self.assertEqual([row['name'] for row in slots if 'oversize_dictionary' in row['reject_decodes']],['xz-legacy-1'])

    def test_dictionary_guard_preserves_index_and_exceeds_native_budget(self):
        slot, original = next((r,s) for r,s in self.products.values() if r['name']=='xz-legacy-1')
        payload = lzma.compress(original.columns[0],format=lzma.FORMAT_XZ,check=lzma.CHECK_NONE,preset=6)
        frame = wrap(slot,original.schema,payload)
        self.assertEqual(inspect_linear(frame,slot)['wire']['lzma2_dictionary_property'],22)
        bad = mutations(frame,slot)
        _, guard = parts(bad['oversize_dictionary'],slot)
        self.assertEqual(xz_blocks(guard)[0]['filters'],[(33,b'\x21')])
        with self.assertRaisesRegex(lzma.LZMAError,'Memory usage limit exceeded'):
            lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=256<<20).decompress(guard, max_length=2)
        for malformed in bad.values():
            with self.assertRaises(ContractError):
                inspect_linear(malformed,slot)
        self.assertEqual(direct_observation(slot)['background_workers'],1)

    def test_override_and_scoped_checks_do_not_modify_other_routes(self):
        base = {'address_space_bytes':128<<20,'file_bytes':1<<20,'wall_seconds':5}
        plan = {'limits':base,'method_address_space_bytes':{METHOD:256<<20}}
        self.assertEqual(batch_limits(plan,{'method':METHOD}),{**base,'address_space_bytes':256<<20})
        self.assertIs(batch_limits(plan,{'method':'zstd'}),base)
        self.assertIs(batch_limits(plan,{}),base)
        self.assertNotEqual(binding_key(EXTENDED_XZ,39,METHOD,'empty_and_short'),
                            binding_key(EXTENDED_XZ,40,'zstd-baseline','empty_and_short'))
        self.assertEqual(binding_key(EXTENDED,40,'zstd-baseline','empty_and_short'),'empty_and_short')
