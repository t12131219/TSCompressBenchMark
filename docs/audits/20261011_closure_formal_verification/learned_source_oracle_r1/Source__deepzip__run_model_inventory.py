"""Isolate legacy-runtime failures so one model cannot hide other evidence."""
import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    tree = ast.parse((ROOT / 'upstream/src/models.py').read_text())
    names = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    result = dict(schema_version=1, source_modified=False, cases=[])
    for name in names:
        folder = a.output / name
        folder.mkdir(exist_ok=True)
        command = [sys.executable, str(ROOT / 'model_oracle.py'),
                   '--output', str(folder), '--model-name', name]
        proc = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, env=dict(os.environ), timeout=120)
        (folder / 'source.log').write_text(proc.stdout)
        report = folder / 'model_inventory.json'
        if report.is_file():
            record = json.loads(report.read_text())['cases'][0]
        else:
            record = dict(name=name, status='PROCESS_FAILURE')
        record.update(returncode=proc.returncode, command=command)
        result['cases'].append(record)
        (a.output / 'model_inventory.json').write_text(json.dumps(result, indent=2) + '\n')
        print(name, record['status'], proc.returncode, flush=True)


if __name__ == '__main__':
    main()
