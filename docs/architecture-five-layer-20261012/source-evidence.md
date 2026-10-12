# 五层运行框架：当前源码依据

以当前工作区实际文件字节为依据；保留已有未提交内容。本次只生成图和查看器，未运行 Benchmark。

箭头表示处理、控制或证据依赖，不是一一对应的函数调用图。虚线表示同次观测、条件分支、证据依赖或对象内部展开。四条执行路径各有自己的 runner 和合同。

## Legacy 命令与配置 · entry

- [src/tscompbench/cli.py:96](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/cli.py:96) · `main`
- [src/tscompbench/configuration.py:397](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/configuration.py:397) · `load_experiment_config`

## 运行身份与环境冻结 · freeze

- [src/tscompbench/runner.py:188](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:188) · `initialize_run_set`
- [src/tscompbench/environment.py:152](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/environment.py:152) · `capture_environment`
- [src/tscompbench/runner.py:283](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:283) · `prepare_run_set`

## 数据集注册与校验 · dataset

- [src/tscompbench/datasets/registry.py:69](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/registry.py:69) · `DatasetRegistry`

## 内容身份与显式派生 · source_identity

- [src/tscompbench/datasets/canonical_source.py:185](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical_source.py:185) · `register_canonical_source`
- [src/tscompbench/comparison/models.py:223](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:223) · `CorpusSpec`
- [src/tscompbench/comparison/pipeline_runner.py:1587](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1587) · `build_real_pipeline_inputs`

## 原域数据加载 · loader

- [src/tscompbench/datasets/loaders.py:314](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/loaders.py:314) · `load_dataset`

## 数据特征分析 · characterize

- [src/tscompbench/datasets/characterize.py:246](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/characterize.py:246) · `characterize`

## Legacy Canonical 工件 · canonical

- [src/tscompbench/datasets/prepare.py:108](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/prepare.py:108) · `prepare_dataset`
- [src/tscompbench/datasets/canonical.py:239](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical.py:239) · `write_canonical`

## P2 逻辑原对象 · logical_object

- [src/tscompbench/pipelines/models.py:32](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:32) · `LogicalObjectSchema`
- [src/tscompbench/pipelines/channel_collection.py:61](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/channel_collection.py:61) · `ChannelCollectionSchema`
- [src/tscompbench/datasets/prepare.py:108](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/prepare.py:108) · `prepare_dataset`

## Codec / Source 注册 · registry

- [src/tscompbench/codecs/registry.py:98](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/registry.py:98) · `CodecRegistry`
- [src/tscompbench/adapters/factory.py:85](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/adapters/factory.py:85) · `adapter_artifacts`
- [src/tscompbench/codecs/registry.py:40](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/registry.py:40) · `SourceRegistry`
- [src/tscompbench/codecs/models.py:64](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/models.py:64) · `CodecManifest`

## 参数扫描与配置生成 · sweep

- [src/tscompbench/planning/sweep.py:82](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/sweep.py:82) · `expand_sweep`

## 完整候选组合展开 · universe

- [src/tscompbench/runner.py:344](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:344) · `plan_run_set`

## 能力协商 · 四态结果 · negotiate

- [src/tscompbench/codecs/negotiation.py:247](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/negotiation.py:247) · `negotiate`

## 显式适配与预处理计划 · plans

- [src/tscompbench/codecs/negotiation.py:247](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/negotiation.py:247) · `negotiate`
- [src/tscompbench/preprocess/contracts.py:69](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/preprocess/contracts.py:69) · `build_preprocess_plan`

## 执行路径解析 · resolution

- [src/tscompbench/planning/resolution.py:33](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/resolution.py:33) · `resolve_execution`

## Legacy 层级可比性键 · keys

- [src/tscompbench/planning/resolution.py:201](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/resolution.py:201) · `build_comparability_keys`
- [src/tscompbench/planning/models.py:59](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/models.py:59) · `ComparabilityKeys`

## Legacy 任务快照 · tasks

- [src/tscompbench/planning/tasks.py:16](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/tasks.py:16) · `create_task`
- [src/tscompbench/runner.py:344](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:344) · `plan_run_set`
- [src/tscompbench/planning/models.py:72](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/models.py:72) · `BenchmarkTask`

## 事前实验决策与合同 · experiment_contract

