#!/usr/bin/env python3
"""Build an unregistered PBEPLA candidate from the verified Unique archive."""
from argparse import ArgumentParser
from pathlib import Path
import subprocess

from prepare_plugin_source import ROOT, prepare
from tsbench.application.m3_pbepla_grouped_timing import TOOL
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.recovery import plan_recovery

PROFILE = 'catalog/selections/pbepla-wide-grid-candidate-v1.json'
SCHEMA = 'bmk.pbepla-wide-grid-candidate-build/1'


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': digest(path), 'bytes': path.stat().st_size}


def build(source_plan, population, output, profile_name=PROFILE):
    profile = local_file(ROOT, profile_name)
    spec = load_json(profile)
    require(spec['schema'] == 'bmk.pbepla-wide-grid-candidate/1' and spec['selection'] == 87 and
            spec['role'] == 'diagnostic_candidate_not_unique_baseline' and
            spec['candidate_id'] == content_id({k: v for k, v in spec.items() if k != 'candidate_id'}),
            'invalid PBEPLA candidate identity')
    main, pop = load_json(source_plan), load_json(population)
    require(pop['source_plan'] == ref(source_plan), 'PBEPLA worker comes from a different M3 plan')
    runtime = pop['runtime']
    worker = runtime['files'][runtime['tools'][TOOL]]
    executable = {'path': worker['source'], 'sha256': worker['sha256']}
    legacy = main['build']['pbepla_corpus']['dependency']
    require(runtime['files']['lib/libtba_native.so']['sha256'] == legacy['sha256'],
            'PBEPLA grouped worker dependency differs from r40')
    require(output.is_relative_to(ROOT / 'build'), 'candidate build must remain in the workspace build directory')
    output.mkdir(parents=True)
    source, obj = output / 'source', output / 'objects'
    source_id = spec['source_id']
    prepare(source_id, source)
    lock = load_json(ROOT / 'third_party/sources.lock.json')['sources'][source_id]
    manifest = load_json(verify_asset(ROOT, lock['source_manifest']))
    expected = {row['path']: row['sha256'] for row in manifest['files']}
    for member in spec['members']:
        require(expected[member['path']] == member['before_sha256'], 'candidate patch input differs from archive lock')
        expected[member['path']] = member['after_sha256']
    with verify_asset(ROOT, spec['patch']).open('rb') as patch:
        subprocess.run(['/usr/bin/patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p1'],
                       cwd=source / source_id, stdin=patch, check=True)
    require({p.relative_to(source).as_posix(): digest(p) for p in source.rglob('*') if p.is_file()} == expected,
            'candidate changed undeclared source bytes')
    subprocess.run(['/usr/bin/cmake', '-S', str(source/source_id), '-B', str(obj), '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run(['/usr/bin/cmake', '--build', str(obj), '--target', 'tba_native', '-j2'], check=True)
    candidate = ref(obj / 'libtba_native.so')
    libraries = {'legacy': legacy, 'candidate': candidate}
    closures = {name: plan_recovery(ROOT, {}, (), tools={TOOL: executable},
                                   libraries=[{k: lib[k] for k in ('path', 'sha256')}])
                for name, lib in libraries.items()}
    body = {'schema': SCHEMA, 'candidate': ref(profile), 'source_plan': ref(source_plan), 'population': ref(population),
            'patch': spec['patch'], 'libraries': libraries, 'closures': closures,
            'patched_sources': [ref(local_file(source, m['path'])) for m in spec['members']]}
    write_new(output/'build-lock.json', {**body, 'build_id': content_id(body)})
    print(output/'build-lock.json')


if __name__ == '__main__':
    p = ArgumentParser(description=__doc__)
    for name in ('source-plan', 'population', 'out'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--profile', default=PROFILE, help='workspace-relative candidate lock')
    args = p.parse_args()
    build(args.source_plan.resolve(strict=True), args.population.resolve(strict=True), args.out.resolve(), args.profile)
