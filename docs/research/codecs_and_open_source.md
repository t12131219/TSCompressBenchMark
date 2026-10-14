# V4 从现有 codec 重建 Python Benchmark：资产与开源源码阅读

日期：2026-10-12。本文为本轮重新读取源码与固定版本联网资料后的研究记录，服务于从零设计的 Python 测量框架。旧 Python 控制面、旧验收流程和旧版本计划不作为新实现依赖。既有 codec 源码、原生 shim、模型和构建配方是可复用资产。

## 1. 证据范围与结论的边界

本轮重新静态核对全部登记、构建目标、两套 ABI、冻结文件和模型。没有编译共享库、执行 codec 或复现上游论文实验。因此下文的“支持”是当前源码/登记声明；迁移到新 bridge 后仍须用真实构建和独立恢复确认。

本轮联网重新下载下列三个项目的固定版本，而不是沿用旧阅读笔记。16 个文件全文阅读，另有 3 个文件按所需函数段阅读；不声称读完三个仓库中全部算法实现。所有实际阅读原文均保存于 [sources/codecs_open_source](sources/codecs_open_source/reading_manifest.json)，清单逐项记录版本、官方 URL、字节数、SHA-256 和阅读行段。

| 项目 | 固定提交 | 已全文阅读 | 仅阅读指定部分 |
| --- | --- | --- | --- |
| [lzbench](https://github.com/inikep/lzbench/tree/9ca711ce574d1ac56b803db4292b8797283575b3) | `9ca711ce574d1ac56b803db4292b8797283575b3` | `README.md`，`bench/lzbench.cpp`，`bench/threadpool.cpp`，`bench/threadpool.h` | `bench/lzbench.h:1–166`，包括计时、选项与能力类型 |
| [ALP](https://github.com/cwida/ALP/tree/31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce) | `31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce` | `README.md`，`how_to_benchmark_your_dataset.md`，`BENCHMARKING.md`，`benchmarks/bench_your_dataset.cpp`，`benchmarks/benchmark.cpp`，`benchmarks/include/benchmark.hpp`，`benchmarks/test_compression_ratio.cpp` | `benchmarks/fls_bench/fls_bench.hpp:515–776`，时钟实现段 |
| [TerseTS](https://github.com/cmcuza/TerseTS/tree/64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0) | `64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0` | `README.md`，`bindings/python/README.md`，`src/tersets.zig`，`src/capi.zig`，`bindings/python/tersets/__init__.py` | `src/tester.zig:330–620,1080–1188`，恢复检查、生成测试及随机种子 |

GitHub commit API 本轮受到公开接口访问频率限制；lzbench、ALP 采用已明确的固定提交原始 URL 重新获取，TerseTS 经 `git ls-remote` 获取提交后下载固定提交 ZIP。下载方式不影响文件哈希固定，但不应把所选两个提交说成下载时的最新 HEAD。

## 2. 本轮现有 codec 资产核对

当前根登记有 **36 个真实 codec key、4 个框架 oracle**，另有 `lz77 → deflate-zlib` 别名。对 `tools/build_codec.py` 的 AST 核对得到相同的 36 个真实构建目标。36 个 key 包含算法变体、实现和一个 bit-packing primitive，不是 36 种互相独立的时序压缩算法。

本轮工作区没有 `build/` 目录，36 个 manifest 指向的共享库全部不存在。可复用的是源码、shim、模型与构建配方，不能把历史完成声明当作新框架已运行的 PASS。

| 重新计算 SHA-256 的资产 | 文件条目 | 结果 |
| --- | ---: | --- |
| 六个无损重写包：Chimp、Chimp128、Elf+、SElf*、Elf、Elf* | 46 | 全部存在且与冻结清单一致 |
| 四个 completed rewrite 包：ABBA 35、fABBA 27、DeepZip 38、DZip 1115 | 1215 | 全部存在且与冻结清单一致 |
| DeepZip `.dzm` 模型 | 17 | 全部存在且哈希一致；全部模型 `alphabet_size=4` |

两类冻结清单合计核对 1261 条文件，模型另列。机器库存保存于 [local_codec_inventory.json](sources/codecs_open_source/local_codec_inventory.json)，包括 40 份登记的原始身份、输入、生命周期、执行能力、参数和 artifact 存在性。哈希一致证明资产完整，不能证明新构建的恢复正确性或实际性能。

### 2.1 全部 36 个真实 key

下表中 `B` 指按原始字节压缩数值数组，需要额外保存 dtype/shape 等恢复信息；`U/M` 指单变量/同步多变量。`C1` 指现有 `tscb_*` ABI，`RW1` 指 completed rewrite 的 `rw_*` ABI。“当前实现”不代表上游算法理论上只有这些能力。

| key | 输入与对象 | ABI / 当前实现 | 新 bridge 最需要保留的行为 |
| --- | --- | --- | --- |
| `lz4-frame` | B；U/M；1–4D | C1；CPU scalar 单线程 | LZ4 frame、typed descriptor、stream finish |
| `zstd-frame` | B；U/M；1–4D | C1；CPU scalar 单线程 | Zstd frame、checksum、typed descriptor、finish；无已接通内部多线程 |
| `snappy-raw` | B；U/M；1–4D | C1；CPU scalar 单线程 | 单次 compress；一次零字节 finalize；raw payload 外需要精确恢复长度 |
| `deflate-zlib` | B；U/M；1–4D | C1；CPU scalar 单线程 | RFC1950 包装、level/window；`lz77` 仅是别名 |
| `brotli-stream` | B；U/M；1–4D | C1；CPU scalar 单线程 | 当前 builtin dictionary；FINISH 至结束 |
| `xz-stream` | B；U/M；1–4D | C1；CPU scalar 单线程 | XZ 最终流、preset/filter/check；CMake 构建 liblzma |
| `bzip2-stream` | B；U/M；1–4D | C1；CPU scalar 单线程 | block level、stream end 与 descriptor |
| `lzss-raw` | B；U/M；1–4D | C1；C++17 单线程 | EI/EJ/initial byte；严格流检查和 decoded length |
| `lzss-dipperstein-c` | B；U/M；1–4D | C1；C 单线程 | offset/length bits、初始窗口、match finder 与位流尾部 |
| `lzsse2-raw` | B；U/M；1–4D | C1；SSE4.1 单线程 | 原生 raw 格式、decoded length；不允许虚构 scalar 路径 |
| `lzsse8-raw` | B；U/M；1–4D | C1；SSE4.1 单线程 | 同上；单独记录 LZSSE8 变体 |
| `fse` | B；U/M；1–4D | C1；CPU scalar 单线程 | 熵编码 block 与 RAW fallback；小对象上限 |
| `huff0` | B；U/M；1–4D | C1；CPU scalar 单线程 | Huff0 block 与 RAW fallback；小对象上限 |
| `alp` | f32/f64；U/M；按列 | C1；CPU scalar 单线程 | 当前强制 decimal 分支；并非上游自动 ALP/ALP-RD 选择 |
| `alp-rd` | f32/f64；U/M；按列 | C1；CPU scalar 单线程 | 当前强制 RD 分支；完整字典、exception 和 tail |
| `chimp` | f32/f64；U/M；按列分块 | C1；CPU scalar 单线程 | 冻结 API 完整 frame；源实现 NaN END 范围拒绝 |
| `chimp128` | f32/f64；U/M；按列分块 | C1；CPU scalar 单线程 | history=128 的独立变体；源实现 NaN END 范围拒绝 |
| `elf` | f32/f64；U/M；按列分块 | C1；CPU scalar 单线程 | 源实现 END/decimal recovery 限制；不能静默替换成 raw 算法 |
| `elf-plus` | f32/f64；U/M；按列分块 | C1；CPU scalar 单线程 | 冻结 frame 与真实 domain rejection |
| `elf-star` | f32/f64；U/M；按列分块 | C1；CPU scalar 单线程 | significance/scale/beta/recovery 的源实现范围拒绝 |
| `self-star` | f32/f64；U/M；列内跨块状态 | C1；CPU scalar 单线程 | 每列 session 状态；最多 1024 块；不能外部切块后无名重置 |
| `neats-lossless-i64` | signed i8/i16/i32/i64；U/M | C1；CPU scalar 单线程 | `max_bpc`、精确恢复、n/m/总字节上限 |
| `leats-lossless-i64` | signed i8/i16/i32/i64；U/M | C1；CPU scalar 单线程 | 同上；与 NeaTS 分开列出方法变体 |
| `sprintz-delta-u8` | u8；U | C1；AVX2/BMI2/LZCNT 单线程 | lowdim 安全 patch、header、exact tail |
| `sprintz-fire-u8` | u8；U | C1；AVX2/BMI2/LZCNT 单线程 | 同上；FIRE 状态从解码序列恢复 |
| `sprintz-delta` | i8/u8/i16/u16；U/M 联合矩阵 | C1；AVX2/BMI2/LZCNT 单线程 | row-major 联合流；禁止默默把 float 量化成整数后称原数据无损 |
| `sprintz-fire` | i8/u8/i16/u16；U/M 联合矩阵 | C1；AVX2/BMI2/LZCNT 单线程 | 同上；记录实际 ISA |
| `sprintz-fire-huff0` | i8/u8/i16/u16；U/M 联合矩阵 | C1；AVX2/BMI2/LZCNT 单线程 | 两阶段完整成本与 Huff0 fallback |
| `simdcomp-u32` | u32；U；bit-packing primitive | C1；SSE4.1/AVX2 单线程 | LENGTH/MASKED/WITHOUTMASK 区分；AVX2 不支持 LENGTH；并无 Delta/FOR 前处理 |
| `serf-qt` | f32/f64；U/M；按列有损 | C1；CPU scalar 单线程 | absolute error 参数与完整 block 恢复 |
| `serf-xor` | f32/f64；U/M；按列有损 | C1；CPU scalar 单线程 | absolute error、adjust digit 与自适应 XOR 状态 |
| `zfp-accuracy-1d` | f32/f64；U/M；每列 1D 有损 | C1；serial CPU | fixed accuracy、FULL header；不是当前已接 GPU ZFP |
| `abba` | 有限 f64；U/M；按列近似 pipeline | RW1；CPU scalar 单线程 | 两类 tolerance、聚类参数、原始网格；无通用逐点误差界 |
| `fabba` | 有限 f64；U/M；按列近似 pipeline | RW1；CPU scalar 单线程 | 当前 native binding 强制 `threads=1`；无通用逐点误差界 |
| `deepzip` | u8，符号 0…3；U/M；按列 | RW1；CPU scalar 单线程 | 模型和 lanes；模型在完整帧内计费；真实模型读取/解析开销 |
| `dzip` | u8；U/M；排序字母表 | RW1；x86 AVX | 输入 9 符号字母表拒绝；调用线程及两个持久单 worker Eigen pool；模型完整帧内计费 |

现有资产没有一个覆盖所有 timestamp/value 联合存储语义的完整系统 codec；timestamp-only 集合也不齐。因此首先形成“给定数组对象的压缩恢复”基准，再把 timestamp、value、joint 或显式组合 pipeline 作为不同问题。不能将数值 byte codec 或 SIMDComp primitive 直接当作完整时序存储系统。

### 2.2 上限、单位和模型参数

新 bridge 的静态检查需要同时满足原生 API 和恢复容器约束。登记中的 `max_n`、`max_m`、`max_total_raw_bytes` 不应替代 checked `prod(shape) * itemsize`，更不能把行数上限误当总字节上限。

| 资产 | 必须显式处理的限制 |
| --- | --- |
| FSE/Huff0 | n≤8192，m≤64，整个输入 raw bytes≤131072 |
| NeaTS/LeaTS | n∈[1,65536]，m≤64，raw bytes≤2097152 |
| Sprintz matrix | n≤131072，m≤128，支持的整数 dtype；Huff0 pipeline 额外 raw bytes≤122880 |
| SElf* | `block_size≤1000`，每列最多 1024 块，n≤1024000；跨块 state 要保留 |
| ABBA/fABBA | 有限 f64、n≥2、总元素≤16777216、raw bytes≤134217728；端点算术异常应具名拒绝 |
| DeepZip | 本地 17 模型 alphabet 都为 4；native 默认 input≤16 MiB、model≤64 MiB、lanes≤4096。binding 的通用读模型上限 512 MiB 不会放宽 native model limit |
| DZip | native 默认≤16 Mi symbols、model≤512 MiB、frame≤600 MiB；mode/seed 和输入字母表决定真实执行 |
| SIMDComp | 仅 u32 单列；API/ISA 有交叉约束；tail、starting point 与实际 count 属于恢复所需元数据 |

旧参数 `block_size` 有多种含义：Python update 字节数、codec 内部行块、算法几何块或状态边界。新框架应分开 `chunk_rows`（harness 的独立归档切块）与 `codec_params`（有单位的算法私有参数）；不能给全部 codec 下发一个共享 `block_size=65536`。

若因为输入上限将一个 whole-object 算法变成独立分块 pipeline，必须命名为显式变体，保存块目录并把其长度计入 archive。线程缩放测试固定同一块划分；线程数变化不能顺带改块数、压缩率和算法状态。

### 2.3 两种 ABI，统一小协议放在 Python 层

32 个真实 key 使用 [C ABI header](../../native/include/tscb_adapter_v1.h)。`tscb_buffer_v1` 描述 host 地址、capacity/used、dtype、rank、shape/stride、alignment 和 ownership。header 支持 rank≤8 不等于每个 codec 支持 8D。它没有 GPU address space 或 stream 字段，device pointer 不能冒充 host buffer。

C1 生命周期包含 create/reset、compress_bound、compress、finalize、decompress、destroy。不同 codec 有流式或 whole-object 行为，新 bridge 必须消化这些差异。Snappy 的 shim 只能执行一次 compress，一次成功的 finalize 输出 0 字节；解码要求 output capacity **恰好**等于 raw decoded length，并检查 Snappy buffer。它适合作为第一个闭环，但不能把同一 handle 直接重复 compress 计时。

通用 header 只给 `tscb_finalize(handle, output)` 的签名，未统一规定 append、完整重写或无输出；每个 bridge 必须核实返回码、`used_bytes` 和缓冲区位置，不能机械追加所有 finalize 输出。已核实 [Zstd](../../adapters/zstd_frame/native/tscb_zstd_frame.c) 与 [LZ4](../../adapters/lz4_frame/native/tscb_lz4_frame.c) 输出 frame 末尾片段，Snappy/ALP/无损重写输出 0 字节，[XZ](../../adapters/xz_stream/native/tscb_xz_stream.c) 的 single-call compress 已写 block/index/footer，finalize 也输出 0 字节。现有 Zstd/LZ4 C1 还明确限制一次 compress update，不能因上游库有 streaming 功能就默认该 shim 可以多次 push。容量不足后的重试可能已改变 native state，应按具体 API 处理或 reset 后完整重编码。

4 个 completed rewrite 使用 [RW1 header](../../adapters/completed_rewrites/native/binding.hpp) 和 [binding 实现](../../adapters/completed_rewrites/native/binding.cpp)：`rw_bound/rw_encode/rw_decode`，及模型 alphabet 查询。`RwConfig` 是 `rows/columns/a/b/c/d/seed/mode/x/y/z/model`，这些通用字段由各 codec 分别解释。该 ABI 本身没有 create/reset/finalize 生命周期，旧 Python wrapper 的单 update 和零字节 finalize 是控制面逻辑，不应写成上游 API 强制规则。

`rw_encode` 内部再次调用 bound；DeepZip/DZip 的 bound 与 encode 都读取/构建模型。以现有 bridge 计时，模型读取/解析实际处于 encode 调用内。若后来增加 resident-model backend，应给它新的 backend ID，分别声明准备时间和 steady-state；恢复必须的模型仍计入存储。

`rw_decode` 得到内部 vector 后才比较 caller capacity；capacity 检查不等于峰值内存上限。新 envelope 需要在 native 调用前校验尺寸与字节预算，worker 还应有超时/资源预算。容量不足的 native return 3、异常 return 4 不能统统归为 unsupported。

阅读时的旧 completed 构建脚本已清理；[新构建配方](../../benchmark/src/tsbench/build.py)同样明确将 `DEEPZIP_WITH_CUDA`、`DZIP_WITH_CUDA`、HDF5 设为 OFF。DZip 的 [cpu_ops.cpp](../../adapters/completed_rewrites/vendor/dzip/src/cpu_ops.cpp) 有两处 `thread_local Eigen::ThreadPool(1)`，构建用 `-mavx`。设置 `OMP_NUM_THREADS=1` 不会令这两个 worker 消失。独立包里有可选 CUDA 源码不等于本地已接入 GPU。

[六无损重写共享 shim](../../adapters/rewrite_lossless/native/tscb_rewrite_lossless.cc) 的 `call()` 持有全库 global mutex，并把 encode/decode 包在锁内；同一进程、同一 codec 共享库内不同 handle 的线程调用仍会串行，分别构建的不同 codec 共享库不因这段代码共用同一把锁。因此进程 executor 是这组资产外部并行的可行起点。若后来修改 shim 的锁粒度，应作为新的 bridge/构建变体重新确认线程正确性，不能将“ctypes 放开 GIL”当成实际并行的充分证据。

原生 shim 编译无需旧 planning/statistics/reporting 控制面，但旧 Python wrappers 引入 accounting/contracts/protocol/ids，completed wrappers 还引入 planning。新运行时不直接 import 这些 wrapper；仅参考其 typed packing、参数映射、native format 和材料化逻辑，重写小 bridge。

## 3. lzbench：基本路径很短，计时和归档仍需重新定义

完整阅读主 runner 后，实际主线是：读文件→分配 buffer/workspace/init→重复压缩→对最后压缩结果重复解压→长度与 `memcmp` 检查→输出结果。通常用户只需文件、算法、level 和重复选项，适合借鉴其简单入口。[runner:516 起](https://github.com/inikep/lzbench/blob/9ca711ce574d1ac56b803db4292b8797283575b3/bench/lzbench.cpp#L516) 是核心证据。

其默认压缩最短 1 秒、解压最短 2 秒，inner loop 约 100 ms；单次时长≥10 μs 会保存，loop 平均值也会加入，默认 statistic 是 FASTEST，最终原始向量会清空。它的统计口径服务于工具，不是保留全部独立实验 trial 的论文协议。新框架可借鉴按时间校准 batch，必须保存未汇总的 trial/batch 数据和所用 statistic。

每个解压 inner loop 只检查最后一次输出，压缩循环只把最后产物提供给解压。这保证常用路径有恢复检查，但不保证每次成功计时调用都产出正确对象。新框架需明确每个测量 trial 内的校验覆盖；重复小对象时可在各 encode/decode 调用结束后暂停计时验证，但不能无说明只检查最后一次。

`-T` 是框架外部线程，`-I` 是 codec 内部线程。线程池创建在计时外，enqueue/wait 在计时内。README 的多线程示例固定 4 MiB block；runner 在 `-T` 且未给 `-b` 时会按 `ceil(insize/threads)` 决定块，随后 codec `max_input_size` 还能再切块。新 scaling 比较固定切块，分别标识 external worker 和 internal thread；没有支持的路径不能静默退回一线程。

多线程 output 按每块 capacity slot 放置，reported compressed length 是各块实际 payload 的和；块长度数组保留在进程中，没有打包为可独立恢复 archive。[MT encode/decode:359–444](https://github.com/inikep/lzbench/blob/9ca711ce574d1ac56b803db4292b8797283575b3/bench/lzbench.cpp#L359) 是该布局证据。新项目需保存紧凑 payload 和完整 directory/header，不应把 capacity 空隙当存储，也不能漏掉恢复目录。

runner 同进程执行各算法，原生 crash 不能隔离。缺 codec/file/init 等路径可以跳过，shell exit 0 也不证明全部候选都有结果。论文实验需要 candidate coverage 和具名失败行。Linux 主时钟是 CLOCK_MONOTONIC，macOS/Windows 各用平台高精度时钟；这支持用共同 wall-clock 主计时，CPU cycles 留作同环境诊断。工具的随机 seed、最快结果筛选、高优先级行为不应无条件变成论文默认配置。

## 4. ALP：用户入口和复现入口分开，微基准不等于完整对象吞吐

[用户数据接入文档](https://github.com/cwida/ALP/blob/31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce/how_to_benchmark_your_dataset.md) 使用五字段 CSV，论文复现由 [BENCHMARKING.md](https://github.com/cwida/ALP/blob/31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce/BENCHMARKING.md) 提供独立入口。这种分离符合轻量框架的目标：普通实验不必经过完整论文或发布验收。

`bench_your_dataset.cpp` 只有 GTest 入口，实际 speed/ratio 位于 `benchmark.cpp`。speed 复制首个 **1024 值向量**，Release 固定 30000 次内核循环、Debug 1 次；初始化、采样和 ALP/ALP-RD 选择在循环外，报告 `cycles/(1024*iterations)`。[源码:56–144](https://github.com/cwida/ALP/blob/31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce/benchmarks/benchmark.cpp#L56) 因而是 cache-resident microbenchmark，不是整个列的 finalized archive 压缩吞吐，也不是 30000 个独立 trial。

ratio 入口使用整列，但 `n_vecs=floor(n/1024)`，按 metadata 估计 bits/value，包含若干 header、exceptions 和 RD dictionary 项；并不生成一个可按物理文件长度核算的最终 archive。文档明确 dry ratio 不保存 compressed output，速度测量是 1024 值 micro，正确性另有可执行入口。新框架以完整归档长度和 host array→archive→host array 主计时为主，允许另列 micro kernel 结果。

固定源码有两个值得防止移植的边界：多 rowgroup 情况最后一组使用 `n_vecs % 100`，当完整向量数恰为 100 的倍数且 rowgroup>1 时可能遗漏最后完整组；decimal 整列路径的恢复 assertion 被注释，RD 路径则检查。首向量 speed 函数本身也未见 data<1024 的长度保护。本轮未执行这些入口，也未全文读取 loader，不据此判断上游论文结果错误；这里只把它们转化为新容器必须覆盖 exact multiple、short input、tail 和逐路径恢复的设计要求。

`ALP_ASSERT` 对 NaN 只检查双方都是 NaN，单独检查 minus zero，其他用 `==`；这不是全部浮点位模式的比较。新 lossless 合同需 dtype/shape/count 与原始字节一致，包括 signed zero、NaN payload，或明确宣布更弱的语义模式和不可比范围。当前本地 forced decimal/RD scalar 与上游 automatic ALP 必须分别命名。

所读 fls clock 在 x86 使用 rdtsc，在 Apple 使用 kperf，其他平台有不同 counter/fallback；cycles/value 不能作为跨机器共同的物理单位。上游 Scalar/SIMD/auto-vectorized 列分开值得保留，主表共同使用 wall time 和 raw bytes 或 values 的明确定义。

## 5. TerseTS：小库接口很好用，但不应当作完整公平测量器

TerseTS 是 Zig 时序压缩 framework/library，提供多语言绑定，README 标为 beta。本文审计它的库与 Python/C 接口；EDBT 2026 demo 论文由另一份 [论文与工作负载笔记](papers_and_workloads.md) 记录本轮四页全文阅读，源码结论与论文描述分别核对。

原生主接口 `compress(f64 slice, Method, JSON) → byte array`、`decompress(bytes) → f64 slice` 很紧凑，[src/tersets.zig](https://github.com/cmcuza/TerseTS/blob/64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0/src/tersets.zig#L120) 把 method ID 放在最终 1 字节。empty→empty；single-value 请求任何 method 都采用 Uncompressed。因此新结果需记录 requested 和 actual 方法，以及归档实际 fallback，而非只保留用户请求的名字。

Python 输入仅 contiguous float64 可以直接借用 buffer；其他 ndarray 自动转成 float64，按 `.size` 展开而不保存原 shape。该用法方便库用户，但标准比较必须把 dtype、layout、shape 和输入变换作为显式实验定义，不能让 binding 暗中把 f32/integer 变成 f64 后仍称同一输入。

C API 返回 native allocator 所有的内存并要求配对 free；`toOwnedSlice` 可能重分配。Python 复制 native output 成 NumPy/Python 所有内存后释放原 allocation。README 的简短描述与当前 NumPy 安装后返回的 ndarray 类型也有差异。若主计时边界是 Python array↔archive，这些必要 allocation/copy/materialization 都属于成本；device/kernel 辅助时间另列。

extract/rebuild 仅对一部分近似算法成立，并非所有 codec 共有操作；不能把 query 或解释能力做成每个 baseline 的准入条件。在已全文阅读文件中未发现统一的 benchmark 计时、repetition 和统计 runner，应借鉴它的接口而自行编写实验调度。

`expectExactRoundTrip` 使用 u64 bitcast 对 f64 检查，是良好的 lossless 验证参考。但另一些 generated 检查先把绝对差转换成 f32，error-bound helper 用首尾差加 0.5 作为 range proxy；并非严格 bitwise 无损或真实 min/max range 合同。默认随机种子来自毫秒时间，失败日志会输出 seed。新 fixture 的 seed 应在配置中固定、原始结果中保存，不能直接照搬这些质量检查。

## 6. 第一批可实现的小接口与迁移顺序

### 6.1 Python 对外协议

第一版以 CPU host ndarray 为对象，接口可以很小；GPU 后续单独增加 device/stream/synchronization backend。下面是设计草图，存储路由和边界检查需要具体实现：

```python
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
import numpy as np

@dataclass(frozen=True)
class CodecSpec:
    codec: str
    backend: str
    params: Mapping[str, Any]

class ObjectScheme(Protocol):
    def encode(self, values: np.ndarray) -> bytes:
        """完整、可独立恢复的 archive；每次调用产生独立对象。"""
    def decode(self, archive: bytes) -> np.ndarray:
        """只依赖 archive 和已安装 decoder，不依赖原数组或编码模型路径。"""
```

factory 创建带配置的 encoder；decoder 按 archive 的 format/backend 版本选择，所有恢复参数来自归档。两套 native ABI 放在两个具体 bridge 内，不要求 RW1 伪造 C1 session。每个 bridge 输出完整 archive，保存 dtype、byteorder、shape、layout、原始长度、每块/列目录、codec 恢复参数与 native payload。已有 native frame 内嵌模型/字典则不重复嵌入；任何外部必需对象要改成明确且计费的共享部署模式。

C1 的 decode buffer shape/dtype 和必要 create options 从 archive 的 wire metadata 得到，不读取之前 encoder 的 Python 对象状态。RW1 的内嵌 frame 已带恢复模型，不再把原始模型文件加第二次。executor/factory 可管理 session 和 close，无需把 native 生命周期逐项扩张到两个方法的 public protocol。

`stored_bytes=len(archive)` 是第一版单对象模式的存储成本。论文若比较共享模型部署，另外记录 distinct model bytes、实际共享对象数、摊销规则和 cold start；不能把模型免费视作 warm cache。input、output 和 envelope 长度按 checked arithmetic 校验，资源限制在 native 调用前检查已知尺寸并由 worker 控制运行。

### 6.2 主计时边界

主计时为 host decoded array→完整 archive 和完整 archive→Python 所有的 decoded array。一次 encode 包括必要 reset/update/finalize、typed packing、bound/allocation、容器封装和必要拷贝；decode 包括容器解析、native decode、reshape 和必要材料化。dataset 加载、library loading、worker 启动、结果校验与报告写出在该计时外。codec 若在调用内部读模型或创建工作区，现有真实开销仍在主计时内，不能靠文档声明将其移出。

模型 preparation 或可复用 workspace 可在特定 backend 的 setup 中完成，但其范围和耗时另记。主时钟先用 Python `perf_counter_ns`；不减掉未经稳定建模的 Python/call overhead。对极小对象采用已声明的 batch，但所有调用产物须有校验覆盖，batch 平均值与独立 trial 不能混为一种重复。

native timing、CPU cycles、RSS、GPU event/device-only、query 和 profiler 都是额外实验列；默认主计时无需 collector 准入。固定算法不因 timer batch 校准就必须留出训练集，只有基于数据挑参数、模型或方法时使用独立 development 数据。

### 6.3 最小闭环顺序

| 次序 | 资产 | 此步验证的问题 |
| ---: | --- | --- |
| 0 | Python identity-copy oracle，仅开发使用 | dtype/shape、完整 envelope、原始 JSONL、worker 和独立 decoder 路由；不进入算法榜 |
| 1 | `snappy-raw` | 第一个 C1 whole-object lifecycle；一次 encode/finalize；精确恢复 buffer 与完整存储成本 |
| 2 | `zstd-frame` | streaming update→finish；多个 payload 片段合为完整 frame；独立恢复 |
| 3 | `chimp` | 真实浮点无损、column/block 目录、NaN/END 域拒绝与 signed zero 位恢复 |
| 4 | `serf-qt` | absolute-error 合同、完整重建网格、有损实际质量与失败记录 |
| 5 | `sprintz-fire` | 整数矩阵、真实 SIMD ISA、输入限制、column coupling、tail |
| 6 | `abba` | 第二套 RW1 ABI、完整近似 pipeline、非逐点有界 tolerance 语义 |
| 7 | `deepzip` | 限制词表、模型完整成本、setup 与 encode 的真实边界 |
| 8 | `dzip` | AVX、持久线程、资源预算与模型状态；在线程报告可靠后再接 |

每步只构建该 codec，用新 bridge 验证完整 encode/decode，再从新的进程只拿 archive 与 decoder 恢复。lossless 检查 dtype/shape/count/原始字节；有损检查明确的 quality contract 和实际指标。成功后加相应 regression fixture，再扩充重复测量和数据集。只有影响 native 正确性、格式和执行条件的变化重做相关 qualification；重渲染报告不使执行失效。

所有已完成资产可以逐项迁入新协议，无需首批就跑完全部 codec×数据集×线程×ISA×设备组合。不支持的环境、受限输入、恢复错误、native crash、超时与 OOM 均保存具名结果，分母按预定候选记录。退出或 BLOCKED 算法不因新框架设计自动复活。

### 6.4 独立新 package 与 executor 扩展的实际风险

`benchmark/src/tsbench` 独立 package、两方法 `ObjectScheme`、保留两套 native ABI 且不复用旧 Python adapters 的选择可实现。它能把运行依赖缩到 codec bridge、数组、容器和测量器，但以下边界须在首批闭环里解决：

| 风险 | 源码依据 | 实现约束 |
| --- | --- | --- |
| “统一 ABI”掩盖真实 typed packing | ALP/Serf/无损重写的 native input 包含自己的 typed metadata；C1 不是全部直接接 ndarray 指针 | 每个 bridge 重写具体 packing/parser；用 roundtrip 验证 shape/dtype/layout |
| 两方法接口共享隐藏 encoder state | C1 handle 有 updated/finalized 标志；RW1 decode 不接编码配置 | 独立 decoder 新进程只读取 archive；不得靠 encoder handle/config/model path 恢复 |
| 全库锁限制线程 scaling | 无损重写 `call()` global mutex | 明确进程/线程/internal-thread executor；首批外部并行使用进程，不声称线程一定加速 |
| process/IPC 拷贝混入 wall time | executor 传 ndarray/bytes 需要 serialization 或 shared-memory transport | 调度与 IPC 放在已声明边界；主 object time 与完整 pipeline time 单独列，不静默混合 |
| 重用 native artifact 路径失效 | 本轮不存在共享库；manifest 路径含旧运行目录 | 新 package 的构建输出和载入路径自己配置；逐 codec 重新构建、核对依赖与 ISA |
| 外部分块改变算法 | SElf* session、Sprintz matrix、ABBA whole-object 有不同 state/coupling | `chunk_rows` 命名显式 variant，容器保存独立块；固定对象划分做 scaling |
| GPU 接口提前假装通用 | C1 无 device address-space/stream，当前 neural CUDA OFF | GPU executor 使用独立能力协议；同步、传输和 device-only 计时明确区分 |
| 两方法接口没有表达 amortized setup | DeepZip/DZip bound/encode 均构建模型 | setup 由 executor/backend 管理并另报；默认既有 bridge 实际工作仍留在 encode |

public protocol 可以保持小；这些约束放在 concrete bridge、archive wire format 和 executor contract 中，不需要变成每次 trial 的重复完整验收。

## 7. 给主计划的具体约束

1. 第一版 public protocol 至少有 C1/RW1 两个 bridge，不能宣称现有 codec 已统一原生 ABI。
2. 第一配置示例优先 `snappy-raw` 或 `zstd-frame`，使用实际 codec key 和私有参数；不使用不存在的通用 `threads/block_size` 能力。
3. 按 Python 全路径 wall time 形成共同主表；上游微基准只能作为明确额外表，不以其性能值代替本地后端结果。
4. standalone archive、恢复正确性、有损质量、完整费用和失败分母是主线；profile、query、论文复现、发布验收各有独立入口。
5. SIMD 和多线程必须绑定真实实现/构建；GPU 作为后续真实 device backend，不把当前 host ABI 说成可直接支持 device pointer。
6. 此资产核对不生成执行资格缓存，不宣称 36 个 codec 本轮可运行；实际迁移阶段逐个 build 和恢复。
