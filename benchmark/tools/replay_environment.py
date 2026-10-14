"""Independently build and replay declared CPU experiments in this interpreter.

Invoke this script with the desired installed Python executable. It never installs
or modifies an environment. Existing run directories are deliberately rejected.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

from tsbench.build import build_all
from tsbench.config import load
from tsbench.records import file_hash, read_jsonl, write_json
from tsbench.runner import run
from tsbench.schemes import ASSET_ROOT
from tsbench.trial_analysis import case_coverage, scheduled_rows


def summarize_run(destination):
    manifest = json.loads((destination / 'manifest.json').read_bytes())
    rows, tail = read_jsonl(destination / 'observations.jsonl')
    if tail:
        raise RuntimeError('replay ended with an interrupted observation tail')
    selected, planned = scheduled_rows(manifest, rows)
    coverage = {case['case_id']: case_coverage(manifest, case, selected, planned)
                for case in manifest['cases']}
    ready = [case for case in manifest['cases'] if case['status'] == 'ready']
    return {'run_id': manifest['run_id'], 'environment': manifest['environment'],
            'manifest_state': manifest.get('state'),
            'manifest_sha256': file_hash(destination / 'manifest.json'),
            'observations_sha256': file_hash(destination / 'observations.jsonl'),
            'admission': dict(collections.Counter(c['status'] for c in manifest['cases'])),
            'requested_trials': sum(len(keys) for keys in planned.values()),
            'missing_trials': sum(c['missing_trials'] for c in coverage.values()),
            'ready_cases': len(ready),
            'complete_cases': sum(coverage[c['case_id']]['complete'] for c in ready),
            'all_planned_trials_ok': bool(planned) and all(c['complete'] for c in coverage.values() if c['requested_trials']),
            'coverage': coverage,
            'trials': dict(collections.Counter(r['status'] for r in selected.values())),
            'trial_attempts': dict(collections.Counter(r['status'] for r in rows
                if r.get('event') == 'terminal' and r.get('phase') == 'measurement'))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('configs', nargs='+', type=Path)
    parser.add_argument('--build-root', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--skip-build', action='store_true', help='reuse already independently built binaries')
    args = parser.parse_args(argv)
    build_root = args.build_root.resolve()
    output_root = args.output_root.resolve()
    if (output_root / 'replay.json').exists():
        raise FileExistsError('replay evidence exists; choose a new output root')
    if (output_root / 'build.json').exists():
        raise FileExistsError('build evidence exists; choose a new output root')
    paths = [path.resolve(strict=True) for path in args.configs]
    destinations = [(output_root / path.stem).resolve() for path in paths]
    if len(set(destinations)) != len(destinations):
        raise ValueError('config stems must map to distinct replay directories')
    for destination in destinations:
        if destination.exists():
            raise FileExistsError(f'replay run directory exists: {destination}')
    output_root.mkdir(parents=True, exist_ok=True)
    report = {'schema': 'tsbench.environment-replay/1', 'status': 'preparing',
              'interpreter': sys.executable, 'script_sha256': file_hash(__file__),
              'build_root': str(build_root), 'build_policy': 'reuse explicit build root' if args.skip_build else 'independent build',
              'primary_policy': 'earliest executed attempt; successful retry never replaces executed failure',
              'runs': [{'run': str(destination), 'config': str(path), 'config_sha256': file_hash(path), 'status': 'pending'}
                       for path, destination in zip(paths, destinations)]}
    checkpoint = output_root / 'replay.json'
    write_json(checkpoint, report)
    active = None
    stage = 'config_resolution'
    try:
        configs = []
        for entry, path in zip(report['runs'], paths):
            active = entry
            cfg = load(path)
            cfg['_build_root'] = str(build_root)
            cfg['build_root'] = str(build_root)
            configs.append(cfg)
        active = None
        stage = 'build'
        report['status'] = 'building' if not args.skip_build else 'running'
        write_json(checkpoint, report)
        records = None if args.skip_build else build_all(ASSET_ROOT, build_root=build_root)
        if records is not None:
            write_json(output_root / 'build.json', records)
            report['build'] = {'path': str(output_root / 'build.json'),
                               'sha256': file_hash(output_root / 'build.json'),
                               'statuses': dict(collections.Counter(row['status'] for row in records))}
            write_json(checkpoint, report)
            if any(row['status'] != 'ok' for row in records):
                raise RuntimeError('one or more independent builds failed; see build.json')
        stage = 'run'
        report['status'] = 'running'
        for active, cfg, destination in zip(report['runs'], configs, destinations):
            active['status'] = 'running'
            write_json(checkpoint, report)
            actual_destination = Path(run(cfg, destination)).resolve()
            if actual_destination != destination:
                raise RuntimeError('runner returned an unexpected replay directory')
            active.update(summarize_run(destination))
            active['status'] = 'complete' if active['manifest_state'] == 'complete' else 'incomplete'
            write_json(checkpoint, report)
            if active['status'] != 'complete':
                raise RuntimeError('replay runner did not finish its declared schedule')
            print(json.dumps(active, ensure_ascii=False), flush=True)
        report['status'] = 'complete'
        write_json(checkpoint, report)
    except BaseException as error:
        failure = {'stage': stage, 'type': type(error).__name__, 'reason': str(error)}
        report.update(status='failed', failure=failure)
        if active is not None:
            active.update(status='failed', failure=failure)
            # Bind any partial evidence without parsing, repairing or resuming it.
            destination = Path(active['run'])
            for filename in ('manifest.json', 'observations.jsonl'):
                if (destination / filename).is_file():
                    active[filename.replace('.', '_') + '_sha256'] = file_hash(destination / filename)
        write_json(checkpoint, report)
        raise
    return report


if __name__ == '__main__':
    main()
