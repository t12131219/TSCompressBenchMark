from binascii import crc32
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tsbench.assets import ContractError, load_json
from tsbench.planner.pbepla_progressive import CONFIG, WORD_MAGIC, plan_pbepla_progressive, retained_paths, schema_bytes
from tsbench.qualification.pbepla_progressive import MAGIC, OUTER, PBEP, _verify_bad_layers, _verify_progressive, _verify_replay, quality

ROOT = Path(__file__).resolve().parents[2]


class PbeplaProgressiveTests(unittest.TestCase):
    def test_plan_freezes_input_closure_eps_and_retention(self):
        bundle, cfg, source = plan_pbepla_progressive(ROOT)
        self.assertEqual((7, 29, 40, 33), (len(bundle['inputs']), sum(len(i['frame_paths']) for i in bundle['inputs']),
                                         len(set(retained_paths(bundle))), len(bundle['cases'])))
        policy = bundle['failure_policy']
        self.assertEqual([2097152,2097168], [s['count']*len(s['requested_eps']) for s in policy['boundary']])
        self.assertEqual(['changed','no-rewind','sink-fail','value-limit'], policy['fault_modes'])
        weather = next(s for s in bundle['inputs'] if s['name'] == 'weather')
        self.assertEqual((1029, [16, 4, 1], sha256(source['weather']).hexdigest()),
                         (weather['count'], weather['requested_eps'], weather['input_sha256']))
        bad = deepcopy(cfg)
        bad['window_eps'] = [16, 16, 1]
        with patch('tsbench.planner.pbepla_progressive.load_json', return_value=bad):
            with self.assertRaisesRegex(ContractError, 'eps order'):
                plan_pbepla_progressive(ROOT)
        bad = load_json(ROOT / CONFIG)
        bad['alternate_geometry'][0]['geometry']['external_transform'] = True
        with patch('tsbench.planner.pbepla_progressive.load_json', return_value=bad):
            with self.assertRaisesRegex(ContractError, 'violates pbepla-cases schema'):
                plan_pbepla_progressive(ROOT)

    def test_error_oracle_uses_exact_binary64_and_rejects_nonfinite(self):
        raw = struct.pack('<d', 1.0)
        restored = struct.pack('<d', -2**-53)
        error, row = quality(raw, restored)
        self.assertEqual(1.0, row['max_abs_error'])
        self.assertEqual(1 + Fraction(1, 2**53), error)
        self.assertGreater(error, 1.0)  # Rounded observed error alone would falsely pass.
        with self.assertRaisesRegex(ContractError, 'nonfinite'):
            quality(raw, struct.pack('<d', float('nan')))
        with self.assertRaisesRegex(ContractError, 'count differs'):
            quality(raw, b'')

    def test_negative_layer_transcript_requires_input_digest_and_empty_outputs(self):
        plan, _, _ = plan_pbepla_progressive(ROOT)
        spec = next(s for s in plan['inputs'] if s['name']=='empty')
        schema = schema_bytes('empty')
        head = PBEP.pack(b'PBEP',1,1,1,1,0,64,-1,1) + struct.pack('<dBQI',1.,2,0,0)
        native = head + struct.pack('<I',crc32(head))
        def outer(body):
            return OUTER.pack(MAGIC,10,0,len(schema),len(body))+schema+body
        row = {'native_rejects':dict.fromkeys(('zero_layers','absent_layer'),
                  'pbepla_rr: requested layers exceed the stored layers'),
               'worker_rejects':{key:{'sha256':sha256(outer(blob)).hexdigest(),'exit_status':3,'plugin_status':5,'outputs_absent':True}
                   for key,blob in [('truncated_native',native[:-1]),('zero_stored_layer',native[:7]+b'\0'+native[8:])]}}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out/spec['frame_paths'][0]).write_bytes(outer(native))
            _verify_bad_layers(spec,row,out,131072)
            for field,value in [('sha256',sha256(native).hexdigest()),('outputs_absent',False),('plugin_status',7)]:
                corrupt = deepcopy(row)
                corrupt['worker_rejects']['zero_stored_layer'][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ContractError,'corrupt frame transcript'):
                    _verify_bad_layers(spec,corrupt,out,131072)

    def test_recompute_quality_bytes_and_replay_from_bounded_evidence(self):
        plan, _, source = plan_pbepla_progressive(ROOT)
        spec = next(s for s in plan['inputs'] if s['name'] == 'empty')
        name = spec['name']
        schema = schema_bytes(name)
        # Structurally valid empty prefix; this unit tests the verifier, not the decoder.
        head = PBEP.pack(b'PBEP', 1, 1, 1, 1, 0, 64, -1, 1) + struct.pack('<dBQI', 1., 2, 0, 0)
        native = head + struct.pack('<I', crc32(head))
        frame = OUTER.pack(MAGIC, 10, 0, len(schema), len(native)) + schema + native
        q = quality(source[name], b'')[1]
        wire = dict(count=0, declared=1, stored=1, delay=64, flags=1, eps=[1.0], resolutions=[2], bits=[0],
                    layer_bytes=[0], header_bytes=61, payload_bytes=0)
        row = {'name': name, 'input_id': spec['input_id'], 'input_sha256': spec['input_sha256'],
               'requested_eps': [1], 'wire': wire, 'native_sha256': sha256(native).hexdigest(),
               'layers': [{'layer': 1, 'effective_eps': 1.0, 'prefix_sha256': sha256(native).hexdigest(),
                           'prefix_header_bytes': 61, 'incremental_payload_bytes': 0, 'cumulative_payload_bytes': 0,
                           'detached_prefix_bytes': 61, 'worker_frame_bytes': len(frame), 'frame_sha256': sha256(frame).hexdigest(),
                           'decode_info': dict(backend='tba-pbepla-rr-port', threads=1, fallback=False, operation='decode',
                                               mode='batch', layers_stored=1, native_header_bytes=61, native_payload_bytes=0), **q}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / spec['word_path']).write_bytes(WORD_MAGIC)
            path = out / spec['frame_paths'][0]
            path.write_bytes(frame)
            batch = _verify_progressive(spec, row, out, len(frame))
            for field, value in [('incremental_payload_bytes', 1), ('exact_max_abs_error', '1/2')]:
                bad = deepcopy(row)
                bad['layers'][0][field] = value
                with self.subTest(field=field), self.assertRaisesRegex(ContractError, 'prefix report differs'):
                    _verify_progressive(spec, bad, out, len(frame))
            path.write_bytes(frame[:-1] + bytes([frame[-1] ^ 1]))
            with self.assertRaisesRegex(ContractError, 'CRC differ'):
                _verify_progressive(spec, row, out, len(frame))
        replay = dict(name=name, scope=plan['replay_policy']['scope'], wire=wire, same_bytes_as_batch=True,
                      payload_sha256=sha256(native).hexdigest(), quality=[{'layer': 1, **q}], io=dict(
                          native_passes=1, rewind_calls=1, eof_passes=1, first_sink_after_pass=1, result=0,
                          native_numerical_retries=0, native_value_count=0, source_bytes_read=0, sink_bytes=len(native),
                          native_buffer_slots=0, temp_bytes_read=0, temp_bytes_written=0, temp_peak_live_bytes=0,
                          temp_seeks=0, temp_files_created=0, temp_files_closed=0, sink_calls=1))
        _verify_replay(spec, replay, plan['replay_policy'], batch)
        replay['io']['first_sink_after_pass'] = 0
        with self.assertRaisesRegex(ContractError, 'replay accounting differs'):
            _verify_replay(spec, replay, plan['replay_policy'], batch)
