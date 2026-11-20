# M4 证据：原生阶段剖析、并行重叠与插桩扰动

这是独立的**诊断运行**，用于 M4 阶段收据的协议与对照验收；它仍不是主性能测量或算法资格。覆盖三个已经有原生运行证据的直接入口；
不是 TSBench 全部方法的 pipeline_full profiling。主测量仍使用原来的未加本 SDK 的构建与入口。

## 构建与对照边界

- `TSBENCH_PROFILE_BUILD=OFF` 是默认值，`tsbench_profile_driver` 在这里不链接 trace SDK。
  独立目录以 `ON` 构建，只为两个已验哈希的 native 翻译单元生成额外 trace 源文件：`alp-native` 的
  `src/codec.cpp` 和 `lzbench-native` 的 `zstdmt_compress.c`。原始归档和已核验解包目录不被修改；
  不关闭 ALP AVX512 对象，本次明确执行的是 **AVX2**，不替代 AVX512 运行验收。
  ON 树不构建常规 TSBench worker 或正式/候选主计时 driver。保留 Unique 自带的 job 计数代码，
  不把未加新 SDK 错报为连原生统计逻辑也被移除。
- 三个 arm：`timing_only` 使用 OFF 构建；`trace_off` 和 `profiled` 使用同一个 ON 构建，分别关闭、开启
  新采集。每种 case 三个按冻结种子随机安排顺序的匹配轮次，编码、解码分别启动新进程。
  逐产物比较原始位，所有 arm 的完整原生码流按 case 逐字节一致。每条记录都是一个方向独立进程的新观测，
  不复用主计时数字，不把多个阶段之和冒充总耗时，不把观测差值当可统一扣减的常数。
- L0 以调用方 `steady_clock` 围住工作区分配、上下文准备、完整 native 操作及必要清理、文件写入并关闭。
  源文件读取、编解码输出比对和 trace 序列化在这段时钟外。L1 实测准备、codec+清理和写出三个阶段；
  不凭空为该直接入口添加解析、布局或外层封装时间。调度使用本机协作锁，不声明专核、稳定热身或外部干扰为零。

| 路线 | 实际工作 | L2 边界 |
|---|---|---|
| ALP `alp-fused` | 8,192 个 f64 十进制值；Auto 编码，显式 AVX2 FALP 解码 | 原生 `generated::falp::x86_64::avx2::falp` 调用处计时；`[unpack_bits, reconstruct]` 合为一个 `fused` 阶段。编码及解码其他内部阶段未测。 |
| Zstd `zstd-mt` | 5 MiB + 617 B，level 3、2 worker、512 KiB job、checksum，直接 session API | 包围 native `ZSTDMT_compressionJob`，保留真实线程 ID。每个作业包含原入口工作，不等同于熵编码耗时；L2 解码未测。 |
| XZ `xz-opaque` | 32 KiB，冻结 `ln_*` 裸批、preset 6 | L0/L1 实测，L2 `opaque`，时间为 null。不能从缺失插桩推断无内部工作或无内部线程。 |

采集器每进程一次初始化，给最多 16 个线程预分配独立缓存，线程首次出现时领取槽位；热路径不序列化、
不写文件、无全局日志互斥锁。常规 profile 每线程可留 128 个事件；达到容量明确报丢失。以 2 个事件容量
实际重跑 ALP 做负载控制，不能把这一不完整时间线用于精确 exclusive time。
汇总以同一 host 单调时钟计算区间**并集**、重叠量及峰值并发；仅从调用线程根区间减去它的直接同线程
子区间并集，异步 worker 关联不从调用线程扣减。线程区间和另列，不当作 wall 或线程 CPU 时间。

L3 尝试读取 `perf_event_open` 的调用线程用户态 cycles（不代表 worker 总计数）。失败记录 errno 和 null；
另从进程监督保存 `wait4` CPU/RSS，只在进程级解释。该诊断不推断缓存 miss 或 NUMA 局部性。

## 已执行的证据

