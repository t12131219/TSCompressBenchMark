"""Prepare an explicit SIMDComp SSE/AVX2 implementation-path comparison.

Generation and audit never run codecs, compile, or measure operations.
The installed SIMDComp binary already contains both selected native paths.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import statistics
import struct

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
LENGTHS = (257, 4096, 65536, 1048576)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(path):
    return {'path': str(path.resolve()), 'sha256': digest(path.read_bytes()), 'nbytes': path.stat().st_size}


def write_identical(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != content:
        raise ValueError(f'existing file differs; choose a new preparation directory: {path}')
    path.write_bytes(content)


def installed_paths(root):
    from tsbench.build import artifact_path
    from tsbench.registry import Registry
    library = artifact_path(root, 'simdcomp-u32')
    build_path = library.parent / 'build.json'
    build = json.loads(build_path.read_text())
    if digest(library.read_bytes()) != build['artifact_sha256']:
        raise ValueError('installed SIMDComp artifact differs from its build identity')
    methods = {'simd-sse-mask': Registry(root).resolve_params('simdcomp-u32', {'api': 'MASKED', 'isa': 'SSE4_1', 'native_timing': False}),
               'simd-avx2-mask': Registry(root).resolve_params('simdcomp-u32', {'api': 'MASKED', 'isa': 'AVX2', 'native_timing': False})}
    commands = [command for command in build['commands'] if '-c' in command]
    sse = [command for command in commands if any(str(value).endswith('/src/simdbitpacking.c') for value in command)]
    avx = [command for command in commands if any(str(value).endswith('/src/avxbitpacking.c') for value in command)]
    shim = [command for command in commands if any(str(value).endswith('/native/tscb_simdcomp.c') for value in command)]
    if len(sse) != 1 or '-msse4.1' not in sse[0] or '-mno-avx' not in sse[0] or '-mno-avx2' not in sse[0]:
        raise ValueError('actual SSE translation-unit flags not established')
    if len(avx) != 1 or '-mavx2' not in avx[0] or '-mno-avx512f' not in avx[0]:
        raise ValueError('actual AVX2 translation-unit flags not established')
    if len(shim) != 1 or '-fno-tree-vectorize' not in shim[0] or '-mno-avx2' not in shim[0]:
        raise ValueError('actual baseline shim translation-unit flags not established')
    sources = [root / 'adapters/simdcomp/native/tscb_simdcomp.c', root / 'adapters/simdcomp/native/avx2_bridge.c',
               root / 'adapters/simdcomp/vendor/simdcomp/src/simdbitpacking.c',
               root / 'adapters/simdcomp/vendor/simdcomp/src/avxbitpacking.c',
               root / 'adapters/simdcomp/contract.md', root / 'benchmark/src/tsbench/build.py',
               root / 'benchmark/src/tsbench/bridges/c_abi_v1.py', root / 'registry/codecs/simdcomp-u32.json']
    evidence = {'library': identity(library), 'build_record': identity(build_path), 'build_id': build['build_id'],
                'params': methods, 'actual_compile_commands': {'shim': shim[0], 'sse': sse[0], 'avx2': avx[0]},
                'source_files': [identity(path) for path in sources],
                'dispatch': {'SSE4_1': {'mode': 0, 'block_size': 128, 'full_encode': 'simdpack', 'full_decode': 'simdunpack',
                                        'tail_encode': 'simdpack_shortlength', 'tail_decode': 'simdunpack_shortlength'},
                             'AVX2': {'mode': 4, 'block_size': 256, 'full_encode': 'avxpack', 'full_decode': 'avxunpack',
                                      'tail_encode': 'simdpack_length', 'tail_decode': 'simdunpack_length'}},
                'interpretation': 'implementation path comparison with different 128/256-value native block geometry and record overhead; no scalar path and no isolated vector-width causality'}
    return evidence


def generate(root, preparation, output, seed):
    evidence = installed_paths(root)
    maximum = np.random.default_rng(seed).integers(0, 1 << 20, size=max(LENGTHS), dtype=np.uint32).astype('<u4', copy=False)
    # Every full or tail block has width 20 on both 128/256 block geometries.
    maximum[::128] |= np.uint32(1 << 19)
    files = []
    lines = ['schema = "tsbench.experiment/1"', 'name = "simdcomp-masked-sse-avx2-paths"',
             'output = ' + json.dumps(str(output)), '']
    for length in LENGTHS:
        array = maximum[:length].copy()
        path = preparation / 'fixtures' / f'u32-{length}.npy'
        stream = io.BytesIO(); np.save(stream, array, allow_pickle=False)
        write_identical(path, stream.getvalue())
        files.append({**identity(path), 'length': length, 'dtype': '<u4', 'raw_bytes': array.nbytes,
                      'raw_sha256': digest(array.tobytes())})
        lines += ['[[datasets]]', f'id = "u32-{length}"', 'format = "npy"',
                  f'path = "fixtures/u32-{length}.npy"', 'component = "V"',
                  f'source = "synthetic-u32-seed-{seed}"', 'license = "generated experiment fixture"', '']
    lines += ['[[methods]]', 'id = "raw-store"', 'codec = "raw-store"', '']
    for name, isa in [('simd-sse-mask', 'SSE4_1'), ('simd-avx2-mask', 'AVX2')]:
        lines += ['[[methods]]', f'id = "{name}"', 'codec = "simdcomp-u32"',
                  'params = { api = "MASKED", isa = "' + isa + '", starting_point = 0, native_timing = false }', '']
    lines += ['[task]', 'kind = "values"', 'fidelity = "bitwise"', 'boundary = "object_memory"',
              'lifecycle = "independent_object"', 'cache_policy = "natural"', '',
              '[[profiles]]', 'id = "cpu-single-path-comparison"', 'device = "cpu"', 'native_threads = 1',
              'object_workers = 1', 'runtime_preload = ["/usr/lib/x86_64-linux-gnu/libstdc++.so.6", "/home/fzg/anaconda3/lib/libgcc_s.so.1"]', '',
              '[execution]', 'sessions = 3', 'rounds = 7', 'warmup_objects = 2', f'seed = {seed}', 'timeout_s = 120',
              'qualification_cache = true', 'save_artifacts = true', '', '[analysis]', 'summary = "median_iqr"', 'inference = "none"', '']
    config = preparation / 'experiment.toml'
    write_identical(config, '\n'.join(lines).encode())
    from tsbench.config import load
    resolved = load(config)
    assert len(resolved['datasets']) == 4 and len(resolved['methods']) == 3
    evidence.update(schema='tsbench.isa-path-preparation/1', seed=seed, lengths=list(LENGTHS), fixtures=files,
                    config=identity(config), generator=identity(Path(__file__)), expected_measurement_trials=252,
                    fixture_policy='nested prefixes of one fixed-seed 20-bit uint32 vector; high bit set every 128 values to force 20-bit blocks; synthetic path experiment, not corpus ranking',
                    native_timing_instrumentation=False, formal_measurement_executed_by_generator=False)
    write_identical(preparation / 'preparation.json', (json.dumps(evidence, indent=2, allow_nan=False) + '\n').encode())
    return config


def parse_frame(frame, *, isa, length):
    """Read real SBP1 geometry; no decoder or compressor is invoked."""
    if len(frame) < 48 or frame[:8] != b'TSCBSBP1':
        raise ValueError('invalid or truncated SIMDComp frame')
    count, seed, mode, block, blocks, reserved, body = struct.unpack_from('<IIIIIIQ', frame, 8)
    expected_mode, expected_block = (0, 128) if isa == 'SSE4_1' else (4, 256)
    if (count, seed, mode, block, reserved) != (length, 0, expected_mode, expected_block, 0) or len(frame) != 48 + body:
        raise ValueError('actual SIMDComp wire mode/geometry differs from declared path')
    at, total = 40, 0
    widths, layouts = Counter(), Counter()
    full, tail = 0, 0
    for _ in range(blocks):
        n, width, layout, size = struct.unpack_from('<HBBI', frame, at)
        if not 1 <= n <= block or width != 20 or at + 8 + size > len(frame) - 8:
            raise ValueError('unexpected block count/width/extent')
        expected_layout = 2 if isa == 'AVX2' and n == 256 else 0
        if layout != expected_layout:
            raise ValueError('actual SIMD lane layout differs')
        widths[width] += 1; layouts[layout] += 1
        full += n == block; tail += n != block
        total += n; at += 8 + size
    if total != count or at != len(frame) - 8 or blocks != (count + block - 1) // block:
        raise ValueError('block records do not cover exact input')
    return {'isa': isa, 'mode': mode, 'block_size': block, 'blocks': blocks, 'full_calls': full, 'tail_calls': tail,
            'width_counts': dict(widths), 'layout_counts': dict(layouts), 'frame_bytes': len(frame),
            'native_frame_sha256': digest(frame), 'record_overhead_bytes': blocks * 8, 'header_trailer_bytes': 48}


def audit_run(run, output):
    from tsbench.artifact import read_bundle_prefix, validate_descriptor
    from tsbench.records import read_jsonl
    from tsbench.study import primary_rows
    manifest = json.loads((run / 'manifest.json').read_text())
    observations, tail = read_jsonl(run / 'observations.jsonl')
    if tail:
        raise ValueError('incomplete JSONL tail')
    rows = list(primary_rows(observations).values())
    cases = {case['case_id']: case for case in manifest['cases']}
    pairs, checked = defaultdict(dict), {}
    for row in rows:
        if row['status'] != 'ok':
            raise ValueError('incomplete/error primary measurement cannot enter path summary')
        case = cases[row['case_id']]
        method = case['method_id']; length = int(case['dataset_id'].removeprefix('u32-'))
        pairs[length, row['session'], row['round']][method] = row
        wire = Path(row['artifact_path']).read_bytes()
        if 'sha256:' + digest(wire) != row['artifact_hash']:
            raise ValueError('saved wire hash differs from terminal observation')
        descriptor, body = read_bundle_prefix(wire); validate_descriptor(descriptor, body)
        if method != 'raw-store':
            isa = case['method']['params']['isa']
            key = (method, length, digest(body))
            if key not in checked:
                checked[key] = parse_frame(body, isa=isa, length=length)
    comparisons = []
    for length in sorted({key[0] for key in pairs}):
        session_values = defaultdict(lambda: defaultdict(list))
        for (n, session, _), entries in pairs.items():
            if n != length:
                continue
            if set(entries) != {'raw-store', 'simd-sse-mask', 'simd-avx2-mask'}:
                raise ValueError('missing requested method in matched comparison round')
            sse, avx = entries['simd-sse-mask'], entries['simd-avx2-mask']
            if sse['codec_input_id'] != avx['codec_input_id'] or sse['codec_input_bytes'] != avx['codec_input_bytes']:
                raise ValueError('actual typed inputs differ across selected native paths')
            for metric in ('encode_ns', 'decode_ns', 'stored_bytes'):
                session_values[session][metric].append(sse[metric] / avx[metric])
        for metric in ('encode_ns', 'decode_ns', 'stored_bytes'):
            medians = [{'session': session, 'rounds': len(values[metric]), 'median_ratio': statistics.median(values[metric])}
                       for session, values in sorted(session_values.items())]
            values = [item['median_ratio'] for item in medians]
            q1, median, q3 = np.percentile(values, [25, 50, 75])
            comparisons.append({'length': length, 'metric': metric, 'ratio_semantics': 'SSE / AVX2; >1 means AVX2 faster or smaller under complete object boundary',
                                'session_medians': medians, 'median': float(median), 'q1': float(q1), 'q3': float(q3), 'iqr': float(q3 - q1)})
    result = {'schema': 'tsbench.isa-path-audit/1', 'manifest': identity(run / 'manifest.json'),
              'raw': identity(run / 'observations.jsonl'), 'primary_ok_trials': len(rows), 'paired_rounds': len(pairs),
              'saved_frame_geometries': [{'method': method, 'length': length, **value} for (method, length, _), value in sorted(checked.items())],
              'paired_session_ratios': comparisons,
              'scope': 'real MASKED SSE4_1/AVX2 implementation paths with 128/256 block records and SSE tails; not scalar vs SIMD and not isolated vector width'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, default=ROOT)
    parser.add_argument('--preparation-dir', type=Path, default=ROOT / 'benchmark/experiments/isa-paths')
    parser.add_argument('--run-output', type=Path, default=ROOT / 'runs/simd-paths-final-20261013')
    parser.add_argument('--seed', type=int, default=20261013)
    parser.add_argument('--audit-run', type=Path)
    parser.add_argument('--audit-output', type=Path)
    args = parser.parse_args()
    if args.audit_run:
        result = audit_run(args.audit_run.resolve(), args.audit_output or args.audit_run / 'path_audit.json')
        print(json.dumps({'primary_ok_trials': result['primary_ok_trials'], 'paired_rounds': result['paired_rounds']}))
    else:
        print(generate(args.asset_root.resolve(), args.preparation_dir.resolve(), args.run_output.resolve(), args.seed))
