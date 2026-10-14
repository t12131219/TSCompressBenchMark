"""Matched native API and complete object-wire boundary experiment.

This fixed-seed fixture diagnoses boundaries, never corpus codec rankings.
Each Python session and every direct-C operation run in isolated subprocesses.
"""
from __future__ import annotations

import argparse
import ctypes as ct
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LENGTHS = (0, 1, 257, 4096, 65536, 1048576)
CODECS = ('zstd-frame', 'lzss-raw')
BOUNDARIES = {
    'direct_c': {'encode_ns': 'CLOCK_MONOTONIC around compress + conditional finalize',
                 'decode_ns': 'CLOCK_MONOTONIC around decompress',
                 'excludes': ['create/reset/destroy', 'bound', 'allocation', 'copy/hash/verification', 'file IO', 'dlopen', 'outer wire', 'Python'],
                 'process_policy': 'fresh standalone C executable per round; fresh encoder and decoder handles'},
    'python_native_api': {'encode_ns': 'perf_counter_ns around prepared ctypes compress + conditional finalize',
                          'decode_ns': 'perf_counter_ns around prepared ctypes decompress',
                          'excludes': ['create/reset/destroy', 'bound', 'allocation', 'copy/hash/verification', 'file IO', 'outer wire'],
                          'includes': ['ctypes call and argument marshalling', 'Python call dispatch and status branch', 'native API work'],
                          'process_policy': 'fresh Python session per codec/length; fresh encoder and decoder handles each round'},
    'object_wire': {'encode_ns': 'ObjectScheme.encode_once(typed object), complete returned wire bytes',
                    'decode_ns': 'decode_once(wire), complete restored typed object',
                    'includes': ['registry/schema checks', 'partition/copy', 'native session create/reset/bound/allocation/destroy',
                                 'native API', 'checksums/identities', 'JSON descriptor and wire framing', 'decoded object allocation'],
                    'excludes': ['file IO', 'post-return verification', 'fixture generation', 'prepare_once'],
                    'process_policy': 'same typed object each round; production scheme creates independent per-operation native handles'},
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def fixture(length, seed):
    """Typed uint8 object: byte counts equal element counts, including 0 and 1."""
    if length < 0:
        raise ValueError('negative length')
    return np.random.default_rng(seed).integers(0, 16, size=length, dtype=np.uint8)


def file_record(path):
    return {'path': str(path.resolve()), 'sha256': sha(path.read_bytes()), 'nbytes': path.stat().st_size}


def preserve(directory, data):
    digest = sha(data)
    path = directory / 'artifacts' / (digest + '.bin')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise AssertionError('content-addressed artifact collision')
    else:
        path.write_bytes(data)
    return {'path': str(path), 'sha256': digest, 'nbytes': len(data)}


def append(path, row):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(dump(row) + '\n')


def checked_process(command, *, timeout, environment=None, process_group=True):
    """A crash/timeout becomes a diagnostic error; never enter native code here."""
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          env=environment, start_new_session=process_group) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if process_group:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise RuntimeError(f'subprocess timeout after {timeout}s: {command[0]}') from error
        if process.returncode:
            raise RuntimeError(f'subprocess returncode={process.returncode}: {stderr[-4000:]}')
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def verify_round_artifacts(row):
    """Re-read every retained product; a successful return proves paired bytes."""
    original = row['actual_input']
    products = [original, row['typed_input']]
    for result in row['boundaries'].values():
        products.extend(result[key] for key in ('payload', 'restored', 'header', 'wire') if key in result)
    for item in products:
        data = Path(item['path']).read_bytes()
        if len(data) != item['nbytes'] or sha(data) != item['sha256']:
            raise AssertionError('retained artifact differs from recorded bytes/hash')
    if row['typed_input']['sha256'] != original['sha256']:
        raise AssertionError('typed/raw actual input differs')
    payloads = [result['payload']['sha256'] for result in row['boundaries'].values()]
    if len(set(payloads)) != 1:
        raise AssertionError('paired native payload hashes differ')
    if any(result['restored']['sha256'] != original['sha256'] for result in row['boundaries'].values()):
        raise AssertionError('restored artifact identity differs')
    obj = row['boundaries']['object_wire']
    if obj['actual_native_input']['content_sha256'] != original['sha256'] or obj['codec_input_bytes'] != original['nbytes']:
        raise AssertionError('object path native input differs')
    if Path(obj['wire']['path']).read_bytes() != Path(obj['header']['path']).read_bytes() + Path(obj['payload']['path']).read_bytes():
        raise AssertionError('wire does not equal recorded header plus native payload')
    return len(products)


