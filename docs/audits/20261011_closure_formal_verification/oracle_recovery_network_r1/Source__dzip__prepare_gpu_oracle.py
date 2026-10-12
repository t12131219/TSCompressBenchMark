"""Restore a separate TF 1.14/CUDA 10 reference environment in /tmp.

Never changes the system CUDA installation or the existing DeepZip oracle.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parent
DOWNLOADS = Path('/tmp/tscb-dzip-gpu-downloads')
RUNTIME = Path('/tmp/tscb-dzip-cuda10')
ENV = Path('/tmp/tscb-dzip-oracle-gpu')
PACKAGES = [
    ('cudatoolkit-10.0.130-0.conda', 'anaconda/cudatoolkit/10.0.130',
     '208b656bd70ebebde57b7633a812582ee0f14559089255d927c35f38949cac97'),
    ('cudnn-7.6.5-cuda10.0_0.conda', 'anaconda/cudnn/7.6.5',
     '770a0a802b642b380971d4d3d21309a45f84965f644011173dd4cc262d10accb'),
]


def sha(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def main():
    import conda_package_handling.api as conda
    DOWNLOADS.mkdir(exist_ok=True)
    RUNTIME.mkdir(exist_ok=True)
    records = []
    for name, route, expected in PACKAGES:
        path = DOWNLOADS / name
        url = 'https://api.anaconda.org/download/' + route + '/linux-64/' + name
        if not path.exists():
            partial = path.with_suffix('.partial')
            print('Downloading ' + name, flush=True)
            urllib.request.urlretrieve(url, str(partial))
            if sha(partial) != expected:
                raise RuntimeError('Package hash mismatch: ' + name)
            partial.rename(path)
        if sha(path) != expected:
            raise RuntimeError('Cached package hash mismatch: ' + name)
        marker = RUNTIME / (name + '.extracted')
        if not marker.exists():
            conda.extract(str(path), dest_dir=str(RUNTIME))
            marker.write_text(expected + '\n')
        records.append(dict(name=name, url=url, sha256=expected))
    subprocess.run(['/tmp/tscb-deepzip-oracle-rebuilt/bin/python', '-m', 'venv',
                    '--system-site-packages', str(ENV)], check=True)
    pip = [str(ENV / 'bin/python'), '-m', 'pip']
    subprocess.run(pip + ['download', '--no-deps', '--dest', str(DOWNLOADS),
                         'tensorflow-gpu==1.14.0'], check=True)
    wheel = next(DOWNLOADS.glob('tensorflow_gpu-1.14.0-cp36-*.whl'))
    records.append(dict(name=wheel.name, sha256=sha(wheel), source='PyPI tensorflow-gpu 1.14.0'))
    deps = Path('/tmp/tscb-dzip-wheels')
    wheels = [wheel, *[deps / name for name in [
        'tensorboard-1.14.0-py3-none-any.whl',
        'tensorflow_estimator-1.14.0-py2.py3-none-any.whl',
        'google_pasta-0.2.0-py3-none-any.whl',
        'Keras_Applications-1.0.4-py2.py3-none-any.whl',
        'Keras_Preprocessing-1.0.2-py2.py3-none-any.whl',
        'gast-0.2.2.tar.gz',
        'wrapt-1.16.0-cp36-cp36m-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl']]]
    subprocess.run(pip + ['install', '--ignore-installed', '--no-deps', *map(str, wheels)], check=True)
    for path in wheels[1:]:
        records.append(dict(name=path.name, sha256=sha(path)))
    (ROOT / 'GPU_ORACLE_ENVIRONMENT_LOCK.json').write_text(json.dumps(dict(
        status='INSTALLED_NOT_YET_RUNTIME_VALIDATED', packages=records, environment=str(ENV),
        runtime=str(RUNTIME), driver_sha256=sha(Path(__file__))), indent=2) + '\n')


if __name__ == '__main__':
    main()
