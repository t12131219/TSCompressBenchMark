# 当前源码架构重绘依据

三张互补图，34 个节点；箭头表示数据、控制或证据依赖。基于当前工作区，包括已有未提交修改。未运行 Benchmark。

## 数据来源与身份 · overview

数据集注册验证内容、许可证声明与身份。显式派生记录父级来源；不隐式改变原始时间顺序、数值类型或缺失语义。

- [src/tscompbench/datasets/registry.py:DatasetRegistry](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/registry.py:69)
- [src/tscompbench/datasets/canonical_source.py:register_canonical_source](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical_source.py:185)

## 规范化原对象 · overview

Legacy 准备 Canonical 工件与特征报告；P2 使用 LogicalObject/LogicalObjectSchema 表达完整时间、值、validity、类型、shape、轴和单位。P2 输入不强制通过 legacy canonical 二进制 wire。

- [src/tscompbench/datasets/prepare.py:prepare_dataset](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/prepare.py:108)
- [src/tscompbench/datasets/canonical.py:write_canonical](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical.py:239)
- [src/tscompbench/pipelines/models.py:LogicalObjectSchema](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:32)

## 算法能力与来源 · overview

CodecManifest 描述输入域、参数域、损失模式与资源能力；SourceArtifact 绑定来源/构建工件。factory 选择注册 adapter；ISA 变体、参数与别名不自动成为新的算法方法。

- [src/tscompbench/codecs/registry.py:CodecRegistry](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/registry.py:98)
- [src/tscompbench/codecs/registry.py:SourceRegistry](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/registry.py:40)
- [src/tscompbench/adapters/factory.py:create_adapter](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/adapters/factory.py:346)

## 事前实验合同 · overview

V3.2 在测量前冻结 Task、Contract、Group、Corpus、ConfigMap、ExpectedOutcomeMatrix、MeasurementProtocol 和 AnalysisPolicy。CORE 有共同原生 API/实际输入的额外限制。

- [src/tscompbench/comparison/decision.py:freeze_experiment_decision](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/decision.py:276)
- [src/tscompbench/comparison/models.py:ComparisonContract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:143)
- [src/tscompbench/comparison/models.py:ExpectedOutcomeMatrix](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:347)

## 冻结全矩阵与调度 · overview

完整候选矩阵保留预期不支持的单元与公共输入投影，再绑定 ExecutionJob、源码/构建闭包、环境和真实 Schedule。Coverage 分母来自冻结全集。

- [src/tscompbench/comparison/planning.py:compile_group_plan](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/planning.py:126)
- [src/tscompbench/comparison/projection.py:public_projection](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/projection.py:30)
- [src/tscompbench/execution/schedule.py:build_schedule](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/schedule.py:112)
- [src/tscompbench/comparison/runner.py:prepare_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271)

## 完整原对象资格 · overview

preflight 检查真实输入、边界、原域正确性和保存产物的独立恢复。按 ExpectedOutcomeMatrix 核对支持或拒绝。图中连线展示满足合同的通过路线；不代表当前所有 lane 都合格。

- [src/tscompbench/comparison/runner.py:qualify_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:940)
- [src/tscompbench/execution/preflight.py:preflight_task](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100)
- [src/tscompbench/execution/recovery.py:decode_in_fresh_worker](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:206)

## 独立 development pilot · overview

使用独立 development 数据/对象评估时钟阈值、内循环长度和采集扰动，保留原始 pilot 证据。pilot 校验通过才开放正式试次。

- [src/tscompbench/comparison/runner.py:pilot_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1177)
- [src/tscompbench/measurement/v32_protocol.py:run_pilot](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/v32_protocol.py:558)
- [src/tscompbench/comparison/pipeline_runner.py:pilot_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:702)

## 分 lane 隔离执行 · overview

四条路径保留各自 runner：Legacy、V3.2 comparison、workload、P2。隔离进程执行，独立对象按内循环逐个 Finalize；同次采集计时和资源。

