"""Durable single-writer environment evidence for a frozen matched block."""
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import canonical_bytes, content_id, digest, load_json, parse_json, require
from . import matched_round_retry as retry
from . import worker_environment as worker

SCHEMA = 'bmk.matched-round-environment-ledger/1'
WITNESS = 'worker-environment.stdout'
FILES = ('run.json', 'ledger.jsonl', 'report.json')
FLAGS = dict.fromkeys(retry.FLAGS, False)


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _append(stream, value):
    stream.write(canonical_bytes(value) + b'\n')
    stream.flush()
    os.fsync(stream.fileno())


def _publish(path, value):
    # Link an already synced file, never replace an existing run or receipt.
    with TemporaryDirectory(prefix='.matched-publish-', dir=path.parent) as tmp:
        staged = Path(tmp) / 'content.json'
        with staged.open('xb') as f:
            _append(f, value)
        os.link(staged, path)
        _sync_dir(path.parent)


def _work(run, attempt, index):
    return run / f'a{attempt:02d}-s{index:04d}'


def _load_witness(run, work, *, sync):
    path = work / WITNESS
    require(work.is_dir() and not work.is_symlink() and not path.is_symlink(), 'invalid matched attempt witness path')
    if not path.exists():
        return None, None
    require(path.is_file() and path.stat().st_size <= 16384, 'invalid matched attempt witness file')
    with path.open('rb') as f:
        # persist the original bytes before making any terminal that cites them
        if sync:
            os.fsync(f.fileno())
        raw = f.read(16385)
    require(len(raw) <= 16384, 'oversized native worker witness')
    if sync:
        _sync_dir(work)
    ref = {'path': path.relative_to(run).as_posix(), 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
    if not raw:
        return ref, None
    require(raw.endswith(b'\n'), 'truncated native worker witness')
    return ref, parse_json(raw, 'native worker witness')


def _terminal(run, work, policy, run_id, slot, number, terminal, process, before, after, *, sync=False):
    sid, pid = process['session_id'], process['pid']
    require((sid is None and pid is None) or (isinstance(sid, str) and sid and type(pid) is int and pid > 0),
            'matched worker lacks a supervised process identity')
    require(terminal != 'verified' or (sid is not None and process['status'] == 'completed' and process['returncode'] == 0),
            'verified terminal requires a successful worker exit')
    ref, raw = _load_witness(run, work, sync=sync)
    facts = worker.project(slot['cpu_ids'], {'begin': None, 'end': None} if raw is None else raw,
                           before, after, session_id=sid)
    return {'kind': 'terminal', 'process': process, 'worker_witness': ref,
            'attempt': {'policy_id': policy['policy_id'], 'run_id': run_id, 'slot_id': slot['slot_id'],
                        'attempt': number, 'terminal': terminal, 'session_id': sid, 'environment': facts['retry_environment']}}


def _manifest(policy, run_id):
    retry.check(policy)
    require(isinstance(run_id, str) and run_id, 'invalid matched environment run id')
    return {'schema': SCHEMA, 'run_id': run_id, 'policy': policy, **FLAGS}


def replay(run):
    path = run / 'run.json'
    manifest = load_json(path)
    run_id, policy = manifest['run_id'], manifest['policy']
    require(manifest == _manifest(policy, run_id), 'matched environment run manifest differs')
    blocks, current = [], []
    report = None
    with (run / 'ledger.jsonl').open('rb') as f:
        for line in f:
            require(line.endswith(b'\n'), 'truncated matched environment ledger')
            row = parse_json(line, 'matched environment ledger')
            if row.get('kind') == 'terminal':
                require(report is None or report['retry_pending'], 'terminal follows a closed matched block')
                index, number = len(current), len(blocks)
                require(index < len(policy['slots']), 'matched retry has no round decision before the next terminal')
                raw = row['attempt']
                sources = raw['environment']
                require(row == _terminal(run, _work(run, number, index), policy, run_id, policy['slots'][index], number,
                                         raw['terminal'], row['process'], sources['governor_before'], sources['governor_after']),
                        'matched terminal does not reproduce the native witness')
                current.append(raw)
            else:
                require(row.get('kind') == 'round', 'unexpected matched ledger record')
                blocks.append(current)
                current = []
                report = retry.reconcile(policy, run_id, blocks)
                require(row == {'kind': 'round', 'disposition': report['attempts'][-1]},
                        'matched round disposition does not recompute from terminal evidence')
    require(not current and report is not None and not report['retry_pending'], 'matched environment block is incomplete')
    return report


def _seal(run, report):
    body = {'schema': 'bmk.matched-round-environment-seal/1', 'run_id': report['run_id'],
            'policy_id': report['policy_id'], 'files': {name: digest(run / name) for name in FILES}, **FLAGS}
    return {**body, 'seal_id': content_id(body)}


def verify(run):
    saved = load_json(run / 'completion.json')
    report = load_json(run / 'report.json')
    require(saved == _seal(run, report), 'matched environment run seal differs')
    require(report == replay(run), 'matched environment report differs from replay')
    return report


def execute(run, policy, run_id, perform_slot, *, read_governor=worker.governor_snapshot):
    """Run the frozen schedule in a new directory and persist exact attempts.

    perform_slot(slot, attempt, work) returns (verified terminal, process facts).
    Its instrumented child may leave worker-environment.stdout in work. The
    surrounding workload still owns codec/input validation and host admission.
    """
    manifest = _manifest(policy, run_id)
    run.mkdir()
    _sync_dir(run.parent)
    _publish(run / 'run.json', manifest)
    positions = {s['slot_id']: i for i, s in enumerate(policy['slots'])}
    with (run / 'ledger.jsonl').open('xb') as ledger:
        _sync_dir(run)
        pending = []

        def launch(slot, attempt):
            work = _work(run, attempt, positions[slot['slot_id']])
            work.mkdir()
            _sync_dir(run)
            before = read_governor(slot['cpu_ids'])
            terminal, process = perform_slot(slot, attempt, work)
            after = read_governor(slot['cpu_ids'])
            pending.append(_terminal(run, work, policy, run_id, slot, attempt, terminal, process, before, after, sync=True))
            return pending[0]['attempt']

        def append_attempt(row):
            entry, = pending
            require(entry['attempt'] == row, 'matched writer received a different terminal')
            _append(ledger, entry)
            pending.clear()

        report = retry.execute(policy, run_id, launch, append_attempt,
                               lambda disposition: _append(ledger, {'kind': 'round', 'disposition': disposition}))
    require(report == replay(run), 'new matched environment evidence does not independently recompute')
    _publish(run / 'report.json', report)
    _publish(run / 'completion.json', _seal(run, report))
    return report
