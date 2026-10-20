"""Freeze supplementary neural paths without building or executing a codec.

The existing 64-symbol designs remain untouched. The complete original
257-symbol fixture reaches prediction and, for DZip COMBINED, an Adam update
whose updated weights are used for 65 further encoded/decoded symbols.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from generate_all_core_experiments import (
    ROOT, SEED, SINGLE, DZIP, fixture, frozen_write, static_requests, text,
)
from tsbench.registry import Registry


SOURCE_REFERENCES = (
    ('adapters/completed_rewrites/vendor/deepzip/src/deepzip.cpp',
     'encode_group/decode_group: first 64 symbols uniform; j=64..length-1 invokes predict; lanes=1'),
    ('adapters/completed_rewrites/vendor/deepzip/contract_v1.md',
     'N<65 is a safe short-stream extension; training is external model authoring, not codec execution'),
    ('adapters/completed_rewrites/vendor/dzip/src/codec.cpp',
     'encode_raw/decode_raw: first 64 uniform; predict thereafter; COMBINED adapts every 128 predicted symbols'),
    ('adapters/completed_rewrites/vendor/dzip/src/nn.cpp',
     'Network::predict executes forward; Network::train differentiates a full batch and advances one Adam step'),
    ('adapters/completed_rewrites/vendor/dzip/include/dzip_nn.hpp',
     'TrainOptions: scalar TensorFlow Adam, lr=5e-4, beta1=.9, beta2=.999, epsilon=1e-8, microbatch=0'),
    ('adapters/completed_rewrites/native/binding.cpp',
     'DZip input-dependent seeded model is freshly created per encode; mode selects bootstrap_cpu/combined_cpu'),
    ('benchmark/examples/data/manifest.json', 'Existing symbols4 fixture is uint8[257]; never padded or repeated'),
    ('benchmark/tools/generate_all_core_experiments.py', 'Shared static registry checks and serialization helpers'),
)


def configuration_text(document):
    return text(document).replace('Frozen by generate_all_core_experiments.py',
                                  'Frozen by generate_neural_core_experiments.py', 1)


def definitions(run_root):
    documents = []
    groups = (
        ('deepzip', [{'id': 'deepzip-biGRU', 'codec': 'deepzip',
                      'params': {'model_key': 'biGRU', 'lanes': 1}}], SINGLE, 8, 256),
        ('dzip', [{'id': 'dzip-bootstrap', 'codec': 'dzip', 'params': {'mode': 'BOOTSTRAP'}},
                  {'id': 'dzip-combined', 'codec': 'dzip', 'params': {'mode': 'COMBINED'}}],
         DZIP, 2, 1024),
    )
    for group, methods, profile, loops, budget in groups:
        for lifecycle in ('prepared', 'fresh_request'):
            name = 'native-neural-' + group + '-' + ('prepared' if lifecycle == 'prepared' else 'fresh')
            documents.append({
                'schema': 'tsbench.experiment/1', 'name': name,
                'output': str(run_root / (name + '-20261015')),
                'datasets': [fixture('symbols4')], 'methods': deepcopy(methods),
                'profiles': [deepcopy(profile)],
                'task': {'kind': 'values', 'fidelity': 'bitwise', 'boundary': 'native_core',
                         'lifecycle': lifecycle, 'cache_policy': 'natural'},
                'execution': {'sessions': 2, 'rounds': 7, 'warmup_objects': 0,
                              'native_loops': loops, 'native_warmup_loops': 2,
                              'native_batch_memory_mb': budget, 'timeout_s': 600,
                              'qualification_cache': True, 'save_artifacts': True, 'seed': SEED},
                'analysis': {'summary': 'median_iqr', 'inference': 'none'},
            })
    return documents


def generate(destination, run_root):
    destination, run_root = Path(destination).resolve(), Path(run_root).resolve()
    documents = definitions(run_root)
    requests = static_requests(documents, Registry(ROOT))
    coverage = defaultdict(Counter)
    for request in requests:
        assert request['shape'] == [257] and request['raw_bytes'] == request['value_count'] == 257
        combined = request['method'] == 'dzip-combined'
        request['mode'] = ('COMBINED' if combined else 'BOOTSTRAP') if request['codec'] == 'dzip' else 'biGRU'
        request['source_derived_operation_counts'] = {
            'scope': 'per encode and per decode; source-derived, not runtime counters',
            'uniform_symbols': 64, 'predict_calls': 193,
            'online_train_batches': 1 if combined else 0,
            'online_train_batch_windows': 128 if combined else 0,
            'adam_steps': 1 if combined else 0,
            'post_update_predict_calls': 65 if combined else 0,
        }
        coverage[request['codec']][request['lifecycle']] += 1
    assert len(documents) == 4 and len(requests) == 6
    destination.mkdir(parents=True, exist_ok=True)
    configurations = []
    for document in documents:
        path = destination / (document['name'] + '.toml')
        body = configuration_text(document)
        frozen_write(path, body)
        configurations.append({
            'path': str(path), 'sha256': 'sha256:' + hashlib.sha256(body.encode()).hexdigest(),
            'requests': sum(r['configuration'] == path.name for r in requests),
            'sessions': 2, 'rounds': 7, 'native_loops': document['execution']['native_loops'],
            'native_warmup_loops': 2, 'timeout_s': 600,
        })
    source = Path(__file__).resolve()
    design = {
        'schema': 'tsbench.native-all-design/1', 'design_role': 'supplemental_neural_paths',
        'date': '2026-10-15', 'generated_from': str(source),
        'generator_sha256': 'sha256:' + hashlib.sha256(source.read_bytes()).hexdigest(),
        'scope': 'DeepZip inference; DZip BOOTSTRAP inference and COMBINED online training; both lifecycles',
        'selection': 'Complete original symbols4.npy uint8[257], fixed from source thresholds before formal runs; no result-dependent tuning',
        'evidence_limit': 'static registry/input checks and source-derived branch counts only; not executed branch counters or measured success',
        'native_work_executed': False,
        'short_stream_evidence': {
            'design_path': str(ROOT / 'benchmark/experiments/native-all/design.json'),
            'preserved': True, 'symbols': 64, 'predict_calls_per_operation': 0,
            'online_train_batches_per_operation': 0,
            'scope': 'Original frozen short streams exercise uniform coding and complete model/container cost only; N<65 is a declared native extension',
        },
        'threshold_reason': 'N>64 starts prediction; COMBINED first trains after symbol index 191, once 128 predictions close. N=257 gives 193 predictions, one full train batch and 65 predictions using updated weights. N=192 would train only after the final symbol.',
        'training_note': 'Per encode and per decode, COMBINED uses one 128x64 context batch and 128 labels, one forward/backward plus Adam update; no partial tail update. BOOTSTRAP never trains. DeepZip training remains external model authoring. DZip default initial weights are native seeded/untrained, not an imported trained checkpoint.',
        'qualification_note': 'Qualification and independent decode are run by the framework before measured trials; nominal counts below cover measured operations only and do not prove runtime branch execution.',
        'source_references': [
            {'path': str(ROOT / path), 'sha256': 'sha256:' + hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
             'evidence': evidence} for path, evidence in SOURCE_REFERENCES
        ],
        'configurations': configurations,
        'expected_codec_coverage': {key: dict(counts) for key, counts in sorted(coverage.items())},
        'request_count': len(requests),
        'nominal_trial_count': sum(c['requests'] * c['sessions'] * c['rounds'] for c in configurations),
        'nominal_measured_operations': sum(c['requests'] * c['sessions'] * c['rounds'] * c['native_loops'] for c in configurations),
        'dependencies': 'Same deterministic fixture and repeated rounds; descriptive summaries only. Source counts are per complete encode/decode and inner loops are not independent samples.',
        'requests': requests,
    }
    frozen_write(destination / 'design.json', json.dumps(design, ensure_ascii=False, indent=2) + '\n')
    return configurations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'benchmark/experiments/native-neural')
    parser.add_argument('--run-root', type=Path, default=ROOT / 'runs')
    options = parser.parse_args()
    for item in generate(options.output, options.run_root):
        print(item['path'])
