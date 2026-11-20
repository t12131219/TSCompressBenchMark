"""Freeze same-run Titchy packet, loaded access, and stateless range controls."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from .m3_in_run_measurement_v7 import freeze as freeze_v7

SCHEMA = 'bmk.m3-in-run-measurement/8'
TITCHY = 'titchy_independent_same_run_file_local_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v8.py', 'src/tsbench/application/m3_primary_measurement_v8.py',
        'src/tsbench/application/m3_in_run_titchy.py')


def population(items, base, routes):
    updated = dict(base)
    for i in items:
        if (i['selection'], i['route']) not in routes or i['applicability'] != 'input_domain_matches':
            continue
        key = i['work_item_id']
        require(updated[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping Titchy file-local measurement')
        updated[key] = {'status':'scheduled','adapter':TITCHY,'case_id':content_id({
            'work_item':key, 'operation_config':i['operation_config_id'], 'adapter':TITCHY})}
    return updated


def freeze(root, plan, cpu, fixed, column, pages, abi, selfstar, field, observer, array, cpus, titchy_tool):
    from ..application import m3_titchy_grouped as grouped, m3_titchy_grouped_timing as timing
    from .m3_real_corpus import TITCHY_ACCESS_DRIVER, TITCHY_ACCESS_ROUTES, TITCHY_STREAM_DRIVER, TITCHY_STREAM_ROUTE

    prior = freeze_v7(root, plan, cpu, fixed, column, pages, abi, selfstar, field, observer, array, cpus)
    routes = {**dict.fromkeys(TITCHY_ACCESS_ROUTES, TITCHY_ACCESS_DRIVER), TITCHY_STREAM_ROUTE:TITCHY_STREAM_DRIVER}
    require({(r['selection'],r['route']):r['driver'] for r in plan['routes'] if (r['selection'],r['route']) in routes} == routes and
            {r for _,r in routes} == set(grouped.ROUTES), 'Titchy timing requires three frozen native file-local routes')
    build = plan['build']; stream = build['titchy_stream']; access = build['titchy_access']; lib = stream['dependency']
    require(lib == access['dependency'], 'Titchy stream and access codec builds differ')
    for ref in (stream['executable'],access['executable'],lib):
        grouped.check(root, ref)
    tool = grouped.relative(root, local_file(root,titchy_tool))
    spec = plan_recovery(root, {}, (), tools={grouped.TOOL:{k:tool[k] for k in ('path','sha256')}}, libraries=[lib])
    native = 'lib/libtitchy_c.so'
    require(set(spec['tools']) == {grouped.TOOL} and native.rsplit('/',1)[1] in spec['files'][spec['tools'][grouped.TOOL]]['needed'] and
            all(spec['files'][native][k] == lib[k] for k in ('bytes','sha256')), 'Titchy grouped tool uses a different native library')
    code = sorted(set((*CODE, *grouped.CODE, *timing.CODE)))
    return {**prior, 'schema':SCHEMA,'population':population(plan['work_items'],prior['population'],routes),
            'titchy_grouped':{'worker':tool,'runtime':spec,'limits':grouped.LIMITS,'launchers':grouped.launcher_lock(),
                              'operations':{r:list(grouped.DIRS) for r in grouped.ROUTES},
                              'policy':{**timing.POLICY,'reference':'present_functional_row_plus_original_domain_detached_oracle'},
                              'code':{p:digest(local_file(root,p)) for p in code}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],TITCHY]}}
