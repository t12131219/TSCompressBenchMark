# 指定无损算法重写与 Benchmark 接入审查（2026-10-06）

本轮完成 Chimp、Chimp128、Elf、Elf+、Elf*、SElf* 和 Prometheus XOR chunk 的
独立重写审查/修正与 Benchmark 接入，最终状态为 `COMPLETE_LOCAL_SCOPE`。
DCT、DWT、PCA 按用户明确决定跳过。

开始实现前已完整阅读重写规范 Markdown 和 Excel 五张工作表；输入 SHA-256
保存在 [机器审查报告](requested_lossless_rewrite_review.json)。用户的任务要求授权
Benchmark 接入，规范中的 rewrite-only 边界用于独立包：独立源码、测试和发布包不含
Benchmark adapter，接入代码另放在 `adapters/rewrite_lossless/`。

## 逐项结论

| 算法 / 注册 key | 审查与交付 | 冻结原版 commit | 独立包原版对照用例 / 真实数据组合 | Benchmark |
| --- | --- | --- | --- | --- |
| Chimp / `chimp` | C++17 重写，原版 raw bytes 和双向解码一致 | `320d397157c7e0696b3c64dc1711fc17a3add3da` | 与 Chimp128 合计 224 / 144 | PASS，3 个任务 |
| Chimp128 / `chimp128` | 固定 history 128；保留原版候选拒绝后的 trailing-zero 状态决策 | 同上 | 共用同一独立包与合计证据 | PASS，3 个任务 |
| Elf / `elf` | 采用 VLDB2023 原始分支；审查发现本地 development C++ 变体不能替代该格式 | `386d69348e6c30475761d3519ee0bfe10ed473d3` | 109 / 72 | PASS，3 个任务 |
| Elf+ / `elf-plus` | 修正/复验已有独立实现；保留 beta reuse 与隐含低 XOR 位；拒绝原版非无损恢复 | `64e0d6004be322d9d8eaf9931e371df202f1a0eb` | 92 / 72 | PASS，3 个任务 |
| Elf* / `elf-star` | 重写真正的 block Huffman 算法；保留迭代 decoder，实例拥有 Huffman 状态 | `457ceb0033e98d516fef42e39d17c9d4b8abbfdb` | 109 / 72 | PASS，3 个任务 |
| SElf* / `self-star` | 修正/复验已有独立实现；保留跨块 Huffman、量化和 XOR window 状态 | 同上 | 89 / 72，另含 6 个 network 用例 | PASS，3 个任务 |
| Gorilla、Delta-of-Delta、Second-order Difference / `prometheus-xor-chunk` | C++17 时间戳/数值联合 chunk；未修改原版公共 API 对照 | `8374d30cb3fe705773bbac72d7015eba17480557` | 113 / 43 个完整真实列 chunk | PASS，3 个任务 |

Gorilla 和二阶差分在所给 Excel 中映射到同一 Prometheus 来源，因此三个名称作为
`prometheus-xor-chunk` 的别名，共享 AlgorithmID、配置和来源身份。它们在 SYSTEM/S0
测量完整 T/V 联合流，不增加独立排名条目。没有交付另一个 timestamp-only 或
value-only 格式来替换清单指定来源。

## 独立重写验收

六个独立包的 G0–G6、当前独立 API 资格检查、GCC Release、Clang Release、
ASan/UBSan、静态分析及移目录构建复现均通过。原版 byte equality、双向 cross-decode、
完整独立 frame 的逐位恢复与 FinalBits 检查通过。Elf、Elf* 另各有 28 个源取值域用例，
覆盖零、无穷、NaN、subnormal 和极大/极小数值的原版行为及有界拒绝。

Java 算法的真实数据对照按事先公开的规则选择 ETTh1、exchange_rate、weather 的
前 1000 行，覆盖每个数值列和 binary32/64；Chimp 同时覆盖两个 variant。
这些数字表示列/宽度/variant 组合，不表示全部数据行已与 Java 对照。
完整数据行的 C++ Benchmark 验证另有 21 项任务。

