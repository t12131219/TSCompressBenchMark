import unittest
from pathlib import Path

from tsbench.assets import ContractError, load_json
from tsbench.planner import zfp_execution as z
from tsbench.planner.linear_batch import ALP_DECODE, ZFP_NATIVE, _suite_definition, protocol_methods

ROOT = Path(__file__).resolve().parents[2]


class ZfpExecutionContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products, cls.binds = z.plan_slots(ROOT)
        cls.slots = [slot for slot,_ in products.values()]

    def test_frozen_route_order_and_scope(self):
        policy,routes,_ = _suite_definition(ZFP_NATIVE)
        self.assertEqual(load_json(ROOT/policy)['routes'],[{'selection':n,'route':r} for n,r in routes])
        self.assertEqual(set(protocol_methods(ZFP_NATIVE))-set(protocol_methods(ALP_DECODE)),set(z.METHODS))
        self.assertEqual(len(self.binds),15)
        z.check_slots({'slots':self.slots,'limits':{'file_bytes':1<<20}})

    def test_recovery_mounts_and_pricings(self):
        for slot in self.slots:
            for name,op in z.steps(slot).items():
                if name.startswith(('restore','reopen')):
                    self.assertEqual(set(op['mounts']),{'metadata','wire'})
                    self.assertLessEqual(set(op['mounts'].values()),set(slot['parts']))
                    self.assertEqual(op['tool'],z.TOOL)
        array = self.slots[-1]
        self.assertEqual(z.metadata(z.ARRAY,array['spec']),b'ZNARRAY1 13 18 32\n')
        self.assertEqual(sum(array['parts'][part] for part in ('after','metadata')),82)

    def test_omp_observer_and_restore_are_separate(self):
        omp = self.slots[-2]
        steps = z.steps(omp)
        for policy in z.THREADS:
            self.assertEqual(steps['encode-'+policy]['tool'],z.OBSERVER)
            self.assertEqual(steps['encode-'+policy]['env'],z.THREAD_ENV)
            self.assertEqual(steps['restore-'+policy]['mounts'],{'metadata':'metadata','wire':'frame-'+policy})
        broken = {**omp,'spec':{**omp['spec'],'chunk_blocks':1}}
        with self.assertRaisesRegex(ContractError,'worker or same-field plan differs'):
            z.check_slots({'slots':self.slots[:4]+[broken,self.slots[-1]],'limits':{'file_bytes':1<<20}})
