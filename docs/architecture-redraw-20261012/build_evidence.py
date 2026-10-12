"""Bind all visible nodes to exact current-working-tree symbols and file hashes."""
import ast, hashlib, json, subprocess
from pathlib import Path
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
B={
'dataset_identity': [('datasets/registry.py','DatasetRegistry'),('datasets/canonical_source.py','register_canonical_source')],
'logical_inputs':[('datasets/prepare.py','prepare_dataset'),('datasets/canonical.py','write_canonical'),('pipelines/models.py','LogicalObjectSchema')],
'codec_sources':[('codecs/registry.py','CodecRegistry'),('codecs/registry.py','SourceRegistry'),('adapters/factory.py','create_adapter')],
'contract_bundle':[('comparison/decision.py','freeze_experiment_decision'),('comparison/models.py','ComparisonContract'),('comparison/models.py','ExpectedOutcomeMatrix')],
'compiled_matrix':[('comparison/planning.py','compile_group_plan'),('comparison/projection.py','public_projection'),('execution/schedule.py','build_schedule'),('comparison/runner.py','prepare_comparison')],
'qualification_gate':[('comparison/runner.py','qualify_comparison'),('execution/preflight.py','preflight_task'),('execution/recovery.py','decode_in_fresh_worker')],
'pilot_gate':[('comparison/runner.py','pilot_comparison'),('measurement/v32_protocol.py','run_pilot'),('comparison/pipeline_runner.py','pilot_pipeline_comparison')],
'formal_workers':[('comparison/runner.py','execute_comparison'),('comparison/workload_runner.py','execute_workload_comparison'),('comparison/pipeline_runner.py','execute_pipeline_comparison'),('execution/isolation.py','run_isolated')],
'persistent_trials':[('comparison/runner.py','_append_trial'),('comparison/pipeline_runner.py','_commit_attempt'),('comparison/pipeline_runner.py','_attempt_state'),('storage/events.py','append_event')],
'readonly_statistics':[('comparison/analysis.py','analyze_comparison'),('comparison/analysis.py','_effect'),('comparison/analysis_extensions.py','augment_analysis')],
'scoped_reports':[('comparison/runner.py','report_comparison'),('comparison/report_renderer.py','render_comparison_report'),('tools/audit_v32_completion.py','audit')],
'legacy_contract':[('runner.py','initialize_run_set'),('runner.py','plan_run_set'),('runner.py','execute_run_set'),('runner.py','report_run_set')],
'legacy_plan':[('configuration.py','ExperimentConfig'),('planning/tasks.py','create_task'),('runner.py','plan_run_set')],
'legacy_execute':[('execution/orchestrator.py','execute_task'),('execution/repetition.py','perform_worker_measurement')],
'legacy_report':[('reporting/generator.py','generate_report'),('statistics/engine.py','analyze_run_set')],
'comparison_plan':[('comparison/runner.py','prepare_comparison'),('comparison/models.py','ComparisonContract')],
'comparison_execute':[('comparison/runner.py','execute_comparison'),('execution/cold_driver.py','measure_cold_object')],
'comparison_report':[('comparison/runner.py','report_comparison'),('comparison/analysis.py','analyze_comparison')],
'workload_plan':[('comparison/workload_runner.py','prepare_workload_comparison'),('measurement/workloads.py',None)],
'workload_execute':[('comparison/workload_runner.py','execute_workload_comparison'),('execution/workload_driver.py',None)],
'workload_report':[('comparison/workload_runner.py','report_workload_comparison')],
'p2_plan':[('comparison/pipeline_runner.py','prepare_pipeline_comparison'),('pipelines/models.py','PipelineRecipe'),('pipelines/models.py','LogicalObject')],
'p2_execute':[('comparison/pipeline_runner.py','execute_pipeline_comparison'),('pipelines/runtime.py','encode_object')],
'p2_report':[('comparison/pipeline_runner.py','report_pipeline_comparison'),('comparison/pipeline_runner.py','_audit_trials')],
'original_domain':[('execution/routing.py','route_canonical_artifact'),('validation/input.py','validate_routed_input'),('pipelines/models.py','LogicalObject')],
'explicit_transform':[('execution/preparation.py','prepare_execution_input'),('adapters/compatibility.py','apply_compatibility_plan'),('preprocess/runtime.py',None)],
'encoding_session':[('execution/repetition.py','_encode'),('execution/protocol.py','CodecSession')],
'finalized_artifact':[('execution/protocol.py','EncodedArtifact'),('execution/recovery.py','bind_decode_context')],
'recovery_worker':[('execution/recovery.py','decode_in_fresh_worker'),('execution/recovery.py','restore_decoded_output'),('comparison/pipeline_runner.py','_independent_decode')],
'correctness_contract':[('validation/correctness.py','validate_common_correctness'),('validation/lossy.py','validate_error_bound'),('pipelines/runtime.py','validate_restored_object')],
'paid_accounting':[('accounting/ledger.py','AccountingLedger'),('execution/recovery.py','bind_decode_context')],
'trial_observation':[('execution/repetition.py','perform_measured_roundtrip'),('measurement/resources.py','ResourceSampler'),('measurement/resource_lease.py','ResourceLease')],
'stored_evidence':[('storage/runs.py','append_run_record'),('comparison/runner.py','_append_trial'),('comparison/pipeline_runner.py','_commit_attempt')],
'eligible_analysis':[('comparison/analysis.py','trial_issues'),('comparison/analysis.py','analyze_comparison'),('comparison/analysis_extensions.py','augment_analysis')],
}
D={
'dataset_identity':'数据集注册验证内容、许可证声明与身份。显式派生记录父级来源；不隐式改变原始时间顺序、数值类型或缺失语义。',
'logical_inputs':'Legacy 准备 Canonical 工件与特征报告；P2 使用 LogicalObject/LogicalObjectSchema 表达完整时间、值、validity、类型、shape、轴和单位。P2 输入不强制通过 legacy canonical 二进制 wire。',
'codec_sources':'CodecManifest 描述输入域、参数域、损失模式与资源能力；SourceArtifact 绑定来源/构建工件。factory 选择注册 adapter；ISA 变体、参数与别名不自动成为新的算法方法。',
'contract_bundle':'V3.2 在测量前冻结 Task、Contract、Group、Corpus、ConfigMap、ExpectedOutcomeMatrix、MeasurementProtocol 和 AnalysisPolicy。CORE 有共同原生 API/实际输入的额外限制。',
'compiled_matrix':'完整候选矩阵保留预期不支持的单元与公共输入投影，再绑定 ExecutionJob、源码/构建闭包、环境和真实 Schedule。Coverage 分母来自冻结全集。',
'qualification_gate':'preflight 检查真实输入、边界、原域正确性和保存产物的独立恢复。按 ExpectedOutcomeMatrix 核对支持或拒绝。图中连线展示满足合同的通过路线；不代表当前所有 lane 都合格。',
'pilot_gate':'使用独立 development 数据/对象评估时钟阈值、内循环长度和采集扰动，保留原始 pilot 证据。pilot 校验通过才开放正式试次。',
'formal_workers':'四条路径保留各自 runner：Legacy、V3.2 comparison、workload、P2。隔离进程执行，独立对象按内循环逐个 Finalize；同次采集计时和资源。',
'persistent_trials':'保存 trials、工件、事件、失败和预算。未知 STARTED 或中断不能被静默当作未运行；正式路径按自己的事件链与预算合同恢复。',
'readonly_statistics':'只读复核冻结身份与原始产物，先筛选合格试次。V3.2 以真实 Schedule block 配对 bootstrap，估计均值时间比，校正多重区间并检验精度；质量、Pareto 与 Coverage 是描述性扩展。',
'scoped_reports':'输出 JSON/HTML/Markdown，并保留 INCONCLUSIVE、NOT_RUN、PARTIAL、失败与缺测。推断限于冻结语料和主机；SOURCE_PARITY、CORE、PROFILE、FORMAL 等范围由独立审计确认。',
'legacy_contract':'Legacy TOML 通过 runner.py 的 init → prepare → plan → validate → report 使用自己的任务、run record 与统计合同。它的三级可比性键不转授 V3.2 新比较组资格。',
'legacy_plan':'读取 ExperimentConfig，展开参数 sweep 与完整任务组合，能力协商后绑定适配/预处理/资源解析、三级可比性键及 task_plan。',
'legacy_execute':'execute_task 先 preflight，再在隔离 worker 内执行本进程 warmup 与测量。warmup 达到固定门槛不等于证明统计稳态。查询与流式辅助 profile 保留独立记录。',
'legacy_report':'统计引擎按资格与可比性键分组，保留 median 口径、bootstrap 区间、Coverage 和 Pareto；generate_report 写只读 JSON/CSV/HTML/Markdown 产物。',
'comparison_plan':'prepare_comparison 编译 common-task bundle，冻结实际输入、全矩阵、Protocol、AnalysisPolicy、构建与源码闭包以及 Schedule。qualify 与独立 pilot 是正式测量门禁。',
'comparison_execute':'STEADY_PROCESS 或冷启动完整对象走注册边界；COMMON_NATIVE_API 的 CORE 是原生组件边界。PIPELINE 与 CORE 的成本/计时分母分开，不能混合排序。',
'comparison_report':'report_comparison 重核冻结 plan 和 trial 工件，再运行 paired block 分析。效应是 FIRST/SECOND 均值时间比；精度或实用差异不满足时输出 INCONCLUSIVE。',
'workload_plan':'workload_runner 在 comparison 公共输入合同之上冻结 stream/query 专用 Protocol、requests/序列、缓存/会话模式、调度与独立 pilot。不是普通 roundtrip 的统计别名。',
'workload_execute':'执行流式 chunk/state/finalize 或查询工作负载，保留查询请求、warm/fresh 会话、stream 工件与资源证据。使用冻结 wall 预算和 STARTED 事件处理失败与中断。',
'workload_report':'重核 workload_trials 及对应 artifact/请求身份，按各 profile 的计时边界与正确性输出报告。PROFILE_COMPLETE 由相应范围审计确认。',
'p2_plan':'P2 有独立 preparation API：冻结 LogicalObject、PipelineRecipe、输入快照、codec 子闭包、完整比较矩阵和协议。支持 mixed / ND / 非默认 time_axis 等显式对象结构。',
'p2_execute':'Pipeline runtime 按配方编码完整 T/V/mask 与子流/块，计入容器、RAW_TAIL 和恢复依赖；独立解码验证完整原对象。执行器持久预留预算并提交 Attempt/Trial 事件。',
'p2_report':'重核 pipeline trials、保存字节、ledger、原域正确性及 attempt 事件链。P2 使用自己的报告协议，不能用“流程已实现”声称当前 pilot 或 FORMAL 已通过。',
'original_domain':'路由后的 Legacy 原对象持有只读逻辑 buffers 和原域参考；P2 使用完整 LogicalObject。验证 DatasetID、dtype、shape、单位、时间/值/mask 与内容哈希。',
'explicit_transform':'CompatibilityPlan 与 PreprocessPlan 把输入域变换写成显式合同，执行时验证实际缓冲区。恢复所需信息随 DecodeContext 或完整容器保存，成本记入 ledger。',
'encoding_session':'一个对象的 adapter session 生命周期包括 create_session、output_bound、compress_update、finalize、accounting、close。检查输入不可变与 output canary；每个内循环对象独立 Finalize。',
'finalized_artifact':'EncodedArtifact 保存最终 stream、stream SHA、Update/Finalize 长度、AccountingLedger 与恢复上下文。恢复必须从已保存字节和已付费依赖开始。',
'recovery_worker':'资格/审计用新的 worker 解码已保存产物，再恢复原 dtype/shape/语义。正式 steady roundtrip 的解码在同一测量 worker 中执行；本图表示对象与证据闭环，非单一函数调用时序。',
'correctness_contract':'在原域验证时间配对、通道顺序、validity 与逐位无损/误差界；有损质量基于原对象。专用 Rate/Summary task validator 不自动建立算法或正式组资格。',
'paid_accounting':'AccountingLedger 的互斥分量闭合 SerializedBits；FinalBits = SerializedBits + ExternalSideInformationBits，物理字节仅在完整边界取整。CORE 对比采用其注册组件成本，不等同于完整对象 FinalBits。',
'trial_observation':'编码、解码和资源来自同一试次。资源包含 wall/CPU/RSS、父进程线程观测及 collector 可用性；没有的 counters 如实标记 unavailable。图中计量节点是同次观测的职责投影。',
'stored_evidence':'保存原始 trial 与可恢复产物、工件身份和失败原因；最后内循环对象提供公开正确性/成本证据。不同 runner 使用自己的提交与中断协议。',
'eligible_analysis':'先 trial_issues 资格过滤，再在完整冻结矩阵上统计；不支持、失败、未运行和缺测保留在 Coverage。质量/压缩因子/Pareto 是对同一冻结证据的只读扩展。',
}
files={}; nodes=[]
for name in ['overview','lanes','object']:
 m=json.loads((OUT/(name+'.archify.json')).read_text())
 for c in m['components']:
  refs=[]
  for rel,symbol in B[c['id']]:
   rel=rel if rel.startswith('tools/') else 'src/tscompbench/'+rel
   p=ROOT/rel; data=p.read_bytes(); tree=ast.parse(data)
   defs=[x for x in ast.walk(tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and x.name==symbol]
   if symbol and not defs: raise RuntimeError(f'Missing symbol: {rel}:{symbol}')
   refs.append({'path':rel,'symbol':symbol,'line':defs[0].lineno if defs else 1})
   files[rel]={'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
  nodes.append({'view':name,'id':c['id'],'label':c['label'],'description':D[c['id']],'sources':refs})
rec={'as_of':'2026-10-12 Asia/Shanghai','basis':'current working tree, including pre-existing uncommitted edits; no benchmark execution','commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'nodes':nodes,'files':list(files.values()),'edge_semantics':'data/control/evidence dependencies; not a direct-call graph or a claim of current run completion'}
(OUT/'source-evidence.json').write_text(json.dumps(rec,ensure_ascii=False,indent=2)+'\n')
lines=['# 当前源码架构重绘依据','','三张互补图，34 个节点；箭头表示数据、控制或证据依赖。基于当前工作区，包括已有未提交修改。未运行 Benchmark。','']
for n in nodes:
 lines += [f"## {n['label']} · {n['view']}",'',n['description'],'']
 lines += [f"- [{r['path']}:{r['symbol'] or 'module'}]({ROOT/r['path']}:{r['line']})" for r in n['sources']]
 lines.append('')
(OUT/'source-evidence.md').write_text('\n'.join(lines)+'\n')
print('Bound',len(nodes),'nodes to',len(files),'current source files')
