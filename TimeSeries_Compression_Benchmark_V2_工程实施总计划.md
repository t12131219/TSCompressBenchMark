# Time-Series Compression Benchmark V2.0 工程实施总计划

> 文档类型：可持续维护的工程建设、源码接入、验证、性能评测与报告计划  
> 当前实施语言：Python 控制面与规范执行层；原始源码作为算法数据面  
> 后续演进：可选 C/C++ Runner、C/C++ 规范执行组件及统一跨语言结果合同  
> 基线环境：`CompressBench14`（Python 3.14.5）  
> 编制日期：2026-09-10  
> 目标项目：`/home/fzg/PycharmProjects/TSDataCompressBenchMark`

---

## 0. 文档使用方式与结论先行

本计划不是“把若干压缩函数放进循环里计时”的任务清单，而是把 Benchmark V2.0 的每一条规范落实为：

1. 一个明确的数据或能力合同；
2. 一个有输入、输出和失败状态的流程节点；
3. 一个 Python 模块及稳定接口；
4. 一组单元、契约、边界、安全、正确性或性能测试；
5. 一条写入 `runs.csv`、`summary.csv` 和最终报告的可追溯证据链。

工程的正确起点是先建立“可验证的合同和最小闭环”，再逐批接入源码算法。第一条正式 Benchmark 路径必须完整经过数据登记、能力协商、适配、预检、正确性、计时、资源采集、最终比特核算和统计过滤。任何算法都不得绕过这些步骤直接向结果表写一个压缩率或速度。

推荐的总体实现方式是：

- Python 负责 Runner、配置解析、Registry、能力协商、任务展开、执行隔离、验证、资源采集、统计和报告。
- C/C++/Zig/Rust/Go/Java 等源码按其真实构建方式编译；Python 通过稳定 C ABI、Python 扩展、受控子进程或系统适配器驱动。
- 算法适配器只描述能力并执行操作，不自行决定公平性、是否可比、如何聚合或是否通过。
- 每次正式重复同时产生编码、Finalize、计费、解码、正确性和资源证据；流程图第 3 层和第 4 层是逻辑职责分层，不是对同一实验重新跑两遍。
- 未来 C/C++ Runner 与 Python Runner 共享同一份版本化 Schema、ID/Hash 算法、状态机和 Golden Fixtures；替换控制面不改变结果语义。

---

## 1. 输入材料、权威关系与解释规则

### 1.1 已审阅材料

| 材料 | 工程角色 | 本计划中的使用方式 |
|---|---|---|
| [`TimeSeries_Compression_Benchmark_Standard_v2.0_EdgeCase_Expanded.docx`](/home/fzg/PycharmProjects/材料/TimeSeries_Compression_Benchmark_Standard_v2.0_EdgeCase_Expanded.docx) | Benchmark Contract / 规范语义来源 | 定义对象、Track、可比性、公平性、正确性、性能、资源、统计和边界合同 |
| [`TimeSeries_Compression_Benchmark_项目构建注意事项_V2_Word完整融合增强版.md`](/home/fzg/PycharmProjects/材料/TimeSeries_Compression_Benchmark_项目构建注意事项_V2_Word完整融合增强版.md) | 实施合同 | 将 Word 规范细化为字段、状态、目录、测试与落盘要求；后部“V2 Word 强化实施合同”在冲突时优先于前部旧表述 |
| [`ChatGPT Image 2026年9月8日 12_32_44.png`](/home/fzg/temp/ChatGPT%20Image%202026年9月8日%2012_32_44.png) | 编排主线 | 五层流程及每层关键输入、输出、门禁和依赖关系 |
| [`pasted-text.txt`：结构图文字展开](/home/fzg/.codex/attachments/70e3e317-e03a-4d10-81c8-f14ea0184129/pasted-text.txt) | 流程细化 | 解释结构图中省略的分支、数据流和执行顺序 |
| [`pasted-text.txt`：三层抽象对齐分析](/home/fzg/.codex/attachments/e5376826-6c37-4fe7-85db-00d0745a9fae/pasted-text.txt) | 对齐校正 | 修正可比性键、Temporal Fidelity、Track 与执行阶段的误读 |
| [`Source_Code/README.md`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/README.md) 与 [`manifest.json`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/manifest.json) | 本地源码资产清单 | 形成源码目录、仓库、版本、语言、构建与接入审计的初始数据源 |

### 1.2 规范词强度

- **MUST**：不满足即不得生成可参与统计和排名的 `PASS` 结果。
- **SHOULD**：默认实现；未实现必须记录原因、影响范围和 `Coverage`，不得静默省略。
- **MAY**：扩展项；启用后仍须遵守统一 Schema、可追溯性和空值语义。
- 文档是项目 Benchmark Contract，不冒充外部标准组织发布的正式标准。

### 1.3 三项材料的裁决顺序

当材料存在表述差异时，按以下顺序裁决并在 `decision_log.md` 记录：

1. Word 中明确的规范语义和强制要求；
2. MD 后部的 V2 强化实施合同；
3. 流程图及其文字说明给出的执行顺序；
4. MD 前部的旧实现建议；
5. 现有 TSBench/算法仓库行为只能作为实现证据，不能反向覆盖规范。

### 1.4 必须固定的四个解释

1. `SemanticComparabilityKey → ExecutionComparabilityKey → ResourceProfileKey` 是逐级收紧的比较边界，不是三个并列分组键。空间/质量先按 Semantic 比；速度再要求 Execution 一致；资源再要求 Resource 一致。
2. Temporal Fidelity 是有损时序画像的 **SHOULD** 指标，不是所有有损算法的通用硬门禁。误差边界违反才是硬失败。
3. `Timestamp / Value / SYSTEM` 是顶层 Track 家族；T0–T2、V0–V4、P0–P3、ObjectLevel、LossMode 等是其下的正交细分。
4. 第 3 层“执行验证”和第 4 层“性能评测”共享同一次 Formal Repetition。禁止用一轮做正确性、另一轮做性能后把结果拼接成一个 Run。

### 1.5 Word 读取审计说明

Word 文件已通过 OOXML 结构完整提取正文和表格，确认无批注部件和修订标记；共识别 474 个段落、86 个表格、533 个表格行。受当前宿主机 GLIBC/GLIBCXX 与工作区内置 LibreOffice 运行时不兼容影响，本次无法生成页面渲染图，因此计划中凡涉及 Word 的结论均以结构化文本和表格内容为依据。最终交付物为 Markdown，不涉及 DOCX 版式修改。

---

## 2. 不可妥协的项目约束

### 2.1 数据语义

- 不得隐藏执行类型转换、转置、排序、去重、补空、插值、重采样、填充、截断、列抽样、时间归一化或算法回退。
- Timestamp 和 Value 必须独立建模、独立计费、独立验证；只有真实共享码字时才进入 SYSTEM/Joint 路径。
- Canonical Logical View 与 Physical View 必须分离。前者决定语义和分母，后者描述算法实际读取的字节布局。
- 时间戳默认 `int64`；单位、epoch、顺序、重复、乱序、负 delta、溢出策略必须显式。
- Value 保留原始 dtype、shape、channel 和 validity；MTS 不得只测一列后乘以列数。
- 异步、多实体、ragged、row-validity、cell-validity 数据不得被暗中规整成同步矩阵。

### 2.2 算法分类与可比性

- ObjectLevel：P0 primitive、P1 standalone codec、P2 pipeline、P3 storage/system。
- Track：Timestamp、Value、SYSTEM；细分 T0–T2、V0–V4。
- ImplementationClass：Conventional、Learned、HardwareAccelerated，与 ObjectLevel 正交。
- LossMode：LOSSLESS、ERROR_BOUNDED_LOSSY、RATE_CONTROLLED_LOSSY、SUMMARY_ONLY。
- ReconstructionMode：EXACT_GRID、APPROX_GRID、SPARSE_REPRESENTATION、SUMMARY_ONLY。
- 仅能力语义、预处理、重建语义、分块/状态等一致的结果才能进入同一 Semantic 分组。
- 实际 ISA、设备、线程、fallback、编译选项、执行组件共同形成 Execution 路径；声明支持不等于实际执行。

### 2.3 正确性与安全

- 无损整数逐元素精确；无损浮点按 IEEE 位模式精确，包括 `-0.0`、NaN payload 策略、Inf；不能只用 `==` 或 `allclose`。
- 有损先检查声明的原始误差合同，数值容差只能用于诊断判定器浮点误差，不能放宽算法误差界。
- 时间戳、value、validity、shape、channel order、T/V pairing 都必须验证。
- 输入不可修改；输出长度、容量、canary、safe-overread、尾块、空输入、Finalize 必须测试。
- N=0/1/2、窗口和块边界的 `B-1/B/B+1`、特殊浮点、扩张数据和不可压缩数据必须先过 Preflight。

### 2.4 计费与性能

- `FinalBits = SerializedBits + ExternalSideInformationBits`。
- SerializedBits 必须覆盖 T、V、shared、metadata、validity、dictionary、model、index、checkpoint、checksum、padding、container 等实际解码所需组件。
- Shared bit 只有在格式可分离时才能按真实字节归属；不可分配的共享位进入 `UnallocatedSharedBits`，禁止 50/50 猜分。
- 仅在最终物理流处执行一次 byte rounding；buffer capacity、内存对象大小和估计位数不得冒充 FinalBits。
- 正式结果至少保留 CORE、PIPELINE、E2E 三个 TimingScope 中适用的范围；主榜默认单线程。
- 每配置预热至少 3 次且累计至少 0.5 秒；正式重复至少 10 次，并保证每个计时范围有足够时长；必须保存每次原始观测。
- Python/FFI 拷贝、适配器布局转换、进程启动、I/O、模型加载和设备传输是否计入，必须由 TimingScope 明示。

### 2.5 统计与报告

- `runs.csv` 逐 repetition 写入，不得只保存最佳值或平均值。
- `summary.csv` 只能聚合同一 `ConfigID + ExecutionPathHash` 且状态为 `PASS` 的 Run。
- 每数据集先统计，再做 micro、geometric mean 或覆盖率聚合；禁止先拼接数据再掩盖数据集差异。
- 所有参数点都保留；不允许事后只挑对某算法有利的配置。
- 排名必须同时公布 Eligibility、Coverage、失败状态和比较键，不能把不支持样本当成零分或静默删除。

---

## 3. 当前资产与差距审计

### 3.1 目标项目现状

`/home/fzg/PycharmProjects/TSDataCompressBenchMark` 当前没有 Benchmark 框架源码、配置、Schema 或 Git 元数据，只有数据集和既往 `.pytest_cache`。因此第一阶段必须从仓库骨架和合同测试开始，不能在不存在的 Runner 上直接批量接算法。

### 3.2 源码资产现状

本地 [`Source_Code`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code) 已登记：

- 221 个逻辑条目：Value 89、Timestamp 110、TSBench 22；
- 72 个去重 GitHub 仓库；71 个已下载/复用，1 个不可直接获取；
- 221 份 metadata，219 个 `code` 符号链接；
- 当前 71 个 checkout 均为 clean，但多为 shallow checkout，计划中必须保存当前 commit，而不能只保存分支名；
- 语言横跨 C、C++、Python、Java、Go、Rust、Zig、CUDA/HLS、MATLAB 等；“Python 驱动源码”必须通过多种 Adapter 完成，不应强行改造成 Python 包；
- 26 个仓库根目录可见 CMake、21 个可见 Makefile、13 个 Python 包、8 个 Maven、3 个 Cargo、2 个 Go module、1 个 Zig；部分构建入口位于子目录，需在源码准入审计中重新探测；
- `NVIDIA/nvcomp` 当前 checkout 只是归档说明，真实样例已移到另一仓库；`Xilinx/lz4-decompression-opt` 需要外部 zip 与 Vitis；`fahaihi/NNLCB` 只有结果和说明；ModelarDB-RS 当前不可用。它们不能被标成“已接入”。

清单中的“算法条目”与“可独立执行的 codec”不是一一对应。例如多个名称指向同一仓库、Delta/BitPack 可能只是 primitive、Prometheus XOR2 是 T/V joint codeword、ClickHouse Delta 是预处理器、SciPy/PCA 是表示变换而非自包含 bitstream。Registry 必须保留这种层级差异。

本次源码审计采用两层扫描：第一层对 72 个仓库递归建立文件、语言、构建入口、binding、benchmark、test、license 和 checkout 状态索引，并排除 `.git`、既有 build 与明显生成目录；整个 `Source_Code` 树约 150,880 个文件，其中可见 Python 约 6,149、C++ 约 9,250、C 约 3,774、Java 约 10,225，说明不能通过人工逐文件线性阅读来形成可靠架构。第二层按接入风险和规范节点语义阅读关键实现/API/benchmark/test，包括 TerseTS、lzbench、Sprintz、ALP/FastLanes、zfp、Serf、NeaTS、ClickHouse、Prometheus、Timescale、Apache TsFile、LZ4、Zstd 与 Snappy。Phase 0 的 `audit_sources.py` 要把这次探索性扫描固化为可重复机器报告；后续每接一个算法，再对实际参与构建的 translation units 做闭包级阅读和记录。

