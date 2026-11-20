#!/usr/bin/env python3
"""Build an unregistered CORAD reference-error-guard candidate off the frozen archive."""
from argparse import ArgumentParser
from pathlib import Path
import shutil
import subprocess

from prepare_plugin_source import ROOT, prepare
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset

PROFILE = 'catalog/selections/corad-reference-error-guard-candidate-v1.json'
RESTORE = 'native/measurement/corad_reference_guard/restore.c'
METHOD = 'corad-frozen'
TARGET = 'tsbench_corad_inference_control'


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size}


def build(frozen, output):
    profile_path = local_file(ROOT, PROFILE)
    spec = load_json(profile_path)
    require(spec['candidate_id'] == content_id({k: v for k, v in spec.items() if k != 'candidate_id'}), 'invalid guard candidate identity')
    original, = frozen['plugins'][METHOD]['dependencies']
    base = verify_asset(ROOT, original)
    parent = base.parent
    require(output.is_relative_to(ROOT / 'build'), 'guard build outside project build')
    output.mkdir(parents=True, exist_ok=False)
    source, patched, unchanged = (output / x for x in ('source', 'guard', 'frozen'))
    unchanged.mkdir()
    prepare(spec['source_id'], source)
    manifest = load_json(verify_asset(ROOT, load_json(ROOT / 'third_party/sources.lock.json')['sources'][spec['source_id']]['source_manifest']))
    expected = {f['path']: f['sha256'] for f in manifest['files']}
    member = spec['member']
    require(expected[member] == spec['before_sha256'], 'guard candidate patch input differs')
    with verify_asset(ROOT, spec['patch']).open('rb') as stream:
        subprocess.run(['/usr/bin/patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p1'],
                       cwd=source / spec['source_id'], stdin=stream, check=True)
    expected[member] = spec['after_sha256']
    require({p.relative_to(source).as_posix(): digest(p) for p in source.rglob('*') if p.is_file()} == expected,
            'guard patch changed files beyond the declared member')
    subprocess.run(['/usr/bin/cmake', '-S', str(source / spec['source_id']), '-B', str(patched), '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['/usr/bin/cmake', '--build', str(patched), '--target', 'corad_c', '-j2'], check=True)
    program = local_file(parent, TARGET)
    shutil.copy2(base, unchanged / base.name)
    for directory in (unchanged, patched):
        shutil.copy2(program, directory / TARGET)
    restore = local_file(ROOT, RESTORE)
    subprocess.run(['/usr/bin/cc', '-std=c11', '-O2', '-Werror', '-Wall', '-Wextra', str(restore),
                    '-I', str(source / spec['source_id'] / 'include'), '-L', str(unchanged), '-lcorad_c',
                    '-Wl,-rpath,$ORIGIN', '-o', str(unchanged / 'restore')], check=True)
    body = {'schema': 'bmk.corad-reference-error-guard-build/1', 'base_build_id': frozen['build_id'],
            'candidate': ref(profile_path), 'patch': spec['patch'], 'patched_source': ref(source / member),
            'restore_source': ref(restore), 'base_dependency': original, 'base_control': ref(program),
            'frozen': {'encode': ref(unchanged / TARGET), 'decode': ref(unchanged / 'restore'), 'library': ref(unchanged / base.name)},
            'guard': {'encode': ref(patched / TARGET), 'library': ref(patched / base.name)}}
    write_new(output / 'build-lock.json', {**body, 'build_id': content_id(body)})
    print(output / 'build-lock.json')


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    p.add_argument('--base-build-lock', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    build(load_json(a.base_build_lock), a.out.resolve())
