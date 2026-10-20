"""Run two distant, frozen light-data queues on separate physical CPU cores.

Only orchestration changes: codec parameters, inputs and repetition counts stay
frozen. The active main worker finishes before auxiliary measurements begin.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


def now():
    return datetime.now().astimezone().isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design', type=Path)
    parser.add_argument('--main-pid', type=int, required=True)
    args = parser.parse_args()
    design_path = args.design.resolve()
    design = json.loads(design_path.read_text())
    root = Path(design['run_root'])
    lock_file = (root / 'parallel_light.lock').open('w')
    fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    amendment = design_path.parent / 'amendments/parallel-light/amendment.json'
    if amendment.exists():
        raise RuntimeError('parallel amendment already exists; inspect before restarting')
    amendment.parent.mkdir(parents=True, exist_ok=True)
    main_proc = Path('/proc') / str(args.main_pid)
    command = (main_proc / 'cmdline').read_bytes().replace(b'\0', b' ').decode()
    if 'forecasting_benchmark.py run' not in command or design_path.parent.name not in command:
        raise RuntimeError('main PID is not the intended forecasting orchestrator')
    queues = {12: [], 13: []}
    for entry in design['configurations']:
        stem = Path(entry['path']).stem
        for cpu, family in [(12, 'Wind'), (13, 'ZafNoo')]:
            if stem.startswith(family + '-'):
                queues[cpu].append(entry)
    assert all(len(entries) == 12 for entries in queues.values())
    for entries in queues.values():
        for entry in entries:
            assert 'sha256:' + hashlib.file_digest(Path(entry['path']).open('rb'), 'sha256').hexdigest() == entry['sha256']
            if (Path(entry['run']) / 'manifest.json').exists():
                raise RuntimeError('selected auxiliary run already exists')
    old_affinity = sorted(os.sched_getaffinity(args.main_pid))
    main_affinity = sorted(set(old_affinity) - set(queues))
    assert {12, 13}.issubset(old_affinity) and main_affinity
    state = {'schema': 'tsbench.parallel-light-amendment/1', 'created_at': now(),
             'reason': 'User requested lightweight datasets alongside the main sweep',
             'main_pid': args.main_pid, 'main_original_affinity': old_affinity,
             'main_parallel_affinity': main_affinity,
             'queues': {str(cpu): [e['path'] for e in entries] for cpu, entries in queues.items()},
             'protocol': 'Frozen full inputs, codec parameters and 14 formal batches unchanged. External affinity inherited and recorded by runner. Shared cache/memory competition remains possible; throughput conditions differ from earlier sequential results.',
             'status': 'preparing', 'events': [], 'runs': []}
    mutex = threading.Lock()

    def save():
        for target in [amendment, root / 'parallel_orchestration.json']:
            temporary = target.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
            temporary.replace(target)

    def event(kind, **extra):
        with mutex:
            state['events'].append({'at': now(), 'event': kind, **extra})
            state['status'] = kind
            save()
        print(kind, extra, flush=True)

    def descendants():
        parents = {}
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():
                continue
            try:
                fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                parents[int(path.name)] = int(fields[1])
            except (OSError, ValueError, IndexError):
                pass
        found = {args.main_pid}
        while True:
            expanded = found | {pid for pid, parent in parents.items() if parent in found}
            if expanded == found:
                return found - {args.main_pid}
            found = expanded

    paused = False
    restricted = False
    try:
        os.sched_setaffinity(args.main_pid, set(main_affinity))
        restricted = True
        event('waiting_for_current_worker_boundary', main_affinity=main_affinity)
        while True:
            overlapping = []
            for pid in descendants():
                try:
                    if set(os.sched_getaffinity(pid)) & set(queues):
                        overlapping.append(pid)
                except ProcessLookupError:
                    pass
            if not overlapping:
                break
            time.sleep(5)
        event('parallel_started', main_descendants=sorted(descendants()))

        def lane(cpu, entries):
            for entry in entries:
                event('auxiliary_configuration_started', cpu=cpu, configuration=entry['path'])
                started = now()
                command = ['taskset', '-c', str(cpu), sys.executable, '-m', 'tsbench', 'run', entry['path']]
                with (root / (Path(entry['path']).stem + '.log')).open('ab') as log:
                    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
                    code = process.wait()
                directory = Path(entry['run'])
                complete = (directory / 'report/summary.json').exists() and json.loads((directory / 'manifest.json').read_text()).get('state') == 'complete'
                with mutex:
                    state['runs'].append({'configuration': entry['path'], 'run': entry['run'],
                                          'cpu': cpu, 'started_at': started, 'ended_at': now(),
                                          'returncode': code, 'complete': complete})
                    save()
                if code or not complete:
                    raise RuntimeError(f'auxiliary experiment failed: {entry["path"]}')
            return len(entries)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(lane, cpu, entries) for cpu, entries in queues.items()]
            while not all(future.done() for future in futures):
                # Stop only the orchestration parent, well before it can reach
                # reserved runs (indices 286..309). Its current worker finishes.
                # This also prevents simultaneous writes to a reserved run.
                try:
                    progress = json.loads((root / 'orchestration.json').read_text())
                except json.JSONDecodeError:
                    time.sleep(1)
                    continue
                if progress['completed_configurations'] >= 270 and not paused:
                    os.kill(args.main_pid, signal.SIGSTOP)
                    paused = True
                    event('main_parent_paused_before_reserved_range')
                time.sleep(5)
            counts = [future.result() for future in futures]
        event('parallel_complete', configurations=sum(counts))
    except BaseException as exc:
        event('parallel_error', error=repr(exc))
        raise
    finally:
        if restricted and main_proc.exists():
            os.sched_setaffinity(args.main_pid, set(old_affinity))
            event('main_affinity_restored', affinity=old_affinity)
        if paused and main_proc.exists():
            os.kill(args.main_pid, signal.SIGCONT)
            event('main_parent_resumed')


if __name__ == '__main__':
    main()
