"""Freeze native performance and ABI admission matrices, without executing them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def value(item):
    if isinstance(item, bool): return str(item).lower()
    if isinstance(item, (int,float)): return str(item)
    if isinstance(item, list): return '['+', '.join(value(x) for x in item)+']'
    if isinstance(item, dict): return '{ '+', '.join(k+' = '+value(v) for k,v in item.items())+' }'
    return json.dumps(str(item),ensure_ascii=False)


def text(name,datasets,methods,boundary='native_core',lifecycle='prepared',fidelity='bitwise',profiles=None):
    lines=['# Frozen by generate_native_experiments.py; no result-dependent tuning.',
           'schema = "tsbench.experiment/1"',f'name = {value(name)}',f'output = {value(str(ROOT/"runs"/(name+"-20261015")))}','']
    for group,entries in [('datasets',datasets),('methods',methods),('profiles',profiles or [{'id':'cpu-single','device':'cpu','native_threads':1,'object_workers':1}])]:
        for entry in entries:
            lines += [f'[[{group}]]',*[k+' = '+value(v) for k,v in entry.items()],'']
    lines += ['[task]','kind = "values"',f'fidelity = {value(fidelity)}',f'boundary = {value(boundary)}',f'lifecycle = {value(lifecycle)}','cache_policy = "natural"']
    if fidelity=='bounded_abs':lines += ['error_bound = "0.01"']
    lines += ['','[execution]','sessions = 2','rounds = 7','warmup_objects = 0','native_loops = 8','native_warmup_loops = 2','native_batch_memory_mb = 256','timeout_s = 120','qualification_cache = true','save_artifacts = true','seed = 20261015','']
    return '\n'.join(lines)


def generate(destination):
    destination=Path(destination).resolve();destination.mkdir(parents=True,exist_ok=True)
    cards=[json.loads(p.read_text()) for p in sorted((ROOT/'registry/codecs').glob('*.json'))]
    methods=[{'id':'raw-store','codec':'raw-store'}]+[{'id':c['key'],'codec':c['key']} for c in cards]
    # Same untouched typed objects for every core method, with layout explicitly
    # fixed. F order is a distinct task, never a hidden conversion for a codec.
    real=[]
    for source,filename,columns,start,stop in [('etth1','ETTh1.csv',['HUFL','HULL','MUFL','MULL','LUFL','LULL','OT'],2048,10240),
            ('weather','weather.csv',['T (degC)','Tdew (degC)','Tlog (degC)'],2048,34816),
            ('ili','national_illness.csv',['OT'],0,512)]:
        for order in ('C','F') if len(columns)>1 else ('C',):
            real.append({'id':source+'-values-'+order.lower(),'format':'csv','path':str(Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus')/filename),
                         'dtype':'<f8','columns':columns,'timestamp_column':'date','timestamp_parser':'datetime64','time_unit':'ns',
                         'encoding':'utf-8','missing':'reject','start':start,'stop':stop,'order':order,'source':source})
    fixtures=[{'id':key,'format':'npy','path':str(ROOT/'benchmark/examples/data'/(key+'.npy')),'component':'V'}
              for key in ('float64','float32','int16','uint8','symbols4','uint32')]
    lossless=[{'id':c['key'],'codec':c['key']} for c in cards if c['semantics']['loss_modes']==['LOSSLESS']]
    single={'id':'cpu-single','device':'cpu','native_threads':1,'object_workers':1}
    triple={'id':'cpu-dzip-three','device':'cpu','native_threads':3,'object_workers':1,'runtime_preload':['/usr/lib/x86_64-linux-gnu/libstdc++.so.6']}
    definitions={
        'core.toml':text('native-core-real',real,methods),
        'fresh.toml':text('native-core-fresh',real,methods,lifecycle='fresh_request'),
        'api_lossless.toml':text('native-api-lossless',fixtures,lossless,'native_api',profiles=[single,triple]),
        'api_bounded.toml':text('native-api-bounded',fixtures[:2],[{'id':k,'codec':k,'params':{'error_bound':'0.01'}} for k in ('serf-qt','serf-xor','zfp-accuracy-1d')],'native_api',fidelity='bounded_abs'),
        'api_empirical.toml':text('native-api-empirical',real[-1:],[{'id':k,'codec':k} for k in ('abba','fabba','qabba')],'native_api',fidelity='empirical_quality'),
        'object.toml':text('object-reference-real',real,[m for m in methods if m['codec'] in ('raw-store','zstd-frame','lz4-frame','snappy-raw')],'object_memory','independent_object'),
    }
    for name,body in definitions.items():
        path=destination/name
        if path.exists() and path.read_text()!=body:raise FileExistsError('refuse to replace a different frozen design: '+str(path))
        path.write_text(body)
    design={'schema':'tsbench.native-design/1','generated_from':str(Path(__file__).resolve()),'date':'2026-10-15',
            'selection':'predefined windows, no input conversion/tuning from results; fixture API matrix tests integration, not corpus ranking',
            'core_scope':'raw/Zstd/LZ4/Snappy direct APIs; all other requests remain unsupported',
            'profiles':'single thread primary; DZip caller+2 workers separate ABI auxiliary',
            'configurations':list(definitions),'raw_sources':real}
    (destination/'design.json').write_text(json.dumps(design,ensure_ascii=False,indent=2)+'\n')
    return [destination/name for name in definitions]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'benchmark/experiments/native')
    for item in generate(parser.parse_args().output):print(item)
