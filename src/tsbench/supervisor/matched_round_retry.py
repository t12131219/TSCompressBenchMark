"""Predeclared interference/retry protocol for a matched comparison block.

This is a scheduler component, not host reservation or timing admission.  It
requires affirmative environment evidence; slow or failing methods never, by
themselves, cause a retry.  Neither round outcomes nor observations are edited.
"""
from ..assets import content_id, require

SCHEMA = 'bmk.matched-round-retry/1'
FLAGS = ('timing_admitted', 'qualification_granted', 'stage_accepted')


def _valid_cpu(cpu):
    return type(cpu) is int and cpu >= 0


def _ids(ids):
    return type(ids) is list and all(_valid_cpu(cpu) for cpu in ids) and ids == sorted(set(ids))


def freeze(block_id, schedule, governors, *, max_retries):
    """Bind ordered (already randomized) slots and expected governor per CPU."""
    require(isinstance(block_id, str) and bool(block_id) and type(max_retries) is int and 0 <= max_retries <= 2,
            'invalid matched block or retry cap')
    require(isinstance(schedule, list) and schedule, 'matched block has no ordered schedule')
    slots = []
    for slot in schedule:
        require(set(slot) == {'slot_id', 'cpu_ids'} and isinstance(slot['slot_id'], str) and slot['slot_id'] and
                _ids(slot['cpu_ids']) and slot['cpu_ids'], 'invalid matched slot identity or CPU set')
        slots.append({'slot_id': slot['slot_id'], 'cpu_ids': list(slot['cpu_ids'])})
    require(len({s['slot_id'] for s in slots}) == len(slots), 'duplicate matched slot identity')
    cpu_keys = {str(cpu) for s in slots for cpu in s['cpu_ids']}
    require(isinstance(governors, dict) and governors.keys() == cpu_keys and all(isinstance(v, str) and v and v.isascii() for v in governors.values()),
            'a governor expectation is required on every planned CPU')
    body = {'schema': SCHEMA, 'block_id': block_id, 'slots': slots, 'governors': dict(sorted(governors.items())),
            'max_retries': max_retries, 'session_policy': 'fresh_process_per_slot_per_attempt', 'retry_rule': 'positive_environment_interference_only_entire_block',
            'selection_rule': 'first_fully_observed_clean_and_verified_block_never_mix_attempts'}
    return {**body, 'policy_id': content_id(body)}


def check(policy):
    require(policy == freeze(policy['block_id'], policy['slots'], policy['governors'], max_retries=policy['max_retries']),
            'matched retry policy differs from frozen policy')


def _signals(policy, slot, obs):
    require(set(obs) == {'affinity', 'observed_cpus', 'governor_before', 'governor_after'},
            'matched attempt must record evidence or explicit null')
    positive, missing = [], []
    planned = set(slot['cpu_ids'])
    for key in ('affinity', 'observed_cpus'):
        seq = obs[key]
        require(seq is None or _ids(seq) and seq, 'invalid matched attempt CPU evidence')
        if seq is None:
            missing.append(key)
        elif key == 'affinity' and set(seq) != planned:
            positive.append('worker_affinity_differs_from_frozen_budget')
        elif key == 'observed_cpus' and not set(seq) <= planned:
            positive.append('worker_observed_outside_frozen_budget')
    cpu_keys = {str(cpu) for cpu in planned}
    for when in ('governor_before', 'governor_after'):
        governors = obs[when]
        require(governors is None or isinstance(governors, dict) and governors.keys() <= cpu_keys, 'governor observation includes foreign CPU')
        for cpu in sorted(cpu_keys):
            g = None if governors is None else governors.get(cpu)
            require(g is None or isinstance(g, str) and g, 'invalid governor observation')
            if g is None:
                missing.append(f'{when}:{cpu}')
            elif g != policy['governors'][cpu]:
                positive.append(f'{when}:{cpu}:policy_mismatch')
    return positive, missing


def _attempt(policy, number, rows, sessions, run_id):
    require(len(rows) == len(policy['slots']), 'partial or extra slots in matched attempt')
    slot_results = []
    for slot, row in zip(policy['slots'], rows, strict=True):
        require(set(row) == {'policy_id', 'run_id', 'slot_id', 'attempt', 'terminal', 'session_id', 'environment'} and
                row['policy_id'] == policy['policy_id'] and row['run_id'] == run_id and row['slot_id'] == slot['slot_id'] and
                type(row['attempt']) is int and row['attempt'] == number and isinstance(row['terminal'], str) and
                row['terminal'], 'matched attempt coordinate, order or terminal differs')
        sid = row['session_id']
        require(sid is None or isinstance(sid, str) and sid and sid not in sessions, 'matched attempt reuses a session')
        require(row['terminal'] != 'verified' or sid is not None, 'verified matched attempt has no process session')
        if sid is not None:
            sessions.add(sid)
        pos, missing = _signals(policy, slot, row['environment'])
        require(sid is not None or row['environment']['affinity'] is None and row['environment']['observed_cpus'] is None,
                'cannot observe worker affinity without a process session')
        slot_results.append({'slot_id': slot['slot_id'], 'terminal': row['terminal'],
                             'positive_environment_signals': pos, 'missing_environment_signals': missing})
    dirty = any(s['positive_environment_signals'] for s in slot_results)
    missing = any(s['missing_environment_signals'] for s in slot_results)
    all_verified = all(s['terminal'] == 'verified' for s in slot_results)
    return {'attempt': number, 'slots': slot_results, 'environment': ('interference_observed' if dirty else
             'incomplete_evidence' if missing else 'no_declared_signal_observed'), 'all_verified': all_verified,
            'policy_candidate': not dirty and not missing and all_verified,
            'retry_whole_block': dirty and number < policy['max_retries']}


def reconcile(policy, run_id, attempts):
    """Check the exact attempt sequence and preserve first-attempt outcomes."""
    check(policy)
    require(isinstance(run_id, str) and run_id and attempts, 'no matched attempts to reconcile')
    results, sessions = [], set()
    for n, rows in enumerate(attempts):
        require(not results or results[-1]['retry_whole_block'], 'unjustified or excess matched retry')
        results.append(_attempt(policy, n, rows, sessions, run_id))
    last = results[-1]
    return {'policy_id': policy['policy_id'], 'run_id': run_id, 'attempts': results,
            'initial_verified_slots': sum(s['terminal'] == 'verified' for s in results[0]['slots']),
            'final_verified_slots': sum(s['terminal'] == 'verified' for s in last['slots']),
            'policy_candidate_attempt': last['attempt'] if last['policy_candidate'] else None,
            'retry_pending': last['retry_whole_block'], **dict.fromkeys(FLAGS, False)}


def execute(policy, run_id, perform_slot, append_attempt, append_decision):
    """Execute full attempts in frozen order using caller-owned I/O and ledger.

    perform_slot returns one terminal record. append_attempt persists raw
    records before append_decision persists the derived round disposition. An
    interrupted caller leaves partial evidence; it cannot invent a completion.
    """
    check(policy)
    require(isinstance(run_id, str) and run_id, 'invalid matched run ID')
    attempts, sessions = [], set()
    for number in range(policy['max_retries'] + 1):
        rows = []
        for slot in policy['slots']:
            row = perform_slot({'slot_id': slot['slot_id'], 'cpu_ids': list(slot['cpu_ids'])}, number)
            append_attempt(row)
            rows.append(row)
        attempts.append(rows)
        disposition = _attempt(policy, number, rows, sessions, run_id)
        append_decision(disposition)
        if not disposition['retry_whole_block']:
            break
    return reconcile(policy, run_id, attempts)
