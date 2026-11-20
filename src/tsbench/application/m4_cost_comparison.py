"""Join same-input M3 and M4 evidence without subtracting incompatible clocks."""
from pathlib import Path
from statistics import median

from ..assets import content_id, load_json, local_file, require
from ..planner.m3_batch_timing import checked_file, reference
from . import m3_batch_timing as batch, m3_lzbench_timing as lz, m4_real_profile as profile
from . import m3_lzbench_corpus_clock as native, m4_abi_cost as abi
from .smoke import _rows

SCHEMA = 'bmk.m4-real-cost-comparison/2'
MULTISCALE_SCHEMA = 'bmk.m4-multiscale-profile-evidence/1'
ARMS = ('timing_only', 'trace_off', 'profiled')
ORIGINAL = ('bytes', 'sha256')
BATCH_CASES = {'alp-fused':'libalp_native.so', 'xz-opaque':'liblzbench_native.so'}


def _one(values, label):
    values = list(values)
    require(len(values) == 1, f'expected one {label}, found {len(values)}')
    return values[0]


def _range(values):
    require(bool(values), 'cannot summarize an empty matched population')
    return {'independent_rounds':len(values), 'min_ns':min(values), 'median_ns':median(values), 'max_ns':max(values)}


def _same_common(named, a, b):
    fields = ('dataset_id', 'route', 'work_item_id', 'operation_config_id')
    require(all(a[k]==b[k] for k in fields), f'{named} frozen route/configuration identity differs')


def _file_id(r):
    return {k:r[k] for k in ORIGINAL}


def match_batch(name, case, timed, pristine, native_plan):
    _same_common(name,case,timed)
    require(all(case[k]==timed[k] for k in ('canonical_object_id','geometry','original','plugin','view')) and
            case['expected_m3_frame']==_file_id(timed['frame']), f'{name} original range/schema or frame differs')
    native = timed['expected_native']
    if name == 'alp-fused':
        effective = case['native_config']
        require(timed['decode_backend']==native['decode']['requested_backend']==effective['m3_decode_dispatch'] and
                native['encode']['backend']=='alpn-auto-encoder' and effective['encode']=='ALPN_AUTO' and
                native['decode']['backend']==effective['effective_backend']=='falp-avx2' and effective['decode']=='ALPN_FALP_AVX2' and
                native['decode']['falp_avx2_vectors']==effective['fused_vectors'] and
                all(v['threads']==effective['threads']==1 for v in native.values()), 'ALP fused dispatch differs')
    else:
        require(name=='xz-opaque' and native==case['native_config'], 'XZ opaque native configuration differs')
    rel = 'lib/'+BATCH_CASES[name]
    depend = native_plan['physical_build'][case['plugin']]['project_runtime_assets'][rel]
    require(_file_id(depend)==pristine[BATCH_CASES[name]], f'{name} linked native codec binary differs')


def match_zstd(case, timed, pristine, plan):
    _same_common('zstd-mt',case,timed)
    variant = timed['variants']['2']
    conf = case['native_config']
    scope = _one(timed['scope'], 'Zstd full-file range')
    require(timed['codec']=='zstd' and scope['object_id']==case['canonical_object_id'] and
            scope['start']==0 and scope['partition']=='full' and case['geometry']=={'byte_range':[0,timed['source']['bytes']]} and
            timed['source']==case['original']['raw'] and case['expected_m3_frame']==variant['frame'] and variant['decode_anchor']=='2',
            'Zstd full-object source or fixed frame differs')
    expected = variant['expected']
    require(all(expected[op]['effective_parameters']==conf[op] for op in profile.DIRECTIONS) and
            expected['encode']['jobs']==conf['jobs'] and expected['decode']['jobs']['worker_threads']==0 and
            conf['span_bytes']=={'encode':[262139,65521],'decode':[1<<20,131071]}, 'Zstd effective configuration or span profile differs')
    depend = plan['runtime']['files']['lib/liblzbench_native.so']
    require(_file_id(depend)==pristine['liblzbench_native.so'], 'Zstd linked native codec binary differs')


