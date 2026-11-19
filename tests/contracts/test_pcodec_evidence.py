"""Negative cases for the offline pcodec proof verifier."""
from copy import deepcopy
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.assets import ContractError, canonical_bytes  # noqa: E402
from tsbench.planner.pcodec import C_NATIVE, HEADER, MAGIC, SOURCE, identity, page_spans, plan_pcodec  # noqa: E402
from tsbench.qualification.pcodec import _verify_batch, _verify_intmult, _verify_pages, intmult_wire_header  # noqa: E402


class PcodecEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle,_ = plan_pcodec(ROOT)

    def test_intmult_replay_reads_integer_base_from_wire_not_report(self):
        # Real header prefixes from the fixtures; the test does not emulate entropy payload decoding.
        fixtures = [bytes.fromhex(s) for s in (
            '70 63 6f 21 03 00 0b 00 02 04 01 01 ff 07 00 d1 ff 00 00 00 00',
            '70 63 6f 21 03 00 0b 00 02 04 01 01 ff 07 00 00 00',
            '70 63 6f 21 03 00 49 80 04 01 02 00 02 00 11 00 00 00 00 00 00 02 00 00',
        )]
        spec = self.bundle['intmult']
        row = {'entry':'pc_compress_intmult','parameters':spec['parameters'],'frames':[],
               'rejected':[{**x,'status':1,'output_bytes':0,'output_pointer_null':True} for x in spec['rejected']]}
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            for frame,job in zip(fixtures,spec['frames'],strict=True):
                (out/job['frame']).write_bytes(frame)
                base = job['wire_base']
                mode_detail = f'IntMult({job["dtype"].upper()}({base}))' if base is not None else 'Classic'
                row['frames'].append({'case':job['case'],'artifact':identity(frame),'fresh_process':{
                    'restored':job['plain'],'spans':page_spans(job['count'],256)+[0],
                    'state':{'backend':'source-rust-repaired','kind':'standalone','decoded_chunk_headers':[
                        {'backend':'source-rust-repaired','mode':job['wire_mode'],'mode_detail':mode_detail,
                         'delta':0,'delta_detail':'NoOp'}]}}})
            _verify_intmult(spec,row,out)
            for mutate in ('restore','drain','float-status','output-pointer'):
                bad = deepcopy(row)
                if mutate == 'restore':
                    bad['frames'][2]['fresh_process']['restored'] = identity(b'')
                elif mutate == 'drain':
                    bad['frames'][2]['fresh_process']['spans'].pop()
                elif mutate == 'float-status':
                    bad['rejected'][2]['status'] = 0
                else:
                    bad['rejected'][0]['output_pointer_null'] = False
                with self.subTest(mutate=mutate),self.assertRaisesRegex(ContractError,'terminal drain, exact restore or rejected input'):
                    _verify_intmult(spec,bad,out)
            rounded = bytearray(fixtures[2]); rounded[14] ^= 0x10
            self.assertEqual(intmult_wire_header(rounded)['base'],2**53)
            bad = deepcopy(row)
            bad['frames'][2]['artifact'] = identity(rounded)
            (out/spec['frames'][2]['frame']).write_bytes(rounded)
            with self.assertRaisesRegex(ContractError,'exact integer base'):
                _verify_intmult(spec,bad,out)

    def test_intmult_rejects_bad_count_hint_and_truncated_prefix(self):
        wire = bytes.fromhex('70 63 6f 21 03 00 0b 00 02 04 01 01 ff 07 00 d1 ff 00 00 00 00')
        for i,xor,reason in ((8,0x80,'count hint'),(12,1,'chunk count'),(9,1,'wire version'),
                             (15,0x2,'comparison mode'),(20,1,'footer marker')):
            bad = bytearray(wire); bad[i] ^= xor
            with self.subTest(i=i),self.assertRaisesRegex(ContractError,reason):
                intmult_wire_header(bad)
        with self.assertRaisesRegex(ContractError,'truncated pcodec IntMult header'):
            intmult_wire_header(wire[:17]+b'\0')

    def test_batch_frame_magic_count_and_report_are_independent_checks(self):
        spec = self.bundle['batch'][SOURCE][0]
        schema = spec['schema'].encode('ascii')
        payload = b'pco!unit-verifier-only'
        wire = HEADER.pack(MAGIC[SOURCE],10,0,len(schema),len(payload))+schema+payload
        row = {'case':'empty','dtype':'f64','count':0,'input':identity(b''),'frame':identity(wire),
               'payload':identity(payload),'schema':identity(schema),'restored':identity(b''),'restored_schema':identity(schema),
               'encode_entry':'pc_compress','decode_entry':'pc_decompress_bounded','decode_backend':'rust-source',
               'rust_reference_encoded':identity(payload),'rust_reference_decoded':identity(b''),'native_count_limit':None,
               'rejected':dict.fromkeys(('envelope_trailing','payload_trailing','payload_truncated','missing_payload_metadata',
                                        'count_too_large','other_format'),5)}
        with TemporaryDirectory() as tmp:
            out = Path(tmp); file = out/spec['frame']
            file.write_bytes(wire)
            _verify_batch(SOURCE,[spec],[row],out)
            for field in ('rust_reference_encoded','rust_reference_decoded','restored','rejected'):
                with self.subTest(field=field), self.assertRaisesRegex(ContractError,'exact restore or rejection'):
                    _verify_batch(SOURCE,[spec],[{**row,field:None}],out)
            for frame in (MAGIC[C_NATIVE]+wire[8:],wire+b'\0',wire[:12]+b'\x01'+wire[13:]):
                file.write_bytes(frame)
                with self.assertRaisesRegex(ContractError,'frame identity'):
                    _verify_batch(SOURCE,[spec],[{**row,'frame':identity(frame)}],out)
        refused = next(r for r in self.bundle['batch'][C_NATIVE] if r['dtype'] == 'f16')
        with self.assertRaisesRegex(ContractError,'C f16 rejection'):
            _verify_batch(C_NATIVE,[refused],[{'case':refused['case'],'dtype':'f16','native_status':0,'abi_status':1}],None)

    def test_page_geometry_quota_and_ownership_cannot_be_swapped(self):
        spec = self.bundle['page']['native-pages']
        meta, pages = b'meta', [b'page-one',b'page-two']
        sidecar = canonical_bytes({'counts':[513,260],'lengths':list(map(len,pages)),
                                   'dtype':6,'capacity':256,'meta_bytes':len(meta)})
        row = {'meta':identity(meta),'pages':list(map(identity,pages)),'sidecar':identity(sidecar),
               'state':{'backend':'native-c11','auto_policy':'NativeAuto','mode':2,'delta':1},
               'detached':[{'index':i,'spans':spec['pages'][i]['spans'],'restored':spec['pages'][i]['plain']} for i in (1,0)],
               'caller_buffer_overwrite_restore':spec['pages'][0]['plain'],
               'total_bytes_in_probe':len(meta)+len(sidecar)+sum(map(len,pages)),
               'rejected':{'missing_meta':1,'first_page_small_quota':6,'early_next_page':1,'read_capacity_255':1,
                           'after_first_with_second_quota':6,'trailing_at_drain':4,'read_after_error':1,
                           'truncated_page':{'stage':'drain','status':3}}}
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/spec['meta']).write_bytes(meta)
            (out/spec['sidecar']).write_bytes(sidecar)
            for page,data in zip(spec['pages'],pages,strict=True):
                (out/page['page']).write_bytes(data)
            _verify_pages('native-pages',spec,row,out)
            for mutation in ('swapped_pages','per_page_quota','borrowed_buffer','unpaid_meta','false_truncation'):
                bad = deepcopy(row)
                if mutation == 'swapped_pages':
                    bad['detached'].reverse()
                elif mutation == 'per_page_quota':
                    bad['rejected']['after_first_with_second_quota'] = 0
                elif mutation == 'borrowed_buffer':
                    bad['caller_buffer_overwrite_restore'] = None
                elif mutation == 'unpaid_meta':
                    bad['total_bytes_in_probe'] -= len(meta)
                else:
                    bad['rejected']['truncated_page']['status'] = 0
                with self.subTest(mutation=mutation),self.assertRaisesRegex(ContractError,'ownership, byte charge or rejection'):
                    _verify_pages('native-pages',spec,bad,out)
            (out/spec['sidecar']).write_bytes(sidecar.replace(b'513',b'512'))
            with self.assertRaisesRegex(ContractError,'sidecar geometry'):
                _verify_pages('native-pages',spec,row,out)
