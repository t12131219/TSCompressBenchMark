"""Freeze same-run reversible and fixed-rate ZFP measurement controls."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .m3_in_run_measurement_v6 import freeze as freeze_v6

SCHEMA = 'bmk.m3-in-run-measurement/7'
ZFP = 'zfp_independent_same_run_fields_and_array_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v7.py', 'src/tsbench/application/m3_primary_measurement_v7.py',
        'src/tsbench/application/m3_in_run_zfp.py', 'src/tsbench/application/m3_zfp_field_timing.py',
        'src/tsbench/application/m3_zfp_array_timing.py', 'src/tsbench/application/m3_zfp.py',
        'src/tsbench/application/m3_lzbench_timing.py', 'src/tsbench/supervisor/zfp_array_grouped.py',
        'src/tsbench/supervisor/zfp_field_grouped.py',
        *(f'native/measurement/zfp_field_grouped/{n}' for n in ('main.cpp', 'observe.cpp', 'CMakeLists.txt')),
        *(f'native/measurement/zfp_array_grouped/{n}' for n in ('main.cpp', 'CMakeLists.txt')))


def population(items, base, routes):
    result = dict(base)
    for i in items:
        if i['selection'] != 31 or i['route'] not in routes or i['applicability'] != 'input_domain_matches':
            continue
        key = i['work_item_id']
        require(result[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping ZFP measurement')
        result[key] = {'status': 'scheduled', 'adapter': ZFP, 'case_id': content_id({
            'work_item': key, 'operation_config': i['operation_config_id'], 'adapter': ZFP})}
    return result


def freeze(root, plan, cpu, fixed, column, pages, abi_worker, selfstar_worker, field_tool, observer, array_tool, field_cpus):
    from ..application import m3_zfp_field_timing as field, m3_zfp_array_timing as array
    from ..application.m3_in_run_zfp import SEED

    prior = freeze_v6(root, plan, cpu, fixed, column, pages, abi_worker, selfstar_worker)
    routes = (*field.ROUTES, array.ROUTE)
    require(set(routes) == {r['route'] for r in plan['routes'] if r['selection'] == 31 and r['driver'] == field.DRIVER},
            'ZFP timing requires all four frozen routes')
    bound = plan['build']['zfp_corpus']; lib = bound['dependency']
    for ref in (bound['executable'], lib):
        field._file(root, ref)
    spec = {}
    for k, module, names, expected_tools in (
            ('field', field, {'timing': field_tool, 'observer': observer}, field.launch.TOOLS),
            ('array', array, {array.launch.NAME: array_tool}, {array.launch.NAME: array.launch.TOOL})):
        refs = {n: field._ref(root, local_file(root, p)) for n,p in names.items()}
        require(len({r['sha256'] for r in refs.values()}) == len(refs), 'ZFP timing and observation builds must differ')
        runtime = plan_recovery(root, {}, (), tools={n: {x: r[x] for x in ('path','sha256')} for n,r in refs.items()}, libraries=[lib])
        key = module.launch.LIBRARY
        require(runtime['tools'] == expected_tools and all(key.rsplit('/', 1)[1] in runtime['files'][p]['needed']
                    for p in expected_tools.values()) and all(runtime['files'][key][x] == lib[x] for x in ('bytes','sha256')),
                'ZFP measurement binding does not share this plan frozen native library')
        spec[k] = {'tools': refs, 'runtime': runtime, 'policy': {**module.POLICY,
                    'reference': 'same_run_functional_geometry_frame_and_restoration_reverified',
                    'order_seed': SEED}, 'launchers': launcher_lock()}
    return {**prior, 'schema': SCHEMA, 'population': population(plan['work_items'], prior['population'], routes),
            'zfp': {**spec, 'field_environment': field._cpus(field_cpus),
                    'operations': {r: list(array.OPERATIONS if r == array.ROUTE else field.DIRECTIONS) for r in routes},
                    'code': {path: digest(local_file(root, path)) for path in CODE}},
            'failure_retention': {**prior['failure_retention'], 'adapters': [*prior['failure_retention']['adapters'], ZFP]}}
