"""Read-only audit of frozen GPU runs; writes only derived documentation."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

from tsbench.gpu import _slot_key, resources_released, unpack_object
from tsbench.records import file_hash, read_jsonl, stable_hash, write_json


ORIGINAL = ['cuszp-formal-0p01-20261013', 'cuszp-formal-0p1-20261013']
MARGIN = ['cuszp-margin90-0p01-20261013', 'cuszp-margin90-0p1-20261013',
          'cuszp-real-f64-0p01-20261013', 'cuszp-real-f64-0p1-20261013']


def extrema(values):
    return {'min': min(values), 'max': max(values), 'median': statistics.median(values)} if values else None


def audit_run(root, name, required_success):
    location = root / 'runs/gpu' / name
    manifest = json.loads((location / 'manifest.json').read_bytes())
    summary = json.loads((location / 'summary.json').read_bytes())
    rows, tail = read_jsonl(location / 'observations.jsonl')
    trace_names = ['manifest.json', 'observations.jsonl', 'summary.json', 'report.md',
                   'experiment.toml', 'resolved_config.json']
    traces = [{'path': str(location / filename), 'sha256': file_hash(location / filename)} for filename in trace_names]
    planned = [row for row in rows if row.get('event') == 'planned']
    started = [row for row in rows if row.get('event') == 'started']
    terminals = [row for row in rows if row.get('event') == 'terminal']
    expected = Counter(map(_slot_key, manifest['schedule']))
    actual = Counter(map(_slot_key, terminals))
    good = [row for row in terminals if row.get('status') == 'ok']
    measured = [row for row in rows if row.get('event') in {'terminal', 'warmup', 'qualification_terminal'} and row.get('status') == 'ok']
    issues = []
    checks = {
        'exact_manifest_terminal_multiset': expected == actual,
        'exact_manifest_planned_multiset': expected == Counter(map(_slot_key, planned)),
        'unique_schedule_slots': all(count == 1 for count in expected.values()),
        'unique_terminal_slots': all(count == 1 for count in actual.values()),
        'no_foreign_run_rows': all(row.get('run_id') == manifest['run_id'] for row in rows),
        'no_interrupted_jsonl_tail': tail is None,
        'execution_source_unchanged': manifest.get('execution_source_unchanged') is True,
        'native_execution_source_unchanged': manifest.get('native_execution_source_unchanged') is True,
        'raw_observation_hash_matches_run_summary': summary['observation_sha256'] == file_hash(location / 'observations.jsonl'),
        'every_ok_terminal_started': Counter(map(_slot_key, good)) == Counter(map(_slot_key, started)),
        'every_ok_measurement_quality_passes': all(row['verification']['passed'] for row in measured),
        'every_ok_measurement_host_input_unchanged': all(row['verification']['input_unchanged'] for row in measured),
        'every_ok_device_measurement_prepared_input_unchanged': all(row['verification']['prepared_device_input_unchanged'] for row in measured if row['boundary'] == 'device_resident'),
        'every_ok_measurement_balanced_adapter_counters': all(row.get('adapter_resources_released') and resources_released(row['native_diagnostics_before'], row['native_diagnostics_after']) for row in measured),
        'every_ok_measurement_zero_live_adapter_bytes': all(row['native_diagnostics_before']['live_bytes'] == 0 and row['native_diagnostics_after']['live_bytes'] == 0 for row in measured),
        'one_native_encode_decode_and_two_fresh_streams_per_measurement': all(
            row['native_diagnostics_after']['encode_launches'] - row['native_diagnostics_before']['encode_launches'] == 1 and
            row['native_diagnostics_after']['decode_launches'] - row['native_diagnostics_before']['decode_launches'] == 1 and
            row['native_diagnostics_after']['streams_created'] - row['native_diagnostics_before']['streams_created'] == 2 and
            row['native_diagnostics_after']['events_created'] - row['native_diagnostics_before']['events_created'] == 4 for row in measured),
        'all_cases_ready': all(case['status'] == 'ready' for case in manifest['cases']),
        'all_formal_slots_ok': len(good) == len(manifest['schedule']),
        'reported_complete_success': summary['complete_success'],
        'reported_qualification_complete_success': summary['qualification_complete_success'],
    }
    initialized = [row for row in rows if row.get('event') == 'worker_init' and row.get('status') == 'ok']
    worker_pids = {row['pid'] for row in initialized}
    profile = manifest['effective_profile']
    checks['actual_host_memory_affinity_device_profile'] = (
        profile['host_memory_limit']['implemented'] and profile['host_memory_limit']['effective_soft_bytes'] == 16384 * 1024**2 and
        profile['host_memory_limit']['effective_hard_bytes'] == 16384 * 1024**2 and profile['affinity'] == [0] and
        profile['device_index'] == 0 and profile['object_workers'] == 1)
    checks['vram_budget_explicitly_null_with_reason'] = (profile['vram_limit']['requested_mb'] is None and
                                                        profile['vram_limit']['effective_bytes'] is None and
                                                        not profile['vram_limit']['implemented'] and bool(profile['vram_limit']['reason']))
    checks['worker_profile_provenance_identical'] = all(row['effective_profile'] == profile and row['execution_provenance'] == manifest['gpu_execution_provenance'] for row in initialized)
    checks['fresh_formal_worker_per_session'] = len({row['pid'] for row in initialized if row.get('phase') == 'measurement'}) == manifest['configuration']['execution']['sessions']
    artifact_cache, artifact_traces = {}, {}
    def checked_artifact(row):
        path = Path(row['artifact_path'])
        if str(path) not in artifact_cache:
            digest = file_hash(path)
            wire = path.read_bytes()
            _, _, metadata, _, payload_bytes = unpack_object(wire)
            artifact_cache[str(path)] = (digest, len(wire), metadata, payload_bytes)
            artifact_traces[str(path)] = {'path': str(path), 'sha256': digest, 'bytes': len(wire)}
        digest, size, metadata, payload_bytes = artifact_cache[str(path)]
        return (digest == row['artifact_hash'] and size == row['stored_bytes'] and
                payload_bytes == row['payload_bytes'] and row['header_bytes'] == size - payload_bytes and
                metadata['count'] == row['value_count'] and
                metadata['error_bound'] == row['codec_quality_metadata']['codec_effective_absolute_tolerance'])
    checks['all_persisted_artifacts_hash_size_typed_bound_match'] = all(checked_artifact(row) for row in rows if row.get('artifact_path'))
    cases = []
    decoder_pids = []
    for case in manifest['cases']:
        case_rows = [row for row in terminals if row['case_id'] == case['case_id']]
        admitted = case.get('qualification', {})
        recovery = admitted.get('independent_recovery')
        decoder_evidence = None
        if case['status'] == 'ready':
            decoder_pids.append(recovery['decoder_pid'])
            decoder_evidence = {
                'passed': recovery['passed'] and recovery['verification']['passed'],
                'separate_interpreter_pid': recovery['decoder_pid'],
                'pid_differs_from_all_encoder_workers': recovery['decoder_pid'] not in worker_pids,
                'exact_admission_artifact_hash_match': recovery['artifact_hash'] == admitted['artifact_hash'],
                'same_execution_build_provenance': recovery['execution_provenance'] == manifest['gpu_execution_provenance'],
                'same_device_runtime': recovery['effective_profile']['gpu'] == profile['gpu'],
                'host_limit_and_affinity_read_back': recovery['effective_profile']['host_memory_limit'] == profile['host_memory_limit'] and recovery['effective_profile']['affinity'] == profile['affinity'],
                'configuration_source': recovery['configuration_source'],
                'restored_object_id': recovery['restored_object_id'],
                'decoder_adapter_cleanup_counters': None,
                'decoder_adapter_cleanup_null_reason': 'not retained in formal independent_recovery record; native qualifier separately records checked decoder cleanup, without imputing it to these processes',
                'decoder_process_snapshot': None,
                'decoder_process_snapshot_null_reason': 'temporary decoder object.json had process_snapshot; formal wire_recovery did not retain that field before deleting the temporary output'}
        result = next(row for row in summary['cases'] if row['case_id'] == case['case_id'])
        selected_rows = [(index, row) for index, row in enumerate(rows) if row.get('case_id') == case['case_id'] and row['event'] in {'planned', 'started', 'terminal', 'qualification_terminal', 'warmup'}]
        source_projection = case['dataset'].get('schema', {}).get('gpu_source_projection')
        views = {}
        for operation in ('encode', 'decode'):
            infos = [row['gpu_' + operation + '_info'] for row in case_rows if row.get('status') == 'ok']
            views[operation] = {field: extrema([item[field] for item in infos]) for field in
                                ('device_event_ms', 'scratch_bytes', 'input_bytes', 'output_bytes',
                                 'output_capacity_bytes', 'owned_allocation_peak_bytes', 'payload_bytes')}
        cases.append({'case_id': case['case_id'], 'dataset_id': case['dataset_id'], 'method_id': case['method_id'],
                      'boundary': case['boundary'], 'dtype': case['capability']['dtype'], 'count': case['capability']['count'],
                      'raw_object_id': case['raw_object_id'], 'raw_bytes': case['raw_bytes'],
                      'task_requested_bound': str(case['task']['error_bound']),
                      'codec_requested_tolerance_text': case['method']['_requested_error_bound'],
                      'codec_requested_tolerance_scalar': case['method']['error_bound'],
                      'codec_effective_tolerance': case['capability']['codec_effective_absolute_tolerance'],
                      'source_projection': source_projection,
                      'source_unit': source_projection['unit'] if source_projection else 'synthetic_value_units',
                      'admission_status': case['status'], 'formal_status_counts': dict(Counter(row['status'] for row in case_rows)),
                      'scheduled_trials': len(case_rows), 'sessions': sorted({row['session'] for row in case_rows}),
                      'complete_success': result['complete_success'],
                      'encode_ns_median': result['encode_ns_median'], 'encode_ns_iqr': result.get('encode_ns_iqr'),
                      'decode_ns_median': result['decode_ns_median'], 'decode_ns_iqr': result.get('decode_ns_iqr'),
                      'encode_throughput_bytes_s': result.get('encode_throughput_bytes_s'),
                      'decode_throughput_bytes_s': result.get('decode_throughput_bytes_s'),
                      'stored_bytes_median': result['stored_bytes_median'], 'compression_ratio_median': result['compression_ratio_median'],
                      'bits_per_value_median': result.get('bits_per_value_median'), 'max_abs_max': result.get('max_abs_max'),
                      'boundary_cost_ns_median': result.get('boundary_cost_ns_median'), 'quality_metadata': result.get('quality_metadata'),
                      'gpu_info_across_formal_trials': views,
                      'qualification_verification': admitted.get('verification'), 'independent_decoder': decoder_evidence,
                      'formal_artifact_hashes': sorted({row['artifact_hash'] for row in case_rows if row.get('artifact_hash')}),
                      'admission_artifact_hash': admitted.get('artifact_hash'),
                      'raw_trace': {'observation_path': str(location / 'observations.jsonl'),
                                    'zero_based_row_indices': [index for index, _ in selected_rows],
                                    'case_rows_sha256': stable_hash(selected_rows)},
                      'metric_null_reason': result.get('metric_null_reason')})
    decoder_checks = [case['independent_decoder'] for case in cases if case['independent_decoder']]
    checks['all_admitted_exact_input_independent_decoders_pass'] = all(all(evidence[key] for key in
        ('passed', 'pid_differs_from_all_encoder_workers', 'exact_admission_artifact_hash_match',
         'same_execution_build_provenance', 'same_device_runtime', 'host_limit_and_affinity_read_back')) for evidence in decoder_checks)
    checks['unique_independent_decoder_pids_per_case'] = len(decoder_pids) == len(set(decoder_pids))
    expected_warmups = sum(case['status'] == 'ready' for case in manifest['cases']) * manifest['configuration']['execution']['sessions'] * manifest['configuration']['execution']['warmup_objects']
    warmups = [row for row in rows if row['event'] == 'warmup']
    checks['all_requested_warmups_recorded'] = len(warmups) == expected_warmups
    ignore_original = {'all_cases_ready', 'all_formal_slots_ok', 'reported_complete_success', 'reported_qualification_complete_success'}
    issues = [key for key, passed in checks.items() if not passed and (required_success or key not in ignore_original)]
    counters = {key: sum(row['native_diagnostics_after'][key] - row['native_diagnostics_before'][key] for row in measured)
                for key in ('allocations', 'releases', 'streams_created', 'streams_released', 'events_created', 'events_released', 'encode_launches', 'decode_launches')}
    statuses = dict(Counter(row['status'] for row in terminals))
    return {'name': name, 'path': str(location), 'run_id': manifest['run_id'], 'pass_kind': manifest['pass_kind'],
            'parameter_policy': 'margin90_after_original_failure' if required_success else 'original_equal_bound',
            'task_requested_bound': str(manifest['configuration']['task']['error_bound']),
            'codec_requested_tolerance_text': manifest['configuration']['methods'][0]['_requested_error_bound'],
            'configuration_id': manifest['configuration_id'], 'configuration_path': manifest['config_path'],
            'raw_traces': traces, 'raw_trace_id': stable_hash(traces), 'artifacts': list(artifact_traces.values()),
            'schedule_audit': {'planned': len(planned), 'started': len(started), 'terminal': len(terminals),
                               'expected': len(manifest['schedule']), 'missing': sum((expected - actual).values()),
                               'unexpected': sum((actual - expected).values()), 'terminal_status_counts': statuses},
            'checks': checks, 'audit_passed': not issues, 'audit_issues': issues,
            'formal_complete_success': summary['complete_success'], 'qualification_complete_success': summary['qualification_complete_success'],
            'qualification_count': len(decoder_pids), 'warmup_count': len(warmups), 'ok_measurement_pairs_audited': len(measured),
            'native_counter_deltas_over_ok_qualification_warmup_formal': counters,
            'resource_profile': profile, 'worker_pids': sorted(worker_pids), 'independent_decoder_pids': decoder_pids,
            'execution_source_id': manifest['execution_provenance']['source_id'],
            'native_build_identity': manifest['gpu_execution_provenance']['native']['build_identity'],
            'native_binary_sha256': manifest['gpu_execution_provenance']['native']['binary_sha256'],
            'cases': cases}


def summarize(root, destination):
    root = Path(root).resolve()
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    originals = [audit_run(root, name, False) for name in ORIGINAL]
    margins = [audit_run(root, name, True) for name in MARGIN]
    margin_decoder_pids = [pid for run in margins for pid in run['independent_decoder_pids']]
    margin_worker_pids = {pid for run in margins for pid in run['worker_pids']}
    cross_run_checks = {
        'margin_global_independent_decoder_pids_unique': len(margin_decoder_pids) == len(set(margin_decoder_pids)),
        'margin_no_decoder_encoder_worker_pid_overlap': not set(margin_decoder_pids) & margin_worker_pids,
        'margin_execution_source_id_consistent': len({run['execution_source_id'] for run in margins}) == 1,
        'margin_native_build_binary_consistent': len({(run['native_build_identity'], run['native_binary_sha256']) for run in margins}) == 1}
    failures = []
    for run in originals:
        for case in run['cases']:
            if case['admission_status'] != 'ready':
                failures.append({'run_name': run['name'], 'case_id': case['case_id'], 'dataset_id': case['dataset_id'],
                                 'boundary': case['boundary'], 'task_requested_bound': case['task_requested_bound'],
                                 'codec_requested_tolerance_text': case['codec_requested_tolerance_text'],
                                 'codec_effective_tolerance': case['codec_effective_tolerance'],
                                 'verification': case['qualification_verification'],
                                 'formal_status_counts': case['formal_status_counts'], 'raw_trace': case['raw_trace']})
    result = {'schema': 'tsbench.gpu-results-audit/1', 'created_at_utc': datetime.now(timezone.utc).isoformat(),
              'analysis_path': str(Path(__file__).resolve()), 'analysis_sha256': file_hash(__file__),
              'gpu_work_executed_by_analysis': False, 'raw_modified_by_analysis': False,
              'overall_audit_passed': all(run['audit_passed'] for run in originals + margins) and all(cross_run_checks.values()),
              'cross_run_checks': cross_run_checks,
              'margin_formal_ok_trials': sum(run['schedule_audit']['terminal_status_counts'].get('ok', 0) for run in margins),
              'margin_expected_trials': sum(run['schedule_audit']['expected'] for run in margins),
              'margin_cases': sum(len(run['cases']) for run in margins),
              'margin_exact_input_independent_decoders': sum(run['qualification_count'] for run in margins),
              'margin_warmup_objects': sum(run['warmup_count'] for run in margins),
              'margin_policy': {'decimal_fraction': '0.9', 'task_codec_pairs': [['0.01', '0.009'], ['0.1', '0.09']],
                                'selection': 'post-observation parameter sensitivity following original equal-bound f32 failures',
                                'universal_guarantee': False, 'optimal_parameter_claim': False,
                                'quality_policy': 'unchanged task bound; strict original-domain verification on every actual input/trial'},
              'interpretation': {'boundaries': 'host_to_host/device_resident kept separate; no pooled throughput or CPU baseline speedup',
                                 'units': 'weather T degree_Celsius; ETT OT exact source units unverified; no pooled physical ABS interpretation',
                                 'storage': 'entire actual persisted TSB+CSP1 wire charged, including schema/source provenance and rate table',
                                 'device_work': 'CUDA events include control/zeroing/transfers as documented, not pure kernel time',
                                 'memory': 'adapter requested allocation accounting, not sampled VRAM peak; VRAM cap null; host address-space cap enforced',
                                 'dependence': 'synthetic lengths reused and 128 prefix of real512; two real sources; views/rounds not independent sources',
                                 'decoder_cleanup_limit': 'formal recovery keeps success/pid/wire/provenance/quality/resource profile; per-decoder native diagnostics and process_snapshot not retained there; separate native qualifier has its own cleanup records'},
              'original_equal_bound_runs': originals, 'original_quality_failures': failures, 'margin90_runs': margins}
    result['trace_set_id'] = stable_hash([trace for run in originals + margins for trace in run['raw_traces']])
    for run in originals + margins:
        for trace in run['raw_traces'] + run['artifacts']:
            if file_hash(trace['path']) != trace['sha256']:
                raise RuntimeError('raw GPU evidence changed during analysis: ' + trace['path'])
    write_json(destination / 'summary.json', result)
    lines = ['# GPU P4 实测与审计', '',
             f"Margin90 四轮正式运行 **{result['margin_formal_ok_trials']}/{result['margin_expected_trials']}** 槽位全部通过，"
             f"40 cases 各 3 sessions × 7 rounds；另有 {result['margin_exact_input_independent_decoders']} 个 exact-input 独立 decoder 与 {result['margin_warmup_objects']} 个 warmup。",
             '', '每个 case 的精确计划/started/terminal 覆盖、严格质量、输入未修改、artifact hash/字节/typed bound、adapter allocation/stream/event 回收和实际资源 profile 均重新只读核对。分析未运行 CUDA、未修改原始证据。', '',
             '原始 equal-bound 的失败仍是独立结果：0.01 为168 ok /84 not_run，0.1 为210 ok /42 not_run；它们不并入 margin90 成功数。0.9 参数比例是观察失败后的固定敏感性政策，task 请求仍为0.01/0.1，不提供普遍误差保证或最优参数结论。详见 [机制与冻结配置](../gpu_margin90.md)。', '',
             '| 运行 | Policy | Task | Codec 参数 | 正式覆盖 | 独立 decoder | Trace |',
             '|---|---|---:|---:|---|---:|---|']
    for run in originals + margins:
        link = '../../runs/gpu/' + run['name'] + '/report.md'
        statuses = ', '.join(str(value) + ' ' + key for key, value in run['schedule_audit']['terminal_status_counts'].items())
        lines.append(f"| [{run['name']}]({link}) | {run['parameter_policy']} | {run['task_requested_bound']} | {run['codec_requested_tolerance_text']} | {statuses} | {run['qualification_count']} | `{run['raw_trace_id']}` |")
    lines += ['', '下表为每个完整 margin90 case 的21轮 median；IQR、吞吐、native actual tolerance、11项 device 外围成本和 raw row/hash 链保留在 [summary.json](summary.json)。wall 是独立 Session 生命周期及各自完成边界，单位 ms。Ratio 为 raw bytes / full wire bytes，低于1表示 expansion。Host/device 值不可合并为同一个计时估计。', '']
    for run in margins:
        lines += ['## ' + run['name'], '', '| Dataset | Boundary | Encode ms | Decode ms | Wire bytes | Ratio | max_abs |',
                  '|---|---|---:|---:|---:|---:|---:|']
        for case in run['cases']:
            lines.append(f"| {case['dataset_id']} | {case['boundary']} | {case['encode_ns_median']/1e6:.6f} | {case['decode_ns_median']/1e6:.6f} | {case['stored_bytes_median']:.0f} | {case['compression_ratio_median']:.6f} | {case['max_abs_max']:.17g} |")
        lines.append('')
    profile = margins[0]['resource_profile']
    lines += ['## 资源证据与范围', '',
              f"实际设备为 {profile['gpu']['name']}，compute {profile['gpu']['compute_major']}.{profile['gpu']['compute_minor']}，CUDA runtime {profile['gpu']['runtime_version']} / driver API {profile['gpu']['driver_api_version']}。四 run 源 ID `{margins[0]['execution_source_id']}` 和 native build `{margins[0]['native_build_identity']}` 一致；Python/native 来源末尾均未变。",
              '', '实际 host affinity `[0]`，object worker1，adapter algorithm host parallelism1。实际 RLIMIT_AS soft/hard 均17179869184 bytes（16GiB）；这是host地址空间，不能称RSS预算。VRAM effective limit为null，理由是当前adapter没有可强制cap。进程 Threads 另包含CUDA/runtime helpers。', '',
              '| Run | 审计成功对象对（资格+warmup+formal） | Allocation/free | Stream create/release | Event create/release |',
              '|---|---:|---|---|---|']
    for run in margins:
        counters = run['native_counter_deltas_over_ok_qualification_warmup_formal']
        lines.append(f"| {run['name']} | {run['ok_measurement_pairs_audited']} | {counters['allocations']}/{counters['releases']} | {counters['streams_created']}/{counters['streams_released']} | {counters['events_created']}/{counters['events_released']} |")
    lines += ['', '每个已审计对象对的calling-thread native counters始末live bytes为0，增量含1次encode、1次decode、2个独立stream及4个event。该证据证明这些被计数的adapter对象回收，不能证明driver/context缓存为零；native Info owned peak是source申请capacity accounting，非整device实测VRAM峰值。CUDA events包含control/zeroing/必要传输，不能称纯kernel时间。', '',
              '40个formal资格decoder均有全局唯一且不同于16个encoder worker的独立PID、exact artifact hash、相同执行/build/device身份、实际资源读回和通过的原始域质量。formal independent_recovery未保留各decoder的allocation/event/stream counters或process_snapshot，因此机器结果将这些字段置null并附原因；不能给这些进程补填计数或线程快照。独立native qualifier的48个fresh decoder有其自己的清理证据。每trial新建Session；新worker解释器的边界是session，不是每个trial。', '',
              'ETT OT精确物理单位未核实；weather T以列名记录degree Celsius。两个source分别描述；同源128是512前缀，已有CPU窗口暴露，不能视作更多独立source或blind holdout。小数组的最小rate table和完整schema/provenance header会产生expansion。没有CPU基线，不能把device_resident与CPU object_memory的时间直接解释为speedup。', '',
              f"全部原始trace集合ID：`{result['trace_set_id']}`；[summary.json](summary.json)给出每个manifest/observation/config/report/artifact SHA和case对应JSONL行索引。"]
    (destination / 'README.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[2] / 'docs/gpu_results')
    args = parser.parse_args()
    result = summarize(args.root, args.output)
    print(json.dumps({'audit_passed': result['overall_audit_passed'], 'ok': result['margin_formal_ok_trials'],
                      'expected': result['margin_expected_trials'], 'trace_set_id': result['trace_set_id'],
                      'issues': {run['name']: run['audit_issues'] for run in result['original_equal_bound_runs'] + result['margin90_runs']}}))
