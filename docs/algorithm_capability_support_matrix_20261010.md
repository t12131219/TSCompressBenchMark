# TSDataCompressBenchMark：算法完整性与性能支持矩阵

日期：2026-10-10。依据：当前《TimeSeries_Compression_Benchmark_V3_工程实施总计划》、Dataset_Verify v1/v3、活动 Codec Manifest，以及本地 lzbench / TerseTS 源码。

本文是能力与验收要求的整理，不是新的运行或性能合格证书。当前33入口见V3.2 §1.5/20；多数CSV候选的长期接入、分类/ID映射与共同比较路线见总计划§1.6/7.11/15.4。下表中的“应支持”与“当前已实现”分别说明。V3.2独立审查后的恢复/成本与测量口径优先：API、schema绑定对象、独立对象和系统分别比较；内部timer可选，旧固定重复门槛只适用LEGACY_V2。

代码实施更新：首批已实现当前 CSV 与旧 scope 的版本映射、现有可逆适配的持久化 DecodeContext 和 spawn 恢复预检、完整输出物化及描述成本、每个测量 worker 内预热。SUMMARY_ONLY / RATE_CONTROLLED 在专属验证器缺失时明确拒绝取得资格，非有限失配不再被有限子集质量分数掩盖。以上未扩展任何 codec 源域、算法范围、流式或设备能力，也不代表共同组已取得 FORMAL；详见[首批实施记录](reviews/v32_first_implementation_batch_20261010.md)。

## 1. “完整”应该怎样定义

**完整 Benchmark 应完整处理预定任务；完整 Codec 应完整实现其声明的算法合同。两者都不意味着每个算法必须原生接受所有数据、拥有所有加速功能。**

一个完整的压缩方案，至少应在合法输入上完成：

```text
声明数据域与参数 → 能力协商 → 显式适配/预处理 → 安全预检
→ 编码 → Finalize → 完整码流及恢复依赖
→ 独立解码 → 逆变换/对象重组 → 原始域正确性
→ 完整空间账本 → 真实执行边界的时间/资源 → 可复现报告
```

域外输入应给出有原因的拒绝。压缩后膨胀应记录真实大小；它本身不代表不支持。构建、模型、ISA 或设备不可用，应与算法数据域不支持分开。

这里有三个不同的完整性问题：

| 对象 | 完整性的要求 |
|---|---|
| 单个 Codec 接入 | 声明真实域；域内能编码、完成输出、解码、验证、计费；域外正确拒绝；路径和依赖可审计 |
| 相对原版的完整重写 | 覆盖冻结 SourceCapabilityMatrix 的必需能力，取得声明范围的 source parity；Benchmark 只开放部分参数，不能反过来证明重写完整 |
| 整个 Benchmark | 能表达不同数据与方法，安排合法任务或正确拒绝，测量实际路径，分开报告正确性、覆盖和正式资格 |

P0 primitive 可以作为组件接入，例如 uint32 位打包。原API/公共协议可用于组件比较；进入完整对象比较时，所需长度、位宽、尾部、类型/形状和恢复依赖须符合所选schema绑定或独立对象合同，并按该场景计费。P1 Codec、P2 管线、P3 存储系统各按自己的边界验收。

建议沿 V3 §8.1 保留四张矩阵：SourceCapabilityMatrix、StandalonePortMatrix、BenchProfileMatrix、PipelineCoverageMatrix。每格记录声明、适用条件、证据、有效版本和状态；用一个总勾选代替四者会掩盖能力来源。

## 2. 数据支持矩阵

下表的“框架要求”是 V3 的目标合同，其中若干通用组合路径仍待实现；“单算法要求”是根据其声明域验收，并不要求所有行都原生支持。

