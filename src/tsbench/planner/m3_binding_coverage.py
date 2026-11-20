"""Recompute M3 execution-driver coverage without claiming successful execution."""
from collections import Counter

from ..assets import require


def _obligation_ids(driver, binding):
    if driver == 'gorilla':
        groups = binding['obligation_slots']
        require(groups.keys() == {'tv-batch', 'state'}, 'M3 Gorilla specialized coverage shape differs')
        yield from groups['tv-batch']
        yield from groups['state']
    elif driver == 'huff0':
        yield from binding['required_slots']
        yield binding['condition']['obligation_id']
    else:
        yield from binding['obligation_slots']


def binding_coverage(plan):
    rows = {r['obligation_id']: r for r in plan['obligations']}
    require(len(rows) == len(plan['obligations']), 'M3 duplicate frozen obligation ID')
    bindings = {}
    for driver, binding in plan.get('specialized', {}).items():
        for oid in _obligation_ids(driver, binding):
            require(oid in rows and oid not in bindings, 'M3 duplicate or unknown specialist obligation ID')
            bindings[oid] = driver
    counts = Counter(rows[p]['kind'] for p in bindings)
    unbound = [r for p, r in rows.items() if p not in bindings]
    unbound_routes = Counter((r['route'], r['kind']) for r in unbound)
    missing = Counter(r['kind'] for r in unbound)
    kinds = ('conditional', 'required')
    require(all(counts[k] + missing[k] == plan['coverage'][f'{k}_obligations'] for k in kinds),
            'M3 frozen plan specialist count differs')
    return {'schema': 'bmk.m3-plan-driver-coverage/1', 'scope': 'plan_binding_only_not_executed_or_qualified',
            'plan_content_id': plan['plan_content_id'],
            'bound': {k: counts[k] for k in kinds}, 'unbound': {k: missing[k] for k in kinds},
            'unbound_by_route': [{'route': r, 'kind': k, 'count': n} for (r, k), n in sorted(unbound_routes.items())],
            'unbound_checks': [{k: o[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind')} for o in unbound],
            'obligation_drivers': dict(sorted(bindings.items()))}