- [src/tscompbench/comparison/decision.py:276](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/decision.py:276) · `freeze_experiment_decision`
- [src/tscompbench/comparison/models.py:143](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:143) · `ComparisonContract`
- [src/tscompbench/comparison/runner.py:271](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271) · `prepare_comparison`

## 期待矩阵与成员准入 · expected_matrix

- [src/tscompbench/comparison/planning.py:126](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/planning.py:126) · `compile_group_plan`
- [src/tscompbench/comparison/models.py:347](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:347) · `ExpectedOutcomeMatrix`

## 公共投影与实际输入 · public_projection

- [src/tscompbench/comparison/projection.py:30](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/projection.py:30) · `public_projection`
- [src/tscompbench/comparison/planning.py:340](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/planning.py:340) · `validate_job_for_cell`
- [src/tscompbench/comparison/pipeline_runner.py:191](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:191) · `prepare_pipeline_comparison`

## 冻结作业、闭包与调度 · frozen_schedule

- [src/tscompbench/comparison/runner.py:271](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271) · `prepare_comparison`
- [src/tscompbench/execution/schedule.py:112](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/schedule.py:112) · `build_schedule`
- [src/tscompbench/comparison/pipeline_runner.py:191](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:191) · `prepare_pipeline_comparison`

## 任务、来源与构建门控 · gates

- [src/tscompbench/execution/preflight.py:100](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100) · `preflight_task`

## 按 Benchmark Track 路由 · track

- [src/tscompbench/execution/routing.py:52](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/routing.py:52) · `route_canonical_artifact`

## 实际输入校验 · input

- [src/tscompbench/validation/input.py:44](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/input.py:44) · `validate_routed_input`

## 适配与适配后校验 · adapter

- [src/tscompbench/execution/preparation.py:23](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preparation.py:23) · `prepare_execution_input`
- [src/tscompbench/adapters/compatibility.py:67](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/adapters/compatibility.py:67) · `apply_compatibility_plan`
- [src/tscompbench/adapters/compatibility.py:188](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/adapters/compatibility.py:188) · `validate_prepared_input`

## 可选预处理阶段验证 · preprocess

- [src/tscompbench/preprocess/runtime.py:18](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/preprocess/runtime.py:18) · `validate_pipeline_stages`
- [src/tscompbench/preprocess/runtime.py:10](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/preprocess/runtime.py:10) · `reviewed_pipeline_executor`

## 边界与安全 Dry-run · boundary

- [src/tscompbench/validation/boundary.py:307](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/boundary.py:307) · `run_boundary_suite`

## 最小完整 Roundtrip · minimal

- [src/tscompbench/execution/preflight.py:100](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100) · `preflight_task`
- [src/tscompbench/execution/recovery.py:206](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:206) · `decode_in_fresh_worker`

## Preflight · preflight

- [src/tscompbench/execution/preflight.py:100](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100) · `preflight_task`

## V3.2 原对象资格 · object_qualification

- [src/tscompbench/comparison/runner.py:940](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:940) · `qualify_comparison`
- [src/tscompbench/execution/preflight.py:100](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100) · `preflight_task`
- [src/tscompbench/comparison/pipeline_runner.py:472](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:472) · `qualify_pipeline_comparison`
- [src/tscompbench/execution/recovery.py:206](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:206) · `decode_in_fresh_worker`

## 独立 development pilot · development_pilot

- [src/tscompbench/comparison/runner.py:1177](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1177) · `pilot_comparison`
- [src/tscompbench/measurement/v32_protocol.py:558](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/v32_protocol.py:558) · `run_pilot`
- [src/tscompbench/comparison/pipeline_runner.py:702](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:702) · `pilot_pipeline_comparison`
- [src/tscompbench/comparison/workload_runner.py:452](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:452) · `pilot_workload_comparison`

## Legacy worker 内预热 · warmup

- [src/tscompbench/execution/repetition.py:425](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:425) · `perform_worker_measurement`
- [src/tscompbench/execution/orchestrator.py:115](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:115) · `execute_task`

## 失败状态与原因留证 · diagnostic

- [src/tscompbench/execution/orchestrator.py:115](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:115) · `execute_task`

## Legacy 正式执行 · formal

- [src/tscompbench/execution/orchestrator.py:115](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:115) · `execute_task`
- [src/tscompbench/execution/repetition.py:498](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:498) · `perform_measured_roundtrip`
- [src/tscompbench/execution/isolation.py:151](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/isolation.py:151) · `run_isolated`

