from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.native import PRIMARY_NOT_PASSED, _check_probe_dependency, _execute
from tsbench.assets import ContractError, canonical_bytes, content_id, digest
from tsbench.planner.huff0 import DECODE_API, ENVELOPE, ref
from tsbench.planner.huff0_portable import BINARIES, DRIVER, RECIPE, REPORT, TEST, _build_recipe
from tsbench.qualification.huff0_portable import comparison_binding, verify_portable_control


def define(doc,key):
    return {**doc,key:content_id(doc)}


def backend(slot,n,compiled,streams=0,log=0):
    calls = [[0,0] for _ in DECODE_API]
    calls[slot][int(compiled)] = n
    return dict(cpu_backend='runtime-bmi2' if compiled else 'portable',implementation='upstream-original',
                dynamic_bmi2_compiled=compiled,cpu_bmi2_available=True,completed_decode_calls=calls,
                streams=streams,effective_table_log=log,table_encode_calls=[0,0])


class Huff0PortableTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run = Path(tmp.name)
        a,b = 'a'*64,'b'*64
        self.source = self.run/'slots'/a
        self.out = self.run/'slots'/b
        self.source.mkdir(parents=True)
        self.out.mkdir()
        self.primary_name = 'huff0-control.json'
        self.bundle = {'bundle_id':'d'*64,'test':'primary','evidence_path':self.primary_name,'fec1':[{}],'etb1':[{},{}]}
        self.primary = {'fec1_cases':[],'etb1_profiles':[]}
        self.rows = []
        plain = '0'*64
        payload = b'actual-fec'
        wire = bytes(ENVELOPE.size)+payload
        (self.source/'batch').write_bytes(wire)
        fec = ref('batch',wire)
        self.primary['fec1_cases'].append(dict(name='batch',artifact=fec,fec_bytes=len(payload),schema_bytes=0,
             fec_sha256=ref('',payload)['sha256'],direct_restored_sha256=plain,direct_backend=backend(0,3,True)))
        self.rows.append(dict(kind='fec1',case='batch',artifacts=[fec],model=None,restored_sha256=[plain],native=backend(0,3,False)))
        for slot,streams in [(1,1),(2,4)]:
            art,model = ref(f'block-{slot}',b'block'),ref(f'model-{slot}',bytes([streams]))
            (self.source/art['path']).write_bytes(b'block')
            (self.source/model['path']).write_bytes(bytes([streams]))
            art_row = dict(artifact=art,restored_sha256=plain)
            self.primary['etb1_profiles'].append(dict(profile='table',streams=streams,model=model,blocks=[art_row],
                         direct_backend=backend(slot,4,True,streams,11)))
            self.rows.append(dict(kind='etb1',case=f'table-{streams}x',artifacts=[art],model=model,
                             restored_sha256=[plain],native=backend(slot,4,False,streams,11)))
        self.primary_path = self.source/self.primary_name
        self.primary_path.write_bytes(canonical_bytes(self.primary))
        inputs = {f'project:{DRIVER}':{'root':'project','path':DRIVER,'sha256':'e'*64},
                  **{f'huff0_portable:{p}':{'root':'huff0_portable','path':p,'sha256':'1'*64} for p in BINARIES}}
        cmd = [{'python':True},{'literal':'-I'},{'literal':'-B'},*({'asset':k} for k in inputs),
               {'input_slot':a},{'output':REPORT}]
        self.slot = {'test':TEST,'slot_id':b,'evidence':[REPORT],'command':cmd,'requires_slot':a}
        self.control = define({'schema':'bmk.huff0-portable-control-plan/1','test':TEST,'evidence_path':REPORT,
                'bundle_id':self.bundle['bundle_id'],'primary_slot_id':a,'control_slot_id':b,'archive_sha256':'f'*64,
                'normalized_build_recipe':{f'{k}/{f}':'2'*64 for k in RECIPE for f in ('flags.make','link.txt')},
                'comparison':'same_run_primary_fec1_payload_etb1_blocks_and_models'},'control_id')
        self.doc = {'bindings':{'huff0':self.bundle,'command_inputs':inputs,'huff0_portable_control':self.control},
                    'slots':[{'test':'primary','slot_id':a},self.slot],
                    'groups':[{'selection':29,'archive_sha256':'f'*64}]}
        self.report = {'schema':'bmk.huff0-portable-decode/1','primary_report_sha256':digest(self.primary_path),
                       'bundle_id':self.bundle['bundle_id'],'driver_sha256':'e'*64,
                       'binaries':{Path(p).name:'1'*64 for p in BINARIES},'formal_qualification':False,'rows':self.rows}

    def verify(self,report):
        (self.out/REPORT).write_bytes(canonical_bytes(report))
        return verify_portable_control(self.doc,self.run,comparison_binding(self.doc))

    def test_same_bytes_separate_build_and_real_portable_argument(self):
        result = self.verify(self.report)
        self.assertEqual(result['portable_calls'],result['dynamic_bmi2_calls'])
        self.assertEqual([3,4,4],list(result['portable_calls'].values()))

    def test_stale_build_model_frame_or_restore_rejected(self):
        for key in ('primary_report_sha256','binaries','model','artifacts','restored_sha256','native'):
            with self.subTest(key=key):
                forged = deepcopy(self.report)
                target = forged if key in ('primary_report_sha256','binaries') else forged['rows'][1]
                target[key] = 'forged' if key!='native' else backend(1,4,True,1,11)
                with self.assertRaisesRegex(ContractError,'Huff0 portable|Huff0 native'):
                    self.verify(forged)

    def test_build_recipe_requires_matching_macros_and_compares_rest(self):
        p = self.run/'test-build'
        p.mkdir()
        (p/'CMakeCache.txt').write_text(f'CMAKE_HOME_DIRECTORY:INTERNAL={ROOT}\nENTROPY_DYNAMIC_BMI2:BOOL=OFF\n')
        for rel,keys in RECIPE.items():
            d = p/rel
            d.mkdir(parents=True)
            (d/'flags.make').write_text('FLAGS = '+' '.join(f'-D{k}=0' for k in keys)+'\n')
            (d/'link.txt').write_text('cc -shared\n')
        a = _build_recipe(p,ROOT,0)
        directory = p/next(iter(RECIPE))
        (directory/'link.txt').write_text('cc -shared -static\n')
        self.assertNotEqual(a,_build_recipe(p,ROOT,0))
        (directory/'flags.make').write_text('FLAGS = -DDYNAMIC_BMI2=1\n')
        with self.assertRaisesRegex(ContractError,'requested DYNAMIC_BMI2=0'):
            _build_recipe(p,ROOT,0)

    def test_changed_command_and_unpassed_dependency_never_launch(self):
        self.slot['command'][-2]['input_slot'] = 'c'*64
        with self.assertRaisesRegex(ContractError,'does not bind primary evidence'):
            comparison_binding(self.doc)
        # Exercise admission before any subprocess, with intentionally invalid argv.
        test_slot = {**self.slot,'slot_id':'c'*64}
        row = _execute(self.doc,test_slot,{},self.run,lambda:False,{self.slot['requires_slot']:'failed'},self.control)
        self.assertEqual((None,None,'dependency_failed',[]),
                         (row['returncode'],row['session_id'],row['status'],row['artifacts']))

    def test_primary_not_passed_and_failed_portable_process_are_distinct(self):
        prior = self.slot['requires_slot']
        row = dict(reason='missing executable at launch',status='dependency_failed',returncode=None,
                   session_id=None,artifacts=[{'path':'probe.stderr'}])
        _check_probe_dependency(self.slot,row,{prior:'passed'})
        with self.assertRaisesRegex(ContractError,'inconsistent terminal state'):
            _check_probe_dependency(self.slot,row,{prior:'failed'})
        blocked = {**row,'reason':PRIMARY_NOT_PASSED,'artifacts':[]}
        _check_probe_dependency(self.slot,blocked,{prior:'failed'})
        with self.assertRaisesRegex(ContractError,'dependency did pass'):
            _check_probe_dependency(self.slot,blocked,{prior:'passed'})