- [src/tscompbench/comparison/runner.py:execute_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377)
- [src/tscompbench/comparison/workload_runner.py:execute_workload_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:867)
- [src/tscompbench/comparison/pipeline_runner.py:execute_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1163)
- [src/tscompbench/execution/isolation.py:run_isolated](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/isolation.py:151)

## 持久原始证据 · overview

保存 trials、工件、事件、失败和预算。未知 STARTED 或中断不能被静默当作未运行；正式路径按自己的事件链与预算合同恢复。

- [src/tscompbench/comparison/runner.py:_append_trial](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:683)
- [src/tscompbench/comparison/pipeline_runner.py:_commit_attempt](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1080)
- [src/tscompbench/comparison/pipeline_runner.py:_attempt_state](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:875)
- [src/tscompbench/storage/events.py:append_event](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/events.py:15)

## 只读重核与统计 · overview

只读复核冻结身份与原始产物，先筛选合格试次。V3.2 以真实 Schedule block 配对 bootstrap，估计均值时间比，校正多重区间并检验精度；质量、Pareto 与 Coverage 是描述性扩展。

- [src/tscompbench/comparison/analysis.py:analyze_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539)
- [src/tscompbench/comparison/analysis.py:_effect](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:482)
- [src/tscompbench/comparison/analysis_extensions.py:augment_analysis](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis_extensions.py:484)

## 报告与结论范围 · overview

输出 JSON/HTML/Markdown，并保留 INCONCLUSIVE、NOT_RUN、PARTIAL、失败与缺测。推断限于冻结语料和主机；SOURCE_PARITY、CORE、PROFILE、FORMAL 等范围由独立审计确认。

- [src/tscompbench/comparison/runner.py:report_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1871)
- [src/tscompbench/comparison/report_renderer.py:render_comparison_report](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/report_renderer.py:325)
- [tools/audit_v32_completion.py:audit](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:311)

## Legacy TOML 路径 · overview

Legacy TOML 通过 runner.py 的 init → prepare → plan → validate → report 使用自己的任务、run record 与统计合同。它的三级可比性键不转授 V3.2 新比较组资格。

- [src/tscompbench/runner.py:initialize_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:188)
- [src/tscompbench/runner.py:plan_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:344)
- [src/tscompbench/runner.py:execute_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:573)
- [src/tscompbench/runner.py:report_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:800)

## Legacy TOML · lanes

读取 ExperimentConfig，展开参数 sweep 与完整任务组合，能力协商后绑定适配/预处理/资源解析、三级可比性键及 task_plan。

- [src/tscompbench/configuration.py:ExperimentConfig](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/configuration.py:80)
- [src/tscompbench/planning/tasks.py:create_task](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/tasks.py:16)
- [src/tscompbench/runner.py:plan_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:344)

## execute_task · lanes

execute_task 先 preflight，再在隔离 worker 内执行本进程 warmup 与测量。warmup 达到固定门槛不等于证明统计稳态。查询与流式辅助 profile 保留独立记录。

- [src/tscompbench/execution/orchestrator.py:execute_task](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:115)
- [src/tscompbench/execution/repetition.py:perform_worker_measurement](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:425)

## generate_report · lanes

统计引擎按资格与可比性键分组，保留 median 口径、bootstrap 区间、Coverage 和 Pareto；generate_report 写只读 JSON/CSV/HTML/Markdown 产物。

- [src/tscompbench/reporting/generator.py:generate_report](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/reporting/generator.py:685)
- [src/tscompbench/statistics/engine.py:analyze_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:1116)

## V3.2 对象与 API · lanes

prepare_comparison 编译 common-task bundle，冻结实际输入、全矩阵、Protocol、AnalysisPolicy、构建与源码闭包以及 Schedule。qualify 与独立 pilot 是正式测量门禁。

- [src/tscompbench/comparison/runner.py:prepare_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271)
- [src/tscompbench/comparison/models.py:ComparisonContract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:143)

## execute_comparison · lanes

