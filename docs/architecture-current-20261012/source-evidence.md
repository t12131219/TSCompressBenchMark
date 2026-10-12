# 当前数据流程源码证据

基于当前工作树 `6300188e70faf7d93f3a97f87f0d9cebfb7cdf4c`；包含捕获时已有的未提交修改。只做源码核对，未运行 Benchmark。

图中箭头表示数据、控制与证据依赖，不等于逐函数调用。P2 原对象使用独立 LogicalObject 合同与公开配方，不强制经过 legacy canonical wire。

## 来源数据与声明 (source_objects)

- [src/tscompbench/datasets/registry.py:DatasetRegistry](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/registry.py:69)
- [src/tscompbench/datasets/canonical_source.py:register_canonical_source](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical_source.py:185)

## 规范化逻辑原对象 (canonical_objects)

- [src/tscompbench/datasets/prepare.py:prepare_dataset](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/prepare.py:108)
- [src/tscompbench/datasets/canonical.py:write_canonical](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/canonical.py:239)
- [src/tscompbench/pipelines/models.py:LogicalObjectSchema](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/models.py:32)

## Legacy TOML (legacy_lane)

- [src/tscompbench/runner.py:initialize_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:188)
- [src/tscompbench/runner.py:plan_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:344)
- [src/tscompbench/runner.py:execute_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:573)
- [src/tscompbench/runner.py:report_run_set](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:800)

## 事前决策与合同 (experiment_contract)

- [src/tscompbench/comparison/decision.py:freeze_experiment_decision](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/decision.py:276)
- [src/tscompbench/comparison/models.py:ComparisonContract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:143)
- [src/tscompbench/comparison/models.py:ExpectedOutcomeMatrix](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/models.py:347)

## 冻结完整矩阵 (frozen_comparison)

- [src/tscompbench/comparison/planning.py:compile_group_plan](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/planning.py:126)
- [src/tscompbench/comparison/projection.py:public_projection](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/projection.py:30)
- [src/tscompbench/comparison/runner.py:prepare_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:271)
- [src/tscompbench/comparison/pipeline_runner.py:prepare_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:191)
- [src/tscompbench/execution/schedule.py:build_schedule](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/schedule.py:112)

## 原对象资格 (object_qualification)

- [src/tscompbench/comparison/runner.py:qualify_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:940)
- [src/tscompbench/execution/preflight.py:preflight_task](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:100)
- [src/tscompbench/execution/recovery.py:decode_in_fresh_worker](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/recovery.py:206)
- [src/tscompbench/comparison/pipeline_runner.py:qualify_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:472)

## 独立开发 pilot (development_pilot)

- [src/tscompbench/comparison/runner.py:pilot_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1177)
- [src/tscompbench/measurement/v32_protocol.py:run_pilot](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/v32_protocol.py:558)
- [src/tscompbench/comparison/pipeline_runner.py:pilot_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:702)

## 分 lane 隔离实测 (isolated_workers)

- [src/tscompbench/comparison/runner.py:execute_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1377)
- [src/tscompbench/comparison/workload_runner.py:execute_workload_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/workload_runner.py:867)
- [src/tscompbench/comparison/pipeline_runner.py:execute_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1163)
- [src/tscompbench/execution/repetition.py:perform_measured_roundtrip](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:498)
- [src/tscompbench/measurement/resource_lease.py:ResourceLease](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resource_lease.py:232)
- [src/tscompbench/pipelines/runtime.py:encode_object](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/pipelines/runtime.py:231)

## 持久原始证据 (durable_evidence)

- [src/tscompbench/comparison/runner.py:_append_trial](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:683)
- [src/tscompbench/comparison/pipeline_runner.py:_commit_attempt](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1080)
- [src/tscompbench/comparison/pipeline_runner.py:_attempt_state](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:875)
- [src/tscompbench/storage/runs.py:append_run_record](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/runs.py:434)

## 复核与配对分析 (readonly_analysis)

- [src/tscompbench/comparison/analysis.py:analyze_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:539)
- [src/tscompbench/comparison/analysis.py:_effect](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis.py:482)
- [src/tscompbench/comparison/analysis_extensions.py:augment_analysis](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/analysis_extensions.py:484)

## 报告与结论边界 (bounded_reports)

- [src/tscompbench/comparison/runner.py:report_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/runner.py:1871)
- [src/tscompbench/comparison/pipeline_runner.py:report_pipeline_comparison](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/pipeline_runner.py:1427)
- [src/tscompbench/comparison/report_renderer.py:render_comparison_report](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/comparison/report_renderer.py:325)

## 辅助审计与验收 (scope_audits)

- [tools/audit_v32_buffer_costs.py:build_buffer_cost_audit](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_buffer_costs.py:631)
- [tools/audit_v32_uncompressed_reference.py:module](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_uncompressed_reference.py:1)
- [tools/audit_v32_completion.py:audit](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/audit_v32_completion.py:311)

## 旧证据漂移：32 / 72

31 项 SHA-256 改变、1 项文件已不存在，说明旧回执不再绑定当前工作树；不等同于每个变化都导致图义错误。

- src/tscompbench/cli.py
- src/tscompbench/configuration.py
- src/tscompbench/runner.py
- src/tscompbench/datasets/registry.py
- src/tscompbench/datasets/loaders.py
- src/tscompbench/datasets/characterize.py
- src/tscompbench/datasets/canonical.py
- src/tscompbench/adapters/factory.py
- src/tscompbench/codecs/negotiation.py
- src/tscompbench/planning/resolution.py
- src/tscompbench/execution/routing.py
- src/tscompbench/execution/preflight.py
- src/tscompbench/execution/preparation.py
- src/tscompbench/adapters/compatibility.py
- src/tscompbench/preprocess/runtime.py
- src/tscompbench/validation/boundary.py
- src/tscompbench/execution/repetition.py
- src/tscompbench/execution/orchestrator.py
- src/tscompbench/execution/isolation.py
- src/tscompbench/validation/correctness.py
- src/tscompbench/validation/lossy.py
- src/tscompbench/measurement/contracts.py
- src/tscompbench/measurement/resources.py
- src/tscompbench/measurement/workloads.py
- registry/codecs/lz4-frame.json
- registry/codecs/delta-maskedvbyte-u32.json
- registry/sources/lz4-frame-lzbench.artifact.json
- tests/unit/test_negotiation.py
- tests/unit/test_measurement.py
- tests/integration/test_layer2_plan.py
- tests/integration/test_layer3_execution.py
- tests/unit/test_formal_direction_duration_audit.py
