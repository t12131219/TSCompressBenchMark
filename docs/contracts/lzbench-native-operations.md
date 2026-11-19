# Zstandard / XZ 冻结入口复核与 M0 诊断

适用 selection **40 Zstandard、39 XZ/LZMA2**。两者共享
`third_party/archives/lzbench-native-source-unique-v1.tar.gz`，SHA-256
`54ddb93af4de953c6dd833c2d16f84286116d2c13b90b01dd87adffd2e173d7e`，CMake 只构建
一份 `lzbench_native`。以下是所选冻结实现的入口合同与**开发诊断**，不是平台支持承诺或
正式资格。两种算法在这些入口上处理字节，不直接声明 f64、T 或 TV 语义。

## 可直接引用的 Unique 来源证据

归档同版的 [Unique 发布验证记录](../../third_party/provenance/lzbench-native/unique-validation.json)
与 `fix_Release/lzbench-native/unique-v1/validation.json` 字节一致，锁定本合同的归档 SHA-256，
记载 `lzbench-native-features` 与 `lzbench-native-api_test` 在隔离构建下通过。
`fix_ReWrite/lzbench-native/FUNCTIONAL_REPORT.md` 也列两项通过，但原测试程序在交付树外，
报告未展开单个 case 与 worker 轨迹。直接引用其来源侧测试结论；不重跑旧整套 Unique 验证，
本工程只补下表中需要明确绑定的边界、依赖与实际执行证据。旧结果不提供新的性能测量或
TSBench 资格，当前重跑也不依赖旁边的 Unique。

## 具体入口、实测用例和剩余验证

