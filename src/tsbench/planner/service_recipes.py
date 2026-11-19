"""Reconcile the complete frozen service scope with real TV recipe lowerings.

This is resolution, not service execution or admission. The registry binds the
selected algorithm to the main (V or joint) branch; an auxiliary T is not a
second measured algorithm. No historical report is an input to this planner.
"""
from collections import Counter, defaultdict
from pathlib import Path

from ..api import PlanRequest, check_sources, plan
from ..assets import (canonical_bytes, content_id, digest, load_json, local_file,
                      require, verify_asset)
from ..contracts import load_contract
from ..plugins import discover, registrations
from ..runtime import SCHEMA as BUILD_SCHEMA
from .recipe import SCHEMA as RECIPE_SCHEMA, compile_recipe
from .service_scope import PLAN_SCHEMA as SCOPE_SCHEMA
from .tv import INGRESS_SUITE_SCHEMA, LIMBS, suite_schema_name

SCHEMA = 'service-recipe-bindings'
PLAN = 'bmk.service-recipe-plan/1'
TV_OPERATIONS = {'ingress', 'typed-restore', 'typed-route', 'type-conversion', 'detached-restore'}


def _reason(code, **facts):
    return {'code': code, **facts}


def _roster(root, registry, scope, build):
    by_id = {r['selection_id']:r for r in scope['selection_rows']}
    sources = check_sources(root, source_ids=set())['sources_lock_id']
    paths = set()
    methods, offers, absent, closure = {}, defaultdict(list), defaultdict(list), {}
    registered = registrations(root)
    for entry in registry['recipes']:
        ref = entry['recipe']
        path = ref['path']
        require(path not in paths, f'duplicate service recipe: {path}')
        paths.add(path)
        recipe = load_json(verify_asset(root,ref))
        load_contract(root,RECIPE_SCHEMA).validate(recipe,path)
        suite = load_json(local_file(root,recipe['suite']['path']))
        load_contract(root,suite_schema_name(suite)).validate(suite,recipe['suite']['path'])
        require(content_id(suite)==recipe['suite']['content_id'], f'stale recipe suite: {path}')
        required = {p['plugin'] for p in suite['profiles'].values()}
        missing = sorted(required-registered.keys())
        disabled = sorted(p for p in required & registered.keys() if not registered[p]['enabled'])
        unbuilt = sorted((required & registered.keys())-set(disabled)-build['plugins'].keys())
        unavailability = [r for r in (
            _reason('recipe_plugin_not_registered', plugins=missing),
            _reason('recipe_plugin_disabled', plugins=disabled),
            _reason('recipe_plugin_not_in_build', plugins=unbuilt),
        ) if r['plugins']]
        declared = discover(root, selected=required)
        contributors = []
        for method, claim in entry['contributors'].items():
            require(method in suite['methods'], f'unknown method {method} in {path}')
            branches = suite['methods'][method]
            main = branches['joint'] if 'joint' in branches else branches['value']
            plugin, selection = claim['plugin'], claim['selection_id']
            require(plugin==suite['profiles'][main]['plugin'] and selection in by_id,
                    f'invalid selected contributor for {path}/{method}: must be the main codec of a first-batch selection')
            row = by_id[selection]
            if declared.get(plugin,{}).get('enabled'):
                source_lock = check_sources(root,source_ids={row['source_id']})
                source = source_lock['sources'][row['source_id']]['archive']
                require(row in source_lock['selections'] and source_lock['sources_lock_id']==sources and
                        declared[plugin]['source_hashes'].get(source['path'])==source['sha256'],
                        f'main codec does not bind the selection archive: {path}/{method}')
            contributors.append((method,plugin,row))
        if unavailability:
            for method, _, row in contributors:
                absent[row['number']].append({'recipe':path,'method':method,'reasons':unavailability})
            continue
        tv = compile_recipe(root,path,build)
        bid = tv['recipe_binding']['recipe_binding_id']
        r = tv['recovery']
        closure[bid] = {'recipe':ref,'tv_plan_id':tv['plan_content_id'],'recovery':r,
                        'recovery_bytes':sum(f['bytes'] for f in r['files'].values())}
        for method, plugin, row in contributors:
            route = tv['methods'][method]
            refs = {role:tv['profiles'][p] for role,p in route['routes'].items()}
            method_body = {'path':path,'recipe_binding_id':bid,'method':method,'method_id':route['method_id'],
                   'selection_id':row['selection_id'],'primary_plugin':plugin,'build_id':build['build_id'],
                   'method_spec':route['method_spec'],'routes':refs,'origin':'C'}
            mid = content_id(method_body)
            methods[mid] = method_body
            # Index scheduled slots, never the method × input cross-product.
            for slot in tv['slots']:
                if slot['method']==method:
                    offers[row['number']].append((mid,tv,slot))
    return sources, methods, offers, absent, closure


