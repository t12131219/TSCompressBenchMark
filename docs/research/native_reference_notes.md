# 原生测量参考与压缩输出边界核查（2026-10-15）

此记录区分已读源码与可采用的方法。没有执行 lzbench 性能测试，没有将外机公开表当成本机结果，也没有确认 TFBench 的对应压缩项目。

## lzbench 的实际实现

本次只读主要参考为 `/home/fzg/PycharmProjects/lzbench`，Git HEAD `3d22c4115e5e99069c30bef00aa4ec59aecd2f66`；下表散列对应此 checkout。另对照 `/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench`，Git HEAD `fa871e66b3543a70fd4d060f7c12719343ff4ac3`。两份 `bench/lzbench.cpp` 字节一致；后者的 `lz_codecs.cpp`／`lzbench.h` 分别为 `3ec09c92122029243308766e74ef87713ff31a710acfd9bce6632d0c89187aaa`／`6bf396727d9a985a8ab1b5062e4448afdbc4760e5d0f5a66da6de0488afe3776`。逐文件对照差异没有修改本次读取的 Zstd／LZ4／Snappy wrappers；不能因此推断全部源码或构建一致。

| 已读文件 | SHA-256 |
|---|---|
| `bench/lzbench.cpp` | `5f19e92fd9855052dad4bac4004092c8d13627c861441aec8dfb09dfc42f86bf` |
| `bench/lz_codecs.cpp` | `f013a716abd44b7d25bd73df3acaceec5f8ab972c0f6e9e113a5691d384da5cf` |
| `bench/lzbench.h` | `ec562970721ee98c380629e9f3130133079573ed4afdeb6db6c8907c8fd891ae` |
| `bench/util.h` | `fbebadc8a2f2f642bc362a0036d4a119ddddde772b8f05810f3084f7066b1620` |

阅读覆盖 `alloc_and_touch`、`lzbench_process_mem_blocks`、`lzbench_process_single_codec`、单线程／线程池的 `lzbench_compress`／`lzbench_decompress`、`print_stats`、`print_speed`、默认参数，以及 Snappy、LZ4、Zstd wrappers。关键事实如下：

- 文件读取、caller buffer 分配和触页先于测量；codec `init` 在重复循环外。`deinit` 在统计后执行。这是 prepared 路径，不是包含完整创建成本的首次请求。
- 同一 C++ 进程内重复执行真实原生 codec 调用，受最小迭代数与最短运行时长共同约束。默认内循环约 100 ms，压缩／解压总运行时长至少约 1／2 秒。
- 解压批次完成后检查返回长度和 `memcmp`，并在主计时外清空输出。原生返回值检查与越界条件仍存在。不能照抄 Snappy wrapper 忽略 `RawUncompress` 的 bool 返回值的行为。
- `print_stats` 默认 `FASTEST`，同时支持 average／median。样本既包括超过 10 μs 的单次测量，也包括 batch elapsed／iterations。新框架应保存每个 batch 的总时长与次数，以同一种样本单位取 median，避免混合两种样本与照搬最短时间默认。
- 普通表格 `Ratio` 是 `100 × compressed / original` 的百分比；`MARKDOWN2` 则显示 `original / compressed`。吞吐以原始 bytes 计十进制 MB/s，不能与 MiB/s 或压缩倍数混名。
- LZ4 wrapper 为 raw block `LZ4_compress_default`／`LZ4_decompress_safe`，不是本工程 `lz4-frame` 的完整 frame。Snappy 为 `RawCompress`／`RawUncompress`。Zstd 复用 CCtx／DCtx，执行 `ZSTD_compress2`／`ZSTD_decompressDCtx`；level、content-size 和线程等仍须匹配。

新实现可采用原生重复、caller buffer/context 复用、完整输出大小、计时外正确性检查。每次独立对象仍必须开始新 frame／清空逻辑历史；prepared 不能继承前一对象的字典。fresh 则另外包含 context 创建、配置、buffer 分配与释放。所有 codec 仍按本工程冻结的实现／参数／构建选项标识，不能因为参考 lzbench 就暗中换成 raw block、关闭 checksum、忽略返回值或引入 `-ffast-math`。

## TFBench 的来源限制

在本工程、`Compression_Source_Code`、其他可读 PycharmProjects 文件列表及相关 README／来源清单中，未找到可确认的 TFBench 压缩基准源码。公开 GitHub 仓库名 `TFBench` 的只读搜索返回 12 个同名结果，内容为 TensorFlow、转录因子等其他领域；进一步的压缩关键词搜索受到 GitHub API 限流。现有证据不能确定用户所指项目，因此未编造其 commit、接口或计时方式，也未复制同名无关项目的默认配置。

## 当前 37 个 CPU codec 的输出分类

以下分类依据当前 bridge 与 native adapter 的实际写出／恢复路径。它是原生入口的资格设计依据，不是通过扣除旧 wire 字节推导的新性能结果。根层 `TSB` wire 的 JSON、SHA、来源和实验身份属于实验记录，不计入新主表的 codec 输出。

