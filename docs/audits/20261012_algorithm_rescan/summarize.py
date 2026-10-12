"""Join fresh finite receipts with preserved full-scope acceptance evidence."""
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
QUAL = ROOT / 'build/algorithm-rescan-20261012/active33-r1'
OLD = ROOT / 'docs/audits/20261011_closure_formal_verification'


def read(path):
    return json.loads(path.read_text())


def ref(path):
    return {'path': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def check_ref(item):
    path = Path(item['path'])
    if not path.is_absolute():
        path = ROOT / path
    observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {'path': item['path'], 'expected_sha256': item['sha256'],
            'actual_sha256': observed,
            'status': 'PASS' if observed == item['sha256'] else 'FAIL'}


source = read(OUT / 'source_closure/report.json')
factory = read(OUT / 'factory_runtime.json')
routes = read(ROOT / 'docs/audits/20261011_porting_standard/rewrite_routes.json')
gates = read(OLD / 'gate_acceptance_review/acceptance_review_r1.json')
supplement = read(OLD / 'gate_acceptance_review/scope_clarification_build_supplement_r1.json')
index = read(OLD / 'final_index_r4.json')
formal_path = ROOT / 'build/closure-formal-verification-20261011/formal-r3/runs/formal_audit_post_queue_semantic.json'
formal = read(formal_path)
plan = read(QUAL / 'plan.json')
summary = read(QUAL / 'summary.json')
scope = read(ROOT / 'registry/algorithm_scope.json')
cases = {c['case_id']: c for c in (read(p) for p in (QUAL / 'cases').glob('*.json'))}
sources = {r['codec_key']: r for r in source['rows']}
factories = {r['codec']: r for r in factory['results']}
route_map = {r['codec']: r for r in routes['entries']}
gate_map = {r['codec_key']: r for r in gates['entries']}
checks = {
    'prior_final_index': [check_ref(r) for r in index['evidence']],
    'prior_gate_inputs': [check_ref(r) for r in gates['inputs'].values()],
    'later_gate_supplement_inputs': [check_ref(r) for r in supplement['inputs'].values()],
    'fresh_source_inputs': [check_ref(r) for r in source['inputs']],
}
assert all(c['status'] == 'PASS' for group in checks.values() for c in group), checks
assert sorted(scope['registered_codecs']) == sorted(plan['active_keys']) == sorted(sources)
assert summary['status'] == 'SCOPED_QUALIFICATION_COMPLETE'
assert summary['observed_track_cases'] == len(cases) == 41
assert supplement['unchanged_gate_status_counts'] == gates['gate_status_counts']
rows = []
for entry in plan['entries']:
    key = entry['codec_key']
    s, f, r, g = sources[key], factories[key], route_map[key], gate_map[key]
    for field in ('algorithm_id', 'source_artifact_id'):
        assert entry[field] == s[field] == f[field], (key, field)
    assert s['installed_source_closure']['status'] == f['status'] == 'PASS'
    selected = []
    for planned in entry['cases']:
        case = cases[planned['case_id']]
        assert case['plan_id'] == plan['plan_id']
        assert case['codec_key'] == key
        assert case['acceptance']['status'] == 'SCOPED_PASS'
        assert all(case['acceptance']['checks'].values())
        assert not case['performance_eligible']
        selected.append({
            'case_id': case['case_id'], 'track': planned['track'],
            'dataset_key': planned['dataset_key'], 'parameters': planned['parameters'],
            'status': case['acceptance']['status'],
            'checks': case['acceptance']['checks'],
            'evidence': ref(next(p for p in (QUAL / 'cases').glob('*.json')
                                 if read(p)['case_id'] == case['case_id'])),
        })
    rows.append({
        'codec_key': key, 'algorithm_id': entry['algorithm_id'],
        'source_artifact_id': entry['source_artifact_id'],
        'implementation_route': r['implementation_route'], 'actual_core': r['actual_core'],
        'registered_profile_scope': r['registered_profile_scope'],
        'declared_input': entry['declared_domain'],
        'declared_execution': entry['declared_execution'],
        'declared_features': entry['declared_features'],
        'fresh_selected_source_closure': 'PASS', 'fresh_factory_and_native_load': 'PASS',
        'fresh_selected_cases': selected,
        'full_scope_gate_statuses': {x['gate']: x['status'] for x in g['gates']},
        'full_scope_acceptance_granted': g['all_required_gates_accepted'],
        'current_limitations': g['current_limitations_after_new_receipts'],
        'unexecuted_domains': 'UNKNOWN_NOT_PROMOTED',
    })
report = {
    'schema_version': 'tscb.algorithm-rescan.v1',
    'created_at': datetime.now(timezone.utc).isoformat(),
    'status': 'ALL_ACTIVE_ENTRIES_FINITE_SCOPED_PASS_FULL_ACCEPTANCE_NOT_GRANTED',
    'driver': ref(Path(__file__)),
    'fresh_checks': {
        'active_entries': len(rows), 'selected_track_cases': len(cases),
        'selected_case_status_counts': dict(Counter(c['acceptance']['status'] for c in cases.values())),
        'selected_source_closure_counts': source['installed_source_closure_status_counts'],
        'upstream_authorities': source['authority_count'],
        'upstream_git_blobs': source['all_authority_blob_count'],
        'factory_real_native_entries': factory['native_entries'],
        'factory_status': factory['status'],
        'route_counts': dict(Counter(r['implementation_route'] for r in rows)),
    },
    'preserved_prior_evidence': {
        'full_scope_gate_status_counts': gates['gate_status_counts'],
        'gate_count': gates['applicable_gate_row_count'],
        'gate_supplement_status': supplement['status'],
        'formal_lane_count': formal['lane_count'],
        'verified_formal_lane_count': formal['verified_current_formal_lane_count'],
        'formal_lanes': [{'lane': x['lane'], 'status': x['status'], 'gaps': x.get('gaps', [])}
                         for x in formal['lanes']],
        'fresh_builds_or_full_pytest_executed_by_this_rescan': False,
    },
    'retained_out_of_scope': scope['retained_out_of_scope_registrations'],
    'hash_checks': checks,
    'evidence': [ref(p) for p in [OUT / 'source_closure/report.json', OUT / 'factory_runtime.json',
                 QUAL / 'plan.json', QUAL / 'summary.json', QUAL / 'four_matrices.json',
                 OLD / 'final_index_r4.json', OLD / 'gate_acceptance_review/acceptance_review_r1.json',
                 OLD / 'gate_acceptance_review/scope_clarification_build_supplement_r1.json', formal_path]],
    'full_upstream_parity_granted': False, 'full_N_G_CAP_acceptance_granted': False,
    'performance_remeasured': False, 'rows': rows,
}
with (OUT / 'report.json').open('x') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')

route_names = {'SOURCE_REWRITE': '源码翻译重写', 'NATIVE_PORT': '原生移植', 'NATIVE_REUSE': '原生复用'}
lines = ['# 2026-10-12 已接入算法重新扫描', '',
    '**结论：33 个活动入口的 C/C++ 核心及当前选定适配配置均可运行；不能判定每个算法已完整完成上游移植／重写。**', '',
    '原生移植、原生复用和从其他语言重写是不同路线，无需让每个算法同时完成两种路线。Python 仍承担 Benchmark 调度、布局、FFI 和部分容器处理；“原生”在本报告中指算法核心。', '',
    '本轮新执行：33/33 安装源码限定集合与字节闭包 PASS，17 个锁定原仓的 14,331 个 Git blob 检查通过；36 个真实登记入口工件／实际动态加载 PASS（另有 4 个 harness oracle）；33 活动入口的 41 个 Track/配置/fixture 案例全部 SCOPED_PASS。每例的边界安全、编解码正确性、成本账本及独立进程恢复检查均通过。', '',
    '每个声明 Track 只选一个有限 fixture/config，不代表所有声明参数、长度、模型、ISA、平台、流式／查询能力均已覆盖。对有损算法按该入口合同验证，不能把 SCOPED_PASS 理解为逐位无损或质量全面达标。', '',
    '完整门禁引用并核验最新冻结验收及后续构建补充：220 条适用条件为 3 PASS、32 FAIL、185 UNKNOWN，无入口获全部门禁通过。FAIL 包括未测试及 API／合同／独立交付缺项，不能读成 32 个算法运行失败；UNKNOWN 也不表示算法损坏。新资格案例不会自动替代完整 G/N/CAP 验收。', '',
    '以下各行的源码、工件加载、本轮所列案例均通过；最后一列列出完整验收中仍明确 FAIL 的条件，其余未通过项为 UNKNOWN。N 族所有 N0–N5 仍为 UNKNOWN。', '',
    '| 算法 | 路线 | 本轮通过案例（Track / fixture） | 完整验收中 FAIL |',
    '|---|---|---|---|']
for row in rows:
    selected = '<br>'.join(c['track'] + ' / ' + c['dataset_key'] for c in row['fresh_selected_cases'])
    failed = ', '.join(k for k,v in row['full_scope_gate_statuses'].items() if v == 'FAIL') or '无；N0–N5 UNKNOWN'
    lines.append(f"| `{row['codec_key']}` | {route_names[row['implementation_route']]} | {selected} | {failed} |")
lines += ['', '## 逐项适配域与限制', '']
for row in rows:
    lines += [f"- **{row['codec_key']}**：{row['registered_profile_scope']} 完整性限制：{row['current_limitations']}"]
lines += ['', '## 正式运行与证据边界', '',
    '既有新 FORMAL 队列共 16 lane，当前只确认 entropy、stream、query-warm、query-fresh 共 4 lane。entropy 为 CORE_COMPLETE 16/16，包含 fse、huff0、lz4-frame、zstd-frame；后三项为 PROFILE_COMPLETE。pipeline pilot 不具资格，其余保留资源压力、停止、不支持或汇总缺口。cold 修复后另有原 raw 重分析回执，未重测。lane 缺口不能归因为每个参与算法都编解码失败。', '',
    '精确 TF 旧源环境和 GPU 已恢复；DeepZip 的新源对照仍有独立预测 CDF 1/15 整数差异；DZip 当前 native-seeded untrained 模型不同于原 TensorFlow 初始化和已训练 PRNN。环境可用不自动授予模型／源码语义一致性。', '',
    '`lzss-raw` 当前生产核心为 C++，固定 EI=10/EJ=4/C=32；Rust 原作对照不属于生产依赖，固定 profile 通过不能证明原 Rust 全部 generic/dynamic/in-place API 完整重写。', '',
    'bzip2-stream、lzsse2-raw、lzsse8-raw 仅保留登记并通过加载，本轮未授活动资格。未在本轮重新执行 67 构建配置、33 strict release 构建、全部 pytest 或性能测量；这些已有记录均按各自原范围引用。', '',
    f"证据哈希重新核验：最终旧索引 {len(checks['prior_final_index'])} 项、冻结验收输入 {len(checks['prior_gate_inputs'])} 项、后续补充输入 {len(checks['later_gate_supplement_inputs'])} 项、本轮源码输入快照 {len(checks['fresh_source_inputs'])} 项全部匹配。算法和 SourceArtifact 身份在新源码、工厂及资格计划之间逐项一致。", '',
    '机器可读逐项结果及 SHA 见 [report.json](report.json)；实际资格记录见 [summary.json](../../../build/algorithm-rescan-20261012/active33-r1/summary.json) 与 [four_matrices.json](../../../build/algorithm-rescan-20261012/active33-r1/four_matrices.json)。旧证据未改签，完整上游 parity／独立交付／全域运行及性能资格均未由本次有限检查授予。', '',
    '复现命令：', '', '```bash',
    '/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/source_closure/audit_sources.py --output-dir <新的源码审计目录>',
    'PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261012_algorithm_rescan/check_factory.py',
    '/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/qualify_v32_active_entries.py --output build/algorithm-rescan-20261012/active33-r1 --resume --execute',
    '```', '',
    '工厂脚本及本汇总脚本使用排他写入以保护现有回执；再次新测须先使用副本配置新的输出位置。', '']
with (OUT / 'README.md').open('x') as stream:
    stream.write('\n'.join(lines))
print(json.dumps({k: report[k] for k in ['status', 'fresh_checks', 'full_upstream_parity_granted']}, ensure_ascii=False, indent=2))