2026-11-19 使用 `tsbench`，[同一冻结计划](../../results/m4-native-profile-20261119-r2/plan.json) 执行
[run `5694e57a4f6846d9bf8725df816e9276`](../../results/5694e57a4f6846d9bf8725df816e9276/derived/report.json)：
**28/28** roundtrip、56 个进程操作；其中 27 个用于配对，1 个为容量压力对照。不把压力对照加入扰动分布。
常规 ALP 每次 decode 8 个实际 AVX2 融合向量；常规 Zstd 每次 encode 11 个 native jobs、2 个 worker；
一轮作业时间并集约 2.95 ms、线程区间和约 4.83 ms，实测存在重叠。所有常规 trace 零丢失；压力对照
encode 丢 2、decode 丢 10，同时完整恢复。profile arm 的 cycles 不可用，保留 errno，不填 0。

[控制证据](../../results/m4-native-profile-20261119-r2/controls.json) 验证 CLI/API 计划一致、两个构建的
ELF 依赖区分、重算封存后仍拒绝改写丢失计数和越过 L0 的 worker 区间；[禁网复算](../../results/m4-native-profile-20261119-r2/recomputed.json)
不挂载原构建和语料，逐字节一致。报告复算不重新解码；本次 decode 以帧为唯一数据入参，但 profile
进程未做文件级沙箱，不能代替 M1/M3 独立恢复资格。M4 阶段收据见 `results/m4-acceptance-20261119-r1/receipt.json`；该收据接纳 profiling 与测量对照协议，但仍保持 `timing_admitted=false`，不开放正式性能排名。

## 复现

```sh
for side in OFF ON; do
  cmake -S . -B "build/profile-$side" -DCMAKE_BUILD_TYPE=Release \
    '-DTSBENCH_PLUGINS=alp-auto;zstd' -DTSBENCH_PROFILE_BUILD="$side" \
    -DPython3_EXECUTABLE="$CONDA_PREFIX/bin/python"
  cmake --build "build/profile-$side" --target tsbench_profile_driver
done
./bmk profile-plan --plain-build build/profile-OFF --profile-build build/profile-ON --out build/native-profile.json
./bmk profile-run --plan build/native-profile.json
./bmk profile-report <run_id>
```

测试挂载与负对照入口分别为 `tools/probe_offline_m4_profile.sh "$CONDA_PREFIX" <run_id>` 和
`"$CONDA_PREFIX/bin/python" -I -B tests/isolation/profile_evidence.py <run_id>`。

## 新合同：绑定真实 M3 输入与配置的三类剖析

[真实输入剖析计划 r3](../../results/m4-real-profile-20261120-r3/plan.json) 对应 r40 冻结项，分别绑定以下封存证据：

| 剖析对象 | 实际输入及配置 | 与 M3 的核对 |
|---|---|---|
| ALP 融合 | ETTm2 值列 5 的 `[0,65536)`，原生 Auto 编码、显式 AVX2 FALP 解码。 | r39 共帧功能的 `falp-auto` 在该单元实际选 AVX2；每次解码同样观测到 51 个融合向量。裸产物加回 M3 头及 schema 后与冻结帧的长度和 SHA-256 一致。与 AVX512BW 无关。 |
| Zstd 多线程 | Weather 全部 8,852,928 B 规范交错 V，level 3、524,288 B job、checksum off。编码两个后台 worker，解码零后台 worker。 | 沿用 r30 已验证的两 worker 帧、每方向 native 输入/输出 span 和 finish 条件；核对原封存帧、实际 17 个 job 和两个 worker。没有把 `workers=2` 当成实测。 |
| XZ opaque | ETTm1 交错 V 字节 `[0,65536)`，preset 6、check none、单线程裸批。 | 关联封存的 M3 同 ABI 双入口批计时 case，从固定帧解析原生载荷；每次产物加回相同 M3 封装后核对既有帧身份。XZ 内部未插桩，L2 为 `opaque`，时间为 null。 |

[封存账本](../../results/m4-real-profile-20261120-r3/runs/956a56a6325e46d38f0140dc1046f6f3/trials.jsonl) 与 [复算报告](../../results/m4-real-profile-20261120-r3/runs/956a56a6325e46d38f0140dc1046f6f3/report.json) 覆盖 28 个试验、56 次方向调用。每个对象三轮匹配的 pristine、trace-off、profiled 对照另加一次 ALP 容量压力控制。固定各对象解码帧，所有方向输出按长度/摘要与确定的帧或原始值比对。regular profile 无丢失；容量 2 的 ALP 控制令编码丢失 2 个、解码丢失 53 个事件。Zstd worker 跨线程重叠按时间区间并集和重叠报告，不把线程区间和当作总墙钟。20 次开启采集的调用均没有可用的 cycles 计数，保留不可用状态，不填零。

