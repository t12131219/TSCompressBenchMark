# V4 测量方法论文全文阅读：Benchmarking Crimes

日期：2026-10-12。此文提供测量研究的方法论背景，**不是时序压缩领域实证调查，也不转换成 22 项执行门禁**。

## 1. 可核验来源和完整阅读范围

- 作品：Erik van der Kouwe, Dennis Andriesse, Herbert Bos, Cristiano Giuffrida, Gernot Heiser, *Benchmarking Crimes: An Emerging Threat in Systems Security*。
- 本轮版本：[arXiv:1801.02381v1](https://arxiv.org/abs/1801.02381v1)，PDF 首页面明确标示 `8 Jan 2018`；[读取 PDF](https://arxiv.org/pdf/1801.02381)。未把此 v1 预印本标成最终会议版。
- 下载 PDF 17 页、465,485 bytes；SHA-256 `915270be60890682599c67c62abd8e9960a394bfdc950b5425aad0ad58af8e63`。
- 本轮读取 PDF p1–17 全部正文、方法、结果、限制、相关工作、Appendix A 和参考文献；另渲染并查看 p3 Table I、p8 Table III、p9 Figure 1，核对表格中分类/分母。
- 原文存 `/tmp/tsbench_v4_research_20261012/root_sources/benchmarking_crimes_arxiv.pdf`；使用系统 `/usr/bin/pdftotext -layout` 按页提取，无未读取的剩余页。
- 获取成功，无全文访问限制。此处只记录当前 PDF 字节身份；若需要正式版本或新版，须另外核查版本并重读差异。

## 2. 论文实际研究了什么

作者将性能评估质量分成 completeness、relevancy、soundness、reproducibility 四个维度，提出 22 类常见问题（§II，Table I）。然后调查**系统安全运行时防御**论文，选择 2010 与 2015 年 USENIX Security、IEEE S&P、CCS、NDSS 共 50 篇，分别 16 和 34 篇（§III、Table II）。这不是抽样的浮点/时序压缩论文。

两位读者独立分类每个 paper/problem 为 correct、flawed、underspecified、not applicable；8/50 篇存在需讨论的分歧，最后协商（§III.A）。没有向作者询问补充信息，严格按公开论文能证明的范围判断。**描述不充分**与**已经证明实验错了**分开，是值得沿用的证据纪律。

Table III 的百分比以该问题适用的论文数为分母，而非所有论文统一作分母。适用 paper/problem pairs 共 255（2010）和 596（2015），flawed+underspecified 分别 77 与 177（原文附近段落印作 179，而表内 162+15=177）；本文引用表内可重算值，不用这一数值支持领域外推。作者强调调查与严重性判断具有主观性、选中论文存在发布选择偏差、主题随年份变化；§VII 明确**不寻求与其他系统领域比较，问题分布具有领域特异性**。

“几乎所有论文有问题”“平均约五类问题”等结果仅用于该安全系统样本。不能据此写“时序压缩论文普遍不公平”“现有 98% 压缩 benchmark 有五类缺陷”或用它判定本仓库当前代码质量。

## 3. 对轻量时序基准真正有用的原则

### 3.1 从声明和 RQ 选择测量，而非积累检查项

§II.A、E1 指出评估应覆盖声明的贡献及可能负面作用：只测系统有利的工作负载、把少量测试说成全面结论都会削弱比较。Appendix A 同时接受有理由的子集：不支持语言、第三方系统能力限制、全套结果后的深入局部分析等。它没有要求每个系统必须支持所有输入或所有硬件。

**V4 推论：**先展开预先声明的任务矩阵，再记录 supported/unsupported、error、timeout、OOM、quality violation 等状态与理由。只在共同可比较子集统计性能，同时展示覆盖率与分母；对全矩阵、共同子集分别明确。profiling、查询、能耗、下游任务是否需要，取决于论文是否提出相应结论，不需要绑在每一次压缩重复上。

### 3.2 微基准和用户完成边界分别回答问题

§II.B1、§V.B1 明确认可 microbenchmark 用于特定操作和瓶颈解释；错误在于把它冒充 overall performance。Appendix A 甚至接受只影响罕见操作、适合用微基准揭示的情况。§II.C1 批评把简化模拟当真实系统却不说明，附录接受不得不用尚未存在硬件且明确说明的实验。

**V4 推论：**Python API、native kernel、持久 artifact、host/device 完成边界应分别命名。steady-state 的输入/模型/字典准备是否在计时前，冷启动是否包括 JIT/初始化，GPU 是否同步到可用结果，必须显式记录。真实 GPU 未运行就标未验证；模拟/估计只作为有标识的分析，不填真实测量栏。默认结果应说明用户完成一次压缩和独立恢复需要什么，而额外 resident kernel 模式用于解释计算成本。

### 3.3 计时粒度校准不是训练或配置选择

§II.C3 的“same dataset for calibration and validation”具体讨论 train/test overlap 与 profile-guided 优化后用同一 workload 宣称泛化，不是指选择计时循环次数或预热时长。Table III 只有五篇适用，§V.C3 也说样本太少，不能可靠判断其实际影响。

**V4 推论：**模型训练、外部参数/阈值/配置选择使用独立开发集，并记录成本和冻结策略。固定 codec 为达到计时粒度进行校准不用单独数据集。codec 内部的自适应采样是实际请求的一部分，应计费并保存必要恢复状态。不能借 C3 再次给所有固定算法增加无必要留出集门槛。

### 3.4 波动和效果需要原始数，而非默认强制显著性检验

§II.B4、Appendix A.B4 要求有变异指标，例如 standard deviation 或 significance；它接受明确数量界限的低变异说明。Appendix A.B3 指出大波动下不能只说差异可忽略，应改善设计或提供区间。本文没有提出任何时序基准都必须跑某一套 hypothesis tests 的规则。

**V4 推论：**保存每个外层 run 的原始时间、批内循环次数、数据/环境/实现身份，报告分布和适合独立统计单位的区间。批内 repeated calls 用于计时稳定，不变成独立数据集样本。共同任务的成对效果优先于单一排行榜；有多个相依窗口时不能把所有窗口当独立来源。具体显著性检验由 RQ、比较单位与假设决定，不作为 qualification 的通过条件。

### 3.5 聚合必须与所回答的量一致

§II.B5 批评算术均值用于跨 benchmark 的 **overhead ratios**，其随 baseline 选择而变；作者主张 geometric mean。Appendix A.B5 明确接受 absolute overhead 的算术均值，以及用范围描述总体趋势。该建议不能机械改写成“任何压缩率、bytes 或时间只能用几何均值”。

**V4 推论：**压缩空间总体率应可从原始输入 bytes 和完整产物 bytes 重算；每数据集等权的 typical ratio 与按样本/bytes 加权的总体 storage ratio 回答不同问题。总体吞吐采用总 bytes/总时间，dataset 等权表现需另报。成对 speedup 可在预先固定同条件任务上用几何均值，并展示原始 absolute time。预先写权重、缺失/失败处理和共同子集分母，避免一张表里偷偷改变口径。

### 3.6 记录环境和真实对照，不等于要求系统饱和

§II.D、F 要求合适 baseline、公平配置、软件与硬件说明及子测试结果。§II.B2/§VI 关于“fully load CPU”的建议，针对安全 instrumentation overhead 被原有 idle/I/O wait 隐藏的情境；它不是要求时序压缩无论目标为何都必须占满所有核。

**V4 推论：**按线程预算比较一次请求延迟和并行吞吐，是两个合法工作负载。记录 compiler flags、SIMD dispatch、CPU affinity、线程数、GPU 和驱动/runtime、数据驻留；单线程任务不用改成全核饱和。原版、移植版、从零重写版应有 implementation 身份，变体之间不能把差异统称为算法差异。参考现有较强真实竞争方法，不能只有本项目旧版作为对照。

## 4. 能保留、应避免的具体设计

| 从此论文推导的有用设计 | 不应追加的框架负担 |
|---|---|
| 每任务原始观测、状态/原因、task matrix 分母 | 为每 trial 再跑一遍 22 类论文审查 |
| 同条件时间边界、真实可恢复产物和 absolute bytes/time | 固定 kernel 排名被自动叫作应用端到端排名 |
| 描述变异、按统计单位比较效果 | 小于任意波动阈值才能运行整个基准 |
| 在独立步骤记录内存等 RQ 所需资源 | 为得到压缩计时永久强制 collector |
| 源码/实现/配置/环境的必要身份 | 报告样式或不相关控制面变化使 codec 资格失效 |
| 合理说明不支持项、分层排名与覆盖 | 为追求完备要求每 codec 实现 GPU/SIMD/查询全部模式 |

这篇论文支持“精确测量、真实状态、清楚范围与证据”的方法，而不是“流程越重越科学”。轻量默认流程仍可是一份配置、相关资格缓存、校准/预热、重复请求与恢复校验、原始结果和描述报告；扩展实验依论文声明单独运行。

## 5. 与本轮其他来源的衔接

TerseTS 已有统一接口、pipeline 和可视化；FCBench 将压缩、查询与性能解释分问题；ALP 清楚展示 L1 microbenchmark 与 Tectorwise COMP/SCAN/SUM 的边界差异。本篇提供为何这种区分关系到结论有效性的解释。V4 最需要验证的不是增加流程文件，而是**相同输入对象、完整恢复成本、相同完成边界和完整失败覆盖是否会改变实际算法选择**。这些主张必须由新实验产生证据，不能从方法论论文直接推得结果。
