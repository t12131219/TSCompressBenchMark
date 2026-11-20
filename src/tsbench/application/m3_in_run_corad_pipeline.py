"""CORAD v14: distinct raw-source-to-durable encode clock; v13 remains immutable."""
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import require
from ..planner.m3_in_run_measurement_v13 import CORAD
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_corad_raw_ingress as ingress, m3_in_run_corad as base
from .m3_in_run_measurement import guard, unavailable
from .m3_primary_measurement_v13 import observe as previous


def _trial(root, plan, entry, run, work, runtime, cases, slot, timed):
    if slot['direction'] != 'encode':
        return base._trial(plan, run, work, runtime, cases, slot, timed)
    start, cpu = monotonic_ns(), process_time_ns()
    try:
        current, records = ingress.materialize(root, entry, cases)
    except (OSError, ValueError) as exc:
        return {**slot, 'status':'measurement_failed', 'reason':str(exc) or type(exc).__name__,
                'failure_stage':'raw_source_ingress', 'units':[], 'unissued_units':len(cases)}
    raw_ns = monotonic_ns() - start
    raw_cpu = process_time_ns() - cpu
    trial = base._trial(plan, run, work, runtime, current, slot, timed)
    return {**trial, 'raw_source':{'file':entry['file'], 'heldout_slices':records, 'parse_verify_materialize_wall_ns':raw_ns,
                                   'parse_verify_materialize_controller_cpu_ns':raw_cpu},
            **({'raw_source_to_verified_durable_and_published_wall_ns':monotonic_ns() - start}
               if trial['status'] == 'measured_as_declared' else {})}


def _checked_trials(entry, cases, expected, trials):
    require(len(trials) == len(expected), 'CORAD raw trial denominator differs')
    add = {'parse_verify_materialize_wall_ns':[], 'parse_verify_materialize_controller_cpu_ns':[],
           'raw_source_to_verified_durable_and_published_wall_ns':[]}
    for slot, t in zip(expected, trials, strict=True):
        fields = {'raw_source','raw_source_to_verified_durable_and_published_wall_ns','failure_stage'} & t.keys()
        if slot['direction'] != 'encode' or t['status'] == 'not_run_after_measurement_failure':
            require(not fields, 'non-encode or unissued CORAD trial reported raw ingress')
            continue
        if t.get('failure_stage') == 'raw_source_ingress':
            require(t['status'] == 'measurement_failed' and fields == {'failure_stage'} and t['units'] == [] and
                    t['unissued_units'] == len(cases), 'CORAD ingress failure cannot issue native units')
            continue
        ok = t['status'] == 'measured_as_declared'
        require(fields == ({'raw_source','raw_source_to_verified_durable_and_published_wall_ns'} if ok else {'raw_source'}),
                'CORAD raw ingress or completed wall observation missing')
        s = t['raw_source']
        require(s == {'file':entry['file'],'heldout_slices':ingress.expected_records(cases),
                      'parse_verify_materialize_wall_ns':s['parse_verify_materialize_wall_ns'],
                      'parse_verify_materialize_controller_cpu_ns':s['parse_verify_materialize_controller_cpu_ns']} and
                all(base._positive(s[k]) for k in add if k in s), 'CORAD raw source identity, slices or clocks differ')
        if ok:
            whole = t['raw_source_to_verified_durable_and_published_wall_ns']
            require(type(whole) is int and whole >= s['parse_verify_materialize_wall_ns'] + t['whole_verified_durable_wall_ns'],
                    'CORAD raw pipeline wall omits a measured stage')
            if t['phase']=='measured':
                for k, series in add.items():
                    series.append(s[k] if k in s else whole)
    return add


def recompute(root, plan, item, entry, run, row, doc, seen, *, cases=None):
    # v13 training has no raw-text timing and never mounts held-out values.
    if item['route'] != base.INFERENCE:
        return base.recompute(root, plan, item, entry, run, row, doc, seen, cases=cases)
    if cases is None:
        cases = base._cases(root, plan, item, row, entry, run)
    frozen = plan['measurement']['population'][item['work_item_id']]
    cid = frozen['case_id']
    schedule = list(base.schedule(item['route'], cid))
    samples = _checked_trials(entry, cases, schedule, doc['trials'])
    ingress_failed = any(t.get('failure_stage') == 'raw_source_ingress' for t in doc['trials'])
    if ingress_failed:
        # Validate earlier native trials and the untouched slot tail, without inventing
        # a process, a failed unit, a completion or a repeated distribution.
        return _check_ingress_failure(plan, run, doc, seen, cases, schedule, frozen)
    summary = base.recompute(root, plan, item, entry, run, row, doc, seen, cases=cases)
    if summary is None:
        return None
    basis = summary['sample_basis']
    whole = base._round_distribution('raw_source_wall_ns', samples['raw_source_to_verified_durable_and_published_wall_ns'], basis)
    logical = sum(v['logical_bytes'] for v in summary['cost'].values())
    return {**summary, 'raw_encode_pipeline':{'scope':'locked_original_text_to_verified_synced_frames_and_published_evidence',
                'input_file_bytes':entry['file']['bytes'], 'logical_value_bytes_total_both_producers':logical,
                'encode_heldout_mib_s':base._round_distribution('encode_heldout_mib_s', [logical*1e9/(ns*(1<<20)) for ns in
                                              samples['raw_source_to_verified_durable_and_published_wall_ns']], basis),
                'wall_ns':whole, 'ingress_wall_ns':base._round_distribution('ingress_wall_ns', samples['parse_verify_materialize_wall_ns'], basis),
                'ingress_controller_cpu_ns':base._round_distribution('ingress_cpu_ns', samples['parse_verify_materialize_controller_cpu_ns'],basis)}}


