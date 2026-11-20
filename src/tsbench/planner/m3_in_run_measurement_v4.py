"""Freeze primary-ledger Gorilla geometry, runtimes and operation lanes."""
from ..assets import content_id, digest, local_file, require
from .m3_in_run_measurement_v3 import freeze as freeze_v3

SCHEMA = 'bmk.m3-in-run-measurement/4'
GORILLA = 'gorilla_c11_independent_whole_file_rounds_v1'
WARMUPS, REPEATS, SEED = 1, 3, 20261120
CODE = ('src/tsbench/planner/m3_in_run_measurement_v4.py',
        'src/tsbench/application/m3_real_corpus_primary.py',
        'src/tsbench/application/m3_in_run_gorilla.py',
        'src/tsbench/application/m3_gorilla_corpus_clock.py',
        'src/tsbench/application/m3_gorilla.py',
        'src/tsbench/supervisor/gorilla_corpus_clock.py',
        'src/tsbench/corpus_ingress.py')


def population(items, base, routes):
    result = dict(base)
    for item in items:
        key = item['work_item_id']
        if item['selection'] == 7 and item['route'] in routes and item['applicability'] == 'input_domain_matches':
            require(result[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping M3 timing adapters')
            result[key] = {'status': 'scheduled', 'adapter': GORILLA, 'case_id': content_id({
                'work_item': key, 'operation_config': item['operation_config_id'], 'adapter': GORILLA})}
    return result


def freeze(root, plan, cpu, fixed, column):
    from ..application import m3_gorilla_corpus_clock as clock
    from .m3_real_corpus import GORILLA_CORPUS_DRIVER

    previous = freeze_v3(root, plan, cpu, fixed, column)
    build = plan['build']
    require('gorilla_corpus' in build and 'gorilla_state_repair' in build and
            {r['route']: r['driver'] for r in plan['routes'] if r['selection'] == 7} == dict.fromkeys(clock.ROUTES, GORILLA_CORPUS_DRIVER),
            'Gorilla timing requires both frozen C11 route implementations')
    return {**previous, 'schema': SCHEMA, 'population': population(plan['work_items'], previous['population'], clock.ROUTES),
            'gorilla': {'bindings': clock._bindings(root, build), 'operations': {k: list(v) for k,v in clock.CLOCKS.items()},
                        'launchers': clock.launcher_lock(), 'native_spans': {r: {d:list(n) for d,n in ds.items()}
                            for r,ds in clock.CLOCKS.items()},
                        'policy': {**clock.POLICY, 'warmups': WARMUPS, 'repeats': REPEATS, 'seed': SEED,
                            'reference': 'rebuild_and_verify_all_blocks_against_same_run_functional_evidence',
                            'statistics': 'one randomized matched direction per independent whole-file process',
                            'verified_durable_clock': 'verify exact products, then fsync files and directories; encode includes original parsing'},
                        'code': {p: digest(local_file(root, p)) for p in CODE}}}