def runtime_overlap(python_libraries, c_libraries):
    python = {Path(item['path']).name.split('.so')[0]: item for item in python_libraries}
    native = {Path(item['path']).name.split('.so')[0]: item for item in c_libraries}
    overlap = sorted(python.keys() & native.keys())
    differences = [{'name': name, 'python': python[name], 'direct_c': native[name]}
                   for name in overlap if python[name]['sha256'].removeprefix('sha256:') != native[name]['sha256'].removeprefix('sha256:')]
    return {'overlap_names': overlap, 'hashes_equal': bool(overlap) and not differences, 'differences': differences}


def prepared_native(bridge, array, params):
    """Tool-only preparation; production bridges and schemes stay untouched."""
    from tsbench.bridges.c_abi_v1 import byte_buffer
    lib = bridge.lib
    config = bridge._config(params)
    raw = array.tobytes()
    prepare_begin = time.perf_counter_ns()
    source_storage = ct.create_string_buffer(raw, max(1, len(raw)))
    source = byte_buffer(source_storage, capacity=len(raw), used=len(raw))
    encoder = ct.c_void_p()
    bridge._check(lib.tscb_create(config, len(config), ct.byref(encoder)), encoder, 'create')
    if not encoder.value:
        raise RuntimeError('null encoder')
    try:
        bridge._check(lib.tscb_reset(encoder, 0), encoder, 'reset')
        bound = ct.c_uint64()
        bridge._check(lib.tscb_compress_bound(encoder, ct.byref(source), ct.byref(bound)), encoder, 'bound')
        if bound.value > 2**31:
            raise ValueError('bound exceeds allocation budget')
        head = ct.create_string_buffer(max(1, bound.value))
        tail_capacity = 0 if bridge.key == 'lzss-raw' else bound.value
        tail = ct.create_string_buffer(max(1, tail_capacity))
        encoded = byte_buffer(head, capacity=bound.value)
        finalized = byte_buffer(tail, capacity=tail_capacity)
        source_pointer, output_pointer, tail_pointer = ct.byref(source), ct.byref(encoded), ct.byref(finalized)
        compress, finish = lib.tscb_compress, lib.tscb_finalize
        encode_prepare_ns = time.perf_counter_ns() - prepare_begin
        begin = time.perf_counter_ns()
        encode_status = compress(encoder, source_pointer, output_pointer)
        finish_status = finish(encoder, tail_pointer) if encode_status == 0 else encode_status
        encode_ns = time.perf_counter_ns() - begin
        postprocess_begin = time.perf_counter_ns()
        bridge._check(encode_status, encoder, 'compress')
        bridge._check(finish_status, encoder, 'finalize')
        if encoded.used_bytes > encoded.capacity_bytes or finalized.used_bytes > finalized.capacity_bytes:
            raise AssertionError('native output exceeds capacity')
        payload = head.raw[:encoded.used_bytes] + tail.raw[:finalized.used_bytes]
    finally:
        bridge._check(lib.tscb_destroy(encoder), ct.c_void_p(), 'destroy')
    encode_postprocess_ns = time.perf_counter_ns() - postprocess_begin

    prepare_begin = time.perf_counter_ns()
    compressed_storage = ct.create_string_buffer(payload, max(1, len(payload)))
    compressed = byte_buffer(compressed_storage, capacity=len(payload), used=len(payload))
    restored_storage = ct.create_string_buffer(max(1, len(raw)))
    restored_buffer = byte_buffer(restored_storage, capacity=len(raw))
    decoder = ct.c_void_p()
    bridge._check(lib.tscb_create(config, len(config), ct.byref(decoder)), decoder, 'create')
    if not decoder.value:
        raise RuntimeError('null decoder')
    try:
        bridge._check(lib.tscb_reset(decoder, 0), decoder, 'reset')
        input_pointer, restored_pointer = ct.byref(compressed), ct.byref(restored_buffer)
        decompress = lib.tscb_decompress
        decode_prepare_ns = time.perf_counter_ns() - prepare_begin
        begin = time.perf_counter_ns()
        status = decompress(decoder, input_pointer, restored_pointer)
        decode_ns = time.perf_counter_ns() - begin
        postprocess_begin = time.perf_counter_ns()
        bridge._check(status, decoder, 'decompress')
        if restored_buffer.used_bytes != len(raw):
            raise AssertionError('decoded length differs')
        restored = restored_storage.raw[:restored_buffer.used_bytes]
    finally:
        bridge._check(lib.tscb_destroy(decoder), ct.c_void_p(), 'destroy')
    decode_postprocess_ns = time.perf_counter_ns() - postprocess_begin
    return {'encode_prepare_ns': encode_prepare_ns, 'decode_prepare_ns': decode_prepare_ns,
            'encode_postprocess_ns': encode_postprocess_ns, 'decode_postprocess_ns': decode_postprocess_ns,
            'encode_ns': encode_ns, 'decode_ns': decode_ns, 'bound_bytes': int(bound.value),
            'compress_bytes': int(encoded.used_bytes), 'finalize_bytes': int(finalized.used_bytes),
            'native_timer_instrumentation': False}, payload, restored