| 操作组 | 源码合同与适用性 | 已绑定的 M0 诊断 | 正式证据仍缺什么 |
|---|---|---|---|
| `zstd-baseline` | 必需。`src/api.cpp` 的 `ln_create` 接受 level 1–22，主选 level 3；`ZSTD_compress2` 同步编码，content size 开、checksum 默认关；不加载字典。 | `lzbench_contract baseline zstd`：0、1、65,535、65,536 字节逐字节恢复；65,537 字节、短容量、负 level 拒绝。已有 TSBench `zstd` 开发插件做封装并限制单帧及窗口。 | 冻结正式方法用例、计量与恢复合同；开发插件的检查不能归因到裸入口。 |
| `zstd-session` | 必需。`src/extended.cpp` 使用 `ZSTD_compressStream2` / `ZSTD_decompressStream`；只支持 frame，level 范围由冻结 Zstd 给出，允许负 level。`reset` 保留已分配的 CCtx/DCtx 但重置会话、参数并重装字典。`pledged_size` 未指定为 −1，非负才向后端设置。 | `lzbench_contract session zstd`：level −1、`workers=0`、checksum 开，136,013 字节以 4,093/7 字节编码输入／输出跨度反复 finish；后续 7,919 字节独立帧先由新会话解码；解码重置、截断失败后恢复、错误跨度、未知参数及 `pledged_size=-2` 拒绝。 | 正式服务入口、正式数据和资源档、每条性能输入的吞吐与首输出延迟；选定调优参数及适用分支的覆盖。 |
| `zstd-dictionary` | 必需。`train_zstd_dictionary` 合并有序样本但保留各样本长度，调用冻结 `ZDICT_trainFromBuffer`；容量下限 256、上限 `INT_MAX`，实际仍受训练器和有效样本资源约束。字典字节由配置持有，在编码和解码分别加载。 | 128 个确定性训练样本与独立生成的 31 个 held-out 片段；训练容量 2,048 字节；删除训练样本与暂存原文后，以新进程只读码流和字典恢复；缺字典与 ID 不匹配预期拒绝。证据记录训练样本、码流、字典和 held-out 的 SHA-256。 | 正式、互斥的语料分区及字典依赖保留；训练、重装、配置/字典传输与摊销单列。此合成诊断不主张实际语料的字典收益。 |
| `zstd-workers` | 有条件必需。扩展编码配置 `workers=0..64`，实际值可在 reset 后查询；需要冻结构建开启 `ZSTD_MULTITHREAD` 和可分派输入。此实现解码走 `ZSTD_decompressStream`，不把编码 worker 算成解码 worker。 | 固定 5,243,177 字节，level 3，job size 524,288，分别在隔离子进程配置 `workers=0/2`，比较恢复字节及原生编码钩子；没有解码钩子活动。 | 性能独占与同资源组、其他适用大小/模式、资源实际开销；distinct worker IDs 不证明同时占满多个核心。 |
| `xz-baseline` | 必需。`src/api.cpp` 的 `ln_create` 接受 preset 0–9，主选 6。每次调用重新初始化 XZ stream，`threads=1`；编码 `LZMA_CHECK_NONE`，解码使用 `LZMA_CONCATENATED\|LZMA_IGNORE_CHECK`、`memlimit_stop=256 MiB`。只接受可信码流，不提供带校验的任意流导入承诺。 | 保留裸入口的四份帧，核对实际 worker、LZMA2 字典属性、独立恢复、原始长度、截断与内存拒绝。开发插件另有完整封装、边界、同版产物差分与独立恢复，见下节。 | 开发留样不是正式资源档与恢复合同；不能把扩展会话的 checksum 支持算给基线。 |
| `xz-session` | 必需。`src/extended.cpp` 构造 XZ frame + LZMA2，使用 `lzma_stream_encoder_mt/decoder_mt`，每方向 reset 销毁并重新初始化该方向 stream。支持 preset/字典大小等 LZMA2 配置及最多三项经验证的 Delta/BCJ 前置 filter；不接受外部字典 blob。`check` 支持构建可用的 None/CRC32/CRC64/SHA256，`memory_limit` 同时约束编码估算及解码的 stop/threading；默认 2 GiB 不是整个进程的 RSS 或输出限额。 | preset 1、32 KiB 块、CRC64、Delta 距离 4、64 MiB 限额、单 worker；验证多块、两方向 reset、校验与独立恢复。分别触发编码预算、解码内存、非法 filter、外部字典、非法跨度及截断拒绝。 | 其他适用 filter/check、资源档及实际资源开销仍待验证；这里只验证了一条合法配置及指定反例。 |
| `xz-workers` | 有条件必需。`threads=1..64`，编码与解码各自受块大小、块头信息、缓冲输入和内存限制。即使线程参数生效，也可能没有可调度的并行块。 | 2,097,449 字节，preset 1、128 KiB 块、CRC64、128 MiB 限额；分别观察 `threads=1/2` 的编码。两种解码配置在新进程读取**同一**多块码流，比较字节并记录实际解码钩子。 | 更小输入及内存降级时的实际分支，正式独占测量和资源限制。不能按参数推断实际 worker 数。 |

共用边界：legacy 块只有 `0 <= n <= LN_MAX_BLOCK`，编码须由调用方给足 `ln_compress_bound`；
解码须提供正确的外部原长与输出上限，错误时 `produced=0` 但写入区可能已修改。扩展 API 的
`compress_block` / `decompress_block` **不是**这两个 stream codec 的入口；实际是
`session::process`。它接收当前不重叠的输入/输出跨度，输出容量须为正，报告
`consumed/produced/finished`。开始 finish 后，驱动须重试剩余输入直到完成；不得把传入
finish 等同于完成，处理异常或到达终点后需要方向 reset。正式计划另行限制输出、停滞重试、
总时限和保留，不能把测试驱动持有完整输入/输出的便利做法当作低内存或首产出证据。

## XZ baseline 的 worker 路线

