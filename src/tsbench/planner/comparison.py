"""Freeze comparable conditions separately from each method and its build."""
from pathlib import Path

from ..assets import content_id, load_json, local_file, require
from ..contracts import Contract, load_contract

SCHEMA = 'comparison-contract'


def freeze_comparison(contract: Contract, spec: dict) -> dict:
    require(contract.name == SCHEMA, 'not a comparison contract schema')
    contract.validate(spec, 'comparison contract')
    task, access, bound = spec['task'], spec['access'], spec['boundary']
    quality, resource, validation = spec['quality'], spec['resource'], spec['validation']
    exact = set(quality['exact_components'])
    required = {'values_only': {'V'}, 'timestamps_only': {'T'},
                'shared_t_controlled': {'T','V'}, 'whole_object': {'T','V'}}[task]
    require((spec['representation'] is not None) == (spec['track']=='representation_controlled'),
            'R requires encoded input, schema and layout; O must not constrain codec representation')
    control = spec['control']
    if task == 'shared_t_controlled':
        require(control is not None and control['kind']=='fixed_timestamp_route', 'shared T requires a fixed timestamp route')
    elif task in {'values_only','timestamps_only'}:
        require(control is None, 'a component-only task cannot fix a separate branch')
    if quality['kind'] == 'bitwise_exact':
        require(required <= exact and not quality['max_abs_by_column'] and quality['exception_policy']=='preserve_bits',
                'bitwise task must cover requested components and preserve special bits')
    else:
        require('V' in required and 'V' not in exact and required-{'V'} <= exact and quality['max_abs_by_column'],
                'original-domain error bounds must apply to V and preserve requested T exactly')
    if access['mode']=='batch_whole':
        require(access['stream'] is None and bound['completion']!='stream_finished' and bound['state']!='carry_stream',
                'batch and stream completion/state cannot be interchanged')
    else:
        require(access['stream'] is not None and bound['completion']=='stream_finished' and
                bound['extent'] in {'pipeline_service','pipeline_full'} and bound['size_scope'] in {'full_frame','bundle'},
                'stream comparison requires bounded service, complete finish and full time/byte accounting')
        if access['mode']=='stream_strict_online':
            require(not access['stream']['replay_allowed'], 'strict online cannot replay ingress')
    if spec['purpose']=='primary_timing':
        require(all(resource[k] is not None for k in ('hardware_group_id','physical_cores','peak_resident_bytes')) and
                validation['strength'] in {'artifact_each','artifact_replay'},
                'primary timing requires complete resource bounds and artifact verification')
    if bound['extent'] in {'pipeline_full','pipeline_service'}:
        placement = 'inside_extent' if bound['extent']=='pipeline_full' else 'outside_extent'
        require(validation['placement']==placement, f"{bound['extent']} requires {placement} validation")
    body = {'schema_id':contract.document_id,'contract':spec}
    return {**body,'comparison_id':content_id(body)}


def plan_comparison(root: Path, config: str) -> dict:
    return freeze_comparison(load_contract(root,SCHEMA),load_json(local_file(root,config)))
