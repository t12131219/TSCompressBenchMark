"""Encode a frozen M3 batch unit once and restore it in detached workers."""
from contextlib import ExitStack
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from ..assets import canonical_bytes, digest, require
from ..planner.m3_fixed_batch import SCALAR, DRIVER, DIRECTORY, RETENTION, ROUTES, sample_indices, units
from ..supervisor.isolated_worker import invoke_isolated_worker
from .smoke import _worker_json

ENCODE, DECODE = 'encode-columns', 'decode-columns'


def _identity(path):
    require(path.is_file() and not path.is_symlink(), 'missing regular M3 batch output')
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _call(bundle, binding, plugin, backend, work, operation, mounts, args, expected_outputs, lines):
    work.mkdir()
    label = 'encode' if operation == ENCODE else f'decode-{backend}'
    options = {'decode_backend': backend} if plugin == 'alp-auto' else {}
    output, process = invoke_isolated_worker(bundle, binding['decoder'], {'plugin': plugin, 'options': options},
                                             binding['limits'], work, work, operation, mounts, args, lambda: False,
                                             label=label, observe=True)
    require(process['status'] == 'completed', f'M3 {label}: {process["status"]}: {process["reason"]}')
    require({p.name for p in output.iterdir()} == set(expected_outputs), f'M3 {label} emitted unexpected files')
    return output, {**process, 'options': options}, _worker_json(work / (label + '.stdout'), lines)


def _verify_execution_info(item, label, meta):
    route = item['route']
    if item['plugin'] == 'alp-auto':
        if label == 'encode':
            require(meta.get('backend') == 'alpn-auto-encoder', 'ALP did not report its Auto encoder')
        else:
            require(meta.get('requested_backend') == label and meta.get('backend') in (
                {SCALAR} if label == SCALAR else {'falp-scalar', 'falp-avx2', 'falp-avx512bw'}),
                'ALP decoder dispatch differs from requested route')
    elif label == 'encode' and route in {'zstd-baseline', 'xz-baseline'}:
        key, value = ('level', 3) if route == 'zstd-baseline' else ('preset', 6)
        require(meta.get(key) == value, f'M3 {route} native option differs from the frozen contract')


def restore_frame(bundle, binding, item, backend, work, frame, artifact, original):
    out, process, (shape, info) = _call(bundle, binding, item['plugin'], backend, work, DECODE,
                                        {'frame': frame}, ['/inputs/frame', '/out/schema', '/out/raw'],
                                        ('schema', 'raw'), 2)
    dtype, count = original['dtype'], original['count']
    restored = {'raw': _identity(out / 'raw'), 'schema': _identity(out / 'schema'), 'dtype': dtype, 'count': count}
    require(process['input_mounts'] == {'frame': artifact} and restored == original and
            shape == {'columns': [{'dtype': dtype, 'count': count}]},
            'M3 detached frame, original bits, shape or schema differ')
    _verify_execution_info(item, backend, info)
    return {'process': process, 'native': info, 'restored': restored}


def _publish_sample(run, frame, ref):
    target = run / ref['path']
    target.parent.mkdir(exist_ok=True)
    if not target.exists():
        with NamedTemporaryFile(dir=target.parent, prefix='.sample-') as pending:
            pending.write(frame.read_bytes())
            pending.flush()
            os.fsync(pending.fileno())
            # Link, not overwrite: another case can reference this same content.
            try:
                os.link(pending.name, target)
            except FileExistsError:
                pass
    require(_identity(target) == {k: ref[k] for k in ('bytes', 'sha256')}, 'M3 retained batch frame differs')


def run_fixed_batch(item, staged, work, run, binding):
    plugin, _, backends = ROUTES[item['selection'], item['route']]
    require(plugin == item['plugin'], 'M3 fixed batch plugin identity differs')
    bundle = run / DIRECTORY
    byte_view = item['view'] == 'v_bytes_interleaved'
    width = 1 if byte_view else 8
    dtype = 2 if byte_view else 10  # BMK_U8 / BMK_F64
    require(len(staged['paths']) == (1 if byte_view else staged['columns']), 'missing M3 staged columns')
    require(binding['retention'] == RETENTION, 'unexpected M3 fixed-batch retention policy')
    keep, samples, rows = set(sample_indices(item)), [], []
    with ExitStack() as stack:
        streams = [stack.enter_context(p.open('rb')) for p in staged['paths']]
        for index, unit in enumerate(units(item)):
            with TemporaryDirectory(prefix='unit-', dir=work) as tmp:
                folder = Path(tmp)
                stream = streams[unit.get('column', 0)]
                start, _ = unit['byte_range'] if byte_view else unit['row_range']
                require(stream.tell() == start * width, 'M3 staged input offset differs from frozen extent')
                raw = stream.read(unit['input_bytes'])
                require(len(raw) == unit['input_bytes'], 'truncated M3 staged input')
                count = len(raw) // width
                raw_path, schema = folder / 'raw', folder / 'schema'
                raw_path.write_bytes(raw)
                schema.write_bytes(canonical_bytes({'role': 'bytes', 'dtype': 'u8', 'bytes': count} if byte_view else
                                                   {'role': 'value', 'dtype': 'f64', 'rows': count}))
                original = {'raw': _identity(raw_path), 'schema': _identity(schema), 'dtype': dtype, 'count': count}
                out, encode, (meta,) = _call(bundle, binding, plugin, backends[0], folder / 'encode', ENCODE,
                                             {'raw': raw_path, 'schema': schema},
                                             ['/inputs/schema', '/out/frame', str(dtype), '/inputs/raw'], ('frame',), 1)
                _verify_execution_info(item, 'encode', meta)
                require(encode['input_mounts'] == {k: original[k] for k in ('raw', 'schema')},
                        'M3 encode mount differs from original input')
                frame = out / 'frame'
                artifact = _identity(frame)
                require(0 < artifact['bytes'] <= binding['limits']['file_bytes'], 'invalid M3 batch frame size')
                recoveries = {backend: restore_frame(bundle, binding, item, backend, folder / f'decode-{backend}',
                                                     frame, artifact, original) for backend in backends}
                require(len({encode['session_id'], *(r['process']['session_id'] for r in recoveries.values())}) == 1 + len(backends),
                        'M3 batch operations did not use distinct process sessions')
                rows.append({**unit, 'original': original, 'artifact': artifact,
                             'encode': {'process': encode, 'native': meta}, 'decodes': recoveries})
                if index in keep:
                    saved = work / f'retained-{index}.bmk'
                    frame.rename(saved)
                    samples.append((saved, {'unit_index': index, 'path': f"{RETENTION['directory']}/{artifact['sha256']}.bmk",
                                            **artifact}))
        require(all(not stream.read(1) for stream in streams), 'unconsumed M3 staged input')
    estimate = item['input']['size_estimate']
    require(len(rows) == estimate['input_units'] and sum(u['input_bytes'] for u in rows) == estimate['native_input_bytes_one_pass'],
            'M3 batch driver did not consume planned units')
    for saved, ref in samples:
        _publish_sample(run, saved, ref)
    return {'driver': DRIVER, 'recovery_id': binding['decoder']['recovery_id'], 'units': rows,
            'retained_samples': [ref for _, ref in samples],
            'released_frames': {'count': len(rows) - len(samples),
                                'bytes': sum(u['artifact']['bytes'] for i, u in enumerate(rows) if i not in keep)},
            'process_timing_scope': 'isolated_process_diagnostic_not_m2_measurement', 'timing_admitted': False}