| 数据维度 | 完整 Benchmark 的要求 | 单个算法应该声明/验证什么 | 当前 Dataset_Verify 覆盖 |
|---|---|---|---|
| 有符号整数 | 原样保留 int8/16/32/64 | 字宽、负数、极值、中间残差/差分的 checked 或 modulo 语义 | 四种均有 |
| 无符号整数 | 原样保留 uint8/16/32/64 | 完整位宽或 u28/alphabet 等受限域；不能只看 dtype | 四种均有；另有专用受限域样本 |
| 浮点 | 原样保留 float32/64；无损按 IEEE 位模式验收 | 数值域或位模式域、计算精度、舍入、FMA/FTZ/fast-math 等 | 两种均有 |
| IEEE 特殊值 | 区分 ±0、subnormal、最大有限值、±Inf、NaN payload、quiet/signaling NaN | 支持、明确拒绝，或保留原始位模式的exceptions管线；canonicalization另声明恢复/失真合同 | 8 份 ieee_special；边界集也含有限极值 |
| UTS 单变量 | 逻辑 shape `[N]` | 长度和状态域，不能因错误 singleton axis 误拒绝 | v3 已修为 `[N]` |
| 同步 MTS 多变量 | 保留 `[N,M]`、列顺序、单位和时间配对 | 原生联合、通道分组、独立列，或仅整体字节序列化 | 主矩阵 M=8；另有 M=2/4/16/32 |
| 混合 dtype MTS | 列 buffer＋dtype vector；保留全部列 | 原生异构，或显式逐列方案；每列实际运行、恢复并计费 | 8 份，每份10种类型各一列 |
| 有时间戳 | 通常 int64；保存单位、epoch、来源、输入顺序和 T/V pairing | TIMESTAMP、VALUE、SYSTEM 哪些 Track 可用；时间域和溢出规则 | regular、irregular、duplicates、out_of_order |
| 无时间戳 | 保持无 T；可使用 VALUE | 不把行号/假设采样间隔冒充原始 T | 四类中的两类 |
| validity/null | 保留 ROW/CELL/每通道 ragged mask；NaN 与 null 分开；mask 计费 | 原生支持、显式管线或拒绝 | 全部1,409份为 NONE；语料覆盖待补 |
| ND / 多实体特征 | 保留原 shape、axes、time_axis 与映射 | 原生 ND 或明确的列/轴映射、重组方案 | 1份 `[4,3,4]` f64 oracle；通用域待补 |
| async / ragged | 保留各通道时间轴、长度及 topology | 原生支持或经过证明的显式转换；不暗中同步化 | 当前索引无系统覆盖 |
| 物理布局 | 区分 SOA/AOS、C/F 连续、strided、端序、alignment | 所需 layout、padding、safe-overread；适配与复制成本 | v1主体SOA；系统布局/错位视图矩阵待补 |
| 空/短/尾块 | N=0/1/2、B±1、2B±1、API最大长度等 | 域内精确恢复，域外明确拒绝；不能丢尾或隐式补零 | 固定短长边界＋v3新增N=2；各算法B/W边界仍需生成 |
| 特殊语义对象 | 保留真实字段、单位和恢复目标 | 音频、Histogram、模型alphabet等专用域不能从普通矩阵推断 | 历史专用样本保留；不代表对应算法仍活动 |

类型转换也是能力的一部分，必须单列：同符号整数扩宽通常可精确逆恢复；有限 f32→f64 与特殊 IEEE 位模式要分别验证。i64/u64→f64 不具有全域无损保证。IEEE bitcast、ZigZag、宽整数拆字、量化等必须形成明确管线身份，并重新检查子算法域。

### 2.1 当前穷举集究竟穷举了什么

主矩阵是：

```text
有/无T × UTS/MTS × 10 dtype × 4载荷档位 × 4数值模式
= 2 × 2 × 10 × 4 × 4 = 640
```

档位为4 KiB、64 KiB、1 MiB、16 MiB，目标是完整 T＋V 载荷并按完整行取整；不是容器文件大小，也不等于 VALUE 或 TIMESTAMP 的输入大小。模式为 constant、slow、periodic、random。

| 子集 | 数量 | 覆盖内容 |
|---|---:|---|
| main | 640 | 上述主矩阵 |
| length_extrema | 560 | N=0/1/7/8/9/31/32/33/127/128/129/1023/1024/1025；整数极值及有限IEEE边界 |
| ieee_special | 8 | 四类×两浮点类型 |
| timestamp_cases | 60 | 两带T类别×10类型×irregular/duplicates/out_of_order |
| channel_counts | 80 | 两MTS类别×10类型×M=2/4/16/32 |
| mixed_dtypes | 8 | 两MTS类别×四数值模式 |
| v1合计 | 1,356 | 原文件保留 |
| v3新增N=2 | 40 | 四类×10类型 |
| v3专用源域 | 12 | 受限整数、byte/model、float、真实源及历史专用合同 |
| v3 ND oracle | 1 | native ND正向框架样本 |
| v3登记合计 | 1,409 | v1的版本化视图/登记＋上述新增项 |

