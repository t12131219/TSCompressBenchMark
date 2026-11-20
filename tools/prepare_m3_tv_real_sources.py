#!/usr/bin/env python3
"""Freeze projected real-source T/V diagnostics using the standard TV CLI suite."""
import argparse
import csv
import io
from pathlib import Path
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import content_id, digest, load_json, local_file, require
from tsbench.application.smoke import write_new
from tsbench.corpus_ingress import load_full_manifest, read_batches
from tsbench.ingress import sha
from tsbench.planner.tv import load_case, suite_schema_name
from tsbench.contracts import load_contract

BASE = 'configs/suites/dev_tv_source_providers_v3/suite.json'


def projected(root, entry, window, *, value_count=5):
    offset, count, wanted = (window[k] for k in ('start', 'rows', 'value_columns'))
    require(type(offset) is type(count) is int and 0 <= offset and 513 <= count <= 8192 and offset + count <= entry['rows'] and
            len(wanted) == len(set(wanted)) == value_count and all(type(i) is int and 0 <= i < entry['value_count'] for i in wanted) and
            entry['parser']['timestamp'] != 'integer_label', 'invalid civil TV projection window')
    t, vs = bytearray(), [bytearray() for _ in wanted]
    width = entry['value_count']
    for batch in read_batches(root, entry):
        lo, hi = max(offset, batch.start), min(offset + count, batch.start + batch.rows)
        if lo >= hi:
            continue  # Consume the complete iterator so the source digest is verified.
        a, b = lo - batch.start, hi - batch.start
        t.extend(batch.axis[8*a:8*b])
        for column, out in zip(wanted, vs, strict=True):
            for row in range(a, b):
                pos = 8*(row*width + column)
                out.extend(batch.values[pos:pos+8])
    require(all(len(v) == count*8 for v in [t, *vs]), 'incomplete projection window')
    return [bytes(v) for v in [t, *vs]]


def _npy(array):
    out = io.BytesIO()
    np.lib.format.write_array(out, array, version=(1, 0), allow_pickle=False)
    return out.getvalue()


