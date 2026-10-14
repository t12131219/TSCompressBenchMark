# V4.0 测量工具的重新联网阅读

阅读日期：2026-10-12。本轮重新通过 `git ls-remote` 固定公开版本、下载原文并读取下列范围。沿用同一 upstream commit 是远端 HEAD 未变化的结果，不以旧笔记代替本轮阅读。没有运行这些 benchmark，没有修改机器调优设置。

## 1. 来源与范围

| 项目 | 固定 commit | 本轮实际阅读 |
|---|---|---|
| [pyperf](https://github.com/psf/pyperf/tree/00556e18777c36cfd96c91fdf1cd6bf70dd8c276) | `00556e18777c36cfd96c91fdf1cd6bf70dd8c276` | README.rst、doc/run_benchmark.rst、doc/analyze.rst、doc/system.rst 四个文件全文 |
| [Google Benchmark](https://github.com/google/benchmark/tree/f2f78087c2235e9e3156d0651be26660005a03a1) | `f2f78087c2235e9e3156d0651be26660005a03a1` | docs/user_guide.md 第70–140、1200–1450、1609–1655行；src/benchmark_runner.cc 第325–584行。只声明这些章节/函数，不声称本轮重读整个指南或runner |

pyperf四文件SHA-256依次为：`d646dc502dda5594b47a448d6fa801c3788e83638e0e11b3e0c7012ae8c69610`、`47fce13c34a6e0744ee280e252e9bc346094c96a015d08547bb6437a09a20e33`、`1f7c85eb7e5a9ad49af1bb2bee2cc3e3a9f43431991b8d23a0c6dd75bac7c279`、`e32dfff3657b8d175426319fd82b50a5026390c4e6759f92b55625b8749b50d7`。Google指南与runner依次为 `7fa5caecc77823d4914ea27f2f2729ecde2d884f248af58f73c077fd5b77c910`、`dae25d41968634183d9473fccf51016ef71113d61c4c50bcb00a6f918e3bc9a9`。

原文快照位于 [measurement来源目录](sources/measurement/pyperf/README.rst)；最终来源清单另记录各文件URL、字节数和哈希。已下载但未读的Google README不能计入本轮全文阅读。

## 2. 原文事实

pyperf把worker process、values、warmups、outer loops与inner loops分开。运行指南的示例先用一个进程校准，再顺序启动多个测量进程；每个测量进程自己预热，校准进程的热状态不会传给它。benchmarks与processes顺序运行，不同时竞争资源。默认计时粒度为每value约100ms，这是工具选择，不是时序压缩的统一阈值。

指南明确没有“预热到稳定”为止的自动政策；某些benchmark永不进入稳定状态，任意终止政策也会导致不同run使用不同预热次数。pystats收集的开销会使性能计时失去意义。分析指南保留warmup、校准与原始分布，提供均值、标准差、median、MAD、直方图等，噪声告警本身不是删除慢值的授权。

系统指南讨论CPU affinity/isolation、NUMA、SMT、频率、电源和ASLR，也区分已支持的功能与明确标注“untested”的调优命令。V4不能把整页命令变成自动修改宿主机的初始化脚本。分析指南的t-test/alpha措辞不作为本项目统计定义；本轮没有审阅该检验实现。

Google指南区分主线程CPU time、全进程CPU consumption、wall time和manual/device timing；内部多线程的用户等待用wall time。框架多线程runner创建/join的时间默认不在测试循环内，不能将这样的结果当包含线程创建的独立请求延迟。

runner的 `DoNIterations` 根据manual/real/CPU选择计时依据。`RunWarmUp` 使用测量机制，但恢复原有迭代数；`DoOneRepetition` 只在第一repetition推算迭代数，后续复用。函数里的“significant”指运行时长/迭代足够，不是统计显著性判定。`RunMemoryManager` 和 `RunProfilerManager` 是额外执行：前者最多16次且单线程，后者按测量iters执行且单线程。不能拿这些资源数据宣称是任意多线程主trial同次精确峰值。

## 3. 对 V4.0 的推论

1. 运行单位明确为数据对象、进程session、round和inner loops；进程次数与同进程重复次数分开配置。V4首版对象路径固定loops=1，校准只诊断时钟粒度；后续批测量才可调整loops，不能改变压缩输入或算法参数。
2. 独立对象生命周期可以运行在已预热worker内。把“新codec session”“新OS进程”“冷cache”“未加载模型”分开命名，避免一个cold字段混淆四件事。
3. CPU wall timer与GPU completion协议由executor负责，encoder/decode的必要分配、模型读入和恢复成本由对象方案负责。默认不减去估计的Python开销。
4. 主计时与profiling分轮执行。资源报告注明不同pass、sampling/high-water/allocator方法和包含范围；资源预算仍可通过worker限制实施。
5. 固定预热政策、保留随机执行顺序、进程层次与原始分布。论文预算由pilot决定，普通一次run不强制20processes或100ms。
6. pyperf是测量机制参考及可选微基准工具，核心压缩runner自写。把encode/decode/验证全部塞入一个pyperf函数会丢失分阶段边界；不能同时叠两套校准与预热。

## 4. 适用限制

这些来源解决测量机制，不提供时序数据集的统计独立性、不证明某有损误差保证，也不定义完整压缩产物成本。V4要另外指定数据任务、产物恢复目标、语料抽样和原始域验证。
