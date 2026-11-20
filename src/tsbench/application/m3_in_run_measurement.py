"""Commit independent whole-file repeats with their own source work decision."""
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from ..assets import ContractError, require
from ..planner.m3_in_run_measurement import ADAPTER
from ..supervisor import timing_resource as resource
from ..recovery import stage_recovery
from . import m3_pbepla_grouped_timing as grouped
from .m3_column_batch_timing import _pin


def _case(item, row, binding):
    evidence = row['evidence']
    units = [{**u,'replay':{k:v for k,v in u['replay'].items() if k!='first_sink_ns'} if u.get('replay') else None}
             for u in evidence['units']]
    return {'case_id':binding['case_id'],'dataset_id':row['dataset_id'],'route':row['route'],'status':row['status'],
            'units':units,'work_item_id':row['work_item_id'],'canonical_object_id':item['canonical_object_id'],
            'operation_config_id':item['operation_config_id'],'configuration':item['input']['pbepla_contract'],
            'reason':row['reason']}


@contextmanager
def guard(plan):
    clock = plan['measurement']; cpu = clock['environment']['cpu']
    # Verify affinity and topology before pinning; do not label this process lock as kernel isolation.
    require(resource.environment(cpu)==clock['environment'],'M3 measurement environment changed since freeze')
    with _pin(cpu):
        yield


def unavailable(prescribed, functional_status):
    if prescribed['status']=='scheduled':
        return {**prescribed,'status':'functional_dependency_not_verified','reason':functional_status,
                'trials':[],'timing_admitted':False}
    return {**prescribed,'trials':[],'timing_admitted':False}


def measure(root, plan, item, partner, entry, work, run, row):
    clock = plan['measurement']
    prescribed = clock['population'][item['work_item_id']]
    if prescribed['status']!='scheduled' or row['status']!='verified':
        return unavailable(prescribed,row['status'])
    require(prescribed['adapter']==ADAPTER and partner is not None,'incompatible in-run measurement adapter')
    case = _case(item,row,prescribed); cpu = clock['environment']['cpu']
    pair = {i['route']:i for i in (item,partner)}
    trials, seen = [], set()
    slots = list(grouped.schedule(case))
    before = resource.observe(cpu)
    failed = None
    with TemporaryDirectory(prefix='same-run-timing-',dir=work) as tmp:
        tmp = Path(tmp)
        try:
            stage_recovery(root,tmp,clock['runtime'],directory='runtime')
            grouped._make_anchor(root,tmp,clock,case,entry,pair,cpu,tmp/'anchors')
        except (ContractError,OSError) as exc:
            failed = f'measurement anchor preparation failed: {exc}'
        for slot in slots:
            if failed:
                trials.append({**slot,'case_id':case['case_id'],'status':'not_run_after_measurement_failure',
                               'reason':failed})
                continue
            try:
                obs = grouped._trial(root,tmp,clock,case,entry,pair,tmp/'anchors',cpu,slot,seen)
                grouped._validate_trial(case,cpu,slot,obs,set())
            except (ContractError,OSError) as exc:
                failed = str(exc) or type(exc).__name__
                trials.append({**slot,'case_id':case['case_id'],'status':'measurement_failed','reason':failed})
            else:
                trials.append(obs)
    out = {**prescribed, 'status':'measurement_failed' if failed else 'measured_and_verified',
           'reason':failed,'trials':trials,'resource_before':before,'resource_after':resource.observe(cpu),
           'timing_admitted':False}
    return {**out,'summary':recompute(item,row,clock,out,set())}


def recompute(item, row, clock, doc, seen):
    prescribed = clock['population'][row['work_item_id']]
    require(doc['timing_admitted'] is False,'in-run evidence cannot grant timing admission')
    if prescribed['status']!='scheduled' or row['status']!='verified':
        require(doc==unavailable(prescribed,row['status']), 'M3 missing scope was changed after planning')
        return None
    case = _case(item,row,prescribed); rounds = defaultdict(list); passed = doc['status']=='measured_and_verified'
    require(doc['status'] in ('measured_and_verified','measurement_failed') and (doc['reason'] is None)==passed and
            doc['case_id']==case['case_id'] and doc['adapter']==ADAPTER,'invalid M3 measured status or identity')
    failed = False
    for slot, trial in zip(grouped.schedule(case),doc['trials'],strict=True):
        require(trial['case_id']==case['case_id'] and all(trial[k]==v for k,v in slot.items()),'M3 timing slot differs')
        if trial['status']=='measured_as_declared':
            require(not failed,'PBEPLA trial after terminal measurement failure')
            stat = grouped._validate_trial(case,clock['environment']['cpu'],slot,trial,seen)
            if slot['phase']=='measured':
                rounds[slot['operation']].append(stat)
        else:
            reason = trial.get('reason')
            require(trial['status'] in ('measurement_failed','not_run_after_measurement_failure') and reason==doc['reason'] and
                    bool(reason) and not (failed and trial['status']=='measurement_failed'),'invalid M3 failed trial')
            failed = True
    require(passed==(not failed),'M3 measurement terminal does not match slot evidence')
    return grouped._summarize(case,rounds) if passed else None
