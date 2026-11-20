"""Derive a separate same-entry M3 input-switch plan, never a new M0 denominator."""
from collections import Counter

from ..assets import content_id, load_json, local_file, require
from ..contracts import load_contract
from ..corpus_ingress import load_full_manifest
from . import m3_real_corpus as base_planner
from .native_corpus import verify_native_corpus_plan

MODE = 'supplemental_new_input_per_selection_v1'
LEGACY = ('datasets/manifests/first-batch-real-v3.json',)
BUILD_FLAGS = ('fixed_batch', 'pcodec_pages', 'titchy_access', 'titchy_stream', 'sprintz_query',
               'gorilla_corpus', 'zfp_corpus', 'pbepla_corpus', 'lzbench_session', 'zstd_dictionary',
               'lzbench_workers', 'huff0_table', 'huff0_fec1', 'corad_corpus')


def _novelty(entries, old):
    ids = {d['id'] for d in old}
    clusters = {d['source_cluster'] for d in old}
    raw = {d[k]['sha256'] for d in old for k in ('asset','file') if k in d}
    objects = {c['object_id'] for d in old for c in [d.get('canonical',{}), *[p.get('canonical',{}) for p in d.get('partitions',[])]] if c}
    values = {c['values_sha256'] for d in old for c in [d.get('canonical',{}), *[p.get('canonical',{}) for p in d.get('partitions',[])]] if c}
    for d in entries:
        require(d['id'] not in ids and d['source_cluster'] not in clusters and d['file']['sha256'] not in raw and
                all(c['object_id'] not in objects and c['values_sha256'] not in values
                    for c in [d['canonical'], *[p['canonical'] for p in d['partitions']]]),
                f"M3 input switch reuses a known input/source identity: {d['id']}")


def plan_input_switch(root, baseline, native_definition):
    root = root.resolve(strict=True)
    ref = base_planner._ref(root, baseline)
    base = load_json(local_file(root, baseline))
    require('input_switch' not in base, 'M3 input switch must reference the accepted full-corpus plan, not another switch')
    base_planner.check_m3_real_corpus_plan(root, base)
    accepted = load_json(local_file(root, base['definition']['plan']['path']))
    new_ref = base_planner._ref(root, native_definition)
    definition = load_json(local_file(root, native_definition))
    verify_native_corpus_plan(root, definition)
    a, b = accepted['bindings'], definition['bindings']
    require(a['manifest'] != b['manifest'] and {k:v for k,v in a.items() if k not in ('manifest','manifest_id')} ==
            {k:v for k,v in b.items() if k not in ('manifest','manifest_id')} and
            accepted['routes']==definition['routes'] and accepted['obligations']==definition['obligations'],
            'M3 input switch must only replace the input manifest, not the route/operation policy or obligations')
    entries = load_full_manifest(root, b['manifest'])['datasets']
    old = load_full_manifest(root, a['manifest'])['datasets']
    for p in LEGACY:
        old += load_json(local_file(root,p))['datasets']
    _novelty(entries, old)
    flags = {key:key in base['build'] for key in BUILD_FLAGS}
    spec = base.get('specialized',{})
    routes, work, _ = base_planner._project_definition(definition, **flags, sprintz_batch='sprintz' in spec,
                                                        selfstar='selfstar' in spec, titchy_batch='titchy' in spec)
    require(routes == base['routes'], 'M3 input switch changed effective route bindings')
    states = Counter(w['applicability'] for w in work)
    require(set(states)<= {'input_domain_matches','outside_declared_domain','condition_not_triggered'},
            'M3 input switch has unresolved input applicability')
    eligible = {w['selection'] for w in work if w['applicability']=='input_domain_matches'}
    require(eligible=={r['selection'] for r in routes}, 'M3 input switch lacks a legal input for at least one selection')
    coverage = {**base['coverage'], 'datasets':len(entries), 'file_route_decisions':len(work),
                **{s:states[s] for s in ('input_domain_matches','outside_declared_domain','condition_not_triggered')},
                'required_obligations':0,'conditional_obligations':0,'executable_work_items':states['input_domain_matches']}
    # The baseline identity binds the exact build and contracts. The supplemental
    # run has no named specialist obligations or original timing population.
    body = {k:v for k,v in base.items() if k not in ('plan_content_id','measurement','corad_specialist_amendment')}
    body.update(definition={'plan':new_ref,'plan_content_id':definition['plan_content_id'],'coverage':definition['coverage']},
                work_items=work, obligations=[], coverage=coverage,
                execution_policy={**base['execution_policy'],'input_scope':MODE},
                input_switch={'baseline':ref,'baseline_plan_id':base['plan_content_id'],
                              'additional_novelty_manifests':[base_planner._ref(root,p) for p in LEGACY],
                              'eligible_selections':sorted(eligible),'does_not_replace_full_corpus_or_specialists':True})
    result = {**body,'plan_content_id':content_id(body)}
    load_contract(root,'m3-real-corpus-plan').validate(result, 'M3 input switch')
    return result


def check_input_switch(root, plan):
    switch = plan['input_switch']
    require(plan == plan_input_switch(root,switch['baseline']['path'],plan['definition']['plan']['path']),
            'M3 input switch plan differs from the rebuilt same-entry configuration')
