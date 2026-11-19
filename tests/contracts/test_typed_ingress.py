from copy import deepcopy
from pathlib import Path
import json
import shutil
import struct
import tempfile
import unittest

from tsbench.assets import ContractError, load_json
from tsbench.ingress import load_typed_source, sha
from tsbench.planner.tv import ingress_groups, load_case

ROOT = Path(__file__).resolve().parents[2]
SUITE = 'configs/suites/dev_tv_cross_format_v2/suite.json'
FIXTURE = 'datasets/fixtures/m3-ingress'


class TypedIngressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='typed-ingress-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for d in ('schemas','plugins/loaders',FIXTURE):
            shutil.copytree(ROOT/d,self.root/d)
        for f in ('catalog/source-loaders.json','src/tsbench/ingress.py'):
            dst = self.root/f
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/f,dst)
        self.manifest = 'source.json'

    def doc(self, fmt, group='exact-bits-tail'):
        return load_json(self.root/f'{FIXTURE}/{group}-{fmt}.json')

    def load(self, doc):
        (self.root/self.manifest).write_text(json.dumps(doc),encoding='utf-8')
        return load_typed_source(self.root,self.manifest)

    def replace(self, doc, index, data):
        path = f'replacement-{index}.bin'
        (self.root/path).write_bytes(data)
        doc['files'][index].update(path=path,bytes=len(data),sha256=sha(data))

    def test_exact_three_format_types_bits_and_path_independence(self):
        result = [self.load(self.doc(f)) for f in ('csv','npy','txt')]
        ref, cols = result[0]
        self.assertEqual([len(c) for c in cols],[515*8]*6)
        self.assertEqual(struct.unpack_from('<qqq',cols[0]),(-2**63,2**63-1,-1))
        self.assertEqual(struct.unpack_from('<4Q',cols[1]),(0,0x8000000000000000,1,0x7ff8000000000019))
        self.assertEqual(len({f['source_file_hash'] for f,_ in result}),3)
        self.assertEqual(len({f['ingestion_id'] for f,_ in result}),3)
        for facts,data in result:
            self.assertEqual(data,cols)
            self.assertEqual(facts['canonical_dataset_hash'],ref['canonical_dataset_hash'])
            self.assertEqual(facts['source_group_id'],ref['source_group_id'])
        doc = self.doc('csv')
        self.replace(doc,0,(self.root/doc['files'][0]['path']).read_bytes())
        moved,_ = self.load(doc)
        self.assertNotEqual(ref['manifest_id'],moved['manifest_id'])
        for key in ['source_file_hash','ingestion_id','canonical_dataset_hash','source_group_id']:
            self.assertEqual(ref[key],moved[key])

    def test_text_rejects_inexact_ambiguous_missing_and_malformed_input(self):
        doc = self.doc('csv')
        doc['object']['rows'] = 1
        doc['object']['values'] = doc['object']['values'][:1]
        bad = [(b'1.0,1','invalid exact i64'),(b'00123,1','invalid exact i64'),(b'9223372036854775808,0','outside i64'),
               (b'1,NaN','invalid f64'),(b'1,NA','missing field'),(b'1,','missing field'),(b'1,1e-600','underflow'),
               (b'1,1e600','nonfinite'),(b'1,"3','quoting'),(b'1,0,8','width'),(b'1,\xff','invalid declared UTF-8'),
               (b'1,0\n\n2,2','row count'),(b'1,\x001','binary data')]
        for line,reason in bad:
            with self.subTest(line=line):
                self.replace(doc,0,b'timestamp,v1\n'+line+b'\n')
                with self.assertRaisesRegex(ContractError,reason): self.load(doc)
        self.replace(doc,0,b'timestamp,v1\n1,2\n')
        doc['options']['delimiter']='|'
        with self.assertRaisesRegex(ContractError,'violates'): self.load(doc)
        txt = self.doc('txt')
        txt['options']['widths'][0] += 1
        with self.assertRaisesRegex(ContractError,'fixed-width record'): self.load(txt)

    def test_explicit_decimal_and_negative_zero(self):
        doc = self.doc('csv')
        doc['object']['rows'] = 2
        doc['object']['values'] = doc['object']['values'][:1]
        doc['options'].update(decimal=',',delimiter=';')
        self.replace(doc,0,b'timestamp;v1\n-1;1,5\n-1;-0,0\n')
        _,data = self.load(doc)
        self.assertEqual(data,[struct.pack('<qq',-1,-1),struct.pack('<dQ',1.5,0x8000000000000000)])

    def test_npy_requires_heterogeneous_roles_and_exact_header_and_payload(self):
        for mutate,reason in [
            (lambda d:d['files'].pop(0),'ordered timestamp'),
            (lambda d:d['files'].reverse(),'ordered timestamp'),
            (lambda d:d['options'].update(allow_pickle=True),'violates'),
            (lambda d:d['options'].update(mmap=True),'violates'),
            (lambda d:d['options'].update(value_dtype='<f8'),'dtype, shape or order'),
            (lambda d:d['options'].update(value_order='C'),'dtype, shape or order'),
            (lambda d:d['object'].update(rows=514),'dtype, shape or order'),
            (lambda d:d['object']['values'].pop(),'dtype, shape or order'),
        ]:
            with self.subTest(reason=reason):
                d=self.doc('npy'); mutate(d)
                with self.assertRaisesRegex(ContractError,reason): self.load(d)
        for substitute,reason in [
            (lambda b:b[:-1],'truncated or trailing'),(lambda b:b+b'1','truncated or trailing'),
            (lambda b:b.replace(b"'>f8'",b"'|O8'",1),'object/structured/complex'),
            (lambda b:b.replace(b"'>f8'",b"'>c8'",1),'object/structured/complex')]:
            with self.subTest(reason=reason):
                d=self.doc('npy'); self.replace(d,1,substitute((self.root/d['files'][1]['path']).read_bytes()))
                with self.assertRaisesRegex(ContractError,reason): self.load(d)

    def test_rejects_tampered_asset_and_non_exact_units(self):
        d=self.doc('csv'); d['files'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ContractError,'source asset bytes changed'): self.load(d)
        d=self.doc('csv'); d['object']['timestamp']['unit']='ns'
        (self.root/self.manifest).write_text(json.dumps(d),encoding='utf-8')
        suite=load_json(ROOT/SUITE)
        with self.assertRaisesRegex(ContractError,'non-exact or overflowing'):
            load_case(self.root,suite,{'ingress':{'manifest':self.manifest,'group':'edge'}})

    def test_source_groups_reject_semantic_mismatch_and_missing_format(self):
        suite=load_json(ROOT/SUITE)
        cases={name:load_case(self.root,suite,src)[0] for name,src in suite['cases'].items()}
        self.assertEqual(len(ingress_groups(suite,cases)),2)
        edited=deepcopy(suite)
        name='exact-bits-tail-npy'
        # Declared values remain parseable, but source semantics change legitimately.
        d=self.doc('npy')
        d['object']['timestamp'].update(interpretation='unix_epoch_integer',epoch='1970-01-01 00:00:00',timezone='UTC')
        (self.root/self.manifest).write_text(json.dumps(d),encoding='utf-8')
        edited['cases'][name]['ingress']['manifest']=self.manifest
        edited_cases={**cases,name:load_case(self.root,edited,edited['cases'][name])[0]}
        with self.assertRaisesRegex(ContractError,'canonical mismatch'): ingress_groups(edited,edited_cases)
        with self.assertRaisesRegex(ContractError,'three distinct'):
            ingress_groups({**suite,'cases':{k:v for k,v in suite['cases'].items() if k!=name}},
                           {k:v for k,v in cases.items() if k!=name})
