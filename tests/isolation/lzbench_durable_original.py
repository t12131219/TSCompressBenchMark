"""Run real CSV ingress and detached frame restore of the frozen Zstd session.

Usage: tsbench Python .../tests/isolation/lzbench_durable_original.py <clock-plan>
The temporary run is a contract test, never a measurement receipt.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_lzbench_durable as path
from tsbench.application.m3_lzbench_corpus_clock import _schedule
from tsbench.assets import load_json, require
from tsbench.recovery import stage_recovery


def main(plan_path):
    plan = load_json(plan_path)
    case, = (c for c in plan['cases'] if c['dataset_id'] == 'etth1' and c['route'] == 'zstd-session')
    original = path._entry_map(ROOT, load_json(path._file(ROOT, plan['definition'])))[case['dataset_id']]
    reference = path._file(path._folder(ROOT, plan['source_run']), case['variants']['session']['retain'])
    sessions = set()
    with TemporaryDirectory(prefix='tsbench-lzbench-durable-contract-') as temp:
        run = Path(temp) / 'run'
        parent = run / 'cases' / case['case_id']
        parent.mkdir(parents=True)
        stage_recovery(ROOT, run, plan['runtime'], directory='runtime')
        results = []
        for trial in list(_schedule(case))[:2]:
            row, output = path._trial(ROOT, run, plan, case, trial, original, {'session': reference}, sessions)
            require(path.artifact(output) == row['output'], 'isolated durable contract output differs')
            results.append({'direction': row['direction'], 'ingress': row['source_original'] is not None,
                            'synced_and_verified': True, 'output': row['output']})
        require([(x['direction'], x['ingress']) for x in results] == [('encode', True), ('decode', False)] and len(sessions) == 2,
                'isolated durable contract did not exercise both scopes')
        print(results)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