聚合v3全部manifest得到：658份UTS、750份同步MTS、1份ND；734份有T、675份无T；全部validity=NONE。

这是一组离散维度覆盖，不能证明所有数值、任意长度、任意block/window、任意layout和状态均已穷尽。合成资格语料、真实代表性性能语料、learned的train/validation/test应分别建设。

## 3. 功能支持与验收矩阵

“基础必需”适用于完整可恢复方案；“声明后必需”表示算法可以没有该能力，但一旦宣称支持，就须满足对应合同；“框架组合”不自动成为子算法原生能力。

| 功能 | 单个算法的要求级别 | 完整 Benchmark 应提供的合同 | 必须观察/验证的内容 |
|---|---|---|---|
| 编码＋解码 | 基础必需 | 完整对象调用，可由one-shot或增量API完成 | 全量恢复；输入不可变；返回长度/错误可解释 |
| 离线 batch / whole-object | 基础执行路径 | 明确一次对象的准备、编码、Finalize、恢复边界 | encode/decode吞吐、总延迟、大小、内存 |
| 参数与域检查 | 基础必需 | dtype＋shape＋roles＋值域＋长度＋依赖＋环境的联合谓词 | 正向、域外拒绝和合法输入误拒绝 |
| bound / 输出容量 | 基础必需的安全合同 | 安全的bound、增长分配或适用API容量策略 | 扩张输入、过小输出、长度转换和溢出 |
| Finalize / Flush / EOF | 基础必需，按API实现 | 完成真正可解码输出；Flush与Finalize分开 | 空输入、尾位、尾块、空final、重复final的声明行为 |
| 生命周期 / reset / state | 基础必需的声明 | 独立对象、复用context、连续状态分开 | 状态隔离、资源释放、失败清理；不能默认复用 |
| 独立恢复 / cold decode | 完整方案必需 | 解码读取恢复描述；独立进程只获码流及声明依赖 | 不借原数组dtype/shape；字典/模型缺失明确失败 |
| chunk / block / window | 声明后必需；可框架组合 | 独立块或连续状态，记录B/W、初态、长度、tail | N<B、B±1、2B±1；所有块/尾部和header计费 |
| online stream | 声明后必需 | start/update/finish、lookahead、state/buffer上限、输出与背压合同 | 首输出、块p50/p95/p99、Finalize、连续流恢复 |
| 多序列/多请求batch | 可选，与单对象batch分开 | batch size、聚合方式和等待策略 | 吞吐、每请求延迟、batch等待、峰值内存 |
| SIMD | 声明后必需 | ISA选择/探测、build/runtime dispatch、实际路径 | 请求/实际ISA、对齐、padding、安全尾部、恢复一致性 |
| 算法内部多线程 | 声明后必需 | 编码/解码分别声明并按适用API控制线程与预算；固定后台池如实计入 | 可配置接口的加速比/效率、所有后台池、峰值内存、超配 |
| 框架块/列并行 | 框架组合扩展 | 独立任务分配worker；保存重组顺序与状态隔离 | worker/context数量、排队/重组成本、总资源与大小变化 |
| 多变量联合 | 声明后必需 | COLUMN_INDEPENDENT / GROUPED_CHANNELS / FULL_MATRIX等区分 | 真正的coupling、列顺序、各列成本；不以一列乘M |
| TIMESTAMP / VALUE / SYSTEM | 声明后必需 | T-only、V-only、完整T＋V＋validity各有分母/SegmentPlan | T/V配对、元信息、共享码流成本；SYSTEM不等于P3 |
| 有损 / 率控制 | 声明后必需 | 原始域loss budget、网格/重建合同；目标率与实际率分开 | MaxAE/RMSE等、逐点/逐列界、全部转换误差 |
| 字典 / learned模型 | 声明后必需 | 初始与更新状态、依赖hash、训练/加载/fit边界 | alphabet、分布偏移、seed、模型/字典完整计费 |
| point/range/projection查询 | 可选；声明后必需 | seeded真实压缩域workload；定义cache策略 | 结果正确性、延迟、bytes touched、decode/read amplification |
| GPU / FPGA / QAT | 可选；声明后必需 | kernel、传输、同步、设备内存与fallback分开 | H2D/D2H/sync、batch/padding、实际设备、设备总成本 |
| P3存储系统 | 专属扩展 | 实际写入/读取/持久化/查询生命周期 | 文件/索引/元数据/WAL等实际适用组件与用户E2E |
| 路径、计费与复现报告 | 基础必需 | 源/实现/参数/数据/模型/二进制/环境身份，完整观测 | 实际method/fallback、FinalBits、资格状态和可重建报告 |

