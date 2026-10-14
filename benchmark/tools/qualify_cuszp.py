"""Correctness qualification of real host/device CUDA paths; no benchmark claims."""
from __future__ import annotations
import argparse
import ctypes as ct
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import numpy as np
from tsbench.bridges.cuszp import (
    HEADER_BYTES, GPUError, Library, Session, prepare_device_input,
    install_device_payload, pack, unpack,
)


def identity(path):
    p = Path(path).resolve()
    with p.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(p), 'sha256': digest, 'nbytes': p.stat().st_size}


def mapped_libraries():
    paths = set()
    for line in Path('/proc/self/maps').read_text().splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[-1].startswith('/') and '.so' in parts[-1]:
            paths.add(parts[-1])
    return [identity(p) for p in sorted(paths) if Path(p).is_file()]


def process_memory():
    """Observed process virtual/resident size, not a GPU allocation measurement."""
    status = Path('/proc/self/status').read_text()
    result = {'source': '/proc/self/status'}
    for line in status.splitlines():
        name, _, value = line.partition(':')
        if name in {'VmSize', 'VmRSS', 'VmPeak', 'VmHWM'}:
            result[name + '_bytes'] = int(value.split()[0]) * 1024
    return result


def clean_diagnostics(lib):
    result = lib.diagnostics()
    if result['live_bytes'] != 0 or any(result[a] != result[b] for a, b in [
        ('allocations', 'releases'), ('streams_created', 'streams_released'),
        ('events_created', 'events_released'),
    ]):
        raise AssertionError('checked CUDA resources not balanced: ' + json.dumps(result))
    return result


def decode_worker(wire_path, output, library_path):
    lib = Library(path=library_path)
    device = lib.device_info()
    initialized_memory = process_memory()
    wire = Path(wire_path).read_bytes()
    meta, _ = unpack(wire)
    with Session(meta['dtype'], meta['count'], meta['error_bound'], library=lib) as decoder:
        array, info = decoder.decode_host(wire)
    diagnostics = clean_diagnostics(lib)
    completed_memory = process_memory()
    np.save(output, array)
    print(json.dumps({'pid': os.getpid(), 'parent_pid': os.getppid(), 'device': device,
                      'decoded': identity(output), 'info': info, 'diagnostics': diagnostics,
                      'process_memory_after_device_init': initialized_memory,
                      'process_memory_after_decode': completed_memory,
                      'mapped_libraries': mapped_libraries()}))


