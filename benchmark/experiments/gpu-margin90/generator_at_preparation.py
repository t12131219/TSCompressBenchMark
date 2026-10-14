"""Freeze GPU margin sensitivity and real single-channel inputs, CPU only.

Creates new configs/evidence using unchanged source files. It does not load
a native library, run CUDA, modify prior runs, or alter measurement sources.
"""
from __future__ import annotations
import argparse
import copy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import numpy as np

from tsbench.data import load_dataset, object_id, project
from tsbench.gpu import _configuration_id, _source_identity, capability, load
from tsbench.records import file_hash, stable_hash, write_json


def empty_directory(path):
    path = Path(path).resolve()
    if path.exists() and any(path.iterdir()):
        raise FileExistsError('new empty preparation directory required: ' + str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def toml_scalar(value):
    if isinstance(value, dict):
        return '{ ' + ', '.join(json.dumps(key) + ' = ' + toml_scalar(item) for key, item in value.items()) + ' }'
    if isinstance(value, list):
        return '[' + ', '.join(toml_scalar(item) for item in value) + ']'
    if isinstance(value, bool):
        return str(value).lower()
    return json.dumps(value, ensure_ascii=False)


def write_config(path, template, datasets, target, native, name):
    lines = ['# Independent post-observation margin sensitivity; prior failures remain unchanged.',
             'schema = "tsbench.gpu-experiment/1"', 'name = ' + json.dumps(name),
             'asset_root = ' + json.dumps(template['_asset_root']),
             'boundaries = ["host_to_host", "device_resident"]']
    for section, fields in [('task', {**template['task'], 'error_bound': target}),
                             ('profile', template['profile']), ('execution', template['execution'])]:
        lines += ['', '[' + section + ']', *(key + ' = ' + toml_scalar(value) for key, value in fields.items())]
    lines += ['', '[[methods]]', 'id = "cuszp-fixed-margin90"', 'codec = "cuszp-fixed-1d"',
              'error_bound = ' + json.dumps(native)]
    for dataset in datasets:
        lines += ['', '[[datasets]]', *(key + ' = ' + toml_scalar(value) for key, value in dataset.items())]
    path.write_text('\n'.join(lines) + '\n')
    resolved = load(path)
    projections = []
    for dataset in resolved['datasets']:
        original = project(load_dataset(dataset, resolved['_base_dir']), resolved['task'])
        supported = capability(original, resolved['methods'][0], resolved['task'])
        projections.append({'dataset_id': dataset['id'], 'raw_object_id': object_id(original),
                            'input_lineage': original.lineage,
                            'dtype': supported['dtype'], 'count': supported['count'],
                            'codec_requested_absolute_tolerance_text': supported['codec_requested_absolute_tolerance_text'],
                            'codec_requested_absolute_tolerance': supported['codec_requested_absolute_tolerance'],
                            'codec_effective_absolute_tolerance': supported['codec_effective_absolute_tolerance'],
                            'codec_effective_absolute_tolerance_hex': supported['codec_effective_absolute_tolerance'].hex(),
                            'task_requested_bound': supported['task_requested_bound'],
                            'declared_capability': True, 'runtime_qualification': 'pending'})
    return {'path': str(path), 'sha256': file_hash(path), 'configuration_id': _configuration_id(resolved),
            'cases': len(datasets) * len(resolved['boundaries']),
            'planned_trials': len(datasets) * len(resolved['boundaries']) * resolved['execution']['sessions'] * resolved['execution']['rounds'],
            'task_error_bound': target, 'codec_error_bound': native, 'margin_fraction_decimal': '0.9',
            'inputs': projections}


def historical_evidence(root):
    history, predictions = [], []
    for label, target in [('0p01', '0.01'), ('0p1', '0.1')]:
        location = root / 'runs/gpu' / ('cuszp-formal-' + label + '-20261013')
        manifest = json.loads((location / 'manifest.json').read_bytes())
        summary = json.loads((location / 'summary.json').read_bytes())
        files = [{'path': str(location / name), 'sha256': file_hash(location / name)}
                 for name in ('manifest.json', 'observations.jsonl', 'summary.json', 'report.md')]
        failures = []
        for case in manifest['cases']:
            qualification = case.get('qualification', {})
            verification = qualification.get('verification', {})
            if case['status'] != 'ready':
                failures.append({'dataset_id': case['dataset_id'], 'boundary': case['boundary'],
                                 'status': case['status'], 'stage': qualification.get('stage'),
                                 'reason': qualification.get('reason'), 'max_abs': verification.get('max_abs'),
                                 'violation_count': verification.get('violation_count'),
                                 'task_requested_bound': target,
                                 'over_requested_bound_decimal': str(Decimal(str(verification['max_abs'])) - Decimal(target)),
                                 'artifact_path': qualification.get('artifact_path'),
                                 'artifact_sha256': file_hash(qualification['artifact_path']) if qualification.get('artifact_path') else None,
                                 'codec_quality_metadata': qualification.get('codec_quality_metadata')})
        history.append({'path': str(location), 'run_id': manifest['run_id'], 'files': files,
                        'formal_status_counts': summary['terminal_status_counts'],
                        'execution_source_unchanged': manifest['execution_source_unchanged'],
                        'native_execution_source_unchanged': manifest['native_execution_source_unchanged'],
                        'failures': failures})
        # CPU arithmetic replay of unchanged f32 source formulas is explanatory,
        # not a substitute for CUDA timing, stream decoding, or qualification.
        bound = np.float32(float(target))
        if float(bound) > float(target):
            bound = np.nextafter(bound, np.float32(0))
        reciprocal = np.float32(np.float32(0.5) / bound)
        for suffix in ('tail-33', 'medium-32769', 'large-1048576'):
            original = np.load(root / 'benchmark/experiments/gpu-p4/fixtures' / ('f32-' + suffix + '.npy'), allow_pickle=False)
            multiplied = np.multiply(original, reciprocal, dtype=np.float32)
            added = np.add(multiplied, np.float32(0.5), dtype=np.float32)
            quantized = added.astype(np.int32) - (multiplied < np.float32(-0.5)).astype(np.int32)
            reconstructed = np.multiply(np.multiply(quantized.astype(np.float32), bound, dtype=np.float32), np.float32(2), dtype=np.float32)
            errors = np.abs(original.astype(np.float64) - reconstructed.astype(np.float64))
            predictions.append({'task_requested_bound': target, 'dataset_id': 'f32-' + suffix,
                                'codec_effective_tolerance': float(bound), 'reciprocal_f32': float(reciprocal),
                                'predicted_max_abs': float(np.max(errors)),
                                'predicted_violation_count': int(np.count_nonzero(errors > float(target))),
                                'scope': 'CPU NumPy f32 arithmetic replay of upstream formulas only; no CUDA/native codec or stream execution'})
    return history, predictions


def prepare(root, config_directory):
    root = Path(root).resolve()
    configs = empty_directory(config_directory)
    before = _source_identity(root=root)
    generator = Path(__file__).resolve()
    (configs / 'generator_at_preparation.py').write_bytes(generator.read_bytes())
    template = load(root / 'benchmark/experiments/gpu-p4/gpu-abs-0p01.toml')
    history, predictions = historical_evidence(root)
    synthetic = copy.deepcopy(template['datasets'])
    for dataset in synthetic:
        dataset['path'] = str((Path(template['_base_dir']) / dataset['path']).resolve())
    catalog_path = root / 'registry/datasets/catalog.json'
    catalog = json.loads(catalog_path.read_bytes())
    catalog_entries = {entry['id']: entry for entry in catalog['datasets']}
    real_datasets, extraction = [], []
    source_columns = [('etth1', 'ETTh1.csv', 'OT', 'source_units_unverified', 'oil temperature; exact physical unit unverified in the frozen source evidence'),
                      ('weather', 'weather.csv', 'T (degC)', 'degree_Celsius', 'column header explicitly labels degC')]
    corpus = Path('/home/fzg/PycharmProjects/材料/TSBench_Corpus')
    for source_id, filename, column, unit, unit_reason in source_columns:
        source_path = corpus / filename
        card = catalog_entries[source_id]
        for length in (128, 512):
            dataset_id = source_id + '-single-f64-n' + str(length)
            parse = {'id': dataset_id, 'format': 'csv', 'path': str(source_path), 'dtype': '<f8',
                     'encoding': 'utf-8', 'delimiter': ',', 'columns': [column],
                     'timestamp_column': 'date', 'timestamp_parser': 'datetime64', 'time_unit': 'ns',
                     'missing': 'reject', 'start': 2048, 'stop': 2048 + length, 'step': 1,
                     'source': source_id, 'order': 'C'}
            parsed = project(load_dataset(parse), 'values')
            values = parsed.components['V']
            if values.shape != (length,) or values.dtype.str != '<f8':
                raise ValueError('real GPU projection shape/dtype differs from declared source window')
            provenance = {'source_id': source_id, 'source_csv_path': str(source_path),
                          'source_csv_sha256': file_hash(source_path), 'column': column,
                          'source_row_window': [2048, 2048 + length], 'step': 1,
                          'source_dtype_conversion': 'CSV decimal via explicit Python float to little-endian f64',
                          'rank_projection': 'existing loader represents exactly one selected CSV column as V[N]; no flattening of multiple channels',
                          'normalization': 'none', 'resampling': 'none', 'missing': 'reject',
                          'unit': unit, 'unit_evidence': unit_reason,
                          'license_status': card['license']['status'], 'license_spdx': card['license']['spdx'],
                          'license_scope': card['license']['scope'],
                          'data_distribution_policy': 'unchanged external local CSV only; no source data or derived windows bundled or redistributed'}
            schema = {'roles': {'V': 'V'}, 'topology': 'UTS', 'columns': [column],
                      'gpu_source_projection': provenance}
            dataset = {**parse, 'schema': schema,
                       'source': source_id + ':column=' + column + ':source_rows=2048:' + str(2048 + length),
                       'license': 'unchanged external local source; ' + card['license']['spdx'] + '; see schema provenance'}
            real_datasets.append(dataset)
            loaded = project(load_dataset(dataset), 'values')
            if loaded.components['V'].tobytes() != values.tobytes() or loaded.components['V'].dtype != values.dtype:
                raise ValueError('GPU projection differs from frozen CSV values')
            extraction.append({'dataset': dataset, 'source_parse_rule': parse, 'parsed_csv_object_id': object_id(parsed),
                               'gpu_object_id': object_id(loaded),
                               'source_csv_sha256': file_hash(source_path), 'values_bitwise_equal_to_selected_csv_column': True,
                               'declared_count': length, 'declared_dtype': '<f8'})
    configs_created = []
    for label, target, native in [('0p01', '0.01', '0.009'), ('0p1', '0.1', '0.09')]:
        for family, datasets in [('synthetic', synthetic), ('real-single-f64', real_datasets)]:
            name = 'gpu-' + family + '-margin90-abs-' + label
            configs_created.append(write_config(configs / (name + '.toml'), template, datasets, target, native, name))
    after = _source_identity(root=root)
    if before != after:
        raise RuntimeError('GPU measurement source changed during CPU-only preparation')
    if any(file_hash(item['path']) != item['sha256'] for run in history for item in run['files']):
        raise RuntimeError('historical GPU evidence changed during follow-up preparation')
    freeze = {'schema': 'tsbench.gpu-followup-preparation/1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'gpu_work_executed': False, 'codec_runtime_qualification_executed': False,
              'historical_run_records_modified': False, 'measurement_sources_modified': False,
              'generator_path': str(generator), 'generator_sha256': file_hash(generator),
              'generator_snapshot': str(configs / 'generator_at_preparation.py'),
              'generator_snapshot_sha256': file_hash(configs / 'generator_at_preparation.py'),
              'numpy': np.__version__, 'gpu_execution_source_id': before['source_id'],
              'catalog_path': str(catalog_path), 'catalog_sha256': file_hash(catalog_path),
              'historical_failure_evidence': history, 'f32_source_arithmetic_replay': predictions,
              'new_configs': configs_created, 'real_source_extractions': extraction,
              'design': {'margin_policy': 'codec absolute parameter is exactly decimal 0.9 times unchanged task absolute request, then existing dtype canonicalization; both dtypes use the same declared fraction',
                         'selection_status': 'post-observation sensitivity chosen after original equal-bound f32 quality failures; not a blind pre-registered optimal parameter or universal bound',
                         'data_policy': 'synthetic files and values unchanged; real source row envelope [2048,2560), n128 prefix of n512; prior CPU study already used these windows',
                         'source_policy': 'two sources; lengths, boundaries, task bounds, rounds and repeated sessions are dependent views, not independent source samples',
                         'unit_policy': 'ETT OT source units unverified; weather T column degC; describe separately, no pooled absolute-quality interpretation',
                         'comparison_policy': 'GPU host_to_host/device_resident are separate estimands; no CPU object_memory baseline comparison without matching canonical input/task/units/storage and declared boundary distinction',
                         'real_file_distribution': 'unchanged external local CSV files; no raw or derived data bundled or redistributed',
                         'pending': 'real CUDA exact-input qualification, full schedule, quality and resources required before any new success/performance conclusion'}}
    freeze['freeze_id'] = stable_hash(freeze)
    write_json(configs / 'preparation.json', freeze)
    return configs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--config-directory', type=Path, required=True)
    arguments = parser.parse_args()
    print(prepare(arguments.root, arguments.config_directory))
