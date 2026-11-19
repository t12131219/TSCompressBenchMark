from copy import deepcopy
from pathlib import Path
import unittest

from tsbench.assets import ContractError, content_id
from tsbench.planner import lzbench_profiles as p
from tsbench.planner.linear_batch import LZBENCH_PROFILES, LZBENCH_SESSION, batch_limits, protocol_methods
from tsbench.supervisor.isolated_worker import validate_limits

ROOT = Path(__file__).resolve().parents[2]


class LzbenchProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        slots,cls.cases = p.plan_slots(ROOT)
        cls.rows = {s['method']:s for s,_ in slots.values()}

    def test_dictionary_files_only_and_split(self):
        slot = self.rows[p.DICT]
        graph = p.steps(slot)
        self.assertEqual(len(graph['train']['mounts']),128)
        self.assertNotIn('raw',graph['train']['mounts'])
        self.assertEqual(graph['restore']['mounts'],{'frame':'dictionary.zst','dict':'trained.zdict'})
        self.assertEqual(graph['reject-missing']['mounts'],{'frame':'dictionary.zst'})
        self.assertEqual(graph['reject-wrong-id']['mounts']['dict'],'wrong-dictionary')
        self.assertEqual(slot['parts']['trained.zdict'],2048)

    def test_xz_decode_profiles_share_the_exact_stream_and_xz_sync_is_separate(self):
        graph = p.steps(self.rows[p.XZ])
        for k in ('decode-shared-1','decode-shared-2','decode-sync-shared'):
            self.assertEqual(graph[k]['mounts'],{'frame':'workers-2.xz'})
        self.assertEqual(graph['decode-sync-own']['mounts'],{'frame':'workers-sync.xz'})
        self.assertEqual(graph['decode-sync-shared']['tool'],p.SYNC)
        self.assertEqual(graph['encode-sync']['tool'],p.SYNC)
        self.assertIn('threads=1',graph['decode-shared-1']['argv'])
        self.assertIn('threads=2',graph['decode-shared-2']['argv'])

    def test_profile_caps_and_denominator_cannot_be_narrowed(self):
        self.assertEqual(len(self.cases),11)
        self.assertEqual(set(protocol_methods(LZBENCH_PROFILES))-set(protocol_methods(LZBENCH_SESSION)),set(self.rows))
        rows = {'slots':list(self.rows.values())}
        p.check_slots(rows)
        altered = deepcopy(rows)
        slot = next(s for s in altered['slots'] if s['method']==p.ZSTD)
        self.assertEqual(batch_limits({'suite':LZBENCH_PROFILES},slot),slot['limits'])
        with self.assertRaisesRegex(ContractError,'invalid isolated worker limits'):
            validate_limits(slot['limits'])
        validate_limits(slot['limits'],file_ceiling=p.FILE_CEILING)
        slot['spec']['settings'] = [0,1]
        slot['product_slot'] = content_id({k:v for k,v in slot.items() if k!='product_slot'})
        with self.assertRaisesRegex(ContractError,'fixture, lane or resource contract differs'):
            p.check_slots(altered)

    def test_selected_runtime_conditions_bind_to_worker_slots_only(self):
        from tsbench.planner.native_admission import plan_native_admission
        eligible = [o for o in plan_native_admission(ROOT)['obligations'] if p.supports_condition(o)]
        self.assertEqual({o['route'] for o in eligible},{p.ZSTD,p.XZ})
        for o in eligible:
            self.assertEqual(p.condition_slots(o,self.rows.values()),[self.rows[o['route']]['product_slot']])
            edited = deepcopy(o)
            edited['condition_case']['criteria']['native_encoding_workers'] = [0,0]
            with self.assertRaisesRegex(ContractError,'worker condition criteria differ'):
                p.condition_slots(edited,self.rows.values())
