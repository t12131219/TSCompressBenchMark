"""Freeze a prespecified CPU length/quality study; no test-object tuning."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [('etth1', 'ETTh1.csv', 'OT', 1024),
           ('weather', 'weather.csv', 'T (degC)', 1024),
           ('national_illness', 'national_illness.csv', 'ILITOTAL', 256)]


def quoted(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def generate(corpus: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    datasets, sources = [], []
    for key, filename, column, evaluation_start in SOURCES:
        path = (corpus / filename).resolve(strict=True)
        with path.open(newline='') as stream:
            reader = csv.DictReader(stream)
            if column not in reader.fieldnames:
                raise ValueError(f'{key}: required column absent')
            count = sum(1 for _ in reader)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if count < evaluation_start + 512:
            raise ValueError(f'{key}: evaluation window too short')
        sources.append({'id': key, 'path': str(path), 'sha256': digest, 'rows': count,
                        'column': column, 'development': [0, evaluation_start],
                        'evaluation': [evaluation_start, evaluation_start+512],
                        'license_status': 'see registry/datasets/catalog.json; local use only until verified'})
        for length in (128, 512):
            datasets.append({'id': f'{key}-n{length}', 'format': 'csv', 'path': str(path),
                             'dtype': '<f8', 'columns': [column], 'start': evaluation_start,
                             'stop': evaluation_start+length, 'source': key})
    study = {'schema': 'tsbench.study-design/1', 'seed': 20261013, 'sources': sources,
             'lengths': [128,512], 'absolute_bounds': ['0.001','0.01','0.1'],
             'empirical_tolerances': ['0.01','0.1','1'], 'sessions': 3, 'rounds': 7,
             'selection': 'all listed grid points; no deployment selector or test-object tuning',
             'dependence': 'nested evaluation windows share data; sources are the highest resampling unit',
             'development_use': 'reserved, not used to pick methods/parameters; fixed grid was declared before these runs',
             'comparison': 'within matching raw_object_id/task/profile/boundary; no cross-error ranking'}
    design_path = output/'study_design.json'
    if design_path.exists() and json.loads(design_path.read_text()) != study:
        raise ValueError('existing study design differs; use a new study directory')
    design_path.write_text(json.dumps(study, ensure_ascii=False, indent=2)+'\n')

    def experiment(name, methods, fidelity, bound=None):
        lines = ['# Fixed study grid; source hashes and selection are in study_design.json.',
                 'schema = "tsbench.experiment/1"', f'name = {quoted(name)}',
                 f'output = {quoted(str(ROOT/"runs"/(name+"-20261013")))}', '']
        for dataset in datasets:
            lines.append('[[datasets]]')
            lines.extend(f'{key} = {quoted(value)}' for key,value in dataset.items())
            lines.append('')
        for method in methods:
            lines.extend(['[[methods]]', f'id = {quoted(method["id"])}', f'codec = {quoted(method["codec"])}'])
            params = method.get('params', {})
            if params:
                lines.append('params = { '+', '.join(f'{key} = {quoted(value)}' for key,value in params.items())+' }')
            lines.append('')
        lines.extend(['[task]','kind = "values"', f'fidelity = {quoted(fidelity)}',
                      'boundary = "object_memory"', 'lifecycle = "independent_object"', 'cache_policy = "natural"'])
        if bound is not None:lines.append(f'error_bound = {quoted(bound)}')
        lines.extend(['','[execution]','sessions = 3','rounds = 7','warmup_objects = 2',
                      'seed = 20261013','timeout_s = 120','qualification_cache = true',''])
        target = output/(name+'.toml')
        target.write_text('\n'.join(lines))
        return target
    methods = [{'id':key, 'codec':key} for key in ('raw-store','zstd-frame','lz4-frame','lzss-raw','chimp128','alp-rd','elf-star')]
    paths = [experiment('study-lossless-length', methods, 'bitwise')]
    for bound in study['absolute_bounds']:
        methods = [{'id':key, 'codec':key, 'params':{'error_bound':bound}} for key in ('serf-qt','serf-xor','zfp-accuracy-1d')]
        paths.append(experiment('study-abs-'+bound.replace('.','p'), methods, 'bounded_abs', bound))
    methods=[]
    for tol in study['empirical_tolerances']:
        methods.append({'id':'abba-'+tol.replace('.','p'), 'codec':'abba',
                        'params':{'compression_tolerance':tol,'digitization_tolerance':tol}})
        methods.append({'id':'fabba-'+tol.replace('.','p'), 'codec':'fabba',
                        'params':{'tolerance':tol, 'alpha':tol}})
        methods.append({'id':'qabba-'+tol.replace('.','p'), 'codec':'qabba',
                        'params':{'tolerance':tol, 'alpha':tol}})
    paths.append(experiment('study-empirical-grid', methods, 'empirical_quality'))
    return paths


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,default=Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus'))
    parser.add_argument('--output',type=Path,default=ROOT/'benchmark/experiments/cpu-study')
    args=parser.parse_args()
    for path in generate(args.corpus,args.output):print(path)
