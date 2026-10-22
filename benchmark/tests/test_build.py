"""Build identities preserve installed recipe origins and reject empty work."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tsbench import build
from tsbench.errors import Unavailable
from tsbench.provenance import execution_files


def assets(root):
    for folder in ('adapters/zstd_frame/native', 'native/include', 'registry/codecs'):
        (root / folder).mkdir(parents=True)
    (root / 'adapters/zstd_frame/native/shim.c').write_text('source')
    (root / 'native/include/adapter.h').write_text('header')
    (root / 'registry/codecs/zstd-frame.json').write_text(json.dumps({'key': 'zstd-frame'}))


def test_installed_recipe_sources_keep_real_origin_and_content_identity(tmp_path, monkeypatch):
    root = tmp_path / 'assets'
    assets(root)
    package = tmp_path / 'installed/tsbench'
    package.mkdir(parents=True)
    local_build = package / 'build.py'
    local_recipe = package / '_native_recipes.py'
    local_build.write_text('installed build')
    local_recipe.write_text('installed recipe')
    (package / 'families.py').write_text('installed canonical family mapping')
    monkeypatch.setattr(build, '__file__', str(local_build))
    monkeypatch.setattr(build.recipes, '__file__', str(local_recipe))
    records = build._source_files(root, 'zstd-frame')
    installed = {row['path']: row for row in records if row['path'].startswith('package:')}
    assert set(installed) == {'package:tsbench/build.py', 'package:tsbench/_native_recipes.py', 'package:tsbench/families.py'}
    assert installed['package:tsbench/build.py']['source_path'] == str(local_build)
    assert installed['package:tsbench/_native_recipes.py']['sha256'] == build.sha(local_recipe)
    assert any(row['path'] == 'registry/codecs/zstd-frame.json' for row in records)
    local_recipe.write_text('changed installed recipe')
    assert build._source_files(root, 'zstd-frame') != records


def test_checkout_recipe_sources_keep_asset_relative_labels(tmp_path, monkeypatch):
    assets(tmp_path)
    package = tmp_path / 'benchmark/src/tsbench'
    package.mkdir(parents=True)
    for name in ('build.py', '_native_recipes.py', 'families.py'):
        (package / name).write_text(name)
    monkeypatch.setattr(build, '__file__', str(package / 'build.py'))
    monkeypatch.setattr(build.recipes, '__file__', str(package / '_native_recipes.py'))
    records = build._source_files(tmp_path, 'zstd-frame')
    python_records = [row for row in records if row['path'].endswith('.py')]
    assert python_records == [{'path': 'benchmark/src/tsbench/' + name, 'sha256': build.sha(package / name)}
                              for name in ('build.py', '_native_recipes.py', 'families.py')]


@pytest.mark.parametrize('registry_present', [False, True])
def test_all_build_rejects_absent_or_empty_registry_before_compiling(tmp_path, monkeypatch, registry_present):
    if registry_present:
        (tmp_path / 'registry/codecs').mkdir(parents=True)
    monkeypatch.setattr(build, 'build_codec', lambda *args, **kwargs: pytest.fail('empty selection must not compile'))
    with pytest.raises(Unavailable, match='codec registry missing|no native codecs selected'):
        build.build_all(tmp_path)


def test_explicit_empty_codec_selection_is_not_all_or_success(tmp_path, monkeypatch):
    monkeypatch.setattr(build, 'Registry', lambda *args: pytest.fail('explicit empty selection must not select all'))
    with pytest.raises(Unavailable, match='no native codecs selected'):
        build.build_all(tmp_path, [])


def test_cli_build_all_missing_registry_returns_failure(tmp_path, monkeypatch, capsys):
    from tsbench import cli
    monkeypatch.setattr('sys.argv', ['tsbench', 'build', '--all', '--asset-root', str(tmp_path)])
    assert cli.entrypoint() == 1
    result = capsys.readouterr()
    assert 'codec registry missing' in result.err
    assert result.out == ''


def test_build_fixes_remain_outside_cpu_measurement_source_closure():
    names = {path.name for path in execution_files()}
    assert 'build.py' not in names and '_native_recipes.py' not in names
    assert 'cli.py' in names


def test_installed_wheel_builds_native_zstd_and_wire_only_decoder_restores(tmp_path):
    """Exercise the installed CLI with real assets and a fresh build, without timing."""
    if not shutil.which('cc') or not shutil.which('ldd'):
        pytest.skip('real Zstd build requires the local C compiler and ldd')
    root = Path(__file__).resolve().parents[2]
    project = tmp_path / 'native-assets'
    shutil.copytree(root / 'adapters/zstd_frame', project / 'adapters/zstd_frame')
    shutil.copytree(root / 'native/include', project / 'native/include')
    (project / 'registry/codecs').mkdir(parents=True)
    shutil.copy2(root / 'registry/codecs/zstd-frame.json', project / 'registry/codecs/zstd-frame.json')
    package_source = tmp_path / 'package-source'
    package_source.mkdir()
    shutil.copy2(root / 'benchmark/pyproject.toml', package_source / 'pyproject.toml')
    shutil.copytree(root / 'benchmark/src', package_source / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.egg-info'))
    wheels = tmp_path / 'wheels'
    wheels.mkdir()
    def invoke(arguments, env=None):
        return subprocess.run([sys.executable, *arguments], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=180, check=True)
    invoke(['-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation', str(package_source), '--wheel-dir', str(wheels)])
    wheel = next(wheels.glob('tsbench-*.whl'))
    installed = tmp_path / 'installed'
    invoke(['-m', 'pip', 'install', '--no-deps', '--no-index', '--target', str(installed), str(wheel)])
    env = {**os.environ, 'PYTHONPATH': str(installed)}
    build_root = project / 'new-build'
    built = invoke(['-m', 'tsbench', 'build', 'zstd-frame', '--asset-root', str(project),
                    '--build-root', str(build_root)], env)
    record = json.loads(built.stdout)[0]
    assert record['status'] == 'ok' and record['dependency_capture'] == 'ACTUAL_PER_TU_MD'
    package_sources = [row for row in record['sources'] if row['path'].startswith('package:')]
    assert {row['path'] for row in package_sources} == {'package:tsbench/build.py', 'package:tsbench/_native_recipes.py', 'package:tsbench/families.py'}
    assert all(Path(row['source_path']).is_relative_to(installed) for row in package_sources)
    assert not (root / record['artifact']).exists()  # The fresh artifact belongs to this isolated asset checkout.
    encoded = invoke(['-c', '''
import json,sys
from pathlib import Path
import numpy as np
import tsbench
from tsbench.data import TimeSeriesObject
from tsbench.schemes import ObjectScheme
root,build_root,wire,original=map(Path,sys.argv[1:])
values=np.arange(771,dtype='<f8').reshape(257,3)
obj=TimeSeriesObject({'V':values},{'roles':{'V':'V'},'topology':'SYNCHRONOUS_MTS'})
before=values.tobytes()
encoded=ObjectScheme({'id':'zstd','codec':'zstd-frame'},root,build_root).encode_once(obj)
assert values.tobytes()==before
wire.write_bytes(encoded.wire)
np.save(original,values,allow_pickle=False)
print(json.dumps({'package':tsbench.__file__,'bytes':len(encoded.wire)}))
''', str(project), str(build_root), str(tmp_path / 'wire.tsb'), str(tmp_path / 'expected.npy')], env)
    assert Path(json.loads(encoded.stdout)['package']).is_relative_to(installed)
    output = tmp_path / 'decoded'
    invoke(['-m', 'tsbench', 'decode', str(tmp_path / 'wire.tsb'), str(output),
            '--asset-root', str(project), '--build-root', str(build_root)], env)
    import numpy as np
    metadata = json.loads((output / 'object.json').read_text())
    restored = np.load(output / metadata['components']['V'], allow_pickle=False)
    expected = np.load(tmp_path / 'expected.npy', allow_pickle=False)
    assert restored.dtype == expected.dtype and restored.shape == expected.shape
    assert restored.tobytes() == expected.tobytes()
