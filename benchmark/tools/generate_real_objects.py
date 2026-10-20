"""Freeze real MTS, timestamp, records and scheme ablations; never measure codecs."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tomllib

from characterize_data import object_profile, sha256, source_profile
from tsbench.config import resolve
from tsbench.data import load_dataset, project
from tsbench.registry import Registry
from tsbench.schemes import capability


ROOT = Path(__file__).resolve().parents[2]
LENGTHS = (128, 512)
EVALUATION_START = 2048
SEED = 20261013
SESSIONS = 3
ROUNDS = 7


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def freeze_text(path: Path, value: str):
    if path.exists() and path.read_text() != value:
        raise ValueError(f'fixed artifact differs: {path}; preserve this study and create a new directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def toml_value(value):
    if type(value) is bool:
        return 'true' if value else 'false'
    if isinstance(value, dict):
        return '{ ' + ', '.join(json.dumps(key) + ' = ' + toml_value(entry) for key, entry in value.items()) + ' }'
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render_config(config):
    lines = ['# Fixed inputs and ablations: study_design.json. No test-object tuning.',
             'schema = "tsbench.experiment/1"']
    for key in ('name', 'output'):
        lines.append(f'{key} = {toml_value(config[key])}')
    for group in ('datasets', 'methods', 'profiles'):
        for entry in config[group]:
            lines.extend(['', f'[[{group}]]'])
            lines.extend(f'{key} = {toml_value(value)}' for key, value in entry.items())
    for group in ('task', 'execution'):
        lines.extend(['', f'[{group}]'])
        lines.extend(f'{key} = {toml_value(value)}' for key, value in config[group].items())
    return '\n'.join(lines) + '\n'


def build_configs(sources, run_root: Path):
    mts, times, temperatures = [], [], []
    for source in sources:
        key = source['id']
        full_columns = source['header'][1:]
        temperature_columns = ['OT'] if key == 'etth1' else ['T (degC)', 'Tdew (degC)', 'Tlog (degC)']
        if not set(temperature_columns).issubset(full_columns):
            raise ValueError(f'{key}: fixed temperature channels absent')
        for length in LENGTHS:
            base = {'format': 'csv', 'path': source['path'], 'dtype': '<f8', 'encoding': 'utf-8',
                    'timestamp_column': 'date', 'timestamp_parser': 'datetime64', 'time_unit': 'ns',
                    'missing': 'reject', 'columns': full_columns,
                    'start': EVALUATION_START, 'stop': EVALUATION_START + length, 'step': 1, 'source': key}
            for order in ('C', 'F'):
                mts.append({'id': f'{key}-mts-n{length}-{order.lower()}', **base, 'order': order})
                if key != 'etth1' or order == 'C':
                    temperatures.append({'id': f'{key}-temperature-n{length}-{order.lower()}',
                                         **base, 'columns': temperature_columns, 'order': order})
            times.append({'id': f'{key}-time-n{length}', **base, 'order': 'C'})

    def codec(key, identifier=None, **extra):
        return {'id': identifier or key, 'codec': key, **extra}

    lossless = [codec('raw-store'), codec('zstd-frame'), codec('chimp128'),
                codec('zstd-frame', 'zstd-channelwise', channelwise=True),
                codec('zstd-frame', 'zstd-chunks-64', chunk_rows=64),
                codec('zstd-frame', 'zstd-chunks-256', chunk_rows=256),
                codec('zstd-frame', 'zstd-channelwise-chunks-64', channelwise=True, chunk_rows=64)]
    timestamp_methods = [codec('raw-store'), codec('zstd-frame'),
                         codec('raw-store', 'raw-integer-affine', transform='integer_affine_gcd'),
                         codec('neats-lossless-i64', 'neats-integer-affine', transform='integer_affine_gcd'),
                         codec('leats-lossless-i64', 'leats-integer-affine', transform='integer_affine_gcd')]
    records = [codec('raw-store'), codec('zstd-frame'),
               codec('chimp128', 'zstd-time-chimp128-values', components={'T': {'codec': 'zstd-frame'}}),
               codec('chimp128', 'neats-time-chimp128-values', components={
                   'T': {'codec': 'neats-lossless-i64', 'transform': 'integer_affine_gcd'}}),
               codec('chimp128', 'leats-time-chimp128-values', components={
                   'T': {'codec': 'leats-lossless-i64', 'transform': 'integer_affine_gcd'}})]

    def experiment(name, datasets, methods, kind, fidelity, bound=None):
        task = {'kind': kind, 'fidelity': fidelity, 'boundary': 'object_memory',
                'lifecycle': 'independent_object', 'cache_policy': 'natural'}
        if bound is not None:
            task['error_bound'] = bound
        return {'schema': 'tsbench.experiment/1', 'name': name,
                'output': str((run_root/(name+'-20261013')).resolve()),
                'datasets': datasets, 'methods': methods,
                'profiles': [{'id': 'cpu-single', 'device': 'cpu', 'native_threads': 1,
                              'object_workers': 1, 'memory_limit_mb': 4096}],
                'task': task, 'execution': {'sessions': SESSIONS, 'rounds': ROUNDS, 'warmup_objects': 2,
                                          'seed': SEED, 'timeout_s': 120, 'qualification_cache': True}}

    configs = [experiment('real-mts-lossless', mts, lossless, 'values', 'bitwise'),
               experiment('real-timestamps-lossless', times, timestamp_methods, 'timestamps', 'bitwise'),
               experiment('real-records-lossless', mts, records, 'records', 'bitwise')]
    for bound in ('0.01', '0.1'):
        methods = [codec(key, params={'error_bound': bound, 'native_timing': False}) for key in
                   ('serf-qt', 'serf-xor', 'zfp-accuracy-1d')]
        configs.append(experiment('real-temperature-abs-'+bound.replace('.', 'p'), temperatures, methods,
                                  'values', 'bounded_abs', bound))
    return configs


def generate(corpus: Path, output: Path, characterization: Path, catalog: Path, run_root: Path):
    output = output.resolve()
    characterization = characterization.resolve()
    catalog_document = json.loads(catalog.read_text())
    by_id = {entry['id']: entry for entry in catalog_document['datasets']}
    sources = [source_profile(by_id[key], corpus, EVALUATION_START, EVALUATION_START + max(LENGTHS))
               for key in ('etth1', 'weather')]
    configs = build_configs(sources, run_root)
    registry = Registry(ROOT)
    cases, profiles, paths = [], [], []
    loaded = {}
    for config in configs:
        text = render_config(config)
        path = output/(config['name']+'.toml')
        # Parse the actual serialization before freezing or preflight.
        resolved = resolve(tomllib.loads(text), output)
        for dataset in resolved['datasets']:
            dataset_key = json.dumps(dataset, sort_keys=True)
            if dataset_key not in loaded:
                loaded[dataset_key] = load_dataset(dataset, output)
            original = project(loaded[dataset_key], resolved['task'])
            profiles.append({'experiment': config['name'], **object_profile(original, dataset['id'])})
            for method in resolved['methods']:
                route = {**method, 'params': registry.resolve_params(method['codec'], method.get('params', {}))}
                if 'components' in method:
                    route['components'] = {name: {**entry, 'params': registry.resolve_params(
                        entry['codec'], entry.get('params', {}))} for name, entry in method['components'].items()}
                for profile in resolved['profiles']:
                    cases.append({'experiment': config['name'], 'dataset_id': dataset['id'],
                                  'raw_object_id': profiles[-1]['raw_object_id'], 'method_id': method['id'],
                                  'profile_id': profile['id'], 'task': resolved['task'], 'resolved_method': route,
                                  **capability(route, original, resolved['task'], profile,
                                               asset_root=ROOT, build_root=resolved['_build_root'])})
        paths.append(path)

    design = {
        'schema': 'tsbench.real-object-study/1', 'seed': SEED,
        'sources': [{'id': source['id'], 'path': source['path'], 'sha256': source['sha256'],
                     'bytes': source['bytes'], 'rows': source['rows'], 'header': source['header'],
                     'development': [0, EVALUATION_START],
                     'evaluation': [EVALUATION_START, EVALUATION_START+max(LENGTHS)],
                     'license': source['license'], 'upstream': source['upstream']} for source in sources],
        'lengths': list(LENGTHS), 'layouts': ['C', 'F'], 'sessions': SESSIONS, 'rounds': ROUNDS,
        'absolute_bounds': ['0.01', '0.1'],
        'channel_policy': 'ETT all 7 and weather all 21 channels for lossless MTS/records; ABS uses ETT OT and weather T/Tdew/Tlog in degC',
        'timestamp_policy': 'date strings to exact naive-wall-clock int64 nanoseconds; preserve original order and duplicates; no timezone assertion',
        'records_policy': 'V and real shared T; missing tokens reject; no invented mask or fabricated missingness',
        'scheme_policy': 'independent object; explicit component routes; separate chunk resets/column streams; integer_affine_gcd parameters charged in wire',
        'selection': 'fixed grid, no method/parameter tuning from these measurements; development reserved, not used for selection',
        'prior_exposure': 'pilot [0,512), older ETT/weather CPU performance study [1024,1536); new evaluation does not overlap those performance windows. Full sources were parsed and characterized before this study; this is not a blind holdout.',
        'dependence': 'n128 is prefix of n512; columns, layouts, task projections and rounds reuse source observations; two source files are the highest grouping level and do not support population inference',
        'comparison': 'rank methods only for matching raw_object_id/task/error/profile/boundary. C/F have distinct exact canonical object identities; layout ablation is a paired logical-data intervention with its own object/wire costs.',
        'timing': 'object_memory Python+scheme+FFI+container boundary; source parsing/characterization outside clock; no native-only comparison',
        'configuration_counts': [{'name': config['name'], 'datasets': len(config['datasets']),
                                   'methods': len(config['methods']), 'profiles': len(config['profiles']),
                                   'requested_cases': len(config['datasets'])*len(config['methods'])*len(config['profiles'])}
                                  for config in configs],
        'requested_cases': len(cases), 'planned_trials': len(cases)*SESSIONS*ROUNDS,
        'measurement_executed_by_generator': False,
    }
    frozen_hash_paths = [catalog, Path(__file__).resolve(), Path(__file__).with_name('characterize_data.py')]
    frozen_hash_paths += sorted((ROOT/'benchmark/src/tsbench').glob('*.py'))
    frozen_hash_paths += sorted((ROOT/'registry/codecs').glob('*.json'))
    preflight = {
        'schema': 'tsbench.real-object-preflight/1', 'measurement_executed': False,
        'qualification_executed': False,
        'scope': 'pure parse/projection/parameter/declared capability and installed artifact checks; native content qualification and accuracy remain pending',
        'source_and_code_hashes': {str(path.resolve()): sha256(path) for path in frozen_hash_paths},
        'configuration_sha256': {str(path): hashlib.sha256(render_config(config).encode()).hexdigest()
                                  for path, config in zip(paths, configs)},
        'requested_cases': len(cases), 'declared_executable_cases': sum(case['supported'] for case in cases),
        'capability_status_counts': dict(Counter(case['status'] for case in cases)),
        'planned_trials': len(cases)*SESSIONS*ROUNDS, 'cases': cases,
    }
    characterization_document = {
        'schema': 'tsbench.data-characterization/1', 'codec_execution': False,
        'scope': 'outside timing; original source tokens and projected canonical inputs',
        'definitions': {
            'decimal_precision': 'lexical Decimal exponent including trailing zeros; floating-point export artifacts are retained; not source sensor resolution',
            'statistics': 'finite values only; population std (ddof=0); NumPy linear quantiles; numeric equality merges signed zero only for unique/equal counts',
            'trend_and_residual': 'OLS against row index; residual RMSE is a descriptive deviation from a line, not an identified measurement-noise estimate',
            'lag1': 'Pearson correlation of adjacent finite pairs; null when absent/constant; no gaps are joined',
            'identity': 'raw_object_id includes task schema, component descriptors/layout and bytes; component hashes follow declared C/F logical order',
        },
        'sources': sources, 'objects': profiles,
    }
    # A differing artifact is rejected before any existing study file is overwritten.
    artifacts = {output/'study_design.json': json_text(design), output/'preflight.json': json_text(preflight),
                 characterization/'real_objects.json': json_text(characterization_document)}
    artifacts.update({path: render_config(config) for path, config in zip(paths, configs)})
    for path, value in artifacts.items():
        if path.exists() and path.read_text() != value:
            raise ValueError(f'fixed artifact differs: {path}; use a new directory')
    for path, value in artifacts.items():
        freeze_text(path, value)
    return {'configurations': [str(path) for path in paths], 'design': str(output/'study_design.json'),
            'preflight': str(output/'preflight.json'), 'characterization': str(characterization/'real_objects.json'),
            'requested_cases': len(cases), 'planned_trials': len(cases)*SESSIONS*ROUNDS,
            'capability_status_counts': preflight['capability_status_counts'], 'measurement_executed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, default=Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus'))
    parser.add_argument('--output', type=Path, default=ROOT/'benchmark/experiments/real-objects')
    parser.add_argument('--characterization', type=Path, default=ROOT/'docs/data_characterization')
    parser.add_argument('--catalog', type=Path, default=ROOT/'registry/datasets/catalog.json')
    parser.add_argument('--run-root', type=Path, default=ROOT/'runs')
    args = parser.parse_args()
    print(json_text(generate(args.corpus, args.output, args.characterization, args.catalog, args.run_root)), end='')
