"""Freeze same-run, bounded whole-file Sprintz compressed-domain queries."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .m3_in_run_measurement_v10 import freeze as freeze_v10

SCHEMA = 'bmk.m3-in-run-measurement/11'
SPRINTZ = 'sprintz_query_independent_same_run_v1'
KEY = (19,'query')
CODE = ('src/tsbench/planner/m3_in_run_measurement_v11.py',
        'src/tsbench/application/m3_primary_measurement_v11.py',
        'src/tsbench/application/m3_in_run_sprintz_query.py',
        'src/tsbench/application/m3_in_run_failure.py')


def population(items,base):
    updated = dict(base)
    for item in items:
        if (item['selection'],item['route']) != KEY or item['applicability'] != 'input_domain_matches':
            continue
        k = item['work_item_id']
        require(updated[k]['status'] == 'measurement_adapter_not_integrated','overlapping Sprintz query measurement')
        updated[k] = {'status':'scheduled','adapter':SPRINTZ,'case_id':content_id({
            'work_item':k,'operation_config':item['operation_config_id'],'adapter':SPRINTZ})}
    return updated


def freeze(root,plan,*args):
    from ..application import m3_sprintz_durable as durable

    prior = freeze_v10(root,plan,*args[:-1])
    require([r['driver'] for r in plan['routes'] if (r['selection'],r['route']) == KEY] == ['sprintz-corpus-query/1'],
            'Sprintz query timing requires the frozen native query route')
    lib = plan['build']['sprintz_query']['dependency']; durable.check(root,lib)
    tool = durable.relative(root,local_file(root,args[-1]))
    spec = plan_recovery(root,{},(),tools={durable.TOOL:{k:tool[k] for k in ('path','sha256')}},libraries=[lib])
    name = lib['path'].split('/')[-1]
    require(spec['tools'] == {durable.TOOL:'bin/tsbench_sprintz_grouped'} and
            name in spec['files'][spec['tools'][durable.TOOL]]['needed'] and
            all(spec['files'][f'lib/{name}'][k] == lib[k] for k in ('bytes','sha256')),
            'Sprintz grouped tool does not link the frozen query library')
    return {**prior,'schema':SCHEMA,'population':population(plan['work_items'],prior['population']),
            'sprintz_query_grouped':{'worker':tool,'runtime':spec,'launchers':launcher_lock(),'limits':durable.LIMITS,
                                     'operations':list(durable.OPS),'archive_group_max_bytes':durable.GROUP_BYTES,
                                     'policy':{**durable.POLICY,'reference':'same_run_functional_frames_and_locked_original_u16_reduction_oracle',
                                               'schedule':'one warmup plus three measured case-seeded rounds'},
                                     'code':{p:digest(local_file(root,p)) for p in (*CODE,*durable.CODE)}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],SPRINTZ]}}
