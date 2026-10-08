# 提示词的源码核对依据

核对日期：2026-10-08。位置和哈希针对当前工作区字节，包含既有未提交变更，不声称绑定 HEAD。行号供导航，SHA-256 供识别后续源码变化。

| 核对内容 | 源码与符号 | SHA-256 |
| --- | --- | --- |
| 入口与冻结 | [src/tscompbench/runner.py:186](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:186) · `initialize_run_set` | `1cddafd48ad12cb34b1defd32f6f63d40c435dbf83150d7d1dc7ddd7d6ba5384` |
| 数据准备 | [src/tscompbench/datasets/prepare.py:108](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/datasets/prepare.py:108) · `prepare_dataset` | `a9cd61a9c74356149d36d1bc44fa102bad7441e2d89663c170a741af2e7ec2d5` |
| 任务规划 | [src/tscompbench/runner.py:342](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/runner.py:342) · `plan_run_set` | `1cddafd48ad12cb34b1defd32f6f63d40c435dbf83150d7d1dc7ddd7d6ba5384` |
| 参数展开 | [src/tscompbench/planning/sweep.py:82](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/sweep.py:82) · `expand_sweep` | `bff6866be4c2dd7931d77b9ca8a56779e6dcb2f733540d11bab3ee43b36fce97` |
| 四态协商 | [src/tscompbench/codecs/negotiation.py:242](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/codecs/negotiation.py:242) · `negotiate` | `294d57f737a54f1029de0640222e1b7616b3667924f5b0d708285202b48bfb84` |
| 执行路径 | [src/tscompbench/planning/resolution.py:32](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/resolution.py:32) · `resolve_execution` | `d31405f56bbd9274a930dc94cec684a6124b5b8f88a39cf5fdd077d69cd5909a` |
| 层级可比性键 | [src/tscompbench/planning/resolution.py:186](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/resolution.py:186) · `build_comparability_keys` | `d31405f56bbd9274a930dc94cec684a6124b5b8f88a39cf5fdd077d69cd5909a` |
| 冻结任务 | [src/tscompbench/planning/tasks.py:16](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/planning/tasks.py:16) · `create_task` | `f2754922e6a1db88f7747a02438db289011b1f9643f34bce9a3b8237075f2b31` |
| Track 路由 | [src/tscompbench/execution/routing.py:51](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/routing.py:51) · `route_canonical_artifact` | `13f9ffad2f4618cefeb3ccb9cca8252de731e552563db3c59a9105ad557fb71e` |
| 实际适配与验证 | [src/tscompbench/execution/preparation.py:23](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preparation.py:23) · `prepare_execution_input` | `9a761afb833b565138475fba34092032cb2872754b8a820c4fae711948595fb5` |
| 预检门控 | [src/tscompbench/execution/preflight.py:93](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/preflight.py:93) · `preflight_task` | `3c900fe56456b5cca518252e4a4279f44e068324421d1b5bac3bbfe0b31e0f58` |
| 共享验证与测量生命周期 | [src/tscompbench/execution/orchestrator.py:86](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/orchestrator.py:86) · `execute_task` | `57f34360126f452510fb08de6d43c413718845552f2bff984c71a15d3be1c03a` |
| 强制 Finalize 与计量 | [src/tscompbench/execution/repetition.py:166](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:166) · `_encode` | `9a9b4733255b6804df10b31c5b5358434b69de272c203e0a3b16932e33d75e54` |
| 正式重复与时长控制 | [src/tscompbench/execution/repetition.py:382](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/execution/repetition.py:382) · `perform_measured_roundtrip` | `9a9b4733255b6804df10b31c5b5358434b69de272c203e0a3b16932e33d75e54` |
| 正确性与 LossMode | [src/tscompbench/validation/correctness.py:51](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/validation/correctness.py:51) · `validate_common_correctness` | `05413254ac81af186db0535ec3448f187064ab6e098b9ed5d1e583000b17f7d9` |
| 资源采样与采集可用性 | [src/tscompbench/measurement/resources.py:195](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/measurement/resources.py:195) · `ResourceSampler` | `c7ed11df070e5e291d8c8e71430c421ce3b45a098a64e12036d505310c07becf` |
| 结构化证据与 CSV 投影 | [src/tscompbench/storage/runs.py:434](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/storage/runs.py:434) · `append_run_record` | `9061c6416d603264dbfca08df57af83a850ffb2d3162afed29b8dd5c8429ff6b` |
| 资格检查 | [src/tscompbench/statistics/engine.py:326](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:326) · `_eligibility` | `dddf61282f0f3c17c579b4afca0773d9b0a228f75c9014c59ce3016cec8b80b7` |
| 统计完整分组 | [src/tscompbench/statistics/engine.py:644](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:644) · `_summaries` | `dddf61282f0f3c17c579b4afca0773d9b0a228f75c9014c59ce3016cec8b80b7` |
| corpus 汇总 | [src/tscompbench/statistics/engine.py:787](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:787) · `_corpus_summaries` | `dddf61282f0f3c17c579b4afca0773d9b0a228f75c9014c59ce3016cec8b80b7` |
| 冻结任务覆盖率 | [src/tscompbench/statistics/engine.py:880](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:880) · `_coverage` | `dddf61282f0f3c17c579b4afca0773d9b0a228f75c9014c59ce3016cec8b80b7` |
| 先过滤、后统计 | [src/tscompbench/statistics/engine.py:1116](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/statistics/engine.py:1116) · `analyze_run_set` | `dddf61282f0f3c17c579b4afca0773d9b0a228f75c9014c59ce3016cec8b80b7` |
| 派生报告输出 | [src/tscompbench/reporting/generator.py:685](/home/fzg/PycharmProjects/TSDataCompressBenchMark/src/tscompbench/reporting/generator.py:685) · `generate_report` | `1b870ac53ad857b9da0247a0862367b6f2f2d432d677418f62d6e41636347656` |