def object_wire(root, array, key, params):
    from tsbench.data import TimeSeriesObject, object_id
    from tsbench.artifact import read_bundle_prefix
    from tsbench.schemes import ObjectScheme, decode_once, _bridge
    obj = TimeSeriesObject({'V': array}, {'topology': 'UTS', 'roles': {'V': 'V'}})
    begin = time.perf_counter_ns()
    scheme = ObjectScheme({'codec': key, 'params': params}, root)
    scheme.prepare(obj)
    prepare_ns = time.perf_counter_ns() - begin
    begin = time.perf_counter_ns()
    encoded = scheme.encode_once(obj)
    encode_ns = time.perf_counter_ns() - begin
    actual = _bridge(str(root), key, str(root / 'build/tsbench')).last_input_identity.copy()
    begin = time.perf_counter_ns()
    restored = decode_once(encoded, root)
    decode_ns = time.perf_counter_ns() - begin
    descriptor, payload = read_bundle_prefix(encoded.wire)
    header = encoded.wire[:len(encoded.wire) - len(payload)]
    if object_id(restored) != object_id(obj):
        raise AssertionError('full restored object identity differs')
    return {'prepare_ns': prepare_ns, 'encode_ns': encode_ns, 'decode_ns': decode_ns,
            'typed_object_id': object_id(obj), 'codec_input_id': descriptor['codec_input_id'],
            'codec_input_bytes': descriptor['codec_input_bytes'], 'actual_native_input': actual,
            'descriptor_sha256': descriptor['descriptor_sha256'], 'transform_id': descriptor['transform_id'],
            'native_timer_instrumentation': False}, payload, restored.components['V'].tobytes(), header, encoded.wire


