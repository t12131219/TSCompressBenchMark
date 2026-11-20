"""Freeze an independent same-run Zstd dictionary clock alongside v8 routes."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor import zstd_dictionary_grouped as launch
from ..supervisor.isolated_worker import launcher_lock
from .m3_in_run_measurement_v8 import freeze as freeze_v8
from .m3_zstd_dictionary import DRIVER, KEY

SCHEMA = 'bmk.m3-in-run-measurement/9'
DICTIONARY = 'zstd_dictionary_independent_same_run_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v9.py',
        'src/tsbench/application/m3_primary_measurement_v9.py',
        'src/tsbench/application/m3_in_run_zstd_dictionary.py',
        'src/tsbench/application/m3_in_run_failure.py',
        'src/tsbench/application/m3_zstd_dictionary_timing.py',
        'src/tsbench/application/m3_zstd_dictionary_grouped.py',
        'src/tsbench/supervisor/zstd_dictionary_grouped.py',
        'src/tsbench/qualification/zstd_dictionary_grouped_wire.py',
        'src/tsbench/corpus_ingress.py',
        'native/measurement/zstd_dictionary_grouped/main.cpp',
        'native/measurement/zstd_dictionary_grouped/CMakeLists.txt')


def population(items, base):
    updated = dict(base)
    for item in items:
        if (item['selection'],item['route']) != KEY or item['applicability'] != 'input_domain_matches':
            continue
        key = item['work_item_id']
        require(updated[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping Zstd dictionary measurement')
        updated[key] = {'status':'scheduled','adapter':DICTIONARY,'case_id':content_id({
            'work_item':key,'operation_config':item['operation_config_id'],'adapter':DICTIONARY})}
    return updated


def freeze(root, plan, cpu, fixed, column, pages, abi, selfstar, field, observer, array, cpus, titchy, dictionary_tool):
    from ..application import m3_zstd_dictionary_timing as timing

    prior = freeze_v8(root,plan,cpu,fixed,column,pages,abi,selfstar,field,observer,array,cpus,titchy)
    require([r['driver'] for r in plan['routes'] if (r['selection'],r['route']) == KEY] == [DRIVER],
            'dictionary timing requires the frozen native train/test driver')
    dependency = plan['build']['zstd_dictionary']['dependency']
    tool = timing._ref(root,local_file(root,dictionary_tool))
    spec = plan_recovery(root,{},(),tools={launch.NAME:{k:tool[k] for k in ('path','sha256')}},libraries=[dependency])
    require(spec['tools'] == {launch.NAME:launch.TOOL} and launch.LIBRARY.rsplit('/',1)[1] in spec['files'][launch.TOOL]['needed'] and
            all(spec['files'][launch.LIBRARY][k] == dependency[k] for k in ('bytes','sha256')),
            'dictionary timing tool uses a different native library')
    policy = {**timing.POLICY,'fixed':'same-run verified dictionary and detached ZDG1 per file; no historical input or retraining during encode/decode',
              'order':'case-seeded permutation of three operations in each of four rounds'}
    return {**prior,'schema':SCHEMA,'population':population(plan['work_items'],prior['population']),
            'zstd_dictionary_grouped':{'worker':tool,'runtime':spec,'policy':policy,'launchers':launcher_lock(),
                                       'operations':list(timing.OPERATIONS),
                                       'code':{p:digest(local_file(root,p)) for p in CODE}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],DICTIONARY]}}
