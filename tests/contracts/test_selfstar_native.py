from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.assets import ContractError
from tsbench.planner.selfstar import BITLEN, HEADER, MAGIC, plan_selfstar, retained_paths, schema_bytes
from tsbench.qualification.selfstar import _progress
from tsbench.qualification.selfstar_wire import leading_bits, read_frame, read_record


class SelfstarNativeTests(unittest.TestCase):
    def test_frozen_exact_block_short_tail_and_paths(self):
        bundle, weather = plan_selfstar(ROOT)
        self.assertEqual(1543*8,len(weather))
        self.assertEqual([1,512,1591,2049]*2+[1543],[r['count'] for r in bundle['objects']])
        self.assertEqual(5,sum(r['ordered'] for r in bundle['objects']))
        self.assertEqual(9,len(bundle['cases']))
        self.assertEqual(22,len(retained_paths(bundle)))

    def test_frame_extents_and_prefixes(self):
        schema = schema_bytes(64,'fixture-1')
        raw = BITLEN.pack(3)+b'\xa0'
        prefix = HEADER.pack(MAGIC,10,1,len(schema),len(raw))+schema
        self.assertEqual([(1,3,b'\xa0')],read_frame(prefix+raw,64,1,schema))
        self.assertEqual(b'\xa0',leading_bits(b'\xb3\x19',3))
        for artifact in (prefix+raw[:-1],prefix+raw+b'\0',prefix+BITLEN.pack(3)+b'\xa1',prefix+BITLEN.pack(0)+b'\x00'):
            with self.assertRaises(ContractError):
                read_frame(artifact,64,1,schema)
        with self.assertRaises(ContractError):
            read_record(BITLEN.pack(0xffffffff)+b'\xff',0,1000,64)

    def test_progress_requires_schedule_and_no_deferred_values(self):
        progress = [dict(count=n,bits=b,deferred_values=0,phase=1) for n,b in [(0,0),(1,4),(8,44),(9,47)]]
        self.assertEqual(47,_progress(progress,[1,7,63,121],9,49,7))
        for field,value in [('count',7),('bits',4),('deferred_values',8),('phase',2)]:
            forged = deepcopy(progress)
            forged[2][field] = value
            with self.assertRaises(ContractError):
                _progress(forged,[1,7,63,121],9,49,7)
        with self.assertRaises(ContractError):
            _progress(progress,[1,7,63,121],9,49,6)
