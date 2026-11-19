"""Freeze the six first-batch conditional obligations, without resolving hardware at plan time."""
from ..assets import content_id, require

# Eligibility and work are separate: the selected build and workload must be
# observed in the run that produces the result. A declaration is not work.
CONDITIONS = {
    (9,'decode-backends','alp_f64_avx2_available'): (
        'avx2_decimal_with_native_work','alp','alp-avx2',
        {'backend':'falp-avx2','width':64,'fixture':'mixed-decimal-raw','branch':'decimal',
         'requests':['falp-avx2'],'confirm':'native_counter_and_detached_bit_exact'}),
    (9,'decode-backends','alp_f64_avx512bw_available'): (
        'avx512bw_decimal_with_effective_dispatch','alp','alp-avx512bw',
        {'backend':'falp-avx512bw','width':64,'fixture':'mixed-decimal-raw','branch':'decimal',
         'requests':['falp-avx512bw','falp-auto'],'confirm':'effective_dispatch_and_detached_bit_exact'}),
    (31,'openmp-encode','zfp_openmp_two_threads_available'): (
        'native_block_work_on_two_threads','zfp','zfp-openmp',
        {'profiles':['serial','1','2'],'encoding_tids':[1,1,2],'decode_on_caller':True,'same_field_work':True}),
    (40,'zstd-workers','zstd_mt_enabled_and_frame_eligible'): (
        'encoder_jobs_and_distinct_native_worker_ids','lzbench','zstd-workers',
        {'profiles':['0','2'],'native_encoding_workers':[0,2],'same_input_and_options':True}),
    (39,'xz-workers','xz_mt_budget_and_frame_eligible'): (
        'trace_encoder_and_decoder_separately','lzbench','xz-workers',
        {'profiles':['synchronous','1','2'],'native_encoding_workers':[0,1,2],'native_decoding_workers':[0,1,2],
         'common_decode_frame':'workers-2.xz'}),
    (29,'huff0-reference','huff0_dynamic_bmi2_and_cpu_available'): (
        'bmi2_dispatch_vs_portable_decode','huff0','huff0-bmi2',
        {'entries':['FEC1_4X_hufOnly_wksp','ETB1_1X_usingDTable','ETB1_4X_usingDTable'],
         'primary':'runtime-bmi2','control':'explicit_portable_build_same_retained_frames_and_model'}),
}


def freeze_conditions(routes, bundles):
    obligations = [(r['selection'],r['route'],c) for r in routes for c in r['conditional']]
    keys = [(n,r,c['predicate']) for n,r,c in obligations]
    require(len(keys)==len(set(keys)) and set(keys)==CONDITIONS.keys(),'native conditional predicate closure differs')
    rows = []
    for (n, route, condition), key in zip(obligations,keys,strict=True):
        check, bundle_key, selector, criteria = CONDITIONS[key]
        require(condition['require']==check,'conditional native work requirement differs')
        bundle = bundles[bundle_key]
        row = {'selection':n,'route':route,'predicate':condition['predicate'],'required_observation':check,
               'bundle_key':bundle_key,'bundle_id':bundle['bundle_id'],'test':bundle['test'],'evidence_path':bundle['evidence_path'],
               'selector':selector,'criteria':criteria,'verification':condition.get('verification')}
        rows.append({**row,'obligation_id':content_id(row)})
    result = {'schema':'bmk.native-conditional-plan/1','target_stage':'M3','definition_stage':'M0',
              'runtime_scope':'same_development_run_only','formal_qualification_granted':False,'obligations':rows}
    return {**result,'conditional_plan_id':content_id(result)}
