"""P4 CUDA object boundary, independent of the CPU C1 executor.

Importing this module performs no CUDA or NumPy work. Resource enforcement
precedes native imports in a fresh worker. No reset, retry or CPU fallback.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid

from .records import append, canonical_json, file_hash, read_jsonl, stable_hash, write_json

KEY = 'cuszp-fixed-1d'
BOUNDARIES = {'host_to_host', 'device_resident'}
SUITE_VERSION = 'gpu-p4-admission/1'
EVENT_SCOPE = 'completed CUDA stream work: scratch/output zeroing, host-path H2D when present, FIXED kernel and encoded rate/size D2H; not kernel-only'
ALLOCATION_SCOPE = 'source-accounted simultaneous adapter-owned requested allocation capacity; excludes CUDA context/runtime/cache, allocator granularity and pre-existing prepared owners; not a sampled VRAM peak'


def _keys(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'{label}: invalid table or unknown fields')


def _integer(value, label, minimum=1):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be integer >= {minimum}')


def _number(value, label, minimum=0, strict=False):
    try:
        actual = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f'{label} must be a finite quality number') from error
    if type(value) is bool or not math.isfinite(actual) or (actual <= minimum if strict else actual < minimum):
        raise ValueError(f'{label} must be a finite quality number')


def resolve(source, base_dir=None):
    """Explicit standalone schema; GPU pointers never enter CPU config."""
    config = copy.deepcopy(source)
    _keys(config, {'schema', 'name', 'output', 'asset_root', 'build_root', 'datasets', 'methods',
                   'profile', 'task', 'boundaries', 'execution'}, 'GPU experiment')
    if config.get('schema') != 'tsbench.gpu-experiment/1' or not isinstance(config.get('name'), str) or not config['name']:
        raise ValueError('need tsbench.gpu-experiment/1 and name')
    base = Path(base_dir or '.').resolve()
    root = Path(config.get('asset_root', Path(__file__).resolve().parents[3])).expanduser()
    root = (base / root).resolve() if not root.is_absolute() else root.resolve()
    build = Path(config.get('build_root', root / 'build/tsbench-gpu')).expanduser()
    output = Path(config.get('output', root / 'runs/gpu' / config['name'])).expanduser()
    config.update(_base_dir=str(base), _asset_root=str(root),
                  _build_root=str((base / build).resolve() if not build.is_absolute() else build.resolve()),
                  output=str((base / output).resolve() if not output.is_absolute() else output.resolve()))
    from .data import validate_selection_spec
    from .config import resolve as cpu_resolve
    # Reuse the strict loader grammar, not CPU scheduling or CPU capabilities.
    datasets = config.get('datasets')
    validated = cpu_resolve({'schema': 'tsbench.experiment/1', 'name': 'loader-grammar',
                             'datasets': datasets, 'methods': [{'id': 'raw', 'codec': 'raw-store'}]}, base)
    config['datasets'] = validated['datasets']
    for dataset in config['datasets']:
        validate_selection_spec(dataset)
    methods = config.get('methods')
    if not isinstance(methods, list) or not methods:
        raise ValueError('GPU methods must be a nonempty array')
    ids = set()
    for method in methods:
        _keys(method, {'id', 'codec', 'error_bound'}, 'GPU method')
        if not isinstance(method.get('id'), str) or not method['id'] or method['id'] in ids or method.get('codec') != KEY:
            raise ValueError('unique method id and genuine cuszp-fixed-1d codec required')
        ids.add(method['id'])
        _number(method.get('error_bound'), 'codec error_bound', strict=True)
        method['_requested_error_bound'] = str(method['error_bound'])
        method['error_bound'] = float(method['error_bound'])
    task = config.setdefault('task', {})
    _keys(task, {'kind', 'fidelity', 'error_bound', 'relative_floor', 'lifecycle', 'cache_policy',
                 'special_values', 'invalid_values'}, 'GPU task')
    task.update({'kind': 'values', 'fidelity': 'bounded_abs', 'lifecycle': 'independent_object',
                 'cache_policy': 'natural', 'special_values': 'bitwise', 'invalid_values': 'preserve', **task})
    if task['kind'] != 'values' or task['lifecycle'] != 'independent_object' or task['cache_policy'] != 'natural':
        raise ValueError('GPU supports values/independent_object/natural only')
    if task['fidelity'] not in {'bounded_abs', 'range_relative', 'point_relative', 'empirical_quality'}:
        raise ValueError('GPU supports declared lossy quality tasks only')
    if task['fidelity'] != 'empirical_quality':
        _number(task.get('error_bound'), 'task error_bound')
    elif 'error_bound' in task:
        _number(task['error_bound'], 'task error_bound')
    if 'relative_floor' in task:
        _number(task['relative_floor'], 'relative_floor')
    if task['special_values'] != 'bitwise' or task['invalid_values'] != 'preserve':
        raise ValueError('special and invalid value policies must remain explicit and strict')
    boundaries = config.setdefault('boundaries', ['host_to_host', 'device_resident'])
    if not isinstance(boundaries, list) or not boundaries or len(set(boundaries)) != len(boundaries) or not set(boundaries) <= BOUNDARIES:
        raise ValueError('unique host_to_host/device_resident boundaries required')
    profile = config.setdefault('profile', {})
    _keys(profile, {'id', 'device', 'device_index', 'native_threads', 'object_workers', 'affinity',
                    'host_memory_limit_mb', 'vram_limit_mb', 'runtime_preload'}, 'GPU profile')
    profile.update({'id': 'gpu-single', 'device': 'cuda', 'device_index': 0, 'native_threads': 1,
                    'object_workers': 1, **profile})
    if profile['device'] != 'cuda' or profile['object_workers'] != 1 or profile['native_threads'] != 1:
        raise ValueError('GPU sequential executor requires cuda, one object worker and one native host thread')
    _integer(profile['device_index'], 'device_index', 0)
    for name in ('host_memory_limit_mb', 'vram_limit_mb'):
        if name in profile:
            _integer(profile[name], name)
    if 'affinity' in profile and (not isinstance(profile['affinity'], list) or not profile['affinity'] or
                                any(type(cpu) is not int or cpu < 0 for cpu in profile['affinity']) or
                                len(set(profile['affinity'])) != len(profile['affinity'])):
        raise ValueError('affinity must be unique nonnegative CPU IDs')
    from .runtime import worker_environment
    worker_environment({}, profile)
    execution = config.setdefault('execution', {})
    _keys(execution, {'sessions', 'rounds', 'warmup_objects', 'seed', 'timeout_s', 'save_artifacts'}, 'GPU execution')
    execution.update({'sessions': 3, 'rounds': 7, 'warmup_objects': 2, 'seed': 20261013,
                      'timeout_s': 120, 'save_artifacts': True, **execution})
    for name in ('sessions', 'rounds'):
        _integer(execution[name], name)
    _integer(execution['warmup_objects'], 'warmup_objects', 0)
    _integer(execution['seed'], 'seed', 0)
    _number(execution['timeout_s'], 'timeout_s', strict=True)
    if type(execution['save_artifacts']) is not bool:
        raise ValueError('save_artifacts must be boolean')
    return config


def load(path):
    path = Path(path).expanduser().resolve(strict=True)
    config = resolve(tomllib.loads(path.read_text()), path.parent)
    config['_config_path'] = str(path)
    return config


def apply_profile(profile):
    """Actual worker resource readback before importing NumPy/native libraries."""
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
        os.environ[key] = '1'
    if profile.get('vram_limit_mb') is not None:
        raise ValueError('unsupported: requested VRAM limit cannot be enforced by this adapter; omit the limit for an explicitly unbounded VRAM profile')
    affinity = profile.get('affinity')
    if affinity is not None:
        if not hasattr(os, 'sched_setaffinity'):
            raise RuntimeError('unavailable: requested host affinity cannot be enforced')
        os.sched_setaffinity(0, set(affinity))
    host = {'requested_mb': profile.get('host_memory_limit_mb'), 'implemented': False,
            'mechanism': 'RLIMIT_AS', 'effective_soft_bytes': None, 'effective_hard_bytes': None,
            'scope': 'host process virtual address space, including driver mappings; not RSS', 'reason': None}
    try:
        import resource
        if host['requested_mb'] is not None:
            amount = host['requested_mb'] * 1024**2
            resource.setrlimit(resource.RLIMIT_AS, (amount, amount))
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        host.update(effective_soft_bytes=None if soft < 0 else soft, effective_hard_bytes=None if hard < 0 else hard,
                    implemented=host['requested_mb'] is not None and soft == amount and hard == amount)
        if host['requested_mb'] is None:
            host['reason'] = 'no host virtual address limit requested; inherited limit read back'
    except (ImportError, OSError, ValueError) as error:
        host['reason'] = f'{type(error).__name__}: {error}'
        if host['requested_mb'] is not None:
            raise RuntimeError('unavailable: requested host memory limit could not be enforced: ' + host['reason']) from error
    return {'device': 'cuda', 'device_index': profile['device_index'],
            'requested_native_threads': 1, 'effective_native_threads': 1,
            'thread_definition': 'adapter algorithm host parallelism; excludes driver/runtime helper threads',
            'thread_evidence': 'adapter has no algorithm host thread pool; driver/runtime process Threads are observed separately',
            'object_workers': 1,
            'affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
            'host_memory_limit': host,
            'vram_limit': {'requested_mb': profile.get('vram_limit_mb'), 'implemented': False,
                           'effective_bytes': None, 'reason': 'no enforceable per-process VRAM budget API in this adapter; allocation accounting is separate'},
            'cuda_context_scope': 'library/device initialization outside object clocks; new interpreter per experiment session',
            'gpu_event_scope': EVENT_SCOPE, 'gpu_allocation_scope': ALLOCATION_SCOPE}


def process_snapshot():
    """Adjacent process facts; never interpreted as a per-trial resource peak."""
    values = {}
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            name, separator, value = line.partition(':')
            if separator and name in {'Threads', 'VmSize', 'VmRSS', 'VmHWM', 'VmPeak'}:
                values[name] = value.strip()
    except OSError:
        pass
    return {'pid': os.getpid(), 'proc_status': values or None,
            'null_reason': None if values else 'procfs process status unavailable',
            'scope': 'adjacent process status, VmHWM/VmPeak are process lifetime high-water; Threads includes runtime helpers'}


def loaded_gpu_runtime(dependencies):
    from .runtime import loaded_runtime
    import numpy as np
    runtime = loaded_runtime(dependencies)
    libraries = {entry['path']: entry for entry in runtime['libraries']}
    maps = Path('/proc/self/maps')
    if maps.is_file():
        for line in maps.read_text().splitlines():
            fields = line.split(maxsplit=5)
            if len(fields) == 6 and fields[5].startswith('/'):
                path = Path(fields[5])
                if path.name.startswith(('libcuda', 'libnvidia', 'libcudart')):
                    path = path.resolve(strict=True)
                    libraries[str(path)] = {'path': str(path), 'sha256': file_hash(path)}
    runtime.update(libraries=[libraries[key] for key in sorted(libraries)], numpy=np.__version__, python=sys.version,
                   gpu_scope='actual mapped CUDA runtime/driver/NVIDIA libraries plus build runtime dependencies and explicit preload')
    return runtime


def classify_error(error, stage):
    from .worker import classify_error as cpu_classify
    result = cpu_classify(error)
    declared = getattr(error, 'classification', None)
    if declared in {'error', 'unsupported', 'unavailable', 'oom'}:
        result['status'] = declared
    if isinstance(error, OSError) and stage == 'initialization.library':
        result['status'] = 'unavailable'
    result['stage'] = getattr(error, 'measurement_stage', stage)
    native = getattr(error, 'status', None)
    if type(native) is int:
        result['native_status'] = native
    result['device_recovery_confirmed'] = getattr(error, 'device_recovery_confirmed', False if native in {4, 5, 6} else None)
    for field in ('diagnostic_encode_ns', 'diagnostic_decode_ns', 'input_unchanged'):
        if hasattr(error, field):
            result[field] = getattr(error, field)
    return result


def live_descriptor(original, metadata):
    name = next(iter(original.components))
    return {'schema': dict(original.schema), 'component': name, 'dtype': metadata['dtype'],
            'count': metadata['count'], 'shape': [metadata['count']], 'order': 'C',
            'codec': KEY, 'codec_effective_absolute_tolerance': metadata['error_bound'], 'mode': 'FIXED',
            'source_format': 'cuSZp 1D FIXED native payload with checked rate table',
            'representation': 'device payload owner plus host recovery descriptor',
            'metadata_location': 'host', 'payload_location': 'device'}


def pack_object(encoded, descriptor):
    from .artifact import pack_bundle
    from .bridges.cuszp import unpack
    metadata, _ = unpack(encoded.wire)
    if any(metadata[key] != descriptor[key] for key in ('dtype', 'count')) or metadata['error_bound'] != descriptor['codec_effective_absolute_tolerance']:
        raise ValueError('materialized wire differs from completed live artifact')
    part = {'codec': KEY, 'params': {'error_bound': metadata['error_bound'], 'mode': 'FIXED'},
            'dtype': metadata['dtype'], 'shape': [metadata['count']], 'order': 'C',
            'offset': 0, 'length': len(encoded.wire), 'row_start': 0, 'row_stop': metadata['count'],
            'sha256': hashlib.sha256(encoded.wire).hexdigest()}
    return pack_bundle({'schema_version': 'tsbench.object/1', 'schema': descriptor['schema'],
                        'gpu_object_format': 'tsbench.cuszp-object/1',
                        'components': [{'name': descriptor['component'], 'dtype': metadata['dtype'],
                                        'shape': [metadata['count']], 'order': 'C', 'parts': [part]}]}, encoded.wire)


def unpack_object(wire):
    """All reconstruction schema and typed metadata derive from actual bytes."""
    from .artifact import read_bundle_prefix, validate_descriptor
    from .bridges.cuszp import unpack
    descriptor, body = read_bundle_prefix(wire)
    components = validate_descriptor(descriptor, body)
    if descriptor.get('gpu_object_format') != 'tsbench.cuszp-object/1' or len(components) != 1:
        raise ValueError('invalid GPU object format/component count')
    component = components[0]
    if len(component['parts']) != 1:
        raise ValueError('GPU object requires exactly one native payload')
    part = component['parts'][0]
    metadata, native = unpack(body)
    if (part['codec'] != KEY or part['params'] != {'error_bound': metadata['error_bound'], 'mode': 'FIXED'} or
            part['shape'] != [metadata['count']] or component['shape'] != [metadata['count']] or
            part['dtype'] != metadata['dtype'] or component['dtype'] != metadata['dtype'] or
            part['order'] != 'C' or component['order'] != 'C' or part['offset'] != 0 or part['length'] != len(body) or
            part.get('row_start') != 0 or part.get('row_stop') != metadata['count'] or
            descriptor['schema'].get('roles', {}).get(component['name'], component['name']) != 'V'):
        raise ValueError('GPU object descriptor differs from native typed wire')
    return descriptor['schema'], component['name'], metadata, body, len(native)


def capability(original, method, task):
    import numpy as np
    from .bridges.cuszp import MAX_N, canonical_error_bound
    if len(original.components) != 1:
        raise ValueError('unsupported: cuSZp values requires one V component without mask')
    name, array = next(iter(original.components.items()))
    if original.schema.get('roles', {}).get(name, name) != 'V' or array.ndim != 1 or not array.flags.c_contiguous or array.dtype.str not in {'<f4', '<f8'}:
        raise ValueError('unsupported: cuSZp requires contiguous little-endian float32/float64 UTS values')
    if not 0 < array.size <= MAX_N:
        raise ValueError('unsupported: cuSZp supports 1..16777216 values')
    bound = canonical_error_bound(array.dtype, method['error_bound'])
    normal = (array == 0) | (np.abs(array) >= np.finfo(array.dtype).tiny)
    if not np.all(np.isfinite(array) & normal & ~((array == 0) & np.signbit(array))):
        raise ValueError('unsupported: cuSZp source excludes negative zero/subnormal/NaN/infinity')
    if np.any(np.abs(array.astype(np.longdouble)) / (2 * np.longdouble(bound)) > 2**28):
        raise ValueError('unsupported: cuSZp source exceeds conservative signed-int quantization domain')
    # Native config also requires the dtype-domain reciprocal to remain finite.
    with np.errstate(over='ignore'):
        reciprocal = np.array(0.5, dtype=array.dtype) / np.array(bound, dtype=array.dtype)
    if not np.isfinite(reciprocal):
        raise ValueError('unsupported: cuSZp reciprocal exceeds dtype domain')
    return {'supported': True, 'dtype': array.dtype.str, 'count': int(array.size),
            'codec_requested_absolute_tolerance_text': method.get('_requested_error_bound', str(method['error_bound'])),
            'codec_requested_absolute_tolerance': float(method['error_bound']),
            'codec_effective_absolute_tolerance': bound,
            'parameter_policy': 'float32 tolerance rounded downward to a representable normal value; float64 exact conversion',
            'domain': 'one finite-normal or positive-zero 1D V array, no masks/special bits, conservative magnitude <=2^28 quantization bins',
            'task_requested_bound': str(task.get('error_bound')) if 'error_bound' in task else None}


def measure_object(original, method, task, boundary, library, device, *, expected_fingerprint=None, on_stage=None):
    """Completed operation clocks; validation, IPC and persistence are outside."""
    from .bridges import cuszp
    from .data import TimeSeriesObject, fingerprint
    from .validate import verify
    before = fingerprint(original)
    if expected_fingerprint is not None and before != expected_fingerprint:
        raise ValueError('trusted canonical input changed before GPU operation')
    array = next(iter(original.components.values()))
    phase = 'input_validation'
    wire = None
    costs = {}
    encode_info = decode_info = None
    encode_ns = decode_ns = None
    def stage(value):
        nonlocal phase
        phase = value
        if on_stage:
            on_stage(value)
    def elapsed(operation, label):
        started = time.perf_counter_ns()
        result = operation()
        costs[label] = time.perf_counter_ns() - started
        return result
    try:
        if boundary == 'host_to_host':
            stage('encode')
            started = time.perf_counter_ns()
            with cuszp.Session(array.dtype, array.size, method['error_bound'], device, library) as session:
                encoded = session.encode_host(array)
                descriptor = live_descriptor(original, encoded.metadata)
                wire = pack_object(encoded, descriptor)
                encode_info = encoded.info
            encode_ns = time.perf_counter_ns() - started
            stage('decode')
            started = time.perf_counter_ns()
            schema, name, metadata, native_wire, payload_bytes = unpack_object(wire)
            with cuszp.Session(metadata['dtype'], metadata['count'], metadata['error_bound'], device, library) as session:
                restored_array, decode_info = session.decode_host(native_wire)
                restored = TimeSeriesObject({name: restored_array}, schema)
            decode_ns = time.perf_counter_ns() - started
            live_bytes = None
        elif boundary == 'device_resident':
            stage('prepare_device_input')
            prepared = elapsed(lambda: cuszp.prepare_device_input(array, method['error_bound'], device, library), 'prepare_device_input_ns')
            try:
                stage('encode')
                started = time.perf_counter_ns()
                with cuszp.Session(array.dtype, array.size, method['error_bound'], device, library) as session:
                    payload = session.encode_device(prepared)
                    descriptor = live_descriptor(original, payload.metadata)
                    descriptor_bytes = canonical_json(descriptor)
                    encode_info = payload.info
                encode_ns = time.perf_counter_ns() - started
                live_bytes = len(descriptor_bytes) + payload.metadata['payload_bytes']
                try:
                    stage('encode_materialize')
                    encoded = elapsed(payload.materialize, 'encode_materialize_csp1_ns')
                    wire = elapsed(lambda: pack_object(encoded, descriptor), 'persisted_object_pack_ns')
                finally:
                    elapsed(payload.close, 'encode_output_release_ns')
                stage('prepared_input_validation')
                prepared_array = elapsed(prepared.materialize, 'prepared_input_check_d2h_ns')
                prepared_unchanged = prepared_array.tobytes() == array.tobytes()
            finally:
                elapsed(prepared.close, 'prepared_input_release_ns')
            stage('install_device_payload')
            schema, name, metadata, native_wire, payload_bytes = elapsed(lambda: unpack_object(wire), 'decode_descriptor_parse_ns')
            installed = elapsed(lambda: cuszp.install_device_payload(native_wire, device, library), 'install_device_payload_ns')
            try:
                stage('decode')
                started = time.perf_counter_ns()
                # Only metadata parsed from the actual wire configures this fresh decoder.
                with cuszp.Session(metadata['dtype'], metadata['count'], metadata['error_bound'], device, library) as session:
                    decoded = session.decode_device(installed)
                    decode_info = decoded.info
                    decoded_schema = copy.deepcopy(schema)
                decode_ns = time.perf_counter_ns() - started
                try:
                    stage('decode_materialize')
                    restored_array = elapsed(decoded.materialize, 'decode_materialize_d2h_ns')
                    restored = TimeSeriesObject({name: restored_array}, decoded_schema)
                finally:
                    elapsed(decoded.close, 'decode_output_release_ns')
            finally:
                elapsed(installed.close, 'installed_payload_release_ns')
        else:
            raise ValueError('unknown GPU boundary')
        stage('validation')
        verification = verify(original, restored, task)
        unchanged = fingerprint(original) == before
        verification['input_unchanged'] = unchanged
        if boundary == 'device_resident':
            verification['prepared_device_input_unchanged'] = prepared_unchanged
            unchanged = unchanged and prepared_unchanged
        passed = verification['passed'] and unchanged
        verification['passed'] = passed
        metadata = unpack_object(wire)[2]
        payload_bytes = unpack_object(wire)[4]
        return {'status': 'ok' if passed else 'error', 'stage': 'complete' if passed else 'validation',
                'reason': None if passed else verification.get('reason') or 'input_modified',
                'encode_ns': encode_ns, 'decode_ns': decode_ns, 'loops': 1,
                'raw_bytes': array.nbytes, 'stored_bytes': len(wire), 'payload_bytes': payload_bytes,
                'header_bytes': len(wire) - payload_bytes, 'value_count': int(array.size),
                'bits_per_value': 8 * len(wire) / array.size,
                'artifact_hash': 'sha256:' + hashlib.sha256(wire).hexdigest(),
                'verification': verification, 'boundary': boundary,
                'codec_quality_metadata': {'codec_requested_absolute_tolerance': float(method['error_bound']),
                                           'codec_requested_absolute_tolerance_text': method.get('_requested_error_bound', str(method['error_bound'])),
                                           'codec_effective_absolute_tolerance': metadata['error_bound'],
                                           'codec_effective_absolute_tolerance_hex': metadata['error_bound'].hex(),
                                           'source': 'checked actual CSP1 artifact'},
                'device_live_artifact': {'representation': descriptor['representation'], 'bytes': live_bytes,
                                         'host_recovery_descriptor': descriptor if boundary == 'device_resident' else None,
                                         'descriptor_constructed_inside_encode_clock': boundary == 'device_resident'},
                'boundary_costs': costs, 'gpu_encode_info': encode_info, 'gpu_decode_info': decode_info,
                'gpu_event_scope': EVENT_SCOPE, 'gpu_allocation_scope': ALLOCATION_SCOPE}, wire
    except BaseException as error:
        error.measurement_stage = phase
        error.input_unchanged = fingerprint(original) == before
        if wire is not None:
            error.artifact_wire = wire
        if encode_ns is not None:
            error.diagnostic_encode_ns = encode_ns
        elif phase == 'encode':
            error.diagnostic_encode_ns = time.perf_counter_ns() - started
        if decode_ns is not None:
            error.diagnostic_decode_ns = decode_ns
        elif phase == 'decode':
            error.diagnostic_decode_ns = time.perf_counter_ns() - started
        raise


def decode_wire(wire, library, device):
    from .bridges.cuszp import Session
    from .data import TimeSeriesObject
    schema, name, metadata, native_wire, _ = unpack_object(wire)
    with Session(metadata['dtype'], metadata['count'], metadata['error_bound'], device, library) as session:
        array, info = session.decode_host(native_wire)
    return TimeSeriesObject({name: array}, schema), info


def _source_identity(library=None, root=None):
    package = Path(__file__).resolve().parent
    files = ['__init__.py', 'gpu.py', 'runner.py', 'worker.py', 'config.py', 'records.py', 'data.py', 'artifact.py',
             'validate.py', 'runtime.py', 'provenance.py', 'environment.py', 'bridges/__init__.py',
             'build.py', 'registry.py', 'errors.py', 'bridges/cuszp.py', 'cuszp_build.py']
    sources = [{'module': name, 'path': str(package / name), 'sha256': file_hash(package / name)} for name in files]
    native = None
    if library is not None:
        evidence = library.evidence
        entries = []
        for item in evidence['identity']['sources']:
            path = Path(root) / item['path']
            if file_hash(path).split(':', 1)[1] != item['sha256']:
                raise RuntimeError('unavailable: GPU source differs from immutable build: ' + str(path))
            entries.append({'path': str(path), 'sha256': file_hash(path)})
        for group in ('compiled_dependencies', 'runtime_dependencies'):
            for item in evidence.get(group, []):
                path = Path(item['path'])
                if file_hash(path).split(':', 1)[1] != item['sha256']:
                    raise RuntimeError('unavailable: GPU build dependency differs: ' + str(path))
                entries.append({'path': str(path), 'sha256': file_hash(path)})
        native = {'binary': str(library.path), 'binary_sha256': file_hash(library.path),
                  'build_record': str(library.build_record), 'build_record_sha256': file_hash(library.build_record),
                  'build_identity': evidence['identity_sha256'], 'sources_and_dependencies': entries,
                  'toolchain': evidence.get('toolchain_files'), 'commands': evidence.get('commands'),
                  'runtime_dependencies': evidence.get('runtime_dependencies')}
    if root is not None:
        card = Path(root) / 'registry/gpu' / (KEY + '.json')
        if card.is_file():
            sources.append({'module': 'registry/gpu/' + card.name, 'path': str(card), 'sha256': file_hash(card)})
    return {'schema': 'tsbench.gpu-execution-provenance/1', 'source_id': stable_hash(sources),
            'sources': sources, 'native': native}


def _save_artifact(root, wire):
    digest = hashlib.sha256(wire).hexdigest()
    target = Path(root) / (digest + '.tsb')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(wire)
    if file_hash(target) != 'sha256:' + digest:
        raise ValueError('existing GPU artifact content mismatch')
    return str(target)


class Worker:
    def __init__(self, send):
        self.send = send
        self.stage = 'initialization'
        self.library = None
        self.original = None

    def phase(self, stage):
        self.stage = stage
        self.send({'event': 'stage', 'stage': stage})

    def dispatch(self, command):
        operation = command['op']
        if operation == 'init':
            self.config = command['config']
            self.profile = self.config['profile']
            self.phase('initialization.profile')
            self.effective = apply_profile(self.profile)
            self.phase('initialization.library')
            from .bridges.cuszp import Library
            self.library = Library(root=self.config['_asset_root'], build_root=self.config['_build_root'])
            self.provenance = _source_identity(self.library, self.config['_asset_root'])
            self.phase('initialization.device')
            device_info = self.library.device_info(self.profile['device_index'])
            self.effective.update(gpu=device_info, runtime=loaded_gpu_runtime(self.library.evidence.get('runtime_dependencies', [])))
            return {'status': 'ok', 'effective_profile': self.effective, 'execution_provenance': self.provenance,
                    'pid': os.getpid(), 'process_snapshot': process_snapshot(), 'native_diagnostics': self.library.diagnostics()}
        if operation == 'prepare':
            from .data import fingerprint, load_dataset, object_id, project
            self.phase('prepare.load')
            self.original = project(load_dataset(command['dataset'], self.config['_base_dir']), self.config['task'])
            self.method = command['method']
            self.boundary = command['boundary']
            self.phase('prepare.capability')
            support = capability(self.original, self.method, self.config['task'])
            self.fingerprint = fingerprint(self.original)
            identity = {'method': self.method, 'task': self.config['task'], 'boundary': self.boundary,
                        'scope': support, 'provenance': self.provenance, 'effective': self.effective,
                        'suite': SUITE_VERSION, 'python': sys.version}
            self.identity = stable_hash(identity)
            return {'status': 'ok', 'raw_object_id': object_id(self.original), 'input_lineage': self.original.lineage,
                    'capability': support, 'implementation_id': self.identity, 'effective_profile': self.effective}
        if operation in {'qualify', 'trial', 'warmup'}:
            before = self.library.diagnostics()
            row, wire = measure_object(self.original, self.method, self.config['task'], self.boundary,
                                       self.library, self.profile['device_index'], expected_fingerprint=self.fingerprint,
                                       on_stage=self.phase)
            after = self.library.diagnostics()
            row.update(native_diagnostics_before=before, native_diagnostics_after=after,
                       process_snapshot=process_snapshot())
            row['adapter_resources_released'] = resources_released(before, after)
            if not row['adapter_resources_released']:
                row.update(status='error', stage='validation.resources', reason='adapter_resources_not_released',
                           device_recovery_confirmed=False)
            # Artifacts used for admission and failures always survive, independently of success policy.
            if command.get('artifact_dir') and (operation == 'qualify' or command.get('save_wire') or row['status'] != 'ok'):
                row['artifact_path'] = _save_artifact(command['artifact_dir'], wire)
            row['implementation_id'] = self.identity
            if operation == 'qualify' and row['status'] == 'ok':
                self.phase('qualification.wire_only_decode')
                try:
                    row['independent_recovery'] = wire_recovery(wire, self.original, self.config, command.get('decoder_log'))
                    if row['independent_recovery']['execution_provenance'] != self.provenance:
                        raise ValueError('independent GPU decoder source/build identity differs from admission encoder')
                    if row['independent_recovery']['effective_profile']['gpu'] != self.effective['gpu']:
                        raise ValueError('independent GPU decoder device/runtime identity differs from admission encoder')
                except BaseException as error:
                    error.artifact_wire = wire
                    error.diagnostic_encode_ns = row['encode_ns']
                    error.diagnostic_decode_ns = row['decode_ns']
                    error.input_unchanged = row['verification']['input_unchanged']
                    raise
            return row
        if operation == 'close':
            return {'status': 'ok', 'closed': True, 'device_reset': False}
        raise ValueError('unknown GPU worker operation')


def wire_recovery(wire, original, config, decoder_log=None):
    """Decoder receives exact wire, implementation paths and resource profile only."""
    from .data import TimeSeriesObject, object_id
    from .validate import verify
    from .runtime import worker_environment
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='tsbench-gpu-wire-') as temporary:
        root = Path(temporary)
        target = root / 'input.tsb'
        target.write_bytes(wire)
        profile = root / 'profile.json'
        write_json(profile, config['profile'])
        command = [sys.executable, '-m', 'tsbench.gpu', 'decode', str(target), str(root / 'output'),
                   '--asset-root', config['_asset_root'], '--build-root', config['_build_root'], '--profile', str(profile)]
        environment = worker_environment(os.environ, config['profile'])
        environment['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent) + os.pathsep + environment.get('PYTHONPATH', '')
        done = subprocess.run(command, capture_output=True, timeout=config['execution']['timeout_s'],
                              env=environment)
        if decoder_log:
            Path(decoder_log).parent.mkdir(parents=True, exist_ok=True)
            Path(decoder_log).write_bytes(done.stdout + done.stderr)
        if done.returncode:
            error = RuntimeError('wire-only GPU decoder failed: ' + done.stderr.decode(errors='replace')[-8192:])
            error.status = 'crash' if done.returncode < 0 else 'error'
            error.returncode = done.returncode
            error.signal = -done.returncode if done.returncode < 0 else None
            error.device_recovery_confirmed = False
            raise error
        metadata = json.loads((root / 'output/object.json').read_bytes())
        restored = TimeSeriesObject({metadata['component']: np.load(root / 'output/value.npy', allow_pickle=False)}, metadata['schema'])
        verification = verify(original, restored, config['task'])
        if not verification['passed']:
            raise ValueError('exact-input wire-only decoder quality failed: ' + str(verification))
        return {'passed': True, 'decoder_process': True, 'decoder_pid': metadata['pid'],
                'artifact_hash': 'sha256:' + hashlib.sha256(wire).hexdigest(),
                'restored_object_id': object_id(restored), 'verification': verification,
                'effective_profile': metadata['effective_profile'], 'gpu_info': metadata['gpu_info'],
                'execution_provenance': metadata['execution_provenance'],
                'configuration_source': 'only checked artifact bytes; no original/schema/shape/bound template provided'}


def serve():
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'w', buffering=1, encoding='utf-8')
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    def send(value):
        protocol.write(canonical_json(value).decode() + '\n')
        protocol.flush()
    worker = Worker(send)
    for line in sys.stdin:
        command = json.loads(line)
        try:
            result = worker.dispatch(command)
        except BaseException as error:
            result = classify_error(error, worker.stage)
            wire = getattr(error, 'artifact_wire', None)
            if wire is not None:
                result.update(artifact_hash='sha256:' + hashlib.sha256(wire).hexdigest(), stored_bytes=len(wire))
                if command.get('artifact_dir'):
                    result['artifact_path'] = _save_artifact(command['artifact_dir'], wire)
        send({'event': 'result', **result})
        if command['op'] == 'close':
            return 0
    return 0


def make_schedule(cases, execution):
    """Freeze every requested slot, including admission rejections."""
    rng = random.Random(execution['seed'])
    blocks = {}
    for case in cases:
        blocks.setdefault(case['block_id'], []).append(case['case_id'])
    schedule = []
    for session in range(execution['sessions']):
        for block_id, members in blocks.items():
            for round_id in range(execution['rounds']):
                order = list(members)
                rng.shuffle(order)
                schedule.extend({'session': session, 'round': round_id, 'sequence': index, 'attempt': 0,
                                 'case_id': case_id, 'block_id': block_id} for index, case_id in enumerate(order))
    return schedule


def device_unsafe(result):
    return (result.get('status') in {'timeout', 'crash', 'oom'} or result.get('native_status') in {4, 5, 6} or
            result.get('device_recovery_confirmed') is False)


def resources_released(before, after):
    """Source counters verify adapter cleanup, without claiming driver cleanup."""
    pairs = (('allocations', 'releases'), ('streams_created', 'streams_released'), ('events_created', 'events_released'))
    return (after['live_bytes'] == before['live_bytes'] and
            all(after[created] - before[created] == after[released] - before[released] for created, released in pairs))


def _worker(root, config, label):
    from .runner import WorkerProcess
    from .runtime import worker_environment
    environment = worker_environment(os.environ, config['profile'])
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent) + os.pathsep + environment.get('PYTHONPATH', '')
    return GPUWorkerProcess(root / 'logs' / (label + '.log'), environment=environment,
                            command=[sys.executable, '-m', 'tsbench.gpu', 'serve'])


# Keep protocol/stage/timeout behavior shared, but always kill the worker group,
# even after its leader died. Its independent decoder inherits the same group.
from .runner import WorkerProcess as _WorkerProcess


class GPUWorkerProcess(_WorkerProcess):
    def terminate(self):
        import signal
        self.healthy = False
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _configuration_id(config):
    return stable_hash({key: value for key, value in config.items() if key not in {'output', '_config_path'}})


def run(config, output=None, *, qualification_only=False):
    """New append-only run; a device failure cancels all remaining device slots."""
    from .data import fingerprint, load_dataset, object_id, project, raw_bytes
    from .environment import capture
    from .provenance import snapshot_sources
    config = copy.deepcopy(config)
    root = Path(output or config['output']).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise FileExistsError('GPU output must be a new empty directory; historical measurements are immutable')
    provenance = _source_identity(root=config['_asset_root'])
    source_snapshot = snapshot_sources(root / 'source')
    config_path = config.get('_config_path')
    if config_path:
        (root / 'experiment.toml').write_bytes(Path(config_path).read_bytes())
    write_json(root / 'resolved_config.json', config)
    observations = root / 'observations.jsonl'
    run_id = str(uuid.uuid4())
    cases = []
    for dataset in config['datasets']:
        for boundary in config['boundaries']:
            for method in config['methods']:
                block_id = stable_hash({'dataset': dataset, 'task': config['task'], 'profile': config['profile'], 'boundary': boundary})
                case_id = stable_hash({'block_id': block_id, 'method': method})
                case = {'case_id': case_id, 'block_id': block_id, 'dataset_id': dataset['id'], 'method_id': method['id'],
                        'dataset': dataset, 'method': method, 'boundary': boundary, 'profile': config['profile'],
                        'task': {**config['task'], 'boundary': boundary}, 'status': 'configured'}
                try:
                    original = project(load_dataset(dataset, config['_base_dir']), config['task'])
                    support = capability(original, method, config['task'])
                    case.update(raw_object_id=object_id(original), raw_bytes=raw_bytes(original),
                                input_lineage=original.lineage, capability=support)
                except BaseException as error:
                    case.update(classify_error(error, 'parent_preflight'))
                cases.append(case)
    schedule = [] if qualification_only else make_schedule(cases, config['execution'])
    manifest = {'schema': 'tsbench.gpu-run/1', 'run_id': run_id, 'name': config['name'],
                'pass_kind': 'qualification' if qualification_only else 'formal',
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'configuration_id': _configuration_id(config), 'config_path': config_path,
                'config_sha256': file_hash(config_path) if config_path else None,
                'configuration': config, 'execution_provenance': provenance, 'source_snapshot': source_snapshot,
                'environment_before': capture(Path(config['_asset_root'])), 'cases': cases, 'schedule': schedule,
                'protocol': {'suite': SUITE_VERSION, 'independent_object': True,
                             'new_worker_per_session': True, 'new_codec_session_per_operation_inside_clock': True,
                             'exact_input_wire_only_decoder_process': True, 'input_unchanged_all_trials': True,
                             'device_reset': False, 'retry': False, 'cpu_fallback': False,
                             'gpu_event_scope': EVENT_SCOPE, 'gpu_allocation_scope': ALLOCATION_SCOPE},
                'state': 'admission', 'device_stop': None}
    write_json(root / 'manifest.json', manifest)
    terminal_keys = set()
    def record(event, **fields):
        append(observations, {'event': event, 'run_id': run_id, **fields})
        if event == 'terminal':
            terminal_keys.add(_slot_key(fields))
    for slot in schedule:
        record('planned', **slot)
    timeout = float(config['execution']['timeout_s'])
    worker = None
    stopped = None
    def request(command, context):
        return worker.request(command, timeout, lambda event: record('stage', **context, **{key: value for key, value in event.items() if key != 'event'}))
    # Exact qualifications are always rerun for this source/input/boundary/device.
    # Their measurements are diagnostics and never enter the formal summaries.
    try:
        worker = _worker(root, config, 'admission')
        initialized = request({'op': 'init', 'config': config}, {'phase': 'admission'})
        record('worker_init', phase='admission', **{key: value for key, value in initialized.items() if key != 'event'})
        if initialized.get('status') != 'ok':
            stopped = initialized
        elif initialized['execution_provenance']['source_id'] != provenance['source_id']:
            stopped = {'status': 'error', 'stage': 'initialization.source_identity',
                       'reason': 'GPU source changed between parent snapshot and actual admission worker',
                       'device_recovery_confirmed': False}
        else:
            manifest['gpu_execution_provenance'] = initialized['execution_provenance']
            manifest['effective_profile'] = initialized['effective_profile']
            for case in cases:
                context = {'case_id': case['case_id'], 'phase': 'admission'}
                record('qualification_planned', **context)
                if stopped or case['status'] != 'configured':
                    case.update(status=case['status'] if case['status'] != 'configured' else 'not_run',
                                reason=case.get('reason') or 'device_recovery_unconfirmed')
                    record('qualification_terminal', **context, status=case['status'], reason=case.get('reason'))
                    continue
                prepared = request({'op': 'prepare', 'dataset': case['dataset'], 'method': case['method'], 'boundary': case['boundary']}, context)
                if prepared.get('status') == 'ok' and prepared.get('raw_object_id') != case['raw_object_id']:
                    prepared = {'status': 'error', 'stage': 'input_validation', 'reason': 'worker input differs from frozen parent object'}
                if prepared.get('status') == 'ok':
                    case.update({key: prepared[key] for key in ('implementation_id', 'capability', 'effective_profile')})
                    record('qualification_started', **context)
                    result = request({'op': 'qualify', 'artifact_dir': str(root / 'artifacts'),
                                      'decoder_log': str(root / 'logs' / (case['case_id'].split(':')[1] + '-decoder.log'))}, context)
                else:
                    result = prepared
                case['status'] = 'ready' if result.get('status') == 'ok' else result.get('status', 'error')
                case['qualification'] = result
                if case['status'] != 'ready':
                    case['reason'] = result.get('reason')
                record('qualification_terminal', **context, **{key: value for key, value in result.items() if key != 'event'})
                if device_unsafe(result):
                    stopped = result
                write_json(root / 'manifest.json', manifest)
    except BaseException as error:
        stopped = classify_error(error, 'parent_admission')
        stopped['device_recovery_confirmed'] = False
        record('parent_failure', phase='admission', **stopped)
    finally:
        if worker:
            worker.close()
            worker = None
    if stopped:
        manifest['device_stop'] = stopped
        for case in cases:
            if case['status'] == 'configured':
                case.update(status='not_run', reason='device_recovery_unconfirmed' if device_unsafe(stopped) else 'device_unavailable')
    manifest['state'] = 'measurement' if not qualification_only else 'complete'
    write_json(root / 'manifest.json', manifest)
    by_case = {case['case_id']: case for case in cases}
    case_failures = {}
    current_session = None
    warmed = set()
    try:
        for slot in schedule:
            case = by_case[slot['case_id']]
            if stopped or case['status'] != 'ready' or case['case_id'] in case_failures:
                reason = ('device_recovery_unconfirmed' if device_unsafe(stopped or {}) else 'device_unavailable') if stopped else 'admission_rejected' if case['status'] != 'ready' else 'case_validation_failed'
                record('terminal', **slot, status='not_run', reason=reason, admission_status=case['status'],
                       device_recovery_confirmed=False if stopped and device_unsafe(stopped) else None)
                continue
            if slot['session'] != current_session:
                if worker:
                    worker.close()
                current_session = slot['session']
                worker = _worker(root, config, f'session-{current_session}')
                initialized = request({'op': 'init', 'config': config}, {'session': current_session, 'phase': 'measurement'})
                record('worker_init', session=current_session, phase='measurement', **{key: value for key, value in initialized.items() if key != 'event'})
                if initialized.get('status') != 'ok':
                    stopped = initialized
                    record('terminal', **slot, status='not_run', reason='session_initialization_failed', worker_result=initialized)
                    continue
                if initialized['execution_provenance'] != manifest['gpu_execution_provenance'] or initialized['effective_profile'] != manifest['effective_profile']:
                    stopped = {'status': 'error', 'stage': 'session_identity', 'reason': 'GPU source/runtime/device/resource identity changed after admission'}
                    record('terminal', **slot, status='not_run', reason='session_identity_changed', worker_result=stopped)
                    continue
            prepared = request({'op': 'prepare', 'dataset': case['dataset'], 'method': case['method'], 'boundary': case['boundary']}, slot)
            if prepared.get('status') == 'ok' and (prepared.get('raw_object_id') != case['raw_object_id'] or prepared.get('implementation_id') != case['implementation_id']):
                prepared = {'status': 'error', 'stage': 'input_validation', 'reason': 'actual trial input/implementation differs from admission'}
            result = prepared
            warm_key = (current_session, case['case_id'])
            if result.get('status') == 'ok' and warm_key not in warmed:
                for warmup in range(config['execution']['warmup_objects']):
                    result = request({'op': 'warmup', 'artifact_dir': str(root / 'artifacts')}, {**slot, 'warmup': warmup})
                    record('warmup', **slot, warmup=warmup, **{key: value for key, value in result.items() if key != 'event'})
                    if result.get('status') != 'ok':
                        break
                warmed.add(warm_key)
            if result.get('status') == 'ok':
                record('started', **slot)
                result = request({'op': 'trial', 'artifact_dir': str(root / 'artifacts'),
                                  'save_wire': config['execution']['save_artifacts']}, slot)
            else:
                result = {**result, 'reason': result.get('reason') or 'pretrial_failed'}
            record('terminal', **slot, **{key: value for key, value in result.items() if key != 'event'})
            if result.get('status') != 'ok':
                case_failures[case['case_id']] = result
                if device_unsafe(result):
                    stopped = result
                    manifest['device_stop'] = result
                    write_json(root / 'manifest.json', manifest)
    except BaseException as error:
        stopped = classify_error(error, 'parent_measurement')
        stopped['device_recovery_confirmed'] = False
        manifest['device_stop'] = stopped
        record('parent_failure', phase='measurement', **stopped)
        for pending in schedule:
            if _slot_key(pending) not in terminal_keys:
                record('terminal', **pending, status='not_run', reason='device_recovery_unconfirmed', device_recovery_confirmed=False)
    finally:
        if worker:
            worker.close()
        manifest['execution_source_unchanged'] = _source_identity(root=config['_asset_root'])['source_id'] == provenance['source_id']
        native = manifest.get('gpu_execution_provenance', {}).get('native')
        if native:
            dependencies = native['sources_and_dependencies'] + [
                {'path': native['binary'], 'sha256': native['binary_sha256']},
                {'path': native['build_record'], 'sha256': native['build_record_sha256']}]
            dependencies += manifest.get('effective_profile', {}).get('runtime', {}).get('libraries', [])
            manifest['native_execution_source_unchanged'] = all(Path(item['path']).is_file() and file_hash(item['path']) == item['sha256'] for item in dependencies)
        else:
            manifest['native_execution_source_unchanged'] = None
        manifest.update(state='complete', environment_after=capture(Path(config['_asset_root'])))
        write_json(root / 'manifest.json', manifest)
        generate(root)
    return root


def _slot_key(row):
    return tuple(row.get(key) for key in ('case_id', 'session', 'round', 'sequence', 'attempt', 'block_id'))


def generate(root):
    """Exact multiset completeness; unsuccessful slots never become good data."""
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_bytes())
    rows, tail = read_jsonl(root / 'observations.jsonl')
    planned = manifest['schedule']
    terminals = [row for row in rows if row.get('event') == 'terminal']
    expected, actual = Counter(map(_slot_key, planned)), Counter(map(_slot_key, terminals))
    malformed = [index for index, row in enumerate(terminals) if type(row.get('session')) is not int or type(row.get('round')) is not int or type(row.get('sequence')) is not int or type(row.get('attempt')) is not int]
    foreign_run = [index for index, row in enumerate(terminals) if row.get('run_id') != manifest['run_id']]
    integrity = {'expected_slots': len(planned), 'terminal_records': len(terminals),
                 'missing_slots': sum((expected - actual).values()), 'unexpected_slots': sum((actual - expected).values()),
                 'duplicate_expected_slots': sum(count - 1 for count in expected.values()),
                 'malformed_terminal_indices': malformed, 'foreign_run_terminal_indices': foreign_run, 'interrupted_tail': tail}
    integrity['complete'] = (not integrity['missing_slots'] and not integrity['unexpected_slots'] and
                             not integrity['duplicate_expected_slots'] and not malformed and not foreign_run and tail is None)
    source_unchanged = manifest.get('execution_source_unchanged') is True and manifest.get('native_execution_source_unchanged') is not False
    summaries = []
    for case in manifest['cases']:
        expected_case = Counter(_slot_key(slot) for slot in planned if slot['case_id'] == case['case_id'])
        trials = [row for row in terminals if row.get('case_id') == case['case_id']]
        actual_case = Counter(map(_slot_key, trials))
        ok = bool(expected_case) and expected_case == actual_case and all(row.get('status') == 'ok' and row.get('verification', {}).get('passed') for row in trials) and not malformed and not foreign_run and tail is None and source_unchanged
        summary = {'case_id': case['case_id'], 'dataset_id': case['dataset_id'], 'method_id': case['method_id'],
                   'boundary': case['boundary'], 'admission_status': case['status'], 'complete_success': ok,
                   'task': case.get('task'), 'profile': case.get('effective_profile'),
                   'codec_requested_absolute_tolerance_text': case.get('method', {}).get('_requested_error_bound'),
                   'codec_effective_absolute_tolerance': case.get('capability', {}).get('codec_effective_absolute_tolerance'),
                   'expected_trials': sum(expected_case.values()), 'terminal_trials': len(trials),
                   'status_counts': dict(Counter(row.get('status', 'missing') for row in trials)),
                   'encode_ns_median': None, 'decode_ns_median': None, 'stored_bytes_median': None,
                   'compression_ratio_median': None, 'metric_null_reason': None if ok else 'requires every exact scheduled slot to pass'}
        if ok:
            for field in ('encode_ns', 'decode_ns', 'stored_bytes'):
                values = [row[field] for row in trials]
                quartiles = statistics.quantiles(values, n=4, method='inclusive') if len(values) > 1 else [values[0]] * 3
                summary[field + '_median'] = statistics.median(values)
                summary[field + '_iqr'] = quartiles[2] - quartiles[0]
            summary['compression_ratio_median'] = statistics.median(row['raw_bytes'] / row['stored_bytes'] for row in trials)
            summary['encode_throughput_bytes_s'] = case['raw_bytes'] * 1e9 / summary['encode_ns_median']
            summary['decode_throughput_bytes_s'] = case['raw_bytes'] * 1e9 / summary['decode_ns_median']
            summary['bits_per_value_median'] = statistics.median(row['bits_per_value'] for row in trials)
            summary['max_abs_max'] = max(row['verification']['max_abs'] for row in trials)
            cost_keys = {key for row in trials for key in row.get('boundary_costs', {})}
            summary['boundary_cost_ns_median'] = {key: statistics.median(row['boundary_costs'][key] for row in trials) for key in sorted(cost_keys)}
            summary['quality_metadata'] = {key: trials[0]['verification'].get(key) for key in
                                            ('task_requested_bound', 'task_absolute_bound', 'relative_floor_requested',
                                             'relative_floor_effective', 'nrmse_denominator', 'psnr_denominator',
                                             'normalization_policy', 'quality_scope', 'metric_null_reasons')}
        summaries.append(summary)
    result = {'schema': 'tsbench.gpu-summary/1', 'run_id': manifest['run_id'], 'pass_kind': manifest['pass_kind'],
              'schedule_integrity': integrity, 'complete_success': bool(planned) and integrity['complete'] and all(case['complete_success'] for case in summaries),
              'qualification_complete_success': source_unchanged and bool(manifest['cases']) and all(case['status'] == 'ready' and case.get('qualification', {}).get('independent_recovery', {}).get('passed') for case in manifest['cases']),
              'execution_source_unchanged': manifest.get('execution_source_unchanged'),
              'native_execution_source_unchanged': manifest.get('native_execution_source_unchanged'),
              'cases': summaries, 'terminal_status_counts': dict(Counter(row.get('status') for row in terminals)),
              'analysis_sha256': file_hash(__file__), 'observation_sha256': file_hash(root / 'observations.jsonl'),
              'boundary_policy': 'host_to_host and device_resident are separate estimands; no pooled throughput',
              'gpu_event_scope': EVENT_SCOPE, 'gpu_allocation_scope': ALLOCATION_SCOPE}
    write_json(root / 'summary.json', result)
    lines = ['# GPU P4 results', '', f"Run `{manifest['run_id']}`; pass `{manifest['pass_kind']}`.", '',
             f"Exact schedule: {integrity['terminal_records']}/{integrity['expected_slots']} terminal records; "
             f"missing {integrity['missing_slots']}, unexpected {integrity['unexpected_slots']}. Complete success: {result['complete_success']}.", '',
             '| Dataset | Method | Boundary | Admission | Complete | Encode ms | Decode ms | Stored bytes |',
             '|---|---|---|---|---|---:|---:|---:|']
    for case in summaries:
        number = lambda value: '-' if value is None else f'{value / 1e6:.6f}'
        lines.append(f"| {case['dataset_id']} | {case['method_id']} | {case['boundary']} | {case['admission_status']} | {case['complete_success']} | {number(case['encode_ns_median'])} | {number(case['decode_ns_median'])} | {case['stored_bytes_median'] if case['stored_bytes_median'] is not None else '-'} |")
    lines += ['', EVENT_SCOPE + '.', '', ALLOCATION_SCOPE + '.', '',
              'Device preparation, artifact materialization/packing, descriptor parsing, payload installation, result download and owner release are separate raw fields. Stored bytes always charge the full persisted self-describing wire.']
    (root / 'report.md').write_text('\n'.join(lines) + '\n')
    return result


def prepare_grid(destination):
    """CPU-only deterministic predeclared fixtures/configs, before GPU admission."""
    import numpy as np
    destination = Path(destination).expanduser().resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError('GPU grid preparation needs a new empty directory')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'fixtures').mkdir()
    lengths = [('tail', 33), ('medium', 32769), ('large', 1048576)]
    datasets = []
    for width in (4, 8):
        for label, length in lengths:
            rng = np.random.default_rng(20261013 + width)
            x = np.arange(length, dtype=np.float64)
            values = (20 + 0.00001 * x + 3 * np.sin(x / 71) + 0.8 * np.cos(x / 4093) +
                      0.02 * rng.standard_normal(length)).astype('<f' + str(width))
            path = destination / 'fixtures' / f'f{width * 8}-{label}-{length}.npy'
            np.save(path, values, allow_pickle=False)
            datasets.append({'id': path.stem, 'format': 'npy', 'path': 'fixtures/' + path.name,
                             'component': 'V', 'source': 'frozen synthetic trend + periodicity + deterministic noise',
                             'license': 'project-generated benchmark fixture'})
    root = Path(__file__).resolve().parents[3]
    allowed = sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None
    generated = []
    for label, bound in [('0p01', 0.01), ('0p1', 0.1)]:
        name = 'gpu-abs-' + label
        lines = ['schema = "tsbench.gpu-experiment/1"', f'name = "{name}"', f'asset_root = "{root}"',
                 'boundaries = ["host_to_host", "device_resident"]', '', '[task]',
                 'kind = "values"', 'fidelity = "bounded_abs"', f'error_bound = "{bound}"',
                 'lifecycle = "independent_object"', 'cache_policy = "natural"', '', '[profile]',
                 'id = "cuda-device0-host-single"', 'device = "cuda"', 'device_index = 0',
                 'native_threads = 1', 'object_workers = 1', 'host_memory_limit_mb = 16384',
                 '# Actual CUDA qualification device init VmSize ~4.72GiB; enforce/read back 16GiB RLIMIT_AS.',
                 '# VRAM limit omitted: no enforceable cap; recorded as null with reason.']
        if allowed:
            lines.append('affinity = [' + str(allowed[0]) + ']')
        lines += ['', '[execution]', 'sessions = 3', 'rounds = 7', 'warmup_objects = 2',
                  'seed = 20261013', 'timeout_s = 120', 'save_artifacts = true', '', '[[methods]]',
                  'id = "cuszp-fixed"', f'codec = "{KEY}"', f'error_bound = "{bound}"']
        for dataset in datasets:
            lines += ['', '[[datasets]]', *(key + ' = ' + json.dumps(value) for key, value in dataset.items())]
        path = destination / (name + '.toml')
        path.write_text('\n'.join(lines) + '\n')
        resolved = load(path)
        generated.append({'path': str(path), 'sha256': file_hash(path), 'configuration_id': _configuration_id(resolved),
                          'cases': len(datasets) * len(resolved['boundaries']),
                          'planned_trials': len(datasets) * len(resolved['boundaries']) * 3 * 7})
    generator_snapshot = destination / 'generator_at_preparation.py'
    generator_snapshot.write_bytes(Path(__file__).read_bytes())
    write_json(destination / 'preparation.json', {'schema': 'tsbench.gpu-preparation/1', 'gpu_work_executed': False,
               'generator_sha256': file_hash(__file__), 'seed': 20261013, 'lengths': lengths, 'dtypes': ['<f4', '<f8'],
               'generator_snapshot': str(generator_snapshot), 'generator_snapshot_sha256': file_hash(generator_snapshot),
               'fixtures': [{'path': str(destination / dataset['path']), 'sha256': file_hash(destination / dataset['path'])} for dataset in datasets],
               'configs': generated, 'selection_policy': 'frozen before qualification; tail includes partial 32-value block, medium crosses 32768-value CUDA grid block, large 1M values; generated data is not a real corpus',
               'memory_policy': '16GiB host RLIMIT_AS selected from actual GPU initialization VmSize 5063843840bytes; enforce/read back in actual qualification worker; no VRAM cap requested, effective budget null with reason; explicit unenforceable VRAM requests reject admission'})
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    sub.add_parser('serve')
    prepare = sub.add_parser('prepare')
    prepare.add_argument('output', type=Path)
    for operation in ('qualify', 'run'):
        command = sub.add_parser(operation)
        command.add_argument('config', type=Path)
        command.add_argument('--output', type=Path)
    report = sub.add_parser('report')
    report.add_argument('output', type=Path)
    decode = sub.add_parser('decode')
    decode.add_argument('wire', type=Path)
    decode.add_argument('output', type=Path)
    decode.add_argument('--asset-root', type=Path, required=True)
    decode.add_argument('--build-root', type=Path, required=True)
    decode.add_argument('--profile', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'serve':
        return serve()
    if args.operation == 'prepare':
        print(prepare_grid(args.output))
        return 0
    if args.operation in {'qualify', 'run'}:
        print(run(load(args.config), args.output, qualification_only=args.operation == 'qualify'))
        return 0
    if args.operation == 'report':
        print(json.dumps(generate(args.output)))
        return 0
    profile = json.loads(args.profile.read_bytes())
    effective = apply_profile(profile)
    try:
        # Bad frames are rejected before Library construction or any CUDA API.
        wire = args.wire.read_bytes()
        unpack_object(wire)
        from .bridges.cuszp import Library
        library = Library(root=args.asset_root, build_root=args.build_root)
        restored, info = decode_wire(wire, library, profile['device_index'])
        import numpy as np
        args.output.mkdir(parents=True, exist_ok=True)
        name, array = next(iter(restored.components.items()))
        np.save(args.output / 'value.npy', array, allow_pickle=False)
        effective['gpu'] = library.device_info(profile['device_index'])
        effective['runtime'] = loaded_gpu_runtime(library.evidence.get('runtime_dependencies', []))
        write_json(args.output / 'object.json', {'schema': restored.schema, 'component': name,
                   'effective_profile': effective, 'gpu_info': info, 'pid': os.getpid(),
                   'execution_provenance': _source_identity(library, args.asset_root),
                   'process_snapshot': process_snapshot(), 'native_diagnostics': library.diagnostics()})
        return 0
    except BaseException as error:
        print(canonical_json(classify_error(error, 'wire_only_decode')).decode(), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