## V3.2 comparison 执行 · comparison_execute

- [src/tscompbench/comparison/runner.py:1377](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377) · `execute_comparison`
- [src/tscompbench/execution/cold_driver.py:394](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/cold_driver.py:394) · `measure_cold_object`

## 独立 workload 执行 · workload_execute

- [src/tscompbench/comparison/workload_runner.py:867](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:867) · `execute_workload_comparison`
- [src/tscompbench/execution/workload_driver.py:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/workload_driver.py:1) · `module`

## P2 pipeline 执行 · p2_execute

- [src/tscompbench/comparison/pipeline_runner.py:1163](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1163) · `execute_pipeline_comparison`
- [src/tscompbench/pipelines/runtime.py:231](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:231) · `encode_object`

## 独立 Context 与编码 · compress

- [src/tscompbench/execution/repetition.py:180](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:180) · `_encode`

## 强制 Finalize / Flush · finalize

- [src/tscompbench/execution/repetition.py:180](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:180) · `_encode`

## 完整对象成本计量 · accounting

- [src/tscompbench/accounting/ledger.py:14](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/accounting/ledger.py:14) · `AccountingLedger`
- [src/tscompbench/execution/recovery.py:193](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:193) · `bind_decode_context`

## 独立 Context 解码 · decompress

- [src/tscompbench/execution/repetition.py:248](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:248) · `perform_roundtrip`
- [src/tscompbench/execution/recovery.py:165](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:165) · `restore_decoded_output`

## 公共正确性与 LossMode · correctness

- [src/tscompbench/validation/correctness.py:72](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/correctness.py:72) · `validate_common_correctness`

## Lossless 按位还原 · lossless

- [src/tscompbench/validation/correctness.py:72](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/correctness.py:72) · `validate_common_correctness`

## Lossy 与专用模式验证 · lossy

- [src/tscompbench/validation/correctness.py:72](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/correctness.py:72) · `validate_common_correctness`
- [src/tscompbench/validation/lossy.py:424](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/lossy.py:424) · `validate_error_bound`
- [src/tscompbench/validation/lossy.py:537](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/lossy.py:537) · `profile_unbounded_loss`

## P2 完整对象与恢复 · p2_object

- [src/tscompbench/pipelines/runtime.py:231](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:231) · `encode_object`
- [src/tscompbench/pipelines/runtime.py:1031](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:1031) · `decode_in_fresh_process`
- [src/tscompbench/comparison/pipeline_runner.py:439](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:439) · `_recovery`

## Legacy MeasurementPolicy · policy

- [src/tscompbench/measurement/contracts.py:9](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/contracts.py:9) · `MeasurementPolicy`

## 方向计时与时长控制 · timing

- [src/tscompbench/execution/repetition.py:498](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:498) · `perform_measured_roundtrip`
- [src/tscompbench/measurement/contracts.py:9](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/contracts.py:9) · `MeasurementPolicy`

## V3.2 生命周期与边界 · measurement_boundary

- [src/tscompbench/comparison/runner.py:271](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271) · `prepare_comparison`
- [src/tscompbench/execution/repetition.py:397](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:397) · `perform_declared_worker_measurement`
- [src/tscompbench/execution/cold_driver.py:394](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/cold_driver.py:394) · `measure_cold_object`

## 资源租约与环境门控 · resource_lease

- [src/tscompbench/measurement/resource_lease.py:232](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resource_lease.py:232) · `ResourceLease`
- [src/tscompbench/measurement/thread_monitor.py:31](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/thread_monitor.py:31) · `ParentThreadMonitor`
- [src/tscompbench/comparison/runner.py:1377](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377) · `execute_comparison`

## 同步进程资源观测 · resources

- [src/tscompbench/measurement/resources.py:195](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resources.py:195) · `ResourceSampler`

## Profile 工作负载选择 · workloads

- [src/tscompbench/execution/orchestrator.py:115](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:115) · `execute_task`
- [src/tscompbench/comparison/workload_runner.py:135](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:135) · `prepare_workload_comparison`
- [src/tscompbench/measurement/workloads.py:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/workloads.py:1) · `module`

## Query / Random Access · query

- [src/tscompbench/measurement/workloads.py:58](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/workloads.py:58) · `execute_query_workload`

