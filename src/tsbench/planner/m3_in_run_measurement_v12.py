"""Bind native Huff0 ETB1 table and whole-holdout measurements."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .m3_huff0_table import DRIVER, KEY, STREAMS
from .m3_in_run_measurement_v11 import freeze as freeze_v11

SCHEMA = 'bmk.m3-in-run-measurement/12'
HUFF0 = 'huff0_etb1_independent_same_run_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v12.py',
        'src/tsbench/application/m3_primary_measurement_v12.py',
        'src/tsbench/application/m3_in_run_huff0_table.py',
        'src/tsbench/application/m3_in_run_failure.py')


def population(items,base):
    updated = dict(base)
    for item in items:
        if (item['selection'],item['route']) != KEY or item['applicability'] != 'input_domain_matches':
            continue
        k = item['work_item_id']
        require(updated[k]['status'] == 'measurement_adapter_not_integrated','overlapping Huff0 table measurement')
        updated[k] = {'status':'scheduled','adapter':HUFF0,'case_id':content_id({
            'work_item':k,'operation_config':item['operation_config_id'],'adapter':HUFF0})}
    return updated


def freeze(root,plan,*args):
    from ..application import m3_huff0_etb1_timing as timing

    prior = freeze_v11(root,plan,*args[:-1])
    require([r['driver'] for r in plan['routes'] if (r['selection'],r['route']) == KEY] == [DRIVER],
            'ETB1 timing requires the frozen native shared-table route')
    lib = plan['build']['huff0_table']['dependency']; timing.check(root,lib)
    tool = timing.relative(root,local_file(root,args[-1]))
    spec = plan_recovery(root,{},(),tools={timing.TOOL:{k:tool[k] for k in ('path','sha256')}},libraries=[lib])
    name = lib['path'].split('/')[-1]
    require(spec['tools'] == {timing.TOOL:'bin/tsbench_huff0_etb1_timing'} and
            name in spec['files'][spec['tools'][timing.TOOL]]['needed'] and
            all(spec['files'][f'lib/{name}'][k] == lib[k] for k in ('bytes','sha256')),
            'ETB1 grouped driver does not link the frozen native library')
    return {**prior,'schema':SCHEMA,'population':population(plan['work_items'],prior['population']),
            'huff0_table_grouped':{'worker':tool,'runtime':spec,'launchers':launcher_lock(),'limits':timing.LIMITS,
                                   'operations':list(timing.OPS),'streams':list(STREAMS),'group_blocks':timing.GROUP_BLOCKS,
                                   'policy':{**timing.POLICY,'reference':'same_run_functional_model_and_ordered_frames',
                                             'schedule':'case-seeded operations and matched stream order; one warmup and three measured rounds',
                                             'whole_wall':'train and encode reopen locked original; decode only fixed model and ordered frames'},
                                   'code':{p:digest(local_file(root,p)) for p in (*CODE,*timing.CODE)}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],HUFF0]}}
