# 当前架构与旧五层图复核（2026-10-12）

结论：旧 HTML 与 SVG 的五层职责划分、Canonical 数据准备、能力协商、完整对象编解码及公共正确性、同次测量、失败留证和 Coverage 原则仍然成立。但它们主要反映 legacy TOML 的 `runner.py → statistics/engine.py` 路径，不能作为当前 V3.2 全项目流程图。应保留其历史用途，并以本目录新图描述当前主流程。

新图：[交互 HTML](framework.html) · [浅色 SVG](framework.light.svg) · [浅色 PNG](framework.light.png)。源码依据见 [source-evidence.md](source-evidence.md)，逐文件 SHA-256、节点映射和旧证据漂移见 [source-evidence.json](source-evidence.json)。图的箭头表示数据、控制和证据依赖；资格与 pilot 的通过路径不表示所有当前实验已通过。

## 当前数据流程

1. **原对象与数据**：验证源 Manifest、内容及声明语义；加载 T/V/validity，保存 dtype、shape、轴、单位、顺序和派生 lineage。`prepare_dataset()` 产出 canonical、特征、Manifest 快照与准备记录。P2 使用独立 `LogicalObjectSchema`、原对象快照和公开配方；图中“规范化逻辑原对象”包括两者，不要求 P2 强制经过 legacy canonical 二进制。
2. **事前合同与计划**：冻结 `experiment_decision.json`；普通比较加载 Task/Contract/Group/Corpus/MethodConfigMap/ExpectedOutcomeMatrix/ExecutionJob 等规范，以及 Protocol、AnalysisPolicy。编译全矩阵，核验活动成员、合法配置、来源独立性与方法等价类；协商实际路径并形成公共投影，冻结源码、build/runtime、资源、环境和随机化 Schedule。P2 有自己的 plan/recipe 编译入口。
3. **资格与 pilot**：源/工件和输入门控、Preflight、安全边界、原域正确性、完整账本、独立公共 decoder 恢复；资格数据与正式评价对象分别绑定。独立 development pilot 核对真实方向时钟、粒度及 collector 开关扰动。未通过不得取得 FORMAL 资格。
4. **执行与证据**：队列逐 lane 串行，lane 内按冻结调度启动隔离 worker。资源租约、CPU/线程、父进程线程观测、环境和预算门禁约束实际测量。每个对象独立上下文，真实 update → Finalize → 完整产物 → decode → 输出物化及验证；计时和资源来自同次执行。逐次保存 Trials、Events、恢复字节及身份。失败、不支持、STOPPED、资源压力和未知中断保留，不自动换成新成功样本。
5. **分析与验收**：从冻结计划和原始证据重核资格与实际成本，按真正共享的调度 block/pair 做比较，使用事前 AnalysisPolicy 和固定分母；生成质量、Pareto、Coverage、缺口与范围结论。完整性不足或精度目标未达成保留 INCONCLUSIVE。成本审计、未压缩参考、completion 与 requirement acceptance 分别验收，不替代性能观察、源码 parity 或完整能力资格。

## 执行入口与边界

| 路径 | 当前入口 | 对象、计时与恢复边界 | 主要持久产物 |
|---|---|---|---|
| Legacy | CLI `run`；`runner.py` | 原 TOML task/measurement/statistics 合同；保留原三级可比性键 | `task_plan.jsonl`、`run_components.jsonl`、`runs.csv`、`events.jsonl`、CSV/报告 |
| V3.2 comparison | CLI `comparison`；`comparison/runner.py` | 普通完整对象要求 steady/cold PIPELINE；共同 native API 要求 STEADY_PROCESS CORE，实际输入 schema 与字节相同 | `bundle.json`、`experiment_decision.json`、`execution_plan.json`、`schedule.json`、`qualification.json`、`pilot.json`、`comparison_trials.jsonl`、`analysis.json`、`report.html` |
| V3.2 workload | `tools/run_v32_existing_workload.py`；`comparison/workload_runner.py` | 独立 query/stream 协议；warm/fresh 状态、工作负载资格及测量分别冻结 | comparison 冻结工件、workload protocol/plan、pilot、`workload_trials.jsonl`、事件与专用分析报告 |
| V3.2 P2 | `tools/run_v32_pipeline_comparison.py`；`comparison/pipeline_runner.py` | 完整 T/V/mask、混合 dtype/ND/time axis；列/块子 codec、RAW_TAIL；STEADY_PROCESS PIPELINE，额外干净 spawn decoder 恢复 | `plan.json`、决策、资格 intent/result、pilot、`pipeline_events.jsonl`、`trials.jsonl`、`artifacts/*.p2`、`report.json/md` |

