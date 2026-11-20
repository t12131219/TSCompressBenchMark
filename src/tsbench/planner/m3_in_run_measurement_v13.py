"""Freeze the CORAD producer/consumer measurements and complete the M3 denominator."""
from ..assets import content_id, digest, local_file, require
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .corad_corpus import INFERENCE
from .m3_corad import DRIVER, ROUTES
from .m3_in_run_measurement_v12 import freeze as freeze_v12

SCHEMA = 'bmk.m3-in-run-measurement/13'
CORAD = 'corad_same_run_full_cohort_repeats_v1'
CODE = ('src/tsbench/planner/m3_in_run_measurement_v13.py',
        'src/tsbench/application/m3_primary_measurement_v13.py',
        'src/tsbench/application/m3_in_run_corad.py',
        'src/tsbench/application/corad_training_execution.py',
        'src/tsbench/application/m3_in_run_failure.py',
        'native/measurement/corad_corpus/main.c', 'native/measurement/corad_corpus/CMakeLists.txt')


def population(items,base):
    updated=dict(base)
    for item in items:
        if (item['selection'],item['route']) not in ROUTES or item['applicability']!='input_domain_matches':
            continue
        k=item['work_item_id']
        require(updated[k]['status']=='measurement_adapter_not_integrated','overlapping CORAD measurement')
        updated[k]={'status':'scheduled','adapter':CORAD,'case_id':content_id({
            'work_item':k,'operation_config':item['operation_config_id'],'adapter':CORAD})}
    return updated


def freeze(root,plan,*args):
    from ..application import m3_in_run_corad as clock

    prior=freeze_v12(root,plan,*args[:-1])
    require({(r['selection'],r['route']):r['driver'] for r in plan['routes'] if (r['selection'],r['route']) in ROUTES}==
            dict.fromkeys(ROUTES,DRIVER),'CORAD timing requires the frozen three-route producer/consumer contract')
    functional=plan['build']['corad_corpus']; lib_name='lib/libcorad_c.so'; library=functional['decoder']['files'][lib_name]
    lib={'path':library['source'],**{k:library[k] for k in ('bytes','sha256')}}
    tool=clock._ref(root,local_file(root,args[-1]))
    runtime=plan_recovery(root,{},(),tools={clock.TOOL:{k:tool[k] for k in ('path','sha256')}},libraries=[lib])
    executable=f'bin/{local_file(root,args[-1]).name}'
    require(runtime['tools']=={clock.TOOL:'bin/tsbench_corad_corpus_clock'} and
            'libcorad_c.so' in runtime['files'][executable]['needed'] and
            all(runtime['files'][lib_name][k]==library[k] for k in ('bytes','sha256')),
            'CORAD clock driver is not linked to the same native library as the functional plan')
    pop=population(plan['work_items'],prior['population'])
    return {**prior,'schema':SCHEMA,'population':pop,
            'corad_clock':{'worker':tool,'runtime':runtime,'source_runtime':functional['source_runtime'],
                           'source_bridge_sha256':functional['source_bridge_sha256'],'timed_source_bridge':clock._identity(clock.bridge(root)),
                           'limits':functional['limits'],'launchers':launcher_lock(),
                           'operations':{r:['encode','decode'] if r==INFERENCE else ['train'] for _,r in sorted(ROUTES)},
                           'policy':{'warmup_rounds':1,'measured_rounds':clock.ROUNDS,
                                     'sample':'whole_frozen_decision_not_per_cohort_or_frame',
                                     'scope':'preverified_input_geometry_one_fresh_process_per_native_unit',
                                     'reference':'same_run_functional_producers_and_frames',
                                     'source':'preserve_shipped_rng_retrain_and_verify_train_only_arrays_per_trial',
                                     'decode':'frame_only_no_model_mount_no_original_mount',
                                     'quality':'verify_train_only_gates_again_and_report_rejected_cohorts_as_diagnostic_only',
                                     'not_measured':'original_source_ingress_is_outside_trial'},
                           'code':{p:digest(local_file(root,p)) for p in (*CODE,*functional['code'])}},
            'failure_retention':{**prior['failure_retention'],'adapters':[*prior['failure_retention']['adapters'],CORAD]}}
