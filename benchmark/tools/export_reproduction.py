"""Export selected current evidence and source assets for private local review.

This tool neither runs codecs nor fetches, installs, publishes or relocates old
evidence. Raw arrays and real-source wire artifacts are deliberately omitted.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


SCHEMA = 'tsbench.local-reproduction-export/1'
ROOT = Path(__file__).resolve().parents[2]
RAW_SUFFIXES = {'.csv', '.tsv', '.npy', '.npz', '.parquet', '.arrow'}
BINARY_SUFFIXES = {'.so', '.a', '.o', '.whl', '.dll', '.dylib', '.exe'}
CACHE_PARTS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache'}
RESTORED_PARTS = {'decoded', 'restored', 'recovered', 'decoder-output', 'decode-output', 'restored_outputs'}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode()


def sha(path):
    with Path(path).open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def strings(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def checked_path(root, value):
    """Require a real in-root path; reject traversal and every symlink ancestor."""
    path = Path(value)
    if '..' in path.parts:
        raise ValueError('parent traversal is not allowed: ' + str(path))
    path = path if path.is_absolute() else root / path
    if not path.is_relative_to(root):
        raise ValueError('path is outside asset root: ' + str(path))
    for part in [path, *path.parents]:
        if part == root.parent:
            break
        if part.is_symlink():
            raise ValueError('symlink is not allowed: ' + str(part))
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def synthetic_run(manifest, root):
    """Fail closed: only the two project fixture directories admit saved wire."""
    config = manifest.get('resolved_config', manifest.get('configuration', {}))
    datasets = config.get('datasets', [])
    if not datasets:
        datasets = [case.get('dataset', {}) for case in manifest.get('cases', [])]
    base = Path(config.get('_base_dir', root))
    allowed = [root / 'benchmark/examples/data', root / 'benchmark/experiments/gpu-p4/fixtures']
    if not datasets:
        return False
    for dataset in datasets:
        value = dataset.get('path')
        if not isinstance(value, str) or Path(value).suffix.lower() == '.csv':
            return False
        path = Path(value)
        path = path if path.is_absolute() else base / path
        if not any(path.is_relative_to(directory) for directory in allowed):
            return False
    return True


def collect(root, index_path, include_binaries=False):
    root = Path(root).resolve(strict=True)
    index_path = checked_path(root, index_path)
    index = json.loads(index_path.read_bytes())
    if index.get('schema') != 'tsbench.current-evidence/1':
        raise ValueError('expected the current evidence index, not a history index')
    included, omissions, selected_runs, documents = {}, {}, [], [index]

    def check_index_records(value):
        if isinstance(value, dict):
            for key, path_value in value.items():
                expected = value.get('sha256') if key in {'path', 'source'} else value.get(key + '_sha256')
                if expected and isinstance(path_value, str) and path_value.startswith(
                        ('docs/', 'runs/', 'benchmark/', 'build/', 'adapters/', 'native/', 'registry/')):
                    path = checked_path(root, path_value)
                    if not path.is_file() or sha(path) != expected:
                        raise ValueError('indexed evidence hash mismatch: ' + path_value)
                check_index_records(path_value)
        elif isinstance(value, list):
            for item in value:
                check_index_records(item)

    check_index_records(index)

    def omit(path, reason):
        relative = str(path.relative_to(root))
        omissions[relative] = {'path': relative, 'reason': reason, 'bytes': path.stat().st_size}

    def add(path, group, wire_allowed=False):
        path = checked_path(root, path)
        if path.is_dir():
            for child in sorted(path.rglob('*')):
                if child.is_symlink():
                    raise ValueError('symlink is not allowed: ' + str(child))
                if child.is_file():
                    add(child, group, wire_allowed)
            return
        relative = str(path.relative_to(root))
        if any(part in CACHE_PARTS for part in path.relative_to(root).parts) or path.suffix in {'.pyc', '.pyo'}:
            return
        if group in {'indexed_run', 'indexed_qualification'} and any(part in RESTORED_PARTS for part in path.relative_to(root).parts):
            omit(path, 'independent_decoder_restored_output_not_bundled')
        elif path.suffix.lower() in RAW_SUFFIXES:
            omit(path, 'raw_array_or_table_not_bundled; regenerate synthetic fixtures or acquire external corpus')
        elif path.suffix.lower() == '.tsb' and not wire_allowed:
            omit(path, 'real_or_unclassified_source_wire_not_bundled; original hash evidence retained')
        elif path.suffix.lower() in BINARY_SUFFIXES and not include_binaries:
            omit(path, 'binary_or_wheel_not_requested; rebuild from frozen source')
        else:
            included[relative] = {'path': relative, 'source_path': str(path),
                                  'bytes': path.stat().st_size, 'group': group}

    for name in ('adapters', 'native', 'registry', 'benchmark'):
        add(root / name, 'source_asset' if name in {'adapters', 'native', 'registry'} else 'benchmark_source')
    for name in ('README.md', 'LICENSE', 'TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md'):
        add(root / name, 'documentation')
    # All small narrative/source diagrams; result tables are selected below by index.
    for path in sorted((root / 'docs').rglob('*')):
        if path.is_file() and path.suffix in {'.md', '.svg'} and 'sources' not in path.relative_to(root / 'docs').parts:
            add(path, 'documentation')
    add(index_path, 'current_index')
    for value in strings(index):
        if value.startswith('docs/'):
            path = checked_path(root, value)
            if path.is_file():
                add(path, 'indexed_document')
                if path.suffix == '.json':
                    documents.append(json.loads(path.read_bytes()))
                if path.name in {'summary.json', 'trace.json'}:
                    add(path.parent, 'indexed_analysis')
        elif value.startswith('runs/') and Path(value).suffix:
            path = checked_path(root, value)
            if path.is_file():
                add(path.parent, 'indexed_qualification')
                if path.suffix == '.json':
                    documents.append(json.loads(path.read_bytes()))
    for item in index.get('runs', []):
        path = checked_path(root, item['run'])
        manifest_path = checked_path(root, path / 'manifest.json')
        manifest = json.loads(manifest_path.read_bytes())
        if sha(manifest_path) != item['manifest_sha256'] or sha(path / 'observations.jsonl') != item['observations_sha256']:
            raise ValueError('indexed run hash mismatch: ' + item['run'])
        is_synthetic = synthetic_run(manifest, root)
        add(path, 'indexed_run', wire_allowed=is_synthetic)
        selected_runs.append({'path': item['run'], 'run_id': manifest['run_id'],
                              'wire_policy': 'project_synthetic_only' if is_synthetic else 'omitted_real_or_unclassified'})
        documents.append(manifest)
    # Installed-wheel verification supersedes the earlier packaging smoke check.
    # Retain both evidence documents without presenting an old wheel as current.
    current_package = index.get('package_installed_verification') or index.get('package_verification')
    current_wheel = None
    if isinstance(current_package, dict) and isinstance(current_package.get('path'), str):
        package_document = json.loads(checked_path(root, current_package['path']).read_bytes())
        if isinstance(package_document.get('wheel'), str):
            current_wheel = checked_path(root, package_document['wheel'])
            expected = package_document.get('wheel_sha256')
            if expected and sha(current_wheel) != expected:
                raise ValueError('current indexed wheel hash mismatch: ' + str(current_wheel))
    # Keep only actual referenced build records/libraries, never entire build trees.
    build_files = set()
    for document in documents:
        for value in strings(document):
            if value.startswith(str(root / 'build') + '/') or value.startswith('build/'):
                path = Path(value)
                if path.name == 'build.json' or path.suffix in {'.so', '.whl'}:
                    path = checked_path(root, path)
                    if path.suffix == '.whl' and current_wheel is not None and path != current_wheel:
                        omit(path, 'superseded_package_wheel_not_selected; original verification retained')
                    else:
                        build_files.add(path)
    for path in sorted(build_files):
        add(path, 'referenced_build')
    restrictions = []
    for path in sorted((root / 'registry/sources').glob('*.artifact.json')):
        source = json.loads(path.read_bytes())
        restrictions.append({'source_record': str(path.relative_to(root)), 'license': source.get('license', {})})
    return {'schema': SCHEMA, 'scope': 'private local source/evidence archive; not publicly redistributable by inference',
            'publication': {'published': False, 'public_redistribution_claimed': False,
                            'policy': 'Preserve original per-asset license restrictions. This export grants no new permission.'},
            'asset_root_at_export': str(root), 'index': str(index_path.relative_to(root)),
            'index_sha256': sha(index_path), 'include_binaries': include_binaries,
            'selected_runs': selected_runs, 'files': [included[key] for key in sorted(included)],
            'omissions': [omissions[key] for key in sorted(omissions)], 'asset_license_records': restrictions,
            'relocation_policy': 'Original evidence bytes and absolute paths are unchanged. Rebuild and start new runs; do not resume relocated evidence.',
            'runtime_policy': 'System/compiler/CUDA/runtime files are not bundled; original build records declare paths and hashes.'}


def summarize(plan):
    groups = Counter()
    for item in plan['files']:
        groups[item['group']] += item['bytes']
    return {'schema': SCHEMA, 'scope': plan['scope'], 'selected_runs': len(plan['selected_runs']),
            'files': len(plan['files']), 'uncompressed_file_bytes': sum(groups.values()),
            'group_bytes': dict(groups), 'omitted_files': len(plan['omissions']),
            'omitted_bytes': sum(item['bytes'] for item in plan['omissions']),
            'include_binaries': plan['include_binaries'], 'index_sha256': plan['index_sha256']}


def export(plan, output):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError('refusing to overwrite export: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    root = Path(plan['asset_root_at_export'])
    final = json.loads(json_bytes(plan))
    final['created_at_utc'] = datetime.now(timezone.utc).isoformat()
    final['exporter_sha256'] = sha(__file__)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + output.name + '.', dir=output.parent)
    os.close(descriptor)
    try:
        with open(temporary, 'wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed, tarfile.open(fileobj=compressed, mode='w|') as archive:
            for item in final['files']:
                path = checked_path(root, item['path'])
                before = path.stat()
                digest = hashlib.sha256()

                class Reader:
                    def read(self, size=-1):
                        value = stream.read(size)
                        digest.update(value)
                        return value

                info = tarfile.TarInfo('tsbench-local/' + item['path'])
                info.size = before.st_size
                info.mode = 0o755 if before.st_mode & 0o111 else 0o644
                with path.open('rb') as stream:
                    archive.addfile(info, Reader())
                after = path.stat()
                if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino) or before.st_size != item['bytes']:
                    raise RuntimeError('source changed during export: ' + str(path))
                item['sha256'] = 'sha256:' + digest.hexdigest()
                if path.suffix == '.tsb' and len(path.stem) == 64 and all(c in '0123456789abcdef' for c in path.stem) and item['sha256'] != 'sha256:' + path.stem:
                    raise ValueError('content-addressed artifact differs: ' + str(path))
            for item in final['omissions']:
                path = checked_path(root, item['path'])
                item['sha256'] = sha(path)
                if path.suffix == '.tsb' and len(path.stem) == 64 and all(c in '0123456789abcdef' for c in path.stem) and item['sha256'] != 'sha256:' + path.stem:
                    raise ValueError('omitted artifact differs from original hash: ' + str(path))
            if sha(root / final['index']) != final['index_sha256']:
                raise RuntimeError('current index changed during export')
            payload = json_bytes(final)
            info = tarfile.TarInfo('tsbench-local/EXPORT_MANIFEST.json')
            info.size = len(payload)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(payload))
        # Link publication fails atomically if another writer claimed output.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {**summarize(final), 'archive': str(output), 'archive_bytes': output.stat().st_size,
            'archive_sha256': sha(output)}


def verify(path):
    """Verify member safety and every exported byte without extracting anything."""
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive members')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not member.isfile() or not parts or parts[0] != 'tsbench-local' or '..' in parts or member.name.startswith('/') or str(PurePosixPath(member.name)) != member.name:
                raise ValueError('unsafe archive member: ' + member.name)
        manifest_name = 'tsbench-local/EXPORT_MANIFEST.json'
        manifest = json.load(archive.extractfile(manifest_name))
        if manifest.get('schema') != SCHEMA or manifest.get('publication', {}).get('public_redistribution_claimed') is not False:
            raise ValueError('unknown export schema or publication claim')
        expected = {manifest_name}
        for item in manifest['files']:
            relative = PurePosixPath(item['path'])
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe ledger path')
            name = 'tsbench-local/' + item['path']
            if name in expected:
                raise ValueError('duplicate ledger path')
            expected.add(name)
            member = archive.getmember(name)
            with archive.extractfile(member) as stream:
                digest = 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()
            if member.size != item['bytes'] or digest != item['sha256']:
                raise ValueError('archive content differs from ledger: ' + name)
        if set(names) != expected:
            raise ValueError('unaccounted archive member')
    return {'verified': True, 'archive_sha256': sha(path), **summarize(manifest)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asset-root', type=Path, default=ROOT)
    parser.add_argument('--index', type=Path, default=Path('docs/current_evidence.json'))
    parser.add_argument('--include-binaries', action='store_true', help='include only referenced native libraries/wheel; no system runtime or build objects')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--plan', action='store_true', help='read-only size and selection summary')
    action.add_argument('--output', type=Path, help='new private tar.gz path')
    action.add_argument('--verify', type=Path, help='read-only archive verification; does not extract')
    args = parser.parse_args(argv)
    if args.verify:
        result = verify(args.verify)
    else:
        if args.output and args.output.exists():
            parser.error('refusing to overwrite export: ' + str(args.output))
        plan = collect(args.asset_root, args.index, args.include_binaries)
        result = summarize(plan) if args.plan else export(plan, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return result


if __name__ == '__main__':
    main()