def _same_source(input_fact, tv_fact):
    return (input_fact['kind']=='typed_source' and
            tv_fact['source'].get('ingress',{}).get('manifest')==input_fact['manifest']['path'] and
            all(input_fact.get(k)==tv_fact.get('lineage',{}).get(k) for k in
                ('manifest_id','source_file_hash','ingestion_id','canonical_dataset_hash','source_column_sha256')))


def _candidate(mid, tv, slot, case, source, service, budget):
    tv_case, method = slot['case'], slot['method']
    fact = tv['cases'][tv_case]
    if not _same_source(source,fact):
        return None
    b = tv['recipe_binding']
    impl = tv['methods'][method]
    cond = b['document']['conditions']
    cids, reasons = [], []
    desired_control = case['parameters'].get('control')
    options = [(label,tv['comparisons'][label][tv_case]) for label in slot['comparisons']]
    matched = [(label,d) for label,d in options if d['encode']['contract']['task']==case['task'] and
               (d['encode']['contract']['control'] or {}).get('kind')==desired_control]
    if matched:
        cids = [directions[k]['comparison_id'] for _,directions in matched for k in ('encode','decode')]
    else:
        reasons.append(_reason('task_or_control_differs', required={'task':case['task'],'control':desired_control},
                               available=[{'task':d['encode']['contract']['task'],
                                           'control':(d['encode']['contract']['control'] or {}).get('kind')} for _,d in options]))
    if cond['quality']!=case['quality']:
        reasons.append(_reason('quality_differs', required=case['quality'], available=cond['quality']))
    if 'C' not in service['permitted_origins']:
        reasons.append(_reason('mechanism_not_permitted', available='C', required=service['permitted_origins']))
    params = case['parameters']
    if 'chunk_rows' in params and params['chunk_rows']!=tv['suite']['chunk_rows']:
        reasons.append(_reason('chunk_rows_differ',required=params['chunk_rows'],available=tv['suite']['chunk_rows']))
    op = service['operation']
    if op=='ingress':
        fmt = source['ingestion']['plugin']
        group = fact['source']['ingress']['group']
        if (fmt,group)!=(params['format'],params['canonical_group']):
            reasons.append(_reason('source_format_or_group_differs', available=[fmt,group],
                                   required=[params['format'],params['canonical_group']]))
    if op=='type-conversion':
        lowering = impl['method_spec']['conversion']
        if (params.get('transform'),lowering)!=('f64_le_u16x4',LIMBS):
            reasons.append(_reason('conversion_differs',required=params.get('transform'),available=lowering))
    if op=='typed-route' and desired_control and matched:
        reasons.append(_reason('fixed_route_not_qualified', control=desired_control))
    # The diagnostic records per-process timings, setup and replay separately.
    # None of that proves a single declared service extent through validation.
    reasons.append(_reason('service_extent_not_bound', required=service['measurement_extent'],
                           available=cond['extent'], ingress=cond['ingress'], charges=service['charge']))
    # Require service-wide limits, not planned participant count or an RSS observation.
    limits = options[0][1]['encode']['contract']['resource']
    reasons.extend((_reason('service_resource_enforcement_missing',
                            unavailable=['cpu_slots','memory_bytes','work_bytes'],
                            required={k:budget[k] for k in ('cpu_slots','memory_bytes','work_bytes')},
                            available=cond['resources']['enforcement']),
                    _reason('whole_case_deadline_not_enforced',required_ns=budget['wall_ms']*10**6,
                            available_per_direction_ns=limits['deadline_ns']),
                    _reason('service_oracle_not_bound',required=case['outcome']['oracle'],
                            available='TV artifact_each and separate files-only recovery audit')))
    if limits['max_serialized_bytes']>budget['product_bytes']:
        reasons.append(_reason('product_limit_exceeds_budget',required=budget['product_bytes'],available=limits['max_serialized_bytes']))
    return {'method_binding_id':mid,'recipe_slot_id':slot['slot_id'],'case':tv_case,
            'input_id':source['input_id'],'comparison_ids':cids,'reasons':reasons}


