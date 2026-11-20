from copy import deepcopy

import pytest

from tsbench.assets import ContractError
from tsbench.supervisor.matched_round_retry import execute, freeze, reconcile


def policy(cap=1):
    return freeze('file-methods-round-0', [{'slot_id': 'zstd', 'cpu_ids': [4, 6]}, {'slot_id': 'xz', 'cpu_ids': [4, 6]}],
                  {'4': 'performance', '6': 'performance'}, max_retries=cap)


def row(p, slot, n, terminal='verified'):
    governors = p['governors'].copy()
    return {'policy_id': p['policy_id'], 'run_id': 'run', 'slot_id': slot['slot_id'], 'attempt': n,
            'terminal': terminal, 'session_id': f"{slot['slot_id']}:{n}",
            'environment': {'affinity': [4, 6], 'observed_cpus': [4],
                            'governor_before': governors, 'governor_after': governors.copy()}}


def test_scheduler_repeats_the_entire_frozen_order_and_retains_first_crash():
    p = policy()
    saved, raw = [], []

    def perform(slot, n):
        x = row(p, slot, n)
        if n == 0 and slot['slot_id'] == 'xz':
            x['environment']['governor_after']['6'] = 'powersave'
            x['terminal'] = 'crash'
        return x

    out = execute(p, 'run', perform, raw.append, lambda x: saved.append((len(raw), x)))
    assert [(r['slot_id'], r['attempt']) for r in raw] == [('zstd', 0), ('xz', 0), ('zstd', 1), ('xz', 1)]
    assert [(n, r['retry_whole_block']) for n, r in saved] == [(2, True), (4, False)]
    assert out['initial_verified_slots'] == 1 and out['final_verified_slots'] == 2
    assert out['policy_candidate_attempt'] == 1 and not out['timing_admitted']
    assert out == reconcile(p, 'run', [raw[:2], raw[2:]])


@pytest.mark.parametrize('terminal', ['timeout', 'crash', 'unsupported_configuration', 'calibration_not_reached', 'quality_rejected'])
def test_failure_without_affirmative_environment_signal_cannot_retry(terminal):
    p = policy()
    initial = [row(p, s, 0, terminal=terminal) for s in p['slots']]
    initial[0]['environment']['governor_after']['6'] = None
    result = reconcile(p, 'run', [initial])
    assert result['attempts'][0]['environment'] == 'incomplete_evidence'
    assert not result['retry_pending'] and result['policy_candidate_attempt'] is None
    with pytest.raises(ContractError, match='unjustified'):
        reconcile(p, 'run', [initial, [row(p, s, 1) for s in p['slots']]])


def test_missing_evidence_is_not_clean_even_when_all_slots_verified():
    p = policy()
    first = [row(p, s, 0) for s in p['slots']]
    first[0]['environment']['observed_cpus'] = None
    report = reconcile(p, 'run', [first])
    assert report['initial_verified_slots'] == 2 and report['policy_candidate_attempt'] is None


def test_retry_cannot_skip_slots_reuse_sessions_or_mix_runs():
    p = policy()
    first = [row(p, s, 0) for s in p['slots']]
    first[0]['environment']['observed_cpus'] = [9]
    subsequent = [row(p, s, 1) for s in p['slots']]
    assert reconcile(p, 'run', [first])['retry_pending']
    with pytest.raises(ContractError, match='partial'):
        reconcile(p, 'run', [first, subsequent[:1]])
    bad = deepcopy(subsequent)
    bad[0]['session_id'] = first[0]['session_id']
    with pytest.raises(ContractError, match='reuses a session'):
        reconcile(p, 'run', [first, bad])
    subsequent[0]['run_id'] = 'foreign'
    with pytest.raises(ContractError, match='coordinate'):
        reconcile(p, 'run', [first, subsequent])
