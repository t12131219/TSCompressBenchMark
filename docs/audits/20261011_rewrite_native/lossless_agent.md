# 六项已接入无损重写审计（2026-10-11）

范围：当前 `REWRITE_LOSSLESS_CTYPES_V1` 注册的 Chimp、Chimp128、Elf、Elf+、Elf*、SElf*。Prometheus XOR 已不在当前 registry，因此不计入。源码、注册和历史证据均未修改；仅新增本目录的审计文件。

结论：这六项可以判为**在冻结版本、声明输入域和已验证 Linux x86_64 平台范围内，重写成功且执行核心为原生 C++**。没有发现原Java JVM参与生产编码/解码、raw fallback、把 SElf* 误降为独立块、以 Elf+ 冒充 VLDB2023 Elf 的情况。原作语言是 Java，C++ 是翻译实现，不能将“原生 C++ 执行”解释成“原作者发布的 C++ 原版”。测试证据是有限用例，不构成任意 IEEE 位模式、所有平台及全部上游应用功能的普遍证明。

| 当前算法 | 冻结上游 | 实际验证内容 | 本次当前 C++ CLI 回放 | 结论 |
|---|---|---|---:|---|
| chimp | panagiotisl/chimp 320d3971 | binary32/64 原始比特流一致、原Java/C++双向cross-decode、边界/历史/IEEE分支 | 112/112 | 支持域内成功；原生C++核心 |
| chimp128 | 同上，ChimpN历史长度严格128 | 同上；不是64-entry近似变体 | 112/112 | 支持域内成功；原生C++核心 |
| elf | Spatio-Temporal-Lab/elf 386d6934，VLDB2023版本 | 每值erasure/beta，无beta reuse，完整significant XOR；binary32/64双向cross-decode | 109/109 | 支持域内成功；原生C++核心 |
| elf-plus | Spatio-Temporal-Lab/elf dev 64e0d600 | beta复用、implicit low XOR bit；82有效无损 +8 source-domain拒绝 +2 NaN END用例 | 82/82有效无损 | 支持域内成功；原生C++核心 |
| elf-star | Spatio-Temporal-Lab/SElfStar 457ceb00 | 独立块Huffman、Java heap tie与post-office表、binary32/64 | 109/109 | 支持域内成功；原生C++核心 |
| self-star | 同上 | 跨块保存Huffman/window/自适应表，含48块分布变化与每列3000行三块 | 89/89 | 支持域内成功；原生C++核心 |

合计 **613 个有效无损用例全部通过**。此处没有把 Elf+ 的10个源域拒绝/END用例当成10个成功无损编码用例。

## 原生执行和原作语义证据

- [build_codec.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/tools/build_codec.py:1032) 校验 `FROZEN_APIS.json` 的文件SHA后，以 `c++ -std=c++17 -shared` 编译C ABI wrapper和各冻结 `src/codec.cpp`，并关闭fast-math/FP contraction。生产adapter没有Java调用。
- [C++ adapter](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/rewrite_lossless/native/tscb_rewrite_lossless.cc:74) 的encode按算法分派到真正 `chimp::compress`、`elf_vldb::compress`、`elf_plus::compress`、`elf_star::compress` 和 `self_star::compress`。其中SElf*先把同列所有块组成一个Session，83行只调用一次compress，保留跨块状态。
- [Chimp测试本体](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/chimp/tools/validate.py:43)、[Elf/Elf*测试本体](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/elf/tools/validate.py:45)、[Elf+测试本体](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/elf-plus/tools/validate.py:67)、[SElf*测试本体](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/self-star/tools/validate.py:32) 都确实调用上游Java类，检查raw byte equality和双向解码，而非只运行重写自roundtrip。
- Oracle bridge是薄层：例如 [ChimpOracle.java](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/Source/chimp/ChimpOracle.java:15) 调用原类 `addValue/close/readValue`；[SElfStarOracle.java](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/Source/self-star/SElfStarOracle.java:57) 在块之间调用原类 `refresh`，没有重写算法逻辑。
- 本次检查每包 `validation/current/report.json` 的全部 `source_files` 都匹配现有文件，differential报告SHA匹配current报告，并且当前CLI二进制SHA匹配differential与current两份证据。各vendor实现源/头文件与standalone当前实现一致。
- 五包冻结SOURCE_FILES闭包合计367条记录均匹配 `Compression_Rewrite/Source/*/upstream`。Chimp、Elf+、Elf*、SElf*各文件还通过了 `Compression_Source_Code/Source_Code/_repos` 所选commit的 `git show COMMIT:PATH` SHA核对。

## 本次验证方法和结果

新增 [replay_lossless_evidence.py](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/replay_lossless_evidence.py)；可在仓库根目录执行：

```sh
python docs/audits/20261011_rewrite_native/replay_lossless_evidence.py
```