### 3.3 源码清单质量风险

- 当前语言探测主要依赖扩展名；例如 TerseTS 实际主体是 Zig，但 metadata 曾被 Rust 文件数量误判。必须重建包含 Zig/CUDA/HLS/生成代码排除规则的语言统计。
- `apache/iotdb` 与 `apache/tsfile` 都在清单中，实际底层 codec 的当前 C++/Java 参考应优先定位到 `apache/tsfile`，不能只按清单 URL 猜入口。
- 同一 checkout 被多个条目复用时，应共享 `SourceArtifactID`，但各自拥有不同 `AlgorithmID`、能力声明和 pipeline 定义。
- 没找到许可证文件不等于没有许可证；必须人工确认仓库根、子模块和复用代码。Serf README 明确为 CC BY-NC，至少需要一个“允许运行但限制再分发/商用”的法律标记。
- 大型仓库包含 vendored 第三方、生成文件、测试数据与多个语言实现。扫描记录必须区分项目代码、vendored code 和实际被链接目标。

### 3.4 本机与 Conda 环境

已验证环境：

| 项目 | 当前值 | 工程影响 |
|---|---|---|
| OS / Kernel | Ubuntu 22.04 系、Linux 6.8、glibc 2.35 | 部分预编译工具要求更新 glibc，构建必须检测 ABI |
| CPU | Intel i5-13400F，10 cores/16 threads，1 NUMA，AVX2，无 AVX-512 | 可建立 scalar/SSE/AVX2 路径；不能伪造 AVX-512 结果；P/E core 异构需固定 CPU 集 |
| Python | `CompressBench14`，Python 3.14.5 | 老旧 setup.py/Cython/深度学习项目可能不兼容，需子环境或独立进程，不污染主 Runner |
| Python 包 | NumPy 2.5.3、Pandas 3.0.5、PyArrow 25、psutil 7.2、pytest 9.1、pybind11 3.1、lz4/zfpy/pyfastpfor 等 | 可用于控制面和 oracle；正式算法仍需记录实际源码构建与 binding 路径 |
| 系统编译器 | GCC/G++ 11.4、CMake 3.22、Make 4.3 | 与 Conda 打包 Python 的 GCC 14.3 标记不同；扩展 ABI 和 C++ runtime 必须实测 |
| 其他 | Rust 1.94、Go 1.18、Java 21；系统无 Zig、numactl、ninja；NVIDIA 驱动不可用 | TerseTS、GPU/HLS 不能在当前机器直接作为正式可运行项；应产生明确 UNSUPPORTED，而非失败或回退 |
| Perf | `perf 6.8.12` 可见 | 仍需测试 `perf_event_paranoid`、计数器权限和 multiplex ratio |

主环境只承载 Runner 及稳定 Python 依赖。每个 native/legacy/learned codec 允许有独立 ToolchainProfile 和 WorkerEnvironment，但其环境哈希必须进入 ExecutionPathHash。

### 3.5 当前数据集清单

所有现有文件均已读取头部/shape 并计算 SHA-256。Dataset Registry 首批应直接导入以下事实，而不是运行时猜测：

| 文件 | shape | 物理类型/特点 | SHA-256 前 12 位 |
|---|---:|---|---|
| ETTh1.csv | 17,420 × 8 | date + 7 value columns | `f18de3ad269c` |
| ETTh2.csv | 17,420 × 8 | date + 7 value columns | `a3dc2c597b92` |
| ETTm1.csv | 69,680 × 8 | date + 7 value columns | `6ce1759b1a18` |
| ETTm2.csv | 69,680 × 8 | date + 7 value columns | `db973ca252c6` |
| PEMS03.npz | 26,208 × 358 × 1 | `float64`、C-contiguous，无 NaN | `34859517425e` |
| PEMS07.npz | 28,224 × 883 × 1 | `float64`、C-contiguous，无 NaN | `a07887e610aa` |
| electricity.csv | 26,304 × 322 | date + 321 value columns | `7e45845d54c5` |
| exchange_rate.csv | 7,588 × 9 | date + 8 value columns | `48b4d9d3d508` |
| national_illness.csv | 966 × 8 | date + 混合量纲的 7 列 | `93601f64d256` |
| pems04.npz | 16,992 × 307 × 3 | `float64`、三特征、无 NaN | `95a3c9b720ff` |
| pems08.npz | 17,856 × 170 × 3 | `float64`、三特征、无 NaN | `e1d03ce74e9f` |
| traffic.csv | 17,544 × 863 | date + 862 value columns | `cb06463d56fa` |
| weather.csv | 52,696 × 22 | date + 21 value columns；当前头部存在编码乱码 | `34ee981d0731` |

数据集风险与决定：

- CSV 文本中的小数应通过明确的 parser 和目标 dtype 生成 Canonical Binary；不得把 CSV 文件字节大小当 RawBits。
- NPZ 没有显式时间戳，必须由数据集 Manifest 声明“无 T”或根据有来源证据的规则构造 regular grid；构造出来的 T 属于数据语义，不可由 Loader 静默生成。
- PEMS 的第三维是特征轴，不应未经声明 flatten；需要 TopologyProfile 和 channel mapping。
- `national_illness` 含百分比和计数列；自动统一成 float 虽方便但会改变整数列语义，应支持 heterogeneous dtype 或显式 adapter。
- `weather.csv` 列名存在 mojibake，修正名称不能改变 DatasetID 所依据的原始文件；应在 Manifest 中保存 raw header bytes 与规范化 display name。
- 现有真实数据不足以覆盖重复时间戳、乱序、NaN payload、Inf、整数极值、ragged validity 和 boundary，因此必须另建合成与 adversarial fixtures。

### 3.6 当前差距清单

| 差距 | 若不处理的后果 | 首次关闭阶段 |
|---|---|---|
| 无项目骨架/Schema/状态机 | 各适配器自行定义结果 | Phase 0–1 |
| 无 Dataset/Codec Registry | 数据和算法不可追溯 | Phase 1–2 |
| 无统一 Adapter ABI | Python/native/CLI 行为不可比 | Phase 2 |
| 无 bit accounting | 压缩率失真 | Phase 1–3 |
| 无 Preflight/正确性门禁 | 错误算法也能出性能结果 | Phase 1–3 |
| 无 ExecutionPath 实测 | scalar fallback 与 SIMD 混比 | Phase 2–3 |
| 无 raw run/统计过滤 | 最快一次和失败结果污染排名 | Phase 1、5 |
| 现有源码完整性不一 | 构建失败被误判为算法失败 | Phase 0、每次 onboarding |
| Python 3.14 兼容风险 | 老代码拖垮主环境 | Phase 0–2 |
| 当前机器无 GPU/Zig/HLS | 隐式跳过导致 Coverage 虚高 | Phase 2、报告层 |

### 3.7 当前状态自省检查

- [x] 已区分“逻辑算法条目”“去重源码仓库”“可执行 codec”。
- [x] 已检查目标项目不是已有完整框架，计划从合同骨架开始。
- [x] 已使用指定 Conda 环境验证 Python 与关键包。
- [x] 已对 13 个数据文件记录 shape、格式与 hash。
- [x] 已发现当前硬件、编译器和工具缺口，并将其设计为能力状态而非隐式回退。
- [ ] 在开始实现前，仍需把 72 个 repo 的 commit、许可证、子模块、构建入口和源码完整性固化为版本化 `source_catalog.json`。

---

## 4. 目标架构：Python 控制面、源码数据面、跨语言合同

### 4.1 逻辑架构

```text
CLI / Experiment Config
          |
          v
Python Orchestrator --------------------------------------------------+
  Dataset Registry -> Canonical Loader -> Characterizer               |
  Codec Registry -> Negotiator -> Adapter/Preprocess -> Task Planner  |
  Preflight -> Formal Repetition -> Validation/Accounting/Resources   |
  Raw Run Store -> Statistics -> Eligibility/Pareto/Report            |
          |                                                           |
          +-------------------- Execution Protocol -------------------+
                               |          |          |          |
                         Python API    C ABI/FFI  Subprocess   System/Device
                               |          |          |          |
                         Python source  C/C++/...  CLI/Java/Go  TSDB/GPU/FPGA
```

这里的关键隔离是：编排状态机、规范判断和结果 Schema 属于框架；编码细节、内存上下文和源码构建属于适配器。适配器可以报告事实，不能自行把 `BOUND_VIOLATION` 改成 `PASS`，也不能删除失败 repetition。

### 4.2 建议项目目录

```text
TSDataCompressBenchMark/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
├── configs/
│   ├── experiments/              # 用户实验配置；只引用 registry ID
│   ├── profiles/                 # timing/resource/correctness/fairness profiles
│   └── sweeps/                   # 可审计参数网格
├── schemas/
│   ├── v2/                       # JSON Schema；跨 Python/C/C++ 的真值来源
│   └── fixtures/                 # Schema 正反例
├── registry/
│   ├── datasets/                 # 一数据集一 manifest
│   ├── codecs/                   # 一 AlgorithmID 一 manifest
│   ├── sources/                  # SourceArtifactID、commit、license、build
│   ├── environments/             # EnvironmentID / ToolchainProfile
│   └── rebuild_protocols/        # sparse/summary 重建协议
├── src/tscompbench/
│   ├── cli.py
│   ├── runner.py
│   ├── contracts/                # enum、dataclass、schema 校验、版本迁移
│   ├── ids/                      # canonical JSON、ID 和 hash
│   ├── datasets/                 # registry、loaders、canonical、characterize
│   ├── codecs/                   # registry、capability、negotiation
│   ├── adapters/                 # base、python、ctypes、extension、cli、system
│   ├── preprocess/               # 显式算法预处理及 validator
│   ├── planning/                 # sweep、task graph、execution resolution
│   ├── execution/                # isolation、preflight、repetition、timeout
│   ├── validation/               # lossless、lossy、pairing、memory、determinism
│   ├── accounting/               # FinalBits 与组件账本
│   ├── measurement/              # timing、CPU、memory、I/O、counter、energy
│   ├── workloads/                # query、random access、streaming
│   ├── storage/                  # append-only runs、artifacts、resume
│   ├── statistics/               # eligibility、aggregate、CI、Pareto、coverage
│   └── reporting/                # CSV/JSON/Markdown/HTML 生成
├── native/
│   ├── include/tscb_adapter_v1.h # 稳定 C ABI；C/C++ Runner 也使用
│   ├── shims/                    # 薄封装，不复制算法实现
│   └── runner/                   # 后续可选 C/C++ Runner
├── adapters/
│   └── <algorithm_id>/           # 每算法 binding、manifest、patches、tests
├── tools/
│   ├── audit_sources.py
│   ├── build_codec.py
│   ├── make_dataset_manifest.py
│   ├── inspect_execution_path.py
│   └── validate_results.py
├── tests/
│   ├── unit/
│   ├── contracts/
│   ├── adapters/
│   ├── integration/
│   ├── boundary/
│   ├── safety/
│   ├── golden/
│   └── performance_smoke/
├── datasets/                     # 当前原始数据；正式运行只读
├── fixtures/                     # 小型合成/对抗数据，可进版本库
├── build/                        # out-of-tree 构建产物，不进版本库
├── runs/<RunSetID>/
│   ├── frozen_config.json
│   ├── environment.json
│   ├── task_plan.jsonl
│   ├── runs.csv
│   ├── run_components.jsonl
│   ├── summary.csv
│   ├── artifacts/
│   └── report/
└── docs/
    ├── architecture.md
    ├── contracts.md
    ├── adapter_authoring.md
    ├── source_audit.md
    └── decision_log.md
```

### 4.3 依赖方向

`contracts`、`ids` 不得依赖具体 codec；`statistics` 只能读取已冻结的结果合同；`reporting` 不得重新计算正确性；`adapters` 不得 import `statistics` 或自行写 CSV。建议用架构测试扫描 import graph。

### 4.4 配置格式决定

规范层以 JSON Schema + canonical JSON 为跨语言真值。人类可编辑配置可以使用 TOML（Python 3.14 标准库可读）或 YAML；若使用 YAML，必须锁定 parser 版本，并将解析后的 canonical JSON 作为 Run 的冻结配置。ID 绝不对原始 YAML 文本求 hash。

### 4.5 未来 C/C++ 适配原则

