"""Compile the first-batch service workload contract, not an M5 executor.

The output has one slot per selection × scenario and separate display/atomic
relations. It never accepts historical native results as service qualification.
"""
from collections import Counter, defaultdict
from math import prod
from pathlib import Path

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require, verify_asset
from ..contracts import load_contract
from ..corpus import PROFILES, load_boundary_fixtures
from ..ingress import load_typed_source, sha
from .corpus_windows import bind_service_window, read_labeled_tv_window


SCHEMA = 'bmk.service-suite/1'
PLAN_SCHEMA = 'bmk.service-scope-plan/1'
TASKS = {'values_only', 'timestamps_only', 'shared_t_controlled', 'whole_object'}
PROVENANCE = 'not_run_no_build_bound'

# Parameters are closed *per workload*, not simply a union of known keys.
PARAMETERS = {
    'ingress': [('format', 'canonical_group'), ('format', 'canonical_group', 'mutation')],
    'typed-restore': [(), ('chunk_rows',)],
    'type-conversion': [('transform', 'chunk_rows'), ('transform',)],
    'masked-restore': [()],
    'bounded-quantize': [('max_abs_error_ppm_of_unit', 'nonfinite')],
    'verified-repair': [('raw_fallback', 'fault')],
    'typed-route': [('chunk_rows',), ('chunk_rows', 'control'), ('time_conversion',)],
    'parallel-blocks': [('chunk_rows', 'budgets')],
    'effective-isa': [('backend',)],
    'chunk-stream': [('chunk_rows', 'max_buffer_rows', 'max_queued_packets', 'arrival_batch_rows', 'arrival_interval_ns', 'consumer')],
    'point-read': [('row',)],
    'range-read': [('begin', 'end', 'chunk_rows'), ('begin', 'end')],
    'query': [('begin', 'end', 'reductions', 'sum_policy', 'nonfinite')],
    'progressive': [('level_abs_error_ppm_of_unit',)],
    'durable-update': [('row', 'new_f64_bits', 'chunk_rows')],
    'checkpoint-replay': [('chunk_rows', 'stopped_after_rows'), ('chunk_rows', 'stopped_after_rows', 'mutation')],
    'deployment': [('assets',), ('assets', 'mutation')],
    'budgeted-search': [('max_trials', 'seed', 'test_trials', 'objective')],
    'detached-restore': [('fresh_process',)],
    'observe': [('passes', 'exclusive')],
}
REJECTION_OPERATIONS = {
    'invalid_source_schema': 'ingress', 'checked_cast_overflow': 'type-conversion',
    'nonfinite_outside_quality_domain': 'bounded-quantize', 'nonintegral_time_unit': 'typed-route',
    'out_of_bounds': {'point-read', 'range-read'}, 'corrupt_checkpoint': 'checkpoint-replay',
    'missing_asset': 'deployment', 'different_asset': 'deployment',
}


def _unique(items, key):
    out = {item[key]: item for item in items}
    require(len(out) == len(items), f'duplicate service {key}')
    return out


