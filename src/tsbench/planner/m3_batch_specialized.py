"""Bind the M0 standalone/page and legacy batch cases to M3's native build."""
from ..assets import digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock, validate_limits
from . import linear_batch as linear, pcodec_batch as pco, pcodec_pages as pages, xz_batch as xz
from .lzbench import plan_lzbench
from .method_boundaries import plan_boundary_cases
from .pcodec import plan_pcodec

PCODEC = 'pcodec_auto_pages'
LZBENCH = 'lzbench_baseline'
FAMILIES = {
    PCODEC: ('pcodec-auto-pages-specialized/1', pco.ROUTES | pages.ROUTES, 23, 28, linear.EXTENDED_WRAPPED),
    LZBENCH: ('lzbench-baseline-specialized/1', {(40, 'zstd-baseline'): 'zstd', (39, 'xz-baseline'): xz.METHOD},
              11, 14, linear.EXTENDED_XZ),
}
FILES = ('src/tsbench/planner/m3_batch_specialized.py', 'src/tsbench/application/m3_batch_specialized.py',
         'src/tsbench/application/batch_execution.py', 'src/tsbench/planner/linear_batch.py',
         'src/tsbench/qualification/linear_batch.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py')


def inputs(root, family):
    if family == PCODEC:
        batch, refs = pco.pcodec_inputs(root)
        wrapped, more = pages.pcodec_page_inputs(root)
        require(not batch.keys() & wrapped.keys() and not refs.keys() & more.keys(), 'pcodec case or product collision')
        return batch | wrapped, refs | more
    require(family == LZBENCH, 'invalid M3 batch family')
    products, refs = linear.linear_inputs(root, 1 << 20)
    zstd = {sid: pair for sid, pair in products.items() if pair[0]['method'] == 'zstd'}
    refs = {cid: ref for cid, ref in refs.items() if all(p in zstd for p in ref[1])}
    products, more = xz.xz_inputs(root)
    require(not zstd.keys() & products.keys() and not refs.keys() & more.keys(), 'legacy batch case or product collision')
    return zstd | products, refs | more


def _declared(root, family):
    if family == PCODEC:
        bundle, _ = plan_pcodec(root)
        bundles = ((bundle, 'pcodec_cases'),)
    else:
        bundles = ((plan_lzbench(root), 'lzbench_cases'), (plan_boundary_cases(root)[0], 'bound_development_cases'))
    wanted = FAMILIES[family][1]
    return {c['case_id']: (bundle['bundle_id'], key, c.get('name') or c['row']['case'],
                           c['selection'], c['route'], c.get('check'))
            for bundle, key in bundles for c in bundle['cases'] if (c['selection'], c['route']) in wanted}


def _obligations(obligations, family, products, refs, declared):
    _, routes, count, slots, _ = FAMILIES[family]
    seen, mapping = set(), {}
    for ob in obligations:
        key = ob['selection'], ob['route']
        if key not in routes:
            continue
        require(ob['kind'] == 'required' and ob['planned_case_inputs'] and ob['obligation_id'] not in mapping,
                'invalid M3 batch specialist obligation')
        ids = []
        for ref in ob['planned_case_inputs']:
            cid = ref['case_id']
            require(cid not in seen and cid in refs and cid in declared, 'unknown or reused M3 batch frozen case')
            did, bundle, name, selection, route, check = declared[cid]
            require((ref['bundle_id'], ref['bundle_key'], ref['case_name'], *key) == (did, bundle, name, selection, route) and
                    refs[cid][0] == did and (check is None or check == ob['check']), 'M3 batch frozen case identity differs')
            ids.extend(refs[cid][1])
            seen.add(cid)
        require(all(products[p][0]['method'] == routes[key] for p in ids), 'M3 batch frozen case uses the wrong route')
        mapping[ob['obligation_id']] = {'selection': key[0], 'route': key[1], 'check': ob['check'],
                                       'case_inputs': ob['planned_case_inputs'], 'slots': list(dict.fromkeys(ids))}
    require(len(mapping) == count and len(products) == slots and seen == refs.keys() == declared.keys() and
            set().union(*(r['slots'] for r in mapping.values())) == products.keys(), 'M3 batch specialist coverage differs')
    return mapping


def bind(root, build, obligations, family, corpus):
    if corpus is None:
        return None
    driver, _, _, _, suite = FAMILIES[family]
    if family == PCODEC:
        paths = {pco.TOOL: linear._pcodec_path(build), pages.TOOL: linear._pcodec_path(build, pages.TARGET)}
        methods, protocol = pco.METHODS, pages.METHODS
        dependency = 'libpcodec_c.so'
        sources = (*pco.SOURCES, *pages.SOURCES)
    else:
        paths = {linear.ZSTD_TOOL: linear._control_path(build), xz.TOOL: linear._xz_path(build)}
        methods, protocol = {'zstd': linear.METHODS['zstd'], xz.METHOD: {'plugin': xz.METHOD, 'options': {}}}, {}
        dependency = 'liblzbench_native.so'
        sources = (*xz.SOURCES, linear.ZSTD_SOURCE, 'src/tsbench/planner/lzbench.py', 'src/tsbench/qualification/lzbench.py')
    if not all((root / p).is_file() for p in paths.values()):
        return None
    limits = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 10}
    validate_limits(limits)
    products, refs = inputs(root, family)
    mapping = _obligations(obligations, family, products, refs, _declared(root, family))
    tools = {k: {'path': p.as_posix(), 'sha256': digest(local_file(root, p.as_posix()))} for k, p in paths.items()}
    closure = plan_recovery(root, build, methods, tools=tools)
    lib = closure['files']['lib/' + dependency]
    require((lib['source'], lib['bytes'], lib['sha256']) == tuple(corpus['dependency'][k] for k in ('path', 'bytes', 'sha256')) and
            all(dependency in closure['files'][p]['needed'] for p in (*closure['tools'].values(), *closure['plugins'].values())),
            'M3 batch specialist does not share the frozen native corpus library')
    if family == PCODEC:
        require(tools[pages.TOOL]['sha256'] == corpus['executable']['sha256'], 'M3 native pages executable changed')
    return {'driver': driver, 'family': family, 'schema': linear.MIXED_SCHEMA, 'suite': suite, 'methods': methods,
            'protocol_methods': protocol, 'decoder': closure, 'direct_control': {'tool_refs': tools},
            'limits': limits, 'launchers': launcher_lock(), 'obligation_slots': mapping,
            'slots': {p: s for p, (s, _) in products.items()},
            'code': {p: digest(local_file(root, p)) for p in (*FILES, *sources)}}
