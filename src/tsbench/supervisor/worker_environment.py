"""Collect governor witnesses and project real worker endpoint evidence.

The caller binds the worker-owned structured record to one supervised session.
A PID inside the worker namespace is deliberately not compared to a wrapper PID.
"""
from pathlib import Path
import re

from ..assets import require

SYS_CPU = Path('/sys/devices/system/cpu')
SCOPE = 'calling_native_worker_thread_endpoints_not_continuous_or_all_worker_threads'


def _cpu(cpu):
    return type(cpu) is int and 0 <= cpu < 131072


def _cpus(ids):
    return type(ids) is list and bool(ids) and all(_cpu(c) for c in ids) and ids == sorted(set(ids))


def governor_snapshot(cpus, *, sys_cpu=SYS_CPU):
    """Read observed settings, never set them and never supply a default."""
    require(_cpus(cpus), 'invalid CPU set for governor observation')
    states = {}
    for cpu in cpus:
        try:
            value = (sys_cpu / f'cpu{cpu}' / 'cpufreq' / 'scaling_governor').read_text(encoding='ascii').strip()
        except (OSError, UnicodeError):
            value = None
        states[str(cpu)] = value if value and re.fullmatch(r'[a-zA-Z0-9_-]+', value) else None
    return states


def _endpoint(value):
    if value is None:
        return None
    require(type(value) is dict and value.keys() == {'namespace_pid', 'namespace_tid', 'cpu', 'affinity'} and
            all(type(value[n]) is int and value[n] > 0 for n in ('namespace_pid', 'namespace_tid')) and
            (value['cpu'] is None or _cpu(value['cpu'])) and (value['affinity'] is None or _cpus(value['affinity'])),
            'malformed native worker endpoint witness')
    # Do not require cpu in affinity: a transition between the two syscalls can
    # be real. Preserve both observed facts; policy compares each to the budget.
    return value


def project(cpus, checkpoints, governor_before, governor_after, *, session_id):
    """Produce retry-policy input without backfilling missing worker evidence.

    With partial observations, a witnessed violation is still a violation, but
    the observations that happen to agree with the plan never prove completeness.
    Keep the raw observations beside the policy input for independent audit.
    """
    require(_cpus(cpus) and set(checkpoints) == {'begin', 'end'}, 'invalid worker evidence coordinates')
    require(session_id is None or isinstance(session_id, str) and session_id, 'invalid worker evidence session')
    begin, end = (_endpoint(checkpoints[k]) for k in ('begin', 'end'))
    samples = [row for row in (begin, end) if row is not None]
    require(not samples or session_id is not None, 'worker evidence has no supervised session')
    require(len({(r['namespace_pid'], r['namespace_tid']) for r in samples}) <= 1,
            'native worker endpoints are from different threads or processes')
    masks = [r['affinity'] for r in samples if r['affinity'] is not None]
    seen = [r['cpu'] for r in samples if r['cpu'] is not None]
    divergent = next((mask for mask in masks if mask != cpus), None)
    budget = set(cpus)
    affinity = divergent if divergent is not None else masks[0] if len(masks) == 2 else None
    observed = sorted(set(seen)) if len(seen) == 2 or set(seen) - budget else None
    return {'scope': SCOPE, 'session_id': session_id, 'checkpoints': {'begin': begin, 'end': end},
            'retry_environment': {'affinity': affinity, 'observed_cpus': observed,
                                  'governor_before': governor_before, 'governor_after': governor_after}}