def _bounds_inputs(root, predecessor_suite, corpus_id, declarations):
    features = load_json(local_file(root, predecessor_suite['corpus_feature_policy']))
    boundary_manifest, _, _ = load_boundary_fixtures(root, features['boundary_manifest'])
    widths = {'b1': 1, 'i1': 1, 'u1': 1, 'i2': 2, 'u2': 2, 'i4': 4, 'u4': 4, 'i8': 8, 'u8': 8, 'f4': 4, 'f8': 8}
    inputs = {}
    origins = {}
    data_manifest = predecessor_suite['corpus']
    for label, definition in declarations.items():
        kind = definition['kind']
        if kind == 'typed_source':
            manifest = definition['manifest']
            verify_asset(root, manifest)
            bound, columns = load_typed_source(root, manifest['path'])
            spec, origin = bound['ingestion']['object'], definition['origin']
            if origin['kind']=='corpus_partition':
                request = {k:v for k,v in origin.items() if k!='kind'}
                request['count'] = spec['rows']
                key = content_id([request, spec])
                if key not in origins:
                    windows, checksums = [], []
                    for column in spec['values']:
                        window = bind_service_window(root,data_manifest,corpus_id,{**request,'column':column['name']})
                        axis, ticks, values = read_labeled_tv_window(root,window)
                        declared_axis = spec['timestamp']
                        require(declared_axis['unit']=='s' and axis['unit']=='second' and
                                all(axis[f]==declared_axis[f] for f in ('epoch','timezone','interpretation')),
                                'source copy time semantics differ from corpus')
                        checksums.append([sha(ticks),sha(values)])
                        windows.append(window)
                    require(windows and len({h[0] for h in checksums})==1, 'source copy does not share one time axis')
                    base = {k:v for k,v in windows[0].items() if k!='column'}
                    origins[key] = ({**origin,'window':base,'columns':spec['values']},
                                    [checksums[0][0],*(h[1] for h in checksums)])
                origin, hashes = origins[key]
                require(bound['source_column_sha256']==hashes, 'declared cross-format copy differs from source corpus window')
            value = {**bound, 'manifest': manifest, 'origin':origin,'rows': spec['rows'],
                     'logical_bytes': sum(map(len, columns))}
        elif kind == 'boundary_arrays':
            refs = boundary_manifest['files']
            selected = definition['arrays']
            require(set(selected) <= refs.keys(), f'unknown boundary arrays: {label}')
            arrays = {name: refs[name] for name in selected}
            value = {'boundary_manifest_id': content_id(boundary_manifest), 'arrays': arrays,
                     'logical_bytes': sum(prod(ref['shape']) * widths[ref['dtype'][1:]] for ref in arrays.values()),
                     'metadata': {name: boundary_manifest[name] for name in ('different_axes', 'timestamp_semantics', 'float_special')}}
        else:
            window = bind_service_window(root, data_manifest, corpus_id, {k:v for k,v in definition.items() if k != 'kind'})
            axis, ticks, column = read_labeled_tv_window(root, window)
            value = {'rows': window['count'], 'window': window, 'timestamp': {**axis, 'dtype': '<i8'},
                     'value_dtype': '<f8','value_unit':dict(PROFILES[window['profile']][0])[window['column']], 'columns_sha256': [sha(ticks), sha(column)], 'logical_bytes': len(ticks) + len(column)}
        item = {'kind':kind, **value}
        inputs[label] = {**item, 'input_id': content_id(item)}
    return inputs


def _check_cases(workloads, inputs, max_validation_workers):
    cases = _unique(workloads['cases'], 'id')
    resources, contracts = workloads['resources'], workloads['contracts']
    require({c['resource'] for c in cases.values()} == resources.keys() and
            {name for c in cases.values() for name in c['inputs']} == inputs.keys(), 'service case input/resource closure differs')
    for r in resources.values():
        require(r['max_workers'] <= r['cpu_slots'] <= max_validation_workers and
                r['product_bytes'] <= r['work_bytes'] <= r['memory_bytes'], 'service resource ceilings are inconsistent')
    use, source_groups = defaultdict(list), defaultdict(list)
    for name,c in cases.items():
        atom, p, outcome = c['requirement'], c['parameters'], c['outcome']
        require(atom in contracts, f'unknown service atom: {atom}')
        op = contracts[atom]['operation']
        require(op in PARAMETERS and any(p.keys()==set(fields) for fields in PARAMETERS[op]),
                f'unknown or missing parameters for service operation {op}: {name}')
        r = resources[c['resource']]
        assets = [inputs[ref] for ref in c['inputs']]
        require(sum(x['logical_bytes'] for x in assets) <= r['work_bytes'], f'case input exceeds work budget: {name}')
        is_negative = outcome['kind'] == 'expected_rejection'
        if is_negative:
            key = REJECTION_OPERATIONS[outcome['reason']]
            require(op in key if isinstance(key, set) else op == key, f'wrong rejection oracle for {name}')
        require(c['quality']=={'bounded-quantize':'bounded_absolute','progressive':'bounded_refinement'}.get(op,'bitwise_exact'),
                f'service operation has inconsistent quality domain: {name}')
        rows = assets[0].get('rows', 0)
        if op == 'ingress':
            require(len(assets)==1 and assets[0]['kind']=='typed_source' and
                    assets[0]['ingestion']['plugin']==p['format'] and atom==f"source/{p['format']}_v1" and
                    is_negative==('mutation' in p), f'source contract does not match the loader asset: {name}')
            if not is_negative:
                source_groups[p['canonical_group']].append((p['format'],assets[0]['canonical_dataset_hash'],
                    assets[0]['source_file_hash'],content_id(assets[0]['origin'])))
        if 'row' in p:
            require(rows and (p['row'] >= rows)==is_negative, f'point/update lies outside the expected domain: {name}')
        if 'end' in p:
            require(rows and p['begin']<p['end'] and (p['end']>rows)==is_negative,
                    f'range does not match the expected domain: {name}')
        if op == 'parallel-blocks':
            require(p['budgets']==[1,2] and r['max_workers']>=2 and rows>p['chunk_rows'], 'parallel workload lacks matched budgets or blocks')
        if op == 'chunk-stream':
            require(rows>p['max_buffer_rows']>=p['chunk_rows']>=p['arrival_batch_rows'] and
                    p['chunk_rows'] % p['arrival_batch_rows']==0 and rows % p['chunk_rows']!=0,
                    'stream workload does not exercise buffer, arrival and partial tail')
        if op == 'checkpoint-replay':
            require(0 < p['stopped_after_rows'] < rows and p['stopped_after_rows'] % p['chunk_rows']==0 and
                    is_negative==('mutation' in p), 'checkpoint requires a real restart boundary and tail')
        if op == 'deployment':
            require(p.get('mutation')==outcome.get('reason'), 'deployment mutation/expected terminal differ')
        if op == 'progressive':
            levels = p['level_abs_error_ppm_of_unit']
            require(levels[-1]==0 and all(a>b for a,b in zip(levels,levels[1:])), 'progressive levels must tighten to exact terminal')
        if op == 'budgeted-search':
            require(len(assets)==3 and all(x['kind']=='corpus_window' for x in assets), 'training split assets are missing')
            windows = [x['window'] for x in assets]
            require([x['partition'] for x in windows]==['train','development','test'] and
                    len({x['partition_canonical_id'] for x in windows})==3 and
                    len({(x['dataset'],x['column'],x['source_cluster']) for x in windows})==1,
                    'training, development and test must be chronological, disjoint and from the same source')
        cbody = {**c,'input_ids': [x['input_id'] for x in assets], 'service_contract_id': content_id(contracts[atom]),
                 'resource_id': content_id(r)}
        use[atom].append({**cbody,'case_id':content_id(cbody)})
    require(len(source_groups)>=2 and all({r[0] for r in rows}=={'csv','npy','txt'} and len(rows)==3 and
                len({r[1] for r in rows})==len({r[3] for r in rows})==1 and len({r[2] for r in rows})==3
                for rows in source_groups.values()) and
            len({rows[0][1] for rows in source_groups.values()})==len(source_groups), 'cross-format canonical identities differ')
    route = use['route/whole_object_v1']
    require({c['task'] for c in route if c['outcome']['kind']=='verified'}==TASKS and
            {(c['task'],c['parameters']['control']) for c in route if 'control' in c['parameters']}==
            {('shared_t_controlled','fixed_timestamp_route'),('whole_object','fixed_value_route')}, 'four T/V tasks or controls missing')
    require(use.keys()==contracts.keys() and all(any(c['outcome']['kind']=='verified' for c in items) for items in use.values()),
            'service contract must have a positive workload for every atom')
    return use