## Streaming Benchmark · streaming

- [src/tscompbench/measurement/workloads.py:159](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/workloads.py:159) · `execute_streaming_workload`

## Legacy 原始记录与投影 · raw

- [src/tscompbench/storage/runs.py:434](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/runs.py:434) · `append_run_record`
- [src/tscompbench/storage/events.py:15](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/events.py:15) · `append_event`

## V3.2 持久试次与产物 · trial_store

- [src/tscompbench/comparison/runner.py:683](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:683) · `_append_trial`
- [src/tscompbench/comparison/workload_runner.py:867](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:867) · `execute_workload_comparison`
- [src/tscompbench/comparison/pipeline_runner.py:1080](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1080) · `_commit_attempt`

## 中断、预算与恢复审计 · resume_audit

- [src/tscompbench/comparison/runner.py:1377](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377) · `execute_comparison`
- [src/tscompbench/comparison/pipeline_runner.py:875](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:875) · `_attempt_state`
- [src/tscompbench/comparison/pipeline_runner.py:1098](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1098) · `_block_interrupted_attempts`

## 采集器与可用性披露 · availability

- [src/tscompbench/execution/repetition.py:498](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:498) · `perform_measured_roundtrip`
- [src/tscompbench/measurement/resources.py:195](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resources.py:195) · `ResourceSampler`
- [src/tscompbench/measurement/resource_lease.py:232](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resource_lease.py:232) · `ResourceLease`

## Legacy 冻结证据读取 · evidence

- [src/tscompbench/statistics/engine.py:1116](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:1116) · `analyze_run_set`

## 资格过滤与排除原因 · eligibility

- [src/tscompbench/statistics/engine.py:326](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:326) · `_eligibility`

## Legacy 逐数据集统计 · summary

- [src/tscompbench/statistics/engine.py:644](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:644) · `_summaries`
- [src/tscompbench/statistics/core.py:56](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/core.py:56) · `descriptive_statistics`

## Legacy Corpus 与分层比较 · corpus

- [src/tscompbench/statistics/engine.py:787](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:787) · `_corpus_summaries`
- [src/tscompbench/statistics/engine.py:939](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:939) · `_comparability_groups`

## V3.2 只读重核与配对 · paired_analysis

- [src/tscompbench/comparison/analysis.py:539](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539) · `analyze_comparison`
- [src/tscompbench/comparison/analysis.py:482](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:482) · `_effect`
- [src/tscompbench/comparison/pipeline_runner.py:1427](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1427) · `report_pipeline_comparison`

## V3.2 原域质量与全矩阵 · quality_coverage

- [src/tscompbench/comparison/analysis_extensions.py:484](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis_extensions.py:484) · `augment_analysis`
- [src/tscompbench/comparison/analysis.py:539](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539) · `analyze_comparison`

## Legacy Pareto 与排名 · pareto

- [src/tscompbench/statistics/engine.py:1017](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:1017) · `_pareto_rows`
- [src/tscompbench/statistics/engine.py:1075](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:1075) · `_ranking_rows`
- [src/tscompbench/statistics/core.py:91](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/core.py:91) · `pareto_front`
- [src/tscompbench/statistics/core.py:132](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/core.py:132) · `rank_values`

## Legacy 冻结全集 Coverage · coverage

- [src/tscompbench/statistics/engine.py:880](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:880) · `_coverage`

## Legacy 报告生成 · report

- [src/tscompbench/reporting/generator.py:685](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/reporting/generator.py:685) · `generate_report`

## V3.2 各路径报告 · v32_reports

- [src/tscompbench/comparison/runner.py:1871](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1871) · `report_comparison`
- [src/tscompbench/comparison/workload_runner.py:1205](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:1205) · `report_workload_comparison`
- [src/tscompbench/comparison/pipeline_runner.py:1427](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1427) · `report_pipeline_comparison`
- [src/tscompbench/comparison/report_renderer.py:325](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/report_renderer.py:325) · `render_comparison_report`
- [tools/audit_v32_completion.py:311](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:311) · `audit`

## 参考成本与辅助审计 · reference_cost

- [tools/audit_v32_uncompressed_reference.py:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_uncompressed_reference.py:1) · `module`
- [tools/audit_v32_buffer_costs.py:631](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_buffer_costs.py:631) · `build_buffer_cost_audit`
- [tools/audit_v32_completion.py:311](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:311) · `audit`