## 相对参考图的内容修正

- Layer 2 创建适配与预处理计划；实际执行和验证属于 Layer 3。
- Layer 3/4 共享正式重复生命周期，测量与正确性证据关联同次 RunID。
- 原始记录追加至 run_components.jsonl；runs.csv 是可重建投影。
- 资格过滤先于统计；PASS 本身不足以证明性能统计资格。
- 聚合包含 Dataset、Algorithm、Config、ExecutionPath、Profile 和记录 schema。
- Coverage 使用冻结任务全集；corpus 汇总已实现，但不产生跨不相容组的全局加权总分。
- Query/Streaming 要求请求且能力支持；Energy/counters 未激活时记录真实 availability。

## Archify 核对依据

- [SKILL.md](/home/fzg/.codex/skills/archify/SKILL.md)
- [references/authoring-contract.md](/home/fzg/.codex/skills/archify/references/authoring-contract.md)
- [references/delivery-contract.md](/home/fzg/.codex/skills/archify/references/delivery-contract.md)
- [schemas/common.schema.json](/home/fzg/.codex/skills/archify/schemas/common.schema.json)
- [schemas/architecture.schema.json](/home/fzg/.codex/skills/archify/schemas/architecture.schema.json)
- [schemas/workflow.schema.json](/home/fzg/.codex/skills/archify/schemas/workflow.schema.json)
- [renderers/workflow/README.md](/home/fzg/.codex/skills/archify/renderers/workflow/README.md)
- [renderers/architecture/render-architecture.mjs](/home/fzg/.codex/skills/archify/renderers/architecture/render-architecture.mjs)
- [bin/visual-check.mjs](/home/fzg/.codex/skills/archify/bin/visual-check.mjs)

已实查 schema、渲染实现和参考图片；Archify doctor 通过，findChrome() 返回 null。本次只创建提示词和核对记录，未生成图或运行图的浏览器验收。
