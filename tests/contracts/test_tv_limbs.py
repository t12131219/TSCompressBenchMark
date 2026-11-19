import struct
import unittest
import zlib

from tsbench.planner.tv import limb_crc


class LimbOracleTests(unittest.TestCase):
    def test_rows_columns_and_low_to_high_limbs(self):
        a = struct.pack('<QQ', 0x3ff0CDEF012389AB, 0x8000000000000000)
        b = struct.pack('<QQ', 0x7ff8000000000042, 0x0000000000000001)
        row0 = struct.pack('<8H', 0x89AB, 0x0123, 0xCDEF, 0x3ff0, 0x0042, 0, 0, 0x7ff8)
        row1 = struct.pack('<8H', 0, 0, 0, 0x8000, 1, 0, 0, 0)
        self.assertEqual(limb_crc([a,b],2,1),[zlib.crc32(row0),zlib.crc32(row1)])
        self.assertEqual(limb_crc([a,b],2,2),[zlib.crc32(row0+row1)])
        self.assertEqual(limb_crc([b''],0,512),[0])
