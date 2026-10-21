"""Freeze and run representative forecasting CSVs, retaining complete files.

The ordinary tsbench runner performs admission, native timing and verification.
This orchestration never changes codec code, drops columns or truncates rows.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmark/src'))
sys.path.insert(0, str(ROOT / 'benchmark/tools'))
from generate_all_core_experiments import text as toml_text
from tsbench.registry import Registry
from tsbench.records import file_hash, write_json
from tsbench.config import load


def family(name):
    return name.split('_dataset')[0] if '_dataset' in name else re.sub(r'_\d+$', '', name)


def freeze(destination):
    destination = Path(destination).resolve()
    if (destination/'design.json').exists():
        raise FileExistsError('design is already frozen; use run to continue it, or prepare a new destination')
    inventory = json.loads((destination / 'inventory.json').read_text())
    grouped = defaultdict(list)
    for row in inventory['files']:
        grouped[family(row['id'])].append(row)
    selected = []
    for name, members in sorted(grouped.items()):
        item = dict(sorted(members, key=lambda x: (x['values'], x['id']))[(len(members)-1)//2])
        item.update(family=name, family_file_count=len(members))
        selected.append(item)
    registry = Registry(ROOT)
    specs = registry.list(include_reference=False)
    keys = {spec.key for spec in specs}
    assert len(keys) == 42 and not keys.intersection({'lzss-raw', 'lzss-dipperstein-c'})
    data_dir = destination / 'typed'
    data_dir.mkdir(exist_ok=True)
    documents = []
    inputs = []
    record_inputs = []
    # Group small objects; separate larger complete files so completed results
    # and an interrupted long experiment can be independently reviewed/resumed.
    batches = [('small', [r for r in selected if r['raw_bytes'] <= 131072])]
    batches += [(r['id'], [r]) for r in selected if r['raw_bytes'] > 131072]
    run_root = ROOT / 'runs' / destination.name

    def add(group, datasets, method_keys, fidelity='bitwise', kind='values', large=False):
        if not datasets or not method_keys:
            return
        for life, short in [('prepared','prepared'), ('fresh_request','fresh')]:
            methods = []
            for key in sorted(method_keys):
                method = {'id':key, 'codec':key}
                if fidelity == 'bounded_abs': method['params'] = {'error_bound':'0.01'}
                if key in {'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}:
                    method['params'] = {'epsilon':'0.1', 'quality_mode':'compatible'}
                methods.append(method)
            name = group + '-' + short
            document = {
                'schema':'tsbench.experiment/1', 'name':name, 'output':str(run_root/name),
                'datasets':datasets, 'methods':methods,
                'profiles':[{'id':'cpu-dzip-three' if method_keys == ['dzip'] else 'cpu-single',
                             'device':'cpu','native_threads':3 if method_keys == ['dzip'] else 1,
                             'object_workers':1,'memory_limit_mb':8192,
                             'runtime_preload':['/usr/lib/x86_64-linux-gnu/libstdc++.so.6']}],
                'task':{'kind':kind,'fidelity':fidelity,'boundary':'native_core','lifecycle':life,
                        'cache_policy':'natural', **({'error_bound':'0.01'} if fidelity=='bounded_abs' else {})},
                'execution':{'sessions':2,'rounds':7,'warmup_objects':0,
                             'native_loops':1 if large else 8,'native_warmup_loops':1 if large else 2,
                             'native_batch_memory_mb':2048 if large else 256,
                             'timeout_s':1800,'qualification_cache':True,'save_artifacts':False,
                             'max_pending_workers':8,'seed':20261018},
                'analysis':{'summary':'median_iqr','inference':'none'}}
            path = destination / (name+'.toml')
            if path.exists() and path.read_text() != toml_text(document):
                raise FileExistsError(f'frozen config differs: {path}')
            path.write_text(toml_text(document))
            load(path)
            documents.append({'path':str(path),'sha256':file_hash(path), 'run':document['output'],
                              'group':group,'kind':kind,'fidelity':fidelity,'lifecycle':life,
                              'requests':len(datasets)*len(methods),
                              'input_ids':[d['id'] for d in datasets], 'codecs':sorted(method_keys)})

    for batch_id, members in batches:
        large = batch_id != 'small'
        base = []
        typed = defaultdict(list)
        records = []
        for row in members:
            source = Path(row['source'])
            if hashlib.file_digest(source.open('rb'),'sha256').hexdigest()!=row['source_sha256']:
                raise ValueError(f'source changed: {source}')
            a = np.load(row['npy'],allow_pickle=False)
            assert list(a.shape)==row['shape'] and a.dtype.str=='<f8'
            common = {'format':'npy', 'component':'V','order':'C','source':str(source),
                      'schema':{'forecasting_source':str(source),'forecasting_source_sha256':row['source_sha256'],
                                'forecasting_family':row['family'],'all_source_rows_and_value_columns':True}}
            row['npy_sha256']=file_hash(row['npy'])
            base.append({'id':row['id']+'-f64','path':row['npy'],**common})
            # f32 is a declared, separate input task. Never call its result
            # lossless recovery of the f64 source.
            variants = [('f32','<f4')]
            if row['integral']:
                variants.append(('i64','<i8'))
                for label, dtype in [('i16','<i2'),('u32','<u4'),('u8','|u1')]:
                    lim=np.iinfo(dtype)
                    if lim.min<=row['min'] and row['max']<=lim.max:
                        variants.append((label,dtype))
            for label,dtype in variants:
                b=a.astype(dtype)
                if label!='f32' and not np.array_equal(b.astype('<f8'),a):
                    raise ValueError(f'inexact integer conversion: {row["id"]}')
                path=data_dir/(row['id']+'-'+label+'.npy')
                np.save(path,b,allow_pickle=False)
                dataset={'id':row['id']+'-'+label,'path':str(path),**common}
                typed[label].append(dataset)
                finite=np.isfinite(a)&np.isfinite(b)
                inputs.append({'id':dataset['id'],'source_id':row['id'],'dtype':dtype,'shape':list(b.shape),
                               'path':str(path),'sha256':file_hash(path),
                               'source_conversion_max_abs':float(np.max(np.abs(b[finite].astype('<f8')-a[finite]),initial=0)),
                               'exact_numeric_conversion':label!='f32'})
            if a.ndim==1:
                frame=pd.read_csv(source, usecols=['date'])
                t=(frame['date'].to_numpy(dtype='<i8') if row['timestamp_parser']=='int'
                   else frame['date'].to_numpy(dtype='datetime64[ns]').astype('<i8'))
                path=data_dir/(row['id']+'-records.npz')
                np.savez(path,V=a,T=t)
                record_inputs.append({'id':row['id']+'-records','path':str(path),
                                      'sha256':file_hash(path),'source_id':row['id'],
                                      'V_shape':list(a.shape),'T_shape':list(t.shape),
                                      'T_units':'ns' if row['timestamp_parser']!='int' else 'source integer index'})
                records.append({'id':row['id']+'-records','format':'npz','path':str(path),
                                'components':{'V':'V','T':'T'},
                                **({'time_unit':'ns'} if row['timestamp_parser']!='int' else {}),
                                'source':str(source),'schema':common['schema']})
        lossless=[s.key for s in specs if s.loss_mode=='LOSSLESS' and s.key!='dzip']
        bounded=[s.key for s in specs if s.loss_mode=='ERROR_BOUNDED_LOSSY']
        empirical=[s.key for s in specs if s.loss_mode=='UNBOUNDED_LOSSY']
        add(batch_id+'-f64-lossless',base,lossless,large=large)
        add(batch_id+'-f64-dzip',base,['dzip'],large=large)
        add(batch_id+'-f64-bounded',base,bounded,'bounded_abs',large=large)
        add(batch_id+'-f64-empirical',base,empirical,'empirical_quality',large=large)
        add(batch_id+'-f32-lossless',typed['f32'],['chimp32','chimpn32'],large=large)
        add(batch_id+'-f32-filters',typed['f32'],[k for k in empirical if k not in {'abba','fabba','qabba'}],
            'empirical_quality',large=large)
        add(batch_id+'-i64',typed['i64'],['neats-lossless-i64','leats-lossless-i64'],large=large)
        add(batch_id+'-i16',typed['i16'],['sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman'],large=large)
        add(batch_id+'-u32',typed['u32'],['simdcomp-u32'],large=large)
        add(batch_id+'-symbols',typed['u8'],['deepzip'],large=large)
        add(batch_id+'-symbols-dzip',typed['u8'],['dzip'],large=large)
        add(batch_id+'-records',records,['gorilla-prometheus-xor'],kind='records',large=large)
    design={'schema':'tsbench.forecasting-design/1', 'created_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
            'selection':'family = prefix before _dataset, otherwise strip trailing _digits; lower median by (full numeric element count, filename)',
            'scope':'53 representative files; every row and every non-date value column; C layout; no windows, imputation, normalization or quantization',
            'typed_tasks':'Primary f64; supplementary f32 declared separately; integer casts only if finite, integral, within range and exactly reversible; records only for source single-channel files, native date units retained',
            'excluded':[s.key for s in registry.list(include_excluded=True) if s.excluded],
            'codecs':sorted(keys),'selected':selected,'typed_inputs':inputs,'record_inputs':record_inputs,'configurations':documents,
            'requested_cases':sum(d['requests'] for d in documents),'run_root':str(run_root)}
    write_json(destination/'design.json',design)
    return design


def execute(destination):
    destination=Path(destination).resolve()
    design=json.loads((destination/'design.json').read_text())
    run_root=Path(design['run_root']);run_root.mkdir(parents=True,exist_ok=True)
    status=[]
    for n,entry in enumerate(design['configurations'],1):
        config=Path(entry['path']);directory=Path(entry['run'])
        assert file_hash(config)==entry['sha256']
        done=directory/'report/summary.json'
        if done.exists() and json.loads((directory/'manifest.json').read_text()).get('state')=='complete':
            code=0
        else:
            log=run_root/(config.stem+'.log')
            command=[sys.executable,'-m','tsbench','run',str(config)]
            if (directory/'manifest.json').exists():command.append('--resume')
            print(f'[{n}/{len(design["configurations"])}] {config.stem}',flush=True)
            with log.open('ab') as stream:
                code=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT).returncode
        status.append({'configuration':str(config),'returncode':code,'run':str(directory)})
        write_json(run_root/'orchestration.json',{'completed_configurations':len(status),
                   'total_configurations':len(design['configurations']),'runs':status})
        # Recompute reviewable progress from completed native runs; never time
        # plotting alongside a codec measurement.
    if any(s['returncode'] for s in status):
        raise RuntimeError('one or more experiments failed; inspect orchestration logs')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['freeze','run'])
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    if args.operation=='freeze':
        design=freeze(args.destination)
        print(json.dumps({'configurations':len(design['configurations']), 'requested_cases':design['requested_cases']}))
    else:execute(args.destination)
