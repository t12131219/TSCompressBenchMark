"""Freeze same-run pcodec page measurements and retained failure diagnostics."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor import pcodec_pages_grouped as launch
from ..supervisor.isolated_worker import launcher_lock
from .m3_in_run_measurement_v4 import GORILLA, freeze as freeze_v4

SCHEMA = 'bmk.m3-in-run-measurement/5'
PCODEC_PAGES = 'pcodec_independent_whole_file_pages_v1'
COMMON = 'native/measurement/pcodec_pages_grouped/'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v5.py',
        'src/tsbench/application/m3_primary_measurement_v5.py',
        'src/tsbench/application/m3_in_run_pcodec_pages.py',
        'src/tsbench/application/m3_in_run_gorilla_retained.py',
        'src/tsbench/application/m3_in_run_failure.py',
        'src/tsbench/application/m3_pcodec_grouped_timing.py',
        'src/tsbench/application/m3_pcodec_page_timing.py',
        'src/tsbench/supervisor/pcodec_pages_grouped.py',
        'plugins/codecs/pcodec/pages_control.cpp',
        *(COMMON + n for n in ('CMakeLists.txt', 'main.cpp', 'grouped-io.patch')))


def population(items, base, routes):
    result = dict(base)
    for item in items:
        if (item['selection'], item['route']) not in routes or item['applicability'] != 'input_domain_matches':
            continue
        key = item['work_item_id']
        require(result[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping pcodec page adapter')
        result[key] = {'status': 'scheduled', 'adapter': PCODEC_PAGES, 'case_id': content_id({
            'work_item': key, 'operation_config': item['operation_config_id'], 'adapter': PCODEC_PAGES})}
    return result


def freeze(root, plan, cpu, fixed, column, tool):
    from ..application import m3_pcodec_grouped_timing as grouped
    from .m3_real_corpus import PCODEC_PAGE_DRIVER, PCODEC_PAGE_ROUTES

    previous = freeze_v4(root, plan, cpu, fixed, column)
    require({(r['selection'], r['route']) for r in plan['routes'] if r['driver'] == PCODEC_PAGE_DRIVER} == PCODEC_PAGE_ROUTES and
            {route for _, route in PCODEC_PAGE_ROUTES} == set(grouped.LANES.values()) and 'pcodec_pages' in plan['build'],
            'pcodec measurement requires both frozen native page control routes')
    binding = plan['build']['pcodec_pages']
    path = local_file(root, tool)
    ref = grouped._ref(root, path)
    runtime = plan_recovery(root, {}, (), tools={launch.NAME: {k: ref[k] for k in ('path', 'sha256')}},
                            libraries=[binding['dependency']])
    lib = runtime['files'].get(launch.LIBRARY, {})
    require(runtime['tools'] == {launch.NAME: launch.TOOL} and launch.LIBRARY in
            [f'lib/{n}' for n in runtime['files'][launch.TOOL]['needed']] and
            all(lib.get(k) == binding['dependency'][k] for k in ('sha256', 'bytes')),
            'pcodec grouped ELF closure differs from this plan functional library')
    return {**previous, 'schema': SCHEMA, 'population': population(plan['work_items'], previous['population'], PCODEC_PAGE_ROUTES),
            'pcodec_pages': {'tool': ref, 'functional_binding': binding, 'runtime': runtime, 'launchers': launcher_lock(),
                            'limits': {'file_bytes': launch.FILE_CEILING, 'address_space_bytes': launch.AS_LIMIT,
                                       'wall_seconds': launch.WALL_SECONDS},
                            'operations': {route: list(grouped.DIRECTIONS) for route in grouped.LANES.values()},
                            'policy': {**grouped.POLICY, 'reference': 'same_run_verified_functional_PM3PAGE1_per_group',
                                       'statistics': 'randomized_matched_directions_independent_process_per_file_and_lane'},
                            'code': {p: digest(local_file(root, p)) for p in CODE}},
            'failure_retention': {'adapters': [GORILLA, PCODEC_PAGES],
                                  'policy': 'retain_supervisor_stdout_and_stderr_before_releasing_failed_scratch'}}
