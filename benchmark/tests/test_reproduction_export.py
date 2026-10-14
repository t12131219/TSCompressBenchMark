"""Small private-export fixtures; no native build, CUDA or benchmark timing."""
import importlib.util
import io
import json
from pathlib import Path
import tarfile

import pytest


TOOL = Path(__file__).resolve().parents[1] / 'tools/export_reproduction.py'
SPEC = importlib.util.spec_from_file_location('private_export', TOOL)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def put(root, name, value=b'example'):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else module.json_bytes(value))
    return path


def fixture(root):
    for folder in ('adapters/demo', 'native', 'registry/codecs', 'benchmark/src', 'docs'):
        put(root, folder + '/source.txt')
    for name in ('README.md', 'LICENSE', 'TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md'):
        put(root, name)
    put(root, 'registry/sources/restricted.artifact.json', {'license': {'spdx': 'NOASSERTION', 'redistribution': 'LOCAL_EXECUTION_ONLY'}})
    library = put(root, 'build/current/id/demo/libdemo.so', b'native binary')
    record = put(root, 'build/current/id/demo/build.json', {'artifact': str(library), 'runtime_dependencies': [{'path': '/outside/libc.so', 'sha256': 'declared-runtime-hash'}]})
    put(root, 'runs/native/qualification.json', {'artifact': str(library), 'build_record': str(record)})
    wheel = put(root, 'build/package-latest/current.whl', b'current indexed wheel')
    package = put(root, 'docs/package.json', {'wheel': str(wheel.relative_to(root))})
    put(root, 'build/package-old/stale.whl', b'old unreferenced wheel')
    runs = []
    for kind in ('synthetic', 'real'):
        path = root / 'runs' / kind
        dataset = str(root / 'benchmark/examples/data/a.npy') if kind == 'synthetic' else '/external/corpus/source.csv'
        manifest = put(root, f'runs/{kind}/manifest.json', {'run_id': kind, 'resolved_config': {'datasets': [{'path': dataset}]}})
        observations = put(root, f'runs/{kind}/observations.jsonl', b'{"status":"ok"}\n')
        put(root, f'runs/{kind}/artifacts/wire.tsb', b'compressed ' + kind.encode())
        put(root, f'runs/{kind}/restored/object.json', {'shape': [7]})
        put(root, f'runs/{kind}/restored/0.npy', b'restored original')
        runs.append({'run': str(path.relative_to(root)), 'manifest_sha256': module.sha(manifest), 'observations_sha256': module.sha(observations)})
    put(root, 'benchmark/examples/data/a.npy', b'raw original')
    put(root, 'runs/history/observations.jsonl', b'old unrelated run')
    put(root, 'build/history/objects.o', b'old unrelated intermediate')
    index = put(root, 'docs/current_evidence.json', {'schema': 'tsbench.current-evidence/1', 'runs': runs, 'native_qualification': {'path': 'runs/native/qualification.json', 'sha256': module.sha(root / 'runs/native/qualification.json')}, 'package_verification': {'path': 'docs/package.json', 'sha256': module.sha(package)}})
    return index


def test_current_selection_preserves_restrictions_and_omits_inputs(tmp_path):
    index = fixture(tmp_path)
    plan = module.collect(tmp_path, index)
    files = {item['path'] for item in plan['files']}
    omitted = {item['path']: item['reason'] for item in plan['omissions']}
    assert 'runs/synthetic/artifacts/wire.tsb' in files
    assert 'runs/real/artifacts/wire.tsb' in omitted
    assert 'benchmark/examples/data/a.npy' in omitted
    assert 'runs/synthetic/restored/object.json' in omitted
    assert 'runs/history/observations.jsonl' not in files
    assert 'build/history/objects.o' not in files
    assert 'build/current/id/demo/build.json' in files
    assert 'build/current/id/demo/libdemo.so' in omitted
    assert 'build/package-latest/current.whl' in omitted
    assert plan['asset_license_records'][0]['license']['redistribution'] == 'LOCAL_EXECUTION_ONLY'
    assert plan['publication']['public_redistribution_claimed'] is False
    binary_plan = module.collect(tmp_path, index, include_binaries=True)
    assert 'build/current/id/demo/libdemo.so' in {item['path'] for item in binary_plan['files']}
    assert 'build/package-latest/current.whl' in {item['path'] for item in binary_plan['files']}
    assert 'build/package-old/stale.whl' not in {item['path'] for item in binary_plan['files']}


