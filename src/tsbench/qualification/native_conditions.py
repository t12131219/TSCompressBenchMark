"""Resolve conditional work from this run's already verified native artifacts."""
from ..assets import content_id, digest, load_json, local_file, require
from ..planner.native_conditions import CONDITIONS


OBSERVED = 'observed_satisfied_in_development'


def _alp(row, doc):
    c = row['criteria']
    backend = c['backend']
    cap = doc['backend_conditions'][str(c['width'])][backend]
    details = {'backend':backend,'built_for_width':cap['built_for_width'],'available':cap['available']}
    if not cap['built_for_width']:
        return 'pending_supported_build','backend_not_in_bound_build',details
    if not cap['available']:
        return 'pending_supported_runtime','built_backend_unavailable_in_this_run',details
    [case] = [r for r in doc['cases'] if r['case']==c['fixture'] and r['width']==c['width']]
    outcomes = {r['request']:r for r in case['backends']}
    proof = [outcomes[request] for request in c['requests']]
    for seen in proof:
        require(seen['dispatch']==backend and seen['state']=='restored_bit_exact' and seen['decimal_vectors_in_wire']>0,
                'ALP conditional control did not restore a decimal frame through requested backend')
        counter = seen['native_decimal_kernel_vectors']
        if row['selector']=='alp-avx2':
            require(type(counter) is int and counter>0 and seen['native_execution_confirmation']=='measured_counter',
                    'ALP AVX2 native decimal work missing')
        else:
            require(counter is None and seen['native_execution_confirmation']=='dispatch_only_no_native_counter',
                    'ALP AVX512 dispatch must not invent an execution counter')
    return OBSERVED,None,{**details,'frame_sha256':case['envelope_sha256'],'requests':proof}


def _zfp(row, doc):
    profiles = doc['openmp']['profiles']
    require([r['policy'] for r in profiles]==row['criteria']['profiles'],'ZFP conditional profiles differ')
    lanes = []
    for r in profiles:
        enc, dec = r['encode_block_work'],r['decode_block_work']
        require(r['reversible_bits_verified'] and r['serial_decode_reported'] and
                [w['tid'] for w in dec]==[r['caller_tid']] and len({w['tid'] for w in enc})==len(enc) and
                all(w['blocks']>0 for w in enc),'ZFP conditional block census differs')
        lanes.append({'profile':r['policy'],'encoding_tids':len(enc),'encode_blocks':sum(w['blocks'] for w in enc),
                      'decode_blocks':sum(w['blocks'] for w in dec),'payload_sha256':r['payload']['sha256']})
    require([r['encoding_tids'] for r in lanes]==row['criteria']['encoding_tids'] and
            len({r['encode_blocks'] for r in lanes} | {r['decode_blocks'] for r in lanes})==1,
            'ZFP conditional same-work/TID proof differs')
    return OBSERVED,None,{'lanes':lanes}


def _lzbench(row, doc):
    [observation] = [r for r in doc['observations'] if r['group']==row['route']]
    w = observation['observed']
    counts = []
    if row['selector']=='xz-workers':
        sync = w.get('synchronous')
        if not sync:
            return 'missing_same_run_control','caller_synchronous_control_not_retained',{}
        shared = w['observed']['2']['frame']
        sync_decode = sync['decode']['shared']
        path = row['criteria']['common_decode_frame']
        require(sync_decode['source_frame']==shared and sync_decode['source_frame_path']==path,
                'XZ conditional common decode artifact differs')
        counts.append({'profile':'synchronous','encode':sync['encode']['mt_worker_hooks'],
                       'decode':sync_decode['mt_worker_hooks']})
        for name in ('1','2'):
            lane = w['observed'][name]
            cross = lane['same_multiblock_frame_decode']
            require(cross['source_frame']==shared,'XZ profile decoded a different artifact')
            counts.append({'profile':name,'encode':lane['encode_jobs'],'decode':cross['decode_jobs']})
        require([r['decode']['worker_threads'] for r in counts]==row['criteria']['native_decoding_workers'] and
                all(r['decode']['jobs']>0 for r in counts[1:]),'XZ conditional decode worker proof differs')
        details = {'shared_decode_frame':{'path':path,**shared}}
    else:
        for name in row['criteria']['profiles']:
            lane = w['observed'][name]
            counts.append({'profile':name,'encode':lane['encode_jobs'],'decode':lane['decode_jobs']})
        details = {}
    require([r['encode']['worker_threads'] for r in counts]==row['criteria']['native_encoding_workers'] and
            all(r['encode']['jobs']>0 for r in counts[1:]),'lzbench conditional encode worker proof differs')
    return OBSERVED,None,{**details,'input':w['input'],'lanes':counts}