pristine 的 codec 共享库与 M3 构建一致；trace-on/off 共用同一个 overlay 构建，驱动另建、不改历史产物。L0 包围准备、native 操作与清理、序列化，L1 细分这些步骤；规范输入预先物化，Zstd 调用的 span 与源合同相同，但这里缓冲输出后单独写盘。未计 M3 插件封装/源文件 ingress，也不以 L0 差值冒充同边界的框架开销。CPU 12、13、14 只做继承亲和，没有系统级独占；r40 功能运行仍活跃。执行进程受 `prlimit` 约束，但不声称 files-only 隔离；不代替 M3 恢复或主计时。报告可以由 `tools/probe_offline_m4_real_profile.sh` 仅挂载 `tsbench`、控制代码和封存运行，在禁网环境逐字节复算，篡改丢失计数和把 worker span 延伸至 L0 外都被拒绝。该诊断不授予新版 M4 阶段通过或正式计时资格。

与后续封存的 M3 重复计划逐项对账：[XZ 双入口留样计时](../../results/m3-fixed-batch-r40-samples-20261120-r1/runs/4df81a6f8c714389b8d66b3d5cb37452/report.json)覆盖同一个 ETTm1 XZ 前块，原始块、配置、编解码后端和帧摘要与剖析匹配；[Zstd 七文件计时](../../results/m3-zstd-worker-seven-files-20261120-r1/runs/b20d44735ed846318c626d46e35a591f/report.json)的 Weather 双 worker 单元与剖析在输入、配置和帧摘要上一致，实际 17 个编码 job、两个后台 worker，解码零后台 worker。两类诊断的时钟边界仍不能直接相减。

[ALP 精确单元双向计时](../../results/m3-alp-m4-exact-20261120-r1/runs/d8e060da99564a3ba2ffccfcae6ae5a7/report.json)覆盖同一 ETTm2 第 5 值列（从 0 起算）`[0,65536)`，不是用第 0 列近似。该帧在 r40 已按留样政策释放；[单元重建证据](../../results/m3-alp-m4-exact-20261120-r1/anchor.json)从冻结原始位串用锁定 ABI 编码器重建完整 364,667 B BMK 帧，与主账本及 M4 封印摘要一致。两后端在独立禁网进程只读同一帧并恢复原值，`falp-auto` 实际走 `falp-avx2`、记录 51 个融合向量。随后同 ABI 两入口、两个生命周期的原生重复共 32 个批次全部通过（8 校准、24 测量），从各自封存记录独立复算；不重用剖析时钟，也不授予 AVX512BW 运行资格。三类剖析均有对应输入和配置的独立测量诊断，尚不等于新版 M4 验收。

### M3/M4 精确对账与成本报告

[成本对照 r2](../../results/m4-real-profile-20261120-r3/cost-comparison-20261120-r2.json)用 `tools/verify_m4_cost_comparison.py` 从四个封存运行独立复算。三个对象均核对 r40 计划、运行配置、规范输入／范围、固定帧摘要及 pristine 原生库身份；Weather 的七个诊断测量轮还重新读取主计时记录，核对编码 17 个 job/2 个后台 worker、解码 0 个后台 worker，逐次保留实际 API 调用数（不要求轮间调用数相等）。

- ALP AVX2、XZ 的链接入口与 `dlopen` 差值只在同一公开 ABI、同生命周期和匹配轮内计算，独立样本数按进程批次计算，不按内循环次数计算。Zstd 的 M3 运行只有包含驱动 I/O 的进程墙钟，缺原生全操作时间，不填零。
- 剖析扰动只在同一驱动三个执行臂的匹配轮内计算，保留带符号范围／中位数、L0/L1/L2、缺失计数器以及事件覆盖；容量压力对照单列，不混入常规分布。三个 `cross_driver_overhead_ns` 均为 `null`：M4 L0 含准备、清理和序列化，但不含框架 ABI 包装和原件加载，不能与 M3 的时钟直接相减。报告也不把阶段时间冒充已测量的分配／复制次数。
- 该报告补足证据绑定和可复算对照，不消除原剖析运行的已声明并发干扰，也不完成全部尺寸下等价直接调用与框架成本验证。M4 新版仍未验收，不授予排名。

