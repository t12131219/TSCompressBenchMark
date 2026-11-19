from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.assets import ContractError, content_id
from tsbench.corad_quality import POLICY, assess, calibrate
from tsbench.planner.corad_deployment import NATIVE
from tsbench.planner.corad_inference import METHOD, plan_corad_inference, retained_paths
from tsbench.qualification.corad_inference import HEADER, verify_bounds, verify_corad_inference
from tsbench.runtime import SCHEMA


class CoradInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle, cls.models, cls.original, cls.calibration = plan_corad_inference(ROOT)

    def test_scope_and_shared_retention(self):
        b = self.bundle
        self.assertEqual(9,len(b['cases']))
        self.assertEqual(8,len(set(retained_paths(b))))
        self.assertEqual(1608,b['input']['bytes'])
        gate, = [r for r in b['cases'] if r['check']=='bound_predeclared_before_formal_run']
        self.assertEqual(b['quality_policy']['policy_id'],gate['quality_policy_id'])
        self.assertEqual(2,len({m['configuration_id'] for m in b['models']}))

    def test_quality_is_exact_per_column_not_a_rounded_average(self):
        cols = list(POLICY['units'])
        calibration = [struct.pack('<dd',0,2)]*3
        bounds = calibrate(cols,calibration,POLICY)
        values = [struct.pack('<dd',1,1)]*3
        self.assertEqual('passed',assess(bounds,values,calibration)['decision'])  # both equal limits
        perturbed = [struct.pack('<dd',-2**-53,2),*calibration[1:]]
        failed = assess(bounds,values,perturbed)
        self.assertEqual('quality_rejected',failed['decision'])
        self.assertFalse(failed['columns'][0]['max_abs_passed'] or failed['columns'][0]['rmse_passed'])
        with self.assertRaisesRegex(ContractError,'nonfinite'):
            assess(bounds,values,[struct.pack('<dd',0,float('nan')),*calibration[1:]])

    def test_recompute_rejects_resealed_relaxed_policy_and_calibration_substitution(self):
        b = self.bundle
        policy = b['quality_policy']
        cols = b['input']['columns']
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            path = out/policy['calibration']['path']
            path.write_bytes(self.calibration)
            self.assertEqual(policy['bounds'],verify_bounds(out,policy,cols,b['window']))
            for mutation,error in [('limit','bounds differ'),('partition','disjoint'),('bytes','sample differs')]:
                bad = deepcopy(policy)
                if mutation=='limit': bad['bounds'][0]['max_abs_error_limit']='1e100'
                elif mutation=='partition': bad['calibration']['windows'][0]['partition']='test'
                else: path.write_bytes(bytes([self.calibration[0]^1])+self.calibration[1:])
                bad['policy_id'] = content_id({k:v for k,v in bad.items() if k!='policy_id'})
                with self.subTest(mutation=mutation), self.assertRaisesRegex(ContractError,error):
                    verify_bounds(out,bad,cols,b['window'])

    def test_recompute_rejects_mutated_model_input_metrics_and_refusal(self):
        def sha(raw):
            return sha256(raw).hexdigest()
        b = deepcopy(self.bundle)
        b['quality_policy'] = 'observed_only_no_formal_budget'  # Historical v2 evidence remains replayable.
        spec = next(s for s in b['frames'] if s['case']=='short-tail-only' and s['route']=='c-lars')
        b['frames'] = [spec]
        b['cases'] = [s for s in b['cases'] if s['name']=='c-lars-tail']
        b['bundle_id'] = content_id({k:v for k,v in b.items() if k!='bundle_id'})
        _,schema,model,_ = self.models[0]
        tail = b''.join(v[:24] for v in self.original)
        fields = list(NATIVE.unpack_from(model))
        fields[1], fields[-1] = 3, len(model)+len(tail)
        native = NATIVE.pack(*fields)+model[NATIVE.size:]+tail
        frame = HEADER.pack(b'BMKCRD\x01\0',len(schema),0,len(native))+schema+native
        worker = {'path':'worker','sha256':'1'*64}
        library = {'path':'plugin','sha256':'2'*64}
        native_lib = {'path':'corad','sha256':'3'*64}
        lock = {'schema':SCHEMA,'worker':worker,'plugins':{METHOD:{'library':library,'dependencies':[native_lib],
                                                                 'manifest_id':'4'*64,'options_schema_id':'5'*64}}}
        lock['build_id'] = content_id(lock)
        build = {x['path']:x['sha256'] for x in (worker,library,native_lib)}
        info = dict(backend='corad-c-frozen',mode='batch',threads=1,columns=3,rows=3,tricklet=4,fallback=False,
                    embedded_model_bytes=176,tail_rows=3)
        model_data = list(struct.unpack_from('<22d',model,NATIVE.size))
        row = {k:spec[k] for k in ('path','case','route','deployment_id','encode_configuration_id','decode_configuration_id',
                                    'model_sha256','model_asset_bytes','columns')}
        row.update(schema_sha256=sha(schema),schema_bytes=len(schema),frame_header_bytes=HEADER.size,frame_bytes=len(frame),
                   native_bytes=len(native),frame_sha256=sha(frame),native_sha256=sha(native),logical_bytes=72,
                   source_sha256=sha(tail),restored_sha256=sha(tail),descriptor={'columns':[{'dtype':10,'count':3}]*3},
                   quality_observed=[dict(column=c,max_abs_error=0.,rmse=0.) for c in spec['columns']],
                   sections=dict(rows=3,columns=3,embedded_model_bytes=176,header_bytes=32,tricklet_record_bytes=0,
                                 tail_bytes=72,sparse_records=0,references=0,first_reference=None,
                                 mean=model_data[16::2],scale=model_data[17::2]),config=spec['native_configuration'],
                   encode={**info,'operation':'encode','external_deployment_loaded':True},pinned_decode=None,
                   decode={**info,'operation':'decode','external_deployment_loaded':False})
        doc = dict(schema='bmk.corad-worker-control/2',diagnostic_id='a'*32,config_id=b['config_id'],bundle_id=b['bundle_id'],
                   probe_sha256='6'*64,source_oracle_sha256='7'*64,formal_qualification=False,formal_performance=False,
                   model_quality_gate_evaluated=False,build=lock,deployments=[m['definition'] for m in b['models']],
                   heldout_windows=b['window'],cases=[row],rejections={k:dict(status=s,returncode=3,no_outputs=True,
                     diagnostic=f'plugin status {s}: synthetic test fixture') for k,s in b['rejections'].items()})
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            report = out / b['evidence_path']
            a, original = out/spec['path'], out/b['input']['path']
            sealed = set(retained_paths(b))
            def verify(paths=sealed):
                verify_corad_inference(b,build,'6'*64,out,sealed_paths=paths,source_oracle_sha256='7'*64)
            for mutation, error in ((None,None),('input','frozen window'),('model','embedded model'),('schema','ordered schema'),
                                    ('metric','restore, metrics'),('refusal','expected refusal'),('closure','retention differs')):
                changed, product, values = deepcopy(doc), bytearray(frame), bytearray(b''.join(self.original))
                match mutation:
                    case 'input': values[0] ^= 1
                    case 'model': product[len(schema)+HEADER.size+NATIVE.size] ^= 1
                    case 'schema': product[HEADER.size] ^= 1
                    case 'metric': changed['cases'][0]['quality_observed'][0]['rmse'] = 1.0
                    case 'refusal': changed['rejections']['wrong-expected-model']['no_outputs'] = False
                report.write_text(json.dumps(changed))
                a.write_bytes(product)
                original.write_bytes(values)
                if error:
                    with self.subTest(mutation=mutation), self.assertRaisesRegex(ContractError,error):
                        verify(sealed-{spec['path']} if mutation=='closure' else sealed)
                else:
                    verify()
