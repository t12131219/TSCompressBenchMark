"""Bind the Unique native Zstd/XZ session and worker clocks to the primary ledger."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor import lzbench_corpus_clock as launch, timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from . import m3_lzbench_session as sessions, m3_lzbench_workers as workers
from .m3_in_run_measurement_v9 import freeze as freeze_v9

SCHEMA = 'bmk.m3-in-run-measurement/10'
LZBENCH = 'lzbench_session_and_worker_independent_same_run_v1'
ROUTES = {**dict.fromkeys(sessions.ROUTES, sessions.DRIVER), **dict.fromkeys(workers.ROUTES, workers.DRIVER)}
CODE = ('src/tsbench/planner/m3_in_run_measurement_v10.py',
        'src/tsbench/application/m3_primary_measurement_v10.py',
        'src/tsbench/application/m3_in_run_lzbench.py',
        'src/tsbench/application/m3_in_run_failure.py',
        'src/tsbench/application/m3_lzbench_durable.py')


def population(items, base):
    updated = dict(base)
    for item in items:
        if (item['selection'],item['route']) not in ROUTES or item['applicability'] != 'input_domain_matches':
            continue
        key = item['work_item_id']
        require(updated[key]['status'] == 'measurement_adapter_not_integrated', 'overlapping lzbench measurement')
        updated[key] = {'status':'scheduled','adapter':LZBENCH,'case_id':content_id({
            'work_item':key,'operation_config':item['operation_config_id'],'adapter':LZBENCH})}
    return updated


def freeze(root, plan, cpu, fixed, column, pages, abi, selfstar, field, observer, array, cpus, titchy, dictionary,
           session_tool, worker_tool, worker_cpus):
    from ..application import m3_lzbench_corpus_clock as clock, m3_lzbench_durable as durable

    prior = freeze_v9(root,plan,cpu,fixed,column,pages,abi,selfstar,field,observer,array,cpus,titchy,dictionary)
    require({(r['selection'],r['route']):r['driver'] for r in plan['routes'] if (r['selection'],r['route']) in ROUTES} == ROUTES,
            'lzbench timing requires the four frozen native session and worker routes')
    require(len(worker_cpus) == 3 and list(worker_cpus) == sorted(set(worker_cpus)),
            'lzbench paired workers require three sorted, distinct CPUs for two workers and the caller')
    env = [resource.environment(c) for c in worker_cpus]
    require(len({(e['package_id'],e['core_id']) for e in env}) == 3 and
            len({tuple(e['cpu_numa_nodes']) for e in env}) == 1,
            'lzbench matched worker budget requires three physical cores on the same NUMA node')
    lib = plan['build']['lzbench_session']['dependency']
    require(plan['build']['lzbench_workers']['dependency'] == lib,'session and worker functional builds use different libraries')
    tools = {k:clock._ref(root,local_file(root,p)) for k,p in zip(launch.TOOLS,(session_tool,worker_tool),strict=True)}
    spec = plan_recovery(root,{},(),tools={k:{x:v[x] for x in ('path','sha256')} for k,v in tools.items()},libraries=[lib])
    native = 'lib/liblzbench_native.so'
    require(spec['tools'] == {k:f'bin/{n}' for k,n in launch.TOOLS.items()} and
            all('liblzbench_native.so' in spec['files'][p]['needed'] for p in spec['tools'].values()) and
            all(spec['files'][native][k] == lib[k] for k in ('bytes','sha256')), 'lzbench clock runtime does not share the locked native library')
    code = (*CODE, *(f'src/tsbench/{p}' for p in clock.CODE), *(f'native/measurement/lzbench_corpus/{p}' for p in clock.SOURCES))
    return {**prior,'schema':SCHEMA,'population':population(plan['work_items'],prior['population']),
            'lzbench_clock':{'tools':tools,'runtime':spec,'worker_environment':env,'launchers':launcher_lock(),
                             'operations':{r:list(clock.DIRECTIONS) for r in clock.ROUTES},
                             'policy':{**clock.POLICY,'end_to_end':durable.POLICY['completion'],
                                       'order':'case-seeded lane permutation per round, paired direction cohorts',
                                       'reference':'same_run_functional_row_with_exact_reconstructed_or_retained_frame',
                                       'cpu_budget':'one CPU for native sessions; same three physical CPUs for each matched worker lane'},
                             'code':{p:digest(local_file(root,p)) for p in code}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],LZBENCH]}}
