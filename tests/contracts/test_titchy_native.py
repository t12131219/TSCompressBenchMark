"""Offline known-answer checks for the Titchy batch/packet wire readers."""
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError
from tsbench.planner.titchy_native import BATCH_POLICY
from tsbench.qualification.titchy_wire import INDEX, SPLIT, TCHY, TSC1, TSTR, TSTR_RECORD, decode_tchy, decode_tstr


class TitchyNativeTests(unittest.TestCase):
    def test_batch_dictionary_deviation_and_padding(self):
        # One base with four u8 values. A two-bit deviation replaces bit zero
        # of the last two lanes. Only the first three lanes are logical output.
        header = TCHY.pack(b'TCHY', 2, 8, 4, 0, 1000, 250000, 2**64-1, 3, 1, 1)
        offset = len(header) + INDEX.size + 4
        idx = INDEX.pack(0, 1, offset, 9)
        bases = b'\x02\x04\x06\x08'
        record = SPLIT.pack(0, 2, 1, 1) + b'\x80'
        wire = header+idx+bases+record
        raw, splits = decode_tchy(wire, 8, 3, BATCH_POLICY)
        self.assertEqual(raw, b'\x02\x04\x07')
        self.assertEqual(splits, [{'first_chunk': 0, 'chunks': 1, 'offset': offset, 'bytes': 9}])
        for frame, reason in ((wire+b'\0', 'trailing data'), (wire[:-1]+b'\x81', 'padding'),
                              (header+INDEX.pack(0,1,offset+1,9)+bases+record, 'split index'),
                              (wire[:-9]+SPLIT.pack(1,1,1,1)+b'\x80', 'dictionary reference')):
            with self.subTest(reason=reason), self.assertRaisesRegex(ContractError, reason):
                decode_tchy(frame, 8, 3, BATCH_POLICY)

    def test_packet_state_config_and_true_tail(self):
        cfg = TSC1.pack(b'TSC1', 64, 4, 1000, 0, 7, .25, 72)
        spec = {'chunks_per_packet': 7, 'max_active_bytes': 72, 'count': 7}
        hdr = TSTR.pack(b'TSTR\1', 64, 4, 1000, 7, 2)
        bases = struct.pack('>4Q', 1, 2, 3, 0)
        # Introduce the dictionary and (lid=0, ld=0). The second packet has
        # neither; decoder must carry both state objects from packet one.
        first = b'\x81\0\0'+bases
        second = b'\0'
        stream = hdr+TSTR_RECORD.pack(1,len(first))+first+TSTR_RECORD.pack(1,1)+second
        raw, rows = decode_tstr(stream, cfg, spec, BATCH_POLICY)
        self.assertEqual(raw, struct.pack('<7Q', 1,2,3,0,1,2,3))
        self.assertEqual([(r['new_bases'],r['parameters']) for r in rows], [(1,True),(0,False)])
        malformed = (
            (stream[:-1], cfg, 'truncated'),
            (stream+b'\0', cfg, 'trailing'),
            (stream, cfg[:-1]+b'\1', 'parameters'),
            (stream[:TSTR.size+TSTR_RECORD.size]+b'\x01'+stream[TSTR.size+TSTR_RECORD.size+1:], cfg,
             'missing Titchy packet parameters'),
            (stream.replace(bases,struct.pack('>4Q', 1,2,3,4)), cfg, 'nonzero'),
        )
        for payload, metadata, reason in malformed:
            with self.subTest(reason=reason), self.assertRaisesRegex(ContractError, reason):
                decode_tstr(payload, metadata, spec, BATCH_POLICY)
