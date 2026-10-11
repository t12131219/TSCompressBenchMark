"""Only read and hash saved records/depfiles; never build or execute test binaries."""

import hashlib
import json
from pathlib import Path
import shlex

ROOT = Path('/home/fzg/PycharmProjects/TSDataCompressBenchMark')
OUTPUT = Path(__file__).resolve().parent / '62-record-review.json'
QUALIFICATION = ROOT / 'docs/audits/20261011_port_standard_v30/general_native_qualification_v2/qualification.json'
FIELDS = ('compiled_source_closure', 'compiler_dependency_files', 'objects', 'toolchain_files', 'toolchain_programs', 'runtime_dependencies', 'runtime_dependency_listing', 'build_driver_files')
cache = {}


def path(value):
    value = Path(value)
    return value if value.is_absolute() else ROOT / value


def sha(value):
    value = value.resolve()
    if value not in cache:
        if not value.is_file():
            cache[value] = None
        else:
            with value.open('rb') as stream:
                cache[value] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return cache[value]


def main():
    report = json.loads(QUALIFICATION.read_text())
    failures, records = [], []
    counts = {field: 0 for field in FIELDS}
    native_tests = 0
    for result in report['results']:
        try:
            record_path = path(result['build_record']['path'])
            before = record_path.read_bytes()
            record = json.loads(before)
            tag = record['algorithm'] + '/' + record['profile']
            if sha(record_path) != result['build_record']['sha256']:
                raise ValueError('qualification build-record drift')
            if sha(path(record['artifact'])) != record['artifact_sha256']:
                raise ValueError('artifact drift')
            command_path = record_path.parent / 'compile-command.json'
            command = json.loads(command_path.read_text())
            canonical = json.dumps(command, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            if hashlib.sha256(canonical).hexdigest() != record['compile_commands_sha256']:
                raise ValueError('compile command drift')
            for field in FIELDS:
                entries = record.get(field)
                if not isinstance(entries, list) or not entries:
                    raise ValueError(field + ' absent/empty')
                counts[field] += len(entries)
                for entry in entries:
                    if sha(path(entry['path'])) != entry['sha256']:
                        raise ValueError(field + ' drift: ' + entry['path'])
                if entries != command.get(field):
                    raise ValueError('record versus command closure drift: ' + field)
            declared = {path(entry['path']).resolve() for entry in record['compiled_source_closure']}
            dependencies = record['compiler_dependency_files']
            object_paths = {path(entry['path']).resolve() for entry in record['objects']}
            dependency_paths = {path(entry['path']).resolve() for entry in dependencies}
            translation_units = command['translation_unit_commands']
            if len(record['objects']) != len(translation_units):
                raise ValueError('per-TU object count differs')
            for argv in translation_units:
                if not all(flag in argv for flag in ('-c', '-MD', '-MF', '-o')):
                    raise ValueError('per-TU dependency flags absent')
                dependency_file = path(argv[argv.index('-MF') + 1])
                object_file = path(argv[argv.index('-o') + 1])
                source = path(argv[argv.index('-o') - 1]).resolve()
                if object_file.resolve() not in object_paths or dependency_file.resolve() not in dependency_paths:
                    raise ValueError('actual per-TU object/.d absent')
                text = dependency_file.read_text().replace('\\\n', ' ')
                if source not in {path(value).resolve() for value in shlex.split(text.split(':', 1)[1])}:
                    raise ValueError('actual TU absent from own .d')
            actual = set()
            for entry in dependencies:
                dependency_file = path(entry['path'])
                directory = record_path.parent / 'vendor-build' if 'vendor-build' in dependency_file.parts else ROOT
                text = dependency_file.read_text().replace('\\\n', ' ')
                actual.update((directory / value).resolve() for value in shlex.split(text.split(':', 1)[1]))
            if declared != actual:
                raise ValueError('retained .d union differs from recorded closure')
            for test in result['native_tests']:
                native_tests += 1
                for field in ('source', 'executable'):
                    entry = test[field]
                    if sha(path(entry['path'])) != entry['sha256']:
                        raise ValueError('native test ' + field + ' drift')
                if test['compile']['returncode'] or test['run']['returncode']:
                    raise ValueError('stored native test execution failure')
            if before != record_path.read_bytes():
                raise ValueError('build record changed during read')
            records.append({'algorithm_profile': tag, 'translation_unit_count': len(translation_units), 'dependency_file_count': len(dependencies), 'compiler_closure_count': len(declared), 'native_test_count': len(result['native_tests'])})
        except Exception as error:
            failures.append({'algorithm': result.get('algorithm'), 'profile': result.get('profile'), 'error': str(error)})
    receipt = {
        'status': 'PASS_CURRENT_SAVED_RECORDS' if not failures and len(records) == 62 else 'FAIL',
        'scope': 'READ_ONLY_HASH_AND_RETAINED_DEPFILE_UNIVERSE_REVIEW; NO_NEW_BUILD_TEST_CODEC_OR_LDD_EXECUTION',
        'qualification': {'path': str(QUALIFICATION), 'sha256': sha(QUALIFICATION)},
        'review_driver_sha256': sha(Path(__file__)),
        'record_count': len(records),
        'closure_field_entry_counts': counts,
        'unique_hashed_paths': len(cache),
        'native_test_evidence_count': native_tests,
        'failures': failures,
        'records': records,
        'limits': ['Implicit static startup/runtime archives are not all pinned.', 'Toolchain discovery is not exec tracing.', 'The real loader resolution policy is a separate demonstrated gap.', 'All N0-N5, source/full parity and present performance are not granted by this read-only review.'],
    }
    with OUTPUT.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({key: receipt[key] for key in ('status', 'record_count', 'closure_field_entry_counts', 'unique_hashed_paths', 'native_test_evidence_count', 'failures')}, indent=2))


if __name__ == '__main__':
    main()
