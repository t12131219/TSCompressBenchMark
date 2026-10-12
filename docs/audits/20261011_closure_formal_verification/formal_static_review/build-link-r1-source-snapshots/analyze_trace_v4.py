"""Read actual strace and ld map evidence; no codec load or build execution."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[4]


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity(path: Path) -> dict:
    path = path.resolve()
    return {'path': str(path), 'sha256': digest(path), 'size_bytes': path.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--codec', required=True)
    parser.add_argument('--profile', required=True)
    parser.add_argument('--trace-directory', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    driver_path = output_root / 'audit' / args.codec / args.profile / 'driver-report.json'
    driver = json.loads(driver_path.read_text())
    files = sorted(args.trace_directory.glob('process.*'))
    captures = {}
    versioned_captures = []
    read_capture = output_root / 'audit' / args.codec / args.profile / 'read-capture'
    for index_file in read_capture.glob('*.tsv'):
        pid = int(index_file.stem.split('-')[1])
        for line in index_file.read_text().splitlines():
            epoch,original,copied,size,failed = line.split('\t')
            if failed != '0': raise RuntimeError('input capture copy failure: '+original)
            selected=Path(copied)
            if selected.stat().st_size != int(size): raise RuntimeError('capture size drift')
            value={'original_path':original,'captured_file_path':copied,'sha256':digest(selected),
                   'size_bytes':int(size),'capture_scope':'SUCCESSFUL_READ_OPEN_RETURN_BEFORE_CALLER_READ',
                   'pid':pid,'epoch':float(epoch)}
            versioned_captures.append(value)
            captures.setdefault(original, []).append(value)
    for capture in (output_root / 'audit' / args.codec / args.profile / 'temporary-capture').glob('*.json'):
        value = json.loads(capture.read_text())
        if 'captured_file_path' not in value:
            continue
        if digest(Path(value['captured_file_path'])) != value['sha256']:
            raise RuntimeError('captured assembler input drift')
        captures.setdefault(value['original_path'], []).append(value)
    opened, written, executed, virtual, missing, undecoded, truncations = set(), set(), [], [], set(), [], []
    for path in files:
        pid = int(path.suffix.removeprefix('.'))
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if '<unfinished ...>' in line or 'resumed>' in line:
                # A per-pid trace normally uses complete syscall records; keep
                # explicit unresolved records if the environment differs.
                undecoded.append({'trace': str(path), 'line': number, 'text': line})
            if re.search(r'"\.\.\."|".*"\.\.\.', line):
                truncations.append({'trace': str(path), 'line': number})
            match = re.search(r'execve\(("(?:[^"\\]|\\.)*"),.*\)\s+=\s+0$', line)
            if match:
                name = json.loads(match[1])
                selected = Path(name)
                if not selected.is_absolute():
                    selected = ROOT / selected
                executed.append({'pid': pid, 'trace_file': str(path), 'line': number,
                                 'syscall': 'SUCCESSFUL_EXECVE', **identity(selected)})
            if re.search(r'\bopen(?:at|at2)?\(', line):
                match = re.search(r'=\s+\d+<(/.*?)>\s*$', line)
                if not match:
                    continue
                name = match[1]
                if 'O_DIRECTORY' in line:
                    continue
                if ' (deleted)' in name:
                    name = name.removesuffix(' (deleted)')
                selected = Path(name).resolve()
                if 'O_WRONLY' in line or 'O_CREAT' in line or 'O_TRUNC' in line:
                    written.add(selected)
                if 'O_WRONLY' not in line and 'O_CREAT' not in line and 'O_TRUNC' not in line:
                    if any(selected.is_relative_to(prefix) for prefix in ('/proc', '/dev', '/sys')):
                        virtual.append({'path': str(selected), 'scope': 'VIRTUAL_DEVICE_OR_NONREGULAR_FILE_NOT_HASHABLE_AS_SOURCE'})
                    elif selected.is_file():
                        opened.add(selected)
                    elif selected.is_dir():
                        pass
                    elif selected.exists():
                        virtual.append({'path': str(selected), 'scope': 'VIRTUAL_DEVICE_OR_NONREGULAR_FILE_NOT_HASHABLE_AS_SOURCE'})
                    elif str(selected) in captures:
                        opened.add(selected)
                    else:
                        missing.add(str(selected))
    read_files = []
    for path in sorted(opened):
        if path.is_file():
            value = identity(path)
        else:
            preserved = captures[str(path)][0]
            value = {'path': str(path), 'sha256': preserved['sha256'],
                     'size_bytes': preserved['size_bytes'],
                     'preserved_input_copy': preserved['captured_file_path'],
                     'capture_scope': preserved['capture_scope']}
        read_files.append({**value, 'generated_in_audit_output': path.is_relative_to(output_root) or (not path.is_file() and str(path) in captures),
                           'opened_for_write_during_run': path in written})
    for preserved in versioned_captures:
        selected = Path(preserved['original_path'])
        read_files.append({'path':str(selected),'sha256':preserved['sha256'],'size_bytes':preserved['size_bytes'],
                           'preserved_input_copy':preserved['captured_file_path'],'capture_scope':preserved['capture_scope'],
                           'pid':preserved['pid'],'epoch':preserved['epoch'],
                           'generated_in_audit_output':selected.is_relative_to(output_root) or str(selected).startswith('/tmp/cc'),
                           'opened_for_write_during_run':selected in written})
    execute_unique = sorted({Path(item['path']) for item in executed})
    kernel_interpreters = []
    for path in execute_unique:
        head = path.read_bytes()[:512]
        if head.startswith(b'#!'):
            interpreter = Path(head.splitlines()[0][2:].decode().strip().split()[0])
            kernel_interpreters.append({'executed_file': str(path), 'role': 'KERNEL_SHEBANG_INTERPRETER_FROM_EXECUTED_SCRIPT', **identity(interpreter)})
        elif head.startswith(b'\x7fELF'):
            output = subprocess.check_output(['/usr/bin/readelf', '-l', str(path)], text=True)
            match = re.search(r'Requesting program interpreter:\s*(.*?)\]', output)
            if match:
                interpreter = Path(match[1])
                kernel_interpreters.append({'executed_file': str(path), 'role': 'KERNEL_PT_INTERP_FROM_EXECUTED_ELF', **identity(interpreter)})
    link_maps = sorted(output_root.rglob('*.map'))
    map_cwds = {}
    for file in (output_root / 'audit' / args.codec / args.profile / 'temporary-capture').glob('link-*.json'):
        value=json.loads(file.read_text())
        for arg in value['actual_argv']:
            if arg.startswith('-Map='): map_cwds[Path(arg[5:]).resolve()]=Path(value['cwd'])
            if arg.startswith('-Wl,-t,-t,-Map,'): map_cwds[Path(arg.split('-Map,',1)[1]).resolve()]=Path(value['cwd'])
    
    map_inputs, archive_members = set(), []
    for path in link_maps:
        text = path.read_text()
        for line in text.splitlines():
            if line.startswith('LOAD '):
                raw = Path(line.removeprefix('LOAD ').strip())
                raw = raw if raw.is_absolute() else map_cwds.get(path, ROOT) / raw
                if raw.is_file() or str(raw.resolve()) in captures:
                    map_inputs.add(raw.resolve())
            for match in re.finditer(r'([^\s()]+\.a)\(([^)]+)\)', line):
                selected=Path(match[1]); selected=(map_cwds.get(path, ROOT)/selected).resolve() if not selected.is_absolute() else selected.resolve()
                item = {'archive': str(selected), 'member': match[2]}
                if item not in archive_members:
                    archive_members.append(item)
    baseline = {item['path']: item['sha256'] for item in driver['baseline_inputs_before']}
    checkpoint = {item['path']: item['sha256'] for call in driver['invocations'] for item in call['pre_invocation_inputs']}
    link_launcher_calls = []
    for file in (output_root / 'audit' / args.codec / args.profile / 'temporary-capture').glob('link-*.json'):
        value = json.loads(file.read_text())
        link_launcher_calls.append(value)
        checkpoint.update({item['path']:item['sha256'] for item in value['pre_invocation_inputs']})
    unmatched = [item['path'] for item in read_files if not item['generated_in_audit_output'] and item['path'] not in baseline and item['path'] not in checkpoint]
    verified_checkpoint_drift = [path for path,expected in checkpoint.items()
        if (digest(Path(path)) != expected if Path(path).is_file()
            else expected not in {item['sha256'] for item in captures.get(path,[])})]
    def input_identity(path):
        if path.is_file(): return identity(path)
        item=captures[str(path)][0]
        return {'path':str(path),'sha256':item['sha256'],'size_bytes':item['size_bytes'],
                'preserved_input_copy':item['captured_file_path']}
    
    old = json.loads((ROOT / 'registry/codecs' / (args.codec + '.json')).read_text())
    old_release = ROOT / old['adapter']['artifact_path']
    old_folder = old_release.parent.parent / args.profile
    new_folder = output_root / args.codec.replace('-', '_') / args.profile
    old_record = json.loads((old_folder / 'build-record.json').read_text())
    new_record = driver['new_recipe_record'] or {}
    object_scope = 'SAVED_BUILD_RECORD_OBJECTS'
    old_objects = {Path(item['path']).name: item['sha256'] for item in old_record.get('objects', [])}
    new_objects = {Path(item['path']).name: item['sha256'] for item in new_record.get('objects', [])}
    if not old_objects and not new_objects:
        object_scope = 'CURRENT_STATIC_OLD_NEW_CMAKE_OBJECT_SCAN_NOT_HISTORICAL_OBJECT_HASHES'
        old_objects = {str(path.relative_to(old_folder)):digest(path) for path in old_folder.rglob('*.o')}
        new_objects = {str(path.relative_to(new_folder)):digest(path) for path in new_folder.rglob('*.o') if 'CMakeTmp' not in str(path)}
    
    def normalized_sources(record, folder):
        result = {}
        for item in record.get('compiled_source_closure', []):
            path = Path(item['path']); path = path if path.is_absolute() else ROOT / path
            key = '$PROFILE/' + str(path.relative_to(folder)) if path.is_relative_to(folder) else str(path)
            result[key] = item['sha256']
        return result
    old_sources = normalized_sources(old_record, old_folder)
    new_sources = normalized_sources(new_record, new_folder)
    report = {
        'status': 'PASS' if driver['status'] == 'PASS' and not driver['baseline_input_drift'] and not missing and not undecoded and not truncations and not verified_checkpoint_drift else 'FAIL',
        'scope': 'ACTUAL_SELF_CHILD_EXECVE_READ_OPENS_AND_LD_TRACE_MAP_FRESH_BUILD_NOT_OLD_BUILD_OR_REGISTRATION',
        'codec': args.codec, 'profile': args.profile, 'output_root': str(output_root),
        'driver_report': identity(driver_path), 'trace_files': [identity(path) for path in files],
        'successful_execve_observations': executed, 'executed_unique_file_count': len(execute_unique),
        'executed_kernel_interpreters': kernel_interpreters,
        'successful_read_file_inputs': read_files, 'successful_read_file_count': len(read_files),
        'virtual_files': virtual, 'unavailable_observed_files': sorted(missing),
        'unresolved_trace_lines': undecoded, 'truncated_argv_or_paths': truncations,
        'link_maps': [identity(path) for path in link_maps],
        'temporary_assembler_and_frontend_input_captures': [value for values in captures.values() for value in values],
        'actual_link_launcher_checkpoints': link_launcher_calls,
        'observed_link_LOAD_inputs': [input_identity(path) for path in sorted(map_inputs)],
        'observed_archive_member_contributions': archive_members,
        'baseline_and_checkpoint_input_sha_drift': verified_checkpoint_drift,
        'observed_read_inputs_without_pre_read_sha_checkpoint': unmatched,
        'pre_read_scope_complete': not unmatched,
        'pre_read_scope': 'PRE_EXISTING_EXTERNAL_INPUTS_ONLY_GENERATED_PIPELINE_FILES_RETAINED_AS_SEPARATE_OUTPUTS',
        'old_new_artifact_bytes_equal': driver['old_new_artifact_bytes_equal'],
        'old_new_object_byte_equality_by_name': {'old_count': len(old_objects), 'new_count': len(new_objects), 'equal': old_objects == new_objects,'scope':object_scope},
        'old_new_normalized_declared_source_byte_closures_equal': old_sources == new_sources,
        'old_normalized_source_count': len(old_sources), 'new_normalized_source_count': len(new_sources),
        'association_limit': 'BYTE_EQUAL_NEW_ARTIFACT_CAN_BE_ASSOCIATED_WITH_CURRENT_OLD_ARTIFACT_CONTENTS_DOES_NOT_PROVE_OLD_BUILD_PROCESS_WAS_TRACED',
        'full_N1_granted': False, 'analyzer': identity(Path(__file__)),
    }
    with args.report.open('x') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'executed_unique_file_count', 'successful_read_file_count', 'pre_read_scope_complete', 'old_new_artifact_bytes_equal', 'old_new_object_byte_equality_by_name', 'old_new_normalized_declared_source_byte_closures_equal')}, indent=2))
    print('read_inputs_without_pre_read_sha_checkpoint', len(unmatched))
    if report['status'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