### 3.1 四组容易混淆的概念

1. **Batch、chunk、stream**：batch是离线处理完整对象；chunk是处理单位及分割合同；stream是状态和增量输出合同。流可以按chunk输入，离线算法也可以分chunk，但分chunk调用one-shot API本身不能证明online stream。
2. **单线程与SIMD**：SIMD是一个线程内的向量执行；多线程是多个执行线程。可以是SIMD＋单线程，也可以是scalar＋多线程。SIMD-only源实现可以拒绝没有所需ISA的机器，不必虚构scalar fallback。
3. **三种并行**：codec内部线程、框架并行块/列、同时运行多项实验是三种不同变量。资格验证多进程加速不能转为正式单算法多线程性能。
4. **三种MTS支持**：逐列编码能恢复MTS；联合模型利用跨通道关系；字节codec序列化完整矩阵能恢复typed对象。三者都可能合法，但不能给它们相同的“原生多变量建模”标签。

块/列并行不一定保持原码流或压缩率。若为并行而改变块长、字典或状态，需报告实际新配置和最终大小；不能把全部收益解释为纯线程加速。

## 4. 应建立哪些性能 Profile

下表是建议的实验分类名称，**不是现有CLI选项**。完整Benchmark应能区分这些问题；V3 CPU主线发布不要求所有扩展同时完成。

| Profile | 共同实验条件 | 主要性能指标 | 进入该比较的必要条件 |
|---|---|---|---|
| 单线程完整对象基线 | 原对象/Track/恢复目标/资源及计时边界相同 | FinalBits、encode/decode semantic MB/s、完整对象延迟、峰值内存 | 全量恢复、账本闭合、FORMAL合格 |
| 原生API / kernel | 实际native输入、workload、dtype/layout/值域、线程及API边界受控 | 各方向native ns与native MB/s | 外部API计时或经审计的内部kernel计时；实际字节、方向与测量协议分别验收 |
| 同方法SIMD变体 | 同方法/参数/恢复合同；披露ISA与布局改变 | 两路径均存在时的scalar/SIMD速度比、适配后总收益、内存 | 实际ISA证据、安全、声明范围恢复/parity |
| 分块/窗口方案 | 同原对象，事前B/W sweep；独立/连续状态明确 | 大小、吞吐、尾部成本、memory-vs-block曲线 | 全块、全部tail与恢复元信息计费 |
| 持续流式 | 明确输入节奏、分段、state、lookahead、输出与背压 | 首输出、steady吞吐、块p50/p95/p99、Finalize、state/buffer峰值 | 真增量协议；持续流式重复与资源合同 |
| 多线程/并行 | 同工作量；分别冻结内部线程或外部worker，固定核心预算 | T1/Tp加速比、效率、总吞吐、大小、峰值内存 | 所有后台线程计入；编码/解码分开；状态与重组合法 |
| 有损/learned | 同原对象、loss/quality或rate目标、模型成本政策 | size-speed-quality、原始域误差、cold/steady、模型bits | 有效误差/质量合同、split、模型/字典依赖 |
| 查询/随机访问 | 相同seed、point/range长度、projection、cache策略 | p50/p95/p99、bytes touched、读/解码放大、index bits | 实际compressed query接口与结果验证 |
| 设备/存储系统 | 相同任务与完整用户边界、设备/存储资源预算 | 设备总成本或文件/进程/系统E2E | 传输/同步/I/O/启动等边界明确；不混入纯CPU内存榜 |

基础空间指标使用原始Track分母：`SizeRatio = FinalBits / RawBits`、`CompressionFactor = RawBits / FinalBits`。分母为0时相应指标为null。FinalBits按总计划§6.6选定场景包含实际payload、header、dtype/shape、块表、tail、validity、字典/模型、index/checkpoint、padding及容器中的适用部分；公共协议与共享依赖按冻结部署边界披露或摊销，每bit只计一次。

基础吞吐同时区分：

```text
Semantic MB/s = ceil(原始Track RawBits/8) × inner_iterations × 1000 / scope_ns
Native MB/s   = 实际native未压缩输入bytes × inner_iterations × 1000 / native_ns
```