P2 当前正式配方使用现有 LZ4/Zstd 子 codec，不新增算法入口。async/ragged 集合采用独立对象/schema/wrapper 与有限资格案例，不能从普通 VALUE/SYSTEM 枚举推断全部算法都原生支持。

## 旧图逐层是否准确

| 旧图区域 | 判断 | 当前应如何解释或更新 |
|---|---|---|
| Layer 1：注册、加载、特征、Canonical | **基本准确，范围不足** | 增补 canonical source 导入、内容/语义双身份、显式派生链；补充 P2 原对象合同与 async/ragged 集合，不能把一种 wire 当作所有对象唯一入口。 |
| Layer 2：参数扫描、能力协商、路径与三级键、BenchmarkTask | **legacy 准确，当前主控制面缺失** | 增加事前决策、全矩阵比较合同、MethodID/ImplementationID 去重、独立真实来源、公开投影、期望矩阵、源码闭包、Protocol/AnalysisPolicy 和 Schedule。旧比较键本身不能授予新组资格。 |
| Layer 3：Preflight、Warmup、完整 roundtrip、错误诊断 | **主体准确，恢复能力不足** | “独立 Context”应扩展为仅凭付费公共恢复信息与保存字节的干净进程恢复。增加 P2 ordered object/column/block/tail、child 依赖与原域恢复；边界不能由能力声明代替实际资格。 |
| Layer 3：正式重复与逐次验证 | **需澄清粒度** | 每个内循环对象独立 Finalize；`perform_measured_roundtrip()` 明确由最后一次内循环提供 correctness/accounting 证据，并检查确定性流。图中文字不能解释为每个内循环对象都执行全部原域 validator。 |
| Layer 4：同次计时与资源 | **原则准确，门禁与 profile 不足** | 增加独立开发 pilot、方向粒度/扰动、ResourceLease、父进程线程观测、冷/稳态生命周期；当前 V3.2 普通完整对象与 native API 分别锁定 PIPELINE/CORE，不能读成三种 timing scope 在每个 lane 任意互换。 |
| Layer 4：Query/Streaming 条件分支 | **legacy 表述可用，当前单独执行** | 当前具有独立 workload runner 和协议，不只是普通压缩测量之后附加两个选项。已声明范围是 known-length fixed-block、Finalize 后完整消费；checkpoint 字段存在不代表全部方法已有 checkpoint 实测资格。 |
| Layer 4：raw/CSV | **只覆盖 legacy** | 增加 comparison/workload/P2 的 Trials、事件、产物和恢复协议。未知 STARTED 不自动重试；P2 另外有持久预算预留、事件链、TERMINAL_COMMITTED、exclusive artifact 与锁。 |
| Layer 5：median/quantiles/bootstrap、corpus、排名 | **legacy 准确，当前正式推断口径不同** | V3.2 主估计量是固定 corpus 上每对象平均进程时间的配对比值；bootstrap 单位为 Schedule block，使用多重比较区间、事前实际效应/精度门槛。质量/Pareto 在公共投影与冻结范围内，不产生全来源全算法的泛化总榜。 |
| LossMode：无损、有界、无界、Rate、Summary | **框架 validator 分类准确** | Rate/summary 当前只有框架专属 validator 资格，没有活动算法或正式组；不能将框内枚举读作已部署和已实测的全部能力。 |
| 最终报告与 Coverage | **保留原则，补充验收** | 保留没有 PASS 的任务及完整分母；增补独立未压缩 SIZE_BASELINE、buffer cost、completion 和逐条 requirement acceptance；辅助审计与 FORMAL 资格分别报告。 |

## 证据与视觉状态

旧图证据记录共 72 个文件，当前 **31 项 SHA-256 已改变，另有 1 项文件已不存在**。这是证据绑定过期的直接证明，但不意味着 32 个文件对应的图义全部错误。新证据按当前工作树捕获，包含已有未提交的 `comparison/analysis.py` 修改；本任务不改变 Benchmark 源码或旧图。

旧目录 [README](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/archify-five-layer-reference/README.md) 已明确记录：原参考展示在 Layer 4 有三处边标签底框遮线/相交，视觉审查为 failed。应将“语义仍大体成立”和“旧图已通过视觉验收”分开判断。

架构图显示已实现的控制流，运行完成情况见 [当前闭包与 FORMAL 审计](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_closure_formal_verification/README.md)：新冻结队列 16 个 lane 均尝试；entropy 完成核心单元，stream/query-warm/query-fresh 完成各自 profile；P2 pilot 不合格，其余 comparison lanes 保留缺口。历史签发和 33/33 有限源码闭包不能直接赋予当前全体正式性能资格。

新图交付、浏览器和导出回执见本目录 JSON。几何校验、实际浏览器行为与人工图像检查分别记录，不能互相替代。本任务未运行算法或新增正式测量。