- `schemas/v2`、C ABI header、状态码数值、枚举、canonical JSON 测试向量必须版本化。
- Python Runner 和未来 Native Runner 都产生同样的 `RunRecord`；语言只进入 `RunnerImplementation` 和 ExecutionPath。
- C/C++ 实现规范判断时，需与 Python 对同一 Golden Fixture 产生字节相同的 ID、相同状态和相同 FinalBits。
- 不把 Python 对象地址、pickle 或 NumPy 私有 ABI 放入长期协议；跨进程优先 Arrow C Data Interface、固定 little-endian binary view 或自定义版本化 flat header。
- Native shim 只暴露 create/destroy/capabilities/compress/finalize/decompress/reset/query/account/error 等窄接口；异常不得跨 C ABI。

### 4.6 架构自省检查

- [x] Python 是当前框架与规范执行主体。
- [x] 原始源码不被重写后才接入；通过 binding/ABI/CLI/system 适配。
- [x] C/C++ 后续版本不是另建一套结果语义，而是共享合同。
- [x] 规范层与算法层、统计层与报告层具有单向依赖。
- [x] 源码构建失败、环境不支持和算法正确性失败拥有不同状态。

---

## 5. 核心数据模型、ID 与状态机

### 5.1 必需实体

| 实体 | 最少内容 | 稳定标识 |
|---|---|---|
| `DatasetManifest` | source hash、许可/来源、schema、T/V/validity/topology、单位、解析策略、canonical policy | `DatasetID` |
| `CanonicalDataset` | logical arrays、physical descriptors、raw bits、mapping、characterization | DatasetID + CanonicalFormatVersion |
| `SourceArtifact` | repo/url、commit、dirty、submodule、license、build recipe、patch hash | `SourceArtifactID` |
| `CodecManifest` | 算法身份、源码、ObjectLevel、Track、dtype/shape/loss/topology 能力、参数 Schema | `AlgorithmID` |
| `AdapterManifest` | adapter version、backend kind、copy/alloc/state/finalize/account semantics | `AdapterID` |
| `ExperimentConfig` | dataset/codec selectors、profiles、sweep、seed、limits | `ExperimentConfigID` |
| `ResolvedConfig` | 单个参数点及已解析所有默认值 | `ConfigID` |
| `ExecutionResolution` | binary hash、actual ISA/device/thread/fallback、env/toolchain | `ExecutionPathHash` |
| `BenchmarkTask` | DatasetID × AlgorithmID × ConfigID × track/profile | `TaskID` |
| `RunRecord` | repetition 原始观测、状态、正确性、时间、资源、计费键 | `RunID` |

### 5.2 ID 生成

所有 ID 都采用：版本前缀 + domain tag + canonical JSON 的 SHA-256。Canonical JSON 必须固定 UTF-8、Unicode normalization、键排序、整数/布尔/null 表示；浮点配置不得依赖语言默认字符串，建议用十进制字符串或 IEEE hex。路径先转换成内容 ID，禁止绝对路径直接进入跨机器语义 ID。

`ConfigID` 必须包含所有影响输出或工作量的参数，包括算法默认参数的展开值。`ExecutionPathHash` 必须包含实际加载的 binary SHA-256、编译器与 flags、ISA、device、线程、运行库、adapter、fallback、环境锁和关键动态库；源码 commit 仅是其中一项，不能替代 binary hash。

### 5.3 逐级可比性键

```text
SemanticComparabilityKey
  = track + object level + loss/reconstruction + canonical semantics
  + adapter/preprocess semantic class + block/state/window + error contract

ExecutionComparabilityKey
  = SemanticComparabilityKey + timing scope + allocation/cache/JIT/GC policy
  + actual ISA/device/thread/fallback + runner/adapter boundary

ResourceProfileKey
  = ExecutionComparabilityKey + resource scope + counter/energy method
  + process tree/cgroup/device attribution + sampling policy
```

任何字段未知都不能通过删除该字段获得可比性。未知应为 `UNSPECIFIED` 并让 Eligibility 明确拒绝对应比较。

### 5.4 Capability Negotiation 四态

- `DIRECT_SUPPORTED`：canonical physical view 可直接传入，语义不变。
- `ADAPTER_LOSSLESS`：需要显式无损适配；适配成本按 profile 进入 PIPELINE/E2E。
- `ADAPTER_LOSSY`：需要有损转换或量化；只能路由到有损 Track，禁止仍挂 lossless 标签。
- `UNSUPPORTED`：不得调用算法；立即产生包含原因与缺失 capability keys 的 RunRecord。

Negotiation 结果必须是结构化 `CompatibilityPlan`，列出每个操作、前后 dtype/shape/layout、额外 bits、copy bytes 和语义等级。布尔 `supports=True` 不足以审计。

### 5.5 状态与原因码

至少支持：`PASS`、`UNSUPPORTED`、`ADAPTER_LOSSY_ROUTED`、`ISA_UNSUPPORTED`、`BUILD_UNAVAILABLE`、`SOURCE_INCOMPLETE`、`LICENSE_RESTRICTED`、`HARNESS_CAPACITY_ERROR`、`MEMORY_SAFETY_FAIL`、`RESOURCE_PRESSURE`、`OVERSUBSCRIBED`、`CORRECTNESS_FAIL`、`BOUND_VIOLATION`、`OOM`、`TIMEOUT`、`INCOMPARABLE`、`NONDETERMINISTIC`、`CRASHED`、`SCHEMA_ERROR`。

状态与数据空值分离：

- `UNSPECIFIED`：该属性本应声明但未知；通常阻止对应比较。
- `NOT_APPLICABLE`：概念不适用，例如 CPU-only 的 GPU energy。
- `UNSUPPORTED`：请求适用但实现不支持。
- 数值 `0` 是真实观测，绝不能兼作缺失。

### 5.6 Run 状态机

```text
PLANNED -> RESOLVED -> PREFLIGHTING -> PREFLIGHT_PASS
        -> WARMING -> RUNNING -> VALIDATING -> ACCOUNTING -> PASS
        \-> terminal non-PASS status at any gate
```

每个状态转换先写 append-only event，再执行下一步。进程崩溃后可据 event log 恢复，未完成的 repetition 标为 `CRASHED/INTERRUPTED`，不得覆盖。

---

## 6. 第一层：Data Preparation / 数据准备

严格步骤：`Benchmark Runner 启动 → Experiment Config/Environment → Dataset Registry → Canonical Loader → Dataset Characterization`。

### 6.1 启动 Benchmark Runner

输入：配置路径、输出根目录、resume/run-id 选项。  
输出：`RunSetID`、启动事件、只读配置快照路径。  
实现：`cli.py` 只做参数解析；`runner.py` 创建 run workspace、文件锁、日志和状态存储。

约束与门禁：

- 禁止覆盖既有 `RunSetID`；resume 必须验证冻结配置和 Schema 版本相同。
- 原始数据和源码目录默认只读；构建写入项目 `build/`，运行写入 `runs/`。
- 启动时验证磁盘空间、文件句柄、计时器、进程隔离和输出原子追加能力。
- Runner 版本、Git commit/dirty、Python executable、命令行完整落盘。

测试：重复启动、并发同 ID、损坏 event log、只读源目录、SIGINT 恢复。

### 6.2 加载 Experiment Config 与 Environment

输入：人类配置、Profile、环境。  
输出：解析后 canonical config、EnvironmentManifest、ExperimentConfigID。

必须采集：OS/kernel/glibc、CPU model/topology/features、内存、NUMA、governor/turbo、Python/编译器/CMake、动态库、容器/Conda、环境变量白名单、BLAS/OpenMP/MKL/TBB 线程设置、GPU/driver（若有）、时钟源、perf 权限。

配置解析必须：拒绝未知字段；展开默认值；校验互斥项；记录未指定字段；对路径解析成内容哈希。不得让算法 wrapper 从全局环境偷偷读取未登记参数。

本机特别措施：固定一组同类核心并记录 affinity；由于 i5-13400F 为 P/E 异构设计，首版主榜不能随意跨全部 16 logical CPUs。若无法稳定区分核心类型，先采用经校准的单核 CPU set，并将校准证据落盘。

### 6.3 Dataset Registry

输入：dataset manifests。  
输出：DatasetID、文件完整性结果、逻辑 Schema、解析计划。

Manifest 必需字段：

- 来源、许可、原始文件相对路径、bytes、SHA-256；
- parser 名称/版本/参数、编码、分隔符、时区、缺失标记；
- T 列或构造规则、单位、epoch、允许 duplicate/out-of-order；
- V 列、每列 dtype/单位/entity/feature、MTS coupling 意义；
- validity 表示和 topology；
- canonical target dtype policy；
- 预期 shape 与最小/最大约束；
- split（train/validation/test）及 learned 数据泄漏边界。

注册时只验证文件与 Manifest，不做隐式数据修复。文件内容变化必须生成新 DatasetID。

### 6.4 Canonical Loader

输入：已验证 Manifest。  
输出：`CanonicalDataset(T, V, validity, topology, descriptors)` 和 canonical binary artifacts。

建议实现：

- `T`: little-endian `int64[N]`；若无 T，显式 `T=None` 或由 Manifest 认可的规则产生，并记录 `TimestampOrigin`。
- UTS `V`: `dtype[N]`；MTS 默认 `V[N,M]`；native ND 可保留 `[N,D1,...]`，同时记录 axes。
- heterogeneous columns 采用 per-column buffers + dtype vector，不强制统一 NumPy dtype。
- validity 分开保存，不能把 NaN 自动当 null，除非 Manifest 明确如此。
- 生成 `LogicalViewDescriptor` 和一个或多个 `PhysicalViewDescriptor`；算法只能请求已登记 physical view。
- Canonical Binary 以 header + raw buffers + hash 或 Arrow IPC 实现均可，但格式必须版本化、可从 C/C++ 映射并有 Golden Bytes。

Loader 在读取 CSV 时先按声明 parser 解析；不得因 Pandas dtype inference 在版本升级后改变结果。日期解析、时区、DST、整数溢出和十进制到 float 的舍入都要有 fixture。

### 6.5 Dataset Characterization

输入：CanonicalDataset。  
输出：characterization JSON、完整性摘要、报告可用画像。

Timestamp 至少统计：范围、delta/DoD 分布与分位数、CV、零 DoD、regularity、gap、duplicate、out-of-order、负 delta、近似 entropy。Value 至少统计：每列 min/mean/std/max/range/quantile、unique/repeat、NaN/Inf/-0、entropy proxy、ACF；高成本 PSD/seasonality/derivative/extrema 可按 profile 开启。

画像不改变数据。对大矩阵允许分块/流式计算，但 exact 与 sampled 指标必须分栏，记录采样 seed、样本数和算法版本。

### 6.6 第一层输出合同

- DatasetID 与 DatasetManifest；
- Canonical Binary Data 与 hash；
- canonical logical/physical descriptors；
- Dataset Characterization；
- loader/characterizer provenance。

### 6.7 第一层自省检查

- [ ] 原始 CSV/NPZ bytes 从未作为统一 RawBits 分母。
- [ ] 所有 dtype、T 构造、transpose、flatten 和 validity 规则都来自 Manifest。
- [ ] PEMS 三维结构未被静默拉平。
- [ ] 所有 loader 输出可由 hash 重现。
- [ ] characterization 只读，不把清洗结果反馈给 benchmark 输入。
- [ ] Word/MD 中“统一 canonical、无隐藏预处理、完整记录数据特征”都有模块和测试落点。

---

## 7. 第二层：Capability & Configuration / 能力与配置

严格步骤：`Codec Registry → 算法属性识别 → Capability Negotiation → Adapter → Post-Adapter Validation → Algorithmic Preprocess → Preprocess Validation → Semantic Key → Sweep/ConfigID → Task Matrix → Execution Resolution`。

### 7.1 Codec Registry 与 Source Registry

每个 AlgorithmID 的 manifest 必须回答：它是什么，而不仅是“代码在哪”。必填项包括：

- display name、family、引用、SourceArtifactID、commit、license；
- ObjectLevel、Track、T/V/SYSTEM、T0–T2/V0–V4；
- supported dtype/width、shape/rank、layout/endian/alignment；
- monotonicity、duplicate、out-of-order、negative delta、overflow policy；
- ValueCouplingMode：COLUMN_INDEPENDENT、GROUPED_CHANNELS(k)、FULL_MATRIX、NATIVE_ND_ARRAY；
- LossMode、ErrorBoundType、ReconstructionMode、RebuildProtocol；
- block/window/history/state/reset/finalize、dictionary/model/index；
- supported ISA/device/threading、fallback policy、safe overread/tail；
- streaming/query/random access 能力；
- 参数 Schema、默认值、非法组合和资源上限；
- adapter backend 及 timing/accounting hooks。

Source Registry 另外保存 build recipe、patches、submodule、compiler、artifact hash、自测命令。不得把 AlgorithmID 与 shared library 文件名绑定。

### 7.2 源码准入审计 SOP

每个仓库在写 adapter 前完成以下卡片：

