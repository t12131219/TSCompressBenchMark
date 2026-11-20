"""Extend the primary timing population to the typed native batch routes."""
from ..assets import content_id, digest, load_json, local_file, require
from ..recovery import plan_recovery
from .m3_in_run_measurement_v2 import freeze as freeze_v2

SCHEMA = 'bmk.m3-in-run-measurement/3'
COLUMN = 'column_batch_independent_whole_file_rounds_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v3.py',
        'src/tsbench/application/m3_real_corpus_measured.py',
        'src/tsbench/application/m3_in_run_batch.py',
        'src/tsbench/application/m3_primary_measurement.py')


def extend_population(items, base, routes):
    result = dict(base)
    for item in items:
        key = item['work_item_id']
        if item['applicability'] == 'input_domain_matches' and (item['selection'], item['route']) in routes:
            require(result[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping M3 timing adapters')
            result[key] = {'status': 'scheduled', 'adapter': COLUMN, 'case_id': content_id({
                'work_item': key, 'operation_config': item['operation_config_id'], 'adapter': COLUMN})}
    return result


def freeze(root, plan, cpu, fixed_worker, column_worker):
    from ..application import m3_column_batch as batch, m3_column_batch_timing as timing
    from .m3_fixed_batch import DRIVER as FIXED_DRIVER
    from .m3_titchy import BATCH_DRIVER as TITCHY_DRIVER

    clock = freeze_v2(root, plan, cpu, fixed_worker)
    source = plan['build']
    actual = {(r['selection'], r['route']): (r['plugin'], r['driver']) for r in plan['routes']
              if (r['selection'], r['route']) in batch.ROUTES}
    require(actual == {key: (plugin, FIXED_DRIVER if key[0] == 9 else TITCHY_DRIVER)
                       for key, (plugin, _) in batch.ROUTES.items()} and 'titchy' in plan.get('specialized', {}),
            'in-run column batch requires the frozen ALP and Titchy drivers')
    frozen = load_json(local_file(root, source['lock']['path']))
    worker_ref = batch.relative(root, local_file(root, column_worker))
    plugins = {name: frozen['plugins'][name] for name, _ in batch.ROUTES.values()}
    build = {'worker': worker_ref, 'plugins': plugins, 'source_build_id': frozen['build_id']}
    runtime = plan_recovery(root, {**build, 'build_id': content_id(build)}, {name: {} for name in plugins})
    return {**clock, 'schema': SCHEMA, 'population': extend_population(plan['work_items'], clock['population'], batch.ROUTES),
            'column_batch': {'worker': worker_ref, 'runtime': runtime, 'policy': timing.POLICY,
                             'limits': batch.LIMITS, 'launchers': batch.launcher_lock(),
                             'operations': {route: ['encode', *backends] for (_, route), (_, backends) in batch.ROUTES.items()},
                             'code': {p: digest(local_file(root, p)) for p in sorted({*batch.CODE, *timing.CODE, *CODE})}}}
