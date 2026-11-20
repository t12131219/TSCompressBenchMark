"""Verify one complete supplemental run without reclassifying official M3 evidence."""
from collections import Counter, defaultdict

from ..assets import content_id, load_json, local_file, require
from ..contracts import load_contract
from ..corpus_ingress import load_full_manifest
from ..planner.m3_input_switch import MODE, check_input_switch
from .m3_full_custody import _references, _inventory, _known_file
from .m3_ledger_census import CORPUS_STATES, _unit_census
from .m3_sealed_ledger import full_run_source, full_run_rows


def audit(root, plan, run):
    require('input_switch' in plan, 'expected a supplemental input switch, not the full M3 plan')
    check_input_switch(root,plan)
    ledger, seal = full_run_source(plan,run)
    report = load_json(local_file(run,'report.json'))
    load_contract(root,'m3-real-corpus-run').validate(report,'M3 input switch run')
    require(report['plan_content_id']==plan['plan_content_id'] and report['run_id']==run.name and
            not report['partial_preflight'] and report['route_filter'] is None and 'dataset_filter' not in report and
            'max_work_items' not in report and not any(report[k] for k in ('obligations','obligation_statuses','specialized')) and
            report['execution_policy']==plan['execution_policy'] and plan['execution_policy']['input_scope']==MODE and
            report['selected_work_items']==plan['coverage']['input_domain_matches'] and
            report['selected_corpus_decisions']==report['planned_work_items']==len(plan['work_items'])==len(report['rows']),
            'M3 input switch audit requires the complete supplemental run without filters')
    definition = load_json(local_file(root,plan['definition']['plan']['path']))
    entries = {d['id']:d for d in load_full_manifest(root,definition['bindings']['manifest'],parse=True)['datasets']}
    rows, refs = [], {}
    by_selection = defaultdict(Counter)
    for n,(row,item) in enumerate(full_run_rows(plan,ledger)):
        require(item is not None and 'entry_kind' not in row and row==report['rows'][n],
                'M3 input switch ledger and report differ')
        status, evidence = row['status'], row['evidence']
        if item['applicability']=='input_domain_matches':
            require(status in CORPUS_STATES and (evidence is not None and not row['reason'] if status=='verified' else bool(row['reason'])),
                    'M3 input switch terminal differs from applicable plan')
        else:
            require(status==item['applicability'] and row['reason']=='; '.join(item['reasons']) and evidence is None,
                    'M3 input switch must account for nonapplicable decisions')
        c = _unit_census(item,row,plan['build'].get('fixed_batch'))
        require(c is None or c['matches_frozen_units'], 'M3 input switch consumed unexpected native batch units')
        for path, ref in _references(evidence):
            require(ref == refs.setdefault(path,ref), 'M3 input switch has conflicting retained-file identities')
        source = entries[item['dataset_id']]
        require(item['canonical_object_id']==source['canonical']['object_id'], 'M3 input switch returned a foreign source')
        rows.append({**{k:row[k] for k in ('work_item_id','dataset_id','selection','route','operation','status','reason')},
                     'applicability':item['applicability'],'source_object':source['canonical'],'source_file':source['file'],
                     'frozen_input':item['input'],'evidence_recorded':evidence is not None,
                     'input_unit_audit':c})
        by_selection[item['selection']][status]+=1
    require(len(rows)==len(report['rows']) and dict(Counter(r['status'] for r in rows))==report['statuses'],
            'M3 input switch status accounting differs')
    require(set(refs)==_inventory(run), 'M3 input switch retained artifact inventory differs from the ledger')
    for ref in refs.values():
        _known_file(run,ref)
    summaries = []
    for selection in plan['input_switch']['eligible_selections']:
        outcomes = by_selection[selection]
        actual = [r['work_item_id'] for r in rows if r['selection']==selection and
                  r['status'] in ('verified','quality_rejected') and r['evidence_recorded']]
        qualified = [r['work_item_id'] for r in rows if r['selection']==selection and r['status']=='verified']
        summaries.append({'selection':selection,'statuses':dict(outcomes),'native_execution_and_validator_evidence':actual,
                          'verified_input_switch_work_items':qualified})
    result = {'schema':'bmk.m3-input-switch-audit/1','source_seal':seal,'run_id':run.name,'plan_id':plan['plan_content_id'],
              'baseline_plan_id':plan['input_switch']['baseline_plan_id'],'manifest':definition['bindings']['manifest'],
              'statuses':report['statuses'],'selections':summaries,'decisions':rows,'retained_physical_files_checked':len(refs),
              'selections_with_execution_and_validation_evidence':sum(bool(x['native_execution_and_validator_evidence']) for x in summaries),
              'selections_with_verified_switch_result':sum(bool(x['verified_input_switch_work_items']) for x in summaries),
              'scope':'supplemental_full_population_ledger_and_retained_file_audit_not_independent_replay',
              'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**result,'audit_id':content_id(result)}
