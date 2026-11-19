"""Admission for measurements whose run and qualification facts were already verified.

This does not verify or mint an observation, and must not consume user-authored
'passed' assertions. There is deliberately no CLI to upload admission facts.
"""
import re

from ..planner.comparison import freeze_comparison


def _id(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def _within(value, cap):
    return type(value) is int and 0 <= value <= cap


def admission_reasons(schema, bindings, facts):
    """Return reasons for rejecting a matched group (or [] when eligible).

    Input is ordered equally sized lists from the frozen schedule and a trusted
    run verifier. Schedule completeness and statistical sufficiency are separate.
    """
    if len(bindings)!=len(facts) or len(bindings)<2:
        return ['missing_comparison_members']
    reasons = []
    observations = [row.get('observation_id') for row in facts if _id(row.get('observation_id'))]
    if len(observations)!=len(set(observations)):
        reasons.append('duplicate_observations')
    if len({b['comparison_id'] for b in bindings})!=1:
        reasons.append('different_comparison_contract')
    for index,(binding,row) in enumerate(zip(bindings,facts,strict=True)):
        def need(condition, reason):
            if not condition:
                reasons.append(f'{index}:{reason}')

        frozen = freeze_comparison(schema,binding['contract'])
        if frozen != binding:
            need(False,'invalid_comparison_identity')
            continue
        spec = frozen['contract']
        need(row.get('comparison_id')==frozen['comparison_id'], 'observation_not_bound_to_comparison')
        need(all(_id(row.get(k)) for k in ('method_id','build_id','configuration_id','qualification_id','observation_id')),
             'missing_method_build_or_evidence_identity')
        need(spec['purpose']=='primary_timing' and row.get('pass_kind')=='timing_only', 'not_primary_timing')
        need(row.get('status')=='ok' and row.get('validation')=='passed' and row.get('quality')=='passed' and
             row.get('domain')=='passed', 'terminal_domain_or_quality_not_verified')
        validation = spec['validation']['strength']
        need(row.get('verification_strength')==validation and
             (validation!='artifact_replay' or _id(row.get('verified_replay_id'))), 'verification_strength_or_replay_missing')
        need(row.get('recovery')=='passed' and _within(row.get('independently_restored_samples'), (1<<63)-1) and
             row['independently_restored_samples']>=spec['retention']['samples_per_case_method'], 'independent_recovery_missing')
        need(row.get('accounting')=='complete' and type(row.get('raw_bytes')) is int and
             row['raw_bytes']==spec['original']['logical_bytes'], 'work_or_byte_accounting_incomplete')
        if control := spec['control']:
            need(row.get(control['kind'])==control['route_id'], 'fixed_branch_differs')
        resource = spec['resource']
        observed = row.get('resource') or {}
        observed_caps = {'physical_cores':'physical_cores','participant_threads':'peak_active_threads_total',
                         'peak_resident_bytes':'peak_resident_bytes','max_serialized_bytes':'serialized_bytes',
                         'deadline_ns':'operation_wall_ns'}
        need(row.get('resource_validation')=='passed' and _id(row.get('resource_evidence_id')) and
             observed.get('hardware_group_id')==resource['hardware_group_id'] and
             all(resource[k] is not None and _within(observed.get(name),resource[k])
                 for k,name in observed_caps.items()) and
             all(observed.get(name,0)>0 for name in ('physical_cores','peak_active_threads_total','operation_wall_ns')),
             'resource_budget_not_verified')
        # Backend and participant count need not be equal across candidates.
        need(isinstance(row.get('effective_backend'),str) and bool(row['effective_backend'].strip()), 'backend_not_observed')
        access = spec['access']
        need(row.get('access_validation')=='passed', 'access_not_verified')
        if access['mechanism']=='native_only':
            need(row.get('service_origin')=='native','native_mechanism_required')
        if stream := access['stream']:
            work = row.get('stream') or {}
            need(row.get('service_origin') in {'native','external_online','external_chunked_batch'} and
                 row.get('measure_includes_ingress_buffer_backpressure_finish') is True and
                 all(_within(work.get(k),stream[k]) for k in ('max_buffer_bytes','max_first_output_ns','max_output_gap_ns')) and
                 work.get('backpressure')=='passed' and work.get('finish_restores_all') is True and
                 work.get('emitted_before_finish') is True and
                 type(work.get('replayed')) is bool and (stream['replay_allowed'] or not work['replayed']),
                 'stream_bounds_completion_or_cost_not_verified')
            if access['mode']=='stream_strict_online':
                need(row.get('service_origin')!='external_chunked_batch', 'batch_wrapper_not_strict_online')
    return reasons