解码吞吐通常以恢复的未压缩字节数为分子。适配扩宽不能增加原RawBits。MB=10^6 B；数据档位KiB/MiB使用2的幂。

CORE、PIPELINE、内存E2E与native观测不是同一边界。当前native是辅助观测，不是`timing_scope=NATIVE`。完整E2E应实际测量，不能拼接分别选出的最佳编码和解码时间；逆适配/重组必须作为生成可消费数据的成本计入。

旧v2代码门槛包括warmup次数≥3且累计≥0.5秒、计划及合格repetition各至少10、重复索引完整、编码/解码各达到配置最短时长；它们仅保留为`LEGACY_V2`。V3.2按pilot冻结MeasurementProtocol与AnalysisPolicy，区分worker内预热、内层迭代、外层进程/会话重复、调度及停止规则，并报告适合实际独立单位的效应与不确定性。QUALIFICATION不进入正式排名，FASTEST-only不作为主榜。

## 5. 当前33个活动入口的声明矩阵

以下逐组覆盖全部33个范围内入口，读取的是当前注册合同，**不是全域测试通过矩阵**。当前40个根登记另含3个缺构建的范围外残留及4个oracle；1个别名不增加算法数。

缩写：`U/M/N`=UTS/同步MTS/ND；`独立列`=COLUMN_INDEPENDENT；`整体`=FULL_MATRIX；`T/V`=TIMESTAMP和VALUE；“native有”仅表示声明了native计时能力，不能据此取得正式原生性能资格。

| 活动入口（按本表字段同类分组） | 输入类型 / topology声明 | Track / 对象层 | 耦合 / fidelity | ISA / 线程声明 | 扩展接口声明 | native timer |
|---|---|---|---|---|---|---|
| chimp、chimp128、elf、elf-plus、elf-star、self-star | f32/f64；U/M | V；P1 | 独立列；无损 | SCALAR；1 | 无stream/query/RA | 缺 |
| alp、alp-rd | f32/f64；U/M | V；P1 | 独立列；无损 | SCALAR；1 | 无stream/query/RA | 有 |
| neats-lossless-i64、leats-lossless-i64 | i8/i16/i32/i64；U/M | V；P1 | 独立列；无损 | SCALAR；1 | query＋random_access | 有 |
| serf-qt、serf-xor | f32/f64；U/M | V；P1 | 独立列；有界有损 | SCALAR；1 | 无stream/query/RA | 有 |
| zfp-accuracy-1d | f32/f64；U/M | V；P1 | 独立列；有界有损 | SCALAR；1 | 无stream/query/RA | 有 |
| abba、fabba | f64；U/M | V；P2 | 独立列；无通用逐点界的有损 | SCALAR；1 | 无stream/query/RA | 缺 |
| deepzip | u8；U/M，另受alphabet/model条件限制 | V；P2 | 独立列；无损 | SCALAR；1 | 无stream/query/RA | 缺 |
| dzip | u8；U/M，另受model条件限制 | V；P2 | 独立列；无损 | AVX/依赖dispatch；调用线程＋两个持久单worker Eigen池 | 无stream/query/RA | 缺 |
| sprintz-delta、sprintz-fire | i8/u8/i16/u16；U/M | V；P1 | 整体；无损 | AVX2_BMI2_LZCNT；1 | 无stream/query/RA | 有 |
| sprintz-delta-u8、sprintz-fire-u8 | u8；U | V；P1 | 独立列；无损 | AVX2_BMI2_LZCNT；1 | 无stream/query/RA | 有 |
| sprintz-fire-huff0 | i8/u8/i16/u16；U/M | V；P2组合 | 整体；无损 | AVX2_BMI2_LZCNT；1 | 无stream/query/RA | 有 |
| simdcomp-u32 | u32；U | V；P0 | 独立列；无损primitive | SSE4.1或AVX2；1 | 无stream/query/RA | 有 |
| deflate-zlib、lz4-frame、zstd-frame、brotli-stream、xz-stream | 全10dtype的字节视图；U/M/N | T/V；P1 | 整体字节打包；无损 | SCALAR登记；1 | stream | 有 |
| snappy-raw、lzss-raw、lzss-dipperstein-c | 全10dtype的字节视图；U/M/N | T/V；P1 | 整体字节打包；无损 | SCALAR登记；1 | 无stream/query/RA | 有 |
| fse、huff0 | 全10dtype的字节视图；U/M/N，另受长度/字节域条件限制 | V；P1 | 整体字节打包；无损 | SCALAR登记；1 | 无stream/query/RA | 有 |

