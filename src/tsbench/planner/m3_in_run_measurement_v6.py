"""Bind frozen Sprintz FIRE, Huff0 FEC1 and SElf* whole-file timing controllers."""
from ..assets import content_id, digest, load_json, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .m3_in_run_measurement_v5 import freeze as freeze_v5

SCHEMA = 'bmk.m3-in-run-measurement/6'
WHOLE = 'abi_or_selfstar_independent_whole_file_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v6.py', 'src/tsbench/application/m3_in_run_whole.py',
        'src/tsbench/application/m3_primary_measurement_v6.py', 'src/tsbench/application/m3_whole_durable.py',
        'src/tsbench/application/m3_fixed_batch_corpus.py')


def population(items, base, routes):
    updated = dict(base)
    for item in items:
        if (item['selection'], item['route']) not in routes or item['applicability'] != 'input_domain_matches':
            continue
        key = item['work_item_id']
        require(updated[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping whole-file measurement')
        updated[key] = {'status': 'scheduled', 'adapter': WHOLE, 'case_id': content_id({
            'work_item': key, 'operation_config': item['operation_config_id'], 'adapter': WHOLE})}
    return updated


def freeze(root, plan, cpu, fixed, column, pages, abi_worker, selfstar_worker):
    from ..application import m3_abi_corpus_timing as abi, m3_selfstar_timing as selfstar
    from ..application.m3_in_run_whole import SEED
    from . import m3_huff0_fec1, m3_sprintz

    prior = freeze_v5(root, plan, cpu, fixed, column, pages)
    keys = {m3_sprintz.BATCH: m3_sprintz.DRIVER, m3_huff0_fec1.KEY: m3_huff0_fec1.DRIVER, **selfstar.DRIVERS}
    require({(r['selection'], r['route']): r['driver'] for r in plan['routes'] if (r['selection'], r['route']) in keys} == keys,
            'whole-file timing requires four exact frozen functional drivers')
    locked = plan['build']
    build = load_json(local_file(root, locked['lock']['path']))
    require(build['build_id'] == locked['build_id'], 'whole-file timing uses a different build lock')
    bindings = {}
    for name, path, module, names in (('abi', abi_worker, abi, abi.CODECS.values()),
                                      ('selfstar', selfstar_worker, selfstar, (selfstar.PLUGIN,))):
        worker = abi.relative(root, local_file(root, path))
        plugins = {p: build['plugins'][p] for p in names}
        parts = {'worker': worker, 'plugins': plugins}
        methods = {p: {'plugin': p, 'options': {}} for p in names}
        bindings[name] = {'worker': worker, 'runtime': plan_recovery(root, {**parts, 'build_id': content_id(parts)}, methods),
                          'limits': module.LIMITS, 'env' if name == 'abi' else 'environment': prior['environment']}
    return {**prior, 'schema': SCHEMA, 'population': population(plan['work_items'], prior['population'], keys),
            'whole': {**bindings, 'operations': {r: ['encode', 'decode'] for _, r in keys}, 'launchers': launcher_lock(),
                      'policy': {'seed': SEED, 'warmups': 1, 'repeats': 3,
                                 'anchors': 'rebuild_from_original_and_verify_against_same_run_each_native_frame',
                                 'trials': 'independent_process_per_direction_randomized_in_matched_rounds',
                                 'group_bytes': abi.GROUP_BYTES, 'incremental': selfstar.POLICY['incremental']},
                      'code': {p: digest(local_file(root, p)) for p in sorted(set((*CODE, *abi.CODE, *selfstar.CODE)))}},
            'failure_retention': {**prior['failure_retention'], 'adapters': [*prior['failure_retention']['adapters'], WHOLE]}}
