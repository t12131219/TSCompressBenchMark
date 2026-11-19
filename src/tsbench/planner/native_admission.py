"""M0 definition lock for M3 native qualification, never a qualification result."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from .native_requirements import plan_native_requirements

POLICY = 'configs/suites/m3_first_batch_native_v2/admission.json'
SCHEMA = 'native-admission-policy'


def _quality(route, cases):
    label, kind = route['route'], route['quality']
    if kind == 'bitwise_exact':
        return {'kind':kind,'oracle':'original_order_dtype_shape_schema_and_bits','on_failure':'reject_quality'}
    if kind == 'exact_aggregate':
        return {'kind':kind,'oracle':'original_unsigned_per_channel_count_sum_max','on_failure':'reject_quality'}
    if kind == 'per_case_absolute_error':
        if label == 'field-modes':
            b = cases['zfp_cases']
            bounds = [{'case':f['id'],'dtype':f['type'],'mode':f['mode'],'shape':f['shape'],'strides':f['strides'],
                       'requested':f['requested'],'effective':f['effective'],
                       'max_abs_error':f['max_observed_error'],
                       'verification':'bitwise_exact' if f['mode']=='reversible' else 'inclusive_absolute_error'} for f in b['fields']]
            return {'kind':kind,'case_bundle_id':b['bundle_id'],'bounds':bounds,'oracle':'original_field_before_strides',
                    'padding':'untouched','on_failure':'reject_quality'}
        if label == 'fixed-rate-array':
            b = cases['zfp_cases']; a = b['array']
            return {'kind':kind,'case_bundle_id':b['bundle_id'],'bounds':[{k:a[k] for k in (
                        'type','shape','requested_rate','effective_rate','max_observed_error')}],
                    'oracle':'expected_after_reopen_including_writes','untouched':'unchanged_relative_to_initial_decoded_values',
                    'on_failure':'reject_quality'}
        if label in {'pbepla-progressive','pbepla-replay'}:
            b = cases['pbepla_cases']
            inputs = [x for x in b['inputs'] if label=='pbepla-progressive' or x['replay']]
            return {'kind':kind,'case_bundle_id':b['bundle_id'],'oracle':'original_finite_f64_each_declared_prefix',
                    'rule':'exact_abs_error_le_effective_epsilon_le_requested_epsilon',
                    'bounds':[{'input_id':x['input_id'],'name':x['name'],'requested_epsilon':x['requested_eps']} for x in inputs],
                    'on_failure':'reject_quality'}
    if kind == 'predeclared_empirical_per_column' and label == 'corad-inference':
        b = cases['corad_inference_cases']; p = b['quality_policy']
        require(p['policy_id']==content_id({k:v for k,v in p.items() if k!='policy_id'}), 'CORAD quality policy identity differs')
        models = [{'deployment_id':m['definition']['deployment_id'],'model_sha256':m['definition']['model']['sha256'],
                   'encode_configuration_id':m['configuration_id']} for m in b['models']]
        require(len({m['deployment_id'] for m in models})==len(models)==2, 'CORAD deployment denominator differs')
        return {'kind':kind,'case_bundle_id':b['bundle_id'],'quality_policy':p,'deployments':models,
                'heldout_input':b['input'],'heldout_windows':b['window'],'on_failure':'reject_quality_not_comparable',
                'tuning':'train_only_never_heldout','inference_admission':'decide_each_frozen_deployment_not_probe_status'}
    if kind == 'model_solver_oracle' and label in {'corad-c-training','corad-source-training'}:
        b = cases['corad_training_cases']; p = b['policy']; c_route = label=='corad-c-training'
        return {'kind':kind,'case_bundle_id':b['bundle_id'],'training_input':b['data']['train']['values'],
                'oracle':'model_statistics_and_lars_objective_kkt' if c_route else 'model_statistics_and_source_bridge_process_contract',
                'options':{'c_options':b['c_options'],'solver':p['c']} if c_route else p['source'],
                'statistics_absolute_tolerance':p['statistics_absolute_tolerance'],
                'heldout_use':'report_only_not_an_inference_pass','on_failure':'reject_training_oracle'}
    require(False,f'undefined native quality contract: {route["selection"]}/{label}/{kind}')


def compile_native_admission(root: Path, requirements: dict) -> dict:
    """Join the selected scope, per-check input identities, and new policy.

    Existing developer case bundles are pointers to immutable definitions, not
    converted into official drivers, resource ceilings or successful results.
    """
    policy = load_json(local_file(root,POLICY))
    schema = load_contract(root,SCHEMA)
    schema.validate(policy,POLICY)
    req_id = requirements['plan_content_id']
    require(req_id==content_id({k:v for k,v in requirements.items() if k!='plan_content_id'}), 'native requirement plan identity differs')
    env = policy['environment']
    toolchain_path = local_file(root,env['python_environment_lock'])
    toolchain = load_json(toolchain_path)
    require((toolchain['environment'],toolchain['platform'])==('tsbench','linux-64'),'initial environment and toolchain lock differ')
    routes = requirements['routes']
    domain = {(r['selection'],r['route']):r['domain'] for r in policy['routes']}
    require(len(domain)==len(policy['routes']) and domain.keys()=={(r['selection'],r['route']) for r in routes} and len(domain)==len(routes),
            'native domain policy must cover the frozen route denominator exactly')
    require(policy['protocols'].keys()=={r['protocol'] for r in routes},'native access protocol denominator differs')

    case_index = {}
    for key,bundle in requirements.items():
        if isinstance(bundle,dict) and 'bundle_id' in bundle and 'cases' in bundle:
            for case in bundle['cases']:
                cid = case['case_id']
                require(cid not in case_index,'ambiguous native case identity')
                case_index[cid] = (case,{'bundle_key':key,'bundle_id':bundle['bundle_id'],'case_name':case.get('name') or case['row']['case']})
    obligations = {}
    for c in requirements['conditional_plan']['obligations']:
        obligations.setdefault((c['selection'],c['route']),[]).append(c)

    out, schedules, used = [], [], set()
    for route in routes:
        key = route['selection'],route['route']
        protocol = policy['protocols'][route['protocol']]
        row = {'selection':key[0],'route':key[1], 'source_identity':{k:route[k] for k in
                    ('selection_id','archive_sha256','native_target','source_member','native_entry_tokens')},
               'domain':{'scope':'only_frozen_case_inputs_and_explicit_rejection_cases','description':domain[key]},
               'quality':_quality(route,requirements),
               'access':{'protocol':route['protocol'],'completion':protocol['completion'],
                         'formal_work_and_resource_limits':'unbound', 'on_limit':'record_explicit_nonpassing_terminal'},
               'retention':{'required':[*protocol['retain'],'exact_decoder_and_transitive_runtime_assets','terminal_and_failure_record'],
                            'restore':'fresh_process_product_and_declared_assets_only',
                            'bytes':'charge_all_serialized_products_and_required_assets_with_ownership_and_amortization_explicit',
                            'formal_case_capacity':'unbound'},
               'out_of_scope':route['out_of_scope']}
        rid = content_id(row)
        out.append({**row,'route_contract_id':rid,'qualification':'not_run'})
        for r in route['required']:
            joins = []
            for cid in r['cases']:
                require(cid in case_index and cid not in used,'missing or repeated native case definition')
                case, binding = case_index[cid]
                require((case['selection'],case['route'])==key and case.get('check',r['check'])==r['check'],
                        'native input case bound to wrong obligation')
                joins.append({'case_id':cid,**binding})
                used.add(cid)
            slot = {'route_contract_id':rid,'selection':key[0],'route':key[1],'check':r['check'],
                    'kind':'required','planned_case_inputs':joins}
            schedules.append({**slot,'obligation_id':content_id(slot),'state':'not_run',
                              'formal_execution_binding':'unbound' if joins else 'missing_case_inputs_and_driver'})
        for c in obligations.get(key,[]):
            slot = {'route_contract_id':rid,'selection':key[0],'route':key[1],'check':c['required_observation'],
                    'kind':'conditional','condition_case':c,
                    'runtime_resolution':'require_selected_build_host_workload_and_actual_work_in_same_run'}
            schedules.append({**slot,'obligation_id':content_id(slot),'state':'requires_runtime_evidence',
                              'formal_execution_binding':'unbound'})
    counts = requirements['coverage']
    require(used==case_index.keys() and len(used)==counts['bound_development_cases'] and
            len(schedules)==counts['required_checks']+counts['conditional_checks'] and
            sum(s['kind']=='conditional' for s in schedules)==counts['conditional_checks'] and
            len(schedules)==len({s['obligation_id'] for s in schedules}), 'native admission slot or case denominator differs')
    missing = sum(s['formal_execution_binding']=='missing_case_inputs_and_driver' for s in schedules)
    body = {'schema':'bmk.native-admission-plan/1','definition_stage':'M0','qualification_stage':'M3',
            'runnable':False,'qualification_granted':False,'stage_accepted':False,
            'coverage':{**counts,'total_obligations':len(schedules),'obligations_missing_input_cases':missing,
                        'formal_execution_bindings':0,'formal_qualified_obligations':0},
            'policies':{'submit':'one_plan_one_run_one_ledger','verification':'artifact_each',
                        'comparison':'qualification_only_not_a_timing_or_comparison_admission',
                        'environment':{**env,'toolchain_sha256':digest(toolchain_path),'meaning':'declared_initial_functional_profile_not_host_attestation'},
                        'regression':{'functional':'normal_ci_and_offline_isolated_restore_and_compatibility',
                                      'performance':'separate_controlled_host_plan_no_shared_ci_rankings'}},
            'bindings':{'requirements_plan_id':req_id,'requirements_bindings':requirements['bindings'],
                        'admission_policy_id':content_id(policy),'admission_schema_id':schema.document_id},
            'open':['formal_driver_and_build_binding','numeric_work_limits_and_enforcement',
                    'formal_resource_and_retention_capacity','files_only_restore_closure_per_case',
                    'formal_performance_comparison_is_separate'],
            'routes':out,'obligations':schedules}
    return {**body,'plan_content_id':content_id(body)}


def plan_native_admission(root: Path) -> dict:
    return compile_native_admission(root,plan_native_requirements(root))
