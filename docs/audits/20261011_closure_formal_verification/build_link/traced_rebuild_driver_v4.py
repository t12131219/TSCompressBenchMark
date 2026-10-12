"""Audit-only diagnostic wrapper: new isolated output, no source/registry edits."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[4]
SELF = Path(__file__).resolve()


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def entry(path: Path) -> dict:
    resolved = path.resolve()
    return {'path': str(resolved), 'sha256': digest(resolved), 'size_bytes': resolved.stat().st_size}


def snapshot(paths: list[Path]) -> list[dict]:
    return [entry(path) for path in sorted(set(paths)) if path.is_file()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('codec')
    parser.add_argument('--profile', choices=['release', 'sanitizer', 'debug'], required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--discovered-inputs', type=Path)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    if not output_root.is_relative_to(ROOT / 'build/closure-formal-verification-20261011'):
        raise SystemExit('refusing output outside new closure-formal build root')
    if (output_root / args.codec.replace('-', '_') / args.profile).exists():
        raise SystemExit('refusing existing build profile')
    manifest = json.loads((ROOT / 'registry/codecs' / (args.codec + '.json')).read_text())
    prior_artifact = ROOT / manifest['adapter']['artifact_path']
    prior_folder = prior_artifact.parent.parent / args.profile
    prior_record = json.loads((prior_folder / 'build-record.json').read_text())
    candidates = [SELF, ROOT / 'tools/build_codec.py', ROOT / 'tools/build_completed_rewrite.py',
                  ROOT / 'adapters/simdcomp/build_native.py', ROOT / 'registry/algorithm_scope.json',
                  ROOT / 'registry/codecs' / (args.codec + '.json'), prior_folder / 'build-record.json',
                  ROOT / prior_record['artifact']]
    for field in ('source_files', 'binding_sources', 'compiled_source_closure', 'toolchain_files',
                  'toolchain_programs', 'runtime_dependencies', 'pinned_native_dependencies',
                  'patches', 'build_driver_files'):
        for value in prior_record.get(field, []):
            path = Path(value['path'])
            candidates.append(path if path.is_absolute() else ROOT / path)
    inventory = json.loads((SELF.parent / 'inventory_v1.json').read_text())
    candidates += [Path(item['resolved_file']['path']) if Path(item['resolved_file']['path']).is_absolute() else ROOT / item['resolved_file']['path'] for item in inventory['tool_availability'] if item['available']]
    candidates += [Path(item['path']) if Path(item['path']).is_absolute() else ROOT / item['path'] for item in inventory['current_readable_CRT_static_archive_script_candidates']]
    discovery = None
    if args.discovered_inputs:
        discovery = json.loads(args.discovered_inputs.read_text())
        candidates += [Path(item['path']) for item in discovery['successful_read_file_inputs'] if not item['generated_in_audit_output']]
    audit_dir = output_root / 'audit' / args.codec / args.profile
    audit_dir.mkdir(parents=True, exist_ok=False)
    wrapper_directory = audit_dir / 'wrapper-bin'
    wrapper_directory.mkdir()
    capture_directory = audit_dir / 'temporary-capture'
    capture_directory.mkdir()
    assembler_wrapper = wrapper_directory / 'as'
    wrapper_text = "#!" + sys.executable + "\n" + r'''import hashlib,json,os,sys
from pathlib import Path
capture=Path(__file__).resolve().parents[1]/'temporary-capture'
for index, value in enumerate(sys.argv[1:]):
    path=Path(value)
    if path.is_file() and path.suffix in {'.s','.S'}:
        data=path.read_bytes()
        copied=capture/('as-%d-input-%d.s' % (os.getpid(),index))
        copied.write_bytes(data)
        entry={'original_path':str(path.resolve()),'captured_file_path':str(copied),
               'sha256':hashlib.sha256(data).hexdigest(),'size_bytes':len(data),
               'capture_scope':'IMMEDIATELY_BEFORE_REAL_AS_EXECVE_SAME_ARGV'}
        (capture/('as-%d-input-%d.json' % (os.getpid(),index))).write_text(json.dumps(entry))
os.execv('/usr/bin/as',['/usr/bin/as',*sys.argv[1:]])
'''
    assembler_wrapper.write_text(wrapper_text)
    assembler_wrapper.chmod(0o755)
    # Separate frontend wrappers retain configure-time CMake scratch TUs
    # before GCC consumes/deletes them; they exec the same real frontend argv.
    for name in ('cc1', 'cc1plus'):
        tool_wrapper = wrapper_directory / name
        text = wrapper_text.replace("{'.s','.S'}", "{'.c','.cc','.cpp','.i','.ii','.s','.S'}")
        text = text.replace("as-%d-input-%d.s", name + "-%d-input-%d.bin")
        text = text.replace("as-%d-input-%d.json", name + "-%d-input-%d.json")
        text = text.replace('IMMEDIATELY_BEFORE_REAL_AS_EXECVE_SAME_ARGV',
                            'IMMEDIATELY_BEFORE_REAL_FRONTEND_EXECVE_SAME_ARGV')
        text = text.replace("'/usr/bin/as'", repr('/usr/lib/gcc/x86_64-linux-gnu/11/' + name))
        tool_wrapper.write_text(text)
        tool_wrapper.chmod(0o755)
        candidates.append(tool_wrapper)
    link_launcher = wrapper_directory / 'link-launcher'
    link_text = "#!" + sys.executable + "\n" + r'''import hashlib,json,os,sys,time
from pathlib import Path
capture=Path(__file__).resolve().parents[1]/'temporary-capture'
command=sys.argv[1:]
inputs=[]
for value in command[1:]:
    path=Path(value)
    if path.is_file() and path.suffix in {'.o','.a','.so'}:
        data=path.read_bytes()
        inputs.append({'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest()})
actual=list(command)
if '-o' in command and 'ar' not in Path(command[0]).name:
    target=Path(command[command.index('-o')+1]).resolve()
    actual += ['-Wl,-t,-t,-Map,'+str(target)+'.linker-observation.map']
(capture/('link-%d.json' % os.getpid())).write_text(json.dumps({
    'kind':'LINK_OR_ARCHIVE','actual_argv':actual,'epoch_before_exec':time.time(),
    'pre_invocation_inputs':inputs,'cwd':os.getcwd()}))
os.execvp(actual[0],actual)
'''
    link_launcher.write_text(link_text)
    link_launcher.chmod(0o755)
    ld_wrapper = wrapper_directory / 'ld'
    ld_text = '#!' + sys.executable + '\n' + r'''import hashlib,json,os,sys,time
from pathlib import Path
capture=Path(__file__).resolve().parents[1]/'temporary-capture'
inputs=[]
for value in sys.argv[1:]:
    path=Path(value)
    if path.is_file():
        data=path.read_bytes()
        inputs.append({'path':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest()})
actual=['/usr/bin/ld',*sys.argv[1:],'-t','-t','-Map='+str(capture/('ld-%d.map'%os.getpid()))]
(capture/('link-ld-%d.json'%os.getpid())).write_text(json.dumps({'kind':'ACTUAL_LD','cwd':os.getcwd(),
 'actual_argv':actual,'epoch_before_exec':time.time(),'pre_invocation_inputs':inputs}))
os.execv(actual[0],actual)
'''
    ld_wrapper.write_text(ld_text)
    ld_wrapper.chmod(0o755)
    helper_source = SELF.parent / 'preserve_build_reads_v1.c'
    helper_library = audit_dir / 'preserve_build_reads.so'
    read_capture = audit_dir / 'read-capture'
    read_capture.mkdir()
    candidates += [assembler_wrapper, link_launcher, ld_wrapper, helper_source, SELF.parent / 'inventory_v1.json']
    if args.discovered_inputs:
        candidates.append(args.discovered_inputs)
    baseline_before = snapshot(candidates)
    started = time.monotonic()
    invocations = []
    original_environment = {key: os.environ.get(key) for key in ('PATH','CC','CXX','LD_LIBRARY_PATH','LD_PRELOAD','LD_AUDIT')}
    if original_environment['LD_PRELOAD'] or original_environment['LD_AUDIT']:
        raise SystemExit('refusing inherited preload/audit instrumentation')
    helper_command = ['/usr/bin/cc','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',str(helper_source),
                      '-o',str(helper_library),'-ldl','-B'+str(wrapper_directory)+'/']
    compiled_helper = subprocess.run(helper_command,capture_output=True,text=True)
    invocations.append({'kind':'AUDIT_READ_PRESERVATION_HELPER_BUILD','actual_argv':helper_command,
                        'returncode':compiled_helper.returncode,'pre_invocation_inputs':snapshot([helper_source]),
                        'output':compiled_helper.stdout+compiled_helper.stderr})
    if compiled_helper.returncode:
        raise RuntimeError(compiled_helper.stderr)
    os.environ['LD_PRELOAD'] = str(helper_library)
    os.environ['TSBENCH_AUDIT_INPUT_ROOT'] = str(output_root) + '/'
    os.environ['TSBENCH_AUDIT_CAPTURE_DIR'] = str(read_capture)
    sys.path.insert(0, str(ROOT / 'tools'))
    recipe = runpy.run_path(str(ROOT / 'tools/build_codec.py'))
    globals_ = recipe['_build'].__globals__
    original = globals_['_run']

    def observed(command: list[str]) -> str:
        actual = list(command)
        kind = 'RECIPE_QUERY_OR_FILE_PREPARATION'
        before = []
        if command[0] == 'cmake' and '-S' in command:
            kind = 'VENDOR_CMAKE_CONFIGURE_WITH_AUDIT_ONLY_WRAPPERS'
            for index,value in enumerate(actual):
                if value.startswith(('-DCMAKE_C_FLAGS=','-DCMAKE_CXX_FLAGS=')):
                    actual[index] = value + ' -B' + str(wrapper_directory) + '/'
        elif '-c' in command:
            kind = 'COMPILATION'
            actual += ['-B' + str(wrapper_directory) + '/']
            before = snapshot([Path(item) for item in command if Path(item).suffix in {'.c', '.cc', '.cpp'}])
        elif '-shared' in command:
            kind = 'LINK_WITH_DIAGNOSTIC_TRACE_AND_MAP'
            target = Path(command[command.index('-o') + 1])
            actual += ['-Wl,-t,-t,-Map,' + str(target.parent / 'linker-observation.map')]
            before = snapshot([Path(item) for item in command if Path(item).suffix in {'.o', '.a', '.so'}])
        if discovery and kind == 'COMPILATION':
            previous_root = Path(discovery['output_root'])
            generated = []
            for item in discovery['successful_read_file_inputs']:
                path = Path(item['path'])
                if path.is_relative_to(previous_root):
                    generated.append(output_root / path.relative_to(previous_root))
            before += snapshot(generated)
        begin = time.monotonic()
        epoch_begin = time.time()
        try:
            if actual[0] == 'ldd':
                saved = os.environ.pop('LD_PRELOAD')
                try: result = original(actual)
                finally: os.environ['LD_PRELOAD'] = saved
            else: result = original(actual)
            invocations.append({'kind': kind, 'planned_recipe_argv': command, 'actual_argv': actual,
                                'returncode': 0, 'elapsed_seconds': time.monotonic() - begin,
                                'epoch_begin': epoch_begin, 'epoch_end': time.time(),
                                'pre_invocation_inputs': before, 'output': result})
            return result
        except Exception as error:
            invocations.append({'kind': kind, 'planned_recipe_argv': command, 'actual_argv': actual,
                                'error': str(error), 'elapsed_seconds': time.monotonic() - begin,
                                'pre_invocation_inputs': before})
            raise

    globals_['_run'] = observed
    status, error, record = 'PASS', None, None
    try:
        factory = manifest['adapter']['factory']
        if factory == 'COMPLETED_REWRITE_CTYPES_V1':
            import build_completed_rewrite
            real_run = subprocess.run
            def traced_run(command, *positional, **keywords):
                actual = list(command) if isinstance(command, (list, tuple)) else command
                kind = 'SPECIAL_RECIPE_SUBPROCESS'
                if isinstance(actual, list) and actual[0] == 'cmake' and '-S' in actual:
                    kind = 'CMAKE_CONFIGURE_WITH_AUDIT_ONLY_LAUNCHERS'
                    for index, value in enumerate(actual):
                        if value.startswith(('-DCMAKE_C_FLAGS=', '-DCMAKE_CXX_FLAGS=')):
                            actual[index] = value + ' -B' + str(wrapper_directory) + '/'
                    source_recipe = Path(actual[actual.index('-S') + 1]) / 'CMakeLists.txt'
                    with source_recipe.open('a') as stream:
                        stream.write('\nset_property(GLOBAL PROPERTY RULE_LAUNCH_LINK "' + str(link_launcher) + '")\n')
                begin = time.time()
                if isinstance(actual,list) and actual[0] == 'ldd':
                    keywords['env'] = {key:value for key,value in os.environ.items() if key != 'LD_PRELOAD'}
                result = real_run(actual, *positional, **keywords)
                invocations.append({'kind':kind,'planned_recipe_argv':command,'actual_argv':actual,
                                    'returncode':result.returncode,'epoch_begin':begin,'epoch_end':time.time(),
                                    'pre_invocation_inputs':[]})
                return result
            subprocess.run = traced_run
            try:
                record = build_completed_rewrite.build(args.codec,args.profile,output_root=output_root)
            finally:
                subprocess.run = real_run
        elif factory == 'SIMDCOMP_CTYPES_V1':
            native = runpy.run_path(str(ROOT / 'adapters/simdcomp/build_native.py'))
            native_globals = native['build'].__globals__
            class OutputRoutedRoot(type(ROOT)):
                def __truediv__(self, other):
                    if other == 'build/adapters/simdcomp_u32':
                        return output_root / 'simdcomp_u32'
                    return super().__truediv__(other)
            native_globals['ROOT'] = OutputRoutedRoot(str(ROOT))
            real_run = subprocess.run
            def traced_run(command,*positional,**keywords):
                actual = list(command)
                before = []
                kind = 'SPECIAL_RECIPE_SUBPROCESS'
                if '-c' in actual:
                    kind = 'COMPILATION'
                    before = snapshot([Path(item) for item in actual if Path(item).suffix in {'.c','.cc','.cpp'}])
                    actual += ['-B'+str(wrapper_directory)+'/']
                elif '-shared' in actual:
                    kind = 'LINK_WITH_DIAGNOSTIC_TRACE_AND_MAP'
                    before = snapshot([Path(item) for item in actual if Path(item).suffix in {'.o','.a','.so'}])
                    target = Path(actual[actual.index('-o')+1])
                    actual += ['-Wl,-t,-t,-Map,'+str(target.parent/'linker-observation.map')]
                begin=time.time()
                if actual[0] == 'ldd':
                    keywords['env']={key:value for key,value in os.environ.items() if key != 'LD_PRELOAD'}
                result=real_run(actual,*positional,**keywords)
                invocations.append({'kind':kind,'planned_recipe_argv':command,'actual_argv':actual,
                                    'returncode':result.returncode,'epoch_begin':begin,'epoch_end':time.time(),
                                    'pre_invocation_inputs':before})
                return result
            subprocess.run = traced_run
            try:
                record = native['build'](args.profile)
            finally:
                subprocess.run = real_run
        else:
            record = recipe['_build'](args.codec, args.profile, output_root=output_root)
    except Exception as caught:
        status, error = 'FAIL', str(caught)
    after = snapshot(candidates)
    changed = [item['path'] for item in baseline_before if next((x['sha256'] for x in after if x['path'] == item['path']), None) != item['sha256']]
    report = {'status': status, 'error': error, 'codec': args.codec, 'profile': args.profile,
              'scope': 'FRESH_AUDIT_ONLY_REBUILD_NOT_CURRENT_REGISTRATION',
              'elapsed_seconds': time.monotonic() - started, 'output_root': str(output_root),
              'diagnostic_wrapper': entry(SELF), 'baseline_inputs_before': baseline_before,
              'baseline_inputs_after': after, 'baseline_input_drift': changed,
              'invocations': invocations, 'new_recipe_record': record,
              'saved_recipe_argv_vs_actual': 'ACTUAL_COMPILE_ADDS_B_FOR_PRE_AS_TEMP_CAPTURE_AND_LINK_ADDS_t_t_MAP_DIAGNOSTICS_SEE_INVOCATIONS',
              'old_artifact': entry(ROOT / prior_record['artifact']),
              'new_artifact': entry(ROOT / record['artifact']) if record else None,
              'old_new_artifact_bytes_equal': digest(ROOT / prior_record['artifact']) == digest(ROOT / record['artifact']) if record else None,
              'full_N1_granted': False,
              'environment':original_environment,
              'audit_instrumentation_environment': {'LD_PRELOAD':str(helper_library),
                  'TSBENCH_AUDIT_INPUT_ROOT':str(output_root)+'/','TSBENCH_AUDIT_CAPTURE_DIR':str(read_capture)},
              'audit_read_preservation_helper':entry(helper_library),
              'runtime_listing_scope':'LDD_EXECUTED_WITHOUT_AUDIT_LD_PRELOAD'}}
    with (audit_dir / 'driver-report.json').open('x') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('status', 'codec', 'profile', 'elapsed_seconds', 'old_new_artifact_bytes_equal', 'baseline_input_drift', 'error')}), flush=True)
    if status != 'PASS' or changed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