使用本表时还须检查完整manifest的长度、总元素/字节数、layout、value_domain、参数和依赖。f32/f64登记不能推出所有IEEE位模式均合法；例如Chimp存在源EOF/NaN域限制。

全部33个活动入口当前validity_shapes仅NONE，无ASYNCHRONOUS_MTS、SYSTEM、P3或GPU登记资格。27个P1、5个P2、1个P0；25个仅VALUE，8个TIMESTAMP＋VALUE；23个声明native timer，10个缺失。

字节codec的FULL_MATRIX不等于统计模型理解跨通道关系。SCALAR登记也不是机器指令审计：依赖自身dispatch、编译器自动向量化与实际ISA要查实际构建/路径，不能只按这个字段做scalar-vs-SIMD结论。

## 6. 当前已有能力与缺口

| 能力 | 当前状态 | 完成V3相应能力还缺什么 |
|---|---|---|
| canonical正式入口 / UTS形状 | 已有正式import/prepare/run/report/resume；v3 UTS `[N]` | 内容语义字段白名单继续版本化治理 |
| 四态协商 / 基础适配 | 已有DIRECT、无损适配、有损适配、UNSUPPORTED；连续化/转置/端序/扩宽/对齐等 | 更通用的子视图/管线规划，状态正交与独立期待矩阵 |
| 整对象流程 / 正式重复 | 已有完整调用、Finalize、新decoder session、正确性、账本、CORE/PIPELINE/内存E2E | 独立进程恢复/逆变换物化仍有缺口；全域/全参数证据不能由少数正向样本替代 |
| 逐列 / 分块 / tail | 部分codec wrapper已实际逐列分块并恢复精确尾长 | 通用COLUMNWISE/ND映射、raw-tail、T＋V P2及统一RecoveryDescriptor |
| 自包含逆恢复 | 有码流描述与原始域逆验证基础 | P2不借原dtype/shape的独立进程cold decode、可消费恢复对象的完整物化 |
| native计时 | 23个活动入口声明有；10个保留重写入口缺 | 逐API边界审计；新正式native profile及各方向时长/字节证据 |
| streaming | 5个活动字节codec有增量协议与附加workload driver | 持续流式主FORMAL重复、总流式时间/资源及统计；更完整在线域合同 |
| query / random access | NeaTS/LeaTS有真实query实现和workload driver | 各查询域、cache策略、大小与资源的正式证据；不扩称其他codec支持 |
| 多线程 / 实验并发 | 有线程/进程预算、隔离与资格多进程调度；DZip有后台池声明 | 通用native线程扫参、块/列并行方案、线程高水位与统一资源租约 |
| ND / validity / async / layout | 类型合同与部分reader/边界基础；byte codec登记ND字节视图 | 系统语料及显式映射/重组路径；原始任意time_axis和异步拓扑 |
| 资源 / 文件/设备E2E | PROCESS collector和内存路径可用 | process-tree/cgroup、硬RSS/完整线程审计、设备/存储/文件E2E等扩展 |

### 6.1 流式现状需要单独说明

`execute_streaming_workload`会执行start、按块push、finalize、解码和正确性，保存首输出、块延迟分位数、Finalize延迟、state/buffer/checkpoint等。5个活动字节codec确有此增量入口。

这里的首输出按首次非空emitted计时，可能只是容器header，不能自动解释为首个有效压缩payload或首个可恢复样本。state/buffer/checkpoint来自session返回的telemetry，不是全过程峰值内存；报告应区分首字节、首payload与首可消费样本，以及状态计数与实测RSS。

但它在主roundtrip之后作为附加worker运行；主记录的编码/解码吞吐与ResourceSampler来自整对象观测。普通warmup/measured repetition仍只接受INDEPENDENT_OBJECT。因此不能把当前主吞吐改名为持续流式正式吞吐。

当前共享流式包装还依赖预先声明的对象长度/块大小，最终物化完整恢复输出。未知总长、任意输入分段、严格常量内存、随机checkpoint恢复和更完整背压不能由`features.streaming=true`推断。

### 6.2 不沿用历史数量签署当前能力

