"""Bind every named CORAD obligation to its frozen same-run product."""
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import corad_execution as inference
from . import corad_training_execution as training
from .corad_corpus import INFERENCE, SOURCE
from .m3_corad import METHOD, ROUTES

DRIVER = 'corad-specialized/1'
LIMITS = {'address_space_bytes': 128 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 10}
SOURCES = (*inference.SOURCES, *training.SOURCES,
           'src/tsbench/planner/m3_corad_specialized.py', 'src/tsbench/application/m3_corad_specialized.py',
           'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py')


def route(slot):
    return INFERENCE if inference.is_corad(slot) else slot['method']


def fixture_inputs(root):
    slots, cases = inference.plan_slots(root)
    more, extra = training.plan_slots(root)
    require(not slots.keys() & more.keys() and not cases.keys() & extra.keys(), 'CORAD specialist slot or case collision')
    return slots | more, cases | extra


def bind_obligations(obligations, slots, cases):
    declared = {}
    for spec in slots.values():
        bundle = spec['bundle']
        for case in bundle['cases']:
            if case['route'] != route(spec):
                continue
            cid = case['case_id']
            require(cid not in declared, 'duplicate CORAD specialist case')
            key = 'corad_inference_cases' if inference.is_corad(spec) else 'corad_training_cases'
            declared[cid] = (case, key, bundle['bundle_id'])
    mapping, seen = {}, set()
    for ob in obligations:
        if (ob['selection'], ob['route']) not in ROUTES:
            continue
        refs = ob.get('planned_case_inputs')
        require(ob['kind'] == 'required' and refs, 'unbound CORAD specialist obligation')
        product_ids = set()
        for r in refs:
            cid = r['case_id']
            require(cid in declared and cid in cases and cid not in seen, 'CORAD specialist case is unknown or reused')
            case, key, bundle_id = declared[cid]
            members = cases[cid][1]
            require((r['case_name'], r['bundle_key'], r['bundle_id'], ob['route'], ob['check']) ==
                    (case['name'], key, bundle_id, case['route'], case['check']) and
                    bundle_id == cases[cid][0] and len(members) == 1 and route(slots[members[0]]) == ob['route'],
                    'CORAD specialist case binding differs from the M0 definition')
            seen.add(cid)
            product_ids.update(members)
        require(len(product_ids) == 1 and ob['obligation_id'] not in mapping, 'CORAD obligation does not bind exactly one product slot')
        mapping[ob['obligation_id']] = {'route': ob['route'], 'check': ob['check'], 'case_inputs': refs,
                                       'fixture_slot': next(iter(product_ids))}
    require(len(mapping) == 17 and len(seen) == 20 and seen == declared.keys() == cases.keys() and
            {v['fixture_slot'] for v in mapping.values()} == slots.keys(), 'CORAD specialist denominator differs')
    return mapping


def bind(root, build, obligations, corpus):
    paths = {inference.TOOL: inference.tool_path(build).as_posix(), training.TOOL: training.tool_path(build).as_posix()}
    if corpus is None or not all((root/path).is_file() for path in paths.values()):
        return None
    tools = {name: {'path': path, 'sha256': digest(local_file(root, path))} for name, path in paths.items()}
    decoder = plan_recovery(root, build, [METHOD], tools=tools)
    require(decoder['files']['lib/libcorad_c.so'] == corpus['decoder']['files']['lib/libcorad_c.so'] and
            all('libcorad_c.so' in decoder['files'][p]['needed']
                for p in (*decoder['tools'].values(), decoder['plugins'][METHOD])),
            'CORAD specialist and corpus native libraries differ')
    fixtures, cases = fixture_inputs(root)
    slots = {p: s for p, (s, _) in fixtures.items()}
    config = {'slots': list(slots.values()), 'limits': LIMITS}
    inference.check_slots(config)
    training.check_slots(config)
    for limits in (inference.limit(config), training.limits(config), training.limits(config, training.PYTHON)):
        validate_limits(limits)
    source, = [s for s in slots.values() if s['method'] == SOURCE]
    require(source['source_runtime'] == corpus['source_runtime'] and
            source['bundle']['bridge_sha256'] == corpus['source_bridge_sha256'] and
            source['bundle']['archive_sha256'] == corpus['source_archive_sha256'], 'CORAD specialist and corpus Source identities differ')
    return {'driver': DRIVER, 'decoder': decoder, 'limits': LIMITS, 'launchers': launcher_lock(), 'slots': slots,
            'obligation_slots': bind_obligations(obligations, slots, cases),
            'code': {p: digest(local_file(root, p)) for p in SOURCES}}