def _batch_summary(groups, rounds):
    require({g['lifecycle'] for g in groups}=={'cold','steady'} and len(groups)==2, 'M3 lacks a matched ABI lifecycle')
    result = {}
    for g in groups:
        matched = g['matched_rounds']
        require(len(matched)==rounds, 'M3 matched population includes a failing or missing pair')
        result[g['lifecycle']] = {'group_id':g['group_id'], 'matched_rounds':matched, 'directions':{
            op:{**{lane:_range([m['directions'][op][lane]/m['loops'] for m in matched]) for lane in ('linked_entry','dlopen')},
                'dlopen_minus_linked_per_operation':_range([(m['directions'][op]['dlopen']-m['directions'][op]['linked_entry'])/m['loops'] for m in matched])}
            for op in profile.DIRECTIONS}, 'lanes':g['lanes']}
    return result


def _profile_summary(observed, name):
    trials = [r for r in observed['trials'] if r['case']==name]
    records = [r for r in observed['perturbation'] if r['case']==name]
    result = {}
    for op in profile.DIRECTIONS:
        p = _one((r for r in records if r['direction']==op), f'{name} perturbation {op}')
        rounds = p['complete_matched_rounds']
        require(len(rounds)==p['planned_rounds'], 'M4 lacks complete profiling triplets')
        def coverage(pressure):
            return [{'round':t['round'],'capacity':t['capacity'],'l2_visibility':o['l2_visibility'],'cycles':o['cycles'],
                     'trace':o['trace'],'native_counters':o['native_counters'],'unobserved_stage_duration_ns':o['unobserved_stage_duration_ns']}
                    for t in trials if t['mode']=='profiled' and (t['round']==0)==pressure
                    for o in t['observations'] if o['direction']==op]
        result[op] = {'arm_wall_ns':{arm:_range([r['wall_ns'][arm] for r in rounds]) for arm in ARMS},
                      'matched_rounds':rounds,
                      'trace_off_minus_pristine_ns':_range([r['disabled_minus_pristine_ns'] for r in rounds]),
                      'profiled_minus_trace_off_ns':_range([r['profiled_minus_disabled_ns'] for r in rounds]),
                      'regular_coverage':coverage(False), 'pressure_control_not_in_distribution':coverage(True)}
    return result


def audit_multiscale(root, native_run, abi_run, profile_run):
    evidence, _ = _replay_multiscale(root, native_run, abi_run, profile_run)
    return evidence