def _huff0(row, doc):
    cap = doc['fec1_cases'][0]['direct_backend']
    details = {'dynamic_bmi2_compiled':cap['dynamic_bmi2_compiled'],'cpu_bmi2_available':cap['cpu_bmi2_available']}
    if not cap['dynamic_bmi2_compiled']:
        return 'pending_supported_build','dynamic_bmi2_disabled_in_bound_build',details
    if not cap['cpu_bmi2_available']:
        return 'pending_supported_runtime','bmi2_unavailable_in_this_run',details
    counts = {k:sum(r['decode_entries'][k]['bmi2_arg_1'] for r in doc['fec1_cases'] + doc['etb1_profiles'])
              for k in row['criteria']['entries']}
    require(all(v>0 for v in counts.values()),'Huff0 expected BMI2 argument was not used for real work')
    return 'missing_same_run_control','explicit_portable_build_not_bound_in_this_run',{**details,'bmi2_calls':counts}


_EVALUATORS = {'alp-avx2':_alp,'alp-avx512bw':_alp,'zfp-openmp':_zfp,'zstd-workers':_lzbench,'xz-workers':_lzbench,'huff0-bmi2':_huff0}


def validate_condition_bindings(document):
    plan = document['bindings']['native_conditional_plan']
    require(isinstance(plan, dict) and set(plan) == {'conditional_plan_id', 'schema', 'target_stage',
                'definition_stage', 'runtime_scope', 'formal_qualification_granted', 'obligations'} and
            plan['conditional_plan_id']==content_id({k:v for k,v in plan.items() if k!='conditional_plan_id'}) and
            plan['schema']=='bmk.native-conditional-plan/1' and plan['definition_stage']=='M0' and
            plan['target_stage']=='M3' and plan['runtime_scope']=='same_development_run_only' and
            plan['formal_qualification_granted'] is False,
            'native conditional plan identity differs')
    obligations = plan['obligations']
    row_fields = {'selection', 'route', 'predicate', 'required_observation', 'bundle_key', 'bundle_id',
                  'test', 'evidence_path', 'selector', 'criteria', 'verification', 'obligation_id'}
    require(isinstance(obligations,list) and len(obligations)==len(CONDITIONS) and
            all(isinstance(r,dict) and set(r)==row_fields and type(r['selection']) is int and
                isinstance(r['route'],str) and isinstance(r['predicate'],str) for r in obligations) and
            {(r['selection'],r['route'],r['predicate']) for r in obligations}==CONDITIONS.keys(),
            'native conditional obligation denominator differs')
    bound = []
    for row in obligations:
        key = (row['selection'],row['route'],row['predicate'])
        check,bundle_key,selector,criteria = CONDITIONS[key]
        bundle = document['bindings'].get(bundle_key)
        require(isinstance(bundle,dict) and
                bundle.get('bundle_id')==content_id({k:v for k,v in bundle.items() if k!='bundle_id'}) and
                row['obligation_id']==content_id({k:v for k,v in row.items() if k!='obligation_id'}) and
                (row['required_observation'],row['bundle_key'],row['selector'],row['criteria'])==(check,bundle_key,selector,criteria) and
                all(row[k]==bundle.get(k) for k in ('bundle_id','test','evidence_path')), 'native conditional evidence binding differs')
        slots = [s for s in document['slots'] if s['test']==row['test']]
        require(len(slots)==1 and row['evidence_path'] in slots[0]['evidence'] and
                any(g['selection']==row['selection'] and g['operation']['route']==row['route'] and g['test']==row['test']
                    for g in document['groups']), 'native conditional observation is outside the bound operation')
        bound.append((row, slots[0]))
    return plan, bound


def resolve_conditions(run, document, statuses, *, portable=None):
    plan, bound = validate_condition_bindings(document)
    rows = []
    for row, slot in bound:
        proof = None
        if statuses[row['test']]=='passed':
            ref = local_file(run,f"slots/{slot['slot_id']}/{row['evidence_path']}")
            state,reason,details = _EVALUATORS[row['selector']](row,load_json(ref))
            proof = {'path':ref.relative_to(run).as_posix(),'sha256':digest(ref)}
            if row['selector']=='huff0-bmi2' and state=='missing_same_run_control':
                control = document['bindings'].get('huff0_portable_control')
                if control and portable:
                    require(statuses[control['test']]=='passed' and portable['control_id']==control['control_id'] and
                            details['bmi2_calls']==portable['dynamic_bmi2_calls'], 'Huff0 portable control identity or call tally differs')
                    state,reason,details = OBSERVED,None,{**details,'portable_control':portable}
                elif control:
                    reason = 'same_run_portable_control_'+statuses[control['test']]
        else:
            state,reason,details = 'not_observed',statuses[row['test']],{}
        rows.append({'selection':row['selection'],'route':row['route'],'predicate':row['predicate'],
                     'obligation_id':row['obligation_id'],'state':state,'reason':reason,'evidence':proof,
                     'observed':details,'formal_qualification':'not_run'})
    return {'conditional_plan_id':plan['conditional_plan_id'],'scope':plan['runtime_scope'],'obligations':rows}
