from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from tsbench.api import check_full_corpus
from tsbench.assets import ContractError, load_json
from tsbench.corpus_ingress import (BATCH_ROWS, MANIFEST, axis_contract, fingerprint, load_full_manifest, read_batches)
from tsbench.planner.full_corpus_windows import bind_full_column, read_full_column

ROOT = Path(__file__).resolve().parents[2]


class FullCorpusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'schemas').mkdir()
        shutil.copyfile(ROOT / 'schemas/full-corpus.schema.json', self.root / 'schemas/full-corpus.schema.json')

    def manifest(self, raw, *, opts=None, values=('a', 'b'), size=3):
        path = self.root / 'table.csv'
        path.write_bytes(raw)
        parser = {'format': 'utf8_delimited_physical_rows_v1', 'separator': ',', 'decimal': '.',
                  'timestamp': 'integer_label', 'missing': 'reject_empty_preserve_finite', **(opts or {})}
        entry = {'id': 'fixture', 'source_cluster': 'fixture-source',
                 'file': {'path': path.name, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()},
                 'parser': parser, 'axis': axis_contract(parser['timestamp']), 'columns': ['time', *values],
                 'values_dtype': '<f8', 'rows': size, 'value_count': len(values),
                 'partitions': [{'name': name, 'start': a, 'end': b}
                                for name, a, b in zip(('train', 'development', 'test'), (0, 1, 2), (1, 2, size))]}
        return entry

    def write(self, entry, scope='fixture-scope'):
        (self.root / 'input.json').write_text(json.dumps({'schema': 'bmk.full-corpus/1', 'scope': scope,
                                                         'datasets': [entry]}), encoding='utf-8')

    def test_canonical_hashes_order_sign_and_split_crossing_batch(self):
        n = BATCH_ROWS + 1
        raw = b'time,a,b\r\n' + b'\r\n'.join(f'{i},-0.0,{i}.125'.encode() for i in range(n))
        entry = self.manifest(raw, size=n)
        emitted = list(read_batches(self.root, entry))
        self.assertEqual([(b.start, b.rows) for b in emitted], [(0, BATCH_ROWS), (BATCH_ROWS, 1)])
        entry.update(fingerprint(self.root, entry))
        expected = b''.join(struct.pack('<dd', -0.0, i+.125) for i in range(n))
        self.assertEqual(entry['canonical']['values_sha256'], sha256(expected).hexdigest())
        self.assertEqual(entry['partitions'][2]['canonical']['values_sha256'], sha256(expected[32:]).hexdigest())
        self.write(entry)
        result = check_full_corpus(self.root, 'input.json', parse=True)
        self.assertEqual(result['rows'], n)
        self.assertEqual(result['logical_value_bytes'], len(expected))
        self.assertFalse(result['stage_accepted'])

    def test_source_sentinel_spans_merge_across_batch_boundaries_and_are_audited(self):
        rows = BATCH_ROWS + 3
        raw = b'time,a,b\n' + b''.join(f'{i},{-9999 if BATCH_ROWS-1 <= i <= BATCH_ROWS else i},'
                                      f'{-9999 if i == BATCH_ROWS else i}\n'.encode() for i in range(rows))
        entry = self.manifest(raw, size=rows, opts={'missing': 'retain_source_minus_9999'})
        entry.update(fingerprint(self.root, entry))
        self.write(entry)
        found = {}
        load_full_manifest(self.root, 'input.json', parse=True, sentinel_index=found)
        self.assertEqual(found, {'fixture': {0: [[BATCH_ROWS-1, BATCH_ROWS+1]], 1: [[BATCH_ROWS, BATCH_ROWS+1]]}})
        with self.assertRaisesRegex(ContractError, 'require a full canonical audit'):
            load_full_manifest(self.root, 'input.json', sentinel_index={})
        entry['retained_sentinel_values'] -= 1
        self.write(entry)
        found = {}
        with self.assertRaisesRegex(ContractError, 'more sentinels than locked'):
            load_full_manifest(self.root, 'input.json', parse=True, sentinel_index=found)
        self.assertEqual(found, {})

    def test_decimal_comma_and_civil_label_no_timezone_conversion(self):
        entry = self.manifest(b'time;a\n"1970-01-01 00:00:01";-0,0\n"1970-01-01 00:00:01";-9999\n'
                              b'"1969-12-31 23:59:59";5,25\n', values=('a',),
                              opts={'separator': ';', 'decimal': ',', 'timestamp': 'civil_iso_seconds',
                                    'missing': 'retain_source_minus_9999'})
        stats = fingerprint(self.root, entry)
        self.assertEqual(stats['axis_observations'], {'first': 1, 'last': -1, 'min': -1, 'max': 1,
                                                      'adjacent_equal': 1, 'decreases': 1})
        self.assertEqual(stats['retained_sentinel_values'], 1)

    def test_reject_incompatible_syntax_and_width(self):
        for row, reason in ((b'1,,2', 'missing'), (b'1,nan,2', 'nonfinite'),
                            (b'1,1e-999,2', 'underflow'), (b'1,1e999,2', 'overflow'),
                            (b'1,1', 'row width'), (b'1970-01-01,1,2', 'timestamp'),
                            (b'1,"1,2', 'unexpected end'), (b'9223372036854775808,1,2', 'i64')):
            with self.subTest(row=row):
                entry = self.manifest(b'time,a,b\n' + row + b'\n2,1,2\n3,1,2\n')
                with self.assertRaisesRegex(ContractError, reason):
                    fingerprint(self.root, entry)

    def test_reject_hash_scope_and_metadata_drift(self):
        entry = self.manifest(b'time,a,b\n1,0,2\n2,1,2\n3,1,2\n')
        entry.update(fingerprint(self.root, entry))
        for key, val, reason in (('value_count', 1, 'shape'), ('canonical', {**entry['canonical'], 'object_id': '0'*64},
                                                              'object identity'), ('partitions', [entry['partitions'][0],
                    {**entry['partitions'][1], 'start': 0}, entry['partitions'][2]], 'partition'),
                                 ('parser', {**entry['parser'], 'format': 'arbitrary'}, 'schema')):
            with self.subTest(key=key):
                self.write({**entry, key: val})
                with self.assertRaisesRegex(ContractError, reason):
                    load_full_manifest(self.root, 'input.json')
        edited = deepcopy(entry)
        edited['axis_observations']['adjacent_equal'] = 1
        self.write(edited)
        with self.assertRaisesRegex(ContractError, 'canonical assets differ'):
            load_full_manifest(self.root, 'input.json', parse=True)
        self.write(entry)
        (self.root / entry['file']['path']).write_bytes(b'time,a,b\n1,7,2\n2,1,2\n3,1,2\n')
        with self.assertRaisesRegex(ContractError, 'SHA-256'):
            load_full_manifest(self.root, 'input.json', parse=True)

    def test_first_batch_denominator_cannot_be_narrowed(self):
        shutil.copytree(ROOT / 'datasets/manifests', self.root / 'datasets/manifests')
        data = load_json(ROOT / MANIFEST)
        data['datasets'].pop()
        (self.root / MANIFEST).write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ContractError, 'exact 23 original'):
            load_full_manifest(self.root)

    def test_cli_and_python_audit_are_the_same_for_declared_input(self):
        entry = self.manifest(b'time,a,b\n1,0,2\n2,1,2\n3,1,2\n')
        entry.update(fingerprint(self.root, entry))
        self.write(entry)
        raw = subprocess.check_output([sys.executable, '-B', str(ROOT / 'bmk'), '--root', str(self.root),
                                       'check-full-corpus', '--manifest', 'input.json', '--parse'], cwd=ROOT)
        self.assertEqual(json.loads(raw), check_full_corpus(self.root, 'input.json', parse=True))

    def test_select_heldout_value_projection_and_replay_it(self):
        entry = self.manifest(b'time,a,b\n1,100,200\n2,101,201\n3,102,-0.0\n4,103,202\n', size=4)
        entry.update(fingerprint(self.root, entry))
        self.write(entry)
        request = {'dataset': 'fixture', 'offset': 0, 'count': 2, 'column': 'b'}
        ref, raw = bind_full_column(self.root, 'input.json', **request)
        self.assertEqual(raw, struct.pack('<dd', -0.0, 202))
        self.assertEqual(ref['absolute_row_range'], [2, 4])
        self.assertEqual(read_full_column(self.root, ref), raw)
        alt, values = bind_full_column(self.root, 'input.json', **{**request, 'column': 'a'})
        self.assertNotEqual(ref['input_id'], alt['input_id'])
        self.assertEqual(values, struct.pack('<dd', 102, 103))
        with self.assertRaisesRegex(ContractError, 'not a declared binary64 value column'):
            bind_full_column(self.root, 'input.json', **{**request, 'column': 'time'})
        with self.assertRaisesRegex(ContractError, 'crosses the frozen test partition'):
            bind_full_column(self.root, 'input.json', **{**request, 'count': 3})
        with self.assertRaisesRegex(ContractError, 'no longer matches'):
            read_full_column(self.root, {**ref, 'raw_sha256': alt['raw_sha256']})