### 同等 public ABI 工作：生产 Context 与直接 ABI（功能预检）

新增独立 `native/measurement/m4_abi_cost` 驱动。两个 lane 共用生产插件加载验证和同一冻结 DSO，直接 lane 使用 ABI callbacks 与栈上所有权句柄，框架 lane 经过生产 `tsbench::Context`；两者相同的配置、类型、输入、原生上下文生命周期与校验后端。分别观察 `cold`（计入 create）与 `steady_reset`（同一上下文先预热，再明确 reset）而不混合分布；result-ready 结束在序列化之前，另记输出 release 和 context destroy。独立解码只挂载固定帧及类型 schema，不挂载源值。

计数二进制与 timing-only 二进制分开，计数臂的墙钟不进入 timing-only 分布。计数覆盖调用方可链接拦截的 `operator new(size_t)` 及 out-of-line `memcpy`；不宣称捕获 DSO/stdlib 内部分配、内联复制或缓存命中。驱动报告的调用顺序经实际回调、同产物比较和返回的原生信息检查，不用拆开的裸内核结果估算适配费用。

[同工作隔离功能预检](../../results/m4-abi-cost-smoke-20261120-r1/report.json)用 ETTh1 第一值列前 8,192 个 f64（64 KiB），冻结 raw-store、Zstd、ALP 和 XZ 公共 ABI 插件，核对 **64 次方向调用**，所有产物与同方法固定帧／原值逐字节匹配。计数臂每个方向实际看到框架持有者一次 `operator new`，直接 lane 未触发该类别调用。这只说明调用方持有者开销，不代表算法无分配或无复制。预检不留性能数字；还须运行冻结小消息、块边界两侧、缓存较小及超过 LLC 等对照并报告配对分布。

### 多尺度对照的冻结设计

`configs/experiments/measurement_controls/m4_abi_cost_v1.json` 固定真实源窗口：ETTh1 小消息及 64 KiB 边界、ETTm2 的 ALP 1,024 元素向量两侧与同原剖析 `[0,65536)` 精确单元，以及 LD2011 两种原样字节视图。Zstd/XZ 批处理 ABI 在 64 KiB 以上不生成计时样本；上侧对照为仍合法的 raw-store/ALP，不能误当成 Zstd/XZ 已支持更大块。LD2011 小对象核对名义载荷、帧和恢复物的尺寸预算低于本机 L2；大对象仅逻辑输入已经超过固定 CPU 的共享 LLC。两者既不证明缓存冷热，也不比较不同插件的 cache 命中率。

每个配置、生命周期、方向均以五个独立配对轮记录 `framework − direct` 的带符号分布；每对 lane 运行顺序预先随机化。计数单列，不进入时钟分布。每次实际输出校对完整字节，解码不挂载原值；21 MiB 以上仅限指定 raw-store 字节视图和两个锁定二进制，不放宽通用隔离工具的上限。直接/框架差值局限于相同 public ABI 的 `Context` 路径；源解析、调用入口/装载、结果序列化另有边界，不能从 M3 成绩统一扣减。

```sh
# 计时运行与 M3 共用协作资源锁；不要同时提交测量。
python tools/m4_abi_cost.py plan --source results/m3-real-r40-20261120/plan.json \
  --build build/m4-abi-cost-v1 --cpu 12 --out results/<new>/plan.json
python tools/m4_abi_cost.py run --plan results/<new>/plan.json --runs results/<new>/runs
python tools/m4_abi_cost.py verify --run results/<new>/runs/<run_id>
```

[多尺度报告](../../results/m4-abi-cost-20261120-r1/runs/e39284f8e8364a57aecd47a1de34e4f2/report.json)已封账并独立复算：10 个真实源形状、18 个形状×插件组合、两种上下文生命周期，**1,008 次**逐产物验证的独立方向调用（720 timing-only 测量、144 预热、144 独立计数）。对每个组合/生命周期/方向报告五个带符号配对差，不相减不同边界的中位数。LD2011 两档逻辑输入分别为 236,800 B 和 25,456,000 B；本机 L2/LLC 分别为 2 MiB/20 MiB，只作名义容量对照，实际缓存计数仍未观测。

