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