1. 冻结 URL、commit、dirty、submodule 和 archive 完整性。
2. 定位真实实现文件、公共 API、benchmark/test、许可证和第三方依赖。
3. 识别 primitive/codec/pipeline/system，防止错误分类。
4. 记录输入 dtype、shape、layout、最大长度、alignment、padding、ownership。
5. 记录 output bound、返回长度、错误码、Finalize/Flush、reset 和上下文复用。
6. 记录实际 stream 中的 header/metadata/model/index；确定 FinalBits 可否精确拆分。
7. 运行上游自测并保存日志；上游自测通过不等于 Benchmark 资格通过。
8. out-of-tree 构建 release/debug/sanitizer 版本；保存编译命令与二进制 hash。
9. 许可证决定 `RUN_ALLOWED/REDISTRIBUTION_RESTRICTED/REVIEW_REQUIRED/BLOCKED`。
10. 建立 known limitations 和 unsupported reason codes。

源码目录保持原样；必要补丁放到 `adapters/<id>/patches` 并记录 patch hash，不直接在共享 `_repos` 中形成未记录改动。

### 7.3 属性识别与 Capability Negotiation

Negotiator 以 dataset logical/physical descriptors、codec capability 和请求 profile 为输入，产出四态结果与 `CompatibilityPlan`。

示例：TerseTS Python wrapper 只接受 C-contiguous float64，并会暗中 `ascontiguousarray(dtype=float64)`。框架必须在调用前自行决定：float64 非连续输入是 `ADAPTER_LOSSLESS`；float32→float64 是精确 widen 但改变 raw denominator/physical bytes，必须显式标记；任何 float64→float32 都是 `ADAPTER_LOSSY`。wrapper 内部拷贝若无法关闭，必须在 PIPELINE/E2E 中记录且通过 adapter telemetry 暴露。

Timestamp 还需逐项协商 preserve order、absolute epoch、gap、duplicate、negative delta、checked overflow。需要排序才能运行的算法对当前 dataset 不是 lossless adapter，而是语义改变；不得在 Timestamp lossless 主榜中伪装支持。

### 7.4 Compatibility Adapter

允许的无损 physical adapter：transpose、gather、stride materialization、alignment copy、exact widening、endianness conversion、safe-overread padding、device staging、显式 null materialization。每个操作都输出：

- `operation_id`、before/after descriptor；
- semantic class；
- bytes read/written、allocation、padding、external metadata bits；
- 是否计入 CORE/PIPELINE/E2E；
- reverse mapping 与验证方法。

禁止 Adapter：静默排序、丢 null、插值、量化后仍标 lossless、选择“最好列”、根据结果改变参数。

### 7.5 Post-Adapter Validation

用独立 validator 检查：转换前后 logical content、shape、channel、validity、T/V pairing 一致；padding 不进入 RawBits；算法不可读取未授权 padding 之外内存；输入不可变。不能让执行 adapter 自证正确。

### 7.6 Algorithmic Preprocess

预处理枚举：`NONE`、`LOSSLESS_LAYOUT`、`LOSSLESS_SEMANTIC`、`LOSSY_PREPROCESS`、`TRAINING_LEARNED`。

Delta、DoubleDelta、ZigZag、FOR、PCA、quantization、dictionary training 等必须作为 pipeline stage 明示。ClickHouse 源码明确把 Delta 称为 preprocessor 且输出带 header，适合作为 P0/P2 区分的参考。Sprintz 把 float 量化为 8/16 bit 后测试的行为必须归入有损预处理，不能与原 float lossless codec 同组。

Pipeline 的 A/B/C/D 四阶段分别记录：A logical representation、B serialization/bitpacking、C backend compressor、D system wrapper。每阶段可开关、可计时、可核算，禁止把 A+C 的结果称作 C 算法本体。

### 7.7 Preprocess Validation

- 无损 preprocess：inverse 后执行完整 bit-exact 验证。
- 有损 preprocess：单独验证其 bound，并把后续 codec 误差组合到总合同。
- learned：验证 train/validation/test split、seed、checkpoint、模型 bits 和首次使用成本。
- stateful：验证 reset、独立 block 和 continuous stream 两种语义。

### 7.8 Parameter Sweep 与 ConfigID

Sweep generator 必须做笛卡尔展开、条件约束和资源预算预估；每个参数点都生成 ConfigID。非法组合在执行前产生 `UNSUPPORTED/SCHEMA_ERROR`，不能静默删除。默认值也写入 ConfigID；浮点误差界使用规范化十进制。

公平调参时，调参数据与测试数据分离；所有候选及选择规则落盘。报告可展示 Pareto 前沿，但 raw 表保留被支配点。

### 7.9 Task Matrix

基础任务键为 `DatasetID × AlgorithmID × ConfigID × BenchmarkTrack × ProfileID`。任务生成前就计算预计 workload、资源上限、dependencies 和 skip reason。按确定顺序输出 `task_plan.jsonl`，同 seed 重建必须字节一致。

### 7.10 Execution Resolution

执行前实测并冻结：

- adapter/backend、binary/library hash、动态依赖；
- requested/actual ISA、vector lanes、alignment、tail path、fallback；
- CPU affinity、threads、processes、SMT、NUMA、OMP/BLAS/MKL/TBB；
- device、driver、runtime、batch、stream、transfer、sync；
- runner/worker Python 或 native 版本、GC/JIT policy；
- allocation/cache/state/repetition semantics。

CPU 无某 ISA 时：若 manifest 禁止 fallback，写 `ISA_UNSUPPORTED`；若允许 scalar fallback，则实际路径可以 PASS，但必须使用不同 ExecutionPathHash 和可比组。

### 7.11 第二层输出合同

- AlgorithmID / CodecManifest / SourceArtifactID；
- ConfigID 与完整参数；
- CompatibilityPlan 及四态；
- TaskID 列表；
- ExecutionResolution、ExecutionPathHash；
- Semantic/Execution/Resource keys。

### 7.12 第二层自省检查

- [ ] 所有 221 条目先分类，再决定是否可作为独立 AlgorithmID。
- [ ] adapter 和 preprocess 可观察且分别验证。
- [ ] `UNSUPPORTED` 也进入 runs，不从任务表消失。
- [ ] ConfigID 包含展开后的全部默认参数。
- [ ] actual ISA/device/thread/fallback 来自运行时证据。
- [ ] semantic、execution、resource 三个键按逐级关系构造。

---

## 8. 第三层：Execution & Validation / 执行与验证

严格步骤：`Track 路由 → Input Validation → Boundary/Safety Dry-run → Preflight Gate → Formal Repetitions → Compress → Finalize/Flush → Accounting → Decompress → Common Correctness → Loss Gate`。

### 8.1 Track 路由

- Timestamp Benchmark：只把 T 作为被压对象；V 不进入算法输入。
- Value/Multivariate Benchmark：只把 V 作为被压对象；T 仅可用于有损 temporal metrics 的对齐依据，不能计入 codec input。
- SYSTEM Benchmark：必须使用共同 SegmentPlan，把 T、V、validity、shared header、assembly 组成真实可解码系统流；禁止分别挑 T 最优和 V 最优后相加。

Prometheus `xor2.go` 使用 timestamp+value 联合 control bits，应作为 SYSTEM + `JOINT_CODEWORD`，不能强拆到 Timestamp 和 Value 独立榜。Timescale Gorilla container 中 header、tag arrays、bit arrays、nulls 同样提示系统计费必须以真实序列化对象为准。

### 8.2 Input Validation

执行前验证实际 buffer 与任务合同一致：dtype、itemsize、shape、strides、endianness、alignment、length、T/V pairing、validity、范围、NaN/Inf、拓扑、block/window。将输入 hash 写入 repetition；验证后到执行结束必须保持不可变。

### 8.3 Boundary / Safety Dry-run

每 AlgorithmID × execution path 至少覆盖：

- N：0、1、2、`minWindow-1/minWindow/minWindow+1`、`B-1/B/B+1`、`2B-1/2B/2B+1`；
- M：1、2、3、4、7、8、9、15、16、17、32、64（适用时）；
- layout：C/F/strided/misaligned/required alignment；
- integer：0、±1、min/max、delta 和 DoD 溢出序列；
- float：±0、normal、subnormal、±Inf、多个 NaN payload、相邻 bit pattern；
- timestamp：regular、jitter、duplicate、OOO、negative delta、large gap、epoch extremes；
- entropy：全零、常量、递增、随机、不可压缩和必然扩张；
- stream：空 final、partial block、exact block、连续多块、reset/重复 finalize；
- buffer：最小合法 capacity、bound、bound-1、canary、safe-overread padding。

Native 代码必须有 ASan/UBSan debug qualification；可能的 SIMD 越界读必须用 guard page 或 sanitizer fixture 证明符合 manifest。Harness 分配错误使用 `HARNESS_CAPACITY_ERROR`，算法越界使用 `MEMORY_SAFETY_FAIL`，不能混为 compression failure。

### 8.4 Preflight Gate

Preflight 只判定该 Task 是否有资格进入正式测量，不为算法调参。通过条件：build/source/license 合法、capability 已解析、边界与安全通过、最小正确性通过、FinalBits 可核算、资源限制可施加、ExecutionPath 可辨识。

失败立即写一条或多条 diagnostic RunRecord，状态可为 `UNSUPPORTED/CORRECTNESS_FAIL/BOUND_VIOLATION/TIMEOUT/OOM/...`；正式 repetition 数为 0，Eligibility 为 false。

### 8.5 Formal Repetition 生命周期

每次 repetition 使用独立 codec object、独立输出 buffer 和明确 cache/state policy，建议顺序：

1. 创建上下文、准备输入、应用 adapter/preprocess；
2. warmup 不写入正式统计但保存摘要；
3. 开启同步资源采集；
4. `compress`；
5. `finalize/flush` 直到 stream complete；
6. 从真实 stream/side info 生成 AccountingLedger；
7. `decompress` 到独立输出；
8. 运行 common correctness 与 loss-specific validator；
9. 停止资源采集，读取 CPU/memory/I/O/counter/energy；
10. 销毁上下文、校验 canary 和 input hash；
11. 原子追加 `runs.csv` 和 component JSONL。

若 Profile 指定 continuous stream，必须作为不同 Semantic Key，明示跨 block 保留状态与 checkpoint/reset 语义。默认 repetition 不能复用已热化的状态对象。

### 8.6 Compress 与 Finalize/Flush

接口不能只有 `compress(bytes)->bytes`。至少区分 update 和 final，使 LZ4 frame footer、Zstd `ZSTD_e_end`、TSFile `flush()`、bitstream 尾位都进入计时和 FinalBits。Finalize 返回 0 bytes 也是有效观测；重复 Finalize 的行为需定义。

源码参考：

- LZ4 提供 `LZ4_compressBound`/`LZ4_decompress_safe`，frame API 明确 `compressBegin`/`compressEnd`；适合建立 output bound 与 finalization 契约。
- Zstd 提供 `ZSTD_compressBound`、context reset、`ZSTD_compressStream2(..., ZSTD_e_end)`；必须循环到返回 0 才完成 stream。
- Apache TsFile `Encoder` 明确 `reset/destroy/encode/flush/get_max_byte_size`，很适合作为 adapter 生命周期参考，但 `get_max_byte_size` 是内存/容量信息，不等于 FinalBits。

### 8.7 Accounting Engine

`AccountingLedger` 至少包含：

```text
TimestampBits, ValueBits, SharedBits, UnallocatedSharedBits,
MetadataBits, ValidityBits, DictionaryBits, ModelBits, IndexBits,
CheckpointBits, ChecksumBits, PaddingBits, ContainerBits,
SerializedBits, ExternalSideInformationBits, FinalBits,
FinalPhysicalBytes, CanonicalRawBits
```

必须满足机器可验证不变量：

- 所有组件为非负整数或带原因的 N/A；
- component sum 与 SerializedBits 的关系明确；
- `FinalPhysicalBytes = ceil(SerializedBits/8)`；
- `FinalBits = SerializedBits + ExternalSideInformationBits`；
- CompressionFactor、bits/value、saving 都只从 FinalBits 与 CanonicalRawBits 派生；
- 解码所需但 stream 外提供的 shape、dtype、scale、model、dictionary 等进入 external side info；若无法精确计算，结果不可进入正式 ratio 排名。

### 8.8 Common Correctness

按固定顺序验证，便于第一失败定位：

1. 解码长度与 shape；
2. Timestamp exact、顺序、单位、epoch；
3. integer exact；
4. float IEEE bit exact（lossless）；
5. validity；
6. channel/entity/feature order；
7. T/V pairing；
8. sparse rebuild protocol；
9. determinism；
10. input immutability、output bounds、memory/API errors。

Lossless 浮点测试不能只仿照某些上游项目的 `NaN is NaN`。例如 ALP 测试保留 `-0`，但 NaN 常只比较类别；本框架需由 Manifest 声明 payload preservation 或 canonicalization，并据此建正确性组。

