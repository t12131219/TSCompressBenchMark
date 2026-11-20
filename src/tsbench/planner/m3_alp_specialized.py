"""Bind the frozen ALP batch and backend obligations to the same native build."""
from collections import Counter

from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import alp_decode as backend, linear_batch as batch
from .alp import METHOD, plan_alp
from .method_boundaries import plan_boundary_cases
from .native_conditions import CONDITIONS

DRIVER = 'alp-specialized/1'
ROUTES = {(9, 'auto-batch'), backend.ROUTE}
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 20}
SOURCES = (*backend.SOURCES, batch.FENV_SOURCE, 'src/tsbench/planner/alp.py',
           'src/tsbench/planner/linear_batch.py', 'src/tsbench/qualification/alp_wire.py',
           'src/tsbench/qualification/linear_batch.py', 'src/tsbench/application/batch_execution.py',
           'src/tsbench/planner/m3_alp_specialized.py', 'src/tsbench/application/m3_alp_specialized.py',
           'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py')


def route(slot):
    return backend.ROUTE[1] if backend.is_decode(slot) else 'auto-batch'


def inputs(root):
    all_linear, refs = batch.linear_inputs(root, LIMITS['file_bytes'])
    abi = {p: entry for p, entry in all_linear.items() if entry[0]['method'] == METHOD}
    direct, direct_refs = backend.plan_slots(root)
    refs = {cid: ref for cid, ref in refs.items() if all(p in abi for p in ref[1])}
    require(len(abi) == 15 and len(direct) == 9 and not abi.keys() & direct.keys() and
            len(refs) == 11 and len(direct_refs) == 4 and not refs.keys() & direct_refs.keys(),
            'ALP specialist product or case denominator differs')
    products = abi | direct
    backend.check_slots({'slots': [s for s, _ in products.values()], 'limits': LIMITS})
    return products, refs | direct_refs


def bind(root, build, obligations):
    if METHOD not in build['plugins']:
        return None
    paths = {batch.FENV_TOOL: batch._fenv_path(build), backend.TOOL: backend.tool_path(build)}
    if not all((root / p).is_file() for p in paths.values()):
        return None
    validate_limits(LIMITS)
    products, sources = inputs(root)
    boundary, _ = plan_boundary_cases(root)
    alp, _ = plan_alp(root)
    cases = {c['case_id']: ('bound_development_cases', boundary['bundle_id'], c['row']['case'], c['route'], None)
             for c in boundary['cases'] if c['selection'] == 9}
    cases.update({c['case_id']: ('alp_cases', alp['bundle_id'], c['name'], c['route'], c['check']) for c in alp['cases']})
    mapping, seen = {}, set()
    for ob in obligations:
        if (ob['selection'], ob['route']) not in ROUTES:
            continue
        key, check, kind = ob['route'], ob['check'], ob['kind']
        if kind == 'conditional':
            c = ob['condition_case']
            required, bundle_key, selector, criteria = CONDITIONS[9, key, c['predicate']]
            require((c['bundle_key'], c['bundle_id'], c['selector'], c['criteria'], c['required_observation']) ==
                    (bundle_key, alp['bundle_id'], selector, criteria, required) and required == check,
                    'ALP same-run condition differs from the frozen definition')
            slots = backend.condition_slots(ob, (s for s, _ in products.values()))
            source = {'condition': c}
        else:
            require(kind == 'required' and ob['planned_case_inputs'], 'unexpected ALP specialist obligation')
            slots = []
            for r in ob['planned_case_inputs']:
                cid = r['case_id']
                require(cid in sources and cid in cases and cid not in seen, 'ALP case is unknown or reused')
                bundle_key, bid, name, case_route, case_check = cases[cid]
                require((r['bundle_key'], r['bundle_id'], r['case_name'], key) == (bundle_key, bid, name, case_route) and
                        sources[cid][0] == bid and (case_check is None or case_check == check), 'ALP case binding differs')
                seen.add(cid)
                slots.extend(sources[cid][1])
            source = {'case_inputs': ob['planned_case_inputs']}
        require(ob['obligation_id'] not in mapping and slots and len(slots) == len(set(slots)) and
                all(route(products[p][0]) == key for p in slots), 'ALP specialist route or slot differs')
        mapping[ob['obligation_id']] = {'route': key, 'check': check, 'kind': kind, 'slots': slots, **source}
    require(Counter(r['kind'] for r in mapping.values()) == {'required': 12, 'conditional': 2} and
            seen == cases.keys() == sources.keys() and set().union(*(r['slots'] for r in mapping.values())) == products.keys(),
            'ALP specialist obligation coverage differs')
    fenv, = (r for r in mapping.values() if r['check'] == batch.FENV_CHECK)
    p, = fenv['slots']
    require(products[p][0]['original']['columns'] == [{'dtype': 10, 'count': 1029}], 'ALP rounding input differs')
    tools = {name: {'path': p.as_posix(), 'sha256': digest(local_file(root, p.as_posix()))} for name, p in paths.items()}
    methods = {METHOD: batch.METHODS[METHOD]}
    closure = plan_recovery(root, build, methods, tools=tools)
    require(all('libalp_native.so' in closure['files'][p]['needed'] for p in
                (*closure['tools'].values(), closure['plugins'][METHOD])), 'ALP controls do not share the ABI native library')
    return {'driver': DRIVER, 'schema': batch.MIXED_SCHEMA, 'methods': methods, 'decoder': closure,
            'direct_control': {'tool_refs': tools}, 'limits': dict(LIMITS), 'launchers': launcher_lock(),
            'obligation_slots': mapping, 'obligation_bindings': {batch.FENV_CHECK: {'product_slots': [p]}},
            'slots': {p: s for p, (s, _) in products.items()},
            'code': {p: digest(local_file(root, p)) for p in SOURCES}}
