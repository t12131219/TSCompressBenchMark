"""Freeze native_core requests for every registry key without executing codecs.

Reads typed source inputs, validates the declared domains and freezes their
identities. Never builds, qualifies, times or calls an encoder/decoder. Old
native/API/object designs and all existing raw results remain untouched.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'benchmark/src'))

from tsbench.config import resolve
from tsbench.data import array_order, load_dataset, object_id, project, raw_bytes
from tsbench.registry import Registry

SEED = 20261015
BYTE_KEYS = ('raw-store', 'brotli-stream', 'bzip2-stream', 'deflate-zlib', 'fse', 'huff0',
             'lz4-frame', 'lzsse2-raw', 'lzsse8-raw',
             'snappy-raw', 'xz-stream', 'zstd-frame')
FLOAT_KEYS = ('alp', 'alp-rd', 'elf', 'elf-plus', 'elf-star', 'self-star')
CHIMP64_KEYS = ('chimp', 'chimp128', 'chimpn', 'chimp128-no-index')
CHIMP32_KEYS = ('chimp32', 'chimpn32')
FILTER_KEYS = ('pmc-mr', 'swing-filter', 'swing-filter-disjoint', 'swing-filter-disjoint-quantized')
BOUNDED_KEYS = ('serf-qt', 'serf-xor', 'zfp-accuracy-1d')
SINGLE = {'id': 'cpu-single', 'device': 'cpu', 'native_threads': 1,
          'object_workers': 1, 'memory_limit_mb': 4096}
DZIP = {'id': 'cpu-dzip-three', 'device': 'cpu', 'native_threads': 3,
        'object_workers': 1, 'memory_limit_mb': 4096,
        'runtime_preload': ['/usr/lib/x86_64-linux-gnu/libstdc++.so.6']}
NATIVE_ROUTE_NOTE = ('expected_declared_domain describes registry declarations only, not direct-route admission; '
                     'Sprintz matrix direct routes accept C layout only. The eight F-layout requests '
                     '(four methods x two lifecycles) are retained as expected unsupported, with no implicit '
                     'transpose. Every registry key must still achieve at least one validated success per '
                     'lifecycle before measured coverage is claimed.')


def value(item):
    if isinstance(item, bool):
        return str(item).lower()
    if isinstance(item, (int, float)):
        return str(item)
    if isinstance(item, list):
        return '[' + ', '.join(value(x) for x in item) + ']'
    if isinstance(item, dict):
        return '{ ' + ', '.join(key + ' = ' + value(item) for key, item in item.items()) + ' }'
    return json.dumps(str(item), ensure_ascii=False)


def frozen_write(path, content):
    if path.exists() and path.read_text() != content:
        raise FileExistsError('refuse to replace a different frozen design: ' + str(path))
    path.write_text(content)


def text(document):
    lines = ['# Frozen by generate_all_core_experiments.py; no result-dependent tuning.']
    for field in ('schema', 'name', 'output'):
        lines.append(field + ' = ' + value(document[field]))
    for group in ('datasets', 'methods', 'profiles'):
        for entry in document[group]:
            lines += ['', '[[' + group + ']]']
            lines += [key + ' = ' + value(item) for key, item in entry.items()]
    for group in ('task', 'execution', 'analysis'):
        lines += ['', '[' + group + ']']
        lines += [key + ' = ' + value(item) for key, item in document[group].items()]
    return '\n'.join(lines) + '\n'


def fixture(name, *, order='C', stop=None):
    result = {'id': name + '-' + order.lower() + (f'-n{stop}' if stop else ''),
              'format': 'npy', 'path': str(ROOT / 'benchmark/examples/data' / (name + '.npy')),
              'component': 'V', 'order': order, 'source': 'development-fixture:' + name}
    if stop is not None:
        result['stop'] = stop
    return result


def csv_dataset(corpus, source, filename, columns, start, stop, order='C', suffix='values'):
    return {'id': source + '-' + suffix + '-' + order.lower(), 'format': 'csv',
            'path': str(corpus / filename), 'dtype': '<f8', 'columns': list(columns),
            'timestamp_column': 'date', 'timestamp_parser': 'datetime64', 'time_unit': 'ns',
            'encoding': 'utf-8', 'missing': 'reject', 'start': start, 'stop': stop,
            'order': order, 'source': source}


def definitions(corpus, run_root):
    # These five objects repeat the original core design exactly. F is a
    # declared separate layout task; each codec receives identical physical bytes.
    real = []
    for source, filename, columns, start, stop in (
            ('etth1', 'ETTh1.csv', ['HUFL', 'HULL', 'MUFL', 'MULL', 'LUFL', 'LULL', 'OT'], 2048, 10240),
            ('weather', 'weather.csv', ['T (degC)', 'Tdew (degC)', 'Tlog (degC)'], 2048, 34816),
            ('ili', 'national_illness.csv', ['OT'], 0, 512)):
        for order in ('C', 'F') if len(columns) > 1 else ('C',):
            real.append(csv_dataset(corpus, source, filename, columns, start, stop, order))
    floats = [fixture(name, order=order) for name in ('float64', 'float32') for order in ('C', 'F')]
    models = [fixture('int16', order=order) for order in ('C', 'F')]
    records = [csv_dataset(corpus, 'etth1', 'ETTh1.csv', ['OT'], 2048, 2560, suffix='records'),
               csv_dataset(corpus, 'weather', 'weather.csv', ['T (degC)'], 2048, 2560, suffix='records')]
    groups = [
        ('real', real, tuple(key for key in BYTE_KEYS if key not in {'fse', 'huff0'}) + FLOAT_KEYS + CHIMP64_KEYS,
         'bitwise', 'values', SINGLE, {}),
        ('entropy', floats + [fixture('uint8')], ('fse', 'huff0'), 'bitwise', 'values', SINGLE, {}),
        ('floats', floats, FLOAT_KEYS, 'bitwise', 'values', SINGLE, {}),
        ('chimp64', [fixture('float64', order=order) for order in ('C','F')], CHIMP64_KEYS, 'bitwise', 'values', SINGLE, {}),
        ('chimp32', [fixture('float32', order=order) for order in ('C','F')], CHIMP32_KEYS, 'bitwise', 'values', SINGLE, {}),
        ('chimp-filters', [{**real[-1], 'dtype': '<f4'}], FILTER_KEYS, 'empirical_quality', 'values', SINGLE, {}),
        ('integer-models', models, ('neats-lossless-i64', 'leats-lossless-i64'), 'bitwise', 'values', SINGLE, {}),
        ('integer-matrix', models + [fixture('uint8')],
         ('sprintz-delta', 'sprintz-fire', 'sprintz-delta-huffman', 'sprintz-fire-huffman'), 'bitwise', 'values', SINGLE, {}),
        ('integer-u8', [fixture('uint8')], ('sprintz-delta', 'sprintz-fire', 'sprintz-delta-huffman', 'sprintz-fire-huffman'), 'bitwise', 'values', SINGLE, {}),
        ('integer-u32', [fixture('uint32')], ('simdcomp-u32',), 'bitwise', 'values', SINGLE, {}),
        ('bounded', floats, BOUNDED_KEYS, 'bounded_abs', 'values', SINGLE, {}),
        ('empirical', real[-1:], ('abba', 'fabba', 'qabba'), 'empirical_quality', 'values', SINGLE, {}),
        ('deepzip', [fixture('symbols4', stop=64)], ('deepzip',), 'bitwise', 'values', SINGLE,
         {'timeout_s': 600}),
        ('dzip', [fixture('symbols4', stop=64)], ('dzip',), 'bitwise', 'values', DZIP,
         {'native_loops': 2, 'native_batch_memory_mb': 1024, 'timeout_s': 600}),
        ('records', records, ('gorilla-prometheus-xor',), 'bitwise', 'records', SINGLE, {}),
    ]
    documents = []
    for group, datasets, keys, fidelity, kind, profile, overrides in groups:
        for lifecycle in ('prepared', 'fresh_request'):
            name = 'native-all-' + group + '-' + ('prepared' if lifecycle == 'prepared' else 'fresh')
            methods = [{'id': key, 'codec': key,
                        **({'params': {'error_bound': '0.01'}} if fidelity == 'bounded_abs' else {})}
                       for key in keys]
            if group == 'chimp-filters':
                for method in methods:
                    method['params'] = {'epsilon': '0.1', 'quality_mode': 'compatible'}
            document = {'schema': 'tsbench.experiment/1', 'name': name,
                        'output': str(run_root / (name + '-20261017')),
                        'datasets': deepcopy(datasets), 'methods': methods, 'profiles': [deepcopy(profile)],
                        'task': {'kind': kind, 'fidelity': fidelity, 'boundary': 'native_core',
                                 'lifecycle': lifecycle, 'cache_policy': 'natural',
                                 **({'error_bound': '0.01'} if fidelity == 'bounded_abs' else {})},
                        'execution': {'sessions': 2, 'rounds': 7, 'warmup_objects': 0,
                                      'native_loops': 8, 'native_warmup_loops': 2,
                                      'native_batch_memory_mb': 256, 'timeout_s': 120,
                                      'qualification_cache': True, 'save_artifacts': True,
                                      'seed': SEED, **overrides},
                        'analysis': {'summary': 'median_iqr', 'inference': 'none'}}
            documents.append(document)
    return documents


def static_requests(documents, registry):
    """Check declared input/quality/thread/model domains, with no native calls.

    Admission, content qualification and result validity remain runtime evidence.
    In particular, registry-eligible F Sprintz matrix requests remain requested
    but the direct route must reject them; registry eligibility is not core support.
    """
    cache = {}
    requests = []
    for document in documents:
        resolved = resolve(tomllib.loads(text(document)), ROOT)
        task = resolved['task']
        for dataset in resolved['datasets']:
            identity = json.dumps(dataset, sort_keys=True)
            if identity not in cache:
                cache[identity] = project(load_dataset(dataset), task)
            obj = cache[identity]
            for method in resolved['methods']:
                spec = registry.get(method['codec'])
                params = registry.resolve_params(method['codec'], method.get('params'))
                if spec.key == 'gorilla-prometheus-xor':
                    assert task['kind'] == 'records' and set(obj.components) == {'T', 'V'}
                    assert obj.components['T'].dtype.str == '<i8' and obj.components['T'].ndim == 1
                    values = obj.components['V']
                    assert values.ndim == 1 and values.size <= 65535
                    assert len(obj.components['T']) == len(values)
                    spec.validate_array(values)
                else:
                    assert len(obj.components) == 1
                    values = next(iter(obj.components.values()))
                    spec.validate_array(values)
                if spec.loss_mode == 'LOSSLESS':
                    assert task['fidelity'] == 'bitwise'
                elif spec.loss_mode == 'UNBOUNDED_LOSSY':
                    assert task['fidelity'] == 'empirical_quality'
                else:
                    assert task['fidelity'] == 'bounded_abs' and params['error_bound'] == task['error_bound']
                if spec.key in {'abba', 'fabba', 'qabba', 'deepzip', 'dzip'}:
                    assert values.ndim == 1
                if spec.key == 'deepzip':
                    alphabet = spec.document['adapter']['models'][params['model_key']]['alphabet_size']
                    assert values.max(initial=0) < alphabet
                if spec.key == 'dzip':
                    alphabet = set(values.tolist())
                    assert len(alphabet) != 9 and alphabet == set(range(len(alphabet)))
                if spec.key in {'neats-lossless-i64', 'leats-lossless-i64'}:
                    assert 1 <= values.size <= 65536
                if spec.key == 'self-star':
                    assert values.nbytes <= 16777216 and (values.size + params['block_size'] - 1) // params['block_size'] <= 1024
                for profile in resolved['profiles']:
                    assert profile['native_threads'] == (3 if spec.key == 'dzip' else 1)
                    requests.append({'configuration': document['name'] + '.toml', 'dataset': dataset['id'],
                                     'codec': spec.key, 'method': method['id'], 'profile': profile['id'],
                                     'boundary': 'native_core', 'lifecycle': task['lifecycle'],
                                     'fidelity': task['fidelity'], 'kind': task['kind'],
                                     'object_id': object_id(obj), 'raw_bytes': raw_bytes(obj),
                                     'value_count': int(values.size),
                                     'timestamp_count': len(obj.components['T']) if task['kind'] == 'records' else 0,
                                     'dtype': values.dtype.str, 'shape': list(values.shape), 'order': array_order(values),
                                     'expected_declared_domain': 'eligible',
                                     'qualification_or_timing_executed': False})
    return requests


def generate(destination, corpus, run_root):
    destination = Path(destination).resolve()
    corpus, run_root = Path(corpus).resolve(), Path(run_root).resolve()
    documents = definitions(corpus, run_root)
    registry = Registry(ROOT)
    requests = static_requests(documents, registry)
    coverage = defaultdict(Counter)
    for request in requests:
        coverage[request['codec']][request['lifecycle']] += 1
    assert set(coverage) == {spec.key for spec in registry.list()}
    assert all(counts['prepared'] > 0 and counts['fresh_request'] > 0 for counts in coverage.values())
    destination.mkdir(parents=True, exist_ok=True)
    configurations = []
    for document in documents:
        path = destination / (document['name'] + '.toml')
        body = text(document)
        frozen_write(path, body)
        configurations.append({'path': str(path), 'sha256': 'sha256:' + hashlib.sha256(body.encode()).hexdigest(),
                               'requests': sum(item['configuration'] == path.name for item in requests),
                               'sessions': 2, 'rounds': 7, 'native_loops': document['execution']['native_loops'],
                               'native_warmup_loops': 2, 'timeout_s': document['execution']['timeout_s']})
    design = {'schema': 'tsbench.native-all-design/1', 'date': '2026-10-17',
              'generated_from': str(Path(__file__).resolve()),
              'generator_sha256': 'sha256:' + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'scope': f'{len(coverage)} registry keys; direct native_core; every declared-domain request, status and reason retained',
              'selection': 'fixed original real windows and preserved development fixtures; no result-dependent tuning',
              'evidence_limit': 'static dtype/geometry/quality/profile/model checks only; not content qualification or measured success',
              'native_route_note': NATIVE_ROUTE_NOTE,
              'native_work_executed': False, 'configurations': configurations,
              'expected_codec_coverage': {key: dict(counts) for key, counts in sorted(coverage.items())},
              'request_count': len(requests), 'nominal_trial_count': len(requests) * 2 * 7,
              'nominal_measured_operations': sum(2 * 7 * next(document['execution']['native_loops'] for document in documents
                                                          if document['name'] + '.toml' == request['configuration']) for request in requests),
              'slow_model_protocol': 'DZip caller+2 Eigen workers, 64 original symbols, 2 loops instead of 8, 2 warmups, 600s timeout; fixed before any run',
              'records_protocol': 'one original T[N] plus one V[N]; no timestamp replication, masks, channel partition or synthetic timing axis',
              'dependencies': 'C/F layouts, nested source windows and repeated rounds are dependent; descriptive summaries only',
              'requests': requests}
    frozen_write(destination / 'design.json', json.dumps(design, ensure_ascii=False, indent=2) + '\n')
    return configurations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmark/experiments/native-all-20261017')
    parser.add_argument('--corpus', type=Path, default=Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus'))
    parser.add_argument('--run-root', type=Path, default=ROOT / 'runs')
    options = parser.parse_args()
    for item in generate(options.output, options.corpus, options.run_root):
        print(item['path'])
