"""Prepare identical byte inputs and run the frozen source models/pipeline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PORT = Path(__file__).resolve().parents[1]
SOURCE = PORT.parent.parent / 'Source/deepzip'
REPO = PORT.parents[2]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def run(command, folder):
    proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, env=dict(os.environ), timeout=300)
    (folder / 'source.log').write_text(proc.stdout)
    return proc.returncode


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kind', choices=['datasets', 'models'], required=True)
    a = p.parse_args()
    cases = []
    folder = SOURCE / 'golden' / ('datasets' if a.kind == 'datasets' else 'pipelines')
    folder.mkdir(parents=True, exist_ok=True)
    if a.kind == 'datasets':
        for name in ['ETTh1.csv', 'exchange_rate.csv', 'weather.csv']:
            source = REPO / 'datasets' / name
            data = source.read_bytes()[:70065]
            if len(data) != 70065:
                raise ValueError('short dataset: ' + name)
            case = folder / name
            case.mkdir(exist_ok=True)
            original = case / 'canonical_input.bin'
            original.write_bytes(data)
            alphabet = len(set(data))
            command = [sys.executable, str(SOURCE / 'model_oracle.py'), '--output', str(case),
                       '--model-name', 'biGRU', '--alphabet', str(alphabet)]
            rc = run(command, case)
            if rc:
                raise RuntimeError('dataset model oracle failed: ' + name)
            model = case / 'biGRU.hdf5'
            cases.append(dict(case=name, folder=str(case), input=str(original),
                              model=str(model), model_name='biGRU', length=len(data), batch=1000,
                              source_file=str(source), source_file_sha256=sha(source),
                              canonical_sha256=sha(original), alphabet=alphabet,
                              model_sha256=sha(model), training='none'))
    else:
        # All symbols are legal; B=100 creates primary predicted symbols and
        # a 65-symbol predicted tail in one small complete pipeline case.
        import numpy as np
        raw = np.random.RandomState(7).randint(4, size=6665).astype('uint8').tobytes()
        input_file = folder / 'input.bin'
        input_file.write_bytes(raw)
        inventory = json.loads((SOURCE / 'golden/locked/model_inventory.json').read_text())
        for record in inventory['cases']:
            if record['status'] != 'PASS':
                continue
            name = record['name']
            case = folder / name
            case.mkdir(exist_ok=True)
            model = SOURCE / 'golden/locked' / name / (name + '.hdf5')
            cases.append(dict(case=name, folder=str(case), input=str(input_file), model=str(model),
                              model_name=name, length=len(raw), batch=100,
                              canonical_sha256=sha(input_file), model_sha256=sha(model), alphabet=4))
    results = []
    for case in cases:
        path = Path(case['folder'])
        report = path / 'source_roundtrip.json'
        command = [sys.executable, str(SOURCE / 'oracle_probe.py'), '--input', case['input'],
                   '--work', '/tmp/tscb-deepzip-' + a.kind + '-' + case['case'],
                   '--length', str(case['length']), '--batch-size', str(case['batch']),
                   '--model-name', case['model_name'], '--model', case['model'],
                   '--artifacts', str(path / 'pipeline'), '--output', str(report)]
        rc = run(command, path)
        case.update(command=command, returncode=rc,
                    source_result=json.loads(report.read_text()) if report.exists() else None)
        results.append(case)
        (folder / 'source_cases.json').write_text(json.dumps(results, indent=2) + '\n')
        print(case['case'], rc, flush=True)
        if rc:
            raise RuntimeError('source pipeline failed: ' + case['case'])


if __name__ == '__main__':
    main()
