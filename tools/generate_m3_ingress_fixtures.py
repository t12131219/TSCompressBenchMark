#!/usr/bin/env python3
"""Reproduce the cross-format fixtures; --check does not modify the checkout.

NumPy is a generator-only dependency and an independent NPY writer. The
runtime loader uses no NumPy, pickle or network.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import struct
import sys
import math

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.assets import load_json, require
from tsbench.ingress import sha
from tsbench.planner.tv import exact_ticks, load_case

OLD = 'configs/suites/dev_tv_limb_comparison_v1/suite.json'
NEW = 'configs/suites/dev_tv_cross_format_v2/suite.json'
FOLDER = 'datasets/fixtures/m3-ingress'
GROUPS = {'traffic-tail':'traffic-five-value-tail','exact-bits-tail':'five-value-edge-bits'}


def build_files():
    old = load_json(ROOT/OLD)
    suite = {k:v for k,v in old.items() if k not in ('corpus','corpus_id')}
    suite['schema'], suite['cases'] = 'bmk.dev-tv-suite/2',{}
    outputs = {}
    text = {'encoding':'utf-8','header':True,'bad_rows':'error','timestamp_encoding':'signed_decimal_integer',
            'decimal':'.','missing_tokens':['','NA'],'f64_encoding':'decimal_or_explicit_ieee_hex'}
    def js(value):
        return (json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode()
    for group,old_name in GROUPS.items():
        fact,(converted,*values) = load_case(ROOT,old,old['cases'][old_name])
        real = group=='traffic-tail'
        rows = fact['rows']
        unit = 's' if real else 'ms'
        ticks = exact_ticks(converted,'ms',unit)
        spec = {'timestamp':{'name':'timestamp','dtype':'i64','unit':unit,
                             'interpretation':'source_civil_label_coordinate_not_utc' if real else 'synthetic_integer_coordinate',
                             'epoch':'1970-01-01 00:00:00' if real else None,'timezone':None},
                'values':[{'name':col['name'],'dtype':'f64'} for col in fact['schema']['columns'][1:]],
                'rows':rows,'row_order':'preserve','layout':'dense_column_little_endian','nullable':False,
                'nan_policy':'preserve_bits'}
        labels = ['timestamp',*(c['name'] for c in spec['values'])]
        def decimal_or_bits(col,r):
            f, = struct.unpack_from('<d',col,r*8)
            if math.isfinite(f):
                return repr(f)
            q, = struct.unpack_from('<Q',col,r*8)
            return f'bits:{q:016x}'
        records = [labels]+[[str(struct.unpack_from('<q',ticks,r*8)[0]),*(decimal_or_bits(v,r) for v in values)] for r in range(rows)]
        csv_file = io.StringIO(newline='')
        csv.writer(csv_file,lineterminator='\r\n',quoting=csv.QUOTE_ALL).writerows(records)
        if real:
            txt = ''.join('|'.join(r)+'\n' for r in records)
            txt_opts = {'mode':'delimited','delimiter':'|'}
        else:
            widths = [24]*len(labels)
            txt = ''.join(''.join(s.ljust(w) for s,w in zip(r,widths,strict=True))+'\n' for r in records)
            txt_opts = {'mode':'fixed_width','widths':widths}
        t = np.frombuffer(ticks,dtype='<i8')
        v = np.column_stack([np.frombuffer(col,dtype='<u8') for col in values]).view('<f8')
        if not real:
            t = t.byteswap().view('>i8')
            v = np.asfortranarray(v.byteswap().view('>f8'))
        def npy(array):
            out=io.BytesIO()
            np.lib.format.write_array(out,array,version=(1,0) if real else (2,0),allow_pickle=False)
            return out.getvalue()
        modes = {
            'csv': ({**text,'delimiter':',','quote':'"','escape':'double_quote'}, [('table','csv',csv_file.getvalue().encode())]),
            'txt': ({**text,'comments':'reject','empty_lines':'reject',**txt_opts}, [('table','txt',txt.encode())]),
            'npy': ({'axis0':'rows','axis1':'value_columns','allow_pickle':False,'mmap':False,
                     'timestamp_dtype':t.dtype.str,'value_dtype':v.dtype.str,'value_order':'C' if real else 'F'},
                    [('timestamp','t.npy',npy(t)),('values','v.npy',npy(v))])}
        for plugin,(options,files) in modes.items():
            refs = []
            for role,suffix,data in files:
                path = f'{FOLDER}/{group}.{suffix}'
                outputs[path] = data
                refs.append({'role':role,'path':path,'bytes':len(data),'sha256':sha(data)})
            name = f'{group}-{plugin}'
            manifest = f'{FOLDER}/{name}.json'
            outputs[manifest] = js({'schema':'bmk.typed-tv-source/1','plugin':plugin,'object':spec,'files':refs,'options':options})
            suite['cases'][name] = {'ingress':{'manifest':manifest,'group':group}}
    for cmp in suite['comparisons'].values():
        cmp['cases'] = list(suite['cases'])
    outputs[NEW] = js(suite)
    return outputs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    check = parser.parse_args().check
    for path,data in build_files().items():
        target=ROOT/path
        if check:
            require(target.read_bytes()==data,f'fixture differs: {path}')
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)


if __name__=='__main__':
    main()
