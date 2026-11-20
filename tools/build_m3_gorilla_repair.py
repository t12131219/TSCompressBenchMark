#!/usr/bin/env python3
"""Build the opt-in Gorilla state derivative in a dedicated directory."""
import argparse
from pathlib import Path
import shutil
import subprocess

from prepare_plugin_source import ROOT, prepare
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.planner.m3_gorilla_specialized import PROFILE, PROGRAMS, ref


def build(base, output):
    profile = load_json(local_file(ROOT, PROFILE))
    original = base['plugins']['gorilla-tv']['dependencies'][0]
    verify_asset(ROOT, original)
    parent = Path(original['path']).parent
    output = output.resolve()
    require(output.is_relative_to(ROOT / 'build'), 'repair build must be under the project build directory')
    output.mkdir(parents=True, exist_ok=False)
    source, native = output / 'source', output / 'native'
    prepare('gorilla-native', source)
    manifest = load_json(verify_asset(ROOT, load_json(ROOT / 'third_party/sources.lock.json')['sources']['gorilla-native']['source_manifest']))
    expected = {item['path']:item['sha256'] for item in manifest['files']}
    member = profile['patched_member']
    require(digest(local_file(source, member)) == profile['before_sha256'] == expected[member], 'patch input SHA differs')
    patch = verify_asset(ROOT, profile['patch'])
    with patch.open('rb') as stream:
        subprocess.run(['patch','--batch','--fuzz=0','--no-backup-if-mismatch','-p1'], cwd=source/'gorilla-native', stdin=stream, check=True)
    expected[member] = profile['after_sha256']
    require({p.relative_to(source).as_posix(): digest(p) for p in source.rglob('*') if p.is_file()} == expected,
            'patched tree changed outside the frozen member or expected result')
    subprocess.run(['cmake','-S',str(source/'gorilla-native'),'-B',str(native),'-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['cmake','--build',str(native),'--target','gorilla_c','-j','3'], check=True)
    programs = {}
    for name in PROGRAMS:
        shutil.copy2(local_file(ROOT, (parent / name).as_posix()), native / name)
        programs[name] = ref(ROOT, native / name)
    body = {'schema':'bmk.gorilla-state-repair-build/1', 'base_build_id':base['build_id'],
            'source_profile':ref(ROOT, ROOT / PROFILE), 'patched_source': ref(ROOT, source / member),
            'base_dependency':original, 'dependency':ref(ROOT,native/'libgorilla_c.so'), 'programs':programs}
    import json
    with (output / 'repair-lock.json').open('x', encoding='utf-8') as f:
        json.dump({**body,'repair_build_id':content_id(body)},f,indent=2)
        f.write('\n')


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-build-lock',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    build(load_json(a.base_build_lock),a.out)
