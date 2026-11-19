"""Map the real M1 candidate suite onto versioned O-track boundary contracts."""
from ..assets import content_id, require
from ..contracts import compile_contract, load_contract
from .comparison import SCHEMA, freeze_comparison
from .measurement import PROFILE

SNAPSHOT = 'comparison-contract.schema.json'
DIRECTIONS = ('encode','decode')


def stage_comparisons(schema, suite, inputs, measurement, *, recovery=None, isolation=None):
    profile = measurement['policy']['profiles'][PROFILE]
    require(suite['task']=='values_only' and suite['quality']=='original_f64_bitwise_exact' and
            suite['access']=='whole_value_column_batch' and suite['comparison_track']=='O',
            'candidate comparison adapter does not cover this workload')
    dependency_policy = ("sealed_frame_and_build_identity_not_distributable_closure" if recovery is None else
                         "sealed_frame_and_run_local_linux_x86_64_glibc_decoder_closure_v1")
    result = {}
    for case in suite['cases']:
        label = case['id']
        source = inputs[label]
        common = {'schema':'bmk.comparison-contract/1','purpose':'development_diagnostic',
                  'track':'original_task','task':'values_only','control':None,'representation':None,
                  'original':{'object_id':content_id(source),'schema_id':source['schema_sha256'],'logical_bytes':source['bytes']},
                  'quality':{'kind':'bitwise_exact','exact_components':['V'],'max_abs_by_column':{},'exception_policy':'preserve_bits'},
                  'access':{'mode':'batch_whole','mechanism':'any_qualified','stream':None,
                            'ingress_id':content_id('canonical_f64_files_prepared_outside_process_clock'),
                            'partition_id':content_id('one_independent_whole_column_message'),
                            'workload_id':content_id(suite['access'])},
                  'resource':{'hardware_group_id':None,'physical_cores':None,'peak_resident_bytes':None,
                              'participant_threads':suite['scheduling']['requested_threads'],
                              'max_serialized_bytes':suite['max_serialized_bytes_per_slot'],
                              'deadline_ns':suite['timeout_seconds_per_operation']*1_000_000_000},
                  'validation':{'strength':profile['verification_strength'],'placement':profile['verification_placement'],
                                'protocol_id':content_id('independent_process_no_staged_input_f64_and_schema_bits'
                                                         if isolation is None else isolation['namespace'])},
                  'retention':{'samples_per_case_method':suite['retention']['verified_samples_per_slot'],
                               'independent_restore':True,'retain_failures':suite['retention']['preserve_raw_ledger_and_failures'],
                               'dependency_policy_id':content_id(dependency_policy)}}
        result[label] = {direction:freeze_comparison(schema,{**common,'boundary':{
            'direction':direction,'extent':profile['measurement_scope'],'lifecycle':profile['lifecycle'],
            'state':profile['state_policy'],'state_protocol_id':content_id(suite['scheduling']['state_reset']),
            'cache_policy_id':content_id(profile['cache_state']),'ownership':profile['ownership'],
            'completion':profile['completion_policy'],'output_boundary_id':content_id(profile['output_boundary']),
            'size_scope':profile['size_scope'],'size_accounting_id':content_id(suite['measurement']['byte_boundary']),
            'measurement_protocol_id':measurement['policy_id'] if isolation is None else
                content_id({'policy_id':measurement['policy_id'],'isolation':isolation})}}) for direction in DIRECTIONS}
    return {'schema_id':schema.document_id,'by_input':result}


def bind_stage_comparisons(root,suite,inputs,measurement, *, recovery=None, isolation=None):
    return stage_comparisons(load_contract(root,SCHEMA),suite,inputs,measurement,recovery=recovery,isolation=isolation)


def verify_stage_comparisons(plan, snapshot):
    schema = compile_contract(SCHEMA,snapshot)
    bindings = plan['contract_bindings']
    require(bindings['comparison']==stage_comparisons(schema,plan['suite'],plan['inputs'],bindings['measurement'],
                                                     recovery=bindings.get('recovery'), isolation=bindings.get('isolation')),
            'frozen comparison contracts differ from planned inputs or policies')
