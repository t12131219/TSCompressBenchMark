"""Capture source-backed diagram dependencies without executing benchmark codecs."""
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BINDINGS = {
    'source_objects': [('datasets/registry.py', 'DatasetRegistry'), ('datasets/canonical_source.py', 'register_canonical_source')],
    'canonical_objects': [('datasets/prepare.py', 'prepare_dataset'), ('datasets/canonical.py', 'write_canonical'), ('pipelines/models.py', 'LogicalObjectSchema')],
    'legacy_lane': [('runner.py', 'initialize_run_set'), ('runner.py', 'plan_run_set'), ('runner.py', 'execute_run_set'), ('runner.py', 'report_run_set')],
    'experiment_contract': [('comparison/decision.py', 'freeze_experiment_decision'), ('comparison/models.py', 'ComparisonContract'), ('comparison/models.py', 'ExpectedOutcomeMatrix')],
    'frozen_comparison': [('comparison/planning.py', 'compile_group_plan'), ('comparison/projection.py', 'public_projection'), ('comparison/runner.py', 'prepare_comparison'), ('comparison/pipeline_runner.py', 'prepare_pipeline_comparison'), ('execution/schedule.py', 'build_schedule')],
    'object_qualification': [('comparison/runner.py', 'qualify_comparison'), ('execution/preflight.py', 'preflight_task'), ('execution/recovery.py', 'decode_in_fresh_worker'), ('comparison/pipeline_runner.py', 'qualify_pipeline_comparison')],
    'development_pilot': [('comparison/runner.py', 'pilot_comparison'), ('measurement/v32_protocol.py', 'run_pilot'), ('comparison/pipeline_runner.py', 'pilot_pipeline_comparison')],
    'isolated_workers': [('comparison/runner.py', 'execute_comparison'), ('comparison/workload_runner.py', 'execute_workload_comparison'), ('comparison/pipeline_runner.py', 'execute_pipeline_comparison'), ('execution/repetition.py', 'perform_measured_roundtrip'), ('measurement/resource_lease.py', 'ResourceLease'), ('pipelines/runtime.py', 'encode_object')],
    'durable_evidence': [('comparison/runner.py', '_append_trial'), ('comparison/pipeline_runner.py', '_commit_attempt'), ('comparison/pipeline_runner.py', '_attempt_state'), ('storage/runs.py', 'append_run_record')],
    'readonly_analysis': [('comparison/analysis.py', 'analyze_comparison'), ('comparison/analysis.py', '_effect'), ('comparison/analysis_extensions.py', 'augment_analysis')],
    'bounded_reports': [('comparison/runner.py', 'report_comparison'), ('comparison/pipeline_runner.py', 'report_pipeline_comparison'), ('comparison/report_renderer.py', 'render_comparison_report')],
    'scope_audits': [('tools/audit_v32_buffer_costs.py', 'build_buffer_cost_audit'), ('tools/audit_v32_uncompressed_reference.py', None), ('tools/audit_v32_completion.py', 'audit')],
}
model = json.loads((OUT / 'framework.archify.json').read_text())
files = {}
nodes = []
for node in model['nodes']:
    refs = []
    for relative, symbol in BINDINGS[node['id']]:
        relative = relative if relative.startswith('tools/') else 'src/tscompbench/' + relative
        path = ROOT / relative
        data = path.read_bytes()
        files[relative] = {'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        matches = [n for n in ast.walk(ast.parse(data)) if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == symbol]
        if symbol and not matches:
            raise RuntimeError(f'Missing source binding: {relative}:{symbol}')
        refs.append({'path': relative, 'symbol': symbol, 'line': matches[0].lineno if matches else 1})
    nodes.append({'id': node['id'], 'label': node['label'], 'source': refs})
old = json.loads((ROOT / 'docs/archify-five-layer-reference/source-evidence.json').read_text())
drift = []
for row in old['files']:
    path = ROOT / row['path']
    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    if actual != row['sha256']:
        drift.append({'path': row['path'], 'old_sha256': row['sha256'], 'current_sha256': actual})
record = {
    'schema_version': 1,
    'as_of': '2026-10-12 Asia/Shanghai',
    'repository_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'working_tree_status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True).splitlines(),
    'basis': 'Current working tree, including user edits present at capture; static source inspection, no benchmark execution',
    'diagram_type': model['diagram_type'],
    'edge_semantics': 'Data/control/evidence dependency; qualification and pilot nodes show passing route only; failures remain diagnostics or prevent formal execution. No claim that every edge is a direct function call.',
    'p2_input_note': 'P2 uses LogicalObject plus public recipe/input snapshots rather than requiring every object to pass through the legacy canonical binary wire. 规范化逻辑原对象 denotes the normalized logical input family in the overview.',
    'nodes': nodes,
    'edges': model['flows'],
    'files': list(files.values()),
    'old_evidence': {'files': len(old['files']), 'changed_files': len(drift), 'drift': drift},
}
(OUT / 'source-evidence.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
lines = ['# 当前数据流程源码证据', '', f"基于当前工作树 `{record['repository_commit']}`；包含捕获时已有的未提交修改。只做源码核对，未运行 Benchmark。", '', '图中箭头表示数据、控制与证据依赖，不等于逐函数调用。P2 原对象使用独立 LogicalObject 合同与公开配方，不强制经过 legacy canonical wire。', '']
for node in nodes:
    lines += [f"## {node['label']} ({node['id']})", '']
    for ref in node['source']:
        lines.append(f"- [{ref['path']}:{ref['symbol'] or 'module'}]({ROOT / ref['path']}:{ref['line']})")
    lines.append('')
lines += [f"## 旧证据漂移：{len(drift)} / {len(old['files'])}", '', '文件指纹变化或缺失说明旧回执不再绑定当前文件，不等同于每个变化都导致图义错误。', '']
lines.extend(f"- {item['path']}" for item in drift)
(OUT / 'source-evidence.md').write_text('\n'.join(lines) + '\n')
print(f'Captured {len(nodes)} nodes, {len(files)} source files; {len(drift)} old file hashes drifted.')