[跨证据对账](../../results/m4-abi-cost-20261120-r1/profile-link.json)分别复算 1,008 次 ABI 试验、696 次 Zstd/XZ 原生诊断与原来的 56 次代表性剖析方向，并核对 ALP 相同 ETTm2 列窗/帧、相同 AVX2 路由与 51 个融合向量；Weather Zstd 按两 worker 相同配置与固定帧关联新 native-clock 分布（编码 17 个 job，解码零个后台 worker）。旧 `cost-comparison` r2 的历史计时保留不变。ABI、原生时钟、剖析 L0 和耐久路径仍不可直接相减；对账不签阶段收据或授予正式比较资格。

### 去除声明重叠运行的 M4 复测

[复测计划 r4](../../results/m4-real-profile-20261120-r4/plan.json)保留 r3 的 ETTm2 ALP、Weather Zstd、ETTm1 XZ 三个精确用例、构建、CPU、28 个试验及配对顺序；除了 `overlap_run` 和由此变化的计划身份，两个计划字段逐项相等。r3 原报告仍带声明重叠，不改写其样本。r4 等其他计时释放协作资源锁后才执行；不声明排除了同机上所有非 TSBench 任务，冻结计划不是新证据。

r4 [报告](../../results/m4-real-profile-20261120-r4/runs/aaa42ccd99bf45bb8021581e21484f20/report.json) 已封账，**28 试验 / 56 方向操作**独立复算与原报告逐字段一致。运行排在 Zstd/XZ 耐久试验封账后、Gorilla 启动前，两端 CPU 记录的声明重叠均为 `null`。[多尺度对账](../../results/m4-real-profile-20261120-r4/profile-link.json)交叉复核 1,008 次 ABI 方向样本及相同 ALP、Weather Zstd 工作；[成本对照](../../results/m4-real-profile-20261120-r4/cost-comparison.json)复核三用例输入、固定帧、构建和执行后端。常规三臂配对不混入容量压力试验；ALP 压力控制的编码/解码分别丢失 2/53 事件。缺失计数与 XZ opaque 部分仍为不可用，不跨时钟相减，也不把本次诊断当成已签发的阶段收据。

[r4 成本对照 v2](../../results/m4-real-profile-20261120-r4/cost-comparison-20261120-r2.json)从封存的前后环境快照生成重叠说明，两端均未声明功能运行重叠；协作资源锁约束 TSBench 提交，不证明主机独占。历史 v1 的重叠文案是常量，仅保留作历史复算，不用于解读 r4。v2 通过 `tools/verify_m4_cost_comparison.py --multiscale-link …/profile-link.json` 重新验证 r4 精确对账及其三个封账引用，关联多尺度 ABI 的 10 个形状、72 个配置×生命周期×方向配对组及 1,008 次方向调用。该对照只在同工作、同 ABI 的匹配轮内计算差值，不把它从原生、剖析或耐久墙钟减去；未测的 codec 内部分配/复制和主机独占不填零。旧报告和原始试验未改写。

### v13 主账本接续核对

[三类剖析的 v13 计划匹配](../../results/m3-primary-full-v13-20261120-r1/m4-plan-link.json)独立复算既有 r4 剖析和成本对照，并核对融合 ALP、原生多线程 Zstd、opaque XZ 三个 work item 的定义、配置和 pristine 原生库字节。r40 与 v13 的整体构建锁不同，不能以整锁相同推断匹配；这里只确认三个代表项的实际依赖。`tools/bind_m4_to_primary_m3.py --m3-run RUN` 还要求主账本已按完整计划封账，核对实际输入范围、帧、恢复和后端/线程；当前 v13 链接仅为 `plan_only_no_runtime_evidence`。历史剖析时钟仍属于 r4 对照，不填入 v13、不做跨计时范围减法，也不签发阶段收据。

主账本尚在执行时，[ALP 已写记录的只读对照](../../results/m3-primary-full-v13-20261120-r1/m4-alp-live-anchor-r1.json)核对 ETTm2 的完整匹配范围、输入、帧和恢复摘要；实际请求 `falp-auto` 走 `falp-avx2`，观测到 51 个 fused vectors，与 r4 剖析锚点一致。此抽查不代表主账本已封存，不能替代同一次完整封账后对 ALP、Zstd、XZ 三项的正式对账。
