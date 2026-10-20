"""Frozen full-file GPU supplement and read-only report integration."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
import shutil
import tomllib

import numpy as np

from tsbench.records import file_hash

BOUNDARIES = ('host_to_host', 'device_resident')


def prepare(design_path):
    from generate_all_core_experiments import value as toml_value
    from tsbench.gpu import load
    path = Path(design_path).resolve()
    design = json.loads(path.read_text())
    if design.get('gpu_configurations'):
        raise FileExistsError('GPU supplement already frozen')
    amendment = path.parent/'amendments/gpu-host-access'
    amendment.mkdir(parents=True, exist_ok=False)
    shutil.copy2(path, amendment/'design_before.json')
    initial = path.parent/'gpu_availability.json'
    shutil.copy2(initial, amendment/'sandbox_availability.json')
    datasets = {}
    for entry in design['configurations']:
        for item in tomllib.loads(Path(entry['path']).read_text())['datasets']:
            datasets.setdefault(item['id'], item)
    documents = []
    for dtype in ('f64', 'f32'):
        name = 'gpu-all-'+dtype+'-abs-0p01'
        document = {
            'schema': 'tsbench.gpu-experiment/1', 'name': name,
            'asset_root': str(path.parents[3]),
            'output': str(Path(design['run_root'])/name),
            'boundaries': list(BOUNDARIES),
            'task': {'kind': 'values', 'fidelity': 'bounded_abs', 'error_bound': '0.01',
                     'lifecycle': 'independent_object', 'cache_policy': 'natural',
                     'special_values': 'bitwise', 'invalid_values': 'preserve'},
            'profile': {'id': 'cuda-device0-host-single', 'device': 'cuda',
                        'device_index': 0, 'native_threads': 1, 'object_workers': 1,
                        'host_memory_limit_mb': 16384, 'affinity': [0]},
            'execution': {'sessions': 2, 'rounds': 7, 'warmup_objects': 1,
                          'seed': 20261018, 'timeout_s': 1800, 'save_artifacts': False},
            'methods': [{'id': 'cuszp-fixed-1d', 'codec': 'cuszp-fixed-1d', 'error_bound': '0.01'}],
            'datasets': [datasets[row['id']+'-'+dtype] for row in design['selected']],
        }
        config = path.parent/(name+'.toml')
        lines=['# Full representative files; host GPU supplement frozen before GPU execution.']
        for key in ('schema','name','asset_root','output','boundaries'):
            lines.append(key+' = '+toml_value(document[key]))
        for key in ('task','profile','execution'):
            lines += ['', '['+key+']']
            lines += [k+' = '+toml_value(v) for k,v in document[key].items()]
        for key in ('methods','datasets'):
            for item in document[key]:
                lines += ['', '[['+key+']]']
                lines += [k+' = '+toml_value(v) for k,v in item.items()]
        config.write_text('\n'.join(lines)+'\n')
        load(config)
        documents.append({'path': str(config), 'sha256': file_hash(config),
                          'run': document['output'], 'requests': 106, 'dtype': dtype,
                          'boundaries': list(BOUNDARIES), 'lifecycle': 'independent_object'})
    record = {'time': datetime.now().astimezone().isoformat(),
              'reason': 'Sandbox NVIDIA access failed, but host nvidia-smi succeeded: RTX 2070, driver 535.288.01, CUDA driver 12.2. Run GPU build and measurements on host after the CPU sweep. All 53 complete f64/f32 objects retained; rank2 and other domain rejections remain explicit. No column selection or flattening.',
              'device': 'NVIDIA GeForce RTX 2070', 'driver': '535.288.01',
              'architecture': 75, 'gpu_execution_pending': True}
    record_path = amendment/'amendment.json'
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    design['gpu_configurations'] = documents
    design['gpu_requested_cases'] = sum(e['requests'] for e in documents)
    design.setdefault('execution_amendments', []).append(str(record_path))
    path.write_text(json.dumps(design, ensure_ascii=False, separators=(',', ':'))+'\n')
    initial.write_text(json.dumps({**record, 'status': 'available_pending_build',
                                   'measurement_executed': False,
                                   'initial_sandbox_evidence': str(amendment/'sandbox_availability.json')},
                                  ensure_ascii=False, indent=2))
    with (path.parent/'README.md').open('a') as stream:
        stream.write('\nGPU 宿主机补充：隔离环境的 nvidia-smi 失败不代表宿主机不可用；宿主机确认 RTX 2070、驱动535.288.01可用。CPU结束后在宿主机构建并测量 cuSZp，53份完整f64和f32输入、2种边界，共212请求。rank2与域不支持保留拒绝，不截取单列、不flatten。GPU独立对象生命周期和CPU双生命周期分开展示。\n')
    return documents


def audit_gpu(design, object_ids):
    from tsbench.gpu import _slot_key, resources_released
    rows, audits = [], []
    for entry in design.get('gpu_configurations', []):
        assert file_hash(entry['path']) == entry['sha256']
        root = Path(entry['run'])
        manifest = json.loads((root/'manifest.json').read_text())
        summary = json.loads((root/'summary.json').read_text())
        assert manifest['state'] == 'complete'
        assert manifest['execution_source_unchanged'] is True
        assert manifest['native_execution_source_unchanged'] is True
        assert summary['observation_sha256'] == file_hash(root/'observations.jsonl')
        assert summary['schedule_integrity']['complete']
        events = [json.loads(line) for line in (root/'observations.jsonl').open()]
        terminals = [r for r in events if r['event'] == 'terminal']
        expected = Counter(map(_slot_key, manifest['schedule']))
        assert expected == Counter(map(_slot_key, terminals))
        assert all(n == 1 for n in expected.values())
        assert all(r['attempt'] == 0 for r in terminals)
        products = 0
        for row in events:
            if row.get('artifact_path'):
                assert file_hash(row['artifact_path']) == row['artifact_hash']
            if row['event'] not in {'terminal', 'warmup', 'qualification_terminal'} or row.get('status') != 'ok':
                continue
            assert row['verification']['passed'] and row['verification']['input_unchanged']
            if row['boundary'] == 'device_resident':
                assert row['verification']['prepared_device_input_unchanged']
            assert row['adapter_resources_released']
            assert resources_released(row['native_diagnostics_before'], row['native_diagnostics_after'])
            if row['event'] == 'terminal':
                products += 1
        cases = {case['case_id']: case for case in manifest['cases']}
        for result in summary['cases']:
            case = cases[result['case_id']]
            if case['status'] == 'ready':
                assert case['qualification']['independent_recovery']['passed']
            if case.get('raw_object_id'):
                assert object_ids[case['dataset_id']] == {case['raw_object_id']}
            trials = [r for r in terminals if r['case_id'] == case['case_id'] and r['status'] == 'ok']
            good = result['complete_success']
            row = {**result, 'codec': 'cuszp-fixed-1d', 'complete_case': good,
                   'dtype': '<f8' if entry['dtype'] == 'f64' else '<f4',
                   'source_file': case['dataset']['source'],
                   'raw_bytes': case.get('raw_bytes'),
                   'compression_ratio': result['compression_ratio_median'],
                   'encode_MiB_s': result.get('encode_throughput_bytes_s', 0)/2**20 if good else None,
                   'decode_MiB_s': result.get('decode_throughput_bytes_s', 0)/2**20 if good else None,
                   'reason': case.get('reason') or next((r.get('reason') or r['status'] for r in terminals if r['case_id']==case['case_id'] and r['status'] not in {'ok','not_run'}), None), 'run': str(root),
                   'ok_trials': result['status_counts'].get('ok', 0)}
            for operation in ('encode', 'decode'):
                values = [r[operation+'_ns'] for r in trials]
                row[operation+'_ns'] = dict(zip(('q1', 'q3'), np.quantile(values, [.25, .75]))) if good else None
            rows.append(row)
        audits.append({'run': str(root), 'requests': len(cases), 'verified_formal_products': products,
                       'schedule_integrity': summary['schedule_integrity'],
                       'status_counts': summary['terminal_status_counts'],
                       'admission_counts': dict(Counter(c['status'] for c in cases.values())),
                       'effective_profile': manifest.get('effective_profile'),
                       'files': [{'path': str(root/name), 'sha256': file_hash(root/name)} for name in
                                 ('manifest.json', 'observations.jsonl', 'summary.json', 'resolved_config.json')]})
    assert len(rows) == design.get('gpu_requested_cases', 0)
    return rows, audits


def report_gpu(rows, audits, output, chart, number):
    import csv
    fields = ['run', 'dataset_id', 'dtype', 'boundary', 'admission_status', 'complete_case',
              'raw_bytes', 'stored_bytes_median', 'compression_ratio', 'encode_MiB_s',
              'decode_MiB_s', 'expected_trials', 'ok_trials', 'reason']
    with (output/'gpu_primary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    good = sum(r['complete_case'] for r in rows)
    ok = sum(r['ok_trials'] for r in rows)
    lines = ['<a id="gpu"></a>', '', '## GPU：cuSZp FIXED 1D', '',
             f'RTX 2070 本轮独立测量：{len(rows)} 个请求，{good} 个完整有效案例，{ok} 个成功正式批次。CPU的5,486个请求和GPU的212个请求分别审计。', '',
             '初始隔离环境无法访问 NVIDIA 驱动；宿主机检查确认可用，随后在全部CPU测量结束后构建并执行本节测量。原隔离环境失败证据保留。', '',
             '使用相同53份完整f64输入及单独声明的f32转换输入，保持原始rank和全部行列。原生1D接口不支持的多变量矩阵、特殊值和超范围数据保留拒绝。ABS任务界限和codec参数均为0.01；任何实际恢复超界均保留失败，不增加容差。', '',
             '**边界单独解释**：GPU为 independent_object 生命周期，每案例2 sessions × 7 rounds，每session每案例1次预热。host_to_host计入会话建立、传输、封装和主机恢复；device_resident以已准备的设备输入/载荷为起点，传输、持久化和下载另记。两者均为含Python/FFI的同步完成操作墙钟，不是CPU native_core计时，也不是纯kernel CUDA event时间，不与CPU混合排名。GPU存储大小使用执行器的完整持久化object wire，包含自描述schema与CSP1 header，范围与CPU的完整codec输出不同。', '',
             '[GPU逐案例CSV](gpu_primary.csv) · [GPU审计证据](audit.json)', '']
    for audit in audits:
        lines += [f'- 原始结果：[{Path(audit["run"]).name}](../../runs/forecasting-20261018-1614/{Path(audit["run"]).name}/report.md)；资格状态 `{audit["admission_counts"]}`，正式终态 `{audit["status_counts"]}`。']
    lines += ['', '### GPU固定家族均值', '',
              '| dtype | boundary | 有效／固定家族 | 平均压缩倍数 | 平均编码MiB/s | 平均解码MiB/s |',
              '|---|---|---:|---:|---:|---:|']
    for dtype in ('<f8', '<f4'):
        for boundary in BOUNDARIES:
            rs = [r for r in rows if r['dtype'] == dtype and r['boundary'] == boundary]
            valid = sum(r['complete_case'] for r in rs)
            values = [number(float(np.mean([r[m] for r in rs]))) if valid == 53 else '—' for m in ('compression_ratio', 'encode_MiB_s', 'decode_MiB_s')]
            lines.append(f'| {dtype} | {boundary} | {valid}/53 | '+' | '.join(values)+' |')
    lines += ['', '缺少任一家族的完整有效结果即不计算该组固定集合均值，不以成功子集补齐。', '']
    by_source = defaultdict(list)
    for row in rows:
        by_source[Path(row['source_file']).stem].append(row)
    for source, members in sorted(by_source.items()):
        pairs = defaultdict(dict)
        for row in members:
            pairs[row['dtype']][row['boundary']] = row
        drawable = {name: pair for name, pair in pairs.items() if any(r['complete_case'] for r in pair.values())}
        lines += [f'### GPU · {source}', '']
        if drawable:
            slug = 'gpu-'+source
            chart(drawable, source+' / GPU ABS <= 0.01 / independent_object', output/'figures'/slug, lives=BOUNDARIES)
            lines += [f'![{source} GPU](figures/{slug}.png)', '', f'[SVG](figures/{slug}.svg)', '']
        lines += ['<details><summary>GPU完整数值和拒绝原因</summary>', '',
                  '| dtype | boundary | 完整bytes | 压缩倍数 | 编码MiB/s | 解码MiB/s | 有效/计划批次 | 资格状态与原因 |',
                  '|---|---|---:|---:|---:|---:|---:|---|']
        for r in sorted(members, key=lambda r: (r['dtype'], r['boundary'])):
            metrics = [number(r[m]) if r['complete_case'] else '—' for m in ('stored_bytes_median', 'compression_ratio', 'encode_MiB_s', 'decode_MiB_s')]
            lines.append(f'| {r["dtype"]} | {r["boundary"]} | '+' | '.join(metrics)+f' | {r["ok_trials"]}/{r["expected_trials"]} | {r["admission_status"]}: {r["reason"] or "—"} |')
        lines += ['', '</details>', '']
    return lines


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('design', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.design), indent=2))
