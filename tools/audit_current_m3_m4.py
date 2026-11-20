#!/usr/bin/env python3
"""Audit current M3/M4 exit evidence without turning diagnostic runs into receipts."""
from argparse import ArgumentParser
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_input_switch import audit as audit_switch
from tsbench.application.m3_measurement_inventory import audit as audit_measurement
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.m4_cost_comparison import compare
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, require, verify_asset
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

SCHEMA = 'bmk.current-m3-m4-exit-evidence-audit/1'
STAGES = ('M0', 'M1', 'M2')
FLAGS = ('stage_accepted', 'qualification_granted', 'timing_admitted')
CLOCKS = ('native_repeat', 'verified_durable_repeat')
SWITCH = {'same_entry_independent_real_projection_v1': 'independent_real', 'same_entry_synthetic_switch_v1': 'synthetic'}


def ref(root, path):
    return {'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def check(root, reference):
    path = verify_asset(root, reference)
    require(path.stat().st_size == reference['bytes'], 'audited asset size differs')
    return path


def _diag(doc, schema=None):
    require((schema is None or doc.get('schema') == schema) and all(doc.get(k) is False for k in FLAGS),
            'expected current, non-admitting evidence; historical receipts are not admissible here')


def _identity(doc, key):
    require(doc.get(key) == content_id({k: v for k, v in doc.items() if k != key}), f'{key} differs')


def _main_population(plan, ledger):
    required, conditional, corpus = [], [], []
    for row, item in full_run_rows(plan, ledger):
        kind = row.get('entry_kind')
        if kind == 'specialized_obligation':
            target = required if row['kind'] == 'required' else conditional
            target.append({k: row[k] for k in ('obligation_id','selection','route','check','status','reason')})
        elif kind is None:
            require('evidence' in row and item is not None, 'missing frozen corpus entry')
            corpus.append({k: row[k] for k in ('work_item_id','dataset_id','route','selection','operation','status','reason','applicability')})
    selections = {r['selection'] for r in plan['routes']}
    require(len(selections)==12 and len(plan['routes'])==36 and len(corpus)==828 and len({r['dataset_id'] for r in corpus})==23 and
            len(required)==180 and len(conditional)==6, 'not the full first-batch revised M3 denominator')
    return (required, conditional, corpus), selections


def _clock_gaps(corpus, inventory):
    gaps = defaultdict(lambda: defaultdict(list))
    coverage = {k: Counter() for k in CLOCKS}
    require(len(corpus) == len(inventory['decisions']), 'measurement denominator differs from main ledger')
    for a,b in zip(corpus,inventory['decisions'],strict=True):
        require(all(v == b.get(k) for k,v in a.items()), 'measurement review changes a main-ledger verdict or work identity')
        if a['status'] != 'verified':
            continue
        for clock in CLOCKS:
            state = b['clock_coverage'][clock]
            coverage[clock][state] += 1
            if state != 'frozen_extent':
                gaps[a['route']][clock].append({'work_item_id': a['work_item_id'], 'dataset_id': a['dataset_id'], 'scope': state})
    return coverage, gaps


def _switch_proof(root, baseline, selections, swap_plan, swap_run):
    d = audit_switch(root, load_json(swap_plan), swap_run)
    _diag(d, 'bmk.m3-input-switch-audit/1')
    require(d['baseline_plan_id'] == baseline, 'switch extends a different M3 baseline')
    manifest_path = local_file(root, d['manifest'])
    scope = load_json(manifest_path)['scope']
    require(scope in SWITCH, 'declare and audit the real/synthetic input provenance before linking it')
    executed = {row['selection'] for row in d['selections'] if row['native_execution_and_validator_evidence']}
    verified = {row['selection'] for row in d['selections'] if row['verified_input_switch_work_items']}
    require(verified <= executed <= selections, 'switch references an undeclared or unexecuted selection')
    return {'type': SWITCH[scope], 'run': ref(root, swap_run/'completion.json'), 'plan': ref(root, swap_plan),
            'manifest': ref(root, manifest_path), 'audit_id': d['audit_id'], 'executed_selections': sorted(executed),
            'verified_selections': sorted(verified), 'status_counts': d['statuses']}


def audit(root, plan_file, run, inventory_file, switch_inputs, cost_file):
    plan = load_json(plan_file)
    check_m3_real_corpus_plan(root, plan)
    require('input_switch' not in plan, 'primary M3 must not be a switch plan')
    ledger, seal = full_run_source(plan, run)
    (required, conditional, corpus), selections = _main_population(plan,ledger)
    predecessors = {s:plan['predecessors'][s.lower()+'_real_corpus_receipt'] for s in STAGES}
    inv = load_json(inventory_file)
    _diag(inv, 'bmk.m3-diagnostic-measurement-inventory/1')
    _identity(inv, 'inventory_id')
    require(inv['source_plan'] == ref(root,plan_file) and inv['source_run'] == run.name and inv['source_seal'] == seal,
            'M3 diagnostic evidence is not from the one primary run')
    evidence = []
    for d in inv['diagnostics']:
        s, report = check(root,d['seal']), check(root,d['report'])
        require(s.name=='completion.json' and report.name=='report.json' and s.parent==report.parent, 'unexpected diagnostic assets')
        evidence.append((d['mode'],s.parent))
    require(audit_measurement(root,plan_file,run,evidence)==inv, 'diagnostic inventory does not independently replay')
    coverage, gaps = _clock_gaps(corpus,inv)
    swap_proofs, executed_swap, verified_swap = [], defaultdict(set), defaultdict(set)
    for swap_plan, swap_run in switch_inputs:
        proof = _switch_proof(root, plan['plan_content_id'], selections, swap_plan, swap_run)
        swap_proofs.append(proof)
        executed_swap[proof['type']].update(proof['executed_selections'])
        verified_swap[proof['type']].update(proof['verified_selections'])
    cost = load_json(cost_file)
    _diag(cost, 'bmk.m4-real-cost-comparison/2')
    _identity(cost, 'comparison_id')
    require(cost['M3_plan'] == ref(root,plan_file) and cost['multiscale_abi_diagnostics'],
            'M4 cost evidence does not bind the current M3 plan and multiscale controls')
    profile = check(root,cost['profile_seal']).parent
    link = check(root,cost['multiscale_abi_diagnostics']['link'])
    timings = {kind:check(root,c['main_seal']).parent for kind,c in cost['cases'].items()}
    require(compare(root,profile,timings,multiscale_link=link)==cost, 'M4 cost evidence does not independently replay')
    open_required = [o for o in required if o['status']!='verified']
    open_conditional = [o for o in conditional if o['status']!='verified']
    not_passed = [r for r in corpus if r['applicability']=='input_domain_matches' and r['status']!='verified']
    body = {'schema':SCHEMA, 'audited_specifications':[ref(root,local_file(root,n)) for n in
                ('TimeSeries_Compression_Benchmark_重建设计与实施方案.md','TSDataCompressBenchMark目标.md')],
            'scope':'exit_evidence_reconciliation_not_a_stage_receipt_or_a_new_run',
            'predecessor_receipts':predecessors,
            'M3':{'plan':ref(root,plan_file), 'seal':ref(root,run/'completion.json'), 'corpus_outcomes':dict(Counter(r['status'] for r in corpus)),
                  'nonpassing_applicable_decisions':not_passed, 'required_obligations':len(required), 'open_required_obligations':open_required,
                  'conditional_obligations':len(conditional), 'open_conditional_obligations':open_conditional,
                  'switches':swap_proofs,
                  'not_yet_executed_and_validated_on_independent_real_switch':sorted(selections - executed_swap['independent_real']),
                  'not_yet_verified_on_independent_real_switch':sorted(selections - verified_swap['independent_real']),
                  'not_yet_verified_on_any_switch':sorted(selections - set().union(*verified_swap.values())),
                  'diagnostic_inventory':ref(root,inventory_file), 'diagnostic_scope_counts':coverage, 'diagnostic_clock_gaps_by_route':gaps,
                  'primary_run_timing_admission_proven':False, 'diagnostic_runs_may_not_replace_main_ledger':True},
            'M4':{'current_cost_comparison':ref(root,cost_file), 'cost_and_multiscale_replayed':True, 'profile_cases':sorted(cost['cases']),
                  'abi_verified_direction_trials':cost['multiscale_abi_diagnostics']['abi_verified_direction_trials'],
                  'profile_does_not_fill_main_timing':True, 'predecessor_M3_current_stage_receipt_bound':False},
            **{flag:False for flag in FLAGS}}
    return {**body,'audit_id':content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    for n in ('plan','run','inventory','m4-cost'):
        p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--switch', action='append', nargs=2, type=Path, default=[], metavar=('PLAN','RUN'))
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path)
    out.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        doc = audit(ROOT,a.plan.resolve(strict=True),a.run.resolve(strict=True),a.inventory.resolve(strict=True),
                    [tuple(p.resolve(strict=True) for p in pair) for pair in a.switch],a.m4_cost.resolve(strict=True))
        if a.out:
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,doc)
        else:
            require(doc==load_json(a.verify), 'current M3/M4 exit audit differs from recomputation')
        print(json.dumps({'audit_id':doc['audit_id'], 'M3_nonpassing_applicable':len(doc['M3']['nonpassing_applicable_decisions']),
                          'M3_open_required':len(doc['M3']['open_required_obligations']),
                          'M3_independent_real_switch_missing':doc['M3']['not_yet_verified_on_independent_real_switch'],
                          'M3_diagnostic_scope_counts':doc['M3']['diagnostic_scope_counts'], 'M4_cost_replayed':True}))
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()
