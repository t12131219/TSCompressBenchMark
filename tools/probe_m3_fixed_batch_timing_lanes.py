#!/usr/bin/env python3
"""Validate linked and dlopen timing workers against the same real-corpus frames.

This does not retain timing samples, calibrate, or admit performance results.
"""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_fixed_batch import _verify_execution_info
from tsbench.application.m3_fixed_batch_audit import audit_fixed_batch, sealed_batch_scope
from tsbench.application.m3_real_corpus_execution import _entry_map, _stage_dataset
from tsbench.application.smoke import write_new
from tsbench.assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.planner.m3_fixed_batch import ROUTES
from tsbench.supervisor.isolated_worker import program_files


def _reference(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size}


def _binaries(build, decoder, plugin, directory):
    lib = decoder['plugins'][plugin]
    tag = plugin.replace('-', '_')
    paths = {'dlopen': build / 'tsbench_frame_batch_dlopen',
             'linked_entry': build / f'tsbench_frame_batch_tsbench_{tag}'}
    # Stage the original case's locked dependencies, not libraries rebuilt
    # incidentally beside a measurement worker.
    copied = {}
    for rel in program_files(decoder, [lib]):
        row = decoder['files'][rel]
        if row['origin'] != 'build':
            continue
        path = local_file(ROOT, row['source'])
        require(digest(path) == row['sha256'] and path.stat().st_size == row['bytes'],
                f'M3 lane build does not use tested codec bytes: {rel}')
        copied[rel] = _reference(path)
    module = directory / Path(lib).name
    refs = {key: _reference(path) for key, path in paths.items()}
    # Copy with exact identities and no ambient LD_* settings. Preserve $ORIGIN
    # lookup by staging each executable beside the tested codec and dependencies.
    all_assets = [*refs.values(), *copied.values()]
    directory.mkdir()
    for ref in all_assets:
        src = verify_asset(ROOT, ref)
        target = directory / src.name
        with target.open('xb') as out:
            out.write(src.read_bytes())
        target.chmod(0o500 if src.name in {p.name for p in paths.values()} else 0o400)
        require(digest(target) == ref['sha256'], 'timing lane staging changed bytes')
    return module, {key: directory / path.name for key, path in paths.items()}, {
        'lanes': refs, 'project_runtime_assets': copied}


def _input(item, unit, staged, work):
    byte_view = item['view'] == 'v_bytes_interleaved'
    span = unit['byte_range'] if byte_view else unit['row_range']
    width = 1 if byte_view else 8
    with staged['paths'][unit.get('column', 0)].open('rb') as src:
        src.seek(span[0] * width)
        raw = src.read(unit['input_bytes'])
    original = unit['original']
    size = len(raw) // width
    schema = canonical_bytes({'role': 'bytes', 'dtype': 'u8', 'bytes': size} if byte_view else
                             {'role': 'value', 'dtype': 'f64', 'rows': size})
    require(original == {'raw': {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()},
                         'schema': {'bytes': len(schema), 'sha256': sha256(schema).hexdigest()},
                         'dtype': 2 if byte_view else 10, 'count': size}, 'M3 timing input differs from verified source span')
    value_file, schema_file = work / 'values.bin', work / 'schema.json'
    value_file.write_bytes(raw)
    schema_file.write_bytes(schema)
    return value_file, schema_file


