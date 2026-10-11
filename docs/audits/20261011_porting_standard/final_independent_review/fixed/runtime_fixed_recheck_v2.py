"""Run only after source stability approval; compile and load non-codec toy DSOs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[5]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(value)


def reference(path):
    return {'path': str(path), 'sha256': sha(path)}


def source_snapshot():
    return [reference(path) for path in sorted((REPOSITORY / 'src/tscompbench/adapters').glob('*.py'))] + [reference(REPOSITORY / 'src/tscompbench/planning/resolution.py')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, required=True)
    parser.add_argument('--execute-after-stability-notice', action='store_true', required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = source_snapshot()
    good, alternative = output / 'recorded-runtime', output / 'alternative-runtime'
    folder = output / 'artifacts/release'
    for directory in (good, alternative, folder, output / 'src/tscompbench/adapters'):
        directory.mkdir(parents=True, exist_ok=False)
    for source in (REPOSITORY / 'src/tscompbench/adapters').glob('*.py'):
        shutil.copy2(source, output / 'src/tscompbench/adapters' / source.name)
    child = output / 'runtime_fixed_child.py'
    shutil.copy2(Path(__file__).with_name('runtime_fixed_child_v2.py'), child)
    sources = {
        output / 'recorded.c': 'int toy_runtime_value(void) { return 11; }\n',
        output / 'alternative.c': 'int toy_runtime_value(void) { return 22; }\n',
        output / 'wrapper.c': 'extern int toy_runtime_value(void);\nint toy_entry(void) { return toy_runtime_value(); }\n',
        output / 'auditor.c': '#define _GNU_SOURCE\n#include <link.h>\nunsigned int la_version(unsigned int version) { (void)version; return LAV_CURRENT; }\n',
    }
    for path, content in sources.items():
        write(path, content)
    artifact = folder / 'libtoy_wrapper.so'
    auditor = output / 'libtoy_noop_auditor.so'
    commands = [
        ['cc', '-shared', '-fPIC', '-Wl,-soname,libtoy_runtime.so', str(output / 'recorded.c'), '-o', str(good / 'libtoy_runtime.so')],
        ['cc', '-shared', '-fPIC', '-Wl,-soname,libtoy_runtime.so', str(output / 'alternative.c'), '-o', str(alternative / 'libtoy_runtime.so')],
        ['cc', '-shared', '-fPIC', str(output / 'wrapper.c'), '-L', str(good), '-ltoy_runtime', '-Wl,-rpath,' + str(good), '-o', str(artifact)],
        ['cc', '-shared', '-fPIC', str(output / 'auditor.c'), '-o', str(auditor)],
    ]
    environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LD_LIBRARY_PATH': str(good)}
    environment.pop('LD_PRELOAD', None)
    environment.pop('LD_AUDIT', None)
    compile_logs = []
    for command in commands:
        result = subprocess.run(command, env=environment, capture_output=True, text=True, check=True)
        compile_logs.append({'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    listing = subprocess.run(['ldd', str(artifact)], env=environment, capture_output=True, text=True, check=True).stdout
    runtimes = sorted({Path(value).resolve() for value in re.findall(r'(?:=>\s+)?(/\S+)\s+\(', listing)})
    command = {'schema_version': 'tscb.compile-command.v1', 'profile': 'release', 'command': commands[2]}
    canonical = json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    write(folder / 'compile-command.json', canonical.decode() + '\n')
    record = {
        'schema_version': 'tscb.build-artifact.v1', 'algorithm': 'lz4-frame', 'profile': 'release',
        'artifact': str(artifact.relative_to(output)), 'artifact_sha256': sha(artifact),
        'compile_commands_sha256': hashlib.sha256(canonical).hexdigest(),
        'compiled_source_closure': [reference(output / 'recorded.c'), reference(output / 'wrapper.c')],
        'runtime_dependencies': [reference(path) for path in runtimes],
    }
    # Compiler/source entries are project relative, external runtime entries keep
    # their actual absolute paths. No real codec record is modified or reused.
    for entry in record['compiled_source_closure']:
        entry['path'] = str(Path(entry['path']).relative_to(output))
    write(folder / 'build-record.json', json.dumps(record, indent=2) + '\n')

    def probe(action, profile, changes=None):
        selected = {**environment, **(changes or {})}
        process = subprocess.run([sys.executable, str(child), str(REPOSITORY), str(output), action, profile], env=selected, capture_output=True, text=True, check=True, timeout=60)
        value = json.loads(process.stdout)
        value['child_stderr'] = process.stderr
        return value

    captures = [probe('capture', 'profile_good'), probe('capture', 'profile_alternative', {'LD_LIBRARY_PATH': str(alternative)})]
    cases = []
    for profile in ('legacy', 'profile_good'):
        for action, changes, accepted in (
            ('baseline', {}, True),
            ('search_path_replacement', {'LD_LIBRARY_PATH': str(alternative)}, False),
            ('already_loaded_replacement', {}, False),
            ('preload', {'LD_PRELOAD': str(alternative / 'libtoy_runtime.so')}, False),
            ('audit', {'LD_AUDIT': str(auditor)}, False),
            ('swap_between_guard_and_load', {}, False),
        ):
            value = probe(action, profile, changes)
            value['expected_factory_status'] = 'PASS' if accepted else 'REJECTED'
            value['expected_session_status'] = 'PASS' if accepted else 'NOT_REACHED'
            cases.append(value)
    value = probe('profile_hash_mismatch', 'profile_good')
    value['expected_factory_status'] = 'REJECTED'
    value['expected_session_status'] = 'NOT_REACHED'
    cases.append(value)
    alternate = probe('baseline', 'profile_alternative', {'LD_LIBRARY_PATH': str(alternative)})
    alternate['expected_factory_status'] = 'PASS'
    alternate['expected_session_status'] = 'PASS'
    cases.append(alternate)
    baseline = next(case for case in cases if case['action'] == 'baseline' and case['profile'] == 'profile_good')
    identities = {
        'baseline': baseline.get('execution_identity'), 'explicit_alternative_profile': alternate.get('execution_identity'),
        'artifact_identity_changed': baseline.get('execution_identity', {}).get('artifact_sha256') != alternate.get('execution_identity', {}).get('artifact_sha256'),
        'adapter_identity_changed': baseline.get('execution_identity', {}).get('adapter_id') != alternate.get('execution_identity', {}).get('adapter_id'),
        'execution_path_identity_changed': baseline.get('execution_identity', {}).get('execution_path_hash') != alternate.get('execution_identity', {}).get('execution_path_hash'),
    }
    failures = []
    for case in cases:
        if case['declared_hashes']['status'] != 'PASS' or case['production_factory']['status'] != case['expected_factory_status'] or case.get('production_session', {}).get('status', 'NOT_REACHED') != case['expected_session_status']:
            failures.append({'action': case['action'], 'profile': case['profile'], 'reason': 'saved hashes or production factory result differs'})
        expected_adapters = 1 if case['expected_factory_status'] == 'PASS' or case['action'] == 'swap_between_guard_and_load' else 0
        expected_sessions = 1 if case['expected_session_status'] in ('PASS', 'REJECTED') else 0
        expected_operations = 1 if case['expected_session_status'] == 'PASS' else 0
        if case['constructor_calls'] != expected_adapters or case['session_constructor_calls'] != expected_sessions or case['toy_operation_calls'] != expected_operations:
            failures.append({'action': case['action'], 'profile': case['profile'], 'reason': 'pre/post factory load guards were not observed'})
        if expected_sessions and (case.get('artifact_mapped_before_session') is not True or case['post_load_guard_calls'] < 1):
            failures.append({'action': case['action'], 'profile': case['profile'], 'reason': 'factory admitted load or post-load guard missing before lazy session'})
        if case['action'] == 'swap_between_guard_and_load' and case['post_load_guard_calls'] < 1:
            failures.append({'action': case['action'], 'profile': case['profile'], 'reason': 'replacement was not rejected by actual post-load guard'})
    if not all(identities[key] for key in ('artifact_identity_changed', 'adapter_identity_changed', 'execution_path_identity_changed')):
        failures.append({'reason': 'explicit runtime profile did not change all expected identities'})
    after = source_snapshot()
    if before != after:
        failures.append({'reason': 'production source changed during probes'})
    result = {
        'status': 'PASS' if not failures else 'FAIL',
        'scope': 'NON_CODEC_DSO_REAL_FACTORY_PRE_POST_RUNTIME_GUARDS_AND_EXECUTION_IDENTITY',
        'actual_codec_execution': False, 'benchmark_execution': False,
        'constructor_substitution': 'Only Lz4FrameAdapter is replaced in isolated children with a lazy toy adapter; production factory preloads/pins verified runtime before its create_session. Toy operation only occurs after admission. Production factory/evidence/runtime/resolution functions unchanged; two explicit race-window cases inject a non-codec alternative immediately before factory CDLL to observe post-load rejection.',
        'source_snapshot_before': before, 'source_snapshot_after': after,
        'initial_harness_failure': {'result': reference(Path(__file__).parent / 'runtime_resolution_r1/result.json'), 'cause': 'Independent probe used nonexistent CapabilityStatus.SUPPORTED; guard behavior succeeded, identity helper failed. Original result and script preserved.'},
        'review_driver': reference(Path(__file__)), 'child_driver': reference(child),
        'compile_logs': compile_logs, 'captures': captures, 'cases': cases, 'identity_binding': identities, 'failures': failures,
        'limits': ['Does not grant complete static-link/toolchain N1 closure.', 'Does not grant full source parity, N0-N5/G0-G6, FULL_PARITY, codec safety or current formal performance.', 'Only demonstrated loader substitution/interposition cases and DT_NEEDED paths are covered.'],
    }
    write(output / 'result.json', json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'status': result['status'], 'case_count': len(cases), 'failures': failures, 'identity_binding': identities, 'result': str(output / 'result.json')}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
