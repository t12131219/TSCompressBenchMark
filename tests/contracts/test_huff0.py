from copy import deepcopy
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError
from tsbench.planner.huff0 import plan_huff0, retained_paths
from tsbench.qualification.huff0 import _bitstreams, _calls, _model, _weights_size


class Huff0EvidenceTests(unittest.TestCase):
    def test_frozen_inputs_and_recovery_closure(self):
        bundle, raw = plan_huff0(ROOT)
        self.assertLessEqual(bundle['train_window']['partition_end'], bundle['test_window']['partition_start'])
        self.assertEqual([32768,32824], list(map(len,(raw['train'],raw['test']))))
        self.assertEqual([1,1,4,4], [x['streams'] for x in bundle['etb1']])
        self.assertEqual(14, sum(len(x['blocks']) for x in bundle['etb1']))
        self.assertEqual(27, len(retained_paths(bundle)))
        self.assertEqual(11, len(bundle['cases']))

    def test_weights_and_4x_jump_boundaries(self):
        jump = struct.pack('<HHH',1,1,1)
        _bitstreams(jump+b'\x01'*4,4)
        for raw in (jump+b'\x01'*3, jump+b'\x01'*3+b'\0', struct.pack('<HHH',65535,1,1)+b'\x01'*4):
            with self.assertRaises(ContractError):
                _bitstreams(raw,4)
        self.assertEqual(3,_weights_size(b'\x82\x12\x30'))
        self.assertEqual(3,_weights_size(b'\x02\x12\x30'))
        with self.assertRaises(ContractError):
            _weights_size(b'\xff\0')
        with self.assertRaises(ContractError):
            _bitstreams(b'\xff\0',1)
        model = b'ETB1\x02\x09\x04\0\x01\xff'
        self.assertEqual(9,_model(model,4))  # outer structure, not Huff weight semantics
        for raw,stream in ((model+b'\0',4),(model,1),(model[:-1],4)):
            with self.assertRaises(ContractError):
                _model(raw,stream)

    def test_runtime_claim_requires_the_actual_entry_and_argument(self):
        row = {'implementation':'upstream-original','cpu_backend':'runtime-bmi2','dynamic_bmi2_compiled':True,
               'cpu_bmi2_available':True,'streams':4,'effective_table_log':11,'table_encode_calls':[0,0],
               'completed_decode_calls':[[0,0],[0,0],[0,2]]}
        self.assertEqual({'bmi2_arg_0':0,'bmi2_arg_1':2},_calls(row,(True,True),2,2,4,11)['ETB1_4X_usingDTable'])
        for bad in ([[0,0],[0,2],[0,0]],[[0,0],[0,0],[2,0]],[[0,0],[0,0],[0,3]]):
            changed = deepcopy(row)
            changed['completed_decode_calls'] = bad
            with self.assertRaisesRegex(ContractError,'entry or count'):
                _calls(changed,(True,True),2,2,4,11)
