"""Read-only clustered descriptive comparisons and original-domain quality grids."""
from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path
import random
import statistics

from .records import file_hash, read_jsonl, stable_hash, write_json
from .report import _distribution, _percentile


from .trial_analysis import analysis_dependency_hash, case_coverage, primary_rows, scheduled_rows, trial_coverage


def environment_condition(manifest):
    return {key:value for key,value in manifest.get('environment',{}).items() if key!='captured_at_utc'}


def effective_allocation(case):
    """Codec-specific runtime libraries are evidence, not resource requests."""
    effective=case.get('effective_profile') or {}
    return {key:effective.get(key) for key in ('device','requested_native_threads',
            'effective_native_threads','object_workers','affinity','memory_limit')}


def pair_condition(case, manifest):
    return {'dataset_id':case['dataset_id'],'raw_object_id':case.get('raw_object_id'),
            'task':manifest['resolved_config']['task'],'profile':case['profile'],
            **{key:case[key] for key in ('boundary','lifecycle','cache_policy')}}


def comparison_group(case, reference, manifest):
    """Keep different methods, resources, runs' conditions and runtimes apart."""
    return {'environment':environment_condition(manifest),
            'pass_kind':manifest.get('pass_kind','measurement'),
            'execution':manifest['resolved_config']['execution'],
            'task':manifest['resolved_config']['task'],'profile':case['profile'],
            **{key:case[key] for key in ('boundary','lifecycle','cache_policy')},
            'method':case['method'],'baseline_method':reference['method'] if reference else None,
            'effective_profile':case.get('effective_profile'),
            'baseline_effective_profile':reference.get('effective_profile') if reference else None,
            'implementation_id':case.get('implementation_id'),
            'baseline_implementation_id':reference.get('implementation_id') if reference else None,
            'build_root':manifest['resolved_config'].get('_build_root',manifest['resolved_config'].get('build_root'))}


def cluster_interval(source_logs, *, repetitions=2000, seed=20261013):
    """Bootstrap sources, never treat nested windows or rounds as new sources."""
    means=[statistics.mean(values) for _,values in sorted(source_logs.items()) if values]
    if not means:return {'source_count':0,'estimate':None,'interval':None}
    estimate=math.exp(statistics.mean(means))
    if len(means)<2:return {'source_count':len(means),'estimate':estimate,'interval':None,'reason':'fewer than two sources'}
    rng=random.Random(seed)
    draws=sorted(math.exp(statistics.mean(rng.choices(means,k=len(means)))) for _ in range(repetitions))
    return {'source_count':len(means),'estimate':estimate,'interval':[_percentile(draws,.025),_percentile(draws,.975)],
            'resampling_unit':'source, equally weighted; nested windows and sessions aggregated within each source',
            'interpretation':'exploratory percentile interval conditional on these few selected sources; not population representativeness'}


def pareto_indices(points):
    """Oracle envelope on actual error/complete size/encode/decode, per same object."""
    return [i for i,a in enumerate(points) if not any(
        all(b[j]<=a[j] for j in range(len(a))) and any(b[j]<a[j] for j in range(len(a)))
        for k,b in enumerate(points) if k!=i)]