def failure_worker(case, dtype, library_path):
    """A real loaded CUDA library/context, with deliberate checked API failures."""
    lib = Library(path=library_path)
    device = lib.device_info()
    memory = process_memory()
    before = clean_diagnostics(lib)
    dt = np.dtype(dtype)
    pointer = ct.c_void_p()
    expected = 2 if case.startswith('source-') else 1
    stage = 'native_source_preflight' if expected == 2 else 'native_payload_preflight'
    resources_created = False
    try:
        if case.startswith('source-'):
            name = case.removeprefix('source-')
            values = {'negative_zero': -0., 'nan': np.nan, 'infinity': np.inf,
                      'subnormal': np.nextafter(dt.type(0), dt.type(1)), 'quant_overflow': 2**29}
            array = np.array([values[name]], dtype=dt)
            # Bypass Python source-domain logic: status is returned by the native ABI.
            lib.call('prepare_input', 0, dt.itemsize, 1, 1/1024,
                     ct.c_void_p(array.ctypes.data), array.nbytes, ct.byref(pointer))
        elif case.startswith('rates-'):
            payload = bytearray(1024)
            name = case.removeprefix('rates-')
            if name == 'width31':
                payload[0] = 31
            elif name == 'padding':
                payload[1] = 1
                payload.extend(bytes(8))
            elif name == 'truncated':
                payload[0] = 1
            elif name == 'trailing':
                payload.extend(b'\0')
            else:
                raise ValueError(case)
            storage = ct.create_string_buffer(bytes(payload))
            # Bypass Python CSP1/rate validation; native rates() must reject itself.
            lib.call('install_payload', 0, dt.itemsize, 1, 1/1024,
                     storage, len(payload), ct.byref(pointer))
        elif case.startswith('wire-'):
            stage = 'python_persisted_wire_preflight'
            wire = bytearray(pack(bytes(1024), dtype, 1, 1/1024))
            wire[12 if case == 'wire-metadata' else HEADER_BYTES] ^= 1
            with install_device_payload(wire, library=lib):
                pass
        elif case in {'match-input', 'kind-input', 'match-payload', 'kind-payload'}:
            stage = 'native_owner_match_after_cuda_setup'
            resources_created = True
            array = np.zeros(1, dtype=dtype)
            wire = pack(bytes(1024), dtype, 1, 1/1024)
            with prepare_device_input(array, 1/1024, library=lib) as original:
                with install_device_payload(wire, library=lib) as payload:
                    n = 32 if case.startswith('match-') else 1
                    with Session(dtype, n, 1/1024, library=lib) as session:
                        if case.endswith('input'):
                            owner = payload if case.startswith('kind-') else original
                            lib.call('encode_device', session.pointer, owner.pointer, ct.byref(pointer))
                        else:
                            owner = original if case.startswith('kind-') else payload
                            lib.call('decode_device', session.pointer, owner.pointer, ct.byref(pointer))
        else:
            raise ValueError(case)
    except GPUError as error:
        if error.status != expected:
            raise AssertionError('unexpected native status') from error
        caught = {'status': error.status, 'classification': error.classification, 'reason': str(error)}
    else:
        raise AssertionError('deliberate invalid case was accepted: ' + case)
    if pointer.value:
        raise AssertionError('failed native operation transferred an output owner')
    after = clean_diagnostics(lib)
    if any(after[k] != before[k] for k in ['encode_launches', 'decode_launches']):
        raise AssertionError('rejected case launched a kernel')
    if not resources_created and any(after[k] != before[k] for k in ['allocations', 'streams_created', 'events_created']):
        raise AssertionError('preflight rejection allocated checked CUDA resources')
    if resources_created and after['allocations'] <= before['allocations']:
        raise AssertionError('owner-match failure did not exercise real CUDA allocations')
    print(json.dumps({'pid': os.getpid(), 'parent_pid': os.getppid(), 'case': case,
                      'dtype': dtype, 'stage': stage, 'error': caught, 'device': device,
                      'native_abi_invoked': not case.startswith('wire-'),
                      'checked_resources_created_before_rejection': resources_created,
                      'diagnostics_before': before, 'diagnostics_after': after,
                      'no_kernel_launch': True, 'all_checked_releases_completed': True,
                      'process_memory_after_device_init': memory,
                      'process_memory_after_failure': process_memory(),
                      'mapped_libraries': mapped_libraries()}))


