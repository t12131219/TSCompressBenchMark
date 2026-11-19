"""Per-case execution bindings over the full native definition, without granting qualification."""
from collections import Counter

from ..assets import content_id, require
from ..supervisor.isolated_worker import program_files
from .batch_execution import DIRECT_TOOL, is_gorilla_slot, requires_cross
from .linear_batch import (FENV_TOOL, ZSTD_TOOL, ALP_DECODE_SUITES, ZFP_NATIVE_SUITES, LZBENCH_PROFILE_SUITES, batch_limits, fenv_binding_key, wants_pcodec_direct,
                           wants_titchy_direct, wants_xz_direct)
from .pcodec_batch import TOOL as PCO_TOOL
from .pcodec_pages import TOOL as WRAPPED_TOOL
from .typed_batch import TITCHY_TOOL
from . import selfstar_execution as selfstar
from . import huff0_execution as huff
from . import huff0_bmi2 as bmi2
from . import sprintz_execution as sprintz
from . import titchy_execution as access
from . import titchy_stream as stream
from . import pcodec_intmult as intmult
from . import gorilla_state as state
from . import lzbench_session as sessions
from . import lzbench_profiles as profiles
from . import alp_decode as decode
from . import zfp_execution as zfp
from . import pbepla_execution as pbepla
from . import corad_execution as corad
from . import corad_training_execution as training
from .xz_batch import TOOL as XZ_TOOL


def operations(plan, slot):
    """Frozen dispatcher labels and actual program selectors, in ledger order."""
    if selfstar.is_selfstar(slot):
        return selfstar.operations(slot)
    if huff.is_huff0(slot):
        return huff.operations(slot)
    if sprintz.is_sprintz(slot):
        return sprintz.operations(slot)
    if access.is_access(slot):
        return access.operations(slot)
    if stream.is_stream(slot):
        return stream.operations(slot)
    if intmult.is_intmult(slot):
        return intmult.operations(slot)
    if state.is_state(slot):
        return state.operations(slot)
    if sessions.is_session(slot):
        return sessions.operations(slot)
    if profiles.is_profile(slot):
        return profiles.operations(slot)
    if decode.is_decode(slot):
        return decode.operations(slot)
    if zfp.is_zfp(slot):
        return zfp.operations(slot)
    if training.is_training(slot):
        return training.operations(slot)
    if corad.is_corad(slot):
        return corad.operations(slot)
    if pbepla.is_pbepla(slot):
        return pbepla.operations(slot)
    if 'protocol' in slot:
        return [(op,WRAPPED_TOOL) for op in slot['operations']]
    order = [('encode-columns',None)]
    if is_gorilla_slot(slot):
        if not slot['expected_status']:
            order.extend([('native-encode',DIRECT_TOOL),('decode-columns',None),('native-decode',DIRECT_TOOL),
                          ('native-to-abi-decode',None)] if requires_cross(plan,slot) else [('decode-columns',None)])
        return order
    pco = [('pcodec-direct-standalone-control',PCO_TOOL)] if wants_pcodec_direct(plan,slot) else []
    if slot['expected_status']:
        return order+pco
    fenv = plan['obligation_bindings'][fenv_binding_key(plan['suite'])]['product_slots']
    if slot['product_slot'] in fenv:
        order.append(('alp-fenv-negative',FENV_TOOL))
    if wants_titchy_direct(plan,slot):
        order.append(('titchy-direct-encode-and-capacity',TITCHY_TOOL))
    if wants_xz_direct(plan,slot):
        order.append(('xz-direct-parity-and-budget',XZ_TOOL))
    order.extend(pco)
    if slot['upstream_zstd']:
        order.append(('upstream-encode',ZSTD_TOOL))
    order.append(('decode-columns',None))
    order.extend((name,None) for name in slot['reject_decodes'])
    if slot['upstream_zstd']:
        order.append(('upstream-to-abi-decode',None))
    return order


def _programs(decoder):
    out = {}
    for kind, group in [('abi',decoder['plugins']),('tool',decoder['tools'])]:
        for name, program in group.items():
            executable = decoder['worker'] if kind=='abi' else program
            roots = [executable,program] if kind=='abi' else [executable]
            files = program_files(decoder,roots)
            out[f'{kind}/{name}'] = {'executable':executable,'library':program if kind=='abi' else None,
                                     'mount_files':files,'bytes':sum(decoder['files'][f]['bytes'] for f in files)}
    return out