def _check_ingress_failure(plan, run, doc, seen, cases, schedule, frozen):
    require(doc['status']=='measurement_failed' and doc['timing_admitted'] is False and doc['reason'] and
            all(doc[k]==frozen[k] for k in ('adapter','case_id')) and
            doc['anchors']=={'units':len(cases),'reference':'same_run_functional_products'} and not doc['failure_logs'],
            'CORAD ingress failure terminal differs')
    failed = False
    files = set()
    for slot, t in zip(schedule, doc['trials'], strict=True):
        require(all(t[k] == v for k,v in slot.items()), 'CORAD ingress failure slot differs')
        if failed:
            require(t['status']=='not_run_after_measurement_failure' and t['reason']==doc['reason'], 'CORAD unissued trial after ingress failure differs')
        elif t.get('failure_stage')=='raw_source_ingress':
            require(t['reason']==doc['reason'], 'CORAD ingress failure reason differs')
            failed = True
        else:
            require(t['status']=='measured_as_declared' and len(t['units'])==len(cases) and
                    all(u['status']=='completed' for u in t['units']) and base._positive(t['whole_verified_durable_wall_ns']) and
                    base._positive(t['controller_cpu_ns']) and sum(u['wall_ns'] for u in t['units'])<=t['whole_verified_durable_wall_ns'],
                    'CORAD prior trial after ingress failure has inconsistent evidence')
            for i,(u,c) in enumerate(zip(t['units'],cases,strict=True)):
                base._verify_unit(run,plan,c,slot,u,f"{slot['path']}/{i:05d}",seen)
                files.update(r['path'] for r in u['files'].values())
    require(failed, 'missing CORAD ingress failure slot')
    base._inventory(run,f"{base.DIRECTORY}/{frozen['case_id']}",files)
    base._inventory(run,f"{base.FAILED}/{frozen['case_id']}",set())
    return None


def observe(root, plan, item, entry, pbepla_pairs, run, row):
    m=plan['measurement']; frozen=m['population'][item['work_item_id']]
    if frozen.get('adapter')!=CORAD or item['route']!=base.INFERENCE:
        return previous(root,plan,item,entry,pbepla_pairs,run,row)
    if row['status'] not in base.READY:
        return unavailable(frozen,row['status'])
    cid=frozen['case_id']; cpu=m['environment']['cpu']
    cases=base._cases(root,plan,item,row,entry,run)
    before=resource.observe(cpu)
    trials, error = [], None
    with guard(plan), TemporaryDirectory(prefix='m3-corad-primary-',dir=run) as folder:
        work=Path(folder); runtime=work/'runtime'; stage_recovery(root,work,m['corad_clock']['runtime'],directory=runtime.name)
        (run/base.DIRECTORY/cid).mkdir(parents=True)
        for slot in base.schedule(item['route'],cid):
            if error:
                trials.append({**slot,'status':'not_run_after_measurement_failure','reason':error})
                continue
            with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
                trial=_trial(root,plan,entry,run,Path(tmp),runtime,cases,slot,None)
            trials.append(trial)
            if trial['status']=='measurement_failed':
                error=trial['reason']
    failures=[r for t in trials if t['status']=='measurement_failed' for u in t['units'] if u['status']=='failed' for r in u['files'].values()]
    done='measured_quality_rejected' if row['status']=='quality_rejected' else 'measured_and_verified'
    doc={**frozen,'status':'measurement_failed' if error else done,'reason':error,'timing_admitted':False,
         'anchors':{'units':len(cases),'reference':'same_run_functional_products'},'trials':trials,'failure_logs':failures,
         'resource_before':before,'resource_after':resource.observe(cpu)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set(),cases=cases)}