def probe(plan, run, build, *, full_ledger=False):
    # First check the run under the official ledger/retention contract. This is
    # not the detached replay; that audit is separately invoked with --replay.
    audit = audit_fixed_batch(ROOT, plan, run, full_ledger=full_ledger)
    seal_id, _, source_rows = sealed_batch_scope(ROOT, plan, run, full_ledger=full_ledger)
    require(seal_id == audit['seal_id'], 'M3 lane probe and sample audit use different sealed runs')
    definition = load_json(local_file(ROOT, plan['definition']['plan']['path']))
    entries = _entry_map(ROOT, definition)
    decoder = plan['build']['fixed_batch']['decoder']
    binaries, asset_refs, rows = {}, {}, []
    with TemporaryDirectory(prefix='m3-real-timing-lane-probe-') as temp, ExitStack() as stack:
        temp = Path(temp)
        staged = {}
        for row, item in source_rows:
            if (row['selection'], row['route']) not in ROUTES or row['status'] != 'verified':
                continue
            plugin, _, backends = ROUTES[item['selection'], item['route']]
            if plugin not in binaries:
                module, lanes, refs = _binaries(build, decoder, plugin, temp / plugin)
                binaries[plugin] = (module, lanes)
                asset_refs[plugin] = refs
            module, lanes = binaries[plugin]
            key = (item['dataset_id'], item['view'])
            if key not in staged:
                directory = Path(stack.enter_context(TemporaryDirectory(dir=temp)))
                staged[key] = _stage_dataset(ROOT, entries[item['dataset_id']], directory, item['view'])
            for ref in row['evidence']['retained_samples']:
                index = ref['unit_index']
                unit = row['evidence']['units'][index]
                frame = verify_asset(run, ref)
                with TemporaryDirectory(dir=temp) as folder:
                    work = Path(folder)
                    value, schema = _input(item, unit, staged[key], work)
                    out = work / 'probe.bmk'
                    for backend in backends:
                        for lifecycle in ('steady', 'cold'):
                            for lane, worker in lanes.items():
                                options = {'decode_backend': backend} if plugin == 'alp-auto' else {}
                                command = ['/usr/bin/prlimit', '--as=1073741824:1073741824', '--fsize=1048576:1048576',
                                           '--core=0:0', '--', worker, module, plugin, canonical_bytes(options).decode('ascii'),
                                           lifecycle, str(unit['original']['dtype']), '1', '1', str(16 << 20), value, schema, out, lane]
                                p = subprocess.run(command, cwd=work, env={'LC_ALL': 'C'}, capture_output=True, text=True, timeout=30)
                                require(p.returncode == 0 and not p.stderr, f'M3 timing lane probe failed: {plugin}/{lane}: {p.stderr}')
                                obs = parse_json(p.stdout)
                                require(obs['lane'] == lane and obs['lifecycle'] == lifecycle and
                                        all(obs[k] == 1 for k in ('encoded_verified', 'decoded_verified', 'loops', 'warmups')) and
                                        out.stat().st_size == ref['bytes'] and out.read_bytes() == frame.read_bytes(),
                                        'M3 timing worker result differs from retained real-corpus reference')
                                _verify_execution_info(item, 'encode', obs['warmup_encode_info'])
                                _verify_execution_info(item, backend, obs['warmup_decode_info'])
                                rows.append({'work_item_id': item['work_item_id'], 'dataset_id': item['dataset_id'],
                                             'route': item['route'], 'unit_index': index, 'backend': backend,
                                             'lifecycle': lifecycle, 'lane': lane, 'frame_sha256': ref['sha256'],
                                             'encode_native': obs['warmup_encode_info'], 'decode_native': obs['warmup_decode_info']})
                                out.unlink()
    body = {'schema': 'bmk.m3-fixed-batch-timing-lane-probe/1', 'plan_content_id': plan['plan_content_id'],
            'run_id': run.name, 'functional_seal_id': audit['seal_id'], 'timing_build': asset_refs,
            'source_policy': 'rebind_original_span_and_schema_to_retained_reference', 'results': rows,
            'timing_observations_retained': False, 'timing_admitted': False, 'stage_accepted': False}
    if full_ledger:
        body['source_projection'] = audit['source_projection']
    return {**body, 'probe_id': content_id(body)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--full-ledger', action='store_true', help='use decisions from the complete sealed functional ledger')
    parser.add_argument('--out', type=Path, help='write a new probe JSON after validation')
    args = parser.parse_args()
    result = probe(load_json(args.plan), args.run.resolve(strict=True), args.build.resolve(strict=True), full_ledger=args.full_ledger)
    if args.out is None:
        print(json.dumps(result, indent=2))
    else:
        write_new(args.out, result)
