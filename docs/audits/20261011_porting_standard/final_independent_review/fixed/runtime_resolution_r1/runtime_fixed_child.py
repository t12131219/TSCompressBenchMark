"""Isolated non-codec probes through the current production factory and runtime guard."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def declared_hash_check(root: Path, artifact: Path) -> dict:
    """Independent check of saved bytes; intentionally does not inspect ELF resolution."""
    record_path = artifact.parent / 'build-record.json'
    record = json.loads(record_path.read_text())
    checked, errors = [], []
    for entry in [
        {'path': record['artifact'], 'sha256': record['artifact_sha256']},
        *record['compiled_source_closure'],
        *record['runtime_dependencies'],
    ]:
        path = Path(entry['path'])
        path = path if path.is_absolute() else root / path
        actual = sha(path)
        checked.append({'path': str(path), 'expected_sha256': entry['sha256'], 'actual_sha256': actual})
        if actual != entry['sha256']:
            errors.append(str(path))
    command = json.loads((artifact.parent / 'compile-command.json').read_text())
    canonical = json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    if hashlib.sha256(canonical).hexdigest() != record['compile_commands_sha256']:
        errors.append('compile_commands_sha256')
    return {'status': 'PASS' if not errors else 'FAIL', 'checked': checked, 'errors': errors}


def execution_identity(manifest, root: Path):
    from tscompbench.adapters.factory import adapter_artifacts
    from tscompbench.contracts import CapabilityStatus
    from tscompbench.planning.resolution import resolve_execution

    artifact, supporting = adapter_artifacts(root, manifest)
    compatibility = SimpleNamespace(status=CapabilityStatus.SUPPORTED, reason_code='TOY_FIXTURE', output_descriptor={}, input_descriptor=SimpleNamespace(alignment_bytes=1))
    profile = {
        'threads': 1, 'runner_version': 'toy-runtime-independent-review-v1',
        'allocation_policy': 'TOY', 'cache_policy': 'TOY', 'state_policy': 'TOY',
        'gc_policy': 'TOY', 'jit_policy': 'TOY',
    }
    environment = {'cpu': {'flags': [], 'affinity': []}, 'environment_id': 'toy-runtime-independent-review'}
    resolved = resolve_execution(manifest, SimpleNamespace(parameters={}), compatibility, environment, artifact_path=artifact, supporting_artifact_paths=supporting, profile=profile)
    return {
        'execution_path_hash': resolved.execution_path_hash,
        'artifact_sha256': resolved.artifact_sha256,
        'adapter_id': resolved.adapter_id,
        'supporting_paths': [str(path.relative_to(root)) if path.is_relative_to(root) else str(path) for path in supporting],
    }


def main():
    repository, root, action, profile_name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    sys.path.insert(0, str(repository / 'src'))
    from tscompbench.adapters import factory
    from tscompbench.adapters import runtime_evidence
    from tscompbench.adapters.runtime_evidence import capture_runtime_profile, verified_runtime_dependencies

    artifact = root / 'artifacts/release/libtoy_wrapper.so'
    alternative = root / 'alternative-runtime/libtoy_runtime.so'
    if action == 'capture':
        profile = capture_runtime_profile(root, artifact, capture_driver=Path(__file__).resolve())
        output = root / (profile_name + '.json')
        with output.open('x', encoding='utf-8') as stream:
            json.dump(profile, stream, indent=2, sort_keys=True)
            stream.write('\n')
        print(json.dumps({'status': 'CAPTURED_LOAD_ONLY', 'profile': str(output), 'profile_sha256': sha(output)}))
        return

    if action == 'already_loaded_replacement':
        preloaded = ctypes.CDLL(str(alternative))
        preloaded.toy_runtime_value.restype = ctypes.c_int
        preloaded_value = preloaded.toy_runtime_value()
    else:
        preloaded_value = None
    adapter = {'factory': 'LZ4_FRAME_CTYPES_V1', 'artifact_path': str(artifact.relative_to(root))}
    if profile_name != 'legacy':
        profile_path = root / (profile_name + '.json')
        registered_hash = sha(profile_path)
        if action == 'profile_hash_mismatch':
            registered_hash = '0' * 64
        adapter['runtime_profile'] = {'path': str(profile_path.relative_to(root)), 'sha256': registered_hash}
    manifest = SimpleNamespace(
        key='lz4-frame', algorithm_id='toy:algorithm', source_artifact_id='toy:source',
        document={
            'identity': {'family': 'TOY_NON_CODEC'}, 'adapter': adapter,
            'input': {'alignment_bytes': 1}, 'lifecycle': {'tail_policy': 'TOY'},
            'execution': {'isa': ['SCALAR'], 'required_cpu_flags': [], 'runtime_dispatch': False, 'fallback_policy': 'NONE', 'backends': ['CTYPES'], 'devices': ['CPU']},
        },
    )
    observation = {
        'action': action, 'profile': profile_name,
        'declared_hashes': declared_hash_check(root, artifact),
        'preloaded_value': preloaded_value,
        'loader_environment': {key: os.environ.get(key) for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT')},
        'constructor_calls': 0, 'session_constructor_calls': 0,
        'post_load_guard_calls': 0, 'toy_operation_calls': 0,
    }
    try:
        paths = verified_runtime_dependencies(root, artifact, adapter)
        observation['direct_runtime_guard'] = {'status': 'PASS', 'paths': [str(path) for path in paths]}
    except Exception as error:
        observation['direct_runtime_guard'] = {'status': 'REJECTED', 'error_type': type(error).__name__, 'error': str(error)}

    class ToySession:
        def __init__(self, artifact_path):
            observation['session_constructor_calls'] += 1
            self.library = ctypes.CDLL(str(artifact_path))
            self.library.toy_entry.restype = ctypes.c_int

        def toy_operation(self):
            observation['toy_operation_calls'] += 1
            return self.library.toy_entry()

        def close(self):
            pass

    class ToyAdapter:
        def __init__(self, artifact_path, unused_adapter):
            observation['constructor_calls'] += 1
            self.artifact_path = artifact_path

        def create_session(self, unused_parameters):
            return ToySession(self.artifact_path)

    original_guard = runtime_evidence.verify_loaded_runtime
    original_load = ctypes.CDLL

    def observe_post_guard(*args):
        observation['post_load_guard_calls'] += 1
        return original_guard(*args)

    def observe_runtime_load(filename, *args, **kwargs):
        if action == 'swap_between_guard_and_load' and str(filename) == str(artifact.resolve()):
            observation['replacement_loaded_inside_factory'] = str(alternative)
            observation['replacement_handle'] = True
            original_load(str(alternative))
        return original_load(filename, *args, **kwargs)

    # Mirror the actual lazy adapter design: CDLL occurs in create_session,
    # and the harmless toy operation occurs only after session admission.
    # Real factory/evidence/runtime pre/post checks execute unchanged.
    factory.Lz4FrameAdapter = ToyAdapter
    runtime_evidence.verify_loaded_runtime = observe_post_guard
    ctypes.CDLL = observe_runtime_load
    try:
        value = factory.create_adapter(root, manifest)
        observation['production_factory'] = {'status': 'PASS'}
        observation['artifact_mapped_before_session'] = str(artifact) in {line.split(maxsplit=5)[-1] for line in Path('/proc/self/maps').read_text().splitlines() if 'libtoy_wrapper.so' in line}
        try:
            session = value.create_session({})
            observation['production_session'] = {'status': 'PASS', 'toy_value': session.toy_operation()}
            observation['execution_identity'] = execution_identity(manifest, root)
            session.close()
        except Exception as error:
            observation['production_session'] = {'status': 'REJECTED', 'error_type': type(error).__name__, 'error': str(error)}
    except Exception as error:
        observation['production_factory'] = {'status': 'REJECTED', 'error_type': type(error).__name__, 'error': str(error)}
    observation['actual_toy_mappings'] = sorted({line.split(maxsplit=5)[-1] for line in Path('/proc/self/maps').read_text().splitlines() if 'libtoy_runtime.so' in line or 'libtoy_wrapper.so' in line})
    print(json.dumps(observation, sort_keys=True))


if __name__ == '__main__':
    main()