V3 §1/§19与Dataset_Verify实施记录的67根入口、18重写入口、213资格用例属于2026-10-09快照。§20后的活动范围是33个真实入口，缺native timer的是10个保留重写入口。

历史`1,409 × 67 × 3 = 283,209`是协商项，每项NOT_RUN，不能解释成283,209次编解码。历史分层执行也是QUALIFICATION；需要按当前身份重新建立能力证据，不把旧PASS自动迁移成当前FORMAL或source parity。

## 7. 建议怎样填写真正的“通过矩阵”

建议每行绑定：

```text
Algorithm/Implementation + Source/Build/Runtime闭包 + Config
+ 原始Dataset/Track + 输入视图/管线 + Workload/状态
+ ISA/线程/设备/资源预算 + Timing/Comparison合同
```

每个能力格至少记录以下相互独立的字段；这些是矩阵设计建议，不是已发布的新Schema：

| 字段 | 示例/含义 |
|---|---|
| capability_origin | NATIVE / ADAPTER / COMPOSITE；明确能力来自哪里 |
| declared_domain | dtype/rank/layout、值域、N/M/bytes、状态/模型、合法参数 |
| negotiation | 保留现有DIRECT_SUPPORTED / ADAPTER_LOSSLESS / ADAPTER_LOSSY / UNSUPPORTED |
| execution | NOT_RUN / 已执行终态；构建/ISA/设备不可用另记origin |
| expected_outcome | 事前应通过或应拒绝、在哪一阶段、原因；未知保持未知 |
| correctness | 原始域恢复结果、误差界或专属对象语义 |
| source_parity | BITSTREAM / CROSS_DECODE / SEMANTIC等实际声明及证据；不适用写N/A＋理由 |
| accounting / safety | FinalBits闭合、安全和恢复依赖证据 |
| performance_qualification | 未测 / QUALIFICATION / FORMAL组门禁；原始观测数、计时与资源排除 |
| evidence | 测试规格、数据/码流/模型/binary/hash、日志和有效版本 |

例如“f64 MTS支持”至少分成：原生联合、独立列封装、整体字节序列化。标记“支持”之后还应明确NaN域、N/M限制、block/tail和模型条件。`SCALAR→AVX2`、`1→p线程`或`one-shot→stream`分别建配置/工作负载证据。

性能矩阵单元不能只有一个速度。推荐同时展示：`路径来源 + 域内正确性 + 完整大小 + encode/decode速度 + timing边界 + ISA/线程 + 资格状态 + 证据`。未执行留空并写NOT_RUN，未采集写null与原因，不能写0或直接打勾。

## 8. 从lzbench与TerseTS借鉴什么

| 参考 | 可借鉴的设计 | 本项目需要保留的限制 |
|---|---|---|
| lzbench | 统一native byte接口、算法版本/等级/最大输入、init/deinit、重复计时、分块、长度＋memcmp验证 | byte可压不等于原生typed/time/channel语义；其driver块表等完整恢复成本仍需本项目实际保存并计费 |
| lzbench内部/外部MT | `INTERNAL_MT`与`BENCH_POOL_MT`分开，CLI分别有`-I`和`-T` | 当前本地版本的源码与较旧manual有差异；按源码核对。外部独立chunk并行会改变压缩率、context数量和内存 |
| lzbench统计 | min-duration与重复、多种统计选项 | 默认FASTEST只作参考；本项目主统计使用合格重复及median/CI等，且公开init/allocation边界 |
| TerseTS | 方法/配置统一接口、实际方法标识、方法特定loss/reconstruction、回环与边界测试 | C ABI是`double*＋len`，核心Zig；无shape/time轴。Python转f64与按size展平不是原生全dtype/MTS支持 |
| TerseTS回退与验证 | 单元素实际Uncompressed应记录实际方法；有bitcast级回环helper | 不把请求method直接当实际method；统一用本项目原始IEEE验证，不能采用弱化的数值近似判据 |
| Sprintz/lzbench分支 | 特定整数类型、ndims与row/column布局、AVX2执行的受控比较 | 浮点预量化到8/16bit后“无损”只针对量化整数，原始浮点端到端仍是有损；去掉T的实验不能算SYSTEM |

lzbench的`-R`是从随机输入块估测，不是随机访问解压能力。TerseTS的模型extract/rebuild也不等于compressed query。统一API应允许方法返回UnsupportedMethod，不能为了接口整齐伪造能力。

