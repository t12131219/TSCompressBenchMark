"""Static inventory only: never imports/loads codecs or executes build recipes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
HASHES: dict[Path, str] = {}


def digest(path: Path) -> str:
    resolved = path.resolve()
    if resolved not in HASHES:
        with resolved.open('rb') as stream:
            HASHES[resolved] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return HASHES[resolved]


def label(path: Path) -> str:
    path = path.resolve()
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def entry(path: Path) -> dict[str, Any]:
    return {'path': label(path), 'sha256': digest(path), 'size_bytes': path.stat().st_size}


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def path_from(value: str, base: Path = ROOT) -> Path:
    raw = Path(value)
    return raw if raw.is_absolute() else base / raw


def argv(item: Any) -> list[str]:
    if isinstance(item, str):
        return shlex.split(item)
    if isinstance(item, list):
        return item
    if isinstance(item, dict):
        return item.get('arguments') or argv(item.get('command', []))
    return []


def declared_check(record: dict[str, Any]) -> dict[str, Any]:
    verified, missing, drift = [], [], []
    for field in ('source_files', 'binding_sources', 'objects', 'patches', 'generated_source_files',
                  'compiled_source_closure', 'compiler_dependency_files', 'toolchain_files',
                  'toolchain_programs', 'runtime_dependencies', 'pinned_native_dependencies',
                  'runtime_dependency_listing', 'build_driver_files'):
        for item in record.get(field, []):
            path = path_from(item['path'])
            if not path.is_file():
                missing.append({'field': field, 'path': item['path']})
            elif digest(path) != item['sha256']:
                drift.append({'field': field, 'path': item['path']})
            else:
                verified.append({'field': field, 'path': item['path']})
    return {'status': 'PASS' if not missing and not drift else 'FAIL', 'verified_entry_count': len(verified),
            'missing': missing, 'drift': drift, 'scope': 'DECLARED_BYTES_ONLY_NOT_ACTUAL_EXEC_OR_LINK_INPUT_PROVENANCE'}


def parse_dep(path: Path, directory: Path) -> set[Path]:
    content = path.read_text().replace('\\\n', ' ')
    if ':' not in content:
        return set()
    return {path_from(item, directory).resolve() for item in shlex.split(content.partition(':')[2])}


def profile(codec: str, document: dict[str, Any], folder: Path) -> dict[str, Any]:
    record_path = folder / 'build-record.json'
    record = read(record_path)
    artifact = path_from(record['artifact'])
    factory = document['adapter']['factory']
    commands: list[dict[str, Any]] = []
    link_commands: list[dict[str, Any]] = []
    metadata_paths = []
    depfiles: list[Path] = []
    if factory == 'COMPLETED_REWRITE_CTYPES_V1':
        command_path = folder / 'cmake/compile_commands.json'
        metadata_paths.append(command_path)
        for item in json.loads(command_path.read_text()):
            commands.append({'directory': item['directory'], 'file': item['file'], 'arguments': argv(item)})
        depfiles = sorted((folder / 'cmake').rglob('*.o.d'))
        for path in sorted((folder / 'cmake').rglob('link.txt')):
            metadata_paths.append(path)
            link_commands.append({'record_kind': 'CMAKE_GENERATED_LINK_RECIPE_NOT_ACTUAL_EXEC_TRACE',
                                  'directory': str(folder / 'cmake'), 'recipe_file': entry(path),
                                  'arguments': argv(path.read_text().strip())})
        cache = folder / 'cmake/CMakeCache.txt'
        metadata_paths.append(cache)
        cache_tools = {}
        for line in cache.read_text().splitlines():
            if re.match(r'CMAKE_(?:C_COMPILER|CXX_COMPILER|LINKER|AR|RANLIB):', line):
                name, _, value = line.partition('=')
                cache_tools[name.partition(':')[0]] = entry(Path(value))
        tools = {'scope': 'CMAKE_CACHE_CURRENT_FILES_NOT_OBSERVED_CHILD_EXECUTIONS', 'selected_files': cache_tools}
    elif factory == 'SIMDCOMP_CTYPES_V1':
        command_path = folder / 'compile-command.json'
        metadata_paths.append(command_path)
        saved = read(command_path)
        for command in saved.get('commands', []):
            if '-c' in command:
                sources = [item for item in command if Path(item).suffix in {'.c', '.cc', '.cpp'}]
                commands.append({'directory': str(ROOT), 'file': sources[0], 'arguments': command})
            elif '-shared' in command:
                link_commands.append({'record_kind': 'SAVED_DRIVER_COMMAND_WITH_OBSERVED_RETURN_CODE_NOT_CHILD_EXEC_TRACE',
                                      'directory': str(ROOT), 'arguments': command})
        depfiles = sorted(folder.glob('*.d'))
        tools = {'scope': 'COMPILER_VERSION_AND_DRIVER_NAME_ONLY_NOT_TOOL_EXECUTABLE_HASH_CLOSURE',
                 'selected_files': [entry(Path('/usr/bin/cc'))], 'recorded_compiler_version': record['compiler']}
    else:
        command_path = folder / 'compile-command.json'
        metadata_paths.append(command_path)
        for command in record.get('translation_unit_commands', []):
            sources = [item for item in command if Path(item).suffix in {'.c', '.cc', '.cpp'}]
            commands.append({'directory': str(ROOT), 'file': sources[0], 'arguments': command})
        command = record.get('link_command')
        if command:
            link_commands.append({'record_kind': 'SAVED_DRIVER_COMMAND_NOT_CHILD_EXEC_TRACE',
                                  'directory': str(ROOT), 'arguments': command})
        depfiles = [path_from(item['path']) for item in record.get('compiler_dependency_files', [])]
        tools = {'scope': record.get('toolchain_discovery', 'UNDECLARED'),
                 'selected_files': record.get('toolchain_programs', []),
                 'actual_exec_trace_present': False}
        vendor_commands = folder / 'vendor-build/compile_commands.json'
        if vendor_commands.is_file():
            metadata_paths.append(vendor_commands)
            for item in json.loads(vendor_commands.read_text()):
                if 'CMakeFiles/liblzma.dir/' in item['command']:
                    commands.append({'directory': item['directory'], 'file': item['file'], 'arguments': argv(item),
                                     'kind': 'EXPLICIT_STATIC_DEPENDENCY_ARCHIVE_TRANSLATION_UNIT'})
            for path in sorted((folder / 'vendor-build/CMakeFiles/liblzma.dir').glob('link.txt')):
                metadata_paths.append(path)
                for line in path.read_text().splitlines():
                    link_commands.append({'record_kind': 'CMAKE_STATIC_ARCHIVE_GENERATED_RECIPE_NOT_EXEC_TRACE',
                                          'directory': str(folder / 'vendor-build'), 'recipe_file': entry(path),
                                          'arguments': argv(line)})
    dependency_union = set()
    for depfile in depfiles:
        directory = folder / 'cmake' if factory == 'COMPLETED_REWRITE_CTYPES_V1' else ROOT
        if 'vendor-build' in depfile.parts:
            directory = folder / 'vendor-build'
        dependency_union.update(parse_dep(depfile, directory))
    declared_union = {path_from(item['path']).resolve() for item in record.get('compiled_source_closure', [])}
    explicit_inputs = set()
    for command in link_commands:
        for item in command['arguments']:
            if Path(item).suffix in {'.o', '.a', '.so'}:
                candidate = path_from(item, Path(command['directory']))
                if candidate.is_file():
                    explicit_inputs.add(candidate.resolve())
    recorded_pinned = {path_from(item['path']).resolve() for field in ('objects', 'compiled_source_closure', 'pinned_native_dependencies', 'toolchain_files') for item in record.get(field, [])}
    saved_command = read(command_path)
    # XZ's anonymous legacy recipe pins the explicit archive separately.
    if isinstance(saved_command, dict) and saved_command.get('dependency_archive_sha256'):
        candidate = folder / 'vendor-build/liblzma.a'
        if candidate.is_file() and digest(candidate) == saved_command['dependency_archive_sha256']:
            recorded_pinned.add(candidate.resolve())
    artifact_status = artifact.is_file() and digest(artifact) == record['artifact_sha256']
    result = {
        'codec': codec, 'profile': record['profile'], 'factory': factory,
        'record': entry(record_path), 'artifact': entry(artifact),
        'artifact_matches_saved_record': artifact_status,
        'declared_hash_verification': declared_check(record),
        'translation_unit_count': len(commands), 'translation_unit_commands': commands,
        'dependency_file_count': len(depfiles), 'dependency_files': [entry(path) for path in depfiles],
        'depfile_union_count': len(dependency_union), 'declared_source_closure_count': len(declared_union),
        'depfile_union_outside_saved_source_closure': sorted(label(path) for path in dependency_union - declared_union),
        'saved_source_closure_outside_depfile_union': sorted(label(path) for path in declared_union - dependency_union),
        'tool_selection_evidence': tools, 'link_recipes': link_commands,
        'explicit_link_inputs_current_static_inventory': [{**entry(path), 'pinned_in_saved_record': path in recorded_pinned} for path in sorted(explicit_inputs)],
        'current_object_count': len(list(folder.rglob('*.o'))),
        'current_object_bytes': sum(path.stat().st_size for path in folder.rglob('*.o')),
        'metadata_files': [entry(path) for path in metadata_paths],
        'crt_static_runtime_linker_script_observation': 'NO_ACTUAL_LINKTRACE_IN_OLD_RECORD_NOT_RETROACTIVELY_RECOVERABLE',
        'actual_exec_trace_in_old_record': False, 'full_N1_granted': False,
        'fresh_rebuild_needed_for': ['SUCCESSFUL_CHILD_EXECVE_AND_EXECUTABLE_HASH', 'ALL_SUCCESSFUL_BUILD_INPUT_OPENS', 'LINKER_SCRIPT_CRT_ARCHIVE_MEMBER_INPUTS', 'PRE_POST_TOOL_AND_INPUT_IMMUTABILITY', 'NATIVE_TEST_EXECUTABLE_BUILD_CLOSURE_IF_QUALIFIED'],
        'can_verify_current_without_rebuild': ['DECLARED_FILE_SHA256', 'SAVED_DRIVER_RECIPE', 'COMPILER_DEPFILE_TU_HEADER_LIST', 'EXPLICIT_OBJECT_AND_ARCHIVE_CURRENT_BYTES', 'ELF_METADATA_BY_READ_ONLY_INSPECTION'],
    }
    (OUT / 'profiles').mkdir(exist_ok=True)
    with (OUT / 'profiles' / (codec + '--' + record['profile'] + '.json')).open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main() -> None:
    scope_path = ROOT / 'registry/algorithm_scope.json'
    scope = read(scope_path)
    active = sorted(scope['registered_codecs'])
    results = []
    snapshots = [entry(scope_path)]
    for codec in active:
        manifest_path = ROOT / 'registry/codecs' / (codec + '.json')
        document = read(manifest_path)
        snapshots.append(entry(manifest_path))
        release = ROOT / document['adapter']['artifact_path']
        for profile_name in ('release', 'sanitizer', 'debug'):
            folder = release.parent.parent / profile_name
            if (folder / 'build-record.json').is_file():
                results.append(profile(codec, document, folder))
    tools = []
    for name in ('strace', 'ltrace', 'perf', 'bpftrace', 'readelf', 'objdump', 'nm', 'ld', 'gcc', 'g++', 'clang', 'clang++', 'cc', 'c++', 'cmake', 'ninja', 'make', 'ar', 'ranlib', 'patch'):
        selected = shutil.which(name)
        tools.append({'name': name, 'available': selected is not None, 'selected_path': selected,
                      'resolved_file': entry(Path(selected)) if selected else None})
    crt_candidates = []
    for directory, patterns in ((Path('/usr/lib/gcc/x86_64-linux-gnu/11'), ('crt*.o', 'libgcc*.a', 'libasan*.a', 'libubsan*.a', 'libstdc++*.a', 'libstdc++*.so', 'libgcc_s.so')),
                                (Path('/usr/lib/x86_64-linux-gnu'), ('crt*.o', 'libc.so', 'libm.so', 'libpthread.so')),
                                (Path('/usr/lib/llvm-14/lib/clang/14.0.0/lib/linux'), ('libclang_rt*asan*.a', 'libclang_rt*ubsan*.a'))):
        for pattern in patterns:
            crt_candidates.extend(entry(path) for path in sorted(directory.glob(pattern)) if path.is_file())
    summary = {
        'schema_version': 'tscb.static-build-link-gap-inventory.v1',
        'scope': 'STATIC_FILE_AND_RECIPE_INSPECTION_NO_REBUILD_CODEC_LOAD_TEST_OR_MEASUREMENT',
        'active_codec_count': len(active), 'profile_count': len(results),
        'current_saved_artifact_hash_matches': sum(row['artifact_matches_saved_record'] for row in results),
        'declared_hash_verification_PASS': sum(row['declared_hash_verification']['status'] == 'PASS' for row in results),
        'total_translation_units_including_registered_CMake_test_targets': sum(row['translation_unit_count'] for row in results),
        'total_depfiles': sum(row['dependency_file_count'] for row in results),
        'total_current_object_bytes': sum(row['current_object_bytes'] for row in results),
        'tool_availability': tools,
        'ptrace_probe': {'sandbox': 'PTRACE_TRACEME_DENIED', 'auto_review_approved_own_true_child_outside_sandbox': 'PASS', 'never_attached_to_other_processes': True,
                         'evidence_files': [entry(path) for path in sorted((OUT / 'tool_probe').glob('*'))]},
        'current_readable_CRT_static_archive_script_candidates': crt_candidates,
        'candidate_scope': 'AVAILABLE_FILES_ONLY_NOT_OBSERVED_OLD_LINK_INPUT_SELECTION',
        'registration_snapshots': snapshots, 'driver': entry(Path(__file__)),
        'profiles': [{key: row[key] for key in ('codec', 'profile', 'factory', 'record', 'artifact', 'artifact_matches_saved_record', 'translation_unit_count', 'dependency_file_count', 'current_object_count', 'current_object_bytes', 'actual_exec_trace_in_old_record', 'full_N1_granted')} for row in results],
        'unresolved_full_N1_profiles': len(results),
        'historical_artifacts_records_and_registration_modified': False,
        'environment': {'PATH': os.environ.get('PATH'), 'CC': os.environ.get('CC'), 'CXX': os.environ.get('CXX'), 'LD_LIBRARY_PATH': os.environ.get('LD_LIBRARY_PATH')},
    }
    with (OUT / 'inventory_v1.json').open('x') as stream:
        stream.write(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: summary[key] for key in ('active_codec_count', 'profile_count', 'current_saved_artifact_hash_matches', 'declared_hash_verification_PASS', 'total_translation_units_including_registered_CMake_test_targets', 'total_depfiles', 'total_current_object_bytes', 'unresolved_full_N1_profiles')}, indent=2))


if __name__ == '__main__':
    main()
