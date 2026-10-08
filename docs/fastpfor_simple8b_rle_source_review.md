# FastPFOR Simple8b_RLE 原始 API 初审

对应全量审计第 148 条，来源 `fast-pack/FastPFOR`，commit
`2457e1ed1af35bbf7f4c509c863fa9797e637cb3`，Apache-2.0。
已完成来源冻结、显式 build-only 修复，以及合法 uint32 对象源码 API 的
三档实际执行和独立审计；有界 ABI 的真实共享库功能场景已执行。
有界uint32 C ABI的系统安全/fault和独立审计已通过；
SDK466项、注册、合成uint32五层和80次正式重复已通过独立审计；
完整条目资格仍未通过，其他数据集和数据域尚待验证。
当前阶段和完整证据见 `adapters/fastpfor_simple8b_rle/SOURCE_ADMISSION.md`。

## 定位与分类

真实实现为 `headers/simple8b_rle.h`，保留 `Simple8b_RLE<true/false>` 两个
原 API 配置和 `Simple8b_Codec::Compress/Decompress` 的 kernel。
`src/codecfactory.cpp` 注册 `simple8b_rle`，使用 marked 配置；原仓库
`src/unit.cpp` 与 `src/inmemorybenchmark.cpp` 为后续完整自测和基准行为来源。
`sprintz-lzbench` 带有 `fastpfor/simple8b_rle.h`，其内部 FastPFOR factory
也注册了 marked `simple8b_rle`；但 `_lzbench/compressors.cpp`、
`compressors.h` 与 `lzbench.h` 的独立入口只有 `simple8b`，没有
`simple8b_rle`。必须区分“附带实现/内部 factory”与“实际 benchmark 入口”。

这是 uint32 primitive：selector 1–14 为固定宽度 packing，selector 15
为最多 28-bit count 的 RLE，selector 0 为结束标记。它不是 Timescale 的
Simple8b-RLE，也不直接提供 int64 timestamp Delta/DoD pipeline 或 float codec。
必须分别登记数据域、预处理、header、外部 count 和完整压缩对象开销。

## Benchmark 副本与清单源码的实际差异

已核对只读、clean 的 `sprintz-lzbench` commit
`580c4f085381f31b1ad669525ed04e63cbc385f3`，与清单指定 FastPFOR pin
逐文件保存 Git bytes、相关 factory/benchmark/test 文件和源码 diff。
两份 `simple8b_rle.h` 并非相同实现：benchmark 副本在 RLE 的代价判断中
使用局部 `bits()`（population count），清单版本调用 `util.h` 的
`bits()`（整数 bit length）。selector 表相同，不代表编码选择相同。

`tools/review_fastpfor_simple8b_rle_provenance.py` 已在 CPU2 分别编译并
实际调用两份原 `Simple8b_Codec::Compress`。探针使用对齐的 uint64 输出，
只验证编码行为，没有调用存在已知风险的 decoder 或 marked wrapper。
每份 encoder 执行九个常量输入，**一个场景产生不同 wire**：

- 输入 `[1048576, 1048576, 1048576]`，即三个 `1 << 20`。
- 清单版本输出一个 uint64：`f000000300100000`，selector 15 的 RLE。
- benchmark 副本输出两个 uint64：`d004000000100000`、
  `d000000000100000`，selector 13 的 packing。

因此继续以清单指定的 FastPFOR pin 为算法身份，benchmark 副本仅作有差异的
行为参考；不能直接替换或声称 bitstream parity。完整原始命令、源快照、
compiler dependency、二进制 hash、九组输出和 diff 保存于
`build/source-audits/fastpfor-simple8b-rle-provenance-2/`。
首轮探针因源码闭包漏列 `bitpacking.h` 而编译失败，其记录与 driver 保留于
`build/source-audits/fastpfor-simple8b-rle-provenance/`；修正闭包后另建目录运行，
没有覆盖失败记录。此编码比较**不授予源码安全、自测或五层资格**。

完整阅读 `src/unit.cpp` 后确认：它通过 `factory.allSchemes()` 包含 RLE，
覆盖 b=0–28、长度 0–255 与 128–3968（步长128），另有五个大 Zipfian
数组；输出与恢复 buffer 均预留额外1024 values，并在 encode 后缩小 vector
逻辑长度，不能证明精确容量安全或完整返回长度。`unittest/test_simple8b.cpp`
测试的是 `Simple8b`，不能替代 RLE 自测。
`src/inmemorybenchmark.cpp` 的默认输入是有序、不同的 uint32 integers，
之后调用 `Delta::process`；其 Delta/SIMD Delta 行为必须作为显式 pipeline
参考，不能隐含加入当前 uint32 primitive。补丁完整自测和当前合成范围正式测量
均已实际执行并独立审计；不授予timestamp或float能力。

## 已实际执行的失败探针

`tools/discover_fastpfor_simple8b_rle.py` 在 CPU2 对未改动的原仓库编译
release/debug/ASan+UBSan 三档；只测试 N=1、uint32 零值和 marked/unmarked。
原仓库 pin/clean 状态、八个相关原文件、探针、原始命令、二进制 hash 和日志
保存在 `build/source-audits/fastpfor-simple8b-rle-discovery/`。
该小探针不替代上游完整自测或完整源码闭包审计。

1. marked encode 返回 `nvalue=2` words，decode 消耗三个 words：源 API 的
   returned count 没有包括开头的 uint32 length word。框架若只序列化返回长度
   会丢失对象尾部，计费也会漏掉 marker。现有显式补丁已修正完整返回长度，
   有界封装使用该返回值，marker只计一次。
2. 普通 packing 的 unrolled decoder 每次写八个 output words，即使实际
   `intNum=1`；在 padded 输出中，N=1 之后的七个 canary words 被改写。
   ASan 使用精确一值输出时确认 `heap-buffer-overflow`，原错误栈保留。
3. marked 输出在 uint32 length word 之后把指针转换为 `uint64_t*`；
   基址即使按 16 bytes 对齐，payload 仍偏移四 bytes。UBSan 实际确认
   `store to misaligned address ... requires 8 byte alignment`。
4. source decoder 忽略调用方 compressed length，需继续测试截断、RLE count、
   selector 0、非法结构与独立 count，不能把 debug assert 当作有界合同。

release/debug 在 padded 输出中 inverse 的第一个值正确，但 canary 和
完整长度合同失败；这些返回不能记作安全 PASS。使用 `detect_leaks=0`，
没有 LeakSanitizer 资格声明。所有原失败均保留，不修改共享 `_repos`。

## 本轮已推进的准入与剩余门禁

`adapters/fastpfor_simple8b_rle/` 保留九个原算法文件和七个自测/benchmark
参考文件，原 `_repos` 和 vendor bytes 均保持不变。补丁仅在build应用，
修复uint64 word访问、八值unroll的tail与完整marker返回计数，不改变原位布局。
原encoder两档140,976个wire检查、补丁三档211,464个往返和4,788个精确
guard-page检查通过；补丁完整unfiltered上游unit重新实际执行通过，源码独立
审计PASS。shared library三档共80,784个功能场景也已执行通过。
source/native功能证据不代替有界ABI的坏输入、fault和独立审计。

真正发布库的malformed/descriptor/alias/guard-page矩阵与同发布objects的
异常/坏时钟fault现已三档实际运行，独立native审计PASS，详见准入卡。
SDK、registry、五层资格和正式重复已实际完成；四组共80次，74次统计有效，
6次swap排除仍保留全部原始记录。第148条保持完整资格=false，
工作清单仅记录当前已证明的uint32 VALUE/UTS合成范围。详见准入卡和合同。
