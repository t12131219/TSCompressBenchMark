"""Join a single native candidate's real replay to its qualification requirements.

This evidence lane does not sign stage acceptance or grant qualification. A
formal run must bind the final policy at submission, not relabel this document.
"""
from collections import Counter, defaultdict
from pathlib import Path

from ..application import batch_execution as batch
from ..application.smoke import _rows
from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from ..contracts import load_contract

SCHEMA = 'qualification'
KIND = 'bmk.native-qualification-audit/1'
RESTORES = ('products','wrapped_products','selfstar_ordered_products','huff0_products',
            'sprintz_products','titchy_access_products','titchy_stream_products','pcodec_intmult_products',
            'gorilla_state_products','lzbench_session_products','lzbench_profile_products',
            'alp_decode_backend_products','zfp_native_products','pbepla_products','corad_inference_products',
            'corad_training_products')
NEGATIVES = ('pcodec_input_rejections','pcodec_intmult_input_rejections','replayed_pbepla_rejections')
_FORMAL_BLOCKERS = ('candidate_submission_not_formal','predecessor_acceptance_not_bound',
                    'formal_work_limits_and_retention_policy_not_bound')


def _validator(root, plan, schema_id):
    require(local_file(root,'src/tsbench/application/batch_execution.py')==Path(batch.__file__).resolve() and
            local_file(root,'src/tsbench/qualification/native_evidence.py')==Path(__file__).resolve(),
            'qualification root must bind the executing validator source tree')
    locked = {p:h for p,h in plan['code'].items() if p.startswith('src/tsbench/') and p.endswith('.py')}
    require('src/tsbench/application/batch_execution.py' in locked and
            'src/tsbench/supervisor/isolated_worker.py' in locked,'qualification run lacks a frozen Python validator lock')
    for p,h in locked.items():
        require(digest(local_file(root,p))==h,f'frozen validator differs: {p}; use the original source or a new validation protocol')
    audited = ('src/tsbench/qualification/native_evidence.py','src/tsbench/contracts.py')
    body = {'schema_id':schema_id,'frozen_python':locked,'audit_python':{p:digest(local_file(root,p)) for p in audited},
            'strength':'artifact_each','recovery':'rerun_sealed_recovery_detached','launchers_id':content_id(plan['launchers'])}
    return {**body,'validation_protocol_id':content_id(body)}


def _indexed_replay(replay, buckets):
    out = {}
    for topic in buckets:
        for row in replay.get(topic,[]):
            sid = row['product_slot']
            require(sid not in out,'duplicate slot across detached replay observations')
            out[sid] = {'observation_kind':topic,'observation_id':content_id(row)}
    return out


def _products(plan, ledger, replay):
    drivers = plan['execution_binding']['drivers']
    restored, negatives = _indexed_replay(replay,RESTORES), _indexed_replay(replay,NEGATIVES)
    by_id = {row['product_slot']:row for row in ledger}
    require(len(by_id)==len(ledger)==len(plan['slots']) and by_id.keys()==drivers.keys(), 'qualification driver/ledger denominator differs')
    require(set(restored)=={k for k,r in by_id.items() if r['status']=='verified'} and
            len(restored)==replay['restored_products'], 'detached replay did not cover every verified product')
    require(set(negatives)<={k for k,r in by_id.items() if r['status']=='expected_rejection'},
            'detached rejection replay has no matching original terminal')
    out = {}
    for slot in plan['slots']:
        sid = slot['product_slot']
        r,driver = by_id[sid],drivers[sid]
        result = 'restored' if sid in restored else 'rejection_replayed' if sid in negatives else (
            'rejection_validated_in_ledger_only' if r['status']=='expected_rejection' else 'not_applicable_nonpassing_terminal')
        names = sorted({step['program'] for step in driver['operations']}|set(driver['primary_restore_programs']))
        out[sid] = {'method':slot['method'],'driver_id':content_id(driver),'case_domain_id':content_id(slot),
                    'configuration_id':content_id(driver['configuration']),'programs':names,
                    'terminal':r['status'],'terminal_reason':r['reason'], 'ledger_row_id':content_id(r),
                    'audit_state':result,'detached_observation':restored.get(sid,negatives.get(sid))}
    return out