完整逐case结果见 [lossless_replay.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/audits/20261011_rewrite_native/lossless_replay.json)。每个有效case检查存档input/raw/frame SHA、完整frame FinalBits、存档原Java交叉解码输出；随后用当前C++ CLI重新编码输入并比对存档原Java流、解码存档原Java流、重建checked frame并逐字节比对、再解码该frame。所有新编码/解码写入 `/tmp` 的临时目录，不覆盖旧报告或比特流。

额外运行了5包当前standalone preflight，并先核对每个preflight二进制的current artifact SHA：5/5 exit 0。它们覆盖生命周期、精确容量/no-write、unaligned/guard、截断与malformed变异、独立对象等；SElf*输出4026 cases/8 independent handles/2002 network values。

## 必须保留的限定与证据问题

1. **声明支持域不是全部IEEE数据。** Chimp/Chimp128 canonical NaN（32: `7fc00000`，64: `7ff8000000000000`）是END，其他NaN payload有raw位模式测试。Elf家族NaN是END且部分极值/十进制恢复/不收敛搜索会被拒绝。原作数值失败被有界拒绝，没有raw兜底。具体范围见 [Chimp contract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/chimp/contract.md:9)、[Elf contract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/elf/contract.md:12)、[SElf* contract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/self-star/contract.md:46)。
2. **Benchmark产物带容器，不与原始流整包相同。** 最终产物包含descriptor、RWF1、per-block完整standalone checked frame和checksum；原Java只应与提取的raw算法流比较。现有差分测试正确区分raw和complete frame。计时还包括Python布局转换/FFI/描述符/拷贝，registry的NATIVE timer为UNAVAILABLE_NULL，不能把CORE指标当纯C++内部耗时。
3. **Benchmark接入没有公开全部standalone能力。** 六项当前都是VALUE；`features.streaming/query/random_access=false`。独立standalone中append/cursor/network API的成功不能改写成Benchmark具有这些接口。Elf*共享注册block_size上限1000，低于其binary64 standalone的16384上限；SElf*每列≤1024块、每块≤16384值、总value bytes≤16 MiB。见 [adapter README](/home/fzg/PycharmProjects/TSDataCompressBenchMark/adapters/rewrite_lossless/README.md:67)。
4. **SElf* differential报告有两处源文件hash过期。** [differential/report.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/self-star/validation/differential/report.json:5) 的header记录 `e7d365...`，实际/current header是 `222465...`；17行CMake记录 `258627...`，实际是 `bb4648...`。codec.cpp、测试和CLI hash一致；current有当前文件hash和相同CLI artifact，89个case本次重放全部通过，所以这不是已复现的编码错误。但历史报告不能被表述成“所有记录的源码hash均为当前版本”。是否仅注释/构建清理没有足够旧文件内容可直接证明；建议重建oracle后生成新的differential证据，不手改旧报告。
5. **Java oracle不能直接在当前机器按历史命令复跑。** `/tmp/tscb-elf-java8/bin/java`、javac和`/tmp/tscb-elf-oracle-downloads/{dsiutils-2.7.0,fastutil-8.5.8}.jar`均已不存在。源码/依赖下载URL与SHA仍在证据中，故这是当前重现环境缺口，不等同于原历史测试失败。本次仅宣称“当前C++重新回放 + 存档Java结果字节核对”，没有宣称新Java oracle运行。
6. **Elf所选原作有意不同于Source_Code当前elf dev checkout。** 所选386d6934 commit在当前 `_repos/Spatio-Temporal-Lab_elf` 的浅克隆中没有对象；该dev checkout只与20条锁记录中9条相同。Source_Code的 `cwida_ALP/publication/source_code/extern/elf` 中17/20条同SHA，包括全部16个算法Java文件；余下是pom/bit-I/O依赖文件。实际选用的VLDB2023冻源20/20条锁记录同SHA，且109个case本次原bitstream回放成功；不能因对比错版本把它判成Elf+。版本区别明载 [Elf contract](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/ReWrite/elf/contract.md:3)。
7. **Elf*/SElf* reference存在公开记录的编译overlay。** 原 `Elf32Utils.java` 未使用的双参数helper缺局部变量temp；补丁只补该声明，所选算法调用三参数overload，见 [原文件](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/Source/self-star/upstream/src/main/java/org/urbcomp/startdb/selfstar/utils/Elf32Utils.java:53)、[补丁](/home/fzg/PycharmProjects/TSDataCompressBenchMark/Compression_Rewrite/Source/self-star/PATCHES/missing-temp-build.patch)。不能宣传reference毫无build patch；现有证据不显示所选codec运行语义被修改。

已证实的原生执行和raw语义兼容范围比“PASS”标签更具体；未核验Linux x86_64以外平台，也未将安全变异测试/能力矩阵模板视为普遍正确性证明。