`xz-baseline` 与 `zstd` 可以各自启停，共用同一个冻结构建 `liblzbench_native.so`。它调用
`ln_*` 的 `LN_XZ`、preset 6，不公开会话、线程数或字典选项。输入是至多 65,536 字节的单个连续无
validity 列，独立 XZ stream 每次重建。TSBench 的 `BMKXZ` 封装单列类型、长度及 schema，账上独立列
32 字节头、schema 和 native payload。解码先检查长度、原生压缩上界、头尾及 Index，仅接受无数据
Check、无 stream padding 的单个 stream（非空一块，空输入零块）。Index CRC 不是原始数据校验；
恢复仍面向可信自产物，原值域逐字节比较是独立验证。256 MiB 是库解码器的内存限制，不是整进程 RSS 上限。

`ctest --test-dir <build> -R '^tsbench.worker.xz-baseline.recovery$' --output-on-failure` 独立复核
空输入、65,535／65,536 字节的确定性高熵输入和 1,029 个真实气象 f64 值。四份 payload 与同一冻结库
直调逐字节一致；移除暂存原值和 schema 后，分别用新 worker 恢复数据及 schema。检查还拒绝超限输入、
未知选项、截断、拼接、padding、数量错配、错误 Index、非基线 Check 和超限帧，并确认不留下输出。
该探针加入同一次 M0 统一运行；未把 stream 和多线程直调提升为 worker 能力，也不提供正式性能或资格。

后续 [五路线冻结批执行](linear-batch-execution.md) 已将四个 XZ 裸基线边界及精确恢复、原生短容量、字典限额和 job 观测放入同一份候选账本。采用独立 XZ 地址空间档，不覆盖本表的扩展会话或多 worker 组。

## 原生作业证据的解释

`src/trace.cpp` 是进程级计数器。实际 hook 位于冻结归档的 `ZSTDMT_compressionJob`、
XZ `worker_encode` 和 XZ worker 的 `block_decoder.code` 调用前。XZ 解码 hook 计的是
处理调用，不是一条逻辑块恰好一次。CMake 测试每个参数组合用独立子进程、无其他算法并发，
在编解码之间清零并分别读取。Zstd 的零个解码 hook 不是对任意解码实现的线程断言；该版本
不暴露内置并行解码路线。这里没有使用 TSBench 外部分块或并发冒充原生 worker。

## 重跑

以 `tsbench` 的 Python 配置 Release 构建，运行
`ctest --test-dir <build> --output-on-failure -R '^tsbench.control.lzbench$'`。
测试链接冻结共享库，并复用冻结树的 `feature_worker` 进行字典和实际 worker 诊断；
`<build>/lzbench-native-probe/report.json` 只在全部检查通过后由测试发布，绑定源码/执行文件哈希、
7 组观测及 20 份留存产物（18 份成功帧、1 份负向帧和 1 份字典）。驱动剔除 C++ feature worker 内部计时字段，明确声明
`formal_performance=false` 和 `formal_qualification=false`。这不是正式全量计划，也不是
把若干执行收据拼接成阶段通过。

### 已绑定的 29 项必需检查

- **Zstd 裸批（4 项）**：保存 `ln_compress` 对 0、1、65,535 和 65,536 字节生成的帧、以及独立调用
  `ZSTD_compress` 的一份帧。用 `ln_decompress` 交叉解码上游接口帧；新进程用同一冻结库的上游
  `ZSTD_decompress` 解码每份留样并比较原值，这不是不同库版本的互操作。核对帧内容长度、无字典和
  checksum 默认关闭，实际拒绝错误原始长度和截断。裸入口失败时确认返回的 `produced=0`，
  不把它解释为调用者缓冲区没有发生部分写入。已有边界 triplet 与 v3 用例仍绑定在 worker 探针。