## 独立范围与条款验收 · scope_acceptance

- [tools/audit_v32_uncompressed_reference.py:1](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_uncompressed_reference.py:1) · `module`
- [tools/audit_v32_buffer_costs.py:631](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_buffer_costs.py:631) · `build_buffer_cost_audit`
- [tools/audit_v32_completion.py:311](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:311) · `audit`

## 关系语义

| 有向关系 | 语义 |
| --- | --- |
| entry → freeze | CLI run 子命令初始化/恢复 Run Set。 |
| freeze → dataset | 冻结环境之后准备数据；先校验可复用记录，否则调用 prepare_dataset。 |
| dataset → source_identity | 来源与派生 |
| dataset → loader | prepare_dataset 先 registry.load(verify_source=True)，随后加载规范化内存。 |
| loader → characterize | 特征分析读取加载完成的内存数据，不依赖新写出的二进制。 |
| characterize → canonical | 分析后才 write_canonical；相关记录来自同一份已加载数据。 |
| source_identity → logical_object | P2 逻辑对象保留冻结内容身份与来源链；不要求先写 Legacy wire。 |
| loader → logical_object | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| canonical → registry | Legacy 数据准备是规划前提；不表示工件调用注册表。 |
| registry → sweep | 按注册 manifest 扫描完整配置空间。 |
| sweep → universe | 配置与 dataset/track 逐一组合；Profile 已冻结。 |
| universe → negotiate | 从 Layer 1 工件生成 track 数据描述，再按配置协商。 |
| negotiate → plans | 四态是替代结果，CompatibilityPlan 含显式适配；PreprocessPlan 独立制定。图中逻辑计划整理不宣称严格函数先后。 |
| plans → resolution | 执行解析接收 CompatibilityPlan，并纳入 preprocess/工件/冻结资源口径。 |
| resolution → keys | 解析路径是层级可比性键的输入。 |
| keys → tasks | create_task 冻结 compatibility、preprocess、execution、comparability；不支持组合保留。 |
| logical_object → experiment_contract | 原对象依赖 |
| experiment_contract → expected_matrix | 事前决策与比较合同 → 完整期待矩阵与成员准入：数据/控制/证据依赖，非逐函数调用序列。 |
| expected_matrix → public_projection | 完整期待矩阵与成员准入 → 公共投影与实际输入：数据/控制/证据依赖，非逐函数调用序列。 |
| public_projection → frozen_schedule | 公共投影与实际输入 → 冻结作业、源码与调度：数据/控制/证据依赖，非逐函数调用序列。 |
| tasks → gates | execute_task 首先执行 preflight；不合格组合返回 DIAGNOSTIC 而非正式 repetition。 |
| frozen_schedule → object_qualification | 冻结作业 |
| gates → track | 任务状态、来源、工件与注册执行器门控后，才路由 Canonical。 |
| track → input | TIMESTAMP / VALUE / SYSTEM 为当前任务所选 Track；路由后输入验证。 |
| input → adapter | 输入验证后实际 apply CompatibilityPlan，并调用 post-adapter validator。 |
| adapter → preprocess | 有声明 stages 时运行已注册的阶段验证，非所有任务必经额外处理。 |
| preprocess → boundary | 可选 stage validation 成功后，隔离 Boundary/Safety suite。 |
| boundary → minimal | Boundary 成功后执行最小完整 roundtrip。 |
| minimal → preflight | 最小 roundtrip 与 Common Correctness 共同产生 PreflightResult。 |
| preflight → warmup | 预检通过后，每个隔离测量 worker 内先预热；预热排除于计时边界，固定门槛不证明统计稳态。 |
| preflight → diagnostic | 失败原因写结构化 DIAGNOSTIC，通过 callback 保留，不静默删除。 |
| object_qualification → development_pilot | 资格通过 |
| development_pilot → comparison_execute | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| development_pilot → workload_execute | 各 workload 使用自己的冻结协议与独立 pilot；通过后开放该路径。 |
| development_pilot → p2_execute | P2 使用自己的 development 输入和 pilot；此处表示共通门禁职责。 |
| warmup → formal | 每个 worker 的 local warmup 完成后进入自身正式计时内循环；不是只在外层预热一次。 |
| formal → compress | 局部展开父节点 formal：每个内循环迭代是独立完整对象，不代表再执行一次 benchmark。 |
| comparison_execute → compress | 完整对象 PIPELINE 路径包含 P1 对象生命周期；CORE 仅测其注册组件边界。 |
| compress → finalize | 独立 session.compress_update 后强制 finalize。 |
| finalize → accounting | 完整 stream 包括 update+finalize 字节，session.accounting 计算完整解码所需成本。 |
| accounting → decompress | 完成编码 ledger 后，独立解码 Context 重建完整 stream。 |
| decompress → correctness | 每次正式 repetition 的结果由 orchestrator 进行 Common Correctness。最终内循环对象提供结果证据；输入/canary/确定性跨内循环累计。 |
| correctness → lossless | LOSSLESS 值数据 dtype 一致并按 C-order 字节还原。 |
| correctness → lossy | Error-bounded 检查界与质量；Unbounded 只有质量。Rate / Summary 需专用 task validator，否则 UNSUPPORTED；当前无活动算法或正式比较组，框架 validator 资格不等于算法资格。 |
| p2_execute → p2_object | P2 是独立完整对象 runtime，不共用 Legacy wire。 |
| formal → policy | 测量层表示同一正式试次的职责投影，非再执行一轮。 |
| comparison_execute → measurement_boundary | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| workload_execute → trial_store | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| p2_object → trial_store | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| diagnostic → raw | 不支持、预检、warmup 失败等诊断也进入权威证据。正式失败保留原 FORMAL_REPETITION 状态，不统改为 DIAGNOSTIC。 |
| policy → timing | 正式 repetition 使用冻结 policy 控制范围与最短时长。 |
| policy → resources | ResourceSampler 与正式 repetition 共用起止边界。 |
| measurement_boundary → resource_lease | 同一试次 |
| timing → workloads | 正式编解码结果之后，条件工作负载分别在隔离 worker 执行；连线不是并发声明。 |
| workloads → query | Profile 请求且 manifest.query 或 random_access 才执行；否则记录明确不可用状态。 |
| workloads → streaming | Profile 请求且 manifest.streaming 才执行；与 Query 按代码顺序分别隔离。 |
| resources → raw | 同次 resource observation 写入结构化 record，不是第二次资源压测。 |
| query → raw | Legacy 请求且支持的 Query 辅助结果写入其 run record；V3.2 workload 有独立 trials。 |
| streaming → raw | Legacy Streaming 辅助结果归自身 raw；V3.2 workload 独立留证。 |
| resource_lease → trial_store | 观测与状态 |
| trial_store → resume_audit | 恢复重核 |
| availability → trial_store | 处理、数据或证据依赖；不宣称是直接函数调用。 |
| raw → evidence | 统计读取 run_components.jsonl 与冻结 task/provenance，runs.csv 不是权威统计输入。 |
| trial_store → paired_analysis | 只读证据 |
| evidence → eligibility | 完整冻结证据核对后先做资格过滤。 |
| eligibility → summary | 仅合格 repetition 进入逐数据集统计，PASS 本身不足。 |
| summary → corpus | 先逐数据集统计，再基于 summaries 作 corpus 汇总；图中同框呈现分层比较职责，其 group universe 同时来自 tasks。 |
| evidence → coverage | Coverage 从完整冻结 tasks 和 raw 求得，不从通过资格的 summaries 推算。 |
| summary → pareto | Pareto 与单指标排名从合格 summaries 生成，组内比较。 |
| corpus → report | AnalysisBundle 的对应输出交给报告生成器，只读分析，不重新调用 codec。 |
| pareto → report | AnalysisBundle 的对应输出交给报告生成器，只读分析，不重新调用 codec。 |
| coverage → report | AnalysisBundle 的对应输出交给报告生成器，只读分析，不重新调用 codec。 |
| paired_analysis → quality_coverage | 同一冻结证据的只读描述性质量/Pareto/Coverage 扩展，不改变配对分析估计量。 |
| quality_coverage → v32_reports | 原域质量、Pareto 与 Coverage → V3.2 报告与结论边界：数据/控制/证据依赖，非逐函数调用序列。 |
| v32_reports → scope_acceptance | 独立验收 |
| reference_cost → scope_acceptance | 处理、数据或证据依赖；不宣称是直接函数调用。 |
