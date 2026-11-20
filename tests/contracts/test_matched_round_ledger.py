from pathlib import Path

import pytest

from tsbench.assets import ContractError, canonical_bytes, parse_json
from tsbench.supervisor import matched_round_ledger as ledger
from tsbench.supervisor.matched_round_retry import freeze


def freeze_test():
    return freeze('zstd-xz', [dict(slot_id=name, cpu_ids=[0]) for name in ('zstd', 'xz')], {'0': 'powersave'}, max_retries=1)


def go(_):
    return {'0': 'powersave'}


def trial(slot, n, work, *, observed=True):
    proc = {'status': 'completed', 'returncode': 0, 'session_id': f'{n}-{slot["slot_id"]}', 'pid': 1}
    budget = [0, 1] if slot['slot_id'] == 'xz' and n == 0 else [0]
    e = {'namespace_pid': 2, 'namespace_tid': 2, 'affinity': budget, 'cpu': 0}
    if observed:
        (work / ledger.WITNESS).write_bytes(canonical_bytes({'begin': e, 'end': e}) + b'\n')
    return 'verified', proc


def test_full_retry_retains_raw_witnesses_and_recomputes(tmp_path):
    run = tmp_path / 'run'
    doc = ledger.execute(run, freeze_test(), 'run', trial, read_governor=go)
    assert ledger.verify(run) == doc
    assert doc['initial_verified_slots'] == 2 and doc['policy_candidate_attempt'] == 1
    rows = [parse_json(x) for x in (run / 'ledger.jsonl').read_bytes().splitlines()]
    assert [r['kind'] for r in rows] == ['terminal', 'terminal', 'round'] * 2
    assert [r['attempt']['slot_id'] for r in rows if r['kind'] == 'terminal'] == ['zstd', 'xz'] * 2
    path = run / rows[0]['worker_witness']['path']
    path.write_bytes(path.read_bytes().replace(b'"cpu":0', b'"cpu":1'))
    with pytest.raises(ContractError, match='does not reproduce'):
        ledger.verify(run)


def test_no_seal_or_round_commit_for_interrupted_partial_attempt(tmp_path):
    run = tmp_path / 'run'

    def interrupt(slot, n, work):
        if slot['slot_id'] == 'xz':
            raise KeyboardInterrupt
        return trial(slot, n, work)

    with pytest.raises(KeyboardInterrupt):
        ledger.execute(run, freeze_test(), 'run', interrupt, read_governor=go)
    raw, = (run / 'ledger.jsonl').read_bytes().splitlines()
    assert parse_json(raw)['attempt']['slot_id'] == 'zstd'
    assert not (run / 'completion.json').exists()
    with pytest.raises(ContractError, match='incomplete'):
        ledger.replay(run)
    with pytest.raises(FileExistsError):
        ledger.execute(run, freeze_test(), 'run', trial, read_governor=go)


def test_missing_worker_witness_does_not_create_environment_candidate(tmp_path):
    run = tmp_path / 'run'
    doc = ledger.execute(run, freeze_test(), 'run', lambda s, n, w: trial(s, n, w, observed=False), read_governor=go)
    assert ledger.verify(run) == doc
    assert doc['initial_verified_slots'] == 2 and doc['policy_candidate_attempt'] is None
    assert doc['attempts'][0]['environment'] == 'incomplete_evidence' and not doc['retry_pending']