## 9. 建议的实施优先级

实际交付次序以V3.2 §15为准：先使首批共同组在多个真实数据集上形成完整方案比较，native计时按成熟范围并行补齐；随后分批覆盖多数CSV候选。本节各项是能力依赖，不要求所有native timer先完成才比较PIPELINE。

1. **先完成完整方案基线**：原始类型/对象语义、源域、cold decode、FinalBits与原始域正确性；为合法域建立正向/拒绝/边界期待矩阵。
2. **完成CPU比较主线**：共同任务与真实API边界，worker内状态、资源隔离、调度、MeasurementProtocol及AnalysisPolicy；取得当前身份的FORMAL证据。10个保留重写入口的内部timer按研究需要补齐，对应native/kernel profile独立验收。
3. **扩大明确管线覆盖**：通用逐列/ND映射、分块/tail、T＋V；每次扩域保存恢复描述、计时与成本证据。
4. **独立推进性能扩展**：stream、SIMD变体、内部/外部并行、query及设备/系统profile，按已有源能力和当前授权范围选择。

不应以给所有算法加SIMD、多线程或所有dtype作为“完成”的先决条件。完整性的判据是合同内闭环与合同外可解释；性能扩展的判据是声明功能真实执行、可恢复、可计费且可比较。

## 10. 依据与源码位置

项目内依据：

- [V3.2 总计划](../TimeSeries_Compression_Benchmark_V3_工程实施总计划.md)，§0顶层目标，§1.6候选基线，§3数据语义，§5适配/恢复，§6账本，§7计时/比较，§8四矩阵，§9验证，§10资格，§11扩展，§15.4长期路线，§20活动范围。
- [当前活动算法/CSV对照](registered_algorithms_20261010.md)；[活动范围政策](../registry/algorithm_scope.json)。
- [Dataset_Verify v1说明](../Dataset_Verify/README.md)；[V3实施记录](dataset_verify_v3_implementation.md)；[v1生成器](../tools/dataset_verify_v1/generate.py)；[v3生成/登记工具](../tools/prepare_dataset_verify_v3.py)。v1 README中“正式CLI只接受CSV/NPZ”属于历史，当前canonical入口已实现。
- [拓扑/类型/Track/对象层枚举](../src/tscompbench/contracts/enums.py)；[当前Codec Manifest目录](../registry/codecs)。
- [workloads.py](../src/tscompbench/measurement/workloads.py)：query从62行、stream从161行；[orchestrator.py](../src/tscompbench/execution/orchestrator.py)：query/stream附加执行从326/368行、主timing/resources在417行。
- [repetition.py](../src/tscompbench/execution/repetition.py)：346/385行起只接受INDEPENDENT_OBJECT；[native_streaming.py](../src/tscompbench/adapters/native_streaming.py)：91/106/150/181行为start/chunk验证/push/finalize；[neats.py](../src/tscompbench/adapters/neats.py)：407行起实际query。
- [rewrite_lossless.py](../src/tscompbench/adapters/rewrite_lossless.py)：已有codec局部逐列/分块wrapper；通用P2目标不能据此签为完成。

本地参考源码：

- [lzbench.h：byte API与线程模式](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench/bench/lzbench.h:126)。
- [lzbench.cpp：内部/外部MT选择](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench/bench/lzbench.cpp:524)，`-I/-T`在1028/1041行，默认FASTEST在1136行；长度与memcmp在673/679行。
- [lzbench manual：外部块线程池成本](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench/doc/lzbench.7.txt:46)。
- [TerseTS C ABI：double与len](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cmcuza_TerseTS/bindings/c/tersets.h:42)。
- [TerseTS Python：转float64与size](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cmcuza_TerseTS/bindings/python/tersets/__init__.py:214)。
- [TerseTS Zig：singleton改用Uncompressed](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cmcuza_TerseTS/src/tersets.zig:131)；[bit-exact helper](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cmcuza_TerseTS/src/tester.zig:440)。
- [Sprintz接口](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/dblalock_sprintz/cpp/Compress/sprintz.h:16)；[Sprintz实验数据说明](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/dblalock_sprintz/README.md:24)。

本次对文档、索引、manifest与源码进行了静态核查，未重新执行全算法资格或正式性能测试；矩阵中的“声明有”不替代这些执行证据。
