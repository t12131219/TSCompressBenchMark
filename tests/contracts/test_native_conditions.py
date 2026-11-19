from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import ContractError, content_id, digest
from tsbench.planner.native_conditions import CONDITIONS, freeze_conditions
from tsbench.qualification.native_conditions import OBSERVED, resolve_conditions


def identified(doc, key):
    doc[key] = content_id({k:v for k,v in doc.items() if k != key})
    return doc


def work(workers):
    return {'worker_threads':workers,'jobs':workers*4}


def evidence():
    frame = {'bytes':512,'sha256':'a'*64}
    avx2 = {'request':'falp-avx2','dispatch':'falp-avx2','state':'restored_bit_exact',
            'decimal_vectors_in_wire':1,'native_decimal_kernel_vectors':1,
            'native_execution_confirmation':'measured_counter'}
    lzbench = {'observations':[
        {'group':'zstd-workers','observed':{'input':frame,'observed':{
            n:{'encode_jobs':work(int(n)), 'decode_jobs':work(0)} for n in ('0','2')}}},
        {'group':'xz-workers','observed':{'input':frame,'observed':{
            n:{'encode_jobs':work(int(n)), 'frame':frame, 'same_multiblock_frame_decode':{
                'source_frame':frame,'decode_jobs':work(int(n))}} for n in ('1','2')},
            'synchronous':{'encode':{'mt_worker_hooks':work(0)},'decode':{'shared':{
                'source_frame':frame,'source_frame_path':'workers-2.xz','mt_worker_hooks':work(0)}}}}},
    ]}
    zfp = {'openmp':{'profiles':[
        {'policy':p,'caller_tid':3,'reversible_bits_verified':True,'serial_decode_reported':True,
         'payload':frame,'encode_block_work':enc,'decode_block_work':[{'tid':3,'blocks':6}]}
        for p,enc in [('serial',[{'tid':3,'blocks':6}]),('1',[{'tid':3,'blocks':6}]),
                      ('2',[{'tid':3,'blocks':3},{'tid':5,'blocks':3}])]]}}
    args = {k:{'bmi2_arg_1':i} for i,k in enumerate(
        ('FEC1_4X_hufOnly_wksp','ETB1_1X_usingDTable','ETB1_4X_usingDTable'),3)}
    huff0 = {'fec1_cases':[{'direct_backend':{'dynamic_bmi2_compiled':True,'cpu_bmi2_available':True},
                           'decode_entries':args}], 'etb1_profiles':[]}
    alp = {'backend_conditions':{'64':{
        'falp-avx2':{'built_for_width':True,'available':True},
        'falp-avx512bw':{'built_for_width':True,'available':False}}},
        'cases':[{'case':'mixed-decimal-raw','width':64,'envelope_sha256':frame['sha256'],'backends':[avx2]}]}
    return {'alp':alp,'zfp':zfp,'lzbench':lzbench,'huff0':huff0}


class NativeConditionsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.run_dir = Path(tmp.name)
        self.docs = evidence()
        bundles = {k:identified({'test':k,'evidence_path':f'{k}/report.json'},'bundle_id') for k in self.docs}
        routes, groups = [], []
        for (n, route, predicate), (check, k, _, _) in CONDITIONS.items():
            routes.append({'selection':n,'route':route,'conditional':[{'predicate':predicate,'require':check}]})
            if not any(g['selection']==n and g['operation']['route']==route for g in groups):
                groups.append({'selection':n,'operation':{'route':route},'test':k})
        self.condition_plan = freeze_conditions(routes,bundles)
        self.plan = {'bindings':{**bundles,'native_conditional_plan':self.condition_plan},'groups':groups,
                     'slots':[{'test':k,'slot_id':k,'evidence':[bundles[k]['evidence_path']]} for k in bundles]}
        self.statuses = dict.fromkeys(bundles,'passed')

    def resolve(self, *, write=True):
        if write:
            for k,doc in self.docs.items():
                path = self.run_dir / 'slots' / k / k / 'report.json'
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(doc),encoding='utf-8')
        doc = resolve_conditions(self.run_dir,self.plan,self.statuses)
        self.assertEqual('same_development_run_only',doc['scope'])
        self.assertTrue(all(row['formal_qualification']=='not_run' for row in doc['obligations']))
        return {plan['selector']:row for plan,row in zip(self.condition_plan['obligations'],doc['obligations'],strict=True)}

    def test_six_same_run_decisions_and_evidence(self):
        rows = self.resolve()
        self.assertEqual({'alp-avx2':OBSERVED,'alp-avx512bw':'pending_supported_runtime','zfp-openmp':OBSERVED,
                          'zstd-workers':OBSERVED,'xz-workers':OBSERVED,'huff0-bmi2':'missing_same_run_control'},
                         {k:row['state'] for k,row in rows.items()})
        for row in rows.values():
            ref = row['evidence']
            self.assertEqual(digest(self.run_dir / ref['path']),ref['sha256'])
        self.assertEqual([0,1,2],[lane['decode']['worker_threads'] for lane in rows['xz-workers']['observed']['lanes']])
        self.assertEqual([3,4,5],list(rows['huff0-bmi2']['observed']['bmi2_calls'].values()))

    def test_failed_probes_do_not_use_evidence_or_infer_hardware(self):
        for state in ('failed','skipped','cancelled','timeout','dependency_failed','crash','evidence_failed'):
            with self.subTest(state=state):
                self.statuses = dict.fromkeys(self.statuses,state)
                for row in self.resolve(write=False).values():
                    self.assertEqual(('not_observed',state,None,{}),
                                     (row['state'],row['reason'],row['evidence'],row['observed']))

    def test_missing_avx512_build_is_distinct_from_runtime(self):
        avx512 = self.docs['alp']['backend_conditions']['64']['falp-avx512bw']
        avx512['built_for_width'] = False
        self.assertEqual('pending_supported_build',self.resolve()['alp-avx512bw']['state'])

    def test_avx512_requires_explicit_and_auto_dispatch_but_no_counter(self):
        self.docs['alp']['backend_conditions']['64']['falp-avx512bw']['available'] = True
        backends = self.docs['alp']['cases'][0]['backends']
        backends.extend({**backends[0],'request':r,'dispatch':'falp-avx512bw','native_decimal_kernel_vectors':None,
                         'native_execution_confirmation':'dispatch_only_no_native_counter'}
                        for r in ('falp-avx512bw','falp-auto'))
        self.assertEqual(OBSERVED,self.resolve()['alp-avx512bw']['state'])
        backends[-1]['dispatch'] = 'falp-avx2'
        with self.assertRaisesRegex(ContractError,'requested backend'):
            self.resolve()
        backends[-1]['dispatch'] = 'falp-avx512bw'
        backends[1]['native_decimal_kernel_vectors'] = 1
        with self.assertRaisesRegex(ContractError,'invent an execution counter'):
            self.resolve()

    def test_avx2_dispatch_without_real_decimal_work_is_rejected(self):
        self.docs['alp']['cases'][0]['backends'][0]['native_decimal_kernel_vectors'] = 0
        with self.assertRaisesRegex(ContractError,'native decimal work missing'):
            self.resolve()

    def test_xz_only_compares_worker_counts_on_one_decode_artifact(self):
        xz = self.docs['lzbench']['observations'][1]['observed']
        xz['observed']['1']['same_multiblock_frame_decode']['source_frame'] = work(1)
        with self.assertRaisesRegex(ContractError,'decoded a different artifact'):
            self.resolve()
        del xz['synchronous']
        self.assertEqual('missing_same_run_control',self.resolve()['xz-workers']['state'])

    def test_wrong_obligation_or_binding_rejected_even_with_refreshed_digests(self):
        original = deepcopy(self.plan)
        for mutation in ('scope','denominator','bundle_id','predicate','criteria','evidence_path','slot','operation'):
            with self.subTest(mutation=mutation):
                self.plan = deepcopy(original)
                self.condition_plan = cp = self.plan['bindings']['native_conditional_plan']
                row = cp['obligations'][0]
                if mutation == 'scope':
                    cp['runtime_scope'] = 'formal'
                elif mutation == 'denominator':
                    cp['obligations'].pop()
                elif mutation == 'slot':
                    self.plan['slots'][0]['evidence'].clear()
                elif mutation == 'operation':
                    self.plan['groups'][0]['test'] = 'huff0'
                else:
                    row[mutation] = 'not-the-planned-value'
                identified(row,'obligation_id')
                identified(cp,'conditional_plan_id')
                with self.assertRaisesRegex(ContractError,'native conditional'):
                    self.resolve(write=False)
