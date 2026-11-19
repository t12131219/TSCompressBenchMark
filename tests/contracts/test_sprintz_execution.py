import unittest

from tsbench.application.sprintz_execution import _abi_mutations
from tsbench.planner import sprintz_execution as sp
from tsbench.qualification.sprintz import GROUP_HEADER


class SprintzExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products, cls.by_case = sp.sprintz_inputs()
        cls.slots = {(s['method'],s['name']):s for s,_ in products.values()}

    def test_freeze_distinct_query_result_and_unsigned_oracle(self):
        batch = self.slots[sp.PLUGIN,'u16-wide-sum']
        query = self.slots[sp.QUERY,'u16-wide-sum']
        self.assertNotEqual(batch['product_slot'],query['product_slot'])
        self.assertEqual(batch['original'],query['original'])
        self.assertEqual(query['oracle'],{'count':[66001,66000,66000],
                                          'sum':[4325375535,4325244000,4325178000],
                                          'max':[65535,65534,65533]})
        self.assertEqual(sp.operations(query),[(f'sfb1-{action}',sp.TOOL) for action in ('encode','query','decode')])
        self.assertEqual(query['parts']['reductions'],sp.RESULT_LIMIT)
        self.assertLessEqual(sp.file_limit(query),1<<20)
        self.assertEqual(len(self.by_case),10)

    def test_dtype_mutation_preserves_extent_at_worker_cap(self):
        cap = self.slots[sp.PLUGIN,'worker-cap']
        header = GROUP_HEADER.pack(b'BMKSPR\x01\x00',4,cap['shape']['count'],len(sp.SCHEMA),40)
        wire = header+sp.SCHEMA+b'\0'*40
        bad = _abi_mutations(wire)['outer_dtype']
        self.assertEqual(GROUP_HEADER.unpack_from(bad),(b'BMKSPR\x01\x00',3,32768,len(sp.SCHEMA),40))
        self.assertEqual(bad[GROUP_HEADER.size:],wire[GROUP_HEADER.size:])
        self.assertEqual(len(bad),len(wire))


if __name__=='__main__':
    unittest.main()