def plan_service_scope(root: Path, request, suite: dict, suite_path: str, registry: dict) -> dict:
    from ..api import PlanRequest, plan

    schemas = {name:load_contract(root,name) for name in ('service-suite','service-workloads')}
    schemas['service-suite'].validate(suite, suite_path)
    require(suite['id']==request.suite, 'suite registry/contract identity mismatch')
    predecessor = suite['predecessor']
    require(predecessor['id'] != request.suite and registry['suites'].get(predecessor['id'])==predecessor['suite']['path'],
            'service predecessor does not match registry')
    draft_suite = load_json(verify_asset(root,predecessor['suite']))
    require(draft_suite.get('schema')=='bmk.suite/1','service predecessor must be the preserved M0 draft')
    # The expanding scope inherits its original row/atom denominator, not the old status.
    draft = plan(root, PlanRequest(predecessor['id'],request.max_workers)).document
    # Freeze historical semantics, not the installed catalog: adding or disabling
    # a plugin is allowed and changes the resolved plan identity, not the scope lock.
    require({k:v for k,v in draft['bindings'].items() if k!='plugin_catalog'} == suite['inherited_locks'],
            'inherited service sources, fixtures or policy changed; version the suite')
    workloads = load_json(verify_asset(root,suite['workloads']))
    schemas['service-workloads'].validate(workloads,suite['workloads']['path'])
    require(workloads['contracts'].keys()==draft['atomic_semantics'].keys(), 'service contract atom denominator differs from draft')
    inputs = _bounds_inputs(root,draft_suite,draft['corpus']['corpus_id'],workloads['inputs'])
    compiled = _check_cases(workloads,inputs,draft_suite['policies']['max_validation_workers'])
    native_inventory = load_json(local_file(root,draft_suite['native_inventory']))
    require(content_id(native_inventory)==draft['bindings']['native_inventory'], 'native inventory changed during compilation')
    scope_bindings = {'predecessor_scope_id':draft['scope_id'], 'suite_id':content_id(suite), 'workloads':suite['workloads'],
                      'native_inventory':draft['bindings']['native_inventory'],
                      'inputs':{key:x['input_id'] for key,x in inputs.items()},
                      'schemas':{name:x.document_id for name,x in schemas.items()},
                      'planner_code':{p:digest(local_file(root,p)) for p in ('src/tsbench/api.py',
                          'src/tsbench/planner/service_scope.py','src/tsbench/planner/corpus_windows.py')}}
    scope_id = content_id(scope_bindings)
    cases, relations, slots, display = {}, [], [], []
    cell_relations = defaultdict(list)
    for entry in draft['required_slots']:
        atom, selection = entry['requirement'], entry['selection']
        rid = content_id([scope_id,entry['selection_id'],atom])
        obligations = []
        for case in compiled[atom]:
            cid = case['case_id']
            cases[cid] = case
            sid = content_id([rid,cid])
            obligations.append(sid)
            slots.append({'slot_id':sid,'atomic_relation_id':rid,'case_id':cid,'selection':selection,
                          'required_terminal':case['outcome']['kind'],'status':'not_run',
                          'reason':'no_qualified_recipe_build_and_validator_binding'})
        relations.append({'id':rid,'predecessor_slot_id':entry['slot_id'],'selection':selection,'group':entry['group'],
                          'requirement':atom,'slots':obligations,'status':'not_run'})
        cell_relations[(selection,entry['group'])].append(rid)
    for cell in draft['display_cells']:
        ids = cell_relations[(cell['selection'],cell['group'])]
        require(len(ids)==len(cell['slots']), 'display relation partition differs')
        display.append({'selection':cell['selection'],'group':cell['group'],'atomic_relations':ids,'status':'not_run'})
    totals = Counter(s['required_terminal'] for s in slots)
    counts = {k: draft['coverage'][k] for k in ('selections','groups','atomic_requirements','display_cells','atomic_relations')}
    counts.update(cases=len(cases),case_obligations=len(slots),rejection_obligations=totals['expected_rejection'])
    require(counts==suite['expected_counts'] and len({s['slot_id'] for s in slots})==len(slots), 'service case denominator differs')
    body = {'schema':PLAN_SCHEMA,'definition_stage':'M0','target_stage':'M5','suite_id':request.suite,'scope_id':scope_id,
            'predecessor_plan_id':draft['plan_content_id'],'bindings':scope_bindings,
            'runnable':False,'stage_accepted':False,'qualification_granted':False,'policies':suite['policies'],
            'resolved_execution':{'max_validation_workers':request.max_workers,'performance_candidates_concurrent':False,
                                  'job_inner_and_outer_workers_share_case_cpu_slots':True},
            'coverage':{**counts,'executed':0,'qualified':0,'unrun':len(slots)},'inputs':inputs,'cases':cases,
            'resources':workloads['resources'],'service_contracts':workloads['contracts'],'corpus':draft['corpus'],
            'selection_rows':draft['selection_rows'],'display_groups':draft['display_groups'],
            'native_matrix':{'state':PROVENANCE,'inventory':native_inventory['entries']},'display_cells':display,
            'atomic_relations':relations,'required_slots':slots,
            'estimates':{'max_case_input_logical_bytes':max(sum(inputs[i]['logical_bytes'] for i in c['inputs']) for c in cases.values()),
                         'reserved_case_work_bytes_upper_bound':max(r['work_bytes'] for r in workloads['resources'].values())*request.max_workers,
                         'aggregate_case_product_cap_bytes':sum(workloads['resources'][cases[s['case_id']]['resource']]['product_bytes']
                                                                for s in slots if s['required_terminal']=='verified'),
                         'decoder_closure_and_ledger_bytes':None,'enforcement':'not_bound_to_executor'}}
    return {**body,'plan_content_id':content_id(body)}


def verify_service_plan(root: Path, frozen: dict) -> dict:
    """Re-derive the service definition; a self-consistent edit is not evidence."""
    from ..api import PlanRequest, plan

    require(isinstance(frozen,dict) and frozen.get('schema')==PLAN_SCHEMA and type(frozen.get('suite_id')) is str and
            isinstance(frozen.get('resolved_execution'),dict), 'invalid frozen service plan document')
    workers = frozen['resolved_execution'].get('max_validation_workers')
    require(type(workers) is int, 'frozen service plan is missing its validation worker request')
    expected = plan(root,PlanRequest(frozen['suite_id'],workers)).document
    require(canonical_bytes(expected)==canonical_bytes(frozen), 'frozen service plan differs from configured workload closure')
    return {'schema':'bmk.service-plan-verification/1','plan_content_id':expected['plan_content_id'],
            'scope_id':expected['scope_id'],'coverage':expected['coverage'],'verified_definition':True,
            'runnable':False,'stage_accepted':False,'qualification_granted':False}