STEADY_PROCESS 或冷启动完整对象走注册边界；COMMON_NATIVE_API 的 CORE 是原生组件边界。PIPELINE 与 CORE 的成本/计时分母分开，不能混合排序。

- [src/tscompbench/comparison/runner.py:execute_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377)
- [src/tscompbench/execution/cold_driver.py:measure_cold_object](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/cold_driver.py:394)

## report_comparison · lanes

report_comparison 重核冻结 plan 和 trial 工件，再运行 paired block 分析。效应是 FIRST/SECOND 均值时间比；精度或实用差异不满足时输出 INCONCLUSIVE。

- [src/tscompbench/comparison/runner.py:report_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1871)
- [src/tscompbench/comparison/analysis.py:analyze_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539)

## V3.2 工作负载 · lanes

workload_runner 在 comparison 公共输入合同之上冻结 stream/query 专用 Protocol、requests/序列、缓存/会话模式、调度与独立 pilot。不是普通 roundtrip 的统计别名。

- [src/tscompbench/comparison/workload_runner.py:prepare_workload_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:135)
- [src/tscompbench/measurement/workloads.py:module](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/workloads.py:1)

## execute_workload_comparison · lanes

执行流式 chunk/state/finalize 或查询工作负载，保留查询请求、warm/fresh 会话、stream 工件与资源证据。使用冻结 wall 预算和 STARTED 事件处理失败与中断。

- [src/tscompbench/comparison/workload_runner.py:execute_workload_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:867)
- [src/tscompbench/execution/workload_driver.py:module](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/workload_driver.py:1)

## report_workload_comparison · lanes

重核 workload_trials 及对应 artifact/请求身份，按各 profile 的计时边界与正确性输出报告。PROFILE_COMPLETE 由相应范围审计确认。

- [src/tscompbench/comparison/workload_runner.py:report_workload_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:1205)

## P2 组合流水线 · lanes

P2 有独立 preparation API：冻结 LogicalObject、PipelineRecipe、输入快照、codec 子闭包、完整比较矩阵和协议。支持 mixed / ND / 非默认 time_axis 等显式对象结构。

- [src/tscompbench/comparison/pipeline_runner.py:prepare_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:191)
- [src/tscompbench/pipelines/models.py:PipelineRecipe](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:271)
- [src/tscompbench/pipelines/models.py:LogicalObject](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:140)

## execute_pipeline_comparison · lanes

Pipeline runtime 按配方编码完整 T/V/mask 与子流/块，计入容器、RAW_TAIL 和恢复依赖；独立解码验证完整原对象。执行器持久预留预算并提交 Attempt/Trial 事件。

- [src/tscompbench/comparison/pipeline_runner.py:execute_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1163)
- [src/tscompbench/pipelines/runtime.py:encode_object](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:231)

## report_pipeline_comparison · lanes

重核 pipeline trials、保存字节、ledger、原域正确性及 attempt 事件链。P2 使用自己的报告协议，不能用“流程已实现”声称当前 pilot 或 FORMAL 已通过。

- [src/tscompbench/comparison/pipeline_runner.py:report_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1427)
- [src/tscompbench/comparison/pipeline_runner.py:_audit_trials](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1282)

## 冻结原域输入 · object

路由后的 Legacy 原对象持有只读逻辑 buffers 和原域参考；P2 使用完整 LogicalObject。验证 DatasetID、dtype、shape、单位、时间/值/mask 与内容哈希。

- [src/tscompbench/execution/routing.py:route_canonical_artifact](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/routing.py:52)
- [src/tscompbench/validation/input.py:validate_routed_input](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/input.py:44)
- [src/tscompbench/pipelines/models.py:LogicalObject](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:140)

## 显式路由与预处理 · object

CompatibilityPlan 与 PreprocessPlan 把输入域变换写成显式合同，执行时验证实际缓冲区。恢复所需信息随 DecodeContext 或完整容器保存，成本记入 ledger。

