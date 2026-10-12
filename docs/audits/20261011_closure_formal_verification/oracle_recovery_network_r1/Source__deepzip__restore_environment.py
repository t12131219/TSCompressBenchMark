"""Rebuild an isolated oracle from verified acquisition archives only.

This uses a user-specified existing conda installation. Archives must be
acquired separately; no unverified automatic network or environment mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--conda', type=Path, required=True)
    p.add_argument('--conda-cache', type=Path, required=True)
    p.add_argument('--pip-cache', type=Path, required=True)
    p.add_argument('--prefix', type=Path, required=True)
    a = p.parse_args()
    prefix = a.prefix.resolve()
    if prefix.exists():
        raise ValueError('target must be a new isolated environment')
    lock = json.loads((ROOT / 'ORACLE_ENVIRONMENT_LOCK.json').read_text())
    conda_archives = []
    for record in lock['conda']:
        path = a.conda_cache / record['filename']
        if digest(path) != record['sha256']:
            raise ValueError('conda archive hash mismatch: ' + str(path))
        conda_archives.append(str(path.resolve()))
    for record in lock['pip_acquisition_archives']:
        path = a.pip_cache / record['filename']
        if digest(path) != record['sha256']:
            raise ValueError('pip archive hash mismatch: ' + str(path))
    subprocess.run([str(a.conda), 'create', '-y', '--offline', '--no-deps',
                    '--prefix', str(prefix)] + conda_archives, check=True)
    subprocess.run([str(prefix / 'bin/python'), '-m', 'pip', 'install',
                    '--cache-dir', str(a.pip_cache / 'build-cache'),
                    '--no-index', '--no-deps', '--find-links', str(a.pip_cache),
                    '-r', str(ROOT / 'oracle-requirements.txt')], check=True)
    print('Rebuilt locked source environment:', prefix)
    print('Use TF_FP16_RNN_USE_FP32_COMPUTE=0 and LD_LIBRARY_PATH=' + str(prefix / 'lib'))
    print('No PYTHONPATH overlay is needed in this rebuilt Keras 2.2.2 environment.')


if __name__ == '__main__':
    main()
