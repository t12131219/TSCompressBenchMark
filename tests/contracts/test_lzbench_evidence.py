"""Mutation tests for lzbench wire, dependency and native work evidence."""
from copy import deepcopy
from hashlib import sha256
import lzma
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.assets import ContractError  # noqa: E402
from tsbench.planner.lzbench import DIR, dictionary_sample, plan_lzbench  # noqa: E402
from tsbench.qualification.lzbench import (  # noqa: E402
    _verify_dictionary, _verify_workers, _xz_restore, verify_spans, xz_advertise_dictionary, xz_block_sizes, xz_blocks,
    zstd_frame,
)


def identity(blob):
    return {'bytes':len(blob),'sha256':sha256(blob).hexdigest()}


def feature(codec, length, encoded, level):
    return {'codec':codec,'input_bytes':length,'encoded_bytes':encoded,'level':level,
            'mode':'frame','native_stream':True,'repeats':1}


def jobs(count, threads):
    return {'jobs':count,'worker_threads':threads,'caller_jobs':0}


class LzbenchEvidenceTests(unittest.TestCase):
    def test_zstd_standard_empty_frame_and_fail_closed_trailer(self):
        frame = bytes.fromhex('28 b5 2f fd 20 00 01 00 00')
        self.assertEqual(zstd_frame(frame),dict(content_size=0,checksum=False,dictionary_id=0,window=0))
        for bad in (frame + frame, frame[:-1], frame[:6]+bytes([7,0,0]), frame[:4]+bytes([0x28])+frame[5:]):
            with self.subTest(bad=bad), self.assertRaises(ContractError):
                zstd_frame(bad)

    def test_partial_span_retry_and_terminal_drain(self):
        good = [[3,1,0,0,0],[2,2,2,0,0],[2,2,1,1,0],[0,0,2,1,1]]
        self.assertEqual(verify_spans(good,5,5,3,2),(1,2,True))
        for index,column,value in ((0,2,3),(1,0,3),(1,4,1),(2,3,0),(3,4,0),(3,2,1)):
            bad = [row.copy() for row in good]; bad[index][column] = value
            with self.subTest(index=index,column=column), self.assertRaises(ContractError):
                verify_spans(bad,5,5,3,2)

    def test_dictionary_replay_binds_dependency_id_charge_and_rejection(self):
        spec = plan_lzbench(ROOT)['dictionary']
        original = b''.join(dictionary_sample('held-out',i) for i in range(31))
        dict_id = 42
        # Synthetic wire headers isolate the verifier; native restoration is tested by CTest.
        dictionary = bytes.fromhex('37 a4 30 ec') + dict_id.to_bytes(4,'little') + b'fixture'
        frame = (bytes.fromhex('28 b5 2f fd a3') + dict_id.to_bytes(4,'little') + len(original).to_bytes(4,'little') +
                 (len(original)*8+1).to_bytes(3,'little') + original)
        stats = {**feature('zstd',len(original),len(frame),3),'encode_jobs':jobs(0,0),'decode_jobs':jobs(0,0)}
        row = {'training_samples':spec['training_samples'],'sample_set_identity':{'train':'train','held_out':'held-out'},
               'training_capacity_bytes':spec['capacity'],'dictionary':{**identity(dictionary),'id':dict_id},
               'held_out':identity(original),'encoded':identity(frame),'fresh_process_restored':identity(original),
               'trainer_rejected':{str(k):{'error':'dictionary training size','exit_status':2} for k in spec['bad_capacities']},
               'serialized_bytes_including_dictionary':len(dictionary)+len(frame),'negative_dictionary_id':dict_id^1,
               'roundtrip':{**stats,'effective_parameters':spec['parameters']},
               'fresh_process_decode':{**stats,'effective_parameters':{}},
               'rejected':{k:{'error':'Dictionary mismatch','exit_status':2} for k in ('missing','wrong_id')}}
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/DIR).mkdir()
            (out/DIR/spec['dictionary_path']).write_bytes(dictionary)
            (out/DIR/spec['frame_path']).write_bytes(frame)
            _verify_dictionary(spec,row,out)
            for field, value in (('serialized_bytes_including_dictionary',len(frame)),('rejected',{}),
                                 ('trainer_rejected',{}),('fresh_process_restored',identity(b''))):
                with self.subTest(field=field), self.assertRaisesRegex(ContractError,'dependency charge or restore'):
                    _verify_dictionary(spec,{**row,field:value},out)
            overlap = deepcopy(spec)
            overlap['held_out_samples'][0] = spec['training_samples'][0]
            with self.assertRaisesRegex(ContractError,'partition closure'):
                _verify_dictionary(overlap,row,out)
            (out/DIR/spec['dictionary_path']).write_bytes(dictionary[:4]+b'\x40'+dictionary[5:])
            with self.assertRaisesRegex(ContractError,'frame dependency'):
                _verify_dictionary(spec,row,out)

    def test_xz_index_options_and_shared_decoder_artifact(self):
        original = b'an XZ verifier fixture'*99
        wire = lzma.compress(original,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,preset=1)
        self.assertEqual(xz_block_sizes(wire),[len(original)])
        crc = bytearray(wire)
        crc[-13] ^= 1
        with self.assertRaisesRegex(ContractError,'index indicator or CRC'):
            xz_block_sizes(crc)
        spec = deepcopy(plan_lzbench(ROOT)['workers']['xz'])
        control = spec.pop('synchronous')  # The previously sealed v4 lane shape must still replay.
        spec['input'] = identity(original)
        params = {**spec['base'],'depth':8,'dict_size':1<<20,'filter0':0,'filter1':0,'filter2':0,
                  'lc':3,'lp':0,'lzma_mode':1,'match_finder':4,'nice_len':128,'pb':2,'preset':1,'timeout_ms':0}
        row = {'input':spec['input'],'profile_parameter':'threads','configured_base':spec['base'],'observed':{}}
        stats = feature('xz',len(original),len(wire),1)
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/DIR).mkdir()
            for n in spec['settings']:
                frame_path = spec['frame_paths'][str(n)]
                (out/DIR/frame_path).write_bytes(wire)
                row['observed'][str(n)] = {**stats,'frame_path':frame_path,'frame':identity(wire),
                    'fresh_process_restored':identity(original),'encode_jobs':jobs(n,n),'decode_jobs':jobs(n,n),
                    'effective_parameters':{**params,'threads':n,'encoder_memory_bytes':10**6*n},
                    'same_multiblock_frame_decode':{**stats,'source_frame':identity(wire),
                        'fresh_process_restored':identity(original),'effective_parameters':{},
                        'encode_jobs':jobs(0,0),'decode_jobs':jobs(n,n)}}
            _verify_workers('xz',spec,row,out)
            for field, change, message in (
                ('same_multiblock_frame_decode',{'source_frame':identity(wire[:-1])},'did not share one frame'),
                ('effective_parameters',{'filter0':1},'changed unmatched options'),
                ('encode_jobs',{'worker_threads':0},'worker trace identity'),
            ):
                bad = deepcopy(row)
                bad['observed']['1'][field].update(change)
                with self.subTest(field=field), self.assertRaisesRegex(ContractError,message):
                    _verify_workers('xz',spec,bad,out)
            bad = deepcopy(row)
            bad['observed']['1']['decode_jobs'] = []
            with self.assertRaisesRegex(ContractError,'malformed XZ decoder'):
                _verify_workers('xz',spec,bad,out)
            v5 = {**spec,'synchronous':control}
            frame_path = control['frame_path']
            (out/DIR/frame_path).write_bytes(wire)
            restored, frame, zero = identity(original), identity(wire), jobs(0,0)
            row['synchronous'] = {'frame_path':frame_path,'frame':frame,'encode':{
                'entry':'lzma_block_encoder','input_bytes':len(original),'frame_bytes':len(wire),
                'raw_encoder_memory_bytes':9015815,'fallback_blocks':0,'inner_input_span_bytes':16384,
                'block_input_bytes':[len(original)],'parameters':{
                    **spec['base'],'preset':1,'filter_id':0x21,'dict_size':1<<20},'mt_worker_hooks':zero},'decode':{
                role:{'entry':'lzma_stream_decoder','input_bytes':len(wire),'restored_bytes':len(original),
                      'memory_limit':spec['base']['memory_limit'],'mt_worker_hooks':zero,'source_frame_path':path,
                      'source_frame':frame,'fresh_process_restored':restored}
                for role,path in (('own',frame_path),('shared',spec['frame_paths']['2']))}}
            _verify_workers('xz',v5,row,out)
            for path, field, value in (
                (('encode',),'mt_worker_hooks',jobs(1,1)),
                (('encode',),'block_input_bytes',[len(original)-1,1]),
                (('encode','parameters'),'dict_size',1<<23),
                (('decode','shared'),'source_frame_path',frame_path), # equal bytes, wrong common artifact
                (('decode','shared'),'mt_worker_hooks',jobs(1,1)),
                (('decode','own'),'fresh_process_restored',identity(original[::-1])),
            ):
                bad = deepcopy(row)
                target = bad['synchronous']
                for p in path:
                    target = target[p]
                target[field] = value
                with self.subTest(path=path,field=field), self.assertRaisesRegex(ContractError,'XZ synchronous'):
                    _verify_workers('xz',v5,bad,out)

    def test_xz_delta_header_and_crc64_payload_reject_mutations(self):
        plain = b'time series\x00'*37
        wire = lzma.compress(plain,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,filters=[
            {'id':lzma.FILTER_DELTA,'dist':4},{'id':lzma.FILTER_LZMA2,'dict_size':1<<20},
        ])
        block, = xz_blocks(wire)
        self.assertEqual(block['filters'],[(3,b'\x03'),(0x21,b'\x10')])
        _xz_restore(wire,identity(plain),lzma.CHECK_CRC64,64<<20)
        bad_header = bytearray(wire)
        bad_header[block['property_offsets'][0]] ^= 1
        with self.assertRaisesRegex(ContractError,'block header CRC'):
            xz_blocks(bad_header)
        index_size = (1+int.from_bytes(wire[-8:-4],'little'))*4
        bad_crc = bytearray(wire)
        bad_crc[-13-index_size] ^= 1
        with self.assertRaisesRegex(ContractError,'invalid retained XZ stream'):
            _xz_restore(bad_crc,identity(plain),lzma.CHECK_CRC64,64<<20)
        with self.assertRaisesRegex(ContractError,'one LZMA2 property'):
            xz_advertise_dictionary(wire,33)

    def test_xz_guard_preserves_block_extent_and_hits_decoder_budget(self):
        wire = lzma.compress(b'\0',format=lzma.FORMAT_XZ,check=lzma.CHECK_NONE,preset=6)
        guard = xz_advertise_dictionary(wire,33)
        self.assertEqual(xz_block_sizes(guard),[1])
        self.assertEqual(xz_blocks(guard)[0]['filters'],[(0x21,b'\x21')])
        self.assertLessEqual(sum(a != b for a,b in zip(wire,guard,strict=True)),5)
        for cap in (64<<20,256<<20):
            with self.subTest(cap=cap),self.assertRaisesRegex(ContractError,'Memory usage limit exceeded'):
                _xz_restore(guard,identity(b'\0'),lzma.CHECK_NONE,cap)