def worker(args):
    from tsbench.bridges import create_bridge
    from tsbench.build import artifact_path
    from tsbench.registry import Registry
    from tsbench.runtime import loaded_runtime, preload_identity
    root, directory = args.asset_root.resolve(), args.output_dir.resolve()
    array = fixture(args.length, args.seed)
    original = array.tobytes()
    library = artifact_path(root, args.codec)
    build_path = library.parent / 'build.json'
    build = json.loads(build_path.read_text())
    params = Registry(root).resolve_params(args.codec, {'native_timing': False})
    bridge = create_bridge(root, args.codec)
    source = preserve(directory, original)
    environment = {'python': sys.version, 'executable': sys.executable, 'numpy': np.__version__,
                   'platform': platform.platform(), 'pid': os.getpid(),
                   'LD_PRELOAD': os.environ.get('LD_PRELOAD', ''),
                   'runtime': loaded_runtime(build['runtime_dependencies']),
                   'requested_preload_files': preload_identity([item for item in os.environ.get('LD_PRELOAD', '').replace(':', ' ').split() if Path(item).is_absolute()])}
    if not environment['runtime'].get('implemented'):
        raise RuntimeError('Python actual runtime maps unavailable')
    common = {'schema': 'tsbench.boundary-observation/1', 'pass_kind': 'boundary_experiment',
              'codec': args.codec, 'length': args.length, 'session': args.session,
              'loops': 1, 'seed': args.seed, 'fixture': 'uint8 random alphabet 0..15; boundary diagnosis only',
              'typed_input': {'dtype': array.dtype.str, 'shape': list(array.shape), 'layout': 'C', **source},
              'actual_input': source, 'params': params, 'native_library': file_record(library),
              'build_id': build['build_id'], 'build_record': file_record(build_path),
              'environment': environment, 'reference_executable': file_record(args.reference)}
    with tempfile.TemporaryDirectory(prefix='tsbench-boundary-round-') as temporary:
        temporary = Path(temporary)
        for round_id in range(args.rounds):
            order = ['direct_c', 'python_native_api', 'object_wire']
            rotate = (args.session + round_id) % len(order)
            order = order[rotate:] + order[:rotate]
            row = {**common, 'round': round_id, 'order': order, 'status': 'ok', 'boundaries': {}}
            artifacts = {}
            try:
                for boundary in order:
                    if boundary == 'direct_c':
                        payload_path, restored_path = temporary / 'payload', temporary / 'restored'
                        command = [str(args.reference), str(library), args.codec, source['path'],
                                   bridge._config(params).decode(), str(payload_path), str(restored_path)]
                        # Inherit the worker's process group, so parent timeout kills both.
                        done = checked_process(command, timeout=args.call_timeout, process_group=False)
                        measurement = json.loads(done.stdout)
                        if not measurement.get('runtime_maps_available'):
                            raise RuntimeError('standalone C actual runtime maps unavailable')
                        measurement['actual_runtime_libraries'] = [file_record(Path(path)) for path in measurement['runtime_mapped_paths']]
                        from tsbench.bridges.c_abi_v1 import Buffer, NativeTiming
                        for field, struct in (('buffer', Buffer), ('native_timing', NativeTiming)):
                            if measurement[field + '_struct_bytes'] != ct.sizeof(struct) or measurement[field + '_offsets'] != [getattr(struct, name).offset for name, _ in struct._fields_]:
                                raise AssertionError(f'C/Python {field} ABI layouts differ')
                        if measurement['raw_bytes'] != len(original):
                            raise AssertionError('standalone C input length differs')
                        payload, restored = payload_path.read_bytes(), restored_path.read_bytes()
                        measurement['subprocess_command'] = command
                    elif boundary == 'python_native_api':
                        measurement, payload, restored = prepared_native(bridge, array, params)
                    else:
                        measurement, payload, restored, header, wire = object_wire(root, array, args.codec, params)
                        measurement['header'] = preserve(directory, header)
                        measurement['wire'] = preserve(directory, wire)
                        actual = measurement['actual_native_input']
                        if actual['content_sha256'] != source['sha256'] or actual['nbytes'] != len(original):
                            raise AssertionError('object native input differs from direct C/Python input')
                    measurement['payload'] = preserve(directory, payload)
                    measurement['restored'] = preserve(directory, restored)
                    if restored != original or array.tobytes() != original:
                        raise AssertionError(f'{boundary}: input mutated or restoration differs')
                    measurement['bitwise_passed'] = True
                    row['boundaries'][boundary] = measurement
                    artifacts[boundary] = payload
                if len(set(artifacts.values())) != 1:
                    raise AssertionError('matched actual inputs produced different native payload bytes')
                row['verified_artifact_records'] = verify_round_artifacts(row)
                row['runtime_overlap'] = runtime_overlap(environment['runtime']['libraries'], row['boundaries']['direct_c']['actual_runtime_libraries'])
                row['all_payloads_bytewise_equal'] = True
                row['all_actual_inputs_bytewise_equal'] = True
                row['paired_ratios'] = {operation: row['boundaries']['python_native_api'][operation] / row['boundaries']['direct_c'][operation]
                                        for operation in ('encode_ns', 'decode_ns') if row['boundaries']['direct_c'][operation] > 0}
            except Exception as error:
                row.update(status='error', stage='boundary_operation', reason=str(error))
            append(args.worker_jsonl, row)
    return 0


def distribution(values):
    data = np.asarray(values, dtype=np.float64)
    if not data.size:
        return {'n': 0, 'median': None, 'q1': None, 'q3': None, 'iqr': None}
    q1, median, q3 = np.percentile(data, [25, 50, 75])
    return {'n': len(values), 'median': float(median), 'q1': float(q1), 'q3': float(q3), 'iqr': float(q3 - q1)}