def test_export_verifies_every_member_and_preserves_original_evidence(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    index = fixture(root)
    before = module.sha(root / 'runs/real/manifest.json')
    destination = tmp_path / 'private.tar.gz'
    result = module.export(module.collect(root, index), destination)
    assert result['selected_runs'] == 2
    assert module.verify(destination)['verified'] is True
    assert module.sha(root / 'runs/real/manifest.json') == before
    with tarfile.open(destination, 'r:gz') as archive:
        manifest = json.load(archive.extractfile('tsbench-local/EXPORT_MANIFEST.json'))
        omitted = next(x for x in manifest['omissions'] if x['path'] == 'runs/real/artifacts/wire.tsb')
        assert omitted['sha256'] == module.sha(root / omitted['path'])
    prior_bytes = destination.read_bytes()
    with pytest.raises(FileExistsError):
        module.export(module.collect(root, index), destination)
    assert destination.read_bytes() == prior_bytes


def test_rejects_index_drift_symlinks_and_parent_traversal(tmp_path):
    index = fixture(tmp_path)
    with pytest.raises(ValueError, match='parent traversal'):
        module.collect(tmp_path, '../current_evidence.json')
    (tmp_path / 'adapters/demo/link').symlink_to('/etc/hosts')
    with pytest.raises(ValueError, match='symlink'):
        module.collect(tmp_path, index)
    (tmp_path / 'adapters/demo/link').unlink()
    (tmp_path / 'runs/real/observations.jsonl').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        module.collect(tmp_path, index)


def test_verify_rejects_unaccounted_and_unsafe_members(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    index = fixture(root)
    good = tmp_path / 'good.tar.gz'
    module.export(module.collect(root, index), good)
    for label, member_name in [('extra', 'tsbench-local/extra.txt'), ('unsafe', '../escape.txt')]:
        bad = tmp_path / (label + '.tar.gz')
        with tarfile.open(good, 'r:gz') as original, tarfile.open(bad, 'w:gz') as rewritten:
            for member in original.getmembers():
                rewritten.addfile(member, original.extractfile(member))
            info = tarfile.TarInfo(member_name)
            info.size = 1
            rewritten.addfile(info, io.BytesIO(b'x'))
        with pytest.raises(ValueError, match='unaccounted|unsafe'):
            module.verify(bad)


def test_omitted_wire_hash_drift_does_not_install_partial_export(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    index = fixture(root)
    # A real artifact is not copied, but its content address still must be true.
    put(root, 'runs/real/artifacts/' + '0' * 64 + '.tsb', b'not the claimed hash')
    destination = tmp_path / 'private.tar.gz'
    with pytest.raises(ValueError, match='omitted artifact differs'):
        module.export(module.collect(root, index), destination)
    assert not destination.exists()
    assert not list(tmp_path.glob('.private.tar.gz.*'))


@pytest.mark.parametrize('key,path_key', [('pems_preparation', 'path'), ('post_observed_parameter_policy', 'source')])
def test_indexed_preparation_hash_is_checked(tmp_path, key, path_key):
    index = fixture(tmp_path)
    preparation = put(tmp_path, 'benchmark/experiments/current/preparation.json', {'frozen': True})
    content = json.loads(index.read_bytes())
    content[key] = {path_key: str(preparation.relative_to(tmp_path)), 'sha256': module.sha(preparation)}
    index.write_bytes(module.json_bytes(content))
    assert str(preparation.relative_to(tmp_path)) in {item['path'] for item in module.collect(tmp_path, index)['files']}
    preparation.write_bytes(b'changed preparation')
    with pytest.raises(ValueError, match='indexed evidence hash mismatch'):
        module.collect(tmp_path, index)


def test_current_installed_wheel_supersedes_old_package_evidence(tmp_path):
    index = fixture(tmp_path)
    wheel = put(tmp_path, 'build/package-installed/current.whl', b'verified installed current wheel')
    verification = put(tmp_path, 'docs/package-installed.json', {
        'wheel': str(wheel.relative_to(tmp_path)), 'wheel_sha256': module.sha(wheel)})
    content = json.loads(index.read_bytes())
    content['package_installed_verification'] = {
        'path': str(verification.relative_to(tmp_path)), 'sha256': module.sha(verification)}
    index.write_bytes(module.json_bytes(content))
    plan = module.collect(tmp_path, index, include_binaries=True)
    files = {item['path'] for item in plan['files']}
    omitted = {item['path']: item['reason'] for item in plan['omissions']}
    assert 'build/package-installed/current.whl' in files
    assert 'build/package-latest/current.whl' not in files
    assert 'superseded_package_wheel_not_selected' in omitted['build/package-latest/current.whl']
    assert 'docs/package.json' in files and 'docs/package-installed.json' in files
    wheel.write_bytes(b'polluted installed wheel')
    with pytest.raises(ValueError, match='current indexed wheel hash mismatch'):
        module.collect(tmp_path, index, include_binaries=True)