### 8.9 Loss Gate

LOSSLESS：bit-exact round trip。  
ERROR_BOUNDED_LOSSY：按 ABS/RANGE_REL/POINTWISE_REL 等声明逐点或逐通道检查；任一原始违反为 `BOUND_VIOLATION`。  
RATE_CONTROLLED_LOSSY：验证目标率、实际率与质量指标；不能把未达 rate 静默归入目标点。  
SUMMARY_ONLY：只在明确的 summary Track，不能与重建 codec 排名。

质量至少输出 MAE、RMSE、NRMSE、MaxAE、误差分位数、bias、PSNR（适用时）、time-weighted RMSE。聚合范围必须标 per-channel/global。

Temporal Fidelity 在有损时序 profile 中按 SHOULD 输出 ACF/PACF、PSD、derivative、extrema、distribution 等；不满足指标只产生画像/警告，除非某 profile 明确把它升级为事先声明的门禁。

### 8.10 第三层输出合同

- 每个失败 Preflight 的结构化记录；
- 每个 Formal Repetition 的编码/解码、正确性、计费、资源和状态原始记录；
- bitstream 或其 hash、必要的诊断 artifact；
- lossless/lossy validator 细节与 first-failure stage。

### 8.11 第三层自省检查

- [ ] Track 路由与真实数据对象一致。
- [ ] Boundary/Safety 在正式计时前完成且不被计入主结果。
- [ ] Finalize/Flush 不遗漏。
- [ ] 正确性与性能来自同一次 repetition。
- [ ] FinalBits 来自真实可解码输出，不是 capacity/估计/内存对象大小。
- [ ] 有损误差界是硬门禁；Temporal Fidelity 未被误设为通用硬门禁。

---

## 9. 第四层：Performance Evaluation / 性能评测

严格步骤：`通过验证的配置进入性能评测 → Performance Benchmark + Resource Monitor + Query/Random Access + Streaming → 同步写入 runs.csv`。

### 9.1 与第三层的关系

第三层定义一次 repetition 如何正确执行，第四层定义在同一次 repetition 中采集哪些性能与资源观测。实现上由 `RepetitionExecutor` 同时调用 `TimingCollector`、`ResourceCollector` 和 validator；不得为了画性能图另跑一套没有正确性证据的循环。

### 9.2 TimingScope

| Scope | 起止边界 | 用途 |
|---|---|---|
| CORE | 算法核心入口到核心返回；不含预先声明的 adapter、I/O | 研究内核能力；只可与同执行边界比较 |
| PIPELINE | 显式 adapter/preprocess + codec + finalize/decode + reverse adapter | 主算法管线比较 |
| E2E | 从 canonical source buffer/文件到最终可消费重建对象，含约定的 I/O/进程/device transfer | 用户实际成本 |

Encode、Decode、E2E 必须分列；E2E 不能用 Encode+Decode 的两个独立最好值合成。计时使用 monotonic high-resolution clock，保存原始 nanoseconds 和处理的 canonical bytes/elements。

### 9.3 预热与重复

- warmup 同时满足次数 ≥3、累计时长 ≥0.5 秒；JIT/模型首次加载另建 cold-start profile。
- 正式 repetition ≥10；过快 kernel 在一次 repetition 内循环到 1–3 秒，但循环次数进入记录，状态重置规则一致。
- 数据顺序固定或由 seed 生成；若随机化任务顺序，保存 permutation。
- 主榜单线程；多线程为独立 profile，记录 total thread budget，不只记录算法显式线程数。
- 默认每次 repetition 创建新 context。若测 steady-state context reuse，单独 profile 和 ExecutionKey。
- 不以最快值为主统计。保存 median、P25、P75、mean、SD、CV、bootstrap CI95；必要时展示 min 但不用于排名。

### 9.4 Allocation、Cache、JIT 与 GC

每个 profile 明确：input/output allocation 是否计时、output buffer 是否预分配、context 构造/销毁是否计时、cold/warm cache、page fault、Python GC 是否开启、JIT compile 是否计入。无论选择什么，不能在算法间不一致。

FFI 特别记录：NumPy contiguous copy、Python↔native output copy、GIL、subprocess IPC、serialization、worker startup。TerseTS Python binding会复制输入/输出；若 CORE 只测 Zig 函数，必须另有 PIPELINE/E2E 展示 Python 用户成本。

### 9.5 Resource Monitor

ResourceScope：`PROCESS`、`PROCESS_TREE_CGROUP`、`DEVICE`、`SYSTEM_E2E`。首版至少支持：

- wall/user/system CPU time、core-seconds、CPU utilization；
- process/thread 数、context switch、minor/major faults；
- RSS baseline、incremental peak、USS/PSS（可用时）；
- read/write bytes 和 syscalls；
- perf cycles/instructions/cache/branch，记录 enabled/running time，multiplex ratio <0.9 时不可用于正式计数器比较；
- energy（RAPL/GPU）可用时记录 domain、wrap、sampling；不可用为 N/A，不填 0。

短任务的采样峰值不可靠，因此 memory 应优先 cgroup/process high-water mark 或独立 worker 峰值，采样只是补充。监测器本身开销通过空载校准记录。

### 9.6 Query / Random Access

仅 capability 声明支持的 codec 运行。统一 workload：seeded point/range queries，长度 `1/16/100/1000/full block`；MTS projection `q=1/2/4/min(8,M)/M`。输出 p50/p95/p99、read amplification、decode amplification、bytes touched、index bits、cache policy。

NeaTS 的随机查询使用固定 seed、查询生成在计时外，可参考其工作负载分离方式；但本框架必须统一 query 数、位置分布和正确性检查。FastLanes 现有示例反复读取 chunk 0，不能直接作为“随机访问”主结果。

### 9.7 Streaming

流式 profile 明确 online/streaming、block size、lookahead、buffer/state 上限、first-output latency、steady-state item/block latency、checkpoint bits、reset、backpressure。一次性 batch API 不能因分块调用而自动宣称 streaming capable。

### 9.8 Hardware 路径

GPU/FPGA 结果分开记录 kernel-only、H2D、D2H、sync、pinned/pageable、batch、overlap、padding 和 multi-device。CPU E2E 榜不得只放 GPU kernel 时间。本机当前 NVIDIA driver 不可用，相关 Task 应为 `UNSUPPORTED(device_unavailable)`；不得调用 CPU fallback 后仍标 GPU。

### 9.9 第四层输出合同

- 每 repetition 的 Encode/Decode/E2E 原始时间；
- CPU、memory、I/O、counter、energy 原始资源记录；
- Query/Streaming 原始 latency 与 amplification；
- TimingScope、ResourceScope、allocation/cache/JIT/GC policy；
- 同一 RunID 下的正确性与 FinalBits 关联。

### 9.10 第四层自省检查

- [ ] 性能采集与正式正确性来自同一 repetition。
- [ ] CORE/PIPELINE/E2E 边界可由字段重建。
- [ ] 未使用 fastest-only 统计。
- [ ] 线程、affinity、隐藏线程池和实际 ISA 已记录。
- [ ] Query/Streaming 仅在真实能力上运行，且 workload 可复现。
- [ ] 资源不可用使用 N/A 和原因，而不是 0。

---

## 10. 第五层：Statistics & Reporting / 统计分析与报告

严格步骤：`Statistics Engine → summary.csv → Eligibility Filtering → 按可比性键分组 → Pareto/排名/Coverage → Result/Report Generator`。

### 10.1 Statistics Engine 输入门禁

只读取 append-only 原始结果，不调用 codec，不修改 RunRecord。候选集合必须同时满足：

- `status == PASS`；
- 所需字段非 `UNSPECIFIED`；
- correctness/bound/accounting 均通过；
- 同一 ConfigID、ExecutionPathHash、SchemaVersion；
- repetition 数、时长与质量门槛达标；
- 无 oversubscription/resource pressure，或在专门 profile 中单列。

过滤理由逐行写入 `eligibility.csv`，不能只输出“剩余 N 条”。

### 10.2 `runs.csv` 最小字段组

1. Identity：SchemaVersion、RunSetID、TaskID、RunID、repetition。
2. Dataset：DatasetID、canonical hash、N/M/dtype/topology/raw bits。
3. Codec：AlgorithmID、SourceArtifactID、AdapterID、ObjectLevel、Track、LossMode。
4. Config：ConfigID、parameter JSON hash、block/window/state/error settings。
5. Execution：ExecutionPathHash、ISA/device/thread/fallback/binary/env。
6. Comparison：SemanticKey、ExecutionKey、ResourceKey。
7. Status：status、reason code、first failure、message artifact。
8. Correctness/Quality：exact flags、bound violation、quality metrics。
9. Accounting：FinalBits 及主要组件、canonical raw bits。
10. Performance：scope、encode/decode/E2E ns、bytes/elements。
11. Resources：CPU/memory/I/O/counters/energy 及 scope。
12. Optional workload：query/streaming seed、latency、amplification。

复杂组件明细放 `run_components.jsonl`，CSV 保存稳定常用列和明细 hash，防止单表无限扩张。

### 10.3 `summary.csv`

分组键至少是 DatasetID + AlgorithmID + ConfigID + ExecutionPathHash + Profile。输出 n、median、P25/P75、mean、SD、CV、CI95；压缩指标从 bit ledger 重新计算并交叉校验，不能信任 adapter 提供的 ratio。

吞吐：micro throughput = `sum(canonical bytes)/sum(time)`，不是吞吐均值。  
压缩：micro ratio 使用 `sum(FinalBits)/sum(RawBits)`；跨数据集可另给 compression factor 的 geometric mean。  
资源：按规范明确 sum/max/weighted aggregation，峰值不能简单求和。

### 10.4 可比性分析顺序

1. 空间/质量：同 SemanticComparabilityKey。
2. 性能：在 1 基础上同 ExecutionComparabilityKey。
3. 资源：在 2 基础上同 ResourceProfileKey。

报告 UI 应把键差异展开成可读原因，如“一个包含 float64 widening adapter，另一个 direct”“一个 AVX2，另一个 scalar fallback”，而不是只显示 hash。

### 10.5 Eligibility、Coverage、Pareto 与排名

- Eligibility 是能否参与某一具体分析，不是全局布尔值。
- Coverage 分母是事先冻结的 Task Universe；UNSUPPORTED、TIMEOUT、OOM 等分别计数。
- Pareto 至少支持 FinalBits/Encode speed/Decode speed/Peak memory/Quality 多目标；只在可比组内计算。
- 排名规则、权重、tie 和缺失处理在运行前配置。默认不把 Coverage 不同的算法压成单一总分。
- Lossless 与 lossy、primitive 与 system、UTS 与 MTS、CPU 与 GPU 不做跨语义总排名。

### 10.6 报告产物

- `runs.csv`：逐次原始数据；
- `summary.csv`：同配置同执行路径统计；
- `eligibility.csv`：过滤证据；
- `coverage.csv`：任务宇宙与状态；
- `pareto.csv`：前沿成员和被支配关系；
- machine-readable `report.json`；
- 人读 Markdown/HTML 报告，包含环境、数据、源码 commit、方法、异常、Coverage 和图表。

报告顶部必须提醒：压缩率方向（ratio 或 factor）、单位、TimingScope、线程数、是否含模型/索引、是否 cold-start。图表不得混用相反方向的 ratio。

### 10.7 第五层自省检查

- [ ] 只聚合 PASS 且同 ConfigID/ExecutionPathHash 的 Run。
- [ ] 每数据集先统计，micro 与 macro 公式明确。
- [ ] 可比性键按 Semantic→Execution→Resource 收紧。
- [ ] Coverage 包含所有预先规划 Task 和失败状态。
- [ ] Pareto/排名不跨 Track、LossMode 或 ObjectLevel 混算。
- [ ] 最终报告可反查到任一 repetition、binary 和 Dataset hash。

---

## 11. Adapter SDK 与跨语言执行协议

### 11.1 Python 协议草案

```python
class CodecAdapter(Protocol):
    def describe(self) -> CodecManifest: ...
    def negotiate(self, data: DataDescriptor, request: RunRequest) -> CompatibilityPlan: ...
    def resolve_execution(self, plan: CompatibilityPlan) -> ExecutionResolution: ...
    def create(self, config: ResolvedConfig) -> CodecContext: ...
    def prepare_input(self, ctx: CodecContext, view: CanonicalView) -> PreparedInput: ...
    def compress(self, ctx: CodecContext, data: PreparedInput, out: OutputSink) -> OperationStats: ...
    def finalize(self, ctx: CodecContext, out: OutputSink) -> OperationStats: ...
    def accounting(self, ctx: CodecContext, out: OutputSink) -> AccountingLedger: ...
    def decompress(self, ctx: CodecContext, source: Bitstream, out: OutputView) -> OperationStats: ...
    def query(self, ctx: CodecContext, request: QueryRequest) -> QueryResult: ...
    def reset(self, ctx: CodecContext, mode: ResetMode) -> None: ...
    def close(self, ctx: CodecContext) -> None: ...
```