def _obligations(plan, report, products):
    definition = plan['admission_definition']
    view = plan['execution_binding']
    by_route = defaultdict(list)
    observed = report['obligation_evidence']
    require(set(o['obligation_id'] for o in observed.values())==view['bound_obligations'].keys() and
            len(observed)==len(view['bound_obligations']), 'qualification obligation report differs from frozen bindings')
    out = {}
    for req in definition['obligations']:
        oid, rid, kind = (req[k] for k in ('obligation_id','route_contract_id','kind'))
        key = f"{req['selection']}/{req['route']}/{req['check']}"
        if oid in view['unbound_obligations']:
            slots, status, reason = [],'not_run',view['unbound_obligations'][oid]['reason']
        else:
            observation = observed[key]
            slots, status = observation['product_slots'],observation['state']
            require(observation['obligation_id']==oid and observation['route_contract_id']==rid and
                    slots and set(slots)<=products.keys(), 'qualification observation crosses a route or run')
            reason = observation.get('reason')
            if status in ('pending_supported_runtime','pending_supported_build'):
                require(kind=='conditional', 'unconditional obligation cannot be a hardware pending result')
                reason = reason or ('compatible_build_host_and_effective_native_work_not_observed'
                                    if status=='pending_supported_runtime' else 'requested_backend_not_built_for_width')
            elif status=='missing_or_failed_products':
                reason = reason or 'product_slot_failed_or_missing'
        require(oid not in out, 'duplicate qualification obligation')
        out[oid] = {'route_contract_id':rid,'check':req['check'],'kind':kind,'state':status,'reason':reason,
                    'predicate':req['condition_case']['predicate'] if kind=='conditional' else None,
                    'product_slots':slots}
        by_route[rid].append(oid)
    routes = {}
    for route in definition['routes']:
        rid = route['route_contract_id']
        obligations = by_route[rid]
        require(rid not in routes and obligations,'empty or duplicate qualified route definition')
        ids = {key+'_id':content_id(route[key]) for key in ('domain','quality','access','retention')}
        routes[rid] = {**ids,'selection':route['selection'],'route':route['route'],
                       'source_identity_id':content_id(route['source_identity']),'obligations':obligations,
                       'required_counts':dict(Counter(out[o]['state'] for o in obligations if out[o]['kind']=='required')),
                       'conditional_counts':dict(Counter(out[o]['state'] for o in obligations if out[o]['kind']=='conditional')),
                       'out_of_scope_claims':len(route['out_of_scope']),'qualification':'not_qualified'}
    require(set(by_route)==routes.keys() and len(out)==definition['coverage']['total_obligations'],
            'qualification scope lost a route or obligation')
    return routes, out


def audit_native_qualification(root: Path, run: Path) -> dict:
    """Use the authoritative plan/ledger/retained assets, never a cached PASS report."""
    contract = load_contract(root,SCHEMA)
    plan = load_json(local_file(run,'plan.json'))
    require(isinstance(plan,dict) and plan.get('purpose')=='native_admission_execution_candidate' and
            plan.get('verification')=='artifact_each' and isinstance(plan.get('execution_binding'),dict) and
            plan['execution_binding'].get('scope')=='candidate_only_no_formal_qualification',
            'native qualification audit requires a frozen unified candidate, not a plan or prior audit alone')
    validator = _validator(root,plan,contract.document_id)
    seal = load_json(local_file(run,'seal.json'))
    report = batch.report_batch_execution(run)
    replay = batch.audit_batch_execution(run)
    require(report['run_id']==replay['run_id']==seal['run_id'] and report['seal_id']==replay['seal_id']==seal['seal_id'] and
            report['plan_content_id']==plan['plan_content_id']==seal['plan_content_id'] and
            report['qualification_granted'] is replay['qualification_granted'] is False,
            'qualification evidence is not from one candidate run')
    ledger_ref = seal['files']['ledger.jsonl']
    ledger = _rows(verify_asset(run,ledger_ref))
    products = _products(plan,ledger,replay)
    routes, obligations = _obligations(plan,report,products)
    view = plan['execution_binding']
    programs = {k:content_id({'program':p,'recovery_id':p.get('recovery_id',view['recovery_id']) if 'mount_files' in p else None})
                for k,p in view['programs'].items()}
    body = {'schema':KIND,'scope':'candidate_evidence_only','definition_stage':'M0','qualification_stage':'M3',
            'run':{'run_id':seal['run_id'],'seal_id':seal['seal_id'],'plan_content_id':plan['plan_content_id'],
                   'admission_plan_id':view['admission_plan_id'],'build_id':view['build_id'],'recovery_id':view['recovery_id'],
                   'ledger_sha256':ledger_ref['sha256'],'execution_binding_id':content_id(view),
                   'reconstructed_report_id':content_id(report),'detached_audit_id':content_id(replay)},
            'validation':validator,'formal_blockers':list(_FORMAL_BLOCKERS),'programs':programs,
            'coverage':{'routes':len(routes),'qualified_routes':0,'obligations':len(obligations),
                        'required':dict(Counter(o['state'] for o in obligations.values() if o['kind']=='required')),
                        'conditional':dict(Counter(o['state'] for o in obligations.values() if o['kind']=='conditional')),
                        'product_slots':len(products),'recovery':dict(Counter(p['audit_state'] for p in products.values()))},
            'routes':routes,'obligations':obligations,'products':products,
            'qualification_granted':False,'stage_accepted':False,'timing_admitted':False}
    result = {**body,'audit_id':content_id(body)}
    contract.validate(result,'generated native qualification audit')
    return result
