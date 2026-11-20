"""Freeze the extended same-run schedule, keeping the v1 freeze reproducible."""
from ..assets import content_id, digest, load_json, local_file, require
from ..recovery import plan_recovery
from .m3_in_run_measurement import build_population, freeze as freeze_v1

SCHEMA = 'bmk.m3-in-run-measurement/2'
FIXED = 'fixed_batch_independent_whole_file_rounds_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v2.py',
        'src/tsbench/application/m3_real_corpus_execution_v4.py',
        'src/tsbench/application/m3_in_run_fixed_batch.py')


def population(items, routes):
    items = list(items)
    result = build_population(items)
    for item in items:
        key = item['work_item_id']
        if item['applicability'] == 'input_domain_matches' and (item['selection'], item['route']) in routes:
            require(result[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping M3 timing adapters')
            result[key] = {'status': 'scheduled', 'adapter': FIXED, 'case_id': content_id({
                'work_item': key, 'operation_config': item['operation_config_id'], 'adapter': FIXED})}
    return result


def freeze(root, plan, cpu, worker):
    from ..application import m3_column_batch as batch, m3_fixed_batch_corpus as fixed

    clock = freeze_v1(root, plan, cpu)
    source = plan['build']
    require('fixed_batch' in source and all(r['plugin'] == fixed.ROUTES[(r['selection'], r['route'])]
            for r in plan['routes'] if (r['selection'], r['route']) in fixed.ROUTES),
            'in-run fixed batch requires matching functional routes')
    frozen = load_json(local_file(root, source['lock']['path']))
    require(frozen['build_id'] == source['build_id'], 'in-run fixed batch source build identity differs')
    worker_ref = batch.relative(root, local_file(root, worker))
    plugins = {name: frozen['plugins'][name] for name in fixed.ROUTES.values()}
    build = {'worker': worker_ref, 'plugins': plugins, 'source_build_id': frozen['build_id']}
    runtime = plan_recovery(root, {**build, 'build_id': content_id(build)}, {name: {} for name in plugins})
    return {**clock, 'schema': SCHEMA, 'population': population(plan['work_items'], fixed.ROUTES),
            'fixed_batch': {'worker': worker_ref, 'runtime': runtime, 'policy': fixed.POLICY,
                            'limits': batch.LIMITS, 'launchers': batch.launcher_lock(),
                            'operations': ['encode', 'default'],
                            'code': {p: digest(local_file(root, p)) for p in {*fixed.CODE, *CODE}}}}