Prometheus 对照使用未修改原版的 `NewXORChunk`、`Appender.Append`、`FromData`
和 `Iterator.Next/At/Err`，覆盖上述三个 CSV 以及 national_illness 的全部行、全部数值列，
共 43 个完整列 chunk，加上 64 个 property vectors 和 6 个 golden vectors。
上游 `tsdb/chunkenc` 包测试通过。Go 1.26.0、模块、公共 API 源闭包及依赖许可证已锁定；
最终证据采用原版公共 API，不以提取版 oracle 替代。

六个 `*-standalone-local.tar.gz` 位于
`Compression_Rewrite/Release/requested-lossless-20261006/`。发布包消费检查验证归档、
manifest、SBOM、源闭包、当前报告和二进制哈希，再从归档解包独立构建，逐字节匹配
全部 GCC 发布产物。此前清理移除了 Elf+、SElf* 源清单中的 26、17 个文件，本轮从
锁定 commit 仅恢复缺失文件并校验原始哈希；源仓库未修改。

## Benchmark 接入验收

七个 C ABI adapter、codec/source manifest、接入卡和 Python factory 已注册。
最终五层运行在 ETTh1、exchange_rate、weather 上通过 VALUE 18 项、SYSTEM 3 项。
预检包括源/构建身份、输入契约、边界、生命周期和容量；同一 repetition 验证逐位恢复、
T/V 配对、输入不变、输出 canary、确定性与物理长度计费闭合。

本轮修正了通用框架中与接入相关的三处契约：SYSTEM 时间戳和数值按角色协商 dtype；
已声明的源域错误仅在精确错误原因匹配且输入/输出未改变时作为边界拒绝通过；
总元素数与 SElf* 每列最多 1024 块的容量在规划阶段检查，超限配置返回 `UNSUPPORTED`。
实际数据的源域失败返回 `SOURCE_DOMAIN_UNSUPPORTED`，不会变成正确性 PASS。

所有计费包含描述符、校验、wrapper headers 和完整独立 frame。standalone frame
保持 opaque：VALUE 计入 `value_bits`，Prometheus 联合 T/V 计入
`unallocated_shared_bits`；不虚拆 timestamp/value bits。Benchmark 采用 `PIPELINE`
计时，包含布局、复制、FFI 和容器开销。E2E 路径有额外接入回归验证；native `CORE`
未注册，选择它会在规划阶段返回 `TIMING_SCOPE_UNSUPPORTED`。

最终相关回归测试 **260 项通过**，包括 adapter、别名、注册表、源接入、角色协商、
容量规划、源域拒绝、PIPELINE/E2E 五层接入及 CORE 规划拒绝。原生 ABI 的七项 ASan/UBSan 检查全部通过。
初次 `final` 运行的边界诊断、`final-v2` 的两项及 `final-v5` 的四项系统换页导致的
`RESOURCE_PRESSURE` 记录保留。最终 `final-v6` 运行 21 项全部 PASS，其身份与哈希
保存在机器审查报告所引用的 Benchmark 验收 JSON 中。

## 适用范围与限制

- DCT、DWT、PCA 跳过；本轮不为它们声明重写完成。
- Elf、Elf+、Elf*、SElf* 保留 `NOASSERTION`，按用户已授权的本地审查/执行/重写例外交付，未对外发布。它不是上游许可授权。
- 保留原版 END/数值域限制；NaN END、无法终止或非无损恢复有界拒绝，未添加 raw fallback。
- 当前声明平台为 Linux x86_64、GCC 11、Clang 14；不声明 ARM、Windows、macOS 已验证。
- ASan/UBSan 通过；沙箱中 `detect_leaks=0`，不声明 leak-clean。
- Benchmark 无 query、random access 或 incremental streaming profile；SElf* 的独立跨块原生状态仍保留。
- 性能运行属于 `QUALIFICATION`，一个 warmup、一个 repetition，记录不进入正式排名。正式排名需要单独的 FORMAL 实验配置和测量。

接入使用说明见 [adapter README](../adapters/rewrite_lossless/README.md)。完整身份与哈希见
[机器审查报告](requested_lossless_rewrite_review.json)、
[Benchmark 验收](requested_lossless_benchmark_qualification.json)、
[原生 ABI 验收](requested_lossless_native_abi_qualification.json) 和
[发布包消费检查](requested_lossless_release_consumption.json)。