- **Zstd 原生会话（5 项）与 XZ 原生会话（5 项）**：保存每个编解码调用的 `[offered, consumed, produced, finish, finished]`。
  离线重放调用者分段、未消费输入、首个产出点、两方向 reset、结束时零输入 drain 和总字节；首输出点是调用序号，
  不是延迟测量。把两个完整帧分别送到新进程，验证不需要上一帧或原始数据文件即可位级恢复。
  Zstd 会话有 checksum；离线只是核对标准帧头、块界、账本及实际恢复摘要，不重新验证压缩内容的 checksum。
  XZ 留样用 Conda `tsbench` 的 Python `lzma` 独立解码，验证 CRC64、原值与帧边界。复算还核对每块头部
  CRC、Index 长度、Delta 距离 4 与 LZMA2 属性；136,013 字节的输入得到四个 32 KiB 块和一个 4,941 字节尾块。
  另在冻结会话入口分别实触发 1 字节编码预算、64 MiB 解码预算以及未知 BCJ filter 的拒绝。
- **XZ 裸批（5 项）**：保存 0、1、65,535 和 65,536 字节的四份成功帧，65,537 字节输入被拒绝。
  分别核对空流零块、非空单块、无数据 Check、preset 6 配置、8 MiB LZMA2 字典属性及实际单 worker，
  非空帧在新进程逐字节恢复，空帧也独立验证；错误原始长度和截断均被拒绝。
  从一字节合法帧构造负向帧，只改 LZMA2 声明为 384 MiB 字典并重算块头 CRC。保留该负向帧供有界复算，
  其触发 256 MiB 裸批解码预算和 64 MiB 会话解码预算拒绝；不将声明值解释为实测分配或 RSS。

- **Zstd 字典（5 项）**：独立生成的 128 个训练样本和 31 个留出样本按内容摘要冻结，核对互斥；训练器
  在分配前拒绝容量 255 和 2³¹。保留 2,048 字节字典与 520 字节依赖帧，恢复依赖一次共 **2,568 字节**。
  新进程只拿帧和字典逐字节恢复，缺字典和错误 ID 均拒绝。隔离复算核对依赖身份、计费和实跑恢复摘要，
  不调用 Zstd 解码器，也不把此合成输入的依赖字节数当作真实语料上的压缩收益。
- **Zstd worker（3 项）**：`workers=0/2` 使用同一输入和匹配的有效配置，保留两份帧，移除暂存原文后
  逐帧由新进程还原。同步设置无后台 job；双 worker 设置记录到 11 次编码 job 和 2 个不同 worker，
  该路径解码不声称并行。帧解析和恢复摘要复算不等价于再次实际运行 job。
- **XZ worker（3 项）**：保留调用线程同步、`threads=1`、`threads=2` 三份完整产物。`threads=1` 实测仍有一个后台
  worker。冻结包没有 `lzma_stream_encoder`，因此诊断用同包的 `lzma_block_encoder` 在调用线程逐块编码，
  按 MT 路线的块预留、16 KiB 内部跨度及无压缩 fallback 规则组装单一 XZ Stream，不换系统库、不改冻结源码。
  同一 2,097,449 字节输入，preset 1、CRC64、1 MiB LZMA2 字典、128 MiB 配置预算，三条路线均生成
  16 个 128 KiB 块和一个 297 字节尾块；**在这个输入上**三份产物都是 2,098,188 字节且逐字节相同。
  移除暂存输入后，冻结包的 `lzma_stream_decoder` 在新进程分别恢复自己的帧和**同一份两 worker 编码产物**；
  两个 MT 解码 profile 也在新进程读取后者。同步编解码的 MT hook 均为零；MT 解码实见 1 和 2 个 worker。
  离线复算绑定共用帧的路径与摘要、检查 Index、CRC64、每块 filter 属性及恢复原字节。同步记录的
  9,015,815 字节是 raw encoder 估算，不是 MT 工作队列估算、总进程内存或峰值 RSS。

这些 job 观测不是多核同时占用、吞吐优势或 M4 剖析证据。同步组装器只是 M0 对照，不是新的正式 codec
路线，也不意味着任意输入的同步和 MT 产物都相同。XZ worker 仍缺正式执行绑定；以下的会话执行也不授予 TSBench 公共流式服务资格，
不比较 batch 与 stream 的性能。

