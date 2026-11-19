"""Boundary tests for the complete-object TV planner, wire oracle and restore scope."""
import struct
import unittest
import zlib

from tsbench.application.tv import ENTRY, HEADER, MAGIC, _slot_dependencies, inspect_bundle
from tsbench.assets import ContractError, canonical_bytes
from tsbench.planner.tv import exact_ticks


class TVCompositionTests(unittest.TestCase):
    def test_exact_time_conversion_never_truncates_or_wraps(self):
        original = struct.pack('<4q',-5,0,1,2**40)
        converted = exact_ticks(original,'s','ms')
        self.assertEqual(struct.unpack('<4q',converted),(-5000,0,1000,(2**40)*1000))
        self.assertEqual(exact_ticks(converted,'ms','s'),original)
        for data,s,t in [(struct.pack('<q',-1001),'ms','s'),(struct.pack('<q',2**63-1),'s','ms'),(b'a','s','ms')]:
            with self.subTest((s,t)),self.assertRaises(ContractError):
                exact_ticks(data,s,t)

    def test_bundle_directory_covers_one_time_axis_and_rejects_wrong_slot(self):
        schema = {'time_axis':'ms','columns':['t','x','y']}
        raw = canonical_bytes(schema)
        identity = '4'*64
        records = [(row,1,col,1) for row in range(2) for col in range(3)]
        header = HEADER.pack(MAGIC,2,3,1,len(records),len(raw),zlib.crc32(raw),identity.encode())
        at = len(header)+len(records)*ENTRY.size+len(raw)
        payload = bytes(range(6))
        entries = [ENTRY.pack(*item,at+i,1,zlib.crc32(payload[i:i+1]),0) for i,item in enumerate(records)]
        frame = header+b''.join(entries)+raw+payload
        case = {'rows':2,'column_sha256':['t','x','y'],'schema':schema}
        method = {'layout':'separate','method_id':identity}
        layout = inspect_bundle(frame,case,method,1)
        self.assertEqual(len(layout['streams']),6)
        self.assertEqual(sum(s['first_column']==0 for s in layout['streams']),2)
        self.assertEqual(layout['bundle_bytes'],sum(layout[k] for k in ('container_bytes','schema_bytes','stream_bytes')))
        for altered in (frame[:-1],frame+b'\0',frame[:HEADER.size+8]+b'\x01'+frame[HEADER.size+9:]):
            with self.assertRaises(ContractError):
                inspect_bundle(altered,case,method,1)

    def test_restore_mounts_only_selected_dso_and_its_transitive_dependencies(self):
        spec = {'worker':'bin/worker','loader':'lib/loader','plugins':{'t':'lib/t.so','v':'lib/v.so','tv':'lib/joint.so'},
                'files':{k:{'needed':deps} for k,deps in {
                    'bin/worker':['libc'], 'lib/loader':[], 'lib/libc':[], 'lib/t.so':[], 'lib/v.so':['native-v.so'],
                    'lib/native-v.so':['libc'],'lib/joint.so':['native-tv.so'],'lib/native-tv.so':[]}.items()}}
        build = {'plugins':{'t':{'dependencies':[]},'v':{'dependencies':[{'path':'b/native-v.so'}]}}}
        paths = _slot_dependencies(spec,build,{'t','v'})
        self.assertEqual(set(paths),{'bin/worker','lib/loader','lib/libc','lib/t.so','lib/v.so','lib/native-v.so'})
        spec['files'].pop('lib/native-v.so')
        with self.assertRaisesRegex(ContractError,'undeclared dependency'):
            _slot_dependencies(spec,build,{'t','v'})
