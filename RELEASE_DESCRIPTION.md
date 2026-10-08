# TSDataCompressBenchMark 当前状态说明

**状态日期：2026-10-08（Asia/Shanghai）**  
**状态：Unreleased / 当前工作区快照**  
**Python 包版本：0.1.0；配置与运行契约：V2**

本文可用于项目介绍、阶段汇报或后续 Release 描述。它记录当前工作区与已有验证证据，不宣称已创建 Git tag、已对外发布，或已完成全量算法验收。使用与复现入口见 [README](README.md)。

## 项目现在能做什么

项目已经实现一个从数据到报告的五层压缩 Benchmark 闭环：输入数据先经过注册校验、Canonical 加载与特征分析；框架再按算法、数据集、Track 和配置生成任务，协商能力并冻结真实执行身份。通过 Preflight 的任务执行预热和正式重复，在同一次编解码中记录完整压缩成本、计时与资源，并逐次验证正确性。最终报告读取原始证据，先筛选资格，再统计和按可比性键分析。

实现重点是使“压缩了什么、用哪份源码、以什么配置执行、花了多少真实成本、哪些结果可比较”都能从报告追溯到原始记录。失败、能力不匹配、超时、内存错误和资源压力同样保留在任务覆盖率中。

## 当前完成的框架能力

| 能力 | 当前实现 |
| --- | --- |
| 可复现数据准备 | DatasetID、源文件 SHA-256、Canonical 工件、Manifest 快照、exact / sampled 特征分析 |
| 明确能力协商 | DIRECT_SUPPORTED、ADAPTER_LOSSLESS、ADAPTER_LOSSY、UNSUPPORTED 四态与结构化原因 |
| 确定性任务规划 | 参数展开、ConfigID、显式适配/预处理计划、工件/ISA/回退解析、TaskID 与 ExecutionPathHash |
| 安全与正确性门控 | 输入契约、预处理阶段验证、边界/容量/canary、隔离最小往返、逐次正式重复检查 |
| 完整成本计费 | 强制 Finalize、完整对象及必要侧信息记账、独立解码；容量不充当实际压缩长度 |
| 正式测量 | 预热、固定重复、编码/解码各方向最短时长、CORE / PIPELINE / 内存 E2E、辅助 NATIVE / stage 计时 |
| 工作负载与资源 | 进程资源采集；按配置和能力门控的 Query / Random Access / persistent Streaming |
| 证据与恢复 | 追加原始 JSONL、CSV 投影、事件、冻结条件校验、未完成重复恢复 |
| 统计与报告 | 按分析维度资格过滤、稳健统计与 Bootstrap 区间、per-dataset / corpus、Pareto、逐指标排名、Coverage、JSON / Markdown / HTML |

规划与执行有明确边界：第 2 层生成计划，第 3 层实际适配和验证；第 3、4 层共享执行器，正式重复同步测量。统计层从 `run_components.jsonl` 读取完整原始结果，`runs.csv` 是其平面投影。`run report` 是读取已有证据的独立命令。

## 接入规模与完成程度

2026-10-08 核查结果：

| 指标 | 数量 | 解释 |
| --- | ---: | --- |
| Codec Manifest | 67 | 63 个非 oracle 入口 + 4 个框架 oracle |
| Dataset Manifest | 22 | 真实语料与合成接入 fixture 共存 |
| SourceArtifact | 118 | 源工件身份，不能按数量推导已完成算法 |
| Codec Alias | 4 | 共享规范身份，不增加算法排名条目 |
| 全量逻辑条目 | 221 | 原工作目标全部保留 |
| 原生核心候选 | 115 | 接入清单的候选范围 |
| 完整逻辑条目验收 | 0 | 限定数据域、API 或 pipeline 的资格不自动完成整个逻辑条目 |

已注册入口覆盖通用字节压缩、LZSS/LZSSE、浮点无损、时间戳、联合 T/V 对象、整数 primitive/pipeline、熵编码、Sprintz、有损及模型压缩。范围包括 LZ4/Zstd、ALP、Elf/Chimp、Prometheus/InfluxDB、StreamVByte、MaskedVByte、SIMDComp、Simple、LittleIntPacker、zfp/Serf、NeaTS/LeaTS 和独立重写包等。

NeaTS / LeaTS 当前声明查询与随机访问能力；LZ4、Zstd、Brotli、DEFLATE、bzip2、XZ 声明 persistent streaming 能力。这些能力依赖具体清单、协议和配置，不能据此声明所有新工作负载已经正式验收。

`registry/native_integration_plan.json` 的逐条状态是工作清单快照，部分早于后续专项刷新。入口是否取得当前资格，应同时查看接入卡、依赖哈希、固定运行批次和独立审计；不能仅根据一个历史自检段落或注册名称判断。

## 最近的重要进展

### 修正正式测量的方向时长门禁

2026-10-07 修正了编码与解码总时长达标、单个方向却不足的情况。当前 `MeasurementPolicy.duration_satisfied()` 分别检查所选范围的编码和解码时长；E2E 另外检查完整对象时长。第五层直接从原始时间与冻结阈值复核，不仅信任 `min_duration_satisfied=true`。

该变化影响共享执行路径，旧批次不能自动继承当前资格。历史数据保留，需要当前验收的入口使用新批次重新验证。详见[方向门禁自检](docs/minimum_duration_direction_self_check.md)。