def summarize(rows):
    """Independent sessions are the primary statistical unit; rounds stay raw."""
    groups = {}
    for row in rows:
        if row['status'] != 'ok':
            continue
        for boundary, result in row['boundaries'].items():
            for operation in sorted(name for name, value in result.items() if name.endswith('_ns') and type(value) is int):
                key = (row['codec'], row['length'], boundary, operation)
                groups.setdefault(key, {}).setdefault(row['session'], []).append(result[operation])
        for operation, ratio in row.get('paired_ratios', {}).items():
            key = (row['codec'], row['length'], 'python_native_api/direct_c', operation + '_ratio')
            groups.setdefault(key, {}).setdefault(row['session'], []).append(ratio)
    output = []
    for (codec, length, boundary, operation), sessions in sorted(groups.items()):
        medians = [{'session': key, 'rounds': len(values), 'median': distribution(values)['median']}
                   for key, values in sorted(sessions.items())]
        output.append({'codec': codec, 'length': length, 'boundary': boundary, 'operation': operation,
                       'session_medians': medians,
                       'independent_session_summary': distribution([item['median'] for item in medians]),
                       'all_rounds_descriptive': distribution([value for values in sessions.values() for value in values])})
    return output


def orchestrate(args):
    root, directory = args.asset_root.resolve(), args.output_dir.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    compiler = shutil.which(os.environ.get('CC', 'cc'))
    if not compiler:
        raise RuntimeError('C compiler unavailable')
    executable = directory / 'reference'
    reference_source = root / 'benchmark/tests/native/reference.c'
    command = [compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(root / 'native/include'),
               str(reference_source), '-ldl', '-o', str(executable)]
    checked_process(command, timeout=60)
    from tsbench.runtime import worker_environment
    environment = worker_environment(os.environ.copy(), {'runtime_preload': args.preload})
    environment['PYTHONPATH'] = str(root / 'benchmark/src') + os.pathsep + environment.get('PYTHONPATH', '')
    package = root / 'benchmark/src/tsbench'
    identity_paths = [Path(__file__), reference_source, root / 'native/include/tscb_adapter_v1.h',
                      *(package / name for name in ('schemes.py', 'artifact.py', 'registry.py', 'runtime.py', 'data.py')),
                      *sorted((package / 'bridges').glob('*.py'))]
    manifest = {'schema': 'tsbench.boundary-experiment/1', 'boundary_definitions': BOUNDARIES,
                'sessions': args.sessions, 'rounds_per_session': args.rounds, 'lengths': args.lengths,
                'codecs': args.codecs, 'loops': 1, 'seed': args.seed,
                'fixture_policy': 'fixed-seed uint8 alphabet 0..15; overhead experiment, no corpus ranking',
                'paired_ratio_policy': 'Python prepared ctypes / standalone C native_api measured intervals only; same actual input and native payload; observed ratio includes process/cache/setup/timer/dispatch effects and is not an isolated FFI cost',
                'object_native_difference_policy': 'object totals include schema/registry/copies/handles/allocation/checksums/header and native work; do not call the difference FFI overhead',
                'statistical_unit': 'independent Python session; primary median/IQR across session medians; all round values remain descriptive',
                'native_timer_instrumentation': False, 'overhead_subtracted': False,
                'clock': vars(time.get_clock_info('perf_counter')), 'compile_command': command,
                'compiler': file_record(Path(compiler)),
                'compiler_version': checked_process([compiler, '--version'], timeout=15).stdout.splitlines()[0],
                'reference_executable': file_record(executable), 'source_files': [file_record(path) for path in identity_paths],
                'status': 'running', 'invocation': sys.argv}
    (directory / 'manifest.json').write_text(dump(manifest) + '\n')
    raw_path = directory / 'observations.jsonl'
    raw_path.touch()
    rows = []
    for key in args.codecs:
        for length in args.lengths:
            for session in range(args.sessions):
                session_path = directory / f'{key}-{length}-session-{session}.jsonl'
                command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--asset-root', str(root),
                           '--output-dir', str(directory), '--codec', key, '--length', str(length),
                           '--session', str(session), '--rounds', str(args.rounds), '--seed', str(args.seed),
                           '--reference', str(executable), '--worker-jsonl', str(session_path), '--call-timeout', str(args.call_timeout)]
                failure = None
                try:
                    checked_process(command, timeout=args.session_timeout, environment=environment)
                except Exception as error:
                    failure = {'schema': 'tsbench.boundary-observation/1', 'status': 'error', 'codec': key,
                               'length': length, 'session': session, 'stage': 'isolated_session', 'reason': str(error),
                               'subprocess_command': command}
                session_rows = [json.loads(line) for line in session_path.read_text().splitlines()] if session_path.exists() else []
                if failure:
                    session_rows.append(failure)
                elif len(session_rows) != args.rounds:
                    session_rows.append({'schema': 'tsbench.boundary-observation/1', 'status': 'error', 'codec': key,
                                         'length': length, 'session': session, 'stage': 'session_cardinality', 'reason': 'missing round rows'})
                for row in session_rows:
                    append(raw_path, row)
                rows.extend(session_rows)
                print(key, length, 'session', session, 'ok', sum(row['status'] == 'ok' for row in session_rows), flush=True)
    summary = {'schema': 'tsbench.boundary-summary/1', 'manifest': file_record(directory / 'manifest.json'),
               'raw': file_record(raw_path), 'ok_rounds': sum(row['status'] == 'ok' for row in rows),
               'runtime_overlap_equal_rounds': sum(row.get('runtime_overlap', {}).get('hashes_equal', False) for row in rows),
               'runtime_differences': [json.loads(value) for value in sorted({dump(row['runtime_overlap']['differences']) for row in rows if row.get('runtime_overlap', {}).get('differences')})],
               'errors': [row for row in rows if row['status'] != 'ok'], 'statistics': summarize(rows)}
    manifest['status'] = 'complete' if not summary['errors'] else 'error'
    manifest['expected_rounds'] = len(args.codecs) * len(args.lengths) * args.sessions * args.rounds
    manifest['completed_rounds'] = summary['ok_rounds']
    (directory / 'manifest.json').write_text(dump(manifest) + '\n')
    summary['manifest'] = file_record(directory / 'manifest.json')
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    table = ['# Boundary experiment', '', 'Primary figures: median of independent session medians; IQR across those session medians. All timings are ns; paired ratios are dimensionless.', '',
             '| Codec | Input bytes | Boundary | Operation | Sessions | Median | IQR |', '|---|---:|---|---|---:|---:|---:|']
    for item in summary['statistics']:
        stat = item['independent_session_summary']
        table.append(f'| {item["codec"]} | {item["length"]} | {item["boundary"]} | {item["operation"]} | {stat["n"]} | {stat["median"]:.3f} | {stat["iqr"]:.3f} |')
    table += ['', f'Valid rounds: {summary["ok_rounds"]}; error rows: {len(summary["errors"])}.', '',
              'The matched ratio is Python prepared ctypes / standalone C compress+finalize or decompress. It includes process/cache/setup/timer/dispatch effects. Object-wire totals have a broader boundary and their difference from native time is not an isolated FFI cost.']
    (directory / 'summary.md').write_text('\n'.join(table) + '\n')
    print(dump({'status': manifest['status'], 'ok_rounds': summary['ok_rounds'], 'errors': len(summary['errors']), 'output': str(directory)}))
    return 0 if not summary['errors'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, default=ROOT)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'runs' / ('boundary-' + time.strftime('%Y%m%d-%H%M%S')))
    parser.add_argument('--codecs', nargs='+', choices=CODECS, default=list(CODECS))
    parser.add_argument('--lengths', nargs='+', type=int, default=list(LENGTHS))
    parser.add_argument('--sessions', type=int, default=3)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--seed', type=int, default=20261013)
    parser.add_argument('--preload', action='append', default=[])
    parser.add_argument('--call-timeout', type=float, default=60)
    parser.add_argument('--session-timeout', type=float, default=300)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--codec', choices=CODECS, help=argparse.SUPPRESS)
    parser.add_argument('--length', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--session', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--reference', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--worker-jsonl', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sessions < 1 or args.rounds < 1 or any(length < 0 or length > 2**28 for length in args.lengths):
        parser.error('positive sessions/rounds and lengths in 0..2**28 required')
    if args.call_timeout <= 0 or args.session_timeout <= 0:
        parser.error('positive timeouts required')
    return worker(args) if args.worker else orchestrate(args)


if __name__ == '__main__':
    raise SystemExit(main())
