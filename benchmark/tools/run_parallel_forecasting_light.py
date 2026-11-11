"""Run two frozen lightweight families on pinned CPUs beside the main sweep."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def now() -> str:
    return datetime.now().astimezone().isoformat()


def main() -> None:
    design_path = Path(sys.argv[1]).resolve()
    if design_path.is_dir():
        design_path = design_path / 'design.json'
    design = json.loads(design_path.read_text())
    root = Path(design['run_root'])
    lock = (root / 'parallel_light.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    amendment_path = design_path.parent / 'amendments/parallel-light/amendment.json'
    previous_state = json.loads(amendment_path.read_text()) if amendment_path.exists() else None
    if previous_state and any(run.get('returncode') != 1 for run in previous_state.get('runs', [])):
        raise RuntimeError('parallel amendment contains a non-retryable prior run')
    amendment_path.parent.mkdir(parents=True, exist_ok=True)
    queues = {12: [], 13: []}
    for entry in design['configurations']:
        stem = Path(entry['path']).stem
        for cpu, family in ((12, 'Wind'), (13, 'ZafNoo')):
            if stem.startswith(family + '-'):
                queues[cpu].append(entry)
    assert all(len(entries) == 12 for entries in queues.values())

    progress_path = root / 'orchestration.json'
    progress = json.loads(progress_path.read_text()) if progress_path.exists() else {'completed_configurations': 0}
    if progress['completed_configurations'] >= 200:
        raise RuntimeError('main sweep is already too close to the reserved light configurations')

    original_affinity = sorted(os.sched_getaffinity(0))
    state = {'schema': 'tsbench.parallel-light-amendment/1', 'created_at': now(),
             'reason': 'User requested lightweight datasets alongside the main sweep',
             'main_pid': None, 'main_original_affinity': original_affinity,
             'main_parallel_affinity': original_affinity, 'main_affinity_modified': False,
             'queues': {str(cpu): [e['path'] for e in entries] for cpu, entries in queues.items()},
             'protocol': 'Auxiliary workers pinned to CPUs 12 and 13 while the main queue continued with its original scheduler affinity. The main queue was not restricted, so runnable workers may contend when scheduled on those CPUs; inputs, codec parameters and repetition counts are unchanged.',
             'status': 'parallel_started', 'events': [{'at': now(), 'event': 'parallel_started',
                                                        'main_completed_configurations': progress['completed_configurations']}],
             'runs': [], 'failed_launch_attempts': previous_state.get('runs', []) if previous_state else []}
    if previous_state:
        state['events'].append({'at': now(), 'event': 'retry_after_missing_pythonpath',
                                'failed_launch_attempts': len(previous_state.get('runs', []))})
    host = {'recorded_at': now(), 'orchestrator_affinity': original_affinity,
            'auxiliary_cpu_assignments': {'Wind': 12, 'ZafNoo': 13},
            'cpu_topology': {str(cpu): {
                'physical_package_id': Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/physical_package_id').read_text().strip(),
                'core_id': Path(f'/sys/devices/system/cpu/cpu{cpu}/topology/core_id').read_text().strip()}
                for cpu in (12, 13)}}

    def save() -> None:
        for target in (amendment_path, root / 'parallel_orchestration.json'):
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            temporary.replace(target)
        (amendment_path.parent / 'host_readback.json').write_text(json.dumps(host, indent=2))

    save()

    def lane(cpu: int, entries: list[dict]) -> None:
        for entry in entries:
            started = now()
            command = ['taskset', '-c', str(cpu), sys.executable, '-m', 'tsbench', 'run', entry['path']]
            with (root / (Path(entry['path']).stem + '.log')).open('ab') as log:
                code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
            directory = Path(entry['run'])
            complete = ((directory / 'report/summary.json').exists() and
                        json.loads((directory / 'manifest.json').read_text()).get('state') == 'complete')
            state['runs'].append({'configuration': entry['path'], 'run': entry['run'], 'cpu': cpu,
                                  'started_at': started, 'ended_at': now(),
                                  'returncode': code, 'complete': complete})
            save()
            if code or not complete:
                raise RuntimeError(f'auxiliary experiment failed: {entry["path"]}')

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(lane, cpu, entries) for cpu, entries in queues.items()]
        for future in futures:
            future.result()
    state['events'].append({'at': now(), 'event': 'parallel_complete'})
    state['status'] = 'parallel_complete'
    save()


if __name__ == '__main__':
    main()
