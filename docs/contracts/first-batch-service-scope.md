# 首批服务用例合同：`first_batch_service_v4`

这是 **M0 的计划定义**，目标执行阶段是 M5。它继承 `first_batch_service_v3` 的 12 项、17 个展示组和
22 个原子要求，不改旧计划或原生路线定义；将草案中的用例意图落实为可校验的输入、域、恢复任务、
预期终态、资源预算、计时范围和费用项。`runnable: false`：缺实际合格的配方、方法配置、build、
有效域验证器和执行证据时，不能提交为功能验收，更不能授予性能准入。

## 三个分母独立保留

| 分母 | 本版定义 | 判定规则 |
|---|---:|---|
| 展示格 | 12 × 17 = **204** | 引用组内所有原子关系，不隐藏负向结果或未完成项 |
| 原子关系 | 12 × 22 = **264** | 引用该算法对这项服务的全部用例，不作为单个运行样本 |
| 场景义务 | 12 × 47 = **564** | 432 项要求成功并通过指定 oracle；132 项要求在指定合同下拒绝，且不得发布错误产品 |

一个场景可以引用多个输入：普通场景要求全部指定输入；训练场景的三个输入依次是 train、development、
test，各有独立分区身份，训练期不应挂载留出窗口。按 selection 复制场景义务不是增加数据来源或统计样本，
负向场景也不是成功压缩。原生矩阵仍展示冻结入口及其条件，独立于有效服务矩阵。本版禁止 raw 保底顶替
所选算法；`N/A/C` 表示**允许的**实现来源，不是已获资格。外部缓冲流不算原生在线流，解码后查询和切片
不算压缩域查询或索引访问。CORAD 冻结原生部署的留出质量政策和 ALP AVX512BW 条件路线均不变。

## 输入与合同

- `suite.json` 锁定历史草案的来源、范围、语料、fixture 和 schema 摘要，并锁定 `workloads.json`。
  `workloads.json` 绑定 20 个命名输入、47 个场景和 22 条服务合同。改变语义、数据窗口或预算应升 suite 版本。
- 语料窗口来自已经纳入仓库的 v3 数据。真实 traffic 的 CSV/NPY/TXT 在规划时逐列与同一冻结留出窗口核对；
  三种文件格式的字节身份不同，但 canonical 目标和来源簇相同，不计作独立来源。整数范围、特殊位、mask、
  时间轴和空间维度另用已锁定的边界资产；elapsed time 和年坐标不强制改成 UTC 时间戳。
- 角色用例显式区分 `values_only`、`timestamps_only`、`shared_t_controlled`、`whole_object`，并声明
  固定 T、固定 V 对照。固定支路的具体 build、有效选项、格式和分块策略仍需要方法绑定，不从配置标签猜测。
- 端到端、访问、流式等测量范围独立。按服务列出必须入账的部分，例如首包等待、背压、尾块、目录、
  修正旁流、已尝试但拒绝的编码、模型加载、写入和重新打开。计划中的 CPU、内存、deadline、产品和暂存限制
  是验收约束；本规划器不执行它们。估算是配置上界，不是 RSS、磁盘占用或性能实测；解码闭包和主账本字节仍待绑定。
- 调高 M0 验证调度槽数（1 至 4）生成不同计划 ID，不改变 564 个义务身份。这个参数不允许正式性能候选并行。

## 生成、复核与负测

```sh
./bmk plan --config configs/suites/first_batch_service_v4/request.toml --out results/m0-service-plan.json
./bmk service-plan-verify --plan results/m0-service-plan.json
bash tools/probe_offline_service_scope.sh "$CONDA_PREFIX" <空结果目录>
```

Python 调用 `tsbench.api.plan` 和 `verify_service_plan`。复核从同版本配置重建完整计划并比较规范化内容，
不只检查计划自身的哈希；重新计算哈希后删除必需项、伪改资格仍被拒绝。另验证非法覆盖、未知参数、
越界访问、分区串用、错误的流缓存和不收紧的渐进质量级。旧 `v3` 仍可原样复算。

[路径迁移禁网审计](../../results/m0-service-scope-20261119-r2/verification.json)只挂载本工程所需源码和受控
输入、Conda `tsbench`，不挂载邻接 Unique、以前的构建或运行产物。CLI 与 Python API 输出一致，
[五项合同测试](../../results/m0-service-scope-20261119-r2/tests.log)通过。此次验证只证明计划生成与拒绝规则；
**564 项仍是 `not_run`，既不是 M0 通过，也不是任何算法的 M5 资格。**

后续已接入 [T/V 配方开发执行](recipe-tv.md)，但它的 source/setup 位于 worker 时钟外，
只设置进程超时和 frame 限额。不能与本 suite 的 ingress 计费和资源合同混标，现有 `v4` 计划不改。

[服务配方解析计划](service-recipe-resolution.md) 另行绑定匹配的开发构建与同源候选，逐槽给出具体差异，
保留本版 plan 身份及全部分母，不把开发候选变成正式执行。