def compile_binding_view(plan, routes):
    admission, case_products = plan['admission_definition'],plan['case_products']
    aid = admission['plan_content_id']
    require(admission['schema']=='bmk.native-admission-plan/1' and admission['runnable'] is False and
            admission['qualification_granted'] is False and admission['stage_accepted'] is False and
            aid==plan['admission_plan_id']==content_id({k:v for k,v in admission.items() if k!='plan_content_id'}) and
            admission['coverage']==plan['admission_coverage'], 'execution binding does not match admission definition')
    all_routes = {(r['selection'],r['route']):r for r in admission['routes']}
    require(len(all_routes)==len(admission['routes'])==36 and len({n for n,_ in all_routes})==12 and
            plan['route_contracts']=={all_routes[key]['route_contract_id']:all_routes[key] for key in routes},
            'execution binding does not cover the frozen route denominator')
    slots = {s['product_slot']:s for s in plan['slots']}
    require(len(slots)==len(plan['slots']) and all(sid==content_id({k:v for k,v in s.items() if k!='product_slot'})
                for sid,s in slots.items()), 'duplicate or altered product in the binding')
    programs = _programs(plan['decoder'])
    if plan.get('suite')==bmi2.SUITE:
        decoder = plan[bmi2.KEY]['decoder']
        for name, program in _programs(decoder).items():
            programs[name] = {**program,'mount_files':[f'{bmi2.DIRECTORY}/{p}' for p in program['mount_files']],
                              'recovery_id':decoder['recovery_id'],'recovery_namespace':bmi2.DIRECTORY}
    for slot in slots.values():
        if training.is_training(slot):
            programs.update(training.programs(slot))
    products, bound, pending, used = {}, {}, {}, set()
    for ob in admission['obligations']:
        oid, key = ob['obligation_id'], (ob['selection'],ob['route'])
        require(oid not in bound and oid not in pending and all_routes[key]['route_contract_id']==ob['route_contract_id'],
                'duplicate obligation or unmatched route contract')
        conditional_profile = plan.get('suite') in LZBENCH_PROFILE_SUITES and profiles.supports_condition(ob)
        conditional_alp = plan.get('suite') in ALP_DECODE_SUITES and decode.supports_condition(ob)
        conditional_zfp = plan.get('suite') in ZFP_NATIVE_SUITES and zfp.supports_condition(ob)
        conditional_bmi2 = plan.get('suite')==bmi2.SUITE and bmi2.supports_condition(ob)
        conditional = conditional_profile or conditional_alp or conditional_zfp or conditional_bmi2
        if key not in routes or (ob['kind']!='required' and not conditional):
            pending[oid] = {'route_contract_id':ob['route_contract_id'],'check':ob['check'],
                            'reason':'runtime_condition_not_bound' if ob['kind']=='conditional' else 'driver_not_bound'}
            continue
        method, cases, ids = routes[key], {}, []
        if conditional_profile:
            ids = profiles.condition_slots(ob,slots.values())
        if conditional_alp:
            ids = decode.condition_slots(ob,slots.values())
        if conditional_zfp:
            ids = zfp.condition_slots(ob,slots.values())
        if conditional_bmi2:
            ids = bmi2.condition_slots(ob,slots.values())
        for c in ob.get('planned_case_inputs',[]) if conditional else ob['planned_case_inputs']:
            cid = c['case_id']
            require(cid in case_products and cid not in used, 'missing or reused admission case binding')
            used.add(cid)
            cp = case_products[cid]
            require(set(cp)=={'bundle_id','product_slots'} and cp['bundle_id']==c['bundle_id'] and cp['product_slots'] and
                    all(s in slots and slots[s]['method']==method for s in cp['product_slots']), 'case product belongs to another route')
            if key==decode.ROUTE:
                case = {'selection':key[0],'route':key[1],'check':ob['check'],'name':c['case_name'],
                        'criteria':{'fixtures':[slots[s]['fixture'] for s in cp['product_slots']],
                                    'decode_requests':list(decode.REQUESTS)}}
                require(content_id(case)==cid,'ALP backend fixture-to-check binding differs')
            if key in zfp.ROUTES:
                require(cp['product_slots']==zfp.required_slots(ob,slots.values()),'ZFP fixture-to-check closure differs')
            if key in pbepla.ROUTES:
                case = {'route':key[1],'check':ob['check'],'name':c['case_name']}
                require(cp['product_slots']==pbepla.required_slots(case,slots.values()),
                        'PBEPLA case-to-step closure differs')
            if key==corad.ROUTE or key in training.ROUTES:
                require(len(cp['product_slots'])==1,'CORAD case requires one common ordered inference slot')
                target=slots[cp['product_slots'][0]]
                require((corad.is_corad(target) if key==corad.ROUTE else training.is_training(target)) and
                        target['bundle']['bundle_id']==cp['bundle_id'] and
                        any(x['case_id']==cid==content_id({k:v for k,v in x.items() if k!='case_id'}) and
                            x['name']==c['case_name'] and x['check']==ob['check'] and x['route']==key[1]
                            for x in target['bundle']['cases']),'CORAD case or quality policy binding differs')
            ids.extend(cp['product_slots'])
            cases[cid] = cp
        if key==corad.ROUTE:
            ids = list(dict.fromkeys(ids))
        name = f'{key[0]}/{key[1]}/{ob["check"]}'
        binding = {'obligation_id':oid,'route_contract_id':ob['route_contract_id'],'product_slots':ids}
        require(ids and len(ids)==len(set(ids)) and plan['obligation_bindings'].get(name)==binding,
                'obligation binding differs from its declared cases')
        bound[oid] = {'route_contract_id':ob['route_contract_id'],'check':ob['check'],'cases':cases}
        if conditional:
            require(not cases,'conditional runtime evidence cannot substitute required cases')
            bound[oid].update(condition_case=ob['condition_case'],product_slots=ids)
        for sid in ids:
            products.setdefault(sid,[]).append(oid)
    coverage = Counter(o['kind'] for o in admission['obligations'])
    require(used==case_products.keys() and products.keys()==slots.keys() and len(bound)==len(plan['obligation_bindings']) and
            coverage=={'required':180,'conditional':6}, 'incomplete binding partition')
    drivers = {}
    for sid,slot in slots.items():
        method = slot['method']
        abi_method = pbepla.PLUG if pbepla.is_pbepla(slot) else method
        steps = [{'label':op,'program':f'python/{tool}' if tool==training.PYTHON else
                  f'tool/{tool}' if tool else f'abi/{abi_method}'} for op,tool in operations(plan,slot)]
        require(all(op['program'] in programs for op in steps), 'unbound program in execution steps')
        if selfstar.is_selfstar(slot):
            artifact_limits = slot['parts']
            input_bytes = slot['original']['bytes']+slot['original']['schema_bytes']
            live = method==selfstar.LIVE
            configuration = {'width':slot['width'],'dtype':slot['dtype'],'block_values':512,
                             **(selfstar.LIVE_METHOD if live else {'options':slot['options'],
                                                                  'default_configuration_id':plan['configuration_ids'][method]})}
            restore_programs = ([f'tool/{selfstar.TOOL}'] + ([] if live else [f'abi/{method}'])) if artifact_limits else []
        elif huff.is_huff0(slot):
            artifact_limits = slot['parts']
            input_bytes = huff.input_bytes(slot)
            fec = method==huff.PLUGIN
            configuration = ({'wire':'FEC1','streams':4,'options':slot['options'],
                              'default_configuration_id':plan['configuration_ids'][method]} if fec else
                             {**plan['protocol_methods'][method],'streams':slot['streams']})
            restore_programs = ([f'tool/{huff.TOOL}'] + ([f'abi/{method}'] if fec else [])) if artifact_limits else []
            if slot.get(bmi2.KEY):
                restore_programs.append(f'tool/{bmi2.TOOL}')
        elif sprintz.is_sprintz(slot):
            artifact_limits = slot['parts']
            input_bytes = sprintz.input_bytes(slot)
            abi = slot['abi']
            shape = slot['shape']
            configuration = ({'wire':'SFB1','algorithm':'fire','path':0} if method==sprintz.PLUGIN else
                             dict(plan['protocol_methods'][method]))
            configuration.update({'dtype':slot['dtype'],'abi_envelope':abi})
            if shape:
                configuration.update({key:shape[key] for key in ('width','dims','message_limit_bytes')})
            if abi:
                configuration.update(options={},default_configuration_id=plan['configuration_ids'][method])
            restore_programs = ([f'tool/{sprintz.TOOL}'] + ([f'abi/{method}'] if abi else [])) if artifact_limits else []
        elif access.is_access(slot):
            artifact_limits = slot['parts']
            input_bytes = slot['original']['bytes']
            configuration = {**access.METHODS[method],'request':slot['request'],'passes':slot['passes'],
                             'callback_limits':slot['limits'] if method==access.LOADED else None}
            restore_programs = [f'tool/{access.TOOL}']
        elif stream.is_stream(slot):
            artifact_limits = slot['parts']
            input_bytes = slot['original']['bytes']
            configuration = {**stream.METHODS[method],'stream':slot['stream'],'policy':slot['policy'],
                             'status_policy':slot['status_policy'],'transform':slot['transform']}
            restore_programs = [f'tool/{stream.TOOL}']
        elif intmult.is_intmult(slot):
            artifact_limits = slot['parts']
            input_bytes = slot['original']['bytes']
            configuration = {**intmult.METHODS[method],**slot['parameters'],'count':slot['count'],
                             'dtype':slot['dtype'],'requested_base':slot['base'],'expected_wire':slot['wire'],
                             'expected_status':slot['expected_status']}
            restore_programs = [f'tool/{intmult.TOOL}'] if artifact_limits else []
        elif state.is_state(slot):
            artifact_limits = slot['parts']
            input_bytes = 16*slot['original']['rows']
            configuration = {**state.METHODS[method],'fixture':slot['name'],'seek':slot['seek'],
                             'prefix':slot['prefix'],'tail':slot['tail'],'observer':'elf-call-interposition-v1'}
            restore_programs = [f'tool/{DIRECT_TOOL}',f'tool/{state.TOOL}']
        elif sessions.is_session(slot):
            artifact_limits = slot['parts']
            input_bytes = sessions.input_bytes(slot)
            configuration = {**sessions.METHODS[method],**{key:slot[key] for key in
                             ('level','parameters','span_limits','restore_spans','call_limit','budget_frame','dictionary_property')}}
            restore_programs = [f'tool/{sessions.TOOL}']
        elif profiles.is_profile(slot):
            artifact_limits = slot['parts']
            input_bytes = profiles.input_bytes(slot)
            configuration = {**profiles.METHODS[method],'native_profile':slot['spec'],'steps':profiles.steps(slot)}
            restore_programs = [f'tool/{profiles.TOOL}'] + ([f'tool/{profiles.SYNC}'] if method==profiles.XZ else [])
        elif decode.is_decode(slot):
            artifact_limits = slot['parts']
            input_bytes = decode.original(slot)['bytes']
            configuration = {**decode.METHODS[method],'fixture':slot['fixture'],'decode_inputs':['frame']}
            restore_programs = [f'tool/{decode.TOOL}']
        elif zfp.is_zfp(slot):
            artifact_limits = slot['parts']
            input_bytes = sum(r['bytes'] for r in slot['inputs'].values())+slot['parts']['metadata']
            configuration = {**zfp.METHODS[method],'spec':slot['spec'],'steps':zfp.steps(slot)}
            restore_programs = [f'tool/{zfp.TOOL}']
        elif training.is_training(slot):
            artifact_limits = slot['parts']
            b = slot['bundle']
            input_bytes = sum(v[k]['bytes'] for v in b['data'].values() for k in ('timestamps','values'))
            recipe = training.steps(slot)
            configuration = {'bundle_id':b['bundle_id'],'steps':recipe,'step_limits':{
                name:training.limits(plan,step['tool']) for name,step in recipe.items()}}
            restore_programs = [f'tool/{training.TOOL}']
        elif corad.is_corad(slot):
            artifact_limits = slot['parts']
            b = slot['bundle']
            input_bytes = b['input']['bytes']+b['quality_policy']['calibration']['bytes']
            configuration = {'bundle_id':b['bundle_id'],'quality_policy_id':b['quality_policy']['policy_id'],
                             'steps':corad.steps(slot)}
            restore_programs = [f'abi/{corad.METHOD}']
        elif pbepla.is_pbepla(slot):
            artifact_limits = slot['parts']
            input_bytes = pbepla.input_bytes(slot)
            recipe = pbepla.steps(slot)
            configuration = {**pbepla.METHODS[method],'spec':slot['spec'],'variant':slot['variant'],'steps':recipe}
            restore_programs = ([f'abi/{pbepla.PLUG}'] if slot['variant'] in ('prefixes','budget-at') else [])
            if method==pbepla.REPLAY:
                restore_programs.append(f'tool/{pbepla.DIRECT}')
        elif 'protocol' in slot:
            config = plan['protocol_methods'][method]
            input_bytes = slot['original']['bytes']
            artifact_limits = slot['parts']
            restore_programs = [f'tool/{WRAPPED_TOOL}']
            configuration = {**config,'native_dtype':slot['native_dtype'],'read_capacity':slot['read_capacity'],'counts':slot['counts']}
        else:
            configuration = {'default_configuration_id':plan['configuration_ids'][method],
                             'options':slot.get('negative_options',plan['methods'][method]['options'])}
            input_bytes = sum(slot['original']['column_bytes'])+slot['original']['schema_bytes']
            artifact_limits = {'frame':slot['max_frame_bytes']} if not slot['expected_status'] else {}
            restore_programs = [f'abi/{method}'] if artifact_limits else []
            if requires_cross(plan,slot):
                restore_programs.append(f'tool/{DIRECT_TOOL}')
        drivers[sid] = {'obligation_ids':sorted(products[sid]),'method':method,'configuration':configuration,
                        'process_limits':batch_limits(plan,slot),'input_bytes':input_bytes,'artifact_byte_ceilings':artifact_limits,
                        'operations':steps,'primary_restore_programs':restore_programs}
    return {'schema':'bmk.native-execution-bindings/1','admission_plan_id':aid,'build_id':plan['build']['build_id'],
            'recovery_id':plan['decoder']['recovery_id'],'bound_routes':len(routes),'total_routes':len(all_routes),
            'bound_obligations':bound,'unbound_obligations':pending,'drivers':drivers,'programs':programs,
            'scope':'candidate_only_no_formal_qualification'}