def prepare(root, spec_path, output, *, native_pair=False):
    request_path = local_file(root, spec_path)
    request = load_json(request_path)
    require(request.keys() == {'manifest', 'windows'} and 1 <= len(request['windows']) <= 4, 'unexpected TV projection request')
    manifest = load_full_manifest(root, request['manifest'], parse=False)
    entries = {x['id']: x for x in manifest['datasets']}
    output.mkdir(parents=True, exist_ok=False)
    base = load_json(local_file(root, BASE))
    suite = {**base, 'cases': {}, 'source_groups': {}}
    suite['profiles']['raw-t'] = {'plugin': 'raw-timestamp', 'role': 'timestamp', 'options': {}}
    if native_pair:
        del suite['profiles']['fire-u16-group']
        suite['profiles'].update({'gorilla-tv': {'plugin': 'gorilla-tv', 'role': 'timestamp_value', 'options': {}},
                                  'gorilla-v': {'plugin': 'gorilla-v-derived', 'role': 'value', 'options': {}}})
        suite['methods'] = {'gorilla-tv': {'joint': 'gorilla-tv'},
                            'gorilla-t-gorilla-v': {'timestamp': 'gorilla-t', 'value': 'gorilla-v'},
                            'gorilla-t-alp-f64': {'timestamp': 'gorilla-t', 'value': 'alp-f64'},
                            'raw-t-gorilla-v': {'timestamp': 'raw-t', 'value': 'gorilla-v'}}
    else:
        suite['methods']['raw-t-alp-f64'] = {'timestamp': 'raw-t', 'value': 'alp-f64'}
    provenance = {}
    for group, cfg in request['windows'].items():
        require(group and all(c in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in group), 'invalid TV group name')
        require(cfg.keys() == {'dataset', 'start', 'rows', 'value_columns'} and cfg['dataset'] in entries,
                'unsupported TV projection config')
        entry = entries[cfg['dataset']]
        t, *v = projected(root, entry, cfg, value_count=1 if native_pair else 5)
        rows = cfg['rows']
        source_columns = [entry['columns'][1+i] for i in cfg['value_columns']]
        names = ['timestamp', *(f'v{i}' for i in cfg['value_columns'])]
        spec = {'timestamp': {'name': 'timestamp', 'dtype': 'i64', 'unit': 's',
                             'interpretation': 'source_civil_label_coordinate_not_utc', 'epoch': '1970-01-01 00:00:00', 'timezone': None},
                'values': [{'name': n, 'dtype': 'f64'} for n in names[1:]], 'rows': rows, 'row_order': 'preserve',
                'layout': 'dense_column_little_endian', 'nullable': False, 'nan_policy': 'preserve_bits'}
        text_base = {'encoding': 'utf-8', 'header': True, 'bad_rows': 'error', 'timestamp_encoding': 'signed_decimal_integer',
                     'decimal': '.', 'missing_tokens': ['', 'NA'], 'f64_encoding': 'decimal_or_explicit_ieee_hex'}
        records = [names, *[[str(struct.unpack_from('<q', t, 8*r)[0]),
                            *(f'bits:{struct.unpack_from("<Q", c, 8*r)[0]:016x}' for c in v)] for r in range(rows)]]
        buf = io.StringIO(newline='')
        csv.writer(buf, lineterminator='\n', quoting=csv.QUOTE_ALL).writerows(records)
        txt = ''.join('|'.join(record) + '\n' for record in records)
        table = np.column_stack([np.frombuffer(c, dtype='<u8') for c in v]).view('<f8')
        formats = {
            'csv': ({**text_base, 'delimiter': ',', 'quote': '"', 'escape': 'double_quote'}, [('table', 'csv', buf.getvalue().encode())]),
            'txt': ({**text_base, 'mode': 'delimited', 'delimiter': '|', 'comments': 'reject', 'empty_lines': 'reject'}, [('table', 'txt', txt.encode())]),
            'npy': ({'axis0': 'rows', 'axis1': 'value_columns', 'allow_pickle': False, 'mmap': False,
                     'timestamp_dtype': '<i8', 'value_dtype': '<f8', 'value_order': 'C'},
                    [('timestamp', 't.npy', _npy(np.frombuffer(t, dtype='<i8'))), ('values', 'v.npy', _npy(table))])}
        suite['source_groups'][group] = list(formats)
        provenance[group] = {'original_file': entry['file'], 'column_mapping': dict(zip(names[1:], source_columns, strict=True)),
                             'row_range': [cfg['start'], cfg['start']+rows],
                             'projected_column_sha256': list(map(sha, (t, *v))), 'manifests': {}}
        for fmt, (opts, parts) in formats.items():
            files = []
            for role, suffix, data in parts:
                dest = output / f'{group}.{suffix}'
                dest.write_bytes(data)
                files.append({'role': role, 'path': dest.relative_to(root).as_posix(), 'bytes': len(data), 'sha256': sha(data)})
            name, dest = f'{group}-{fmt}', output / f'{group}-{fmt}.json'
            write_new(dest, {'schema': 'bmk.typed-tv-source/1', 'plugin': fmt, 'object': spec, 'options': opts, 'files': files})
            case = {'ingress': {'manifest': dest.relative_to(root).as_posix(), 'group': group}}
            suite['cases'][name] = case
            provenance[group]['manifests'][fmt] = {'path': case['ingress']['manifest'], 'sha256': digest(dest)}
    cases = list(suite['cases'])
    if native_pair:
        suite['comparisons'] = {
            'native-vs-composed': {'task': 'whole_object', 'control': None,
                                   'methods': ['gorilla-tv', 'gorilla-t-gorilla-v'], 'cases': cases},
            'fixed-t': {'task': 'shared_t_controlled', 'control': 'fixed_timestamp_route',
                        'methods': ['gorilla-t-gorilla-v', 'gorilla-t-alp-f64'], 'cases': cases},
            'fixed-value': {'task': 'whole_object', 'control': 'fixed_value_route',
                            'methods': ['gorilla-t-gorilla-v', 'raw-t-gorilla-v'], 'cases': cases},
        }
    else:
        suite['comparisons']['fixed-t-direct-vs-limbs']['cases'] = cases
        suite['comparisons']['fixed-value'] = {'task': 'whole_object', 'control': 'fixed_value_route',
                                              'methods': ['gorilla-t-alp-f64', 'raw-t-alp-f64'], 'cases': cases}
    load_contract(root, suite_schema_name(suite)).validate(suite, 'real-source TV switch suite')
    for case in suite['cases'].values():
        fact, _ = load_case(root, suite, case)
        require(fact['lineage']['source_column_sha256'] == provenance[case['ingress']['group']]['projected_column_sha256'],
                'provider projection does not match real-source bytes')
    write_new(output/'suite.json', suite)
    body = {'schema': 'bmk.m3-tv-real-source-projections/1', 'request_sha256': digest(request_path),
            'manifest_sha256': digest(local_file(root, request['manifest'])), 'suite_sha256': digest(output/'suite.json'),
            'scope': 'selected_row_and_column_projections_not_full_files', 'groups': provenance}
    write_new(output/'projections.json', {**body, 'projection_id': content_id(body)})
    return output/'suite.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--native-pair', action='store_true', help='require single-V windows and schedule native-vs-composed controls')
    args = parser.parse_args()
    target = (ROOT / args.out).resolve()
    require(target.is_relative_to(ROOT), 'projection output must be in the TSBench workspace')
    print(prepare(ROOT, args.sources, target, native_pair=args.native_pair))
