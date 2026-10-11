"""Non-codec demonstration of recorded runtime hashes versus ELF resolution."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

REPOSITORY = Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
ROOT = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def entry(path):
    resolved = path.resolve()
    return {'path': str(resolved.relative_to(ROOT)) if resolved.is_relative_to(ROOT) else str(resolved), 'sha256': digest(resolved)}


def write(path, content):
    with path.open('x', encoding='utf-8') as stream:
        stream.write(content)


def main():
    good, alternative = ROOT / 'recorded-runtime', ROOT / 'alternative-runtime'
    folder = ROOT / 'artifacts/release'
    for directory in (good, alternative, folder):
        directory.mkdir(parents=True, exist_ok=False)
    sources = {
        ROOT / 'recorded.c': 'int toy_runtime_value(void) { return 11; }\n',
        ROOT / 'alternative.c': 'int toy_runtime_value(void) { return 22; }\n',
        ROOT / 'wrapper.c': 'extern int toy_runtime_value(void);\nint toy_entry(void) { return toy_runtime_value(); }\n',
    }
    for path, content in sources.items():
        write(path, content)
    library = folder / 'libtoy_wrapper.so'
    commands = [
        ['cc', '-shared', '-fPIC', '-Wl,-soname,libtoy_runtime.so', str(ROOT / 'recorded.c'), '-o', str(good / 'libtoy_runtime.so')],
        ['cc', '-shared', '-fPIC', '-Wl,-soname,libtoy_runtime.so', str(ROOT / 'alternative.c'), '-o', str(alternative / 'libtoy_runtime.so')],
        ['cc', '-shared', '-fPIC', str(ROOT / 'wrapper.c'), '-L', str(good), '-ltoy_runtime', '-Wl,-rpath,' + str(good), '-o', str(library)],
    ]
    logs = []
    for command in commands:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        logs.append({'command': command, 'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
    baseline_env = {**os.environ, 'LD_LIBRARY_PATH': str(good)}
    baseline_env.pop('LD_PRELOAD', None)
    listing = subprocess.run(['ldd', str(library)], check=True, capture_output=True, text=True, env=baseline_env).stdout
    runtime = {Path(value).resolve() for value in re.findall(r'(?:=>\s+)?(/\S+)\s+\(', listing)}
    command_document = {'schema_version': 'tscb.compile-command.v1', 'profile': 'release', 'command': commands[-1]}
    canonical = json.dumps(command_document, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    write(folder / 'compile-command.json', canonical.decode() + '\n')
    record = {
        'schema_version': 'tscb.build-artifact.v1',
        'algorithm': 'toy-native',
        'profile': 'release',
        'artifact': str(library.relative_to(ROOT)),
        'artifact_sha256': digest(library),
        'compile_commands_sha256': hashlib.sha256(canonical).hexdigest(),
        'compiled_source_closure': [entry(ROOT / 'recorded.c'), entry(ROOT / 'wrapper.c')],
        'runtime_dependencies': [entry(path) for path in sorted(runtime)],
    }
    write(folder / 'build-record.json', json.dumps(record, indent=2) + '\n')
    child = ROOT / 'check_load.py'
    write(child, '''import ctypes, hashlib, importlib.util, json, os, re, subprocess, sys
from pathlib import Path
repository, root = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repository / "src"))
spec = importlib.util.spec_from_file_location("isolated_build_evidence", repository / "src/tscompbench/adapters/build_evidence.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
artifact = root / "artifacts/release/libtoy_wrapper.so"
dependencies = module.verified_build_dependencies(root, artifact, "toy-native", {"factory": "TOY_NATIVE_CTYPES_V1"})
library = ctypes.CDLL(str(artifact))
library.toy_entry.restype = ctypes.c_int
value = library.toy_entry()
mapped = sorted({line.split()[-1] for line in Path("/proc/self/maps").read_text().splitlines() if "libtoy_runtime.so" in line})
listing = subprocess.run(["ldd", str(artifact)], check=True, capture_output=True, text=True).stdout
print(json.dumps({"declared_dependency_verification": "PASS", "verified_path_count": len(dependencies), "LD_LIBRARY_PATH": os.environ["LD_LIBRARY_PATH"], "toy_value": value, "actual_mapped_runtime": mapped, "current_ldd": listing}))
''')
    observations = []
    inputs_before = {str(path.relative_to(ROOT)): digest(path) for path in (library, folder / 'build-record.json', folder / 'compile-command.json', good / 'libtoy_runtime.so')}
    for selected in (good, alternative):
        environment = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'LD_LIBRARY_PATH': str(selected)}
        environment.pop('LD_PRELOAD', None)
        output = subprocess.run([sys.executable, str(child), str(REPOSITORY), str(ROOT)], check=True, capture_output=True, text=True, env=environment)
        observations.append(json.loads(output.stdout))
    inputs_after = {str(path.relative_to(ROOT)): digest(path) for path in (library, folder / 'build-record.json', folder / 'compile-command.json', good / 'libtoy_runtime.so')}
    demonstrated = inputs_before == inputs_after and [row['toy_value'] for row in observations] == [11, 22] and all(row['declared_dependency_verification'] == 'PASS' for row in observations)
    result = {
        'status': 'DEMONSTRATED' if demonstrated else 'NOT_DEMONSTRATED',
        'scope': 'THREE_NON_CODEC_TOY_DSOS_AND_DIRECT_EXISTING_HASH_VERIFIER; NO_CODEC_OR_BENCHMARK_EXECUTION',
        'verifier_source': {'path': str(REPOSITORY / 'src/tscompbench/adapters/build_evidence.py'), 'sha256': digest(REPOSITORY / 'src/tscompbench/adapters/build_evidence.py')},
        'compile_commands': logs,
        'recorded_ldd': listing,
        'observations': observations,
        'declared_inputs_before': inputs_before,
        'declared_inputs_after': inputs_after,
        'declared_input_bytes_unchanged': inputs_before == inputs_after,
        'script_sha256': digest(Path(__file__)),
        'child_script_sha256': digest(child),
    }
    write(ROOT / 'result.json', json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'observations': observations, 'result': str(ROOT / 'result.json')}, indent=2))
    if not demonstrated:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