def analyze(run_dirs, destination, baseline='zstd-frame'):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    runs=[];case_points=[];comparisons=[];manifests={}
    for root in map(Path,run_dirs):
        manifest=json.loads((root/'manifest.json').read_bytes())
        if manifest['run_id'] in manifests:
            raise ValueError('the same run cannot contribute more than once')
        manifests[manifest['run_id']]=manifest
        rows,tail=read_jsonl(root/'observations.jsonl')
        if tail:raise ValueError('study cannot analyze interrupted JSONL tails')
        primary,planned=scheduled_rows(manifest,rows)
        source={'path':str(root.resolve()),'run_id':manifest['run_id'],
                'manifest_hash':file_hash(root/'manifest.json'),'observations_hash':file_hash(root/'observations.jsonl')}
        runs.append(source)
        by_case=collections.defaultdict(list)
        for row in primary.values():by_case[row['case_id']].append(row)
        indexed={}
        for case in manifest['cases']:
            observations=by_case[case['case_id']]
            ok=[row for row in observations if row['status']=='ok']
            coverage=case_coverage(manifest,case,primary,planned)
            point={'run_id':manifest['run_id'],'case_id':case['case_id'],'dataset_id':case['dataset_id'],
                   'source_id':case['dataset'].get('source',case['dataset_id']), 'method_id':case['method_id'],
                   'codec':case['codec'],'profile_id':case['profile_id'],'raw_object_id':case.get('raw_object_id'),
                   'task':manifest['resolved_config']['task'],'admission':case['status'],'reason':case.get('reason'),
                   **coverage,'performance_scope':'diagnostic only; execution source changed' if not coverage['execution_source_valid'] else 'all scheduled trials' if coverage['complete'] else 'conditional on successful primary trials',
                   'profile':case['profile'],'effective_profile':case.get('effective_profile'),
                   'condition':pair_condition(case,manifest),
                   'raw_bytes':case['raw_bytes'],'method':case['method'],
                   'trace':[{'session':r['session'],'round':r['round'],'attempt':r.get('attempt',0),
                             'observation_line':r['observation_line'],'artifact_hash':r.get('artifact_hash'),
                             'implementation_id':r.get('implementation_id'),'status':r['status']} for r in observations]}
            for metric in ('encode_ns','decode_ns','stored_bytes','payload_bytes','header_bytes'):
                point[metric]=_distribution([r[metric] for r in ok if r.get(metric) is not None])
            point['quality']={metric:_distribution([r['verification'][metric] for r in ok if r.get('verification',{}).get(metric) is not None])
                              for metric in ('max_abs','rmse','nrmse','psnr_db')}
            point['stored_fraction']=point['stored_bytes']['median']/case['raw_bytes'] if point['stored_bytes']['median'] is not None and case['raw_bytes'] else None
            point['session_summaries']={}
            for session in sorted({key[1] for key in planned.get(case['case_id'],set())}):
                session_rows=[r for r in ok if r['session']==session]
                point['session_summaries'][str(session)]={metric:statistics.median([r[metric] for r in session_rows if r.get(metric) is not None])
                                                         for metric in ('encode_ns','decode_ns','stored_bytes')
                                                         if any(r.get(metric) is not None for r in session_rows)}
            case_points.append(point)
            key=(stable_hash(pair_condition(case,manifest)),case['method_id'])
            if key in indexed:raise ValueError(f'duplicate pair key: {key}')
            indexed[key]=(case,point)
        if manifest['resolved_config']['task']['fidelity']=='bitwise':
            for case in manifest['cases']:
                method=case['method_id']
                if method==baseline:continue
                pair_key=stable_hash(pair_condition(case,manifest))
                baseline_entry=indexed.get((pair_key,baseline))
                baseline_case,reference=baseline_entry if baseline_entry else (None,None)
                candidate=indexed[(pair_key,method)][1]
                available=bool(reference and reference['complete'] and candidate['complete'])
                reason=None if available else 'one or both matching requested cases did not complete'
                if available and effective_allocation(case)!=effective_allocation(baseline_case):
                    available=False;reason='effective resource allocations differ'
                if available and (set(reference['session_summaries'])!=set(candidate['session_summaries']) or any(
                    not math.isfinite(point['session_summaries'][session].get(metric,math.nan)) or point['session_summaries'][session].get(metric,0)<=0
                    for point in (reference,candidate) for session in point['session_summaries']
                    for metric in ('encode_ns','decode_ns','stored_bytes'))):
                    available=False;reason='matching session metrics are missing, nonfinite or nonpositive'
                group=comparison_group(case,baseline_case,manifest)
                comparison={'run_id':manifest['run_id'],'dataset_id':case['dataset_id'],'source_id':case['dataset'].get('source',case['dataset_id']),
                            'baseline':baseline,'method':method,'raw_object_id':case.get('raw_object_id'),
                            'group_id':stable_hash(group),'group_condition':group,
                            'pair_available':available,'reason':reason}
                if available:
                    comparison['session_ratios']={metric:[reference['session_summaries'][session][metric]/candidate['session_summaries'][session][metric]
                                                           for session in reference['session_summaries']]
                                                  for metric in ('encode_ns','decode_ns','stored_bytes')}
                    comparison['semantics']='baseline / candidate; >1 means candidate faster or smaller; median round within each session'
                comparisons.append(comparison)
    effects=[]
    for group_id in sorted({x['group_id'] for x in comparisons}):
        selected=[x for x in comparisons if x['group_id']==group_id]
        method=selected[0]['method']
        for metric in ('encode_ns','decode_ns','stored_bytes'):
            source_logs=collections.defaultdict(list)
            for pair in selected:
                if pair['pair_available']:
                    source_logs[pair['source_id']].extend(math.log(r) for r in pair['session_ratios'][metric])
            effects.append({'method':method,'baseline':baseline,'group_id':group_id,
                            'group_condition':selected[0]['group_condition'],'metric':metric,'requested_pairs':len(selected),
                            'available_pairs':sum(x['pair_available'] for x in selected),**cluster_interval(source_logs)})
    groups=collections.defaultdict(list)
    for point in case_points:
        if point['complete'] and point['task']['fidelity'] in {'bounded_abs','empirical_quality'}:
            # Bounds are grid coordinates; all other task and execution semantics must match.
            manifest=manifests[point['run_id']]
            condition={**point['condition'],'task':{key:value for key,value in point['task'].items() if key!='error_bound'},
                       'environment':environment_condition(manifest),'execution':manifest['resolved_config']['execution'],
                       'pass_kind':manifest.get('pass_kind','measurement'),
                       'effective_allocation':effective_allocation(point)}
            groups[stable_hash(condition)].append(point)
    for points in groups.values():
        dimensions=[(p['quality']['max_abs']['median'],p['stored_bytes']['median'],p['encode_ns']['median'],p['decode_ns']['median']) for p in points]
        valid=[i for i,x in enumerate(dimensions) if all(v is not None for v in x)]
        frontier={valid[i] for i in pareto_indices([dimensions[i] for i in valid])}
        for i,p in enumerate(points):p['empirical_oracle_pareto']=i in frontier
    report={'schema':'tsbench.study-analysis/1','analysis_code_hash':file_hash(__file__),'trial_analysis_hash':analysis_dependency_hash(),'runs':runs,
            'requested_cases':len(case_points),'complete_cases':sum(x['complete'] for x in case_points),
            'primary_policy':'earliest executed attempt; successful retry never replaces executed failure',
            'pair_policy':'same run/dataset/raw_object_id/full requested profile/task/boundary/lifecycle/cache policy and effective allocation; exact scheduled trials must all succeed',
            'aggregation_policy':'separate full method and baseline parameters, environment, execution, profile, effective runtime and boundary conditions',
            'source_count':len({point['source_id'] for point in case_points}),
            'uncertainty':'source-cluster bootstrap conditional on the selected sources; exploratory, no p-values or population ranking',
            'quality_policy':'actual original-domain error; cross-grid Pareto is post-hoc oracle envelope, not a deployed selector',
            'cases':case_points,'paired_comparisons':comparisons,'source_cluster_effects':effects}
    report['analysis_id']=stable_hash(report)
    write_json(destination/'summary.json',report)
    lines=['# CPU length and quality study','','Read-only reconstruction from raw trials. Nested lengths and repeated sessions do not create independent data sources.',
           '',f"Requested cases: {len(case_points)}; complete: {report['complete_cases']}.",'',
           f'| Method / {baseline} baseline | Condition group | Metric | Pairs | Sources | Baseline / method | Exploratory 95% source interval |',
           '|---|---|---|---:|---:|---:|---|']
    for e in effects:
        estimate=f"{e['estimate']:.4g}" if e['estimate'] is not None else '—'
        interval='—' if e['interval'] is None else '–'.join(f'{v:.4g}' for v in e['interval'])
        lines.append(f"| {e['method']} | {e['group_id'].removeprefix('sha256:')[:12]} | {e['metric']} | {e['available_pairs']}/{e['requested_pairs']} | {e['source_count']} | {estimate} | {interval} |")
    lines.extend(['','Intervals resample sources, equally weighted; they are conditional on these few selected sources. No p-values, multiplicity claims, or overall winner.',
                  'Quality and complete/payload/header values, all statuses and per-trial trace are in summary.json.'])
    (destination/'README.md').write_text('\n'.join(lines)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runs',nargs='+',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline',default='zstd-frame')
    args=parser.parse_args()
    result=analyze(args.runs,args.output,args.baseline)
    print(json.dumps({'requested_cases':result['requested_cases'],'complete_cases':result['complete_cases'],'analysis_id':result['analysis_id']}))