实际类型用冻结 dataclass/Enum，不在核心合同中传无结构 dict。每个操作返回字节数、实际路径、native error、copy/allocation telemetry；异常由框架映射为稳定状态码并保存 traceback/native stderr。

### 11.2 Adapter 后端

| 后端 | 适用对象 | 隔离/计时注意 |
|---|---|---|
| Python in-process | fABBA、SciPy/PyWavelets、纯 Python算法 | GIL、GC、NumPy/BLAS 隐藏线程、Python 3.14 兼容 |
| `ctypes` C ABI | LZ4、Zstd、streamvbyte、C shim | stdlib 可用；显式 ownership/argtypes；native crash 会带走 Runner，正式可在 worker 进程中调用 |
| CPython extension/pybind11 | ALP、Serf、zfp、复杂 C++ API | 扩展 ABI、C++ runtime、copy/GIL；版本与 binary hash |
| Subprocess CLI | Java/Go/legacy Python/独立二进制 | 启动/I/O/临时文件范围；timeout、process tree、stderr、exit code |
| Persistent worker RPC | 高启动成本模型、JVM、跨 ABI codec | cold/steady 分离；状态污染与 reset；协议版本 |
| System adapter | Prometheus/Timescale/ClickHouse/TSFile P3 | 真实 container、segment、index、query，不把内部 primitive 结果冒充系统结果 |
| Device adapter | CUDA/HLS/QAT | transfer/sync/batch/device memory/driver 与 CPU E2E |

### 11.3 稳定 C ABI 草案

`native/include/tscb_adapter_v1.h` 使用 opaque handle 和显式 buffer descriptor：

- `tscb_get_abi_version`、`tscb_get_manifest_json`；
- `tscb_create`、`tscb_destroy`、`tscb_reset`；
- `tscb_compress_bound`、`tscb_compress`、`tscb_finalize`；
- `tscb_decompress`、`tscb_query`；
- `tscb_get_accounting_json`、`tscb_get_last_error`；
- 所有函数返回稳定整数状态码；长度统一 `uint64_t`，检查到目标库 `int` 限制后分块或 UNSUPPORTED；
- buffer descriptor 带 pointer/capacity/used/dtype/shape/strides/alignment/ownership；
- shim 不分配跨边界后无法释放的内存，或同时暴露配对 free 函数。

### 11.4 Worker 隔离

默认把不可信 native adapter 放到一次 Task 或一批同配置的 worker 进程。父 Runner 负责超时、cgroup/affinity、stdout/stderr、崩溃检测和结果落盘。worker 只通过版本化 request/response 操作，不能直接写主 `runs.csv`。

共享内存可降低 IPC，但 descriptor 和生命周期必须明确；首版可先用 memory-mapped canonical binary，待正确闭环后优化。

### 11.5 Adapter 资格测试

每个 adapter 的 Definition of Done：

- manifest/schema/ID 稳定；
- upstream tests 通过并有日志；
- boundary + ASan/UBSan（native）通过；
- lossless/lossy correctness 通过；
- FinalBits 账本与实际文件长度闭合；
- reset/finalize/state/determinism 测试通过；
- requested vs actual execution path 可观测；
- 10+ raw repetitions可落盘并通过统计器；
- unsupported 情况返回结构化状态；
- license 与 source commit 已登记；
- 与另一个语言 adapter（若有）跑 Golden Fixture 结果一致。

---

## 12. 现有源码中应复用的行为与必须修正的偏差

### 12.1 重点源码证据矩阵

| 本地源码 | 可参考行为 | 不能照搬的部分 |
|---|---|---|
| [`TerseTS`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cmcuza_TerseTS) | C/Python binding、配置 JSON、f64 压缩、N=0/1、随机与特殊值测试、无损位模式比较 | Python wrapper 隐式 contiguous+float64 转换和拷贝；缺统一 benchmark/资源/计费；当前机无 Zig |
| [`lzbench`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/inikep_lzbench) | codec function table、统一编译、output bound、chunk、compress/decompress+memcmp、最短计时 | 默认保留 fastest、非逐 repetition、byte-stream 无时序语义、状态复用不透明、无 FinalBits 组件 |
| [`Sprintz`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/dblalock_sprintz) | MTS integer、row/column、padding 修正、旧基准路径 | 去掉 timestamps；8/16 bit 量化不可标 float lossless；Python/路径陈旧 |
| [`ALP`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cwida_ALP) | kernel encode/decode、cycle timing、special value tests、metadata 结构 | 固定 30,000 次内循环不等于统一 repetition；NaN payload 验证不足；逻辑 size 不保证等于最终序列化 bits |
| [`FastLanes`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/cwida_FastLanes) | P3 文件格式、C++/Python、chunk/query API | CSV 文件大小作为分母无效；async 线程预算不透明；读取 chunk 0 不等于 seeded random access |
| [`zfp`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/LLNL_zfp) | nD、reversible/accuracy/rate、多后端、明确 stream size/header | 1D 与 nD 不能混为同一 Value topology；header/stride/device profile 必须显式 |
| [`Serf`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/Spatio-Temporal-Lab_Serf) | error-bounded float、streaming、block size、C++/pybind、压缩/解压时间 | 平均 block time 代替 raw reps、部分尾块处理、固定 buffer、CC BY-NC 许可限制 |
| [`NeaTS`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/and-gue_NeaTS) | SIMD 路径、serialization/in-memory 区分、seeded query、full/random decode | C++23/AVX 依赖、硬编码路径、allocation scope 不一致、部分查询正确性不足 |
| [`ClickHouse`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/ClickHouse_ClickHouse) | Delta 明确为 preprocessor；header、width、SIMD+tail、输出容量检查；pipeline 组合 | ClickHouse 系统默认行为不能冒充 standalone primitive；系统上下文另立 P3 |
| [`Prometheus`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/prometheus_prometheus/tsdb/chunkenc) | XOR/XOR2 appender/iterator、timestamp DoD、value XOR、joint control bits、Go benchmarks | Go benchmark 统计边界不是本项目默认；XOR2 必须 SYSTEM/JOINT，不可强拆 T/V bits |
| [`TimescaleDB`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/timescale_timescaledb/tsl/src/compression/algorithms) | DeltaDelta、Simple8b-RLE、Gorilla、finish/reset、header/tag/null/bitarray 的真实容器 | 数据库扩展的对象生命周期和系统开销需 P3 profile；primitive 不等于整个 storage result |
| [`Apache TsFile`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/apache_tsfile) | C++/Java 跨语言 wire format、Encoder reset/flush、TS_2DIFF/Gorilla/Chimp/Sprintz 测试、golden bytes | float TS_2DIFF 包含 scale/round/raw-bits 三态，不能一概标 lossless；Java NaN canonicalization 与 C++ payload policy不同 |
| [`LZ4`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/lz4_lz4) | `compressBound`、safe decode、raw/frame、begin/end | raw block不自描述；frame/header/footer与 raw 模式必须不同 Config/Semantic key |
| [`Zstd`](/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos/facebook_zstd) | bound、one-shot/stream、context reset、final end、dictionary | dictionary bits、context reuse、多线程都需显式；流未 end 不可计费 |

### 12.2 TSBench 行为吸收原则

“参考 TSBench”应落实为测试夹具和接口决策：

- 吸收其对算法原生 build/API、参数、block 和自测的理解；
- 把其 benchmark 循环封装在本框架 Formal Repetition 外或拆出 kernel，不直接导入它的汇总 CSV；
- 重新执行统一 canonical input、correctness、FinalBits、timing/resource profile；
- 同时报告“upstream-compatible profile”和“V2 canonical profile”时，两者使用不同 ProfileID，不能混排；
- 对修改上游源码才能暴露 API 的算法，补丁必须最小化并可重放，且保留 unmodified baseline build。

### 12.3 外部参考库获取政策

当前本地 72 仓库已足够开始，不应在 Phase 0 无边界扩张。新增参考仓库须进入 `sources.lock.json`：官方 URL、用途、license、commit、获取时间、hash、submodule、是否仅参考/可执行。优先补齐：

- NVIDIA 当前官方 nvCOMP samples（本地仓库已归档，只在具备 GPU 后获取）；
- Google Benchmark 或 nanobench 仅作 native micro-timing 参考，不替代本框架 raw-run合同；
- Arrow C Data Interface 作为跨语言 buffer contract 参考；
- SPEC/Google Benchmark 的运行稳定性原则、ASV/Airspeed Velocity 的环境隔离思想可研究，但结果 Schema 仍以本项目为准。

任何网络获取都应在独立 source acquisition 步骤完成，固定 commit 后再审计；正式运行不得临时 `git pull` 或下载模型。

---

## 13. 算法接入批次与优先级

### 13.1 Batch 0：Harness Oracles（验证框架，不进入正式算法主榜）

实现 identity、deliberately-corrupt、sleep/timeout、OOM、nondeterministic、zlib/lzma/bz2 等测试 adapter。目的不是满足“源码算法 benchmark”，而是验证状态机、bit accounting、错误注入、恢复、统计过滤和报告。只有这批通过，才允许 native codec 接入。

验收：一条 PASS、一条 CORRECTNESS_FAIL、一条 BOUND_VIOLATION、一条 TIMEOUT、一条 OOM、一条 UNSUPPORTED 都可在报告中正确出现；统计只保留 PASS。

### 13.2 Batch 1：通用无损 C/C++ 源码

优先 LZ4 raw/frame、Zstd one-shot/frame、Snappy、Brotli。理由：API 稳定、bound/length 清晰，可先打通 ctypes/C shim、Finalize、buffer safety、raw byte codec 与 canonical value bytes 的 P1 路径。

必须分开：raw block 与 self-contained frame；one-shot 与 streaming；dictionary/no-dictionary；single/multithread。主榜先 single-thread、无 dictionary、self-contained 或明确 external metadata。

### 13.3 Batch 2：Timestamp primitives 与 pipelines

接入 Delta、DoubleDelta、ZigZag、VarInt、StreamVByte、MaskedVByte、SIMDComp、FastPFOR/Simple8b。先以 P0 primitive microprofile 建正确性与 execution path，再定义可独立解码的 P2 pipeline，例如：

```text
T:int64 -> checked Delta/DoD -> ZigZag -> StreamVByte/BitPack -> header/finalize
```

每个 stage 计费，overflow checked，duplicate/OOO/negative delta 能力明确。可参考 ClickHouse、Timescale、TsFile；但不能把原始 primitive 的 packed bytes 当完整 codec stream。

### 13.4 Batch 3：Value lossless UTS/MTS

Gorilla、Chimp/Chimp128、Elf 系、FPC、ALP/ALP_RD、Sprintz integer。先 UTS，再 MTS：

- COLUMN_INDEPENDENT 必须运行全部 M 列并累计每列 header/state；
- GROUPED/FULL_MATRIX 保留真实 coupling；
- special floats 按 bit contract；
- ALP 等 representation + bitpack + backend 完整计费；
- Sprintz float 量化版本路由有损，integer 原生路径才可 lossless。

### 13.5 Batch 4：有损与 native ND

Serf、SZ3、zfp、分段近似、transform/PCA。优先绝对误差合同和单一 dtype，随后 range-relative/pointwise/rate。每个方法明确 ReconstructionMode；PCA/FFT truncation 的 basis/coefficients/shape 均计入 side info。

zfp 的 nD 路径单设 NATIVE_ND_ARRAY 组；1D 不与 2D/3D kernel 吞吐直接比。Serf 先完成许可证标记和尾块/FinalBits 验证。

### 13.6 Batch 5：SYSTEM / TSDB

Prometheus XOR/XOR2、Timescale、TsFile、ClickHouse、InfluxDB。定义共同 SegmentPlan、容器、index、validity 和 query workload。可以同时提供：

- P0/P1 内部 codec profile，用于机制研究；
- P3 system profile，用于真实存储/查询；

但二者永不在同一 ObjectLevel 排名。

### 13.7 Batch 6：Learned / Streaming / Hardware

ABBA/fABBA、NeaTS、TerraCodec、WaLLoC、DeepZip/DZip、GPU/FPGA/QAT。先解决训练范围、模型 artifact、首用/steady、seed、device 和环境隔离。当前 Python 3.14 可能不兼容旧深度学习栈，因此使用锁定 worker env/container，不为它们降级主 Runner。

硬件在设备缺失时保留完整 Task Universe 与 UNSUPPORTED；具备设备后再生成新的 EnvironmentID，不复用 CPU run set。

### 13.8 每批阶段自省模板

