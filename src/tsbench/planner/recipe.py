"""Freeze declarative recipes supported by the existing complete-object TV runner.

Graph validation is an assertion about a lowering to real operations, not a
free-form interpreter or a qualification result. No options come from test scores.
"""
from collections import Counter
from pathlib import Path

from ..assets import content_id, load_json, local_file, relative_parts, require
from ..contracts import Contract, load_contract
from .tv import GROUPED, compile_tv

SCHEMA = 'recipe'
# (input representations, output representation, inverse, optional codec role)
_OPS = {
    'typed-object': ((), 'original-tv', 'verify-original-object', None),
    'exact-ms': (('original-tv',), 'aligned-tv', 'restore-original-unit', None),
    'chunk-reset': (('aligned-tv',), 'blocked-tv', 'reassemble-in-row-order', None),
    'take-t': (('blocked-tv',), 'i64-ms-axis', 'restore-shared-axis', None),
    'take-v': (('blocked-tv',), 'f64-value-columns', 'restore-value-order', None),
    'pack-limbs': (('f64-value-columns',), 'u16-limb-groups', 'unpack-limbs-bitwise', None),
    'codec-joint': (('blocked-tv',), 'tv-payload', 'decode-joint', 'joint'),
    'codec-t': (('i64-ms-axis',), 't-payload', 'decode-t', 'timestamp'),
    'codec-f64': (('f64-value-columns',), 'v-column-payloads', 'decode-f64', 'value'),
    'codec-u16-group': (('u16-limb-groups',), 'v-group-payload', 'decode-u16-group', 'value'),
    'bundle-joint': (('tv-payload',), 'tv-bundle', 'open-joint-bundle', None),
    'bundle-separate': (('t-payload', 'v-column-payloads'), 'tv-bundle', 'open-separate-bundle', None),
    'bundle-grouped': (('t-payload', 'v-group-payload'), 'tv-bundle', 'open-grouped-bundle', None),
}
_ROOT = ('typed-object', 'exact-ms', 'chunk-reset')
_SPLIT = ('take-t', 'take-v', 'codec-t')
_LOWERINGS = {
    'pair': Counter((*_ROOT, 'codec-joint', 'bundle-joint')),
    'separate': Counter((*_ROOT, *_SPLIT, 'codec-f64', 'bundle-separate')),
    GROUPED: Counter((*_ROOT, *_SPLIT, 'pack-limbs', 'codec-u16-group', 'bundle-grouped')),
}


def _graph(label, nodes, max_depth):
    types, depths = {}, {}
    known = set()
    for node in nodes:
        name, op, inputs = node['id'], node['op'], node['inputs']
        where = f'recipe graph {label}, node {name}'
        require(name not in known, f'{where}: duplicate node')
        require(op in _OPS, f'{where}: operation not implemented by TV runner: {op}')
        require(set(inputs) <= known, f'{where}: unknown, forward or cyclic input')
        input_types, output, inverse, _ = _OPS[op]
        require(tuple(types[i] for i in inputs) == input_types, f'{where}: incompatible input types for {op}')
        require(node['inverse'] == inverse, f'{where}: inverse must be {inverse}')
        depths[name] = 1 + max((depths[i] for i in inputs), default=0)
        require(depths[name] <= max_depth, f'{where}: maximum graph depth exceeded')
        types[name] = output
        known.add(name)
    used = {i for n in nodes for i in n['inputs']}
    last = nodes[-1]['id']
    require(known - used == {last} and types[last] == 'tv-bundle', f'recipe graph {label}: expected one bundle sink and no unused branch')
    return {'depth': depths[last], 'output': last,
            'inverse_order': [{'node': n['id'], 'op': n['inverse']} for n in reversed(nodes)]}