## extended-v13：两个原生字节会话接入统一执行

`zstd-session`（#40）和 `xz-session`（#39）各绑定一个产品槽、五项必需义务，与已有路线共用一份冻结计划、
一次提交和一个主账本。新增驱动 `tsbench_lzbench_session_control` 从两种 baseline 插件所在构建目录封存，
只依赖同一份 `liblzbench_native.so` 和运行库，不加载 batch 插件。不从之前的 CTest 或 Unique 报告导入 PASS。

- 两路线都实际调用 `lzbench_native::session::process`，不是外部将 batch 切片。第一帧输入 136,013 B，
  reset 后第二帧输入 7,919 B；配置和六组正向跨度由原生用例约束。保留完整调用日志，不把 finish 请求当成完成。
  首帧编码 `4093/7` B 输入／输出跨度，两路线都必须出现零输入时的实际 finish 排空。首输出记录的是从零开始的
  调用序号，不是延迟或吞吐。此驱动持有完整测试输入和产物，不证明应用级在线传输或低内存行为。
- Zstd 配置 level `-1`、`workers=0`、checksum 开，无外部字典。核对标准帧和窗口（此用例要求不超过 1 MiB）；
  实触发非法 pledged size、重叠与零容量跨度、批入口、截断和失败态拒绝。XZ 配置 preset `1`、`threads=1`、
  32 KiB block、Delta 距离 4、CRC64；核对 Index、块长及 LZMA2 字典属性，并用有界 Python `lzma` 从保留的帧
  单独核验数据 CRC64 与输出原字节。原生会话实拒绝外部字典、非法 filter、1 B 编码预算及声明 384 MiB 字典的
  负向流；**64 MiB** 是 XZ 会话库内预算，**256 MiB** 是这个槽的进程地址空间上限，都不是实测 RSS。
  `threads=1` 走 MT API，不据此声称调用线程同步执行；worker 对照另验。
- 每个槽保留两份裸帧。原值文件从临时输入目录移除后，每份裸帧在独立进程只挂载自身与冻结的 ELF 闭包；
  不挂载另一份帧、原文或 batch 适配器，进程外按计划中的字节数与 SHA-256 核对输出。封存审计再以独立恢复的
  原值复跑整个两方向 reset、排空及原生拒绝过程，重生两份帧并校验字节一致；不要求重放的逐次进度与原日志相同。

离线迁移重跑（输出目录必须为空，进入 `tsbench` 环境）：

```bash
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --lzbench-session
```

这是有界功能候选，不授资格，不是 TSBench 公共流式服务准入，也没有比较 batch 与 stream 的性能。
`zstd-dictionary`、`zstd-workers`、`xz-workers` 不属于 v13 账本，由后续 v14 独立重跑。

2026-11-19，[`extended-v13` 主报告](../../results/m0-lzbench-session-unified-20261119-r2/report.json)，
run `a52bfe7438654848b9f73186faeee428`：**166 槽、142 槽通过独立恢复、24 项预期拒绝**；
**24/36 个原生操作组、124/180 项必需义务**在本次有候选证据，剩 56 项必需和 6 项条件未绑定。
Zstd 两帧为 4,758 / 2,036 B，首帧编码 11 次带 finish 的调用；XZ 两帧为 952 / 196 B，首帧编码
54 次带 finish 的调用，Index 显示四个 32 KiB 块和一个 4,941 B 尾块。这些计数只对应冻结的测试跨度。
空构建、迁移路径及禁网验证下通过 15/15 CTest 和 166 项 Python 测试。
[恢复](../../results/m0-lzbench-session-unified-20261119-r2/restore.json)和报告逐字节复算不挂载原构建或原数据；
20 项计划改写及 3 项会话证据重封存负例均被拒绝。`r2` 是从头执行，不汇总 `r1` 或旧 `extended-v12`；
旧 v12 主报告仍逐字节复算一致。