- [ ] 该批每个对象的 ObjectLevel/Track/LossMode 都有证据。
- [ ] 不是把同 repo 多个名称误当多个独立实现，也不是把多个实现误合并。
- [ ] 所有 source commit、build、license、binary hash 已冻结。
- [ ] 上游行为中不符合 V2 的统计/分母/正确性已隔离。
- [ ] 先过小数据、boundary、sanitizer，再运行真实大数据。
- [ ] 新字段未破坏旧 Schema；必要时做版本迁移而非临时列。

---

## 14. 测试体系

### 14.1 测试金字塔

1. Contract unit：enum、schema、canonical JSON、ID、status transition、bit formulas。
2. Dataset unit：parser、dtype、timestamp、validity、topology、hash、characterization。
3. Adapter contract：capability、ownership、bound、reset、finalize、accounting。
4. Validator property tests：整数/float bits/error bound/pairing/determinism。
5. Boundary/safety：尺寸、特殊值、canary、ASan/UBSan、fault injection。
6. Integration：完整五层最小闭环、resume、timeout/crash、append-only raw runs。
7. Golden cross-language：Python/C/C++ 对同 fixture 的 ID、stream、status、ledger。
8. Performance smoke：不设易抖动的绝对速度阈值，只检查时间为正、重复数、scope、无明显数量级回归；稳定机再建历史阈值。

### 14.2 必须建立的 Fixtures

- `tiny_timestamp_*`：regular/jitter/dup/OOO/overflow/gap/negative；
- `tiny_float_bits_*`：±0/subnormal/Inf/多个 NaN payload/相邻 bits；
- `tiny_int_extremes_*`：所有宽度边界；
- `tiny_mts_*`：M 列、heterogeneous、projection、channel reorder；
- `tiny_validity_*`：cell/row/ragged；
- `tiny_async_topology_*`：不同实体时间轴；
- `incompressible_*` 与 expansion；
- `lossy_bound_edge_*`：刚好在界、界内、界外；
- `stateful_chunks_*`：partial/exact/empty final、reset/checkpoint。

### 14.3 Metamorphic Tests

- 无损 round-trip 后再次压缩应满足声明的 determinism；
- 分块与 one-shot 在声明等价时重建相同；
- physical transpose adapter 不改变 logical view；
- column-independent MTS 等于所有列独立结果的真实总和，而非估算；
- 修改 Dataset bytes 必须改变 DatasetID；修改参数必须改变 ConfigID；仅改变输出路径不应改变语义 ID；
- scalar 与 SIMD 解码输出一致，但 ExecutionPathHash 不同；
- 加入不可见 side info 应增加 FinalBits。

### 14.4 CI 分层

- PR-fast：纯 Python contract/unit + oracle 闭环；
- PR-native：Batch 1/2 小型 release + sanitizer；
- nightly：所有可构建 adapter、全 boundary、确定性、多 seed；
- benchmark-host：固定硬件上的受控正式测量，不与普通 CI 性能混合；
- weekly source audit：commit/source tree/license/build recipe 漂移检测，但不自动升级源码。

---

## 15. 分阶段实施路线图与验收门

### Phase 0：仓库与决策基线

实施：初始化 Git；建立目录、`pyproject.toml`、lint/type/test；冻结本计划、Word/MD hash、流程图 hash；生成 72 仓库 `source_catalog.json`；记录本机环境；定义 Decision Record 模板。

验收：项目可在 `CompressBench14` 执行 `python -m pytest`；source audit 可重复并发现归档/缺失/dirty；未修改共享源码。

自省：用户要求的所有输入是否都有 hash 和审阅状态？Python 3.14 风险是否被隔离而非忽略？

### Phase 1：合同、ID、结果存储与 Oracle 闭环

实施：Schema v2、Enums、canonical JSON/ID、Run 状态机、append-only CSV/JSONL、AccountingLedger、identity/fault adapters、最小报告。

验收：Batch 0 六类状态完整通过；进程中断可 resume；不合格 run 不进入 summary。

自省：在没有任何真实 codec 前，是否已经能证明“错误结果不会被排名”？

### Phase 2：数据层

实施：13 个 dataset manifests、CSV/NPZ loaders、canonical binary、characterization、synthetic fixtures。显式处理 PEMS axes、NPZ 无 T、national_illness dtype、weather header encoding。

验收：所有 DatasetID 稳定；二次加载 bit-identical；无 hidden transform；C/C++ 能读取 canonical fixture。

自省：是否错误地把文件 bytes、Pandas 推断或自动 datetime 行为当作规范？

### Phase 3：Registry、Negotiation 与执行隔离

实施：Codec/Source Registry、四态 Negotiator、CompatibilityPlan、worker protocol、execution resolution、thread/ISA probe、preflight、timeout/cgroup/affinity。

验收：同一数据对 direct/lossless-adapter/lossy-adapter/unsupported 产生预期状态；fallback 改变 ExecutionPathHash。

自省：adapter 是否只报告事实、没有掌握 PASS/可比性最终裁决权？

### Phase 4：首批源码闭环

实施：LZ4/Zstd/Snappy/Brotli source builds 和 adapters；raw/frame、one-shot/streaming；ASan/UBSan、Finalize、FinalBits。

验收：所有 boundary；stream 可独立解码；ledger 与物理长度闭合；10+ raw reps；CORE/PIPELINE/E2E 边界明确。

自省：使用的是本地冻结源码构建产物还是恰好同名的 pip/system library？binary hash 能证明吗？

### Phase 5：Timestamp Track

实施：checked Delta/DoD/ZigZag、StreamVByte/FastPFOR/Simple8b pipelines；T0/T1/T2；overflow、OOO、dup、negative；ClickHouse/Timescale/TsFile 对照。

验收：P0 与 P2 分榜；所有时间语义测试通过；T bits、headers 和 side info 全计费。

自省：是否存在先排序再压缩、overflow wrap 或 primitive 伪装 standalone？

### Phase 6：Value UTS/MTS

实施：Gorilla/Chimp/Elf/ALP/Sprintz；float bit correctness、coupling mode、all-column accounting、heterogeneous/validity 能力。

验收：UTS/MTS 不混；MTS 每列实际运行；NaN/-0 策略明确；SIMD/scalar 输出一致。

自省：是否只测第一列、统一 cast float64 或遗漏每列 header？

### Phase 7：Lossy、ND 与 Temporal Fidelity

实施：Serf/SZ3/zfp 和表示型算法；ErrorBound contracts、RD sweep、quality、temporal profile、rebuild protocol。

验收：故意越界 fixture 必定 BOUND_VIOLATION；Temporal metrics 可报告但不误作通用 gate；模型/系数/索引计费。

自省：质量提升是否来自未计费 side info 或测试数据调参？

### Phase 8：SYSTEM、Query、Streaming

实施：SegmentPlan、Prometheus XOR2、TsFile/Timescale/ClickHouse 代表路径；统一 query/stream workload。

验收：真实 T/V pairing；joint codeword 不强拆；query 正确性、latency、amplification；P3 与 primitive 分榜。

自省：SYSTEM 是否真的是共同分块的一次可解码装配，而非独立结果求和？

### Phase 9：Learned 与 Hardware

实施：训练合同、模型/seed、cold/steady、worker env；具备硬件后 GPU/FPGA/QAT profiles。

验收：无 test leakage；model bits/time 明确；设备不可用/可用 Coverage 正确；kernel 与 E2E 分开。

自省：是否为了跑通旧代码污染主环境，或把 CPU fallback 写成硬件成绩？

### Phase 10：统计、报告与发布资格

实施：完整 summary/eligibility/coverage/Pareto/ranking、报告、reproduction bundle、schema migration、用户文档。

验收：从报告任一点反查 raw run、config、dataset、source、binary、environment；另一机器能验证结果合同并重跑小 fixture。

自省：是否仍有手工 Excel/脚本后处理没有版本和 hash？是否展示所有失败与覆盖率？

### 阶段依赖

```text
P0 -> P1 -> P2 -> P3 -> P4 -> P5/P6 -> P7 -> P8 -> P9
                    \---------------------------> P10 (逐步增强)
```

不得以“先跑出数字”为由跳过 P1–P3。P5/P6 可在 P4 稳定后并行，P9 不阻塞 CPU 主线。

---

## 16. 可复现构建与运行操作规程

### 16.1 Source Lock

每个 source entry 保存 repo、commit、archive hash、submodules、license、patch series。共享 `_repos` 作为只读源；构建使用显式 source path 和独立 build dir。若仓库 shallow，不影响固定当前 commit，但未来归档时应生成 source tar hash。

### 16.2 Toolchain Profile

区分：主 Runner env、native compiler env、legacy worker env、learned env、device env。每个 profile 固定 compiler/linker、stdlib、CMake、flags（`-O3/-DNDEBUG/-march`）、sanitizer、Python ABI、依赖 lock。禁止本地 `-march=native` 结果只写成“AVX2”；必须保存完整 compile command 与运行时 ISA probe。

### 16.3 Build Artifact

BuildID = SourceArtifactID + PatchHash + ToolchainProfileID + BuildOptions。产物保存二进制 hash、`ldd`/依赖、symbols/ABI version、自测日志。Debug/sanitizer 产物只做资格测试，正式性能使用 release BuildID。

### 16.4 正式运行前清单

- 工作树、配置、registry、schema 已冻结；
- 数据/source/binary hash 验证；
- affinity/governor/turbo/thread env 已施加并复读；
- 系统负载、温度、可用内存、磁盘空间满足阈值；
- perf/energy/cgroup 权限探测；
- Preflight 全通过；
- 输出目录新建且可原子追加；
- 运行中禁止自动更新包、源码或模型。

### 16.5 运行后清单

- 任务计划每项都有终态；
- repetition 数和 checksums 完整；
- `validate_results.py` 检查 ID、ledger、status、foreign key；
- summary 可从 raw 重建且 hash 一致；
- 生成环境、源码、配置、失败、Coverage 报告；
- 归档时保留小型 bitstream/fixture，超大中间流可仅保留 hash 与受控路径，但规则统一。

---

## 17. 风险登记表

| 风险 | 证据/触发 | 缓解 | 阻断条件 |
|---|---|---|---|
| Python 3.14 与旧算法不兼容 | Sprintz/learned/旧 Cython | 独立 worker env；稳定协议；不降级主 Runner | 无法复现环境则 BUILD_UNAVAILABLE |
| 源码只是占位/结果 | nvcomp、NNLCB、ModelarDB | Source completeness audit；补官方源后新 SourceID | 无真实实现不得标 PASS |
| 许可证限制 | Serf CC BY-NC、缺失许可 | license field、人工 review、分发策略 | blocked/restricted 不打包传播 |
| 隐式 dtype/layout copy | TerseTS、NumPy binding | 框架先做 CompatibilityPlan；copy telemetry | 无法辨识则不可进性能主榜 |
| primitive 被当 codec | Delta、Simple8b、PCA | ObjectLevel + pipeline manifest + FinalBits | 非自包含不得 P1 排名 |
| shared T/V 错误拆账 | XOR2/system codecs | BitstreamSeparability + UnallocatedSharedBits | JOINT 禁止拆分 |
| buffer capacity 冒充 size | native APIs | used length + physical stream cross-check | ledger 不闭合即 INCOMPARABLE |
| best-time 偏差 | lzbench 等 | raw repetitions、median/CI | fastest-only 不进入正式统计 |
| SIMD fallback 混比 | runtime dispatch | actual ISA probe、ExecutionPathHash | 路径未知不可比 |
| P/E core 抖动 | i5-13400F | affinity、core calibration、记录 topology | 无法稳定固定则性能仅 exploratory |
| GPU 不可用 | nvidia-smi 失败 | explicit UNSUPPORTED、Coverage | 不允许 CPU fallback 冒名 |
| CSV parser 漂移 | pandas/Python 升级 | parser version、canonical binary hash | canonical hash 变化生成新 DatasetID |
| 数据语义不足 | NPZ 无 T、weather header | manifest、source evidence、N/A timestamp | 禁止 Loader 自行猜测 |
| learned test leakage | 训练型 codec | split contract、seed/model hash | 泄漏则结果作废 |
| 资源采样误差 | 短任务、perf multiplex | 内循环、cgroup HWM、ratio gate | 不达门槛不做资源排名 |
| 结果 Schema 演化 | 逐步新增 codec | version + migration + contract fixtures | 不允许临时私有列参与排名 |

---

## 18. 源码资产全量逻辑目录（221 条）

本节记录“当前登记资产”，不是“已通过 Benchmark 资格”。方括号为去重仓库；同仓库出现多次是不同逻辑算法/用法，必须在 Registry 中再确认是否形成独立 AlgorithmID。

### 18.1 ValueCompress（89）

