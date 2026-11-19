import unittest
from pathlib import Path

from tsbench.application.alp_decode import ERROR, _decode_record, condition_state
from tsbench.assets import ContractError
from tsbench.planner import alp_decode as a
from tsbench.planner.linear_batch import ALP_DECODE, LZBENCH_PROFILES, protocol_methods

ROOT = Path(__file__).resolve().parents[2]


class ALPDecodeExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products, cls.binds = a.plan_slots(ROOT)
        cls.slots = {slot['fixture']['name']:slot for slot,_ in products.values()}

    def test_nine_locked_frames_cover_four_checks(self):
        self.assertEqual(len(self.slots),9)
        self.assertEqual(sorted(len(v[1]) for v in self.binds.values()),[2,2,4,9])
        self.assertEqual(set(protocol_methods(ALP_DECODE))-set(protocol_methods(LZBENCH_PROFILES)),{a.METHOD})
        for slot in self.slots.values():
            self.assertLessEqual(slot['parts']['frame'],1<<20)
            self.assertEqual([name for name,_ in a.operations(slot)],['encode',*a.REQUESTS])

    def record(self,request,*,label='mixed-decimal-raw',width=64,available512=False,built512=True):
        slot = self.slots[f'f{width}-{label}']
        caps = [[1,1],[1,1],[int(width==64)]*2,[1,1],
                [int(width==64 and built512),int(width==64 and available512)],[0,0],[0,0]]
        token = a.ID[request]
        supported = bool(caps[token][1])
        effective = ((4 if available512 else 2 if width==64 else 1) if token==3 else token) if supported else -1
        dec,rd,raw = slot['fixture']['decimal_rd_raw_vectors']
        wire = {'coded_decimal_vectors':dec,'coded_rd_vectors':rd,'raw_vectors':raw}
        doc = {'caps':caps,'status':0 if supported else 1,'diagnostic':'' if supported else ERROR,
               'written':slot['fixture']['count'] if supported else 0,'width':width,'request':token,'effective':effective,
               'counts':([dec if effective==i else 0 for i in range(3)]+[rd,raw]) if supported else [0]*5}
        return slot,wire,doc

    def test_compiled_avx512_unavailable_is_not_verified(self):
        req = 'falp-avx512bw'
        stmt = {'backend':req,'requests':[req,'falp-auto']}
        def observed(**kwargs):
            rows = {}
            for request in stmt['requests']:
                slot,wire,doc = self.record(request,**kwargs)
                rows[request] = _decode_record(slot,wire,request,doc)
            return {'decode_backends':{'requests':rows}}
        self.assertEqual(condition_state(stmt,observed()),'pending_supported_runtime')
        self.assertEqual(condition_state(stmt,observed(available512=True)),'verified_candidate')
        with self.assertRaisesRegex(ContractError,'lost compiled AVX512BW'):
            observed(built512=False)

    def test_avx2_has_no_decimal_work_on_rd_only(self):
        req = 'falp-avx2'
        slot,wire,doc = self.record(req,label='rd-only')
        row = _decode_record(slot,wire,req,doc)
        self.assertEqual((row['dispatch'],row['native_decimal_kernel_vectors']), (req,0))
        doc['counts'][2] = 2
        with self.assertRaisesRegex(ContractError,'native dispatch or branch counters'):
            _decode_record(slot,wire,req,doc)

    def test_f32_ran_native_rejection(self):
        req = 'falp-avx2'
        slot,wire,doc = self.record(req,width=32)
        self.assertEqual(_decode_record(slot,wire,req,doc)['capability']['reason'],'width_unsupported')
        doc['written'] = 1
        with self.assertRaisesRegex(ContractError,'native rejection differs'):
            _decode_record(slot,wire,req,doc)
