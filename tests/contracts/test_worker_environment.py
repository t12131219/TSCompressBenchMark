import pytest

from tsbench.assets import ContractError
from tsbench.supervisor import matched_round_retry as retry
from tsbench.supervisor.worker_environment import governor_snapshot, project


def endpoint(*, cpu=4, mask=None, pid=2, tid=2):
    return {'cpu': cpu, 'affinity': [4, 6] if mask is None else mask, 'namespace_pid': pid, 'namespace_tid': tid}


def report(checkpoints):
    slot = {'slot_id': 'cold', 'cpu_ids': [4, 6]}
    governors = {'4': 'powersave', '6': 'powersave'}
    policy = retry.freeze('block', [slot], governors, max_retries=1)
    env = project(slot['cpu_ids'], checkpoints, governors, governors, session_id='external-session')
    row = {'policy_id': policy['policy_id'], 'run_id': 'run', 'slot_id': slot['slot_id'], 'attempt': 0,
           'terminal': 'verified', 'session_id': env['session_id'], 'environment': env['retry_environment']}
    return retry.reconcile(policy, 'run', [[row]])


def test_governor_snapshot_keeps_unavailable_and_invalid_entries(tmp_path):
    path = tmp_path / 'cpu4/cpufreq/scaling_governor'
    path.parent.mkdir(parents=True)
    path.write_text('powersave\n')
    assert governor_snapshot([4, 6], sys_cpu=tmp_path) == {'4': 'powersave', '6': None}
    path.write_text('bogus setting\n')
    assert governor_snapshot([4], sys_cpu=tmp_path) == {'4': None}


def test_normalizes_real_endpoints_without_conflating_inside_budget_migration():
    r = report({'begin': endpoint(), 'end': endpoint(cpu=6)})
    assert r['policy_candidate_attempt'] == 0 and not r['timing_admitted']
    r = report({'begin': endpoint(), 'end': None})
    assert r['policy_candidate_attempt'] is None and not r['retry_pending']
    assert r['attempts'][0]['slots'][0]['missing_environment_signals'] == ['affinity', 'observed_cpus']


def test_keeps_observed_violation_even_with_one_missing_checkpoint():
    r = report({'begin': endpoint(cpu=9, mask=[4, 6, 9]), 'end': None})
    assert r['retry_pending'] and r['policy_candidate_attempt'] is None
    assert r['attempts'][0]['slots'][0]['positive_environment_signals'] == [
        'worker_affinity_differs_from_frozen_budget', 'worker_observed_outside_frozen_budget']


def test_affinity_change_between_endpoints_cannot_be_hidden_by_clean_start():
    r = report({'begin': endpoint(), 'end': endpoint(mask=[4])})
    assert r['retry_pending']
    with pytest.raises(ContractError, match='different threads'):
        report({'begin': endpoint(), 'end': endpoint(tid=3)})
    with pytest.raises(ContractError, match='no supervised session'):
        project([4, 6], {'begin': endpoint(), 'end': None}, None, None, session_id=None)