- 通用字典：LZ77、DEFLATE `[madler/zlib]`；LZSS、A-LZSS `[alexkazik/lzss]`；LZ4 `[lz4/lz4]`；Snappy `[google/snappy]`；Zstd `[facebook/zstd]`；Brotli `[google/brotli]`；LZMA/xz `[tukaani-project/xz]`。
- 时序字典：TRISTAN、CORAD `[eXascaleInfolab/CORAD]`；OMP、Online Dictionary Learning `[scikit-learn]`；alphaCSC `[alphacsc]`；ABBA `[nla-group/ABBA]`；fABBA `[nla-group/fABBA]`。
- 分段近似：PMC、PLA、Sliding Window、Bottom-Up、Top-Down、SWAB、LTC、Adaptive、Smart-Grid `[Data-Stream-Compression]`；PPA `[PiecewiseLinearTimeSeriesApproximation]`；Sim-Piece、Mix-Piece `[Mix-Piece_Sim-Piece]`；Spline `[scipy]`；ABBA/fABBA stage `[fABBA]`。
- 变换：DFT、FFT+selection、DCT `[scipy]`；DWT、Haar、Wavelet Packet `[PyWavelets]`。
- 降维：PCA、Incremental PCA、SVD/Truncated SVD、Randomized SVD、NMF `[scikit-learn]`。
- 无损预测：Sprintz-Delta/FIRE `[sprintz]`；FPC/FCM/DFCM `[fpc]`；TSXor；Chimp；Chimp128；Patas；Elf/Elf+；Elf*/SElf*；ALP/ALP_RD；Camel；Delta-of-Delta；Gorilla。
- Residual/Entropy：Huffman、Canonical Huffman；Arithmetic/Range；ANS/rANS/tANS；FSE/Huff0。
- 有损预测：SZ/SZ3；Serf-Qt、Serf-XOR；zfp。
- Learned：DeepZip、DZip、RAT-CC、RNN predictor、NeaTS、TerraCodec TEC-TT/FlexTEC、WaLLoC/LeaTS family。
- Hardware：nvCOMP、cuSZ/pSZ、cuSZp/SZp-CUDA、Falcon、G-ALP/FastLanes GPU、Vitis Data Compression、Xilinx LZ4 HLS、QAT/QATzip。

### 18.2 TimeStampCompress（110）

- Delta：First-order/D-gap、Delta+VarInt、Delta+ZigZag+VarInt、Masked/Stream VByte、SIMD Differential、Parquet DELTA_BINARY_PACKED、Influx TSM Delta、Timescale Delta。
- Delta-of-Delta/Higher-order：generic D2、Gorilla D2、Prometheus XOR/XOR2、ClickHouse DoubleDelta、IoTDB TS_2DIFF、Timescale DeltaDelta、Redis Gorilla DoubleDelta、TurboPFor Gorilla-style、Prometheus triple-delta pattern。
- VarInt/ZigZag：Base128/ULEB128/VByte/Stream/Masked/Group/TurboByte/G8IU/Snappy varint；Protobuf 32/64、Delta/DoD ZigZag、Parquet metadata、IoTDB ZigZag、TurboPFor transform。
- Universal codes：Elias Gamma/Delta/after Delta/after DoD；Golomb、Golomb-Rice、Partitioned Rice、folded residual Rice、adaptive block Rice。
- Bit packing：fixed-width、Binary Packing、SIMD-BP128、SIMDComp、LittleIntPacker、TurboPack、Parquet packing。
- Simple family：Simple-8b、Influx Simple8b、Simple8b-RLE、reverse-decodable variant、Simple-9、Simple-16、Variable Simple、FastPFOR Simple8b_RLE。
- FOR/PFOR：FOR、Delta-FOR、PFOR/PForDelta、NewPFor/NewPFD、OptPFor/OptPFD、FastPFOR、SIMD-FastPFOR、TurboPFor、AFOR、Parquet min-delta frame。
- RLE/prediction：Influx timestamp RLE、Timescale Simple8b-RLE over D2、TurboPFor RLE、UUIDv7 timestamp D2、Sprintz zero-block、Simple8b zero selector、last-delta predictor、DPCM+VarInt/Rice。
- Sprintz/Gorilla：Sprintz Delta/FIRE/entropy、IoTDB Sprintz、Facebook/Redis Gorilla、ClickHouse Gorilla/DoubleDelta pipeline。
- TSDB families：Prometheus XOR/XOR2/Histogram/Histogram-ST；IoTDB TS_2DIFF/RLE/GORILLA/ZIGZAG/SPRINTZ/CHIMP/RLBE/PLAIN + backend；Influx TSM scaling/RLE/Simple8b/raw/adaptive；ClickHouse Delta/DoubleDelta+Zstd/LZ4/GCD；Timescale Hypercore 与 Influx Parquet path。

### 18.3 TSBench / Benchmark（22）

TerseTS、Data-Stream-Compression、CORAD、Sprintz、Chimp、Elf、SElfStar、Serf、ALP/FastLanes、Mix-Piece/Sim-Piece、ModelarDB、SZ ecosystem、zfp、NNLCB、NeaTS、TerraCodec、WaLLoC、lzbench、nvCOMP、Vitis Data Compression、QATzip、FiniteStateEntropy。

### 18.4 首轮 source lock 的 72 个 commit

当前 clean checkout 的 commit 前 12 位应写入机器清单而非依赖本节文本：

```text
ClickHouse 0a779875c376; TsFile b924b1b2ff79; Prometheus 8374d30cb3fe;
TimescaleDB 1ab3743df851; TerseTS 64abd7767f8f; lzbench fa871e66b354;
ALP 31ca0ed11c93; FastLanes f0edc1020a53; Sprintz a056cdb67d04;
Serf b38450b56825; NeaTS 2d804ff492e4; zfp c0c2c40b30d9;
LZ4 0774d05537f9; Zstd d9c0c7e2cf8a; Snappy 26aa88cbb235;
Brotli 4508218e7fef; FastPFOR 2457e1ed1af3; streamvbyte 7c472d7d4d63;
MaskedVByte e2298b7a2800; SIMDComp d5301778fe50; SZ3 57ce9e905af5.
```

其余 commit 由 Phase 0 自动生成完整 JSON/CSV；复制在计划正文中的 hash 不应作为唯一真值。

---

## 19. 首版配置与结果示例（用于开发对齐，不是最终 Schema）

### 19.1 实验配置示例

```toml
schema_version = "2.0"
datasets = ["etth1@canonical-v1"]
algorithms = ["lz4-frame@source", "zstd-frame@source"]
tracks = ["VALUE"]
seed = 20260910

[profile]
timing = "single-thread-pipeline-v1"
resource = "process-v1"
correctness = "lossless-ieee-v1"
warmup_min_count = 3
warmup_min_seconds = 0.5
repetitions = 10
timeout_seconds = 120

[sweep]
block_size = [256, 1024, 4096]
```

冻结后补全 adapter、allocation、cache、ISA、threads、default params，生成 canonical JSON 和 ID。

### 19.2 Codec Manifest 关键片段

```json
{
  "algorithm_id": "lz4-frame",
  "source_artifact_id": "sha256:...",
  "object_level": "P1_STANDALONE_CODEC",
  "tracks": ["VALUE", "TIMESTAMP"],
  "loss_modes": ["LOSSLESS"],
  "input": {"kind": "BYTE_VIEW", "max_length": 2147483647},
  "finalization": "REQUIRED",
  "bitstream_separability": "INDEPENDENT",
  "state_semantics": "INDEPENDENT_CONTEXT_PER_REPETITION",
  "execution_backends": ["C_ABI"]
}
```

通用 byte codec 可压 canonical T/V bytes，但其 Semantic Key 必须标明 byte-view pipeline，不能与理解 timestamp 语义的 T1/T2 codec 混作同一机制类别。

### 19.3 Unsupported 也写 Run

```json
{
  "status": "ISA_UNSUPPORTED",
  "reason_code": "requested_avx512_actual_cpu_avx2",
  "requested_isa": "AVX512",
  "actual_isa": "NOT_EXECUTED",
  "eligible": false
}
```

---

## 20. 项目管理、代码评审与完成定义

### 20.1 Issue/PR 粒度

每个功能 Issue 必须引用：流程图节点、规范条款类别、模块、Schema 字段、测试和验收证据。每个算法接入单独 PR，不能把十几个 codec 和框架改动混成一次不可审计提交。

### 20.2 评审问题

- 是否引入 hidden transform/fallback？
- 是否改变 Dataset/Config/Execution ID 语义？
- 是否让 adapter 决定公平性或统计？
- 是否漏掉 finalization、side info、model/index/header？
- 是否为失败状态提供可行动原因？
- 是否覆盖空输入、尾块、special values、overflow、capacity？
- 是否能在未来 C/C++ Runner 中表达相同合同？

### 20.3 “算法已接入”的定义

只有同时完成源码冻结、license、build、自测、manifest、negotiation、adapter、boundary/safety、correctness/bound、accounting、execution path、raw repetitions、summary/coverage 后，才能标 `QUALIFIED`。仅“能编译”“能 import”“上游 benchmark 有数字”均不算接入完成。

### 20.4 “Benchmark V2 首个可发布版本”的定义

- 五层所有节点有代码、Schema、测试和 artifact；
- 至少两类通用 lossless、一条 timestamp pipeline、一条 float lossless、一条 lossy、一条 SYSTEM 路径完成闭环；
- 13 个真实数据集和对抗 fixtures 已注册；
- Python Runner 稳定，C ABI 有 Golden Fixture；
- report 展示 Eligibility、Coverage、keys、raw/statistics；
- 可从冻结 source/build/config/environment 重跑；
- 已知不支持的 221 条目不被误报为通过。

---

## 21. 对用户要求的最终追踪矩阵

| 用户要求 | 本计划落实位置 | 验证方式 |
|---|---|---|
| 严格按结构图分层和步骤 | 第 6–10 章 | 每层输入/输出/步骤/自省清单 |
| Word/MD 约束分配并互联 | 第 1–2、5–10 章 | 规范词、状态、Schema、门禁与结果链 |
| Python 框架驱动源码 | 第 4、11、13 章 | Runner + Adapter SDK + source builds |
| 后续 C/C++ 版本适配 | 第 4.5、11.3、14.1 | 共享 Schema/C ABI/Golden cross-language |
| 参考 TSBench 行为 | 第 12 章 | 源码证据矩阵及“可复用/不可照搬” |
| 扫描现有算法与 TSBench | 第 3、12、18 章 | 221 条/72 repo/source lock audit |
| 使用 CompressBench14 | 第 3.4、Phase 0 | 环境 manifest 与 CI 命令 |
| 记录/获取参考 benchmark 库 | 第 12.3、16.1 | source lock、license、commit、用途 |
| 计划越详细越好且持续可用 | 全文，尤其 15–20 | 阶段 DoD、风险、评审、版本化合同 |
| 编写时阶段性自省 | 第 3.7、4.6、6.7、7.12、8.11、9.10、10.7、13.8、各 Phase | checklist 必须随实施逐项签署 |

### 21.1 最终自省

- [x] 没有把附件中的文字当作用户要求以外的执行指令；它们只作为用户指定的设计材料。
- [x] 计划以五层流程为主线，而不是按算法名称堆任务。
- [x] 每层都关联了标准约束、实现模块、失败状态、输出和测试。
- [x] 明确了 Python 现阶段实现与 C/C++ 未来实现的共同合同。
- [x] 记录了当前源码与数据的真实情况，包括不可用、归档、许可和环境限制。
- [x] 区分了 TSBench 可参考行为与不符合 V2 的行为。
- [x] 覆盖正确性、误差界、Temporal Fidelity、FinalBits、性能、资源、query、streaming、statistics、coverage 和 Pareto。
- [x] 明确第 3/4 层共享同一 Formal Repetition。
- [x] 明确 Semantic→Execution→Resource 为逐级收紧。
- [ ] 实施启动时需把本计划中的复选框转成 Issue/验收记录；计划本身不等于代码已实现。

---

## 22. 建议立即执行的前十项工作

1. 初始化项目 Git 和 `pyproject.toml`，锁定 `CompressBench14` 环境快照。
2. 将 Word、MD、流程图和两份说明的 hash 写入 `docs/source_contracts.json`。
3. 实现 `schemas/v2`、Enums、canonical JSON 与 ID Golden Fixtures。
4. 实现 append-only Run 状态机、`runs.csv`/JSONL writer 和结果校验器。
5. 实现 identity/corrupt/timeout/OOM/nondeterministic oracle adapters，证明门禁有效。
6. 为 13 个数据集编写 manifests 与 deterministic canonical loader，处理 PEMS/NPZ/weather 特例。
7. 生成 72 repo 的完整 Source Catalog，人工确认首批 LZ4/Zstd/Snappy/Brotli 许可证与构建。
8. 定义 C ABI v1 和 worker protocol，先接 LZ4 frame 完成 source-driven 五层闭环。
9. 接 Zstd 并用两种 codec 验证比较键、raw repetition、FinalBits 和 summary。
10. 在首个真实结果发布前运行本计划第 21 章追踪矩阵，任何 MUST 未闭合都阻止“V2 结果”标签。