def subprocess_json(command):
    done = subprocess.run(command, capture_output=True, text=True, timeout=60)
    if done.returncode:
        error = RuntimeError('independent GPU qualification worker failed: ' + done.stderr)
        error.worker_evidence = {'command': command, 'returncode': done.returncode, 'stdout': done.stdout, 'stderr': done.stderr}
        raise error
    return json.loads(done.stdout)


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts = output/'artifacts'
    artifacts.mkdir()
    lib = Library()
    device = lib.device_info()
    root = Path(__file__).resolve().parents[2]
    report = {'schema': 'tsbench.cuszp-qualification/1',
              'captured_at_utc': datetime.now(timezone.utc).isoformat(),
              'purpose': 'real GPU correctness qualification; not formal throughput or latency measurements',
              'python': sys.version, 'numpy': np.__version__, 'executable': sys.executable, 'pid': os.getpid(),
              'library': identity(lib.path), 'build': identity(lib.build_record), 'script': identity(__file__),
              'build_identity': lib.evidence['identity_sha256'], 'build_sources': lib.evidence['identity']['sources'],
              'invocation': sys.argv, 'process_thread_env': {k: os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS']},
              'gpu_capability_card': identity(root/'registry/gpu/cuszp-fixed-1d.json'),
              'device': device, 'cases': [], 'expected_rejections': [], 'failure_cases': [],
              'process_memory_after_device_init': process_memory(),
              'initial_diagnostics': clean_diagnostics(lib),
              'bound_policy': 'actual 1/1024 ABS; strict independent full-array max error <= bound; no 1.1 tolerance',
              'limits': ['finite qualification corpus, not a universal proof over accepted source domain',
                         'runtime OOM, kernel execution faults and failed-context recovery are not injected or qualified',
                         'calling-thread checked adapter resource balance excludes CUDA context/library allocations']}
    try:
        (output/'qualification_source.py').write_bytes(Path(__file__).read_bytes())
        for dtype in ['<f4', '<f8']:
            for n in [1, 31, 32, 33, 257, 32767, 32768, 32769]:
                for pattern in ['zero', 'grid', 'offgrid']:
                    if pattern == 'zero':
                        array = np.zeros(n, dtype=dtype)
                    elif pattern == 'grid':
                        array = ((np.arange(n)%31-15)/16).astype(dtype)
                    else:
                        array = ((np.arange(n)*17%101-50)/19).astype(dtype)
                    trusted = hashlib.sha256(array.tobytes()).hexdigest()
                    eb = 1/1024
                    report['current_stage'] = {'dtype': dtype, 'count': n, 'pattern': pattern, 'operation': 'host_encode'}
                    with Session(dtype, n, eb, library=lib) as encoder:
                        host = encoder.encode_host(array)
                    host_memory = process_memory()
                    host_sha = hashlib.sha256(host.wire).hexdigest()
                    wire_path = artifacts/(host_sha+'.csp')
                    if not wire_path.exists():
                        wire_path.write_bytes(host.wire)
                    report['current_stage']['operation'] = 'device_encode_and_materialize'
                    with prepare_device_input(array, eb, library=lib) as original:
                        with Session(dtype, n, eb, library=lib) as encoder:
                            encoded = encoder.encode_device(original)
                        with encoded:
                            resident = encoded.materialize()
                        restored_input = original.materialize()
                    if resident.wire != host.wire:
                        raise AssertionError('host/device paths produced different FIXED wire')
                    if restored_input.tobytes() != array.tobytes() or hashlib.sha256(array.tobytes()).hexdigest() != trusted:
                        raise AssertionError('source modified')
                    # New payload allocation and decoder from persisted wire only.
                    meta, _ = unpack(host.wire)
                    report['current_stage']['operation'] = 'independent_device_decode'
                    with install_device_payload(host.wire, library=lib) as payload:
                        with Session(meta['dtype'], meta['count'], meta['error_bound'], library=lib) as decoder:
                            decoded = decoder.decode_device(payload)
                        with decoded:
                            restored = decoded.materialize()
                            decode_info = decoded.info
                    max_error = float(np.max(np.abs(restored.astype(np.longdouble)-array.astype(np.longdouble))))
                    if not np.all(np.isfinite(restored)) or max_error > eb:
                        raise AssertionError('strict resident reconstruction failed')
                    diagnostics = clean_diagnostics(lib)
                    decoded_path = artifacts/(host_sha+'.decoded.npy')
                    command = [sys.executable, str(Path(__file__).resolve()), '--decode-wire', str(wire_path),
                               '--decoded-output', str(decoded_path), '--library', str(lib.path)]
                    report['current_stage']['operation'] = 'fresh_process_decode'
                    child = subprocess_json(command)
                    child_array = np.load(decoded_path, allow_pickle=False)
                    if child_array.dtype != array.dtype or child_array.shape != array.shape or not np.all(np.isfinite(child_array)) or not np.all(np.abs(child_array.astype(np.longdouble)-array.astype(np.longdouble)) <= eb):
                        raise AssertionError('strict fresh-process reconstruction failed')
                    case = {'dtype': dtype, 'count': n, 'pattern': pattern, 'status': 'ok', 'source_sha256': trusted,
                            'wire': identity(wire_path), 'host_info': host.info, 'device_info': resident.info,
                            'decode_info': decode_info, 'max_abs_error': max_error, 'diagnostics': diagnostics,
                            'process_memory_after_host_encode': host_memory,
                            'process_memory_after_device_decode': process_memory(),
                            'host_device_wire_equal': True, 'input_unchanged': True, 'fresh_decoder': child}
                    report['cases'].append(case)
                    (output/'qualification.partial.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
                    (output/'progress.json').write_text(json.dumps({'completed_cases': len(report['cases'])})+'\n')
        failure_names = ['source-negative_zero', 'source-nan', 'source-infinity', 'source-subnormal',
                         'source-quant_overflow', 'rates-width31', 'rates-padding', 'rates-truncated',
                         'rates-trailing', 'wire-metadata', 'wire-payload', 'match-input', 'match-payload',
                         'kind-input', 'kind-payload']
        for dtype in ['<f4', '<f8']:
            for name in failure_names:
                command = [sys.executable, str(Path(__file__).resolve()), '--failure-case', name,
                           '--dtype', dtype, '--library', str(lib.path)]
                report['current_stage'] = {'dtype': dtype, 'case': name, 'operation': 'fresh_process_failure_case'}
                child = subprocess_json(command)
                report['failure_cases'].append(child)
                if name.startswith('source-'):
                    report['expected_rejections'].append(child)
                (output/'qualification.partial.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        report['final_diagnostics'] = clean_diagnostics(lib)
        report['process_memory_after_all_operations'] = process_memory()
        report['mapped_libraries'] = mapped_libraries()
        report['summary'] = {'success_cases': len(report['cases']), 'expected_source_rejections': len(report['expected_rejections']),
                             'failure_subprocess_cases': len(report['failure_cases']),
                             'fresh_decoder_processes': len({c['fresh_decoder']['pid'] for c in report['cases']}),
                             'unexpected_errors': 0, 'all_checked_releases_completed': True}
        (output/'qualification.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        print(json.dumps(report['summary']))
    except BaseException as error:
        report['failure'] = {'stage': report.get('current_stage'), 'exception_type': type(error).__name__,
                             'reason': str(error), 'native_status': getattr(error, 'status', None),
                             'classification': getattr(error, 'classification', None),
                             'worker_evidence': getattr(error, 'worker_evidence', None),
                             'captured_at_utc': datetime.now(timezone.utc).isoformat(),
                             'process_memory': process_memory()}
        try:
            report['failure']['diagnostics'] = lib.diagnostics()
            report['failure']['balanced_checked_releases'] = clean_diagnostics(lib)
        except BaseException as diagnostic_error:
            report['failure']['diagnostics_unverified_reason'] = str(diagnostic_error)
        report['summary'] = {'success_cases': len(report['cases']), 'expected_source_rejections': len(report['expected_rejections']),
                             'failure_subprocess_cases': len(report['failure_cases']), 'unexpected_errors': 1,
                             'qualification_complete': False}
        (output/'qualification.failed.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, default=Path('runs/cuszp-qualification-20261013'))
    p.add_argument('--decode-wire', type=Path)
    p.add_argument('--decoded-output', type=Path)
    p.add_argument('--failure-case')
    p.add_argument('--dtype', default='<f4')
    p.add_argument('--library', type=Path)
    a = p.parse_args()
    if a.decode_wire:
        decode_worker(a.decode_wire, a.decoded_output, a.library)
    elif a.failure_case:
        failure_worker(a.failure_case, a.dtype, a.library)
    else:
        run(a.output)


if __name__ == '__main__':
    main()