## extended-v14：字典与原生 worker 对照接入统一执行

新增 `zstd-dictionary`、`zstd-workers`、`xz-workers` 三个槽。封存程序使用原归档的 `feature_worker` 源码和已经验证的 XZ 调用线程对照；两个程序在同一份 `liblzbench_native.so` 旁构建，只挂载各自 ELF 闭包和计划指定的输入。实验不是外部分块、外部并行，也不是把历史开发结果写入新账本。

- **Zstd 字典**：按冻结顺序只挂载 128 个训练样本，held-out 的 31 个片段只在训练结束后送入编码；逐样本核对 SHA-256 和互斥分区。恢复仅挂载字典和码流，计费为两者实际大小之和；实际重跑非法训练容量、缺字典及错 ID 的拒绝。合成样本用来验证依赖和恢复，不用来推断真实语料上的字典收益。
- **Zstd worker**：同一输入、level、job size 与帧选项，分别走 `workers=0/2`；由冻结原生 hook 核对作业及参与的不同线程，逐帧以新进程恢复。不从编码线程推断解码线程。
- **XZ worker**：同一多块输入比较调用线程同步组装、MT API 的 `threads=1` 和 `threads=2`。两档 MT 解码与同步解码均读取计划指定的同一份 `workers-2.xz`；另外独立恢复各自的产物。不是把 `threads=1` 写成调用线程同步。验证 Index、CRC64、过滤器、块边界和原始 SHA-256，分别核对编码、解码 hook。
- **资源与运行条件**：worker 槽只为原有 5 MiB / 2 MiB 工作负载使用 6 / 3 MiB 的单文件上限，两条 worker 路线均为 512 MiB 地址空间、15 s 操作截止；两档 XZ 共享相同进程上限和 128 MiB 原生 `memory_limit`。Zstd 和 XZ 的两项 runtime 条件各绑定实测槽；不接受“配置请求相同”或“编译支持”作为 work 证据。其他四项条件仍留在原分母。

```bash
bash tools/probe_offline_unified_batch.sh "$CONDA_PREFIX" "$RUST_TOOLCHAIN_PREFIX" <空结果目录> --lzbench-profiles
```

恢复审计只从封存产物读取帧与字典。各帧先分别恢复，随后以恢复出的原字节重新运行对照并核对重生产物，字典训练输入由封存定义再生成。原生驱动 stdout 包含调试计时，报告剔除此类字段；后台线程数量与作业数不表示核同时利用率、吞吐比较或 M4 剖析结论。

2026-11-19，[`extended-v14` 主报告](../../results/m0-lzbench-profiles-unified-20261119-r3/report.json)，
run `371e6685a2e54944bf1b2eea93a03058`：**169 槽、145 槽通过独立恢复、24 项预期拒绝**。
字典 2,048 B、依赖帧 520 B，首次恢复共 2,568 B。Zstd 这份输入的两份帧均为 5,243,306 B；`workers=0`
没有后台作业，`workers=2` 有 11 次编码作业、2 个不同后台线程；未观察到解码 worker 作业。
XZ 这份输入的三份帧均为 2,098,188 B 且逐字节一致；两档 MT 编码各 17 个作业，实际 1 / 2 个后台线程。
同一帧的 MT 解码实际 1 / 2 个后台线程，同步解码无 MT hook；不要将 MT 解码的 hook 调用次数解释为块数。
`tsbench` 空构建、迁移、禁网通过 15/15 CTest、170 项 Python 测试。
[独立恢复与重跑](../../results/m0-lzbench-profiles-unified-20261119-r3/restore.json)和报告逐字节复算通过；
22 项计划改写及[3 项专项重封存负例](../../results/m0-lzbench-profiles-unified-20261119-r3/lzbench-profiles-reseal.json)被拒绝。
两次预备尝试均在提交前停止，不提供运行证据；旧 v13 主报告仍可逐字节复算。