def _replay_multiscale(root, native_run, abi_run, profile_run):
    nr, ar, pr = native.verify(native_run), abi.verify(abi_run), profile.recompute(profile_run)
    require(pr == load_json(local_file(profile_run, 'report.json')), 'stored profile differs from sealed raw observations')
    n, a, p = (load_json(local_file(run, 'plan.json')) for run in (native_run, abi_run, profile_run))
    require(n['source_plan'] == a['m3_plan'] == p['m3_plan'], 'mixed full-corpus identities')
    pristine = {Path(r['path']).name: _file_id(r) for r in p['assets']['plain']}
    weather = pr['inputs']['zstd-mt']
    z = _one((c for c in n['cases'] if c['work_item_id'] == weather['work_item_id']), 'Weather native two-worker case')
    match_zstd(weather, z, pristine, n)
    clocks = _one((c for c in nr['cases'] if c['case_id'] == z['case_id']), 'Weather native clock distribution')
    alp = pr['inputs']['alp-fused']
    exact = _one((c for c in ar['cases'] if c['id'] == 'alp-exact-profile'), 'exact ALP public ABI case')
    require((exact['dataset'], exact['column'], exact['rows']) == (alp['dataset_id'], alp['geometry']['column'], alp['geometry']['row_range']) and
            _file_id(exact['inputs']['values']) == alp['original']['raw'] and _file_id(exact['inputs']['schema']) == alp['original']['schema'] and
            _file_id(ar['frame_inventory']['alp-exact-profile/alp-auto']) == alp['expected_m3_frame'] and
            _file_id(a['runtime']['files']['lib/libalp_native.so']) == pristine['libalp_native.so'],
            'ALP multiscale control does not use same frozen fused input and frame')
    both = {life: ar['execution_info'][f'alp-exact-profile/alp-auto/{life}/decode'] for life in abi.LIVES}
    require(all(x['backend'] == alp['native_config']['effective_backend'] and x['falp_avx2_vectors'] == alp['native_config']['fused_vectors']
                for x in both.values()), 'ALP matched effective fused work differs')
    body = {'schema': MULTISCALE_SCHEMA, 'm3_plan': p['m3_plan'],
            'seals': {tag: reference(root, local_file(run, 'completion.json')) for tag, run in
                      [('native', native_run), ('multiscale_abi', abi_run), ('profile', profile_run)]},
            'abi_verified_direction_trials': ar['trials'], 'profile_verified_direction_trials': pr['verified_operations'],
            'profiled_route_classes': sorted(pr['inputs']), 'scale_regimes': sorted(c['regime'] for c in ar['cases']),
            'weather_zstd': {'native_case_id': z['case_id'], 'profile_case_id': weather['case_content_id'], 'native_worker_lane_2': {
                op: clocks['lanes'][op]['2'] for op in abi.DIRECTIONS}},
            'alp': {'profile_case_id': alp['case_content_id'], 'multiscale_exact_case': exact['id'], 'actual_decode': both},
            'not_estimated': {'cross_scope_wall_delta_ns': None, 'reason': 'ABI result-ready, lzbench call-wall sum, profile L0 and file path are distinct'},
            'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}
    return {**body, 'audit_id': content_id(body)}, ar


def _overlap_policy(environment):
    require(set(environment) == {'before', 'after'}, 'M4 comparison needs both sealed environment snapshots')
    observations = {when: snapshot['overlap'] for when, snapshot in environment.items()}
    return {'declared_functional_overlap': any(value is not None for value in observations.values()),
            'sealed_snapshots': observations,
            'host_exclusivity_established': False,
            'interpretation': 'a functional overlap declaration is not a measurement of concurrent activity; '
                              'its absence does not establish host exclusivity'}


def _bind_multiscale(root, link_path, profile_run, profile_seal):
    link_path = link_path.resolve(strict=True)
    require(link_path.is_relative_to(root), 'M4 multiscale link outside project')
    link = load_json(link_path)
    require(link.get('schema') == MULTISCALE_SCHEMA and set(link.get('seals', {})) == {'profile', 'multiscale_abi', 'native'},
            'unknown M4 multiscale link contract')
    require(link['seals']['profile'] == profile_seal, 'M4 multiscale link targets a different profile seal')
    runs = {}
    for tag in ('native', 'multiscale_abi'):
        seal = checked_file(root, link['seals'][tag])
        require(seal.name == 'completion.json', 'M4 multiscale link must bind a completion seal')
        runs[tag] = seal.parent
    replayed, abi_report = _replay_multiscale(root, runs['native'], runs['multiscale_abi'], profile_run)
    require(replayed == link, 'M4 multiscale link differs from recomputation')
    return {'link': reference(root, link_path), 'audit_id': link['audit_id'], 'seals': link['seals'],
            'abi_report': reference(root, runs['multiscale_abi'] / 'report.json'),
            'abi_verified_direction_trials': abi_report['trials'],
            'scale_regimes': link['scale_regimes'], 'paired_groups': len(abi_report['pairs']),
            'scope': abi_report['policy']['scope'],
            'interpretation': 'diagnostics on frozen eligible shapes and plugins only; '
                              'not a subtraction from profiling L0, native call clocks, or durable file time'}


def compare(root: Path, profile_run: Path, timing_runs: dict, *, multiscale_link: Path | None = None):
    root = root.resolve(strict=True)
    profile_run = profile_run.resolve(strict=True)
    require(set(timing_runs)==set(profile.NATIVE_ROUTE) and profile_run.is_relative_to(root), 'incomplete M4 cost comparison run binding')
    observed = profile.recompute(profile_run)
    require(observed==load_json(profile_run/'report.json'), 'stored M4 report differs from replay')
    pplan = load_json(profile_run/'plan.json')
    pristine = {Path(r['path']).name:_file_id(r) for r in pplan['assets']['plain']}
    cases = {}
    for name, user_run in timing_runs.items():
        run = user_run.resolve(strict=True)
        require(run.is_relative_to(root), 'M3 timing evidence outside project')
        plan = load_json(run/'plan.json')
        c = observed['inputs'][name]
        ref = plan['main_plan'] if name=='zstd-mt' else plan['functional']['plan']
        require(ref==pplan['m3_plan'], 'M3 and M4 do not target the same full plan')
        verify = lz.verify if name=='zstd-mt' else batch.report_timing
        measured = verify(run)
        require(measured==load_json(run/'report.json'), 'stored M3 report differs from replay')
        def wanted(x):
            return x['work_item_id']==c['work_item_id'] and (name=='zstd-mt' or x['geometry']==c['geometry'] and
                  (name!='alp-fused' or x['decode_backend']==c['native_config']['m3_decode_dispatch']))
        t = _one((x for x in plan['cases'] if wanted(x)), f'{name} exact timing case')
        if name=='zstd-mt':
            match_zstd(c,t,pristine,plan)
            m = _one((m for m in measured['cases'] if m['case_id']==t['case_id']), 'Zstd timing')
            work = {}
            for op in profile.DIRECTIONS:
                rows = [r for r in _rows(run/'trials.jsonl') if (r['case_id'],r['lane'],r['direction'],r['phase']) ==
                        (t['case_id'],'2',op,'measured')]
                want = t['variants']['2']['expected'][op]['jobs']
                require(len(rows)==plan['policy']['rounds'] and all(r['native']['jobs']==want for r in rows),
                        'Zstd measured native job participation differs from the profile case')
                work[op] = [{'round':r['round'],'calls':r['native']['calls'],'jobs':r['native']['jobs']} for r in rows]
            diagnostics = {'clock':'supervised_process_including_driver_io', 'native_whole_operation_wall_ns':None,
                           'native_clock_reason':plan['policy']['native_operation_clock_missing'],
                           'measured_native_work':work, 'lane_2':m['lanes']['2']}
        else:
            match_batch(name,c,t,pristine,plan)
            groups = [g for g in measured['groups'] if g['case_id']==t['case_id']]
            diagnostics = {'clock':'same_public_ABI_matched_batch_ns_divided_by_inner_loop_count',
                           'lifecycles':_batch_summary(groups,plan['config']['matched_rounds'])}
        cases[name] = {'profile_case_id':c['case_content_id'], 'main_case_id':t['case_id'],
                       'same_native_library':pristine['liblzbench_native.so' if name=='zstd-mt' else BATCH_CASES[name]],
                       'geometry':c['geometry'],'source':c['original'],'frame':c['expected_m3_frame'],
                       'configuration':c['native_config'], 'main_timing':diagnostics, 'profiling':_profile_summary(observed,name),
                       'main_environment':measured['environment'], 'main_seal':reference(root,run/'completion.json'),
                       'cross_driver_overhead_ns':None,
                       'not_equivalent':'profile L0 omits plugin framing and original ingress; includes setup/cleanup and output serialization'}
    profile_seal = reference(root, profile_run / 'completion.json')
    controls = _bind_multiscale(root, multiscale_link, profile_run, profile_seal) if multiscale_link is not None else None
    body = {'schema':SCHEMA, 'profile_seal':profile_seal, 'profile_environment':observed['environment'],
            'M3_plan':pplan['m3_plan'], 'cases':cases, 'multiscale_abi_diagnostics':controls,
            'policy':{'subtract_only_matched_same_scope_pairs':True,
            'interference':_overlap_policy(observed['environment']),
            'unmeasured':{'profile_codec_internal_allocation_or_copy_counts':None,
                          'host_exclusivity':None, 'cross_scope_framework_overhead_ns':None}},
            'stage_accepted':False,'timing_admitted':False,'qualification_granted':False}
    return {**body,'comparison_id':content_id(body)}
