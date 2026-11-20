"""Freeze timing scope for the M3 primary ledger, without admitting its clocks."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor import timing_resource
from .m3_pbepla import ROUTES as PBEPLA

SCHEMA = 'bmk.m3-in-run-measurement/1'
CODE = ('src/tsbench/planner/m3_in_run_measurement.py', 'src/tsbench/application/m3_in_run_measurement.py',
        'src/tsbench/application/m3_real_corpus_execution_v3.py', 'src/tsbench/application/m3_pbepla_grouped_timing.py',
        'src/tsbench/application/m3_column_batch_timing.py', 'src/tsbench/supervisor/timing_resource.py',
        'src/tsbench/application/m3_sprintz_timing.py')
ADAPTER = 'pbepla_grouped_independent_whole_file_rounds_v1'
TOOL = 'pbepla-grouped'


def build_population(items):
    population = {}
    for i in items:
        key = i['work_item_id']
        require(key not in population, 'duplicate work item in M3 timing population')
        if i['applicability']!='input_domain_matches':
            population[key] = {'status':i['applicability']}
        elif (i['selection'],i['route']) in PBEPLA:
            population[key] = {'status':'scheduled','adapter':ADAPTER, 'case_id':content_id({
                'work_item':key, 'operation_config':i['operation_config_id'], 'adapter':ADAPTER})}
        else:
            population[key] = {'status':'measurement_adapter_not_integrated'}
    return population


def freeze(root, plan, cpu):
    # Import only after the M3 planner is loaded; reuse the already audited whole-file schedule.
    from ..application.m3_pbepla_grouped_timing import OPERATIONS, POLICY
    binding = plan['build']
    require('pbepla_repair' in binding and 'input_switch' not in plan,'in-run measurements require the revised full M3 build')
    corpus = binding['pbepla_corpus']
    closure = plan_recovery(root,{},(),tools={TOOL:{k:corpus['executable'][k] for k in ('path','sha256')}},
                           libraries=[{k:corpus['dependency'][k] for k in ('path','sha256')}])
    return {'schema':SCHEMA, 'environment':timing_resource.environment(cpu), 'population':build_population(plan['work_items']),
            'runtime':closure,'limits':binding['pbepla_repair']['limits'], 'operations':list(OPERATIONS),
            'policy':dict(POLICY), 'admission':'cooperative_only_not_system_exclusive',
            'code':{p:digest(local_file(root,p)) for p in CODE}}
