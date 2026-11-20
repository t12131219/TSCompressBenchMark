"""Bind the accepted ZFP obligations to public ABI and isolated native fixtures."""
from . import typed_batch as typed, zfp_execution as native
from .linear_batch import MIXED_SCHEMA
from .zfp import CHECKS, plan_zfp
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits

DRIVER = 'zfp-specialized/1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 20}
SOURCES = tuple(dict.fromkeys((*typed.SOURCES, *native.SOURCES,
    'plugins/codecs/zfp-reversible/adapter.cpp', 'src/tsbench/qualification/linear_batch.py',
    'src/tsbench/application/batch_execution.py', 'src/tsbench/planner/linear_batch.py',
    'src/tsbench/planner/m3_zfp_specialized.py', 'src/tsbench/application/m3_zfp_specialized.py',
    'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py')))


def inputs(root):
    typed_slots, typed_cases = typed.typed_inputs(root, LIMITS['file_bytes'])
    baseline = {sid: entry for sid, entry in typed_slots.items() if entry[0]['method'] == typed.ZFP}
    regular = {cid: (bid, ids) for cid, (bid, ids) in typed_cases.items() if set(ids) <= baseline.keys()}
    specialist, other = native.plan_slots(root)
    require(not baseline.keys() & specialist.keys() and not regular.keys() & other.keys(), 'duplicate ZFP fixture identity')
    require(len(baseline) == 14 and len(regular) == 4 and len(specialist) == 6 and len(other) == 15,
            'ZFP fixture or obligation denominator differs')
    native.check_slots({'slots': [v[0] for v in specialist.values()], 'limits': LIMITS})
    return {**baseline, **specialist}, {**regular, **other}


def bind(root, build, obligations, corpus):
    if not corpus:
        return None
    tools = native.tool_paths(build)
    if not all((root / p).is_file() for p in tools.values()):
        return None
    products, sources = inputs(root)
    bundle, _ = plan_zfp(root)
    cases = {(x['route'], x['check']): x for x in bundle['cases']}
    by_route = {'field-baseline': typed.ZFP, **{k: k for k in native.METHODS}}
    selected = [ob for ob in obligations if ob['selection'] == 31]
    mapping, used, seen_conditions = {}, set(), 0
    require(len(selected) == 20, 'ZFP frozen obligations differ')
    for ob in selected:
        if ob['kind'] == 'conditional':
            require(native.supports_condition(ob) and
                    (ob['condition_case']['bundle_key'], ob['condition_case']['bundle_id'], ob['condition_case']['predicate']) ==
                    ('zfp', bundle['bundle_id'], 'zfp_openmp_two_threads_available'), 'ZFP condition source differs')
            slots = native.condition_slots(ob, (slot for slot, _ in products.values()))
            seen_conditions += 1
        else:
            require(ob['kind'] == 'required', 'unexpected ZFP obligation kind')
            case, = ob['planned_case_inputs']
            route, check = ob['route'], ob['check']
            require(route in CHECKS and check in CHECKS[route], 'unrecognized ZFP fixture binding')
            candidate = cases[route, check]
            cid = case['case_id']
            require(cid == candidate['case_id'] and case['case_name'] == candidate['name'] and cid in sources and
                    cid not in used and case['bundle_key'] == 'zfp_cases' and case['bundle_id'] == sources[cid][0],
                    'ZFP fixture case differs from the accepted definition')
            used.add(cid)
            slots = sources[cid][1]
        require(slots and all(products[sid][0]['method'] == by_route[ob['route']] for sid in slots),
                'ZFP obligation landed on a different native route')
        mapping[ob['obligation_id']] = slots
    require(seen_conditions == 1 and len(mapping) == 20 and used == sources.keys() and
            set().union(*mapping.values()) == products.keys(), 'ZFP specialist coverage differs')
    validate_limits(LIMITS)
    tool_refs = {name: {'path': path.as_posix(), 'sha256': digest(local_file(root, path.as_posix()))}
                 for name, path in tools.items()}
    methods = {typed.ZFP: typed.METHODS[typed.ZFP]}
    closure = plan_recovery(root, build, methods, tools=tool_refs)
    require(closure['files']['lib/libzfp_native_c.so']['sha256'] == corpus['dependency']['sha256'] and
            all('libzfp_native_c.so' in closure['files'][rel]['needed'] for rel in closure['tools'].values()),
            'ZFP specialized controls and corpus must use the same locked native CPU library')
    return {'driver': DRIVER, 'schema': MIXED_SCHEMA, 'methods': methods, 'decoder': closure,
            'direct_control': {'tool_refs': tool_refs}, 'limits': dict(LIMITS), 'launchers': launcher_lock(),
            'obligation_slots': mapping, 'slots': {sid: slot for sid, (slot, _) in products.items()},
            'code': {path: digest(local_file(root, path)) for path in SOURCES}}