def _conditions(declared, tv):
    m = tv['measurement']
    for cases in tv['comparisons'].values():
        for directions in cases.values():
            for frozen in directions.values():
                c = frozen['contract']
                facts = {'quality': c['quality']['kind'], 'access': c['access']['mode'],
                         'extent': c['boundary']['extent'], 'state': c['boundary']['state'],
                         'ingress': 'canonical_before_clock', 'validation': c['validation']['strength'],
                         'accounting': 'all_serialized_bundle_bytes'}
                require(c['quality']['exact_components'] == ['T','V'] and c['boundary']['size_scope'] == 'bundle',
                        'recipe runner must restore both original components and account for full bundle')
                for key, value in facts.items():
                    require(declared[key] == value, f'recipe condition {key}: runner provides {value}, not {declared[key]}')
                limits = declared['resources']
                for key in ('deadline_ns','max_serialized_bytes','participant_threads'):
                    require(c['resource'][key] <= limits[key], f'recipe resource {key}: configured runner limit exceeds requested bound')
                require(m['resource_enforcement'] == limits['enforcement'],
                        'recipe resource enforcement: runner cannot promise requested isolation')


def bind_recipe(contract: Contract, recipe_path: str, recipe: dict, tv: dict) -> dict:
    """Pure lowering check, also used on the sealed plan without the source tree."""
    relative_parts(recipe_path)
    contract.validate(recipe, recipe_path)
    require(recipe['suite']['path'] == tv['suite_path'], 'recipe refers to a different TV suite')
    require(recipe['suite']['content_id'] == content_id(tv['suite']), 'recipe suite content differs from frozen reference')
    graphs = recipe['graphs']
    methods = recipe['methods']
    require(methods.keys() == tv['methods'].keys(), 'recipe must cover exactly the frozen TV methods')
    require(set(methods.values()) == graphs.keys(), 'recipe has unknown or unused graph')
    orders = {k: _graph(k,g,recipe['max_depth']) for k,g in graphs.items()}
    _conditions(recipe['conditions'], tv)
    routes = {}
    for method, label in methods.items():
        spec = tv['methods'][method]
        nodes = graphs[label]
        require(Counter(n['op'] for n in nodes) == _LOWERINGS[spec['layout']],
                f'recipe graph {label}: not implemented by the {spec["layout"]} lowering for {method}')
        bindings = {}
        for node in nodes:
            role = _OPS[node['op']][3]
            if role:
                bindings[node['id']] = tv['profiles'][spec['routes'][role]]['route_id']
        routes[method] = {'method_id': spec['method_id'], 'graph': label,
                          'graph_id': content_id(nodes), 'codec_routes': bindings}
    body = {'path': recipe_path, 'document': recipe, 'schema_id': contract.document_id,
            'graphs': orders, 'methods': routes, 'execution_plan_id': tv['plan_content_id'],
            'binding_status': 'resolved_for_development', 'qualification_granted': False}
    return {**body, 'recipe_binding_id': content_id(body)}


def compile_recipe(root: Path, recipe_path: str, build: dict, recovery=None, **kwargs) -> dict:
    contract = load_contract(root, SCHEMA)
    recipe = load_json(local_file(root, recipe_path))
    contract.validate(recipe, recipe_path)
    tv = compile_tv(root, recipe['suite']['path'], build, recovery, **kwargs)
    binding = bind_recipe(contract, recipe_path, recipe, tv)
    body = {**{k:v for k,v in tv.items() if k != 'plan_content_id'}, 'recipe_binding': binding}
    return {**body, 'plan_content_id': content_id(body)}


def plan_recipe(root: Path, build_lock: str, recipe_path: str) -> dict:
    return compile_recipe(root, recipe_path, load_json(local_file(root, build_lock)))


def check_sealed_recipe(contract: Contract, plan: dict) -> None:
    binding = plan['recipe_binding']
    body = {k:v for k,v in plan.items() if k not in ('plan_content_id','recipe_binding')}
    tv = {**body, 'plan_content_id': content_id(body)}
    require(binding == bind_recipe(contract,binding['path'],binding['document'],tv),
            'sealed recipe binding differs from TV lowering')