### 完成 13 个原生入口的证据刷新与限定范围复验

已有源码依赖变化使部分 SDK/运行证据过期，AdapterFactory 拒绝加载这些旧身份。刷新流程重新执行原生、SDK 和五层验证，再更新注册消费的真实依赖证据；没有放宽哈希门禁或修改原始算法源副本。

最新保存的最终验证报告为 PASS，固定批次记录如下：

| 入口 | 批次记录 | 有效测量 |
| --- | ---: | ---: |
| fast-differential-u32 | 320 | 310 |
| maskedvbyte-u32 | 80 | 79 |
| delta-maskedvbyte-u32 | 320 | 311 |
| simdcomp-u32 | 202 | 165 |
| delta-simdcomp-u32 | 80 | 73 |
| for-simdcomp-u32 | 80 | 77 |
| simple9-u28 | 80 | 73 |
| simple9hacked-u28 | 80 | 74 |
| simple16-u28 | 80 | 77 |
| streamvbyte-u32 | 40 | 38 |
| delta-zigzag-streamvbyte64 | 240 | 231 |
| streamvbyte-modern-u32 | 40 | 39 |
| delta-zigzag-streamvbyte-modern64 | 240 | 228 |
| **合计** | **1882** | **1775** |

1882 条记录包含 1880 次测量尝试和 2 条预期拒绝诊断；另有 105 次 RESOURCE_PRESSURE 测量，全部保留且排除出有效统计。各合法配置固定 20 次重复，编码/解码选定方向各至少 1 秒；每配置至少 10 条有效记录。Simple 首批未达到有效次数门槛的失败批次也保留，后续使用新 RunSetID 重跑整个固定批次。

uint32 / uint28 primitive 和 modular pipeline 的验收主要覆盖登记合成 UTS 及配置矩阵；两个 checked int64 StreamVByte pipeline 覆盖 ETTh1、Exchange Rate、Weather 时间戳。该范围不代表其他语料、float、其他 ISA 或完整逻辑条目均已通过。

这一轮已有报告记录 683 项框架与证据回归测试通过，失败、错误、跳过均为 0；直接 SDK 四组记录为 103、159、888、322 项通过。最终还核查了全部 63 个非 oracle 原生入口及 4 个 oracle 的会话创建/关闭。这是已有验证批次的证据，不是本次文档更新重新跑出的全量结果。

依据：[原生入口证据刷新](docs/native_codec_evidence_refresh.md)。详细最终报告位于本机 `build/rejected-native-requalification-20261007-1/final-verification.json`，通常不随 Git 分发。

## 当前尚未完成的范围

- 全量 221 个逻辑条目的完整验收，以及全部算法在统一真实语料上的最终 Benchmark 结果。
- 超出已签署范围的数据域、API 变体、ISA、pipeline 和配置验证；注册、构建成功和会话创建通过都不能代替这项工作。
- 通用 T Codec × V Codec 自动装配的 SYSTEM 执行器。当前 SYSTEM 路由共同 T/V/Validity，具体封装由适配器实现。
- 设备级、进程树、perf 和 Energy 的有效采集器；当前内置采集主要为进程级，未采集值为 null 并附原因。
- 完整的通用码率目标验收；RATE_CONTROLLED_LOSSY 分支记录目标，不能解释为误差界已经通过。
- 当前未纳入能力声明的 GPU、外部训练或增量流式路径。部分神经/音频入口只覆盖冻结模型和限定 CPU profile。

DCT、DWT、PCA 当前继续跳过；TerraCodec 两个阻塞重写包不在已完成接入声明中。原版 modern StreamVByte signed ZigZag 已知 UB、其他源码失败探针和资源压力批次均保留。LeakSanitizer 未执行通过声明，外部 MKL/LibTorch 等二进制也不属于全部重新插桩的 sanitizer 覆盖。

合成 fixture 证明接入与合同闭环，不能建立真实语料上的通用性能或质量结论。框架不输出跨 Track、LossMode、对象层级或设备的加权总排名。

## 本次文档状态核查

本次重新执行控制面帮助和注册表校验：`--help`、`codecs verify`、`datasets verify` 均通过，分别核对 67 个 Codec / 118 个 SourceArtifact / 4 个别名及 22 个数据集。文档同时对照当前 runner、执行器、测量、存储、统计和报告源码，以及保存的专项审计记录。

本次不重新构建原生库、不重跑上述正式性能批次，也不把历史测试数量描述为当前完整回归结果。后续执行源码或工件变化仍应触发相应证据刷新与重新资格验证。

## 对外讲述参考

> TSDataCompressBenchMark 已经完成五层基准框架的实现，可以把数据注册、算法能力协商、正确性验证、正式测量和统计报告连接成可追溯的实验闭环。目前注册表包含 63 个非 oracle 算法入口和 4 个框架 oracle，但接入资格仍严格区分具体来源、API、数据域和执行配置。最近一轮修正了编码与解码各方向的最短测量时长，并对 13 个原生入口刷新证据、完成限定范围复验，保存 1882 条批次记录，其中 1775 条进入有效统计。项目下一步重点是扩展真实数据域和配置的资格覆盖、完成全量逻辑条目验收，并持续保留失败和不支持的原始证据。
