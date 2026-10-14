# TSBench V4.0：第二轮联网阅读与源码核对

日期：2026-10-12。设计入口：[TSBench 4.0 工程实施总计划](../../TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md)。本轮重新检索、下载、阅读全文／指定源码，再独立编写 V4.0；第一轮旧索引已在框架清理时移除，本轮来源另行完整保存。

## 1. 阅读记录

| 记录 | 主要内容 |
|---|---|
| [论文、对象与工作负载](papers_and_workloads.md) | TerseTS、FCBench、ALP全文；适用对象、输入变换、实验边界及论文差异 |
| [测量方法论文](measurement_paper.md) | Benchmarking Crimes v1全文含附录；研究范围、失误类别及对压缩基准的有限迁移 |
| [测量工具](measurement_tools.md) | pyperf四份文档全文，Google Benchmark指南／runner的明确区间；进程、预热、计时与独立profiling |
| [时序算法、GPU环境与计时](environments_and_timing.md) | Sprintz、cuSZ全文，Gorilla指定章节；nvCOMP官方生命周期、样例和实际固定NVBench依赖；传输、完成、缓存与设备状态 |
| [codec资产与开源执行](codecs_and_open_source.md) | lzbench、ALP、TerseTS具名文档／源码；36个真实codec key、两ABI、构建、模型和线程限制 |

各记录区分原文事实、源码事实与本项目推论。没有运行第三方benchmark或复现其性能数字，也没有构建当前缺失的codec共享库。

## 2. 论文全文与定向阅读

| 论文与本轮版本 | 实际范围 | 本地原文 |
|---|---|---|
| [TerseTS，EDBT 2026 demo](https://openproceedings.org/2026/conf/edbt/paper-286.pdf) | 4页全文 | [PDF](sources/papers/tersets.pdf) |
| [FCBench，PVLDB 2024](https://www.vldb.org/pvldb/vol17/p1418-tao.pdf) | 14页全文 | [PDF](sources/papers/fcbench.pdf) |
| [ALP，SIGMOD 2024作者版](https://ir.cwi.nl/pub/33334/33334.pdf) | 14页全文 | [PDF](sources/papers/alp.pdf) |
| [Sprintz，arXiv v1](https://arxiv.org/pdf/1808.02515v1) | 23页全文 | [PDF](sources/papers/sprintz_v1.pdf) |
| [cuSZ，arXiv v1](https://arxiv.org/pdf/2007.09625v1) | 13页全文 | [PDF](sources/papers/cusz_v1.pdf) |
| [Benchmarking Crimes，arXiv v1](https://arxiv.org/pdf/1801.02381v1) | 17页全文含附录 | [PDF](sources/papers/benchmarking_crimes_v1.pdf) |
| [Gorilla，PVLDB 2015](https://www.vldb.org/pvldb/vol8/p1816-teller.pdf) | 定向重读压缩、数据与评估章节；不计入本轮全文篇数 | [PDF](sources/papers/gorilla_vldb2015.pdf) |

本轮全文合计 **6篇、85页**。Sprintz/cuSZ官方HTML作交叉核对，不能重复计作两篇论文。选定版本的结论不自动代表后续论文或当前实现。

## 3. 开源项目范围与版本

“完整阅读”只指下述具名文件，不指整个仓库。精确URL、commit、行区间、字节数和SHA-256见[来源总清单](sources_manifest.json)。

| 项目 | 本轮固定版本／范围 |
|---|---|
| [lzbench](https://github.com/inikep/lzbench) | `9ca711ce574d1ac56b803db4292b8797283575b3`；README、lzbench.cpp、threadpool.cpp/.h全文，lzbench.h指定声明 |
| [ALP](https://github.com/cwida/ALP) | `31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce`；README、用户数据指南、BENCHMARKING及四个执行文件全文，fls_bench.hpp计时相关区间 |
| [TerseTS](https://github.com/cmcuza/TerseTS) | `64abd7767f8fc6ac1ef4e932f2027a74cf8fb4a0`；README、Python README／binding、tersets.zig、capi.zig全文；tester.zig指定计时／误差区间 |
| [pyperf](https://github.com/psf/pyperf) | `00556e18777c36cfd96c91fdf1cd6bf70dd8c276`；README.rst与run_benchmark/analyze/system三份指南全文 |
| [Google Benchmark](https://github.com/google/benchmark) | `f2f78087c2235e9e3156d0651be26660005a03a1`；user_guide.md三组指定区间；benchmark_runner.cc第325–584行 |
| [nvCOMP官方文档与样例](https://github.com/NVIDIA/CUDALibrarySamples/tree/master/nvCOMP/benchmarks) | 官方C/C++ quickstart全文；样例固定`07c4f09223302ce4310eef945ed458e092598d17`；README、HLIF全文，chunked/common/CMake计时或依赖区间 |
| [NVBench](https://github.com/NVIDIA/nvbench) | 上述样例实际依赖`4a33a61591666f48cb5fd714d00d7d2df5977ff1`；benchmarks指南、state_exec与cold/hot timer相关具名文件，范围见清单 |

远端来源总计52份：6份全文论文、1份定向论文、32份全文文档／源码文件、9份指定段源码文件、4份官方HTML文章／指南。另记录63份本地源码／登记／库存来源及5份阅读笔记。已下载但未阅读的Google README、未读的克隆仓库文件、检索／metadata响应及失败下载均不计入阅读来源。

## 4. 复核入口

- [来源总清单](sources_manifest.json)：实际使用的primary source、阅读范围、版本及哈希；哈希用于资料溯源，不成为实验执行门禁。
- [codec／开源快照索引](sources/codecs_open_source/reading_manifest.json)：19份具名文件及对应阅读范围。
- [本地codec静态库存](sources/codecs_open_source/local_codec_inventory.json)：36个真实key、4个oracle、构建目标、1261个冻结文件与17个模型核对；静态一致不等于运行资格。

本轮两个关键源码结论是：当前ALP桥接为forced scalar方案；六个无损重写shim在各自共享库内使用全局锁，同库跨handle线程调用也会串行。因此论文必须区分算法、实现和实际资源，不能从配置中的SIMD／线程字段推定执行能力。
