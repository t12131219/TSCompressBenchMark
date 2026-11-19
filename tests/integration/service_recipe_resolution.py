"""Run with the matching build mounted read-only as in the offline audit."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import PlanRequest, plan
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.service_recipes import plan_service_recipes, verify_service_recipes


def _write(path, doc):
    path.write_bytes(canonical_bytes(doc)+b'\n')


def _reject(invoke, message):
    try:
        invoke()
    except ContractError as exc:
        require(message in str(exc),f'unexpected rejection: {exc}')
    else:
        raise AssertionError(f'negative case accepted: {message}')


def main(root, bindings, build, path):
    expected = plan_service_recipes(root,bindings,build)
    require(expected==load_json(path),'CLI and Python plans differ')
    scope = plan(root,PlanRequest('first_batch_service_v4')).document
    require(expected['scope_plan_id']==scope['plan_content_id'] and
            all(expected[key]==scope[key] for key in ('scope_id','coverage','native_matrix','cases','inputs','display_cells','atomic_relations')),
            'resolution changed frozen scope')
    slots = expected['required_slots']
    require(len(slots)==564 and all({k:row[k] for k in old if k!='reason'}=={k:v for k,v in old.items() if k!='reason'}
                                    for row,old in zip(slots,scope['required_slots'],strict=True)),
            'required scenario identity or execution status changed')
    require(expected['runnable'] is expected['stage_accepted'] is expected['qualification_granted'] is False,
            'resolution granted qualification')
    by_id = {(s['selection'],expected['cases'][s['case_id']]['id']):s['resolution'] for s in slots}
    counts = Counter(x['state'] for x in by_id.values())
    mechanisms = set()
    for number in (9,19):
        for fmt in ('csv','npy','txt'):
            row = by_id[number,f'traffic-tail-{fmt}']
            [c] = row['candidates']
            require(row['state']=='incompatible_candidates' and not c['comparison_ids'] and
                    c['input_id']==scope['inputs'][f'traffic-tail-{fmt}']['input_id'], 'cross-format source identity or task confused')
            reasons = {r['code']:r for r in c['reasons']}
            require(reasons['service_extent_not_bound']['ingress']=='canonical_before_clock' and
                    reasons['whole_case_deadline_not_enforced']['required_ns']==15_000_000_000 and
                    'memory_bytes' in reasons['service_resource_enforcement_missing']['unavailable'],
                    'diagnostic scope compared as M5 ingress')
            require('source_format_or_group_differs' not in reasons,'matching source format rejected')
            mechanisms.add(c['method_binding_id'])
        [c] = by_id[number,'route-fixed-t']['candidates']
        require(len(c['comparison_ids'])==2 and any(r['code']=='fixed_route_not_qualified' for r in c['reasons']),
                'fixed control was not resolved or was admitted')
    matching_cases = {f'{group}-{fmt}' for group in ('traffic-tail','exact-bits-tail') for fmt in ('csv','npy','txt')} | {
        'bitwise-tail','four-u16-limbs','route-v-only','route-t-only','route-fixed-t','route-fixed-v'}
    require(len(mechanisms)==2 and counts=={'unbound':540,'incompatible_candidates':24} and
            {key for key,r in by_id.items() if r['candidates']}=={(n,c) for n in (9,19) for c in matching_cases},
            'incorrect resolution denominator or matched cases')
    require(not by_id[7,'route-fixed-t']['candidates'] and
            by_id[7,'route-fixed-t']['reasons'][0]['code']=='no_registered_recipe_for_selection',
            'auxiliary T incorrectly attributed as selected codec')
    for number in (9,19):
        r = by_id[number,'csv-invalid-schema']
        require(not r['candidates'] and r['reasons'][0]['expected_reason']=='invalid_source_schema', 'positive recipe credits negative test')
        r = by_id[number,'chunked-stream-tail']
        require(not r['candidates'] and r['reasons'][0]=={'code':'no_registered_recipe_lowering_for_operation','operation':'chunk-stream'},
                'batch recipe mislabelled as stream')
    require('conversion_differs' not in {r['code'] for r in by_id[19,'four-u16-limbs']['candidates'][0]['reasons']} and
            'task_or_control_differs' in {r['code'] for r in by_id[19,'four-u16-limbs']['candidates'][0]['reasons']},
            'TV conversion accepted as V-only')
    altered = deepcopy(expected)
    altered['required_slots'].pop()
    altered['plan_content_id'] = content_id({k:v for k,v in altered.items() if k!='plan_content_id'})
    _reject(lambda: verify_service_recipes(root,altered),'differs from configured resolution')
    with tempfile.TemporaryDirectory(dir=root/'evidence',prefix='recipe-negatives-') as td:
        temp = Path(td)
        spec = load_json(root/bindings)
        doc = spec['recipes'][0]['contributors']
        doc['gorilla-t-alp-f64']['plugin'] = 'gorilla-t-derived'
        changed = temp/'wrong-claim.json'
        _write(changed,spec)
        _reject(lambda: plan_service_recipes(root,changed.relative_to(root).as_posix(),build),'must be the main codec')
        doc['gorilla-t-alp-f64']['plugin'] = 'alp-auto'
        doc['gorilla-t-alp-f64']['selection_id'] = doc['gorilla-t-fire-u16']['selection_id']
        _write(changed,spec)
        _reject(lambda: plan_service_recipes(root,changed.relative_to(root).as_posix(),build),'does not bind the selection archive')
        small = load_json(root/build)
        del small['plugins']['gorilla-t-derived']
        small['build_id'] = content_id({k:v for k,v in small.items() if k!='build_id'})
        changed = temp/'missing-build.json'
        _write(changed,small)
        fallback = plan_service_recipes(root,bindings,changed.relative_to(root).as_posix())
        require(fallback['coverage']==scope['coverage'] and fallback['recipe_resolution']['counts']=={'unbound':564} and
                any(r['code']=='registered_recipe_unavailable' for s in fallback['required_slots'] for r in s['resolution']['reasons']),
                'missing dependency shrank scope or was treated as readiness')
        bad = load_json(root/build)
        bad['worker']['sha256'] = '0'*64
        bad['build_id'] = content_id({k:v for k,v in bad.items() if k!='build_id'})
        _write(changed,bad)
        _reject(lambda: plan_service_recipes(root,bindings,changed.relative_to(root).as_posix()),'SHA-256 mismatch')
    return {'schema':'bmk.service-recipe-controls/1','scope_plan_id':scope['plan_content_id'],'plan_content_id':expected['plan_content_id'],
            'cli_api_parity':True,'resolution':dict(counts),'same_source_matched_separately_from_contract':True,
            'no_auxiliary_attribution':True,'resealed_omission_rejected':True,'wrong_contributor_and_build_rejected':True,
            'missing_dependency_keeps_denominator':True,'qualification_granted':False}


def disabled_check(root):
    config = 'configs/suites/first_batch_service_v4/recipe-bindings.json'
    result = plan_service_recipes(root,config,'build/build-lock.json')
    require(len(result['required_slots'])==564 and result['recipe_resolution']['counts']=={'unbound':564} and
            all(s['status']=='not_run' for s in result['required_slots']), 'disabled provider altered denominator or executed')
    cases = {(s['selection'],result['cases'][s['case_id']]['id']):s for s in result['required_slots']}
    for number in (9,19):
        [r] = cases[number,'route-fixed-t']['resolution']['reasons']
        require(r['code']=='registered_recipe_unavailable' and r['unavailable_recipes'][0]['reasons']==[
            {'code':'recipe_plugin_disabled','plugins':['alp-auto']}], 'disabled provider did not block the comparison')
    return {'disabled_plugin':'alp-auto','obligations':564,'unbound':564,'runnable':False}


if __name__=='__main__':
    if sys.argv[1:]==['--disabled']:
        result = disabled_check(Path.cwd())
    else:
        _, root, bindings, build, plan_file = sys.argv
        result = main(Path(root),bindings,build,Path(plan_file))
    sys.stdout.buffer.write(canonical_bytes(result)+b'\n')