- [src/tscompbench/execution/preparation.py:prepare_execution_input](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preparation.py:23)
- [src/tscompbench/adapters/compatibility.py:apply_compatibility_plan](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/adapters/compatibility.py:67)
- [src/tscompbench/preprocess/runtime.py:module](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/preprocess/runtime.py:1)

## 独立编码对象 · object

一个对象的 adapter session 生命周期包括 create_session、output_bound、compress_update、finalize、accounting、close。检查输入不可变与 output canary；每个内循环对象独立 Finalize。

- [src/tscompbench/execution/repetition.py:_encode](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:180)
- [src/tscompbench/execution/protocol.py:CodecSession](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/protocol.py:114)

## 完整编码产物 · object

EncodedArtifact 保存最终 stream、stream SHA、Update/Finalize 长度、AccountingLedger 与恢复上下文。恢复必须从已保存字节和已付费依赖开始。

- [src/tscompbench/execution/protocol.py:EncodedArtifact](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/protocol.py:92)
- [src/tscompbench/execution/recovery.py:bind_decode_context](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:193)

## 独立解码与恢复 · object

资格/审计用新的 worker 解码已保存产物，再恢复原 dtype/shape/语义。正式 steady roundtrip 的解码在同一测量 worker 中执行；本图表示对象与证据闭环，非单一函数调用时序。

- [src/tscompbench/execution/recovery.py:decode_in_fresh_worker](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:206)
- [src/tscompbench/execution/recovery.py:restore_decoded_output](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:165)
- [src/tscompbench/comparison/pipeline_runner.py:_independent_decode](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:420)

## 原域正确性验证 · object

在原域验证时间配对、通道顺序、validity 与逐位无损/误差界；有损质量基于原对象。专用 Rate/Summary task validator 不自动建立算法或正式组资格。

- [src/tscompbench/validation/correctness.py:validate_common_correctness](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/correctness.py:72)
- [src/tscompbench/validation/lossy.py:validate_error_bound](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/lossy.py:424)
- [src/tscompbench/pipelines/runtime.py:validate_restored_object](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:1076)

## 完整对象比特成本 · object

AccountingLedger 的互斥分量闭合 SerializedBits；FinalBits = SerializedBits + ExternalSideInformationBits，物理字节仅在完整边界取整。CORE 对比采用其注册组件成本，不等同于完整对象 FinalBits。

- [src/tscompbench/accounting/ledger.py:AccountingLedger](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/accounting/ledger.py:14)
- [src/tscompbench/execution/recovery.py:bind_decode_context](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:193)

## 同一试次观测 · object

编码、解码和资源来自同一试次。资源包含 wall/CPU/RSS、父进程线程观测及 collector 可用性；没有的 counters 如实标记 unavailable。图中计量节点是同次观测的职责投影。

- [src/tscompbench/execution/repetition.py:perform_measured_roundtrip](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:498)
- [src/tscompbench/measurement/resources.py:ResourceSampler](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resources.py:195)
- [src/tscompbench/measurement/resource_lease.py:ResourceLease](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resource_lease.py:232)

## 保存试次与恢复证据 · object

保存原始 trial 与可恢复产物、工件身份和失败原因；最后内循环对象提供公开正确性/成本证据。不同 runner 使用自己的提交与中断协议。

- [src/tscompbench/storage/runs.py:append_run_record](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/runs.py:434)
- [src/tscompbench/comparison/runner.py:_append_trial](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:683)
- [src/tscompbench/comparison/pipeline_runner.py:_commit_attempt](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1080)

## 资格筛选后的分析 · object

先 trial_issues 资格过滤，再在完整冻结矩阵上统计；不支持、失败、未运行和缺测保留在 Coverage。质量/压缩因子/Pareto 是对同一冻结证据的只读扩展。

- [src/tscompbench/comparison/analysis.py:trial_issues](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:224)
- [src/tscompbench/comparison/analysis.py:analyze_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539)
- [src/tscompbench/comparison/analysis_extensions.py:augment_analysis](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis_extensions.py:484)

