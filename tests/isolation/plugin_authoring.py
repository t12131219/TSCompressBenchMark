#!/usr/bin/env python3
"""Run real catalog/build/ABI/CLI evolution on a reduced staged checkout."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.assets import canonical_bytes, digest, load_json  # noqa: E402


PLUGIN = 'test-xor-f64'
RAW_REGISTRATION = '\n[plugins."raw-store"]\nenabled = true\nmanifest = "plugins/codecs/raw-store/plugin.json"\n'
NEW_REGISTRATION = '\n[plugins."test-xor-f64"]\nenabled = true\nmanifest = "plugins/codecs/test-xor-f64/plugin.json"\n'


def demand(condition, message):
    if not condition:
        raise RuntimeError(message)


def write(path, value):
    path.write_bytes(canonical_bytes(value) + b'\n')


def main(out: Path) -> None:
    out.mkdir(exist_ok=False)
    stage = out / 'relocated project'
    stage.mkdir()
    for name in ('CMakeLists.txt', 'bmk', 'pyproject.toml'):
        shutil.copyfile(ROOT / name, stage / name)
    for name in ('cmake', 'include', 'src', 'native', 'tools', 'schemas'):
        shutil.copytree(ROOT / name, stage / name, ignore=shutil.ignore_patterns('__pycache__'))
    raw = stage / 'plugins/codecs/raw-store'
    raw.parent.mkdir(parents=True)
    shutil.copytree(ROOT / raw.relative_to(stage), raw)
    (stage / 'catalog').mkdir()
    index = stage / 'catalog/plugins.toml'
    shutil.copyfile(ROOT / 'catalog/plugins.toml', index)
    source_index = index.read_text()
    shutil.copytree(ROOT / 'datasets/fixtures', stage / 'datasets/fixtures')
    suite_dir = stage / 'configs/suites/authoring_v1'
    suite_dir.mkdir(parents=True)
    package = stage / 'plugins/codecs' / PLUGIN
    logs = out / 'logs'
    logs.mkdir()
    excluded = out / 'unregistered-sources'
    checks = []
    core_files = [p for p in stage.rglob('*') if p.is_file() and p.relative_to(stage).parts[0]
                  in {'src', 'native', 'cmake', 'CMakeLists.txt', 'include', 'schemas', 'tools', 'bmk'}]
    core_hashes = {p: digest(p) for p in core_files}

    def invoke(label, argv, *, rc=0, contains=None):
        proc = subprocess.run(argv, cwd=stage, check=False, capture_output=True, text=True, timeout=120)
        (logs / (label + '.stdout')).write_text(proc.stdout)
        (logs / (label + '.stderr')).write_text(proc.stderr)
        demand(proc.returncode == rc and (contains is None or contains in proc.stderr),
               f'{label}: unexpected code={proc.returncode}; see {logs}')
        return proc.stdout

    def configure(label, selection, directory, *, rc=0, contains=None):
        invoke(label, ['cmake', '-S', '.', '-B', directory, '-DBUILD_TESTING=OFF', '-DCMAKE_BUILD_TYPE=Release',
                       f'-DPython3_EXECUTABLE={sys.executable}', f'-DTSBENCH_PLUGINS={selection}'], rc=rc, contains=contains)

    def build(label, directory):
        invoke(label, ['cmake', '--build', directory, '--parallel', '3'])

    def bmk(label, *command, rc=0, contains=None):
        stdout = invoke(label, [sys.executable, '-B', './bmk', *command], rc=rc, contains=contains)
        return json.loads(stdout) if rc == 0 else None

    def definition(plugin, role='value', **options):
        write(suite_dir / 'suite.json', {'schema': 'bmk.dev-lossless-suite/1', 'id': 'authoring_v1',
             'verification': 'artifact_each', 'timeout_seconds_per_operation': 5,
             'fixture_manifest': 'datasets/fixtures/manifest.json', 'fixtures': ['f64-bits.npy'],
             'methods': [{'plugin': plugin, 'role': role, 'options': options}]})

    def library(directory, plugin):
        binary = 'libbmk_raw_store.so' if plugin == 'raw-store' else 'libtest_xor_f64.so'
        return f'{directory}/plugins/codecs/{plugin}/{binary}'

    def lock(label, directory, plugin):
        dest = f'{label}.build.json'
        bmk(label + '-lock', 'lock-build', '--worker', f'{directory}/tsbench_cpu_worker', '--plugin',
            f'{plugin}={library(directory, plugin)}', '--out', dest)
        return dest

    def freeze(label, lock_path, *, rc=0, contains=None):
        dest = f'{label}.plan.json'
        bmk(label + '-plan', 'smoke-plan', '--suite', 'authoring_v1', '--build-lock', lock_path, '--out', dest,
            rc=rc, contains=contains)
        return dest

    def run(label, lock_path):
        plan = freeze(label, lock_path)
        result = bmk(label + '-run', 'smoke-run', '--plan', plan)
        demand(result['statuses'] == {'verified': 1} and not result['qualification_granted'], f'{label} did not verify')
        return load_json(stage / plan), result

    def install(version):
        recipe = package / 'CMakeLists.txt'
        if version == 2:
            with recipe.open('a') as file:
                file.write('target_compile_definitions(test_xor_f64 PRIVATE WIRE_VERSION=2)\n')
        props = {} if version == 1 else {'key': {'type': 'integer', 'enum': [90, 165], 'default': 90}}
        write(package / 'options.json', {'type': 'object', 'additionalProperties': False,
              'properties': props, 'required': []})
        files = [str((package / p).relative_to(stage)) for p in ('CMakeLists.txt', 'xor_f64.c')]
        write(package / 'plugin.json', {'schema': 'bmk.plugin/1', 'kind': 'codec', 'id': PLUGIN, 'abi_version': 1,
             'implementation_version': f'v{version}', 'format_id': f'test.xor.f64.v{version}', 'roles': ['value'],
             'supported_tasks': ['linear_f64_bitwise'], 'options_schema': f'plugins/codecs/{PLUGIN}/options.json',
             'source_files': files + ['include/tsbench/plugin_abi.h'],
             'build': {'cmake_dir': f'plugins/codecs/{PLUGIN}', 'target': 'test_xor_f64'}})

    configure('baseline-configure', 'raw-store', 'build/base')
    build('baseline-build', 'build/base')
    definition('raw-store')
    raw_lock = lock('baseline', 'build/base', 'raw-store')
    baseline_plan, baseline = run('baseline', raw_lock)
    checks.append('unselected_missing_packages_and_archives_do_not_block_bounded_raw_task')

    shutil.copytree(ROOT / 'tests/fixtures/plugin-authoring/xor-f64', package)
    index.write_text(source_index + NEW_REGISTRATION)
    install(1)
    configure('added-configure', f'raw-store;{PLUGIN}', 'build/base')
    build('added-build', 'build/base')
    old_lock = lock('added', 'build/base', PLUGIN)
    old_manifest = load_json(package / 'plugin.json')
    old_options = load_json(package / 'options.json')
    definition(PLUGIN, role='bytes')
    freeze('wrong-role', old_lock, rc=2, contains='plugin role not declared')
    definition(PLUGIN)
    old_plan, old = run('added', old_lock)
    case = old['cases'][0]
    prev = stage / 'results' / old['run_id']
    before = {p: digest(p) for p in prev.rglob('*') if p.is_file() and 'derived' not in p.relative_to(prev).parts}
    demand(case['original_sha256'] == baseline['cases'][0]['original_sha256'] and
           case['task'] == baseline['cases'][0]['task'], 'method switch changed the workload')
    checks.append('same_task_alternative_plugin_from_local_package_without_core_changes')

    index.write_text(index.read_text().replace(RAW_REGISTRATION, RAW_REGISTRATION.replace('true', 'false')))
    raw.rename(excluded)
    configure('disabled-configure-rejected', 'raw-store', 'build/reject', rc=1, contains='disabled plugin: raw-store')
    invoke('disabled-autoreconfigure-rejected', ['cmake', '--build', 'build/base'], rc=2, contains='disabled plugin: raw-store')
    definition('raw-store')
    freeze('disabled-run-rejected', raw_lock, rc=2, contains='disabled plugin: raw-store')
    configure('disabled-other-configure', PLUGIN, 'build/only')
    build('disabled-other-build', 'build/only')
    demand(not (stage / 'build/only/plugins/codecs/raw-store').exists(), 'disabled codec was built')
    definition(PLUGIN)
    _, alone = run('disabled-other', lock('disabled-other', 'build/only', PLUGIN))
    demand(alone['cases'][0]['artifact']['sha256'] == case['artifact']['sha256'], 'disable changed other format bytes')
    checks.append('disabled_and_missing_package_build_and_plan_rejected_while_other_method_still_runs')

    index.write_text(index.read_text().replace(RAW_REGISTRATION.replace('true', 'false'), ''))
    definition('raw-store')
    freeze('removed-run-rejected', raw_lock, rc=2, contains='unknown plugin: raw-store')
    configure('removed-configure-rejected', 'raw-store', 'build/reject', rc=1, contains='unknown plugin: raw-store')
    checks.append('removed_registration_is_not_silently_substituted')

    install(2)
    configure('upgrade-configure', PLUGIN, 'build/v2')
    build('upgrade-build', 'build/v2')
    new_lock = lock('upgrade', 'build/v2', PLUGIN)
    definition(PLUGIN)
    freeze('stale-build-rejected', old_lock, rc=2, contains='plugin manifest_id differs from build lock')
    default = load_json(stage / freeze('upgrade-default', new_lock))
    demand(default['methods'][PLUGIN]['options'] == {'key': 90}, 'new option default not expanded')
    definition(PLUGIN, key=1)
    freeze('invalid-new-option', new_lock, rc=2, contains='unknown enum value')
    definition(PLUGIN, key=165)
    new_plan, new = run('upgrade-override', new_lock)
    demand(new_plan['methods'][PLUGIN]['options'] == {'key': 165} and
           new_plan['methods'][PLUGIN]['configuration_id'] != default['methods'][PLUGIN]['configuration_id'] and
           old_plan['build']['build_id'] != new_plan['build']['build_id'], 'configuration or implementation identity did not change')
    new_run = stage / 'results' / new['run_id']
    observation = json.loads((new_run / 'observations.jsonl').read_text())
    demand(observation['execution']['encode']['key'] == 165 and observation['execution']['encode']['backend'] == 'test-xor-v2',
           'override did not reach the actual codec entry')
    checks.append('incompatible_replacement_and_new_plugin_option_bind_distinct_build_and_resolved_config')

    # The old build is still present but no compiler, registry or input file is passed to decode.
    # Move the staged fixture directory away before either independent decode attempt.
    (stage / 'datasets/fixtures').rename(out / 'retired-inputs')
    artifact = prev / case['artifact']['path']
    old_binary = old_plan['build']['plugins'][PLUGIN]['library']
    old_worker = old_plan['build']['worker']
    demand(all(digest(stage / binding['path']) == binding['sha256'] for binding in (old_binary, old_worker)),
           'retained build differs from old lock')
    invoke('upgrade-old-artifact-rejected', ['build/v2/tsbench_cpu_worker', 'decode', str(stage / library('build/v2', PLUGIN)), PLUGIN,
           '{"key":165}', str(artifact), 'unexpected.bin', 'unexpected.json'], rc=3, contains='plugin status 5')
    demand(not (stage / 'unexpected.bin').exists() and not (stage / 'unexpected.json').exists(), 'rejected decode left outputs')
    invoke('retained-v1-decoder', ['build/base/tsbench_cpu_worker', 'decode', str(stage / library('build/base', PLUGIN)), PLUGIN,
           '{}', str(artifact), 'restored.bin', 'restored.json'])
    src = old_plan['inputs']['f64-bits.npy']
    demand(digest(stage / 'restored.bin') == src['raw_sha256'] and digest(stage / 'restored.json') == src['schema_sha256'],
           'retained old decoder failed exact restore')
    demand(bmk('sealed-report-recompute', 'smoke-report', old['run_id']) == old and
           all(digest(p) == h for p, h in before.items()), 'historical evidence mutated')
    demand(all(digest(p) == sha for p, sha in core_hashes.items()), 'core changed during authoring regression')
    demand(not (stage / 'third_party').exists(), 'unexpected third-party tree in reduced checkout')
    checks.append('incompatible_new_decoder_rejects_retained_old_decoder_restores_without_input_and_report_is_stable')
    write(out / 'retained-decoder-v1.json', {'manifest': old_manifest, 'options_schema': old_options,
          'build': old_plan['build'], 'decoder_options': old_plan['methods'][PLUGIN]['options'],
          'artifact': {**case['artifact'], 'path': artifact.relative_to(stage).as_posix()},
          'original_sha256': src['raw_sha256'], 'decoded_schema_sha256': src['schema_sha256']})
    write(out / 'audit.json', {'schema': 'bmk.plugin-authoring-regression/1', 'qualification_granted': False,
          'checks': checks, 'platform': sys.platform, 'python': sys.version, 'namespace': os.readlink('/proc/self/ns/net'),
          'core_files_sha256': {p.relative_to(stage).as_posix(): sha for p, sha in core_hashes.items()},
          'nested_runs': [baseline['run_id'], old['run_id'], alone['run_id'], new['run_id']],
          'old_format_retained': 'test.xor.f64.v1', 'new_format': 'test.xor.f64.v2'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    main(args.out.resolve())
