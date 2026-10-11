# CSV 算法范围清理（2026-10-10）

> 本文保存首次 CSV 范围清理的历史状态。后续用户指定退出 27 个入口的决定见[算法退出记录](algorithm_retirement_20261010.md)，当前清单见[活动算法/CSV 对照](registered_algorithms_20261010.md)；本文历史数量与删除声明不能代替当前注册表。

按用户要求，以根目录 `algorithm_implementation_plan.csv` 为当前保留清单。保留全部 163 条记录的三类建议：主集合、扩展，以及组件/配置/来源；同时保留合并来源中的变体。CSV 内容未修改。

活动范围保存在 [algorithm_scope.json](../registry/algorithm_scope.json)，包含清单 SHA-256、记录 ID、合并名称、注册入口和必要参考的明确映射。源码目录名、语言、来源仓库或历史 PASS 不能代替这一映射。163 个选项不等于已经实现了 163 个算法。

## 已删除的实现

| 范围 | 删除项 | 清理内容 |
|---|---|---|
| TSBench 已注册入口 | `bzip2-stream`、`lzsse2-raw`、`lzsse8-raw` | native/vendor、Python adapter、注册/接入卡、专属源身份、构建分支、实验配置、专属测试与审计工具、活动构建产物 |
| Compression_Rewrite | `terracodec-tec-tt`、`terracodec-flextec` | 两项的 Source 和 ReWrite 目录，包括候选源码与模型 |

ALP、Sprintz、NeaTS 曾从 LZSSE 模块借用 C ABI 缓冲区定义。该定义已原样迁移到 `adapters/native_buffers.py`，保留算法改用公共模块，执行工件依赖集合也包含公共模块。

旧逻辑候选表移除 15 条：OMP、Mairal Online Dictionary Learning、alphaCSC、Spline、NMF、RAT-CC、TerraCodec 的三个数值条目、G-ALP GPU direction、Prometheus Triple-delta pattern、Timescale UUIDv7 timestamp-part、ClickHouse GCD 管线，以及 NNLCB 和 TerraCodec 两个基准参考条目。这些条目没有对应的其他已接入实现需要继续删除。

## 当前保留范围

| 对象 | 数量与口径 |
|---|---|
| CSV | 163 条选择记录，包含所有建议类别与合并变体 |
| 根 Codec Manifest | 64：60 个真实入口、4 个框架 oracle |
| 别名 | 4，不重复计作算法 |
| SourceArtifact | 115，属于源码身份，不代表可运行算法数量 |
| 活动逻辑来源/工作清单 | 206：186 个选定算法/组件及合并来源条目，20 个必要参考条目 |
| 原生核心候选 | 112，属于候选范围，不代表已验收 |
| 重写包 | Source/ReWrite 各 16 个包，对应已接入的 18 个入口 |

源目录的 72 仓库库存记录保留历史 provenance，`repository_inventory_role` 明确其不属于活动算法列表。外部 `Compression_Source_Code` 的共享原版资产没有修改。保留算法使用的第三方依赖、框架 oracle，以及 lzbench 等必要来源/比较参考继续保留。

`audit_sources.py` 和 `build_native_integration_plan.py` 输出经过同一范围过滤，保留原审计索引。重新生成不会恢复被排除的候选；本地 CSV 如发生变化，工具要求先更新审阅后的映射快照。

## 证据与恢复

旧 runs、outputs、来源审计和 V2 历史材料保留原始内容。清理改变了 Python 执行闭包，旧批次不能直接证明新身份的资格。本轮对受影响构建和 SDK 执行重新验证后，使用既有独立审计与注册刷新工具更新运行依赖，没有放宽源码/构建门禁，也没有手改旧批次哈希。

验证结果与日志位于 `build/algorithm-scope-cleanup-20261010/`。新 SDK 证据使用 `scope-cleanup-20261010` 后缀；旧正式性能仍绑定原身份，只有另行执行且独立审核的新批次可以证明当前正式资格。

删除前的本地源码、模型、构建产物和旧清单已移出项目，存放在 `/tmp/tsbench-algorithm-scope-cleanup-20261010`。其中 `cleanup_manifest.json` 记录原路径，`pre-refresh/` 保存证据刷新前副本。该目录不属于 Git push 或活动算法范围。

当前已确认的清理验证：64 个入口的注册、完整运行依赖、会话创建/关闭通过；6 组 SDK 共 2,437 项测试无失败、错误或跳过；最终范围/注册/协商合同检查 24 项通过。新 MaskedVByte 与 SIMDComp 的正向和域外拒绝批次均独立审计通过。该验证不等于所有算法在所有数据域或所有旧正式性能批次重新合格。

Simple8b-RLE 新正式批次完成 80 次观测，79 次合格、1 次 RESOURCE_PRESSURE 排除，独立审计通过。LittleIntPacker 的当前 SDK 已通过，但旧正式批次与新执行闭包不匹配，工作清单明确标记需要重新验收。最终机器记录见 `build/algorithm-scope-cleanup-20261010/verification.json`。

针对新状态补测的来源、SDK、拒绝、账本和工作清单测试分别通过 33、5、57 项。首次扩大回归出现的旧计数/过期批次失败已通过更新计数和新批次审计解决；本轮未重跑全部测试集合。
