"""Native batches: Python prepares and verifies; the compiled driver owns clocks.

No throughput is inferred by subtracting Python or ABI overhead. Every retained
native product, including warmups, is checked after both native clocks stop.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .data import TimeSeriesObject, array_order, fingerprint, object_id
from .errors import BenchError, Unavailable, Unsupported, ValidationError
from .records import file_hash, stable_hash, write_json

CORE = {'raw-store': 'raw', 'zstd-frame': 'zstd', 'lz4-frame': 'lz4', 'snappy-raw': 'snappy',
        **dict.fromkeys(('brotli-stream','bzip2-stream','deflate-zlib','xz-stream','huff0','fse',
                        'lzss-raw','lzss-dipperstein-c','lzsse2-raw','lzsse8-raw',
                        'alp','alp-rd','chimp','chimp128','chimp32','chimpn','chimpn32','chimp128-no-index',
                        'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized','elf','elf-plus','elf-star','self-star',
                        'serf-qt','serf-xor','zfp-accuracy-1d','abba','fabba','qabba','deepzip','dzip',
                        'gorilla-prometheus-xor',
                        'sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman','simdcomp-u32',
                        'neats-lossless-i64','leats-lossless-i64'), 'core')}
API_COMPLETE_STREAMS = {'raw-store','zstd-frame','lz4-frame','snappy-raw'} | {'brotli-stream', 'bzip2-stream', 'deflate-zlib', 'xz-stream',
                               'abba', 'fabba', 'qabba', 'deepzip', 'dzip'}
API_COMPLETE_STREAMS |= {'chimp','chimp32','chimp128','chimpn','chimpn32','chimp128-no-index',
                         'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}
API_COMPLETE_STREAMS |= {'sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman'}
SIZE_REASON = 'ABI output includes recovery framing/state not yet separated by a reviewed format parser'


def _valid_record(record):
    files = [*record.get('sources', []), *record.get('compiled_dependencies', []),
             {'path': record.get('binary', ''), 'sha256': record.get('binary_hash')}]
    return bool(files) and all(Path(x['path']).is_file() and file_hash(x['path']) == x['sha256'] for x in files)


def driver_record(build_root):
    index = Path(build_root) / 'native-driver/index.json'
    if not index.is_file():
        raise Unavailable('native batch driver is missing; build it before admission', stage='native.build')
    record_path = Path(json.loads(index.read_bytes())['record'])
    record = json.loads(record_path.read_bytes())
    if record.get('status') != 'ok' or not _valid_record(record):
        raise Unavailable('native driver binary or compiled source closure changed; rebuild before a new run', stage='native.build')
    return {**record, 'record_path': str(record_path), 'record_hash': file_hash(record_path)}


def ensure_driver(asset_root, build_root):
    """Build once before run provenance is frozen, never in a timed worker."""
    root = Path(asset_root).resolve()
    directory = Path(build_root).resolve() / 'native-driver'
    compiler = shutil.which(os.environ.get('CXX', 'g++'))
    if not compiler:
        raise Unavailable('C++ compiler unavailable for native driver', stage='native.build')
    compiler = str(Path(compiler).resolve())
    version = subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]
    sources = [{'path': str(path), 'sha256': file_hash(path)} for path in sorted((root / 'benchmark/native').glob('*')) if path.suffix in {'.cpp', '.hpp'}]
    flags = ['-std=c++17', '-O3', '-DNDEBUG', '-I', str(root / 'native/include')]
    recipe = {'compiler': compiler, 'compiler_hash': file_hash(compiler), 'version': version,
              'flags': flags, 'link': ['-ldl'], 'sources': sources, 'schema': 'tsbench.native-build/1'}
    try:
        previous = driver_record(build_root)
        if previous['recipe'] == recipe:
            return previous
    except (Unavailable, OSError, ValueError, KeyError):
        pass
    if not (root / 'benchmark/native/driver.cpp').is_file():
        raise Unavailable('native driver source unavailable', stage='native.build')
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='compile-', dir=directory) as temporary:
        work = Path(temporary)
        command = [compiler, *flags, '-MD', '-MF', str(work / 'driver.d'), str(root / 'benchmark/native/driver.cpp'), '-o', str(work / 'driver'), '-ldl']
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=180)
        if compiled.returncode:
            raise Unavailable('native driver compile failed: ' + compiled.stderr[-12000:], stage='native.build')
        dependency_text = (work / 'driver.d').read_text().replace('\\\n', '')
        dependencies = sorted({str(Path(p).resolve()) for p in shlex.split(dependency_text.split(':', 1)[1])})
        closure = [{'path': p, 'sha256': file_hash(p)} for p in dependencies]
        build_id = stable_hash({'recipe': recipe, 'compiled_dependencies': closure})
        target = directory / build_id.split(':')[1]
        if target.exists():
            # A content identity is immutable; damaged artifacts are never repaired in place.
            existing = json.loads((target / 'build.json').read_bytes())
            if not _valid_record(existing):
                raise Unavailable('immutable native build is damaged: ' + str(target), stage='native.build')
        else:
            target.mkdir()
            shutil.copy2(work / 'driver', target / 'driver')
            (target / 'driver.d').write_text(dependency_text)
            record = {'schema': 'tsbench.native-build/1', 'status': 'ok', 'build_id': build_id,
                      'binary': str(target / 'driver'), 'binary_hash': file_hash(target / 'driver'),
                      'recipe': recipe, 'sources': sources, 'compiled_dependencies': closure,
                      'command': command, 'compile_stdout': compiled.stdout, 'compile_stderr': compiled.stderr}
            write_json(target / 'build.json', record)
        write_json(directory / 'index.json', {'record': str(target / 'build.json'), 'build_id': build_id})
    return driver_record(build_root)


def capability(method, obj, task, profile, asset_root, build_root):
    """Native entry points have their own capability, with no boundary fallback."""
    from .schemes import capability as object_capability
    from .registry import Registry
    try:
        spec = Registry(asset_root).get(method['codec'])
        spec.require_enabled()
        key = spec.key
        boundary = task.get('boundary')
        if boundary not in {'native_core', 'native_api'}:
            raise Unsupported('unknown native boundary')
        if boundary == 'native_core' and key not in CORE:
            raise Unsupported(f'{key}: direct native_core entry is not implemented; request native_api or object_memory explicitly')
        if boundary=='native_api' and key=='raw-store':
            raise Unsupported('raw-store has a compiled native_core copy reference, no C1/RW native_api entry')
        if task.get('lifecycle', 'prepared') not in {'prepared', 'fresh_request'}:
            raise Unsupported('native lifecycle requires prepared or fresh_request')
        if key != 'gorilla-prometheus-xor' and (len(obj.components) != 1 or task.get('kind') == 'records'):
            raise Unsupported('native batches currently require one projected component; joint records remain object_memory')
        if method.get('components') or method.get('chunk_rows') or method.get('channelwise') or method.get('transform', 'identity') not in {None, 'identity'}:
            raise Unsupported('native batches currently require a single identity route without chunking or channel partitioning')
        if key == 'gorilla-prometheus-xor':
            if boundary != 'native_core':
                raise Unsupported('Gorilla joint native batches require direct native_core')
            from .bridges.gorilla import names_and_arrays
            arrays = names_and_arrays(obj)
            if set(arrays) != {'T','V'} or arrays['V'][1].ndim != 1 or len(arrays['V'][1]) > 65535:
                raise Unsupported('Gorilla direct batch requires one T[N]/V[N] pair <=65535, without mask or partition')
        base = object_capability(method, obj, {**task, 'boundary': 'object_memory', 'lifecycle': 'independent_object'}, profile,
                                 asset_root=asset_root, build_root=build_root)
        if not base.get('supported'):
            return base
        spec = Registry(asset_root).get(key)
        rw = spec.document['adapter'].get('factory') == 'COMPLETED_REWRITE_CTYPES_V1'
        array = next(iter(obj.components.values()))
        if rw and array.ndim != 1:
            raise Unsupported('RW native batches require rank 1 / columns=1; collection framing belongs to object mode')
        if boundary == 'native_core' and key in {'abba','fabba','qabba'} and array.ndim != 1:
            raise Unsupported('ABBA family native_core requires rank1; use object/native_api for independent columns')
        if boundary == 'native_api' and array_order(array) != 'C':
            raise Unsupported('native_api currently requires C layout; it cannot silently materialize a different layout')
        if boundary == 'native_core' and key in {'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'} and array.ndim == 2 and array.shape[1] != 1:
            raise Unsupported('filter native_core requires one column; object/native_api preserve independent columns')
        record = driver_record(build_root)
        return {**base, 'boundary': boundary, 'native_abi': CORE[key] if boundary == 'native_core' else 'raw' if key == 'raw-store' else 'rw' if rw else 'c1',
                'driver': record, 'codec_complete_output_reviewed': boundary == 'native_core' or key in API_COMPLETE_STREAMS,
                'codec_complete_bytes_null_reason': None if boundary == 'native_core' or key in API_COMPLETE_STREAMS else SIZE_REASON,
                'executor_features': {'native_batch': True, 'object': False, 'stream': False, 'query': False, 'gpu': False}}
    except (Unsupported, Unavailable, ValueError, KeyError) as error:
        return {'supported': False, 'status': getattr(error, 'status', 'unsupported'), 'reason': str(error), 'stage': getattr(error, 'stage', 'capability')}


def mapped_runtime(result, directory):
    maps_path = directory / Path(result.get('runtime_maps_path', 'runtime-maps.txt')).name
    if not maps_path.is_file():
        raise ValidationError('driver did not retain actual runtime maps', stage='native.runtime')
    paths = set()
    for line in maps_path.read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and fields[5].startswith('/'):
            path = Path(fields[5])
            if not path.is_file():
                raise ValidationError('mapped runtime missing or deleted: ' + str(path), stage='native.runtime')
            paths.add(path.resolve())
    loader=result.get('loader_environment',{})
    for value in loader.get('LD_PRELOAD','').replace(':',' ').split():
        if Path(value).is_absolute() and Path(value).resolve() not in paths:
            raise ValidationError('requested runtime was not mapped by native driver: '+value,stage='native.runtime')
    return {'implemented': True, 'mechanism': '/proc/self/maps','process_scope':'actual native driver',
            'ld_preload':loader.get('LD_PRELOAD',''),'ld_library_path':loader.get('LD_LIBRARY_PATH',''),
            'libraries': [{'path': str(path), 'sha256': file_hash(path)} for path in sorted(paths)]}


def checked_driver(command, timeout):
    completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    try:
        result = json.loads(completed.stdout)
    except (ValueError, UnicodeError):
        result = {'status': 'error', 'error': 'invalid native protocol: ' + completed.stdout[-2048:].decode(errors='replace')}
    if completed.returncode or result.get('status') != 'ok':
        error = BenchError(str(result.get('error', result)) + ' ' + completed.stderr[-4096:].decode(errors='replace'), stage='native.' + str(result.get('stage', 'driver')))
        if completed.returncode < 0:
            error.status, error.returncode, error.signal = 'crash', completed.returncode, -completed.returncode
        elif result.get('status') == 'unsupported' or result.get('native_status') == 2:
            error.status = 'unsupported'
        error.native_batch = result
        raise error
    if result.get('schema') != 'tsbench.native-batch/1':
        raise ValidationError('native driver schema mismatch', stage='native.protocol')
    return result


class NativeMeasurement:
    def __init__(self, method, task, execution, support, asset_root, build_root):
        self.method, self.task, self.execution = method, task, execution
        self.support, self.root, self.build_root = support, Path(asset_root), Path(build_root)
        self.key, self.abi = method['codec'], support['native_abi']
        self.record = support['driver']
        self.runtime = None

    def prepare(self, original):
        # Do not share a native context with a trial or its independent decoder.
        self.original = original
        with tempfile.TemporaryDirectory(prefix='tsbench-native-probe-') as temporary:
            directory=Path(temporary)
            command=[self.record['binary'],'--abi',self.abi,'--codec',self.key,'--probe','--result-dir',str(directory)]
            if self.support.get('library_path'):command += ['--library',self.support['library_path']]
            result=checked_driver(command,self.execution['timeout_s'])
            self.runtime=mapped_runtime(result,directory)

    def _prepare_files(self, obj, directory):
        from .schemes import _bridge
        from .bridges.c_abi_v1 import _COLUMN_KEYS, _ZERO_FINISH
        name, array = next(iter(obj.components.items()))
        gorilla = self.key == 'gorilla-prometheus-xor'
        if gorilla:
            from .bridges.gorilla import names_and_arrays
            arrays = names_and_arrays(obj)
            name, values = arrays['V']
            timestamps = arrays['T'][1]
            array = np.empty((len(values), 2), dtype='<u8')
            array[:, 0] = timestamps.view('<u8')
            array[:, 1] = values.view('<u8')
        params = self.method.get('params', {})
        order = array_order(array)
        data = array.tobytes(order=order)
        config, model = b'{}', None
        input_layout = order
        if self.abi not in {'raw'}:
            bridge = _bridge(str(self.root), self.key, str(self.build_root))
            if self.abi == 'rw' or (self.abi == 'core' and self.key in {'deepzip','dzip'}):
                # Reuse content-domain guards, outside all native clocks. This
                # does no encode and preserves the existing admission contract.
                if self.key == 'deepzip':
                    alphabet = bridge.spec.document['adapter']['models'][params['model_key']]['alphabet_size']
                    if np.any(array >= alphabet):
                        raise Unsupported('DeepZip: MODEL_ALPHABET_UNSUPPORTED')
                if self.key == 'dzip' and np.unique(array).size == 9:
                    raise Unsupported('DZip: MODEL_ALPHABET_UNSUPPORTED')
                c = bridge._config(array.size, params)
                if self.abi == 'rw':
                    config = struct.pack('<QQIIIIIIddd', c.rows, c.columns, c.a, c.b, c.c, c.d, c.seed, c.mode, c.x, c.y, c.z)
                model = c.model.decode() if c.model else None
            elif self.abi != 'core':
                config = bridge._config(params)
                if self.abi == 'c1' and self.key != 'simdcomp-u32':
                    data = bridge._input(array, params)
                    input_layout = 'native_envelope_SOA' if self.key in _COLUMN_KEYS else 'native_bytes'
        if self.abi == 'core':
            config = json.dumps(params, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        (directory / 'input.bin').write_bytes(data)
        (directory / 'config.bin').write_bytes(config)
        library = self.support.get('library_path')
        command = [self.record['binary'], '--abi', self.abi, '--codec', self.key,
                   '--input', str(directory / 'input.bin'), '--config-file', str(directory / 'config.bin'),
                   '--output-bytes', str(array.nbytes), '--mode', self.task['lifecycle'],
                   '--memory-bytes', str(int(self.execution['native_batch_memory_mb']) * 1024**2)]
        if library:
            command += ['--library', library]
        if model:
            command += ['--model', model]
        if self.abi == 'c1' and self.key in _ZERO_FINISH:
            command += ['--zero-finish', '1']
        if self.abi == 'core' or self.key == 'simdcomp-u32':
            codes = {'|i1':1,'|u1':2,'<i2':3,'<u2':4,'<i4':5,'<u4':6,'<i8':7,'<u8':8,'<f4':9,'<f8':10}
            command += ['--dtype-code', str(11 if gorilla else codes[array.dtype.str]),
                        '--shape', ','.join(map(str, array.shape)), '--order', order]
        typed=self.abi in {'rw','core'} or self.key=='simdcomp-u32'
        if gorilla:
            input_layout = 'LE_I64_F64_INTERLEAVED_PAIRS'
        actual_input = {'content_sha256': hashlib.sha256(data).hexdigest(), 'nbytes': len(data),
                        'dtype': array.dtype.str if typed else '|u1',
                        'shape': list(array.shape) if typed else [len(data)],
                        'logical_dtype':array.dtype.str,'logical_shape':list(array.shape),
                        'logical_layout':order,'layout': input_layout, 'abi': self.abi,
                        'logical_components':{obj.schema.get('roles',{}).get(n,n):{'dtype':a.dtype.str,'shape':list(a.shape),'order':array_order(a)} for n,a in obj.components.items()}}
        return command, data, actual_input, name, array

    def _restored(self, path, obj):
        from .bridges.c_abi_v1 import _COLUMN_KEYS
        name, template = next(iter(obj.components.items()))
        data = path.read_bytes()
        if self.key == 'gorilla-prometheus-xor':
            from .bridges.gorilla import names_and_arrays
            arrays = names_and_arrays(obj)
            tname, t = arrays['T']; vname, v = arrays['V']
            if len(data) != t.nbytes + v.nbytes:
                raise ValidationError('native paired restored byte count mismatch', stage='native.validation')
            pairs = np.frombuffer(data, dtype='<u8').reshape(len(v), 2)
            return TimeSeriesObject({tname:pairs[:,0].copy().view('<i8'),
                                     vname:pairs[:,1].copy().view('<f8')}, obj.schema)
        if len(data) != template.nbytes:
            raise ValidationError('native restored byte count mismatch', stage='native.validation')
        flat = np.frombuffer(data, dtype=template.dtype)
        if self.abi == 'c1' and self.key in _COLUMN_KEYS and template.ndim == 2:
            array = flat.reshape(template.shape[1], template.shape[0]).T.copy()
        else:
            array = flat.reshape(template.shape, order=array_order(template)).copy(order=array_order(template))
        return TimeSeriesObject({name: array}, obj.schema)

    def measure(self, obj, *, loops=None, warmup=None, independent=False, artifact_dir=None, on_stage=None):
        from .validate import verify
        loops = self.execution['native_loops'] if loops is None else loops
        warmup = self.execution['native_warmup_loops'] if warmup is None else warmup
        initial = fingerprint(obj)
        if on_stage:
            on_stage('native.batch')
        with tempfile.TemporaryDirectory(prefix='tsbench-native-') as temporary:
            directory = Path(temporary)
            command, data, input_identity, name, array = self._prepare_files(obj, directory)
            result_dir = directory / 'batch'
            result = checked_driver([*command, '--loops', str(loops), '--warmup', str(warmup), '--result-dir', str(result_dir)], self.execution['timeout_s'])
            if result.get('iterations') != loops:
                raise ValidationError('driver iterations do not match requested loops', stage='native.protocol')
            if result.get('warmup_iterations')!=warmup or not result.get('native_loop_batch') or result.get('python_inside_batch_clock') is not False:
                raise ValidationError('driver did not execute the requested native batch',stage='native.protocol')
            runtime = mapped_runtime(result, result_dir)
            if self.runtime is not None and runtime != self.runtime:
                raise ValidationError('actual native process runtime changed after prepare', stage='native.runtime')
            if on_stage:
                on_stage('native.validation')
            if (result_dir / 'input-after.bin').read_bytes() != data or fingerprint(obj) != initial:
                raise ValidationError('native input buffer was modified', stage='native.validation')
            evidence, sizes, validations = [], [], []
            quality_parts=[]
            for prefix, count in (('warmup-', warmup), ('', loops)):
                for index in range(count):
                    payload_path = result_dir / f'{prefix}payload-{index:06d}.bin'
                    restored_path = result_dir / f'{prefix}restored-{index:06d}.bin'
                    restored = self._restored(restored_path, obj)
                    verification = verify(obj, restored, self.task)
                    verification['input_unchanged'] = True
                    validations.append(verification)
                    payload = payload_path.read_bytes()
                    if self.key=='zfp-accuracy-1d':
                        from .quality_metadata import zfp_frame_quality, zfp_core_quality
                        quality_parser = (lambda payload, part: zfp_core_quality(payload, part, self.support['library_path'])) if self.abi == 'core' else zfp_frame_quality
                        quality_parts.append({'component':name,'phase':'warmup' if prefix else 'measurement','operation':index,
                                              **quality_parser(payload,{'dtype':array.dtype.str,'shape':list(array.shape),'params':self.method['params']})})
                    if self.key in {'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'}:
                        from .quality_metadata import chimp_frame_quality
                        from .registry import Registry
                        quality_params = Registry(self.root).resolve_params(self.key, self.method.get('params'))
                        quality_parts.append({'component': name, 'phase': 'warmup' if prefix else 'measurement', 'operation': index,
                                              **chimp_frame_quality(payload, {'codec': self.key, 'shape': list(array.shape), 'params': quality_params})})
                    item = {'phase': 'warmup' if prefix else 'measurement', 'index': index,
                            'output_bytes': len(payload), 'payload_hash': file_hash(payload_path),
                            'restored_hash': file_hash(restored_path), 'verification': verification}
                    if artifact_dir:
                        target = Path(artifact_dir) / (file_hash(payload_path).split(':')[1] + '.codec')
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.exists():
                            target.write_bytes(payload)
                        item['payload_path'] = str(target)
                        if not verification.get('passed'):
                            failed=Path(artifact_dir)/(file_hash(restored_path).split(':')[1]+'.failed-restored')
                            if not failed.exists():failed.write_bytes(restored_path.read_bytes())
                            item['failed_restored_path']=str(failed)
                    evidence.append(item)
                    if not prefix:
                        sizes.append(len(payload))
            if result.get('output_sizes') != sizes or result.get('warmup_output_sizes')!=[item['output_bytes'] for item in evidence[:warmup]]:
                raise ValidationError('retained outputs do not match native byte accounting', stage='native.protocol')
            if result.get('restored_sizes')!=[array.nbytes]*loops or result.get('warmup_restored_sizes')!=[array.nbytes]*warmup:
                raise ValidationError('native restored sizes do not cover every operation',stage='native.protocol')
            verification = dict(validations[-1])
            for metric in ('max_abs','rmse','nrmse','effective_absolute_bound'):
                measured=[v[metric] for v in validations if v.get(metric) is not None]
                if measured:verification[metric]=max(measured)
            measured=[v['psnr_db'] for v in validations if v.get('psnr_db') is not None]
            if measured:verification['psnr_db']=min(measured)
            verification['passed'] = all(v.get('passed') for v in validations)
            verification['validated_operations'] = len(validations)
            verification['input_unchanged'] = True
            recovery = None
            if independent and verification['passed']:
                decode_dir = directory / 'independent'
                payload = result_dir / 'payload-000000.bin'
                # Codec data, fixed method configuration and the common typed
                # task schema only; no original data/model/encoder context.
                decode_command = [*command]
                decode_command[decode_command.index('--input') + 1] = str(payload)
                if '--model' in decode_command:
                    index = decode_command.index('--model')
                    del decode_command[index:index + 2]
                if self.abi not in {'c1','rw'}:
                    (directory/'decode-config.bin').write_bytes(b'{}')
                    decode_command[decode_command.index('--config-file')+1]=str(directory/'decode-config.bin')
                decoded = checked_driver([*decode_command, '--decode-only', '--loops', '1', '--warmup', '0', '--result-dir', str(decode_dir)], self.execution['timeout_s'])
                restored = self._restored(decode_dir / 'restored-000000.bin', obj)
                check = verify(obj, restored, self.task)
                if not check.get('passed') or (decode_dir / 'input-after.bin').read_bytes() != payload.read_bytes():
                    raise ValidationError('independent native decoder did not recover', stage='qualification.native_decode')
                recovery = {'passed': True, 'decoder_process': True, 'decoder_pid': decoded.get('process_pid'),
                            'decoder_returncode': 0, 'restored_object_id': object_id(restored), 'verification': check,
                            'decoder_runtime': mapped_runtime(decoded, decode_dir), 'artifact_hash': file_hash(payload)}
            complete = self.support['codec_complete_output_reviewed']
            size = sum(sizes) / loops
            roles = obj.schema.get('roles', {})
            values = sum(a.size for n,a in obj.components.items() if roles.get(n,n)=='V')
            timestamps = sum(a.size for n,a in obj.components.items() if roles.get(n,n)=='T')
            row = {'status': 'ok' if verification['passed'] else 'error', 'stage': 'complete' if verification['passed'] else 'native.validation',
                   'reason': None if verification['passed'] else 'one or more retained native products failed validation',
                   'boundary': self.task['boundary'], 'lifecycle': self.task['lifecycle'], 'cache_policy': 'natural',
                   'measurement_scope': 'direct codec API' if self.task['boundary'] == 'native_core' else 'complete native ABI including shim work',
                   'raw_bytes': array.nbytes, 'encode_ns': result['encode_batch_ns'] / loops,
                   'decode_ns': result['decode_batch_ns'] / loops, 'loops': loops,
                   'encode_batch_ns': result['encode_batch_ns'], 'decode_batch_ns': result['decode_batch_ns'],
                   'native_output_bytes': size, 'codec_complete_bytes': size if complete else None,
                   'codec_complete_bytes_null_reason': self.support['codec_complete_bytes_null_reason'],
                   'stored_bytes': size if complete else None, 'payload_bytes': size,
                   'header_bytes': None, 'framework_management_bytes_in_codec_size': 0,
                   'codec_input_id': stable_hash({k:input_identity[k] for k in ('content_sha256','nbytes','logical_dtype','logical_shape','logical_layout','logical_components')}), 'codec_input_bytes': len(data), 'native_input': input_identity,
                   'transform_id': 'identity', 'value_count': values, 'timestamp_count': timestamps,
                   'bits_per_value': size * 8 / values if complete and values else None,
                   'bits_per_timestamp': size * 8 / timestamps if complete and timestamps else None,
                   'verification': verification, 'native_products': evidence,
                   'native_batch': {**result, 'runtime_maps_path': None}, 'native_runtime': runtime,
                   'driver_build_id': self.record['build_id'], 'driver_binary_hash': self.record['binary_hash'],
                   'metric_null_reasons':{'codec_complete_bytes':self.support['codec_complete_bytes_null_reason'],
                                          'bits_per_value':self.support['codec_complete_bytes_null_reason'] if not complete else 'no values' if not values else None},
                   'artifact_hash': evidence[warmup]['payload_hash'],
                   'sampling_unit': 'one native batch per scheduled round; inner operations are not independent samples'}
            if recovery:
                row['independent_recovery'] = recovery
            if quality_parts:
                row['codec_quality_metadata']={'schema':'tsbench.codec-quality-metadata/1','parts':quality_parts,
                                               'scope':'native payload parsed after clocks; no task bound substituted for effective codec tolerance'}
            if artifact_dir:
                maps=result_dir/'runtime_maps.txt'
                maps_target=Path(artifact_dir)/(file_hash(maps).split(':')[1]+'.maps.txt')
                if not maps_target.exists():maps_target.write_bytes(maps.read_bytes())
                row['native_batch']['runtime_maps_path']=str(maps_target)
                row['native_batch']['runtime_maps_hash']=file_hash(maps_target)
                metadata = Path(artifact_dir) / (stable_hash({'row': row, 'schema': obj.schema}).split(':')[1] + '.experiment.json')
                write_json(metadata, {'schema': 'tsbench.native-experiment/1', 'typed_schema': obj.schema,
                                      'components':{n:{'dtype':a.dtype.str,'shape':list(a.shape),'order':array_order(a)} for n,a in obj.components.items()},
                                      'method': self.method, 'task': self.task, 'row': row})
                row['experiment_record_path'] = str(metadata)
                row['framework_management_bytes'] = metadata.stat().st_size
                row['artifact_path'] = evidence[warmup]['payload_path']
            return row, b''
