"""M2 execution controls using a real build, lock conflict and sealed replay."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.api import TimingPlanRequest, plan_timing, report_timing, run_timing
from tsbench.application.timing import LEDGER, SEAL
from tsbench.assets import ContractError, canonical_bytes, content_id, digest, load_json
from tsbench.supervisor.timing_resource import reserve


def cli(*args, code=0):
    p = subprocess.run([sys.executable, '-I', '-B', ROOT / 'bmk', *args], capture_output=True, timeout=60)
    assert p.returncode == code, p.stderr.decode()
    return json.loads(p.stdout if code == 0 else p.stderr)


def resealed_rejection(run, run_id):
    path = run / LEDGER
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    i = next(i for i, row in enumerate(rows) if row['phase'] == 'measured')
    rows[i]['loops'] += 1
    path.write_bytes(b''.join(canonical_bytes(row) + b'\n' for row in rows))
    completion = run / SEAL
    seal = load_json(completion)
    del seal['seal_id']
    next(f for f in seal['files'] if f['path'] == LEDGER).update(bytes=path.stat().st_size, sha256=digest(path))
    completion.write_bytes(canonical_bytes({**seal, 'seal_id': content_id(seal)}))
    try:
        report_timing(run.parents[1], run_id)
    except ContractError as exc:
        assert 'calibrated loops differs from plan' in str(exc), exc
        return str(exc)
    raise AssertionError('accepted a changed loop count even when calibration disagreed')


def exercise(plan_path, run_ids):
    plan = load_json(ROOT / plan_path)
    request = TimingPlanRequest(plan['build_dir'], plan['environment']['cpu'])
    assert plan_timing(ROOT, request) == plan == cli('timing-plan', '--build-dir', request.build_dir, '--cpu', str(request.cpu))
    results = ROOT / 'results'
    before = set(results.iterdir())
    with reserve():
        refusal = cli('timing-run', '--plan', plan_path, code=2)
        assert 'resource is already reserved' in refusal['reason'], refusal
        try:
            run_timing(ROOT, plan)
        except ContractError as exc:
            assert str(exc) == refusal['reason'], exc
        else:
            raise AssertionError('concurrent API acquired a non-reentrant reservation')
    assert before == set(results.iterdir()), 'refused submissions must not publish a run'
    stopped = run_timing(ROOT, plan, cancelled=lambda: True)
    groups = len(plan['batches']['groups'])
    assert stopped['statuses'] == {'cancelled': 2*groups, 'blocked_calibration': plan['planned_batches']-2*groups}
    assert stopped['serial_child_wall_ns'] == 0 and not stopped['all_batches_verified']
    assert report_timing(ROOT, stopped['run_id']) == stopped

    with tempfile.TemporaryDirectory(prefix='timing-build-copy-', dir=ROOT / request.build_dir) as t:
        copied_build = Path(t)
        original = ROOT / request.build_dir
        for artifact in plan['artifacts'].values():
            source = ROOT / artifact['path']
            dest = copied_build / source.relative_to(original)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
        missing_plan = plan_timing(ROOT, TimingPlanRequest(copied_build.relative_to(ROOT).as_posix(), request.cpu))
        next(copied_build.rglob('liblzbench_native.so')).rename(copied_build / 'withheld.so')
        failed = run_timing(ROOT, missing_plan)
        affected = sum(g['method'] == 'zstd' for g in missing_plan['batches']['groups'])
        failed_calibration = 2 * affected
        blocked = 2 * missing_plan['batches']['config']['matched_rounds'] * affected
        assert failed['statuses'] == {'dependency_failed': failed_calibration, 'blocked_calibration': blocked,
                                       'verified': missing_plan['planned_batches'] - failed_calibration - blocked}
    assert report_timing(ROOT, failed['run_id']) == failed

    with tempfile.TemporaryDirectory(prefix='timing-replay-') as t:
        paths = {}
        for run_id in run_ids:
            original = results / run_id
            run = Path(t) / 'results' / run_id
            shutil.copytree(original, run, ignore=shutil.ignore_patterns('derived'))
            assert report_timing(Path(t), run_id)['all_batches_verified']
            assert (run / 'derived/report.json').read_bytes() == (original / 'derived/report.json').read_bytes()
            paths[run_id] = run
        rejection = resealed_rejection(paths[run_ids[0]], run_ids[0])
    return {'cli_api_same_plan': True, 'plan_content_id': plan['plan_content_id'],
            'lock_contention_rejected_before_publication': refusal['reason'],
            'cancelled_run_id': stopped['run_id'], 'cancelled_run_statuses': stopped['statuses'],
            'missing_library_run_id': failed['run_id'], 'missing_library_run_statuses': failed['statuses'],
            'byte_identical_replay_runs': run_ids, 'resealed_changed_loop_rejected': rejection}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('plan')
    parser.add_argument('run_ids', nargs=2)
    args = parser.parse_args()
    sys.stdout.buffer.write(canonical_bytes(exercise(args.plan, args.run_ids)) + b'\n')
