#!/usr/bin/env python3
"""Recompute one full M3 run's functional, measurement and obligation census.

This is a cross-check of existing raw-evidence auditors, not a stage receipt.
It refuses preflights, incomplete ledgers and plans with a reduced denominator.
"""
from argparse import ArgumentParser
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from audit_m3_in_run_measurement import audit as audit_measurement
from tsbench.application.m3_ledger_census import census
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, require

DENOMINATOR = {'input_domain_matches': 724, 'outside_declared_domain': 74, 'condition_not_triggered': 30}
OBLIGATIONS = {'required': 180, 'conditional': 6}
SUCCESS = 'measured_and_verified'
REJECTED = 'measured_quality_rejected'
MISSING = 'functional_dependency_not_verified'
FAILED = 'measurement_failed'
MEASURED_PHASES = ('measured', 'measure')  # ZFP's frozen grouped-v7 records use the latter.
FLAGS = {'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}


def _denominator(plan):
    work = plan['work_items']
    domains = Counter(i['applicability'] for i in work)
    kinds = Counter(o['kind'] for o in plan['obligations'])
    population = plan['measurement']['population']
    require(domains == DENOMINATOR and kinds == OBLIGATIONS and
            len({i['dataset_id'] for i in work}) == 23 and len({i['selection'] for i in work}) == 12 and
            len({(i['selection'], i['route']) for i in work}) == 36 and len(work) == len(population) and
            {i['work_item_id'] for i in work} == set(population), 'M3 closeout requires the complete frozen first-batch denominator')
    for item in work:
        prescribed = population[item['work_item_id']]
        domain = item['applicability']
        require((prescribed['status'] == 'scheduled' and prescribed.get('adapter') and prescribed.get('case_id'))
                if domain == 'input_domain_matches' else prescribed['status'] == domain,
                'M3 closeout plan omits an applicable decision or changes a domain terminal')
    return dict(domains), dict(kinds)


def _decision(item, row, observed, checked):
    keys = ('work_item_id', 'dataset_id', 'route')
    require(all(item[k] == row[k] == checked[k] for k in keys) and
            checked['functional_status'] == row['status'] and checked['measurement_status'] == observed['status'],
            'M3 closeout corpus and measurement decisions disagree')
    domain, functional, state = item['applicability'], row['status'], observed['status']
    samples = checked['trials']
    summary = checked['summary']
    reason = observed.get('reason')
    measured = sum(samples.get(f'{phase}:measured_as_declared',0) for phase in MEASURED_PHASES)
    declared_samples = {f'{phase}:measured_as_declared' for phase in ('warmup',*MEASURED_PHASES)}
    if domain != 'input_domain_matches':
        require(domain == functional == state and not samples and summary is None, 'M3 closeout non-applicable terminal differs')
    elif state in (SUCCESS, REJECTED):
        require(functional == ('verified' if state == SUCCESS else 'quality_rejected') and
                reason is None and summary is not None and measured > 0 and set(samples)<=declared_samples and
                all(type(n) is int and n>0 for n in samples.values()), 'M3 closeout successful measurement has inconsistent sample scope')
    elif state == MISSING:
        require(functional != 'verified' and reason == functional and not samples and summary is None,
                'M3 closeout missing measurement must preserve original dependency terminal')
    elif state == FAILED:
        require(functional in ('verified', 'quality_rejected') and isinstance(reason, str) and reason and summary is None and
                any(not k.endswith(':measured_as_declared') for k in samples), 'M3 closeout failed measurement lacks reason or terminal trial')
    else:
        require(False, 'M3 closeout unresolved applicable measurement status')
    return {**{k: item[k] for k in (*keys, 'selection', 'operation', 'operation_config_id', 'applicability')},
            'functional_status': functional, 'functional_reason': row['reason'], 'measurement_status': state,
            'measurement_reason': reason, 'trials': samples, 'measurement_summary': summary}


def audit(root, plan, run):
    domains, kinds = _denominator(plan)
    ledger, seal = full_run_source(plan, run)
    functional = census(root, plan, run)
    require(functional['all_frozen_decisions_and_obligations_accounted'], 'M3 closeout requires full function and obligation census')
    measured = audit_measurement(root, plan, run)
    require(functional['seal_id'] == measured['source_seal_id'] == seal and
            measured['partial_preflight'] is False and all(d['run_id'] == run.name and d['plan_content_id'] == plan['plan_content_id']
                                                          for d in (functional, measured)), 'M3 closeout source runs or seals differ')
    require(all(all(d[k] is v for k, v in FLAGS.items()) for d in (functional, measured)),
            'M3 diagnostics unexpectedly claim acceptance or admission')
    details, obligations = [], []
    statuses = Counter()
    trials_by_result = defaultdict(Counter)
    inspected = iter(measured['measurement_decisions'])
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') == 'specialized_obligation':
            obligations.append({k: row[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind', 'status', 'reason')})
        elif item is not None:
            checked = next(inspected, None)
            require(checked is not None, 'M3 closeout lacks a recomputed measurement')
            detail = _decision(item, row, row['measurement'], checked)
            details.append(detail)
            state = detail['measurement_status']
            statuses[state] += 1
            trials_by_result[state].update(detail['trials'])
    require(next(inspected, None) is None and statuses == measured['statuses'] and len(obligations) == sum(kinds.values()),
            'M3 closeout decision or obligation reconciliation differs')
    body = {'schema': 'bmk.m3-primary-closeout/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'source_seal_id': seal, 'measurement_audit_id': measured['audit_id'],
            'planned_applicability': domains, 'planned_obligation_kinds': kinds,
            'functional_statuses': functional['corpus_statuses'], 'measurement_statuses': dict(statuses),
            'repeat_trial_counts_by_terminal': {k: dict(v) for k, v in trials_by_result.items() if v},
            'obligation_statuses': functional['obligation_statuses'], 'batch_unit_mismatches': functional['batch_unit_mismatches'],
            'diagnostic_repeats_not_formal_samples': True, 'group_processes_verified': measured['group_processes_verified'],
            'scope': 'one_sealed_primary_ledger_native_function_and_in_run_repeats_not_full_artifact_replay_or_formal_admission',
            'decisions': details, 'obligations': obligations, **FLAGS}
    return {**body, 'closeout_id': content_id(body)}


def main():
    p = ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out', type=Path)
    out.add_argument('--verify', type=Path)
    a = p.parse_args()
    try:
        doc = audit(ROOT, load_json(a.plan), a.run.resolve(strict=True))
        if a.out:
            write_new(a.out, doc)
        else:
            require(doc == load_json(a.verify), 'M3 primary closeout differs from recomputation')
        print(doc['closeout_id'], doc['functional_statuses'], doc['measurement_statuses'], doc['obligation_statuses'])
    except (OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
