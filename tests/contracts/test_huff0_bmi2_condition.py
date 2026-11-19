"""Keep actual dispatch separate from host and build capability declarations."""
import unittest

from tsbench.application.huff0_execution import condition_evidence
from tsbench.assets import ContractError
from tsbench.planner.huff0 import DECODE_API


def rows(cpu):
    slots = [(0,0),(0,0),(0,0),(0,1),(0,2),(1,2),(1,2),(2,2),(2,2)]
    def entries(which,n,arg):
        return {name:{f'bmi2_arg_{i}':n if which==j and i==arg else 0 for i in (0,1)}
                for j,name in enumerate(DECODE_API)}
    return [{'status':'verified','huff0_validation':{
        'runtime':{'cpu_bmi2_available':cpu},'native_decode_entries':entries(which,n,int(cpu)),
        'bmi2_comparison':{'portable_decode_entries':entries(which,n,0)}}} for which,n in slots]


class Huff0UnifiedCondition(unittest.TestCase):
    def test_same_census_but_missing_cpu_keeps_condition_pending(self):
        available = condition_evidence(rows(True))
        unavailable = condition_evidence(rows(False))
        self.assertEqual(available['state'],'verified_candidate')
        self.assertEqual(unavailable['state'],'pending_supported_runtime')
        self.assertEqual(unavailable['reason'],'host_bmi2_unavailable')
        self.assertEqual(unavailable['primary_completed_decode_calls'], unavailable['portable_completed_decode_calls'])

    def test_zero_work_or_inconsistent_cpu_cannot_claim_dispatch(self):
        sample = rows(True)
        sample[4]['huff0_validation']['native_decode_entries'][DECODE_API[0]]['bmi2_arg_1'] = 0
        with self.assertRaisesRegex(ContractError,'actual native call census'):
            condition_evidence(sample)
        sample[4]['huff0_validation']['runtime']['cpu_bmi2_available'] = False
        with self.assertRaisesRegex(ContractError,'CPU feature report differs'):
            condition_evidence(sample)
