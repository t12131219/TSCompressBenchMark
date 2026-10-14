# V4 论文与工作负载阅读记录

日期：2026-10-12。本文是本轮重新获取资料、逐页全文阅读后的记录，服务于“各类时序压缩算法在各类时序数据上的标准测试”论文定位。不是运行规范，也不是把历史 V3.2 门禁搬到新框架。

## 1. 来源、版本与阅读范围

| 来源 | 本轮读取的版本与公开入口 | 页数与阅读范围 | 本轮 PDF SHA-256 |
|---|---|---|---|
| TerseTS: A Framework for Time Series Compression | EDBT 2026 Demonstration Paper，印刷页 760–763；[DOI](https://doi.org/10.48786/edbt.2026.74)，[公开全文](https://openproceedings.org/2026/conf/edbt/paper-286.pdf) | 4 页，PDF p1–4 全文，包括代码、表图、参考文献；另渲染核对 p1、p2、p4 | `7f2a5eb53660de99c25f560519844f64ea0862159f61354e8e8185438d1ece63` |
| FCBench: Cross-Domain Benchmarking of Lossless Compression for Floating-Point Data | PVLDB 17(6), 2024，1418–1431；DOI `10.14778/3648160.3648180`；[公开全文](https://www.vldb.org/pvldb/vol17/p1418-tao.pdf) | 14 页，PDF p1–14 全文，包括参考文献；另渲染核对 p7、p9、p10 | `76b6829ed2d64faf013d67302e8885d9d3b1597c81415ec2f713bcc67ce9e30b` |
| ALP: Adaptive Lossless floating-Point Compression | SIGMOD 2024 author version；正文 DOI 为占位字符串，因此用 [CWI 作者版全文](https://ir.cwi.nl/pub/33334/33334.pdf)，正式 DOI `10.1145/3626717` 仅用于作品身份 | 14 页，PDF p1–14 全文，包括算法、表图、讨论与参考文献；另渲染核对 p9、p10 | `07629cc7d63ca00e52ed2f257e379d3a7c5efe0637eaf11327252166afa31819` |

本轮合计 32 页全文。文件分别为 `/tmp/tsbench_v4_research_20261012/papers_a/{tersets,fcbench,alp}.pdf`；`sources.json` 记录下载地址、长度、页数、散列。下载字节数依次为 1,240,673、4,061,229、1,117,147。系统 `/usr/bin/pdftotext -layout` 提取全文并按页读取，`/usr/bin/pdftoppm` 渲染图表。工具默认 bundled Poppler 要求本机没有的 GLIBC_2.38，因此改用系统 Poppler，未将提取失败算成阅读完成。

检索边界：本轮使用 OpenAlex、Crossref、搜索引擎页面及 GitHub 检索 TerseTS、TSCompress、时序压缩 survey。OpenAlex 确认了正式 TerseTS 2026 条目。部分搜索引擎返回脚本/验证码页；Crossref 对 `TSCompress` 没有确认独立论文，GitHub 的近名结果包含疑似本项目仓库。**未确认外部独立 TSCompress 论文，故不把这个名称作为相关工作依据；这不表示断言该作品不存在。**本记录不宣称检索穷尽整个领域，也不把仅检索到的 survey 标记为全文读完。

以下“论文事实”限定于所读取版本；“本项目推论”是设计建议，需实际实验检验。

## 2. TerseTS：最需要正面对比的已有框架

### 2.1 论文事实（p1–4，§2–3）

TerseTS 已把无损与有损方法放入统一 API，核心用 Zig 从零实现，公开小型 C API，并提供 C、Rust、Julia、Python bindings。NumPy 在满足条件时可零拷贝传入。它接受 `UncompressedValues` double 数组、输出 `CompressedValues` byte 数组；`compress()` 还接受 method ID 和 JSON 参数。参数有方法相关 schema，非法/不兼容参数返回错误。

Table 1 的三族为 functional approximation、line simplification、value representation。表内具名方法/变体标签约 18 个（将 PMC-mean/mid 分开数）；论文自己的表述是 “over a dozen”。这两个口径不应改写成“18 个独立算法”。NeaTS* 的星号明确指 **NeaTS 的有损阶段**，不是完整原论文 codec。

它用 `extract()`、`rebuild()` 暴露和重建中间表示，可以把 coefficients 与 indices 再编码。若方法只做逻辑结构压缩，中间表示的每元素固定为 8 bytes，由用户继续选择物理编码；Serf-QT 等物理级方法则实现完整 pipeline。Listing 3 的 Python 示例为 Swing → coefficient SerfQT + index RLE；Figure 3c 的 GUI 示例为 PMC-mean → coefficient Bit-QT + index Bit-delta。

Visualization 组件可上传数据、按数据范围百分比设 error bound、选择 Zstandard postprocessing，并查看原始及重建序列。示例为 Saugeenday 前 1,000 点。Comparison 组件可汇总多个 run/configuration，选择 RMSE、compression ratio、execution time、bits/value，切换 linear/log 轴，并显示 Pareto trade-off。Figure 1 使用 Monash 来源的 Saugeenday、Oikolab，显示相同方法随数据变化的质量/空间差异。

Figure 1 图例有 DFT，而 §2.1 将 Fourier/wavelet domain transformation 写作未来工作。因此不能只凭图例断言该版本完整 API 已支持所有变换方法。

### 2.2 该 4 页 demo 没有建立的证据

正文没有给出系统性的语料抽样协议、固定硬件/编译器矩阵、完整计时起止、重复次数与区间估计、CPU threads/SIMD/GPU 对照矩阵、全部失败任务分母或冷进程保存/恢复实验。文章讨论 intended downstream use，但没有预测/分类等下游任务实验证据。

Listing 3 把 `c2 + c3` 注释为 compressed representation，恢复仍从调用方 `pipeline[0]["method"]` 取得 primary method。论文没有规定完整多阶段自包含持久 container 及恢复 metadata 计费协议。这是**论文描述边界**，不是对当前 TerseTS 源码“不能保存”的证明；源码能力应由本轮开源项目审计另行判定。

### 2.3 本项目推论

“轻量框架、统一 API、多语言封装、JSON 参数、多阶段 pipeline、交互 dashboard、RMSE/ratio/Pareto 可视化”均已有直接先例，不能作为 V4 论文的独立新贡献，更不能声称“首个通用时序压缩框架”。

值得验证的区别是：保留真实已有实现及移植身份，将带 dtype 的 value/timestamp/mask 原始对象、完整独立恢复成本、测量驻留与完成边界、失败覆盖、数据集抽样及跨环境统计单位写成清楚而可复现的**实验协议**。该差异是否成立、是否影响结论，必须由同条件对照与消融实验支持。

## 3. FCBench：分开回答三个问题

### 3.1 论文事实（§3–6）

文章分开评价 general compression performance、HDF5/pandas query microbenchmark、roofline 性能分析，而不是要求每一个重复 trial 同时完成三类任务。Table 3 有 33 个真实数据集：HPC 10、TS 8、OBS 8、DB 7，列明 single/double precision、size、extent、entropy。八个 TS 名称为 citytemp、ts-gas、phone-gyro、wesad-chest、jane-street、nyc-taxi、gas-price、solar-wind。它们主要作为浮点数组测试，不能自动视为完整 timestamp/value/missing-mask 时序对象。

数量应谨慎引用：摘要、§1、§3、§5.4 概称 13 方法、8 CPU + 5 GPU，Friedman 使用 `k=13`；Table 1 把 bitshuffle LZ4/zstd 变体分别列出，并列了 DZip；Table 4/5 实际为 14 个实现/变体结果列（9 CPU + 5 GPU，不含 DZip 结果）。正文和表格计数口径不完全一致；不擅自用此断言作者统计错误，也不把各变体列数等同独立算法数。

§5.2 对大部分方法计量压缩/解压函数调用前后的时间并排除 I/O；bitshuffle 与 nvCOMP 使用 built-in benchmark。每方法/数据集重复十次并报告平均值，压缩率聚合用调和均值，throughput 用算术均值。§5.4 用 Friedman 和 Nemenyi；多数据集是统计比较的单位，不能把内层时间重复当作新增独立数据集。

§5.5 的平台为双 Xeon Gold 6126 2.6 GHz、187 GB RAM、RTX 6000 24 GB，Ubuntu 20.04、GCC 9.4、CUDA 11.3、CMake 3.25、Python 3.8，C/C++ 用 `-O3`，GPU 尽可能使用 `sm_75`。这些参数是论文该次实验环境，不能不经验证套用到本机。

§6.1 compression level 按最好压缩率选择，blocks/chunks 用默认值。Table 4 的 `-` 表示没有相应结果，不是零空间成本。§6.1.1 报告 CPU 和 GPU 压缩错误率分别为 2% 与 7.3%，真实失败是结果的一部分。

Table 5 的 GPU 核内吞吐与 Table 6 的含 host/device copy wall time 可产生不同排序。nvCOMP 缺没有 I/O 的独立 wall API，因此从 Table 6 省略，不能把缺失栏补成核时间。§6.1.6 线程数 1/2/4/16/24；ndzip-CPU 没有相似缩放，作者说可能与实现问题有关，这不是算法不可并行的定理。Table 9 比较 4 KB、64 KB、8 MB blocks，块大小属于会改变结果的自变量。

§6.2 的查询系统读取 HDF5、解码，再由 pandas full scan，包含基于 10-bin histogram 的谓词实验；作者明确它不是复杂真实数据库系统。§6.3 的 roofline 只以 msg-bt 为分析数据，CPU 使用 Advisor，GPU 使用 Nsight；Go Gorilla/Chimp 不被 Advisor 支持，GPU roofline 受篇幅省略。

### 3.2 本项目推论

默认时序比较可只做正确性、完整空间成本与压缩/恢复性能。查询、profiling、能耗及 downstream 可以是独立实验入口；把它们做成全部 trial 的门槛既不必要，也混淆 RQ。

跨 CPU/GPU 至少要报告设备驻留内核边界和可使用产物的完成边界；只有结果放在相同边界下才比较。native 最佳运行块大小与统一工作负载块大小可分别服务于“部署性能”和“同一请求”的问题，但不能混在同一排名里。固定 dtype、extent、layout，并公布转换成本；不能为了让某方法更压缩而静默把 double 降成 float。

level/线程数/块大小的选择成本要披露；若根据测试集选冠军，只能标为事后 oracle，不能伪装成预先固定配置的泛化性能。失败记录与 task matrix 的完整分母必须留下，平均值不得只展示各 codec 最有利的成功子集。

## 4. ALP：缓存内核、完整系统与原始精度是不同对象

### 4.1 论文事实（§2–4、§6）

ALP 分析 30 个真实用户贡献的数据集：13 个 time series、17 个 non-time-series，后者含 12 个 Public BI 数据集。18 个来自 Elf/Chimp 的既有评估、12 个来自 PDE 评估。论文借这些数据设计并评价算法，未建立算法开发/评估彼此隔离的新语料协议。

§2 分析数据语义、重复值、decimal precision、IEEE exponent、previous-value XOR 的 leading/trailing zeros，并按 1,024 值 vector 分析局部相似性。大部分样本源自 decimals；POI-lat/lon 则高精度、更难压缩。这个结论限定于作者的 30 个样本，不能扩大成“所有真实时序都是低精度小数”。

ALP 用 decimal→integer 转換、exceptions、FFOR，自适应选 exponent/factor；难压缩行组改用 ALP-rd 的 front-bit dictionary+bitpacking。exception 含原值与位置；vector 参数、row-group 参数、dictionary 都是恢复需要的状态。论文有些细小开销称可忽略，例如 ALP-rd 的每行组 8-bit split 参数；标准测试仍应记录真实总 bytes，并让读者看到固定开销何时显著。

§4 定义 vector=1,024、row-group=100 vectors、最多五组 exponent/factor 候选；sampling 参数在 evaluation 中调过。实现身份不是单一语言：ALP C++；Gorilla 作者自行 C++ 实现；Chimp/Chimp128/Patas 从 DuckDB 调整；PDE/Elf 用原作者代码；Zstd 原 C 实现 level=3。移植、自写、原版和 stripped implementation 必须区分。

Table 4 对全部数据的 bits/value 为 **ALP 21.7、LWC+ALP 18.8、Zstd 20.6、Elf 23.1**；不能把 23.1 误写成 ALP。LWC+ALP 是不同完整组合，不应和裸 ALP 的身份或恢复成本混算。ALP 并非每个数据集压缩率最优。

§4.2 微基准取每个数据集一个 1,024 值 vector，重复 300K 次并求平均，让数据 L1 resident；Zstd 使用一个约 1 MB row-group。速度单位为 tuples/CPU cycle，包含 ALP 的 FFOR，**不含第一阶段 row-group sampling**（§4.3 明确指出它只在完整 COMP 中出现）。这种测量支持缓存驻留核心计算成本，而不是全数据流压缩墙钟时间。

Table 3/Figure 4 比较 Ice Lake、Zen3、M1、Graviton2、Graviton3 五种 CPU；区分 scalar、auto-vectorized、SIMD intrinsics。scalar 通过禁用 auto-vectorization 的 flags 构建；能禁用时关闭 turbo。Figure 4 展示解压的架构实验，不能改写成压缩/解压在所有 CPU 上均做完对照。

§4.3 在 Tectorwise 测 COMP、SCAN、SUM，以拼接把数据扩成 10 亿 doubles（8 GB），取五个不同特征数据集，线程到 16，32 次查询平均。完整 COMP 包含写 metadata、可变 exceptions、第一 sampling 阶段；SCAN 包含 metadata 读取和解码函数选择。因此不应把它和 Table 5 的全语料缓存微基准均值直接对比。Elf 因缺 C++ 实现不纳入该系统查询。

§4.4 另做 ALP-rd 32-bit ML weights 压缩，非默认时序语料。将 f64 数据变为 f32 是输入任务的改变，即使论文在其可表示样本上这么做，也不能据此在标准基准中无说明降精度。§7 将 GPU/TPU 作为未来工作，该作者版没有 ALP GPU 评估结果。

### 4.2 本项目推论

既有 codec 可以保存，bench 控制面用 Python；这并不要求把所有 codec 内核翻译成 Python。对移植完成/重写完成实现记录来源、版本、语言、构建 flags 和准确的能力范围，再逐个做 adapter，可避免把解释器和绑定开销当成算法本体。

以 wall-clock 为共同比较基线，cycles/tuple 和设备 events 做可选诊断。默认计时至少覆盖一次请求所需的采样、编码、最终可用 bytes 和解码状态恢复；额外 kernel mode 必须明确“状态已准备、数据已驻留”的前提。高层 Python API 开销若属于用户调用路径就计入；另测 native kernel 可解释差异。

不能用 300K 内层循环推出同样数量的统计独立样本。保存每个外层 run 的原始时间与循环次数，按 series/window 或数据集汇总，依据 RQ 选择统计方法。不能用一个挑选的 vector 的速度替代全语料压缩率所覆盖的任务。

## 5. 对 V4 论文定位的直接限制

| 可能提出的贡献 | 本轮直接先例 | 可支持的 V4 研究方向 |
|---|---|---|
| 统一无损/有损 API、JSON 参数、Python bindings | TerseTS §2 | 工程接口；不能单独主张新贡献 |
| 多阶段 pipeline、重建可视化、Pareto | TerseTS §2–3；ALP LWC cascade | 作为分析工具；需具体实验发现才成为论文证据 |
| 多真实数据集、CPU/GPU、重复统计、roofline | FCBench §5–6 | 以时序原始对象、完整恢复、失败覆盖与同边界环境协议扩展；不可只列功能数量 |
| scalar/auto-vector/SIMD 多 CPU | ALP §4.2 | 用相同工作负载条件检验排名及瓶颈变化，准确记录实现身份 |
| 完整空间成本和独立恢复 | 本轮论文讨论必要 metadata，但未统一成跨方法持久恢复协议 | 测完整 self-contained artifact、共享模型/字典与分摊策略，实测 payload-only 排名会否改变 |
| 异构时序标准测试 | TerseTS 同质 double API；FCBench 浮点数组跨域；ALP double vectors | 建立 typed values/timestamps/masks、真实抽样单位和质量约束，实测统一转换与原生表示的影响 |

“标准测试”应解释为**公开、可执行、可复现实验协议和基准套件**，不是正式标准组织认证，也不是一份对所有任务适用的绝对算法排名。候选贡献仍需更完整相关工作核查以及真实对照实验证据；本文不能证明任何“首个”或优于已有框架的广泛断言。

## 6. 从文献推导的 RQ 与最小实验（本项目建议）

1. **RQ1：数据特征怎样改变条件排名？** 在不同来源、规则/不规则时间、多 dtype、单/多变量、缺失率、长度、重复率、局部变化和噪声下报告 ratio、encode/decode wall time、质量、失败覆盖。先选真实语料、预先固定来源与抽样策略，再补 controlled synthetic；同源多个窗口是嵌套样本。
2. **RQ2：完整恢复代价怎样改变排名？** 同时记录 value payload、timestamp/mask、headers、shape/dtype/config/model/dictionary/index 总成本。保存后在冷进程只从 artifact 和明确声明的 immutable shared artifact 解码；计 shared artifact 的真实下载/存储 bytes，并预先固定单序列或多序列分摊口径。小序列与大序列分别评价。
3. **RQ3：计时与环境边界怎样改变结论？** CPU 线程、SIMD build、GPU kernel resident 与 host→artifact→host complete 分开比较。同一硬件内先做成对比较；不同硬件各保留独立层，不把不同设备的 raw throughput 混成一个算法总分。冷启动和 steady-state 回答不同问题，需单列。
4. **RQ4：同一质量目标下的有损 trade-off 是什么？** 相同误差定义、原始 dtype 和特殊值政策下跑 quality ladder，报告 max absolute/relative、RMSE 等实际值及 infeasible/violation 状态。至少按 declared error guarantee 分组；不能把 abs-error、RMSE-only 方法当同等保证。预测/分类/异常检测只在论文明确声称保持该任务效用时增加相应独立实验。
5. **RQ5：多少结论依赖输入布局/实现/调参？** 原版与重写身份、内核/API/full-artifact 边界、默认参数与开发集固定调参、不同 block/layout 作少量有目的消融，量化结论变化。训练和外部配置选择隔离开发/测试；固定算法的计时粒度校准不承担训练语料隔离要求；codec 内部自适应采样属于压缩请求成本。

最小输出是预先展开的 task matrix（含不支持环境/输入）、每任务状态和原因、完整 artifact cost、每个外层 run 的原始观测、描述报告。默认不阻断主测量的资源 profiling 可独立运行。置信区间与成对效果以适当的 dataset/series 层级重采样；Friedman/Nemenyi 仅在共同任务、独立统计单位、RQ 与假设适配时做，不把它们永久绑成所有试次的门禁。

一个可用于主计划的小型任务身份参考：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ComparisonTask:
    raw_object_id: str       # typed values + timestamp/mask identity
    codec_input_id: str      # explicit dtype/layout/transform output identity
    implementation_id: str  # original/port/rewrite + build and binding identity
    parameters_id: str
    environment_id: str
    boundary: str           # e.g. request_complete or kernel_resident
    quality_id: str         # declared guarantee + target + special-value policy
```

这是参考结构，不是本轮实现代码。它只为说明公平比较所依赖的对象；资格检查复用应依 codec 可执行身份、相关 adapter/validator 身份与输入/质量能力，报告渲染代码的变化不应使编码正确性资格作废。