def _resolve_slot(scope, slot, offers, absent):
    case = scope['cases'][slot['case_id']]
    service = scope['service_contracts'][case['requirement']]
    op, selection = service['operation'], slot['selection']
    blocked = []
    if slot['required_terminal']=='expected_rejection':
        blocked.append(_reason('negative_case_driver_not_registered', expected_reason=case['outcome']['reason'],
                               operation=op, oracle=case['outcome']['oracle']))
    if op not in TV_OPERATIONS:
        blocked.append(_reason('no_registered_recipe_lowering_for_operation', operation=op))
    if not offers[selection]:
        blocked.append(_reason('registered_recipe_unavailable' if absent[selection] else 'no_registered_recipe_for_selection',
                               **({'unavailable_recipes':absent[selection]} if absent[selection] else {})))
    candidates = []
    if not blocked:
        inputs = case['inputs']
        if len(inputs)==1:
            source = scope['inputs'][inputs[0]]
            budget = scope['resources'][case['resource']]
            candidates = [c for mid,tv,scheduled in offers[selection]
                          if (c:=_candidate(mid,tv,scheduled,case,source,service,budget)) is not None]
        if not candidates:
            blocked.append(_reason('input_not_scheduled_by_registered_recipe', required_input_ids=case['input_ids'],
                                   match='exact_typed_source_manifest_ingestion_and_original_columns'))
    resolution = {'state':'incompatible_candidates' if candidates else 'unbound',
                  'reasons':blocked,'candidates':candidates}
    return {**slot,'reason':resolution['state'] if candidates else blocked[0]['code'],'resolution':resolution}


def plan_service_recipes(root: Path, bindings: str, build_lock: str, max_workers: int = 1) -> dict:
    contract = load_contract(root,SCHEMA)
    registry = load_json(local_file(root,bindings))
    contract.validate(registry,bindings)
    scope = plan(root,PlanRequest(registry['scope_suite'],max_workers)).document
    require(scope['schema']==SCOPE_SCHEMA, 'recipe bindings require a complete service scope')
    build = load_json(local_file(root,build_lock))
    require(isinstance(build,dict) and set(build)=={'schema','worker','plugins','build_id'} and
            build['schema']==BUILD_SCHEMA and isinstance(build['plugins'],dict) and
            build['build_id']==content_id({k:v for k,v in build.items() if k!='build_id'}), 'invalid service recipe build lock')
    sources, methods, offers, absent, closure = _roster(root,registry,scope,build)
    slots = [_resolve_slot(scope,s,offers,absent) for s in scope['required_slots']]
    summary = Counter(s['resolution']['state'] for s in slots)
    body = {**{k:v for k,v in scope.items() if k not in ('schema','plan_content_id','required_slots')},
            'schema':PLAN,'scope_plan_id':scope['plan_content_id'],'required_slots':slots,
            'recipe_resolution':{'request':{'bindings':bindings,'build_lock':build_lock,'max_workers':max_workers},
                                 'registry_id':content_id(registry),'registry_schema_id':contract.document_id,
                                 'resolver_sha256':digest(local_file(root,'src/tsbench/planner/service_recipes.py')),
                                 'sources_lock_id':sources,'build':build,'methods':methods,'lowerings':closure,
                                 'counts':dict(summary),'runnable_slots':0}}
    return {**body,'plan_content_id':content_id(body)}


def verify_service_recipes(root: Path, frozen: dict) -> dict:
    require(isinstance(frozen,dict) and frozen.get('schema')==PLAN, 'invalid service recipe plan')
    request = frozen['recipe_resolution']['request']
    require(isinstance(request,dict) and set(request)=={'bindings','build_lock','max_workers'}, 'invalid service recipe request')
    expected = plan_service_recipes(root,**request)
    require(canonical_bytes(expected)==canonical_bytes(frozen), 'frozen service recipe plan differs from configured resolution')
    return {'schema':'bmk.service-recipe-plan-verification/1','plan_content_id':expected['plan_content_id'],
            'scope_plan_id':expected['scope_plan_id'],'coverage':expected['coverage'],
            'resolution':expected['recipe_resolution']['counts'],'runnable':False,'qualification_granted':False}