| codec／族 | 现有 payload 的性质与新入口需要保留的内容 |
|---|---|
| `zstd-frame`、`lz4-frame`、`deflate-zlib`、`brotli-stream`、`bzip2-stream`、`xz-stream` | 原生完整压缩流／frame，包含原生 header、结束数据与所选 checksum。必须累计 update 和 finalize 写出的全部 bytes，不能只计 update 返回的片段。Zstd／LZ4 首批 direct 入口应显式保持 frame 及原参数。 |
| `snappy-raw`、`lzsse2-raw`、`lzsse8-raw`、`lzss-raw`、`lzss-dipperstein-c` | 原生 raw 输出。Snappy 自带原始长度 varint；其他 raw API 的长度／参数依赖必须在恢复契约中明确。原生必需的 fixed dictionary／初始化规则不能被当成实验 JSON。部分 adapter 在 vendor decoder 前额外扫描合法性，该 ABI 时间不可直接充当原生核心时间。 |
| `chimp`、`chimp128`、`elf`、`elf-plus`、`elf-star`、`self-star` | `tscb_rewrite_lossless.cc` 内嵌 frozen public API 返回的完整 `.bytes`，又外包 `RWF1` 头、每记录 count／length 和 FNV。内层自身恢复必需的 metadata／SElfStar session 历史完整保留；`RWF1` 是适配器集合格式。主原生入口应直接调用 public API，不能把整段 `RWF1` 同名当作 upstream stream；多 block／列的路由或依赖仍需声明。 |
| `abba`、`fabba`、`deepzip`、`dzip` | C++ binding 返回 public API 完整序列化；Python `RwAbiBridge` 再加 `TSBCRW1\0`、列数及长度表。ABBA／fABBA 必须保留字典、中心与恢复参数；DeepZip／DZip 结果中携带的模型必须完整计入。不能把模型仅留在 sidecar 来降低大小。binding 每次 `rw_encode` 又调用 bound，DeepZip/DZip bound 也会加载／创建 model，该 ABI 成本须单列。 |
| `alp`、`alp-rd` | 上游提供编码／FFOR 原语，当前 `ALP1`／`ARD1` 是本工程明确的序列化格式。每组字典、exp／fac／bit-width、FOR base、异常值与位置、逻辑尾长都是真实恢复状态。只有 kernel 的 packed bits 不是完整输出。`TAI1` 输入 envelope 不属于有效输入 bytes，内部 1024 对齐也不能扩大分母。 |
| `serf-qt`、`serf-xor` | 原生 AddValue／Close 流外再包 `SRQ1`／`SRX1`、block 长度／状态重置标识、参数与 FNV，并可能由适配器选择 raw exception block。必须区分 codec 与扩展 scheme；XOR 跨 block 状态不能丢失。不能忽略 fallback bytes／状态或将全部对象称为上游单块原生输出。 |
| `neats-lossless-i64`、`leats-lossless-i64` | 真正上游／reviewed SDSL `serialize` 输出含模型与索引，必须计入，不能使用 `size_in_bits()` 代替保存 bytes。当前 `NTS1`／`LTS1` 又存每列归一化 bias、长度、统计位数与 FNV；若使用归一化，bias 是恢复必需状态，须保存并计费，不能扔到实验记录。 |
| `zfp-accuracy-1d` | 每列 `zfp_write_header(ZFP_HEADER_FULL)`＋`zfp_compress` 返回的完整 ZFP stream 应计入；外层 `ZFA1`／记录表／FNV 属于 adapter，并可能为非有限值采用 raw column。原生入口不能只报 coefficient payload，不能继承 raw exception scheme 的全域支持承诺。 |
| `sprintz-delta`、`sprintz-fire` | `bounded_sprintz.cc` 的 `TSF1` 为 16-byte adapter envelope，里面还有上游 8-byte metadata。后者及原生码流必须保留；`TSI1` 输入 envelope 不计有效输入。不得将 staging／padding 扩大分母。 |
| `sprintz-delta-u8`、`sprintz-fire-u8` | 有上游 8-byte metadata 的原生流，bounded wrapper 负责容量／结构验证与 staging。直接入口的输出、输入长度和 API 返回单位必须核对，不能沿用 envelope 字节数作 raw 分母。 |
| `sprintz-fire-huff0` | 明确的 Sprintz→Huff0 组合格式，包含模式、长度及两级恢复状态；必须按完整组合计费，不与单独 Sprintz/Huff0 默认等同。 |
| `huff0`、`fse` | 上游 entropy API 可返回 raw／RLE／compressed 指示，需要保存分支和原始长度才能独立恢复。现有 adapter 的 9-byte type＋length 是 scheme 编码的一部分；不能只取 vendor 返回长度，尤其返回 0／1 时不能伪造无限压缩／速度。需具名的完整 entropy 格式或明确 unsupported。 |
| `simdcomp-u32` | 原语只返回 packed blocks，不提供完整自描述 codec stream。`TSCBSBP1` 当前存 count、seed、mode、block 几何、bit-width、layout、长度与 FNV。width／seed／尾长等是恢复必需，不应扣掉。现有可选 internal timer 逐 kernel 累加，未含完整 width 分析／序列化／分配，不满足新的主时间边界。 |
| `gorilla-prometheus-xor` | `gorilla::encode` 返回完整 Prometheus raw EncXOR，含 2-byte sample count。Python joint records 外层目录不属于 codec 流。真实 T＋V 输入有效 bytes 必须按原任务去重；多列编码重复 T 的物理工作应保存为辅助输入计数，不能扩大主分母。 |

ALP／Simdcomp／entropy 这类原语若暂未实现可审查的完整原生 driver，应在 `native_core` 保留请求与 unsupported 原因。其已有 `native_api`／`object_memory` 结果仍可保留，但不能仅重命名为 `native_core`。
