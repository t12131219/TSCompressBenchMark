# 压缩算法 C/C++ 独立重写工程规范
## Compression Algorithm Standalone C/C++ Porting Standard

**文档版本**：v2.0\
**修订基线日期**：2026-09-28\
**适用范围**：有损/无损压缩算法从 Python、NumPy、Go、Java、Kotlin、Rust、C#/.NET、JavaScript/TypeScript、Zig、MATLAB、Fortran、Julia、R 或其他语言独立迁移/重写至 C/C++；尤其适用于时序数据、传感器数据和科学计算数据。本文只覆盖算法重写及其独立验证，不覆盖 TSDataCompressBenchMark/TSBenchMark 接入。\
**目标读者**：项目经理、算法工程师、C/C++ 工程师、性能工程师、测试工程师、代码审查人员、研究生/科研开发人员。\
**文档性质**：工程规范、实现约束、Code Review 基线、CI 验收标准。\
**文件说明**：本文件名和正文版本均为 v2.0；v1.0 仅作为历史基线，不得继续作为新重写任务的验收依据。

---

# 0. 文档目标

本规范解决的不是“如何把其他语言的语法翻译成 C/C++”，而是：

> 在大规模压缩算法重写过程中，确保 **算法定义、数值语义、状态语义、bitstream 语义、内存语义、误差语义、性能计量语义和许可证语义** 不发生未经记录的变化。

整个迁移必须遵循：

```text
论文 / 标准 / 原始实现
        ↓
Algorithm Contract
        ↓
Golden Vectors
        ↓
Scalar Canonical C/C++
        ↓
Differential Validation
        ↓
Optimized C/C++
        ↓
SIMD / Thread / GPU / HLS
        ↓
再次 Differential Validation
```

核心原则：

> **Reference First → Correctness First → Optimization Second → Parallel/SIMD Third**

第一版 C/C++ 实现的目标是“正确、可解释、可验证”，不是“最快”。

重写完成后的 Benchmark 接入是后续独立工程活动，不在上述链路内，也不是本规范的交付物。

## 0.1 项目规范依赖与优先级

本规范使用以下项目文件提供术语和算法边界背景：

1. `TimeSeries_Compression_Benchmark_V2_工程实施总计划.md`：提供 ObjectLevel、算法边界、FinalBits 和联合码流等术语；
2. `registry/onboarding/README.md` 及 registry schema：仅用于理解资产身份和源码准入口径；
3. 本文件：非 C/C++ 实现从源码复现到独立 C/C++ 发布包的唯一重写验收规则。

总计划和 registry 不能扩大本标准的执行范围。凡涉及 adapter、ABI、registry 注册、Benchmark 配置、框架调用或正式排名的内容，均留待重写完成后的独立接入任务处理。重写实现不得为了适配当前框架而改变算法合同、公开 API 或 bitstream。

## 0.2 资产统计不得直接转化为重写任务

`Source_Code` 中的逻辑条目数量和仓库级语言统计只用于发现候选资产。它们可能重复指向同一仓库，也可能包含 binding、wrapper、primitive、pipeline、system、benchmark 或已有 C/C++ core。只有通过 G0/G1 后形成的 AlgorithmID 与 source closure 才是重写任务清单。

截至 2026-09-28 的盘点快照为 221 个逻辑条目、约 72 个去重仓库；该数字不是独立 codec 数量，也不是待重写数量。metadata 的 `primary_language` 不能替代 source closure 的实际语言判定。

## 0.3 重写与接入的强制边界

本规范中的“重写”是指在 `Compression_Rewrite/Source/<algorithm_id>` 和 `Compression_Rewrite/ReWrite/<algorithm_id>` 内完成可独立构建、运行、测试和验证的 C/C++ 算法交付包。

以下工作属于“接入”，本标准明确 **禁止实施**：

- 编写或修改 `tscb_adapter_v1`、Benchmark plugin、Python adapter 或框架 wrapper；
- 修改 TSDataCompressBenchMark 的 `adapters/`、`native/`、`registry/`、`configs/experiments/`、`src/tscompbench/` 或框架测试；
- 为重写算法登记 Benchmark capability、运行正式排名或提交 Benchmark 结果；
- 以接入便利为由改变算法格式、参数、状态、reset/finalize 或错误语义；
- 将重写和接入放在同一任务、同一 PR、同一验收结论或同一状态中。

重写完成后只可声明 `REWRITE_DONE`。只有另行创建、授权并执行接入任务后，才可以声明 `INTEGRATED` 或 `BENCHMARK_READY`。未来接入任务必须消费冻结的重写产物，不得回写、搬迁或悄然修改 canonical 算法实现；必要的框架适配必须位于重写目录之外。

## 0.4 单算法端到端完成原则

每次选择一个算法执行重写时，授权范围默认覆盖本规范 G0-G6 的全部重写阶段。执行者不得在只完成源码复制、语法翻译、encoder、decoder、canonical 版本、单组样例或某个中间 Gate 后，将任务声明为完成并转入下一算法。

单算法任务必须遵守：

1. G0-G2 发现硬阻断时，将任务标记为 `BLOCKED`，保留证据并停止实现；
2. 一旦进入 G3 编码阶段，必须连续推进 canonical、完整编解码、独立 API、测试、安全验证、必要优化、文档和可复现发布，直至 G6；
3. encoder 与 decoder、timestamp 与 value 联合码流、模型与容器、训练/推理所需状态不得拆成彼此独立的“已完成”任务；
4. 优化不是替代 canonical 的后续补丁；所有 `REQUIRED_PARITY` optimized path 必须在同一次重写交付中完成，只有上游不存在 required optimized capability 时才可记录 `OPTIMIZATION_NOT_APPLICABLE`，`OPTIONAL_OPTIMIZATION` 可进入明确 backlog；
5. 任务结束只能是 `REWRITE_DONE` 或有具体阻断证据的 `BLOCKED`，不得使用含糊的“基本完成”“待以后补测试”或 `BENCH_READY`。

## 0.5 工具链与执行权限

为准确读取、运行和验证参考实现，重写任务允许自行下载、安装和使用所需的源语言编译器、运行时、SDK、构建工具及依赖，例如 JDK、Go toolchain、Rust toolchain、Python/conda/venv、Node.js、.NET SDK、Zig、Julia、R、Fortran 或 MATLAB-compatible runtime。

该授权必须满足：

- 优先使用项目局部目录、版本管理器、容器或隔离环境，不覆盖系统默认编译器和用户已有环境；
- 固定下载 URL、版本、目标平台及 SHA-256；记录安装和构建命令、lockfile、环境变量与镜像 digest；
- 只安装复现 source closure 和 oracle 所必需的组件，不执行来源不明的二进制或安装脚本；
- 需要网络、包管理器或较高系统权限时，可以按执行环境的审批机制申请，不得因工具缺失而跳过参考实现测试；
- 参考环境与 C/C++ 构建环境必须分别记录；参考工具链不得成为最终 C/C++ 运行时依赖，除非算法合同明确包含该依赖且获得书面批准；
- 临时服务、进程和缓存必须可识别、可停止；不得删除或覆盖与当前算法无关的用户数据和环境。

“本机没有 Java/Go/Rust/Python 某版本”不是降低 CompatibilityTarget 或省略 differential/cross-decode 的理由。

---

# 1. 规范性用语

本文件使用以下强制等级：

| 术语 | 含义 |
|---|---|
| **MUST / 必须** | 不满足则实现不得合入 canonical 分支 |
| **MUST NOT / 禁止** | 一旦违反视为 correctness defect |
| **SHOULD / 应当** | 除非有明确理由，否则必须遵守 |
| **SHOULD NOT / 不应** | 原则上禁止，若采用需记录原因 |
| **MAY / 可以** | 可选实现策略 |
| **WAIVER / 豁免** | 对规范的正式例外，必须留下书面理由和影响分析 |

任何开发者不得以“性能更快”“代码更短”“在我的机器上没问题”为理由绕过 MUST 条款。

---

# 2. 重写工作的正交分类

旧版使用 P1/P2/P3 同时表达迁移方式和兼容程度，与 Benchmark 已有的 P0/P1/P2/P3 `ObjectLevel` 冲突。v2.0 起禁止使用含义不明确的 `porting_level`，每个实现必须分别声明以下三个维度。

## 2.1 PortMethod：实现来源方式

| 值 | 含义 | 最低证据要求 |
|---|---|---|
| `TRANSLATED` | 逐语句或结构化翻译既有源码 | 原文件/片段映射、许可证继承、差异清单 |
| `CLEAN_ROOM` | 依据公开格式、行为合同和独立测试重新实现 | 设计输入、角色隔离记录（如适用）、cross-decode/differential 证据 |
| `PAPER_BASED` | 依据论文、标准或伪代码实现 | 公式到代码映射、未定义细节决策和验证依据 |

`TRANSLATED` 不得标记为 `CLEAN_ROOM`。同一实现混用多种方式时，必须按文件或模块记录 provenance。

## 2.2 CompatibilityTarget：兼容目标

| 值 | 要求 |
|---|---|
| `SEMANTIC` | 输入域、参数、边界、状态、重建或误差合同与参考实现一致；不承诺格式互通 |
| `CROSS_DECODE` | 新编码器可由参考解码器读取，且新解码器可读取参考编码器输出 |
| `BYTE_IDENTICAL` | 在冻结的配置、版本和确定性条件下，输出字节与参考实现完全相同 |

所有重写至少必须达到 `SEMANTIC`。存在公开或官方 bitstream 的实现，应达到 `CROSS_DECODE`；只有格式要求 canonical encoding 或项目确有字节一致需求时才要求 `BYTE_IDENTICAL`。

## 2.3 ObjectLevel：重写对象层级

| 值 | 含义 | 例子 |
|---|---|---|
| `P0_PRIMITIVE` | 不一定能独立解码的原语或 stage | Delta、ZigZag、bit packing、quantization |
| `P1_STANDALONE_CODEC` | 独立、自包含的 codec | LZ4 frame、Zstandard frame |
| `P2_PIPELINE` | 多 stage 组合且拥有完整解码合同 | Delta + ZigZag + entropy coding |
| `P3_SYSTEM` | storage/container/query 系统对象 | TSFile、数据库 segment、联合 T/V 容器 |

ObjectLevel 只描述重写对象，不描述移植质量。P0 primitive 不得冒充独立 codec；P3 system 必须保留其容器和联合状态边界。

## 2.4 AlgorithmID 与 ImplementationID

- `algorithm_id` 标识稳定的算法/格式合同，不因语言或优化变体变化；
- `implementation_id` 标识具体来源、语言、版本和实现；
- `variant` 标识 scalar、AVX2、NEON、CUDA 等执行变体；
- 目录名必须使用稳定 ASCII slug；展示名称单独记录为 `display_name`；
- 同一仓库、目录或 metadata 条目不自动等于一个独立算法。

## 2.5 NativeCapabilityParity：上游原生能力保留等级

每个算法必须建立 `NATIVE_CAPABILITY_MATRIX.yaml`，逐项记录上游实现真实具备的功能和执行变体，不得只记录 canonical scalar。能力至少包括：

```text
one-shot / block / chunk / continuous streaming
stateful reset / finalize / flush / seek / random access
incremental encode / incremental decode / output backpressure
supported dtype / shape / layout / loss mode
dictionary / model / checkpoint / online update
SIMD ISA variants and runtime dispatch
internal multithreading / concurrent handles / thread safety
GPU / CUDA / HIP / SYCL / OpenCL / HLS
in-place / zero-copy / query / checksum / format version
```

每项 capability 必须且只能归入下列一种状态：

| 状态 | 含义 | 对 `REWRITE_DONE` 的影响 |
|---|---|---|
| `REQUIRED_PARITY` | 上游已有且属于正式、可达、受支持的算法能力或执行路径 | 必须在 C/C++ 中实现并通过专项验证，否则阻断 |
| `OPTIONAL_OPTIMIZATION` | 不改变算法功能/格式、且不属于上游正式承诺的新优化或实验性变体 | 可以进入明确 backlog，不得宣称已经支持 |
| `UNAVAILABLE_WITH_WAIVER` | 原生能力应保留，但因已证实的平台、硬件、工具链或法律限制当前无法实现 | 仅在正式 WAIVER 有效时允许发布；总体只能标记 `PARTIAL_WITH_WAIVER` |
| `NOT_APPLICABLE` | 上游不具备该能力，或该能力不属于锁定的 source closure/算法对象 | 必须提供可审计依据，不产生实现义务 |

分类的默认规则：

- 出现在上游公开 API、用户文档、release build、默认/官方 feature flag、CI、正式测试或受维护执行路径中的能力，默认是 `REQUIRED_PARITY`；
- 上游已有并受支持的 streaming、SIMD、内部多线程、并发 handle、random access 或 GPU 路径，不得仅因 canonical scalar 已正确而降为 optional；
- 仅存在于 dead code、未发布实验分支、不可达示例或与当前 AlgorithmID 无关的辅助工具中的能力，才可在证据充分时归入 `OPTIONAL_OPTIMIZATION` 或 `NOT_APPLICABLE`；
- 重写团队新提出、上游不存在的 AVX-512、NEON、GPU 或并行优化，可以是 `OPTIONAL_OPTIMIZATION`；
- “开发时间不足”“实现复杂”“当前机器较慢”不是 `UNAVAILABLE_WITH_WAIVER` 的充分理由；
- 同一能力在不同平台可分别分类，例如 `AVX2=REQUIRED_PARITY`、`NEON=NOT_APPLICABLE`，禁止用笼统的 `SIMD=true` 代替 ISA 级清单。

总体结果只能是：

```text
FULL_PARITY
PARTIAL_WITH_WAIVER
FAIL
```

只有所有 `REQUIRED_PARITY` 项通过且不存在 waiver 时才能声明 `FULL_PARITY`。

---

# 3. 项目治理与阶段 Gate

任何候选条目必须依次经过 G0-G6。Gate 的输入、输出、审查人和证据文件必须写入 `PORT_MANIFEST.yaml`；不得仅凭仓库级 `primary_language` 决定重写。单次重写任务的交付范围是全部 Gate，不允许按 Gate 拆成多个“以后再完成”的任务。

## Gate G0：资产去重与 AlgorithmID 分配

必须完成：

- 将逻辑条目映射到去重后的 repository/worktree；
- 区分算法、primitive、pipeline、system、binding、wrapper、benchmark 和重复引用；
- 判断是否已有可复用的 C/C++ core，非 C/C++ binding 不构成重写理由；
- 为真实算法对象分配稳定 `algorithm_id`、`implementation_id` 和 `ObjectLevel`；
- 判断对象是否独立可编码/解码；非自包含 stage 必须标为 P0 或纳入完整 P2 pipeline；
- 联合码流必须保持整体边界，例如 Prometheus `xor2.go` 的 timestamp/value 共享 control bits 时禁止强拆。

**G0 未通过的条目不得复制到批量重写目录。**

## Gate G1：Source Closure、来源与许可证锁定

必须明确：

- 论文、仓库、commit/tag/version、submodule 和依赖；
- 真正参与构建或解释执行的 translation-unit/source closure，而非仓库语言汇总；
- closure 中每个文件的 SHA-256、角色、语言、生成来源和许可证；
- 构建入口、代码生成步骤、补丁和测试向量；
- 为运行参考实现所需的精确 compiler/runtime/SDK、依赖锁和可重建环境；
- redistribution、修改和商业使用条件；
- 是否存在官方 decoder、公开格式和交叉解码条件。
- 从 source closure、构建系统、feature flags、公开 API、文档、CI 和测试中提取完整 native capability inventory，并为每项保存证据位置。

**G1 未通过，不允许开始正式移植。**

## Gate G2：Algorithm Contract 与 Oracle 冻结

必须冻结输入类型、布局、参数、数学公式、边界条件、状态、bitstream、error bound、输出条件、CompatibilityTarget，并建立可执行 golden/differential/cross-decode oracle。还必须完成 `NATIVE_CAPABILITY_MATRIX.yaml` 的四态分类及逐项测试计划，并从项目 `datasets/` 中选择与算法输入域兼容的数据，形成 `DATASET_TEST_PLAN.yaml`；若当前没有兼容数据，必须记录证据并补充合法测试数据或提交 WAIVER。

**G2 未通过，不允许编写 canonical C/C++。**

## Gate G3：Canonical Scalar Correctness

要求 scalar C/C++、golden、differential、无损 round-trip 或有损误差合同、sanitizer、边界和 malformed-input 测试全部通过。原始实现与重写实现还必须在 `DATASET_TEST_PLAN.yaml` 选定的相同真实数据、相同预处理结果和相同参数上完成 dataset differential validation。

## Gate G4：独立 API 与资格测试

要求：

- 提供重写包自有的、与 TSDataCompressBenchMark 无关的 C 或 C++ public API 和 CLI/测试驱动；
- setup/create、compress、finalize、decompress、query、reset 和 destroy 生命周期可区分；
- `FinalBits` 和组件账本闭合；
- canonical 与 optimized 执行路径可辨识；
- 独立 API 能暴露所有属于 `REQUIRED_PARITY` 的功能能力，不能由未来接入层补齐；
- 输入不可修改、canary、safe overread、bound-1、重复 finalize、N=0/1/2、B-1/B/B+1 和 T/V pairing 等 preflight 通过。

G4 禁止产生 `tscb_adapter_v1`、registry entry 或 Benchmark 配置。资格测试必须直接调用重写包的独立 API。

## Gate G5：Optimization

只有 G3/G4 通过以后才允许优化实现：

- SIMD；
- OpenMP；
- pthread/std::thread；
- CUDA；
- architecture-specific intrinsic；
- fast-math 实验；
- GPU；
- HLS/FPGA。

G5 不是任意优化阶段：`NATIVE_CAPABILITY_MATRIX.yaml` 中属于 `REQUIRED_PARITY` 的 SIMD、多线程、GPU 或其他 optimized path 必须在本 Gate 实现并验证。只有 `OPTIONAL_OPTIMIZATION` 可以进入后续 backlog。

## Gate G6：Release

必须完成：

- correctness；
- portability；
- security；
- performance；
- license；
- documentation；
- reproducibility。

G6 前必须生成 `dataset_validation_report.md` 并满足第 38.2 节的通过条件；只通过 toy vector、随机数组或单个 smoke case 不足以声明重写完善。

G6 前还必须通过 NativeCapabilityParity Gate：所有能力已分类、所有 `REQUIRED_PARITY` 项已通过、所有 `UNAVAILABLE_WITH_WAIVER` 项具有未过期批准，且不存在 `UNCLASSIFIED`、`NOT_TESTED` 或静默 fallback。

G6 的产物是可独立消费的 `REWRITE_DONE` 发布包。它不得依赖 TSDataCompressBenchMark 源码、运行时、adapter 或 registry 才能构建和验证。

发布后的验证产物保留、清理和去重必须遵守第 113 章。`FULL_PARITY` 不能单独作为删除验证产物的依据；清理不得破坏 G0-G6、CAP-GATE 或发布包的证据闭环。

## NativeCapabilityParity Gate（CAP-GATE）

CAP-GATE 是贯穿 G1-G6 的强制 Gate，而不是 G6 末尾补填的表格：

| 检查点 | 必须产物 | 通过条件 |
|---|---|---|
| G1-CAP Inventory | 上游能力清单与证据 | public API、build flags、tests、CI、docs 和可达路径已检查 |
| G2-CAP Classification | `NATIVE_CAPABILITY_MATRIX.yaml` | 每项为四态之一，owner、理由、测试和平台已冻结 |
| G3-CAP Functional | streaming/state/random-access 等功能验证 | 所有功能型 `REQUIRED_PARITY` 已由 canonical 实现覆盖 |
| G4-CAP API | 独立 API capability tests | required 能力可直接调用、查询且生命周期一致 |
| G5-CAP Optimized | SIMD/thread/GPU 等 variant 验证 | 所有优化型 `REQUIRED_PARITY` 已实现，无静默 fallback |
| G6-CAP Closure | `native_capability_validation_report.md` | required 全 PASS；waiver 有效；总体结果明确 |

任一 `REQUIRED_PARITY` 项为 `MISSING`、`FAIL` 或 `NOT_TESTED` 时，CAP-GATE 失败，算法不得进入 `REWRITE_DONE`。

---

# 4. 每个算法必须提交的交付物

项目交付目录必须使用相同的 `<algorithm_id>` 一一对应：

```text
Compression_Rewrite/
├── Source/<algorithm_id>/
│   ├── upstream/                  # 锁定的原始 source closure，不在此目录直接修改
│   ├── SOURCE_MANIFEST.yaml
│   ├── TOOLCHAIN_MANIFEST.yaml    # 源语言 compiler/runtime/SDK、下载 hash 和复现命令
│   ├── PATCHES/                   # 为运行 oracle 所需的最小补丁
│   └── LICENSES/
└── ReWrite/<algorithm_id>/
    ├── README.md
    ├── PORT_MANIFEST.yaml
    ├── NATIVE_CAPABILITY_MATRIX.yaml
    ├── contract.md
    ├── CMakeLists.txt
    ├── include/
    ├── src/
    │   ├── canonical/
    │   └── optimized/
    ├── tools/                     # 独立 CLI、向量生成和诊断工具；禁止放 Benchmark adapter
    ├── tests/
    │   ├── golden/
    │   ├── differential/
    │   ├── datasets/              # 只存测试清单/loader；项目 datasets/ 原文件保持只读
    │   ├── cross_decode/
    │   ├── malformed/
    │   └── performance/
    ├── LICENSES/
    └── validation/
        ├── porting_report.md
        ├── DATASET_TEST_PLAN.yaml
        ├── dataset_validation_report.md
        ├── native_capability_validation_report.md
        ├── validation_report.md
        └── build_reproducibility.md
```

`Source/<algorithm_id>/upstream` 必须是可审计快照，不得在其中混入重写代码。运行参考实现所需的修改必须保存为补丁并记录 patch hash。不得复制整个大型仓库来代替 source closure，除非 contract 确实依赖整个仓库且有书面说明。

每个算法 MUST 有：

```text
SOURCE_MANIFEST.yaml
TOOLCHAIN_MANIFEST.yaml
PORT_MANIFEST.yaml
NATIVE_CAPABILITY_MATRIX.yaml
contract.md
canonical implementation
unit tests
golden tests
dataset test plan and source-vs-rewrite report
native capability inventory, parity matrix and validation report
validation report
source closure/license record
reproducible build record
standalone build/test entrypoint
REWRITE_DONE evidence
```

---

# 5. Algorithm Contract 模板

每个算法在编码前必须填写。

```yaml
algorithm_id:
implementation_id:
algorithm_name:
display_name:
category: lossless | lossy
family:
object_level: P0_PRIMITIVE | P1_STANDALONE_CODEC | P2_PIPELINE | P3_SYSTEM
source:
  paper:
  repo:
  commit:
  version:
  archive_sha256:
  closure_sha256:
  patch_sha256:
original_language:
source_language_version:
source_runtime:
source_backend_target:
source_build_profile:
source_dependency_lock_sha256:
source_toolchain:
  compiler_or_runtime:
  exact_version:
  target:
  acquisition_url:
  archive_sha256:
  install_method:
  isolated_environment:
  environment_digest:
  build_command:
  test_command:
port_method: TRANSLATED | CLEAN_ROOM | PAPER_BASED
compatibility_target: SEMANTIC | CROSS_DECODE | BYTE_IDENTICAL
license:
  concluded_spdx:
  files:
  dependencies:
  redistribution_status:

input:
  dtype:
  dimensions:
  layout:
  signedness:
  endian:
  allows_empty:
  supports_nan:
  supports_inf:
  supports_negative_zero:
  supports_subnormal:

state:
  stateless:
  streaming:
  block_independent:
  cross_block_history:
  dictionary:
  reset_semantics:

lossy:
  enabled:
  error_mode:
  error_value:
  rounding:
  fp_precision:
  fma_policy:
  nan_policy:
  inf_policy:

bitstream:
  standardized:
  specification:
  byte_order:
  bit_order:
  version:
  checksum:
  frame_structure:

native_capability_parity:
  overall_result: FULL_PARITY | PARTIAL_WITH_WAIVER | FAIL
  matrix_path: NATIVE_CAPABILITY_MATRIX.yaml
  validation_report: validation/native_capability_validation_report.md
  unclassified_count: 0
  required_total:
  required_passed:
  waiver_ids: []

standalone_validation:
  preprocessing_included:
  execution_scopes: [CORE, PIPELINE, E2E]
  dataset_suite:
    source_root: datasets/
    plan_sha256:
    selected_dataset_ids: []
    canonical_input_hashes: []
    case_unit:
    label_policy:
    partition_policy:
    row_boundary_policy:
    source_vs_rewrite_required: true
  serialized_bits_components:
    - timestamp | value | shared | metadata | validity | model | dictionary | index | checkpoint | checksum | padding | container
  external_side_information_bits:
  workspace_accounted:
  threads:
  isa:

integration:
  performed: false
  tscb_adapter_present: false
  registry_modified: false
  note: "Out of scope; requires a separate post-rewrite task."

execution:
  scope: REWRITE_ONLY
  required_gates: [G0, G1, G2, G3, G4, G5, G6]
  current_gate:
  terminal_status: "REWRITE_DONE | BLOCKED"
  blocker_evidence:

build:
  c_standard:
  cxx_standard:
  compiler:
  compiler_version:
  flags:
  compile_commands_sha256:
  artifact_sha256:
  environment_digest:
```

## 5.1 `NATIVE_CAPABILITY_MATRIX.yaml` 模板

每个 capability 必须使用稳定 `capability_id`，并分别记录上游证据、分类、重写实现和验证状态：

```yaml
schema_version: 1
algorithm_id:
upstream_revision:
overall_result: FULL_PARITY | PARTIAL_WITH_WAIVER | FAIL

capabilities:
  - capability_id: streaming.incremental_encode
    category: STREAMING_STATEFUL
    upstream:
      present: true
      public_or_supported: true
      evidence:
        - path:
          symbol_or_test:
          lines_or_case:
          sha256:
      platforms: []
      build_flags: []
      semantic_contract:
        reset_frequency:
        flush_semantics:
        finalize_semantics:
    parity_class: REQUIRED_PARITY
    rewrite:
      present: true
      public_symbol:
      variant:
      platforms: []
      build_target:
    validation:
      status: PASS | FAIL | NOT_TESTED | WAIVED
      oracle:
      tests: []
      artifact_hashes: []
    waiver_id:
    rationale:

  - capability_id: simd.avx2
    category: SIMD
    upstream:
      present: true
      public_or_supported: true
      evidence: []
      platforms: [linux-x86_64]
      build_flags: [avx2]
    parity_class: REQUIRED_PARITY
    rewrite:
      present: true
      variant: avx2
      runtime_dispatch: true
      fallback: scalar
    validation:
      status: PASS
      forced_path_test: true
      tail_tests: []
      differential_tests: []

  - capability_id: threading.internal_parallel_encode
    category: MULTITHREADING
    upstream:
      present: true
      public_or_supported: true
      evidence: []
      supported_thread_counts: "1..N"
    parity_class: REQUIRED_PARITY
    rewrite:
      present: true
      thread_control_api:
    validation:
      status: PASS
      thread_counts_tested: [1, 2, 3]
      tsan: PASS
      determinism: PASS
```

不得使用 `present: true` 代替证据，不得用性能提升间接证明 optimized path 实际执行。每项 PASS 必须能追溯到测试命令、运行平台、日志或 artifact hash。

---

# 6. 源语言语义审计

迁移前 MUST 写一份“Source Language Semantic Audit”。

原因：不同语言相同表达式可能具有不同语义。

语言审计对象必须来自 G1 锁定的 source closure，而不是仓库内所有扩展名。当前资产中可见的 C#、Kotlin、JavaScript、R 或 Fortran 文件有相当一部分属于 binding、vendor、测试、文档或可视化脚本；这些文件的存在不表示算法核心需要重写。反之，TerseTS 的 Zig 文件、Brotli 的 TypeScript/Kotlin decoder 等可能直接包含 codec 逻辑，必须按实际调用闭包判断。

所有语言审计至少记录：

```text
language/compiler/runtime exact version
backend/target/word size/build profile
package lockfile and dependency closure
integer widths, overflow, shift, division and conversion
floating precision, rounding, contraction and special values
array layout, slice/view/copy/alias and lifetime
collection iteration and tie-breaking determinism
exception/panic/error and bounds behavior
serialization, endian and bit order
threading/async/task-local/global state
JIT/GC/setup/finalization boundary
native extension/FFI and existing C/C++ core
```

---

## 6.1 Python

### PY-001：Python `int` 不得直接映射为 C `int`

Python 内置整数具有任意精度。

所以：

```python
x = a * b
```

不能默认翻译为：

```cpp
int x = a * b;
```

必须确定原算法的理论位宽。

### PY-002：必须区分 Python `int` 与 NumPy integer

NumPy：

```python
np.int32
np.int64
np.uint32
```

属于固定宽度数值类型。

其溢出行为和 Python `int` 不同。

### PY-003：Python `round()` 必须审计

Python 内置：

```python
round(0.5) == 0
round(1.5) == 2
round(2.5) == 2
```

采用 nearest-even tie-breaking。

不得直接替换成：

```cpp
std::round()
```

因为 C/C++ `round()` halfway 是 away-from-zero。

### PY-004：`//`、`%` 和负数右移必须显式重现

Python 整数 `a // b` 向负无穷取整，`a % b` 的符号与除数一致；负整数右移等价于按 `2^n` 做 floor division。C/C++ 整数除法向零截断，直接使用 `/`、`%` 或依赖实现细节的 signed shift 可能改变 residual、bucket 和 entropy symbol。

只要操作数可能为负，必须使用经过边界测试的 helper，并覆盖正负操作数组合、最小值和除数为零。

### PY-005：NumPy dtype promotion、casting 和 endian 必须锁定

必须记录每个关键表达式的输入 dtype、输出 dtype、ufunc promotion、标量/数组混算、溢出和 casting rule。不得假设 NumPy promotion 与 C++ usual arithmetic conversions 相同。

对 `view`、`astype`、`byteswap`、structured dtype 和 memory-mapped array，必须同时记录 byte order、itemsize、alignment 和是否发生复制。

### PY-006：数组连续性与 view/copy 语义必须审核

必须区分 C-contiguous、Fortran-contiguous、strided view、negative stride 和广播视图。重写若把非连续 view 隐式物化为连续数组，必须验证语义，并在相应 E2E scope 中计入转换时间与内存。

---

## 6.2 Java

### JAVA-001：整数 overflow 语义必须显式复制

Java 固定宽度整数溢出保留低位，即具有定义好的二补码 wrap 行为。

C/C++ signed overflow 则可能是 undefined behavior。

错误迁移：

```java
int hash = value * 0x9E3779B9;
```

直接变成：

```cpp
int32_t hash = value * 0x9E3779B9;
```

正确策略通常是先转换成：

```cpp
uint32_t hash =
    static_cast<uint32_t>(value) * UINT32_C(0x9E3779B9);
```

再在需要时显式解释位模式。

### JAVA-002：Java shift distance 必须审计

Java 对 `int` shift 只使用 shift count 的低 5 bit，对 `long` 使用低 6 bit。

C/C++ 不允许直接假设相同语义。

所有 Java：

```java
x << s
x >> s
x >>> s
```

迁移时必须独立审核。

特别注意 Java `>>>` 无符号右移在 C/C++ 中没有 signed 类型的一一对应操作。

### JAVA-003：除法、余数和极值必须审核

Java 整数除法向零截断，余数与 dividend 同号；除数为零抛出异常。`MIN_VALUE / -1` 在 Java 中产生 `MIN_VALUE`，而对应 C/C++ signed 运算可能产生 undefined behavior。必须用显式 helper 保留这些语义。

### JAVA-004：narrowing、byte 和 char 语义必须审核

Java `byte` 是 signed 8-bit，`char` 是 unsigned 16-bit UTF-16 code unit。赋值转换、cast 和 compound assignment 的截断/符号扩展必须逐处记录；不能把 Java `byte[]` 无条件映射为 C++ `char[]`。

### JAVA-005：ByteBuffer 与序列化端序必须锁定

必须记录 `ByteBuffer.order()`、typed view、position/limit、slice/duplicate 和 direct/heap buffer 行为。禁止使用 host-native load/store 替代显式 bitstream endian。

### JAVA-006：Java 版本和 floating-point 语义必须记录

Java SE 17 及以后所有浮点表达式均为 strict floating-point。迁移必须记录 JDK major version，并审计求值精度、舍入、NaN、Infinity、signed zero 和是否允许 C/C++ FP contraction/FMA。

---

## 6.3 Rust

### RUST-001：不得假设普通 Rust overflow 始终等于 C++ unsigned wrap

Rust debug 与某些 build configuration 下 overflow 可 panic；release 可能 wrap。

原实现若使用：

```rust
wrapping_add
wrapping_mul
checked_add
saturating_add
```

必须逐一保留对应语义。

### RUST-002：`wrapping_*` 必须用显式无符号或专门 helper 重现

禁止依赖 C/C++ signed overflow。

### RUST-003：`usize/isize` 和 target 必须锁定

`usize/isize` 的位宽随 target 变化。凡其进入 bitstream、hash、索引或算术状态，必须锁定参考 target 并转换为显式宽度类型；不得把 `usize` 机械翻译为固定的 `uint64_t`。

### RUST-004：overflow-check profile 与 panic 条件必须记录

必须保存 Rust toolchain、Cargo profile、`overflow-checks` 设置。普通算术、非法或超宽 shift、除数为零、signed 最小值除以 `-1`、越界索引和 slice 操作的 panic 行为必须纳入 contract；C/C++ 端不得以 UB 代替参考实现的确定失败。

### RUST-005：`as`、TryFrom 和 bit reinterpretation 必须区分

Rust `as` 数值转换、`TryFrom` 检查转换、`from_*_bytes` 与 `transmute` 的行为不同。移植必须逐处标注 narrowing、saturation、truncation、符号扩展和 bit reinterpretation，优先使用 checked helper 或 `memcpy`/`bit_cast`。

### RUST-006：unsafe、slice alias 和 endian 必须审核

所有参与 source closure 的 `unsafe` block 必须列入审计清单。需要记录 slice 长度、alignment、alias 前提、`get_unchecked` 的证明条件，以及 `to_le_bytes`/`from_le_bytes` 等显式端序操作。

---

## 6.4 Go

### GO-001：`int`/`uint` 和目标架构必须锁定

Go 的 `int`、`uint` 和 `uintptr` 为 32 或 64 bit，取决于实现和目标。只要值进入算法状态、索引、hash 或 bitstream，必须记录 `GOOS`、`GOARCH`、Go version，并映射为有证明的 C/C++ 固定宽度类型或 `size_t`。

### GO-002：signed overflow 不得翻译为 C/C++ signed overflow

Go 对有符号整数 overflow 的结果是确定的二补码截断，编译器不得基于“不发生 overflow”进行推断；C/C++ signed overflow 是 undefined behavior。必须通过对应无符号位模式或经过测试的 helper 重现。

### GO-003：shift、除法、余数和 conversion 必须审核

Go 非常量 shift count 没有按左操作数位宽取模的上限规则，负 shift count 会 panic；转换后的值可能截断并符号扩展。整数除法向零截断，余数符号跟 dividend。所有可能超宽、为负或到达极值的路径必须形成 golden/boundary tests。

### GO-004：map 迭代不得影响确定性输出

Go map 的迭代顺序不保证稳定。若 map 参与 codebook、header、dictionary、model 或 symbol 排序，必须先使用规范化排序或记录 tie-breaker；否则不得承诺 deterministic 或 `BYTE_IDENTICAL`。

### GO-005：slice alias、capacity 和 append 必须审核

Go slice 是共享 backing array 的 descriptor，`append` 可能原地写入或重新分配。移植必须记录 len/cap、subslice alias、append 后旧 view 是否仍观察到修改，以及 overlap copy 语义。

### GO-006：浮点 contraction/FMA 必须锁定

Go 实现可将浮点表达式合并为 FMA；显式转换可能要求中间舍入。凡 predictor 或 quantizer 位于舍入边界，必须以参考 Go 版本和目标平台建立 golden vectors，并在 canonical C/C++ 中固定 contraction policy。

---

## 6.5 MATLAB

### MATLAB-001：数组布局必须审核

MATLAB 默认：

```text
column-major
```

C/C++ 常规二维数组：

```text
row-major
```

因此 MATLAB：

```matlab
A(i,j)
```

迁移时不能机械映射。

必须审计：

- linear indexing；
- reshape；
- transpose；
- permute；
- flatten；
- 邻域访问；
- predictor 邻接关系。

### MATLAB-002：round 版本和 TieBreaker 必须记录

现代 MATLAB 默认 tie 行为可与 C/C++ `std::round` 接近，但历史版本行为发生过变化。

项目必须记录：

```text
MATLAB version
round tie mode
```

### MATLAB-003：矩阵运算顺序不得擅自改变

```matlab
A * B
```

如果迁移时为了方便将数据 transpose 后计算，必须证明：

```text
数学含义一致
+
storage layout 转换成本被正确计量
```

---

## 6.6 C# / .NET

### CSHARP-001：`checked`/`unchecked` 与项目溢出配置必须锁定

C# 整数 overflow 取决于显式 `checked`/`unchecked`、常量表达式以及项目的 overflow-check 配置。必须记录 .NET SDK/runtime、target framework、`CheckForOverflowUnderflow` 和相关编译选项。不得把 unchecked wrap 直接翻译为 C/C++ signed overflow；应通过无符号位模式或 checked helper 重现。

### CSHARP-002：整数类型、移位和除法必须审核

必须区分 `byte`、`sbyte`、`char`、`int`、`uint`、`long`、`ulong`、`nint` 和 `nuint`。`nint/nuint` 随进程位宽变化；`int`/`long` shift count 会被掩码，`>>` 与 C# 11 起的 `>>>` 含义不同。整数除法向零截断，最小 signed 值除以 `-1` 以及除数为零的异常行为必须形成边界测试。

### CSHARP-003：舍入、`decimal` 和浮点语义必须审核

`Math.Round` 默认 midpoint-to-even，重载和 `MidpointRounding` 可改变规则；`decimal` 是十进制定点风格类型，不得机械映射为 `double`。必须记录 JIT/runtime、浮点 precision、FMA/硬件 intrinsic、NaN、Infinity、signed zero 和 conversion 行为。

### CSHARP-004：Span、数组和 Buffer 所有权必须审核

`Span<T>`/`ReadOnlySpan<T>`、`Memory<T>`、`ArraySegment<T>` 和 `byte[]` 可能共享存储。必须记录 slice、overlap、pinning、GC relocation、stackalloc 和 unsafe/fixed pointer 的生命周期。Stream 或其他 wrapper 的额外 buffering/finalize 也必须纳入 PIPELINE/E2E。

### CSHARP-005：序列化端序必须显式

`BitConverter` 可能使用 host endian；跨平台格式应审计 `BinaryPrimitives`、`MemoryMarshal`、unsafe cast 和 struct layout。禁止直接 dump managed struct 或依赖 CLR padding 形成 bitstream。

---

## 6.7 JavaScript / TypeScript

### JS-001：`Number`、`BigInt` 和 bitwise domain 必须区分

JavaScript `Number` 是 IEEE-754 binary64，只能精确表示绝对值不超过 `2^53-1` 的整数。普通 bitwise 运算通常先转换到 32-bit integer，shift count 使用低 5 bit；`BigInt` 是不同数值域，不能与 `Number` 隐式混算，且不支持 unsigned right shift。任何 timestamp、offset、hash 或 bit accumulator 都必须标注实际数值域。

### JS-002：TypeScript 类型不能作为运行时语义证据

TypeScript 类型在生成 JavaScript 后被擦除。审计必须以实际生成产物、`tsconfig`、target/module、transpiler/bundler 版本和 Node/browser runtime 为准；`number` 注解不提供整数宽度或溢出保证。

### JS-003：TypedArray、DataView 和 Node Buffer 端序/别名必须审核

多字节 TypedArray 按平台原生端序解释 backing buffer，`DataView` 的 endian 参数必须显式；Node `Buffer.subarray`/部分 slice 操作共享内存。必须记录 byteOffset、byteLength、alignment、view alias、copy 与 detach/transfer 行为。

### JS-004：舍入、负零和 conversion 必须审核

`Math.round` 的 tie 方向和 `-0` 行为不同于 Python `round` 与 C++ `std::round`。`Math.trunc`、`floor`、`ceil`、ToInt32/ToUint32 和 BigInt conversion 必须逐处映射，并覆盖 `NaN`、Infinity、signed zero 和精度边界。

### JS-005：集合顺序与运行时成本必须隔离

即使特定 runtime 对 property/Map iteration 有定义，产生 canonical codebook、model 或 header 时仍必须显式排序和定义 tie-breaker。JIT tiering、GC、module initialization、WebAssembly/native addon 调用和 async I/O 必须与 codec scope 分离并记录。

---

## 6.8 Kotlin 与其他 JVM 语言

### KOTLIN-001：backend 必须锁定，不能一概按 Java 处理

必须记录 Kotlin compiler 和 JVM/Native/JS/Wasm backend。Kotlin/JVM 的许多整数行为与 Java 接近，但 Kotlin/Native 或 Kotlin/JS 可能具有不同表示、运行时与互操作边界；同一源码跨 backend 的结果不得未经验证共用 oracle。

### KOTLIN-002：signed/unsigned、除法和 shift 必须审核

必须区分 `Byte`/`UByte`、`Int`/`UInt`、`Long`/`ULong`、普通 `/`/`rem`、`floorDiv`/`mod` 以及 `shl`/`shr`/`ushr`。unsigned 类型、inline/value class 和转换函数不得机械映射为同宽 signed C++ 类型。

### KOTLIN-003：数组、集合与 wrapper 边界必须审核

`ByteArray`/`IntArray` 与 boxed `Array<T>`、List/Sequence、ByteBuffer 和 native interop 的布局、装箱、lazy evaluation 与复制成本不同。若 Kotlin 只包装 Java/C/C++ core，应保留 native core 并将 Kotlin 层标为 binding，而不是创建新的算法重写任务。

Scala、Clojure 等 JVM 语言除遵守 Java/JVM 规则外，还必须审计 `BigInt`/boxed numeric、lazy collection、parallel collection、exception 和 collection iteration/tie-breaking。

---

## 6.9 Zig

### ZIG-001：Zig 版本和 optimization mode 必须锁定

Zig 在 1.0 前语言与标准库变化较快，必须记录精确 compiler commit/version、target 和 Debug/ReleaseSafe/ReleaseFast/ReleaseSmall mode。普通整数 overflow 在安全模式可触发 safety check，在不安全优化模式不能当作可移植 wrap；需要 wrap 时必须识别 `+%`、`-%`、`*%` 等显式操作。

### ZIG-002：整数类型、shift 和 cast builtins 必须审核

Zig 支持任意位宽整数、comptime integer 和依赖目标的 `usize/isize`。必须逐处审计 `@intCast`、`@truncate`、`@bitCast`、`@as`、shift RHS 类型、精确/截断转换和 comptime folding，不得用 C-style cast 概括。

### ZIG-003：slice、sentinel、packed struct 和错误语义必须审核

必须记录 slice 长度、sentinel、bounds/safety check、optional/error union、defer/errdefer 和 allocator ownership。`packed struct`、`extern struct`、普通 struct、bit offset 与 endian 的布局合同不同，禁止把内存布局直接当作 wire format，除非逐字段验证。

### ZIG-004：现有 C API 必须用于 G0 判定或 Oracle

若 Zig 实现已经导出稳定 C API，G0 必须先判断该对象是否应从重写名单移出并标记为 `DIRECT_INTEGRATION_CANDIDATE`。本标准不实施该接入。若经书面决策仍需 C/C++ 重写，Zig scalar/original 实现及其 C API 必须保留为 differential oracle。

---

## 6.10 Fortran

### FORTRAN-001：kind、隐式类型和整数 overflow 必须审核

不得假设 `INTEGER`/`REAL` 默认 kind 等于 C 的 `int`/`double`。必须记录 compiler、standard、kind 参数、`ISO_C_BINDING` 映射、implicit typing 状态和相关 flags。Fortran 普通 signed integer overflow 没有可移植 wrap 保证，必须从算法合同而非偶然编译器结果确定语义。

### FORTRAN-002：数组布局、下标和临时副本必须审核

Fortran 通常为 column-major、默认 1-based 且支持自定义 lower bound。array section、noncontiguous actual argument、assumed-shape/assumed-size 和 expression temporary 可能产生隐式复制；必须计入 E2E 时间和 peak memory。

### FORTRAN-003：alias、传参与数值求值必须审核

必须记录 `INTENT`、pass-by-reference、COMMON/module/global state、EQUIVALENCE/TRANSFER、DO loop 边界和 alias 前提。浮点表达式重排、contract、IEEE rounding/exception mode 及 `-ffast-math` 类 flags 必须与 canonical policy 对齐。

### FORTRAN-004：unformatted I/O 不是可移植 bitstream

sequential unformatted record marker、compiler-specific padding、native endian 和 derived-type storage 不得直接作为跨平台格式。必须用显式字段宽度和 endian 重建 wire contract。

---

## 6.11 Julia

### JULIA-001：word-size integer、overflow 和除法族必须审核

`Int`/`UInt` 随 target word size 变化，固定格式应使用 `Int32/UInt32/Int64/UInt64`。普通机器整数 arithmetic 可 wrap，`Base.Checked` 提供 checked 运算；`div`、`fld`、`cld`、`rem` 和 `mod` 的舍入/符号规则不同，必须逐处映射。

### JULIA-002：数组、view、broadcast 和 promotion 必须审核

Julia 数组通常 column-major、1-based；slice 可能复制，`view`/`@views` 共享存储。broadcast fusion、multiple dispatch、type promotion、reinterpret 和 strided array 可能改变中间精度、调用路径与分配，必须记录实际 method specialization。

### JULIA-003：舍入、FMA 和 fast-math 必须锁定

必须记录 `round` 的 `RoundingMode`、`muladd`/`fma`、`@fastmath`、BLAS/FFT library 和线程数。量化边界必须以冻结的 Julia version、Project/Manifest 和 target 生成 golden vectors。

### JULIA-004：JIT、GC 与 native wrapper 必须分离

首次编译、method specialization、GC 和 package precompilation 不得静默混入 CORE 时间。若 `.jl` 文件只是 C/Zig library binding，应锁定 native library artifact/hash，并按 binding 处理。

---

## 6.12 R

### RLANG-001：numeric/integer/NA 语义必须审核

R 的 `numeric` 通常为 binary64，`integer` 通常为 32-bit，并存在 `NA_integer_` 等缺失值语义；整数 overflow 常产生 `NA` 和 warning，而不是 C++ wrap。必须区分 `NA`、`NaN`、Inf、logical 和 raw，并定义缺失值是否进入 validity bitmap。

### RLANG-002：向量化、recycling 与数组布局必须审核

R 通常使用 1-based、column-major 数组；vector recycling、`%/%`、`%%`、广播式向量化和 attribute/class dispatch 可能隐藏算法行为。copy-on-modify、ALTREP、slice/drop 和 package-specific object 必须审计实际复制与 materialization。

### RLANG-003：脚本与 native package 必须先分类

绘图、统计汇总和 benchmark 可视化脚本不属于 codec source closure。R package 若通过 `.Call`/`.C`/Rcpp 调用 C/C++/Fortran core，应优先定位并复用 native core；只有 R 本身实现了算法语义时才进入重写。

---

## 6.13 其他语言与执行环境

### LANG-001：未列语言必须完成通用语义审计

遇到 Swift、Dart、Lua、Objective-C、Scala、Clojure、Ruby、Haskell、Erlang/Elixir、WebAssembly text/binary 或 DSL 时，不得以“与某语言相似”为由跳过审计。必须按本章开头的通用清单建立 language/backend/version-specific contract，并至少覆盖整数、浮点、layout/alias、错误、确定性、序列化和运行时成本。

### LANG-002：脚本、binding、生成代码和算法核心必须分开

Shell、PowerShell、SQL、Make/CMake、notebook、代码生成器、CLI、测试、文档和可视化默认不是算法核心。Objective-C/Swift/Kotlin/Python/R 等 wrapper 若调用已有 C/C++/Rust/Zig/native library，必须先评估直接复用 native core。只有实际承载算法语义且位于 source closure 的文件才进入 C/C++ 重写。

### LANG-003：GPU/加速语言不得仅按扩展名判为非 C/C++

CUDA C/C++、HIP、SYCL、OpenCL C 和 HLS C/C++ 属于异构执行模型或 C/C++ 方言，应单独记录 host/device 边界、address space、work-group/warp、atomic、barrier、device floating-point 和 kernel launch/transfer 成本。它们不因 `.cu`、`.cl` 或工具链不同而自动成为“非 C/C++ 重写任务”。

---

# 7. C/C++ 语言基线

推荐 canonical 实现使用：

```text
C11/C17
或
C++17/C++20
```

项目必须固定：

```text
compiler family
compiler version
language standard
standard library
platform ABI
```

建议主要核心类型来自：

```cpp
#include <cstdint>
#include <cstddef>
#include <limits>
```

---

# 8. 整数规则

## INT-001：serialized integer 必须有明确宽度

必须使用：

```cpp
std::uint8_t
std::uint16_t
std::uint32_t
std::uint64_t

std::int8_t
std::int16_t
std::int32_t
std::int64_t
```

禁止在文件格式中使用未固定宽度的：

```cpp
int
long
short
```

---

## INT-002：长度和容器大小优先使用 `size_t`

但不得混淆：

```text
size_t
serialized uint64
algorithmic uint32
```

它们是三种不同概念。

---

## INT-003：禁止依赖 signed overflow

以下写法必须审核：

```cpp
a + b
a - b
a * b
-a
```

特别是：

```cpp
INT_MIN - 1
-INT_MIN
```

---

## INT-004：模 2^N 算术必须显式使用 unsigned

如果算法定义：

\[
x \leftarrow x \pmod{2^{32}}
\]

必须使用：

```cpp
std::uint32_t
```

而不是：

```cpp
std::int32_t
```

的 overflow。

---

## INT-005：所有 size arithmetic 必须做 overflow check

例如：

```cpp
size_t total = n * channels * sizeof(double);
```

必须检查：

```text
n * channels
channels * sizeof(T)
offset + length
header + payload
```

推荐 helper：

```cpp
bool checked_add_size(size_t a, size_t b, size_t* out);
bool checked_mul_size(size_t a, size_t b, size_t* out);
```

---

## INT-006：conversion 必须审核

高风险转换：

```cpp
uint64_t -> uint32_t
size_t   -> int
double   -> int32_t
int64_t  -> int32_t
signed   -> unsigned
```

必须确认：

```text
range
rounding
overflow
negative input
```

---

# 9. Shift / Bit Operation 规则

## BIT-001：shift count 必须满足位宽范围

禁止：

```cpp
x << 32  // 对 32 位值
x << 64  // 对 64 位值
```

所有动态 shift：

```cpp
x << n
```

必须保证：

```text
0 <= n < bit_width
```

---

## BIT-002：对 signed negative value 的位运算必须谨慎

需要逻辑右移时：

```cpp
static_cast<uint32_t>(x) >> n
```

不要依赖 signed right shift 的平台/语言语义差异。

---

## BIT-003：bit mask 必须用正确宽度常量

推荐：

```cpp
UINT32_C(1)
UINT64_C(1)
```

例如：

```cpp
UINT64_C(1) << bit
```

而不是：

```cpp
1 << bit
```

---

# 10. Endianness

## END-001：bitstream 禁止使用 host-native endian

禁止：

```cpp
fwrite(&value, sizeof(value), 1, file);
```

作为协议序列化方式。

必须明确：

```text
Little Endian
或
Big Endian
```

---

## END-002：提供统一 serialization helper

例如：

```cpp
uint16_t load16_le(const std::byte* p);
uint32_t load32_le(const std::byte* p);
uint64_t load64_le(const std::byte* p);

void store16_le(std::byte* p, uint16_t v);
void store32_le(std::byte* p, uint32_t v);
void store64_le(std::byte* p, uint64_t v);
```

算法代码不应自行重复 endian conversion。

---

## END-003：跨平台 CI 必须至少验证两种架构

理想：

```text
x86_64
AArch64
```

如有 big-endian 环境可进一步加入。

---

# 11. Bitstream 统一规则

建议公共模块：

```text
core/bitstream/
    bit_reader.hpp
    bit_writer.hpp
    endian.hpp
    varint.hpp
    zigzag.hpp
```

---

## BITSTREAM-001：每个格式必须声明

```text
byte_order
bit_order
field_width
padding
alignment
flush rule
frame termination
```

---

## BITSTREAM-002：bit order 和 byte order 必须分开

例如必须明确：

```text
byte order: little endian
bit packing: LSB first
Huffman code traversal: MSB first
```

不能只写：

```text
little endian
```

---

## BITSTREAM-003：跨 64-bit word 写入必须有专门测试

测试：

```text
bitpos = 0
1
7
8
31
32
63
```

并测试：

```text
nbits = 0
1
7
8
31
32
63
64
```

特别是：

```text
bitpos + nbits > 64
```

---

## BITSTREAM-004：flush 必须定义

必须说明：

```text
最后一个 byte 未填满怎么办？
padding bit = 0 还是 unspecified？
是否必须 byte align？
EOF 如何判断？
```

---

# 12. Frame / Header / Metadata

每个自定义格式 SHOULD 使用：

```text
Magic
Version
Flags
Original Size
Algorithm Metadata
Payload Size
Payload
Checksum
```

---

## FRAME-001：格式必须 versioned

禁止发布：

```text
header
payload
```

却没有格式版本。

---

## FRAME-002：reserved bits 必须定义

编码器：

```text
reserved bits = 0
```

解码器：

```text
遇到未知 required feature 必须报错
```

---

## FRAME-003：所有解码必需信息必须进入 FinalBits

统一计费定义为：

\[
FinalBits = SerializedBits + ExternalSideInformationBits
\]

`SerializedBits` 必须按实际物理流分解并核对：timestamp、value、shared、metadata/header、validity/null、dictionary、model、index、checkpoint、checksum、padding、container 和 payload。未嵌入流但解码所必需的模型、字典、参数或索引必须计入 `ExternalSideInformationBits`。

只在最终物理流上执行一次 byte rounding：

\[
FinalPhysicalBytes=\lceil SerializedBits/8\rceil
\]

禁止只统计 entropy payload，禁止把 output capacity、bound、估算位数、workspace 或内存对象大小当作 `FinalBits`。

---

# 13. Varint / ZigZag

## VARINT-001：必须限制最大长度

decoder 不能无限读取 varint。

例如 uint64：

```text
最多 10 bytes
```

超过必须返回 malformed stream。

---

## VARINT-002：ZigZag 必须避免 signed overflow

必须从位级定义实现和测试：

```text
0
-1
1
INT32_MIN
INT32_MAX
INT64_MIN
INT64_MAX
```

---

# 14. Memory / Object Model

## MEM-001：禁止未验证的 pointer punning

高风险：

```cpp
uint32_t x = *reinterpret_cast<const uint32_t*>(p);
```

可能涉及：

```text
alignment
strict aliasing
object lifetime
```

优先：

```cpp
std::memcpy(&x, p, sizeof(x));
```

然后显式 endian conversion。

---

## MEM-002：alignment 必须声明

SIMD buffer 必须明确：

```text
required_alignment = 1/8/16/32/64
```

并区分：

```text
aligned load
unaligned load
```

---

## MEM-003：不得默认 allocator 成本为零

独立性能验证必须区分：

```text
setup allocation
workspace allocation
per-call allocation
kernel
```

---

## MEM-004：hot path SHOULD NOT 分配临时容器

不推荐：

```cpp
for (...) {
    std::vector<uint8_t> tmp(size);
    ...
}
```

优先：

```text
create
prepare
allocate workspace
repeat encode/decode
destroy
```

---

## MEM-005：workspace 必须可观测

API 建议暴露：

```cpp
size_t workspace_bytes(const Config&, const InputDesc&);
```

并在独立性能验证结果中记录。

---

# 15. Output Capacity

## BUF-001：所有 encoder 必须定义最坏输出容量

不得：

```cpp
compressed.resize(input_size);
```

必须提供：

```cpp
size_t max_compressed_size(
    const InputDesc& input,
    const CodecConfig& cfg);
```

---

## BUF-002：容量计算本身必须 overflow-safe

例如：

```text
header + n + n/255 + ...
```

也需要 checked arithmetic。

---

## BUF-003：encoder 写入前必须验证 output capacity

API 返回：

```text
OK
OUTPUT_TOO_SMALL
INVALID_CONFIG
UNSUPPORTED
INTERNAL_ERROR
```

禁止缓冲区越界后再报错。

---

# 16. Decoder 安全规则

**所有 compressed input 必须视为不可信数据。**

## DEC-001：所有长度字段都必须验证

包括：

```text
frame_size
block_size
literal_length
match_length
dictionary_size
symbol_count
tree_size
offset
```

---

## DEC-002：所有 offset 必须验证

LZ 类算法：

```text
offset > 0
offset <= bytes_already_decoded
```

---

## DEC-003：任何写操作前检查

```text
out_pos + write_len <= output_capacity
```

必须采用 overflow-safe check：

```cpp
if (write_len > output_capacity - out_pos) ...
```

优于：

```cpp
if (out_pos + write_len > output_capacity)
```

因为后者本身可能 overflow。

---

## DEC-004：递归树解析必须限制深度

Huffman/grammar/tree decoder 必须限制：

```text
node count
depth
symbol count
```

防止畸形输入造成：

```text
stack overflow
CPU DoS
memory DoS
```

---

## DEC-005：错误输入必须 deterministic fail

禁止：

```text
crash
UB
hang
infinite loop
silent corruption
```

---

# 17. 无损压缩专项

无损的基本正确性要求：

\[
D(C(x)) = x
\]

但仅做 round-trip 不够。

---

## LOSSLESS-001：必须做 bit-exact reconstruction

对于整数和原始 byte 数据：

```text
memcmp(original, decoded) == 0
```

---

## LOSSLESS-002：浮点无损必须比较 bit pattern

不能只做：

```cpp
a == b
```

因为需要判断：

```text
-0
NaN payload
NaN sign
```

如算法承诺 bitwise lossless，应比较原始 bit pattern。

---

## LOSSLESS-003：Delta 类算法必须定义第一个值

例如：

```text
delta[0] = x[0]
```

还是：

```text
base = x[0]
delta 从 x[1] 开始
```

必须进入格式定义。

---

## LOSSLESS-004：预测 residual 的位宽必须审核

例如：

```cpp
int32_t residual = current - predicted;
```

若两者都是 int32，数学差值可能需要 33 bit。

必须决定：

```text
wrap
widen to int64
zigzag
saturate
error
```

---

## LOSSLESS-005：Dictionary 生命周期必须明确

必须定义：

```text
dictionary source
dictionary ID
dictionary lifetime
per-stream / per-block
embedded / external
reset
```

---

## LOSSLESS-006：Entropy coder 必须定义 tie-breaking

如果相同 frequency 下 Huffman tree 有多个合法结果，必须确认：

- 是否要求 deterministic tree；
- 是否有 canonical Huffman；
- symbol 排序规则；
- frequency tie-breaking；
- code-length ordering。

---

# 18. 有损压缩专项

有损算法的核心不是“能解码”，而是：

\[
\hat{x}=D(C(x))
\]

满足正式 quality/error contract。

---

# 19. Error Bound 语义

## LOSSY-001：禁止只有一个模糊的 `error_bound`

必须使用结构化配置：

```cpp
enum class ErrorMode {
    None,
    Absolute,
    RelativeRange,
    RelativePointwise,
    PSNR,
    L2Norm,
    FixedRate,
    FixedPrecision
};

struct ErrorSpec {
    ErrorMode mode;
    double value;
};
```

---

## LOSSY-002：Relative 必须说明 denominator

可能是：

```text
global max-min
global max(abs(x))
pointwise abs(x_i)
RMS
other scale
```

必须明确公式。

---

## LOSSY-003：ABS 必须明确严格/近似保证

例如：

\[
|x_i-\hat{x_i}| \le \epsilon
\]

如果算法只能“统计上通常满足”，不能标为 strict absolute-bound codec。

---

## LOSSY-004：PSNR 必须明确 peak definition

\[
PSNR = 20\log_{10}\frac{MAX}{RMSE}
\]

其中 `MAX` 到底是：

```text
dtype maximum
data max
range
application fixed peak
```

必须写清楚。

---

# 20. Floating-Point 精度

## FP-001：canonical implementation 必须固定 float/double

不得因为“double 更精确”擅自把原来的：

```text
float32 predictor
```

改为：

```text
double predictor
```

除非该行为作为新的实现 variant 被明确记录。

---

## FP-002：中间精度必须审核

特别关注：

```text
accumulator
mean
variance
regression coefficient
prediction
transform
quantization input
```

---

## FP-003：禁止 canonical build 默认 `-ffast-math`

理由：

fast-math 可能改变：

```text
NaN
Inf
signed zero
reassociation
reciprocal
rounding assumptions
FMA
```

建议：

```text
canonical correctness:
    -O2/-O3
    strict/precise FP

optimized:
    -O3

experimental-fast:
    -O3 -ffast-math
```

`experimental-fast` 必须独立标记，禁止与 canonical 混淆。

---

# 21. Rounding

## ROUND-001：每个 quantizer 必须声明 tie-breaking

可能值：

```text
toward zero
toward +inf
toward -inf
nearest-away-from-zero
nearest-even
custom
```

---

## ROUND-002：禁止直接将 Python `round` 翻成 `std::round`

Python built-in 默认 nearest-even。

C/C++ `std::round` halfway 默认 away-from-zero。

这可以直接改变 quantized code。

---

## ROUND-003：若使用当前 FP rounding mode，必须显式设置/验证

例如：

```cpp
fesetround(FE_TONEAREST);
```

并保证编译器选项允许程序依赖 rounding environment。

---

# 22. FMA / FP Contraction

## FMA-001：canonical validation 必须固定 FMA policy

例如：

```text
FMA_OFF
FMA_STANDARD
FMA_FAST
```

---

## FMA-002：quantization boundary 前的 FMA 特别敏感

```cpp
pred = a * x + b;
q = round((value - pred) / eb);
```

FMA 可能造成：

```text
几个 ULP 差异
↓
跨量化边界
↓
q 不同
↓
bitstream 完全不同
```

因此必须测试边界样本。

---

# 23. NaN / Inf / ±0 / Subnormal

每个浮点算法 capability 必须声明：

```text
supports_nan
supports_inf
preserve_nan
preserve_nan_payload
preserve_signed_zero
supports_subnormal
flush_subnormal
```

---

## SPECIAL-001：NaN policy 必须明确

例如：

```text
reject
pass-through side channel
preserve bit pattern
canonicalize
encode as special symbol
```

---

## SPECIAL-002：Inf policy 必须明确

不能让：

```text
max-min
```

在包含 Inf 时悄悄变成 Inf 并破坏 error bound。

---

## SPECIAL-003：±0 必须明确

如果算法承诺 bitwise lossless：

```text
+0 != -0
```

在 bit pattern 层面必须保留。

---

# 24. Predictor / Transform

## PRED-001：公式必须原样记录

例如：

```text
p_i = x_{i-1}
p_i = 2x_{i-1} - x_{i-2}
```

不能仅写“linear predictor”。

---

## PRED-002：必须定义前 K 个样本

对于 order-K predictor：

```text
x[0:K]
```

怎么编码必须明确。

---

## PRED-003：block boundary 必须定义

例如：

```text
每 block 重置 predictor
```

或：

```text
继承上一 block state
```

二者会直接影响 CR 与 random access。

---

# 25. Block / Chunk / Stream

## STATE-001：必须区分

```text
independent block
dependent block
continuous stream
```

---

## STATE-002：重写实现不得擅自改变 reset frequency

例如算法原生 1 MB continuous stream，重写 API 不得为了简化调用而：

```text
每 64 KB reset
```

除非 Algorithm Contract 明确把它定义为独立 variant，且与原模式分别验证。

---

## STATE-003：chunk size 必须作为实验参数记录

至少记录：

```text
input size
block size
chunk size
number of blocks
state reset interval
```

---

## STATE-004：random access 能力必须真实

只有满足：

```text
独立定位
+
不解码之前所有数据
```

才可以声明 random access。

## STATE-005：上游正式 streaming/stateful 能力必须等价保留

若上游公开 API、文档、CI 或正式测试支持 streaming/stateful 模式，该能力默认为 `REQUIRED_PARITY`。C/C++ 重写不得只提供 one-shot 并在内部缓存全部输入来冒充 incremental streaming，除非上游本身就是该语义。

必须分别审计并按上游能力实现：

```text
incremental encode
incremental decode
partial input consumption
partial output / backpressure
flush without finalize
finalize and footer emission
reset and object reuse
cross-chunk history
dictionary/model lifetime
seek / random access
bounded streaming memory
```

专项测试至少包含：

```text
one-shot baseline
1-element or 1-byte fragments
irregular fragment schedule
B-1 / B / B+1 splits
empty update
multiple flush calls
finalize and repeated finalize
reset then reuse
two independent interleaved handles
truncated final chunk
small output buffer / resume（若上游支持）
```

只有当上游规定 streaming 与 one-shot 应产生同一 bitstream 时才要求字节一致；否则必须比较解码结果、状态转移、边界、FinalBits 和 cross-decode 合同。调用粒度导致的合法格式差异必须写入 capability matrix。

---

# 26. Multivariate / ND 数据布局

必须明确：

```text
N = timestamps
D = channels
```

以及：

```text
row-major:
values[t * D + d]

column-major:
values[d * N + t]
```

---

## LAYOUT-001：不得用 flatten 冒充 multivariate compression

必须区分：

```text
COLUMN_INDEPENDENT
GROUPED_CHANNELS
FULL_MATRIX
NATIVE_ND_ARRAY
```

---

## LAYOUT-002：layout conversion 成本必须计量

如果一个算法必须：

```text
row-major → column-major
```

必须明确：

- conversion 是否算入 encode latency；
- 临时内存是否算入 peak memory。

---

# 27. 独立重写 API 与接入隔离

重写包必须提供不依赖 TSDataCompressBenchMark 的本地 public API。实现语言可以是 C 或 C++；API 可以采用 C 函数、C++ class 或二者组合，但必须能够由本目录内的测试和 CLI 独立调用。

最低接口能力包括：

```text
create/init
reset（有状态对象）
compress_bound 或等价的容量查询
compress
finalize（流式对象）
decompress
destroy/RAII cleanup
error detail
accounting/query（算法具有 side information 时）
```

独立 API 合同包括：

- 输入 dtype、rank、shape、stride、alignment 和 ownership 与真实内存一致；
- 容量、已用字节和 shape 使用固定、足够宽且经过检查的整数类型；
- `bytes_written` 表示本次调用的真实有效字节，不得用 capacity 或 bound 代替；
- 输入 buffer 默认只读，算法确需 in-place 时必须在 contract 中明确；
- `finalize` 的尾部、footer、checksum 和剩余 bit 必须产生真实输出并进入 FinalBits；
- C++ exception 不得逃逸到 C API；错误对象、消息所有权和生命周期必须明确；
- public header、namespace/symbol、allocator ownership 和 ABI 假设必须记录。

**禁止**在本目录实现、复制或包装 `tscb_adapter_v1`。未来接入层只能依赖此处冻结的 public API，且必须存放在 TSDataCompressBenchMark 的独立接入目录和独立任务中。

---

# 28. API 设计约束

## API-001：禁止隐藏全局状态

不允许：

```cpp
static Dictionary dict;
static PredictorState state;
```

除非明确只读且 thread-safe。

---

## API-002：必须支持 reset

任何 streaming/stateful codec 都要提供：

```cpp
reset()
```

---

## API-003：必须返回实际 bytes_written

必须通过独立 API 的返回对象或 out parameter 返回实际长度。禁止由 caller 猜测压缩长度，也禁止以 `capacity_bytes`、`compress_bound` 或内存对象大小冒充实际输出。

---

## API-004：禁止异常和 status 混用无规范

项目必须统一：

```text
exception-based
或
status-code-based
```

若提供 C ABI，必须使用本重写包自有的版本化 status enum；C++ 异常不得越过 C ABI 边界。错误详情的访问方式、消息所有权和失效时机必须写入 public header。

---

## API-005：生命周期和重复调用语义必须定义

必须定义 create 失败、reset mode、空输入、分段 compress、重复 finalize、finalize 后继续 compress、decompress 后 reset、query 可用阶段和 destroy(NULL/invalid handle) 的行为。未定义行为不得由未来接入层补猜。

---

## API-006：manifest、config 与实现身份必须一致

manifest 必须准确公布 dtype、shape、streaming、loss mode、ObjectLevel、参数 schema、线程、ISA、query 和 accounting capability。实际执行路径与 manifest 不一致时，验证失败，不得声明 `REWRITE_DONE`。

---

# 29. Canonical 与 Optimized 实现分离

目录示例：

```text
kernel/
├── scalar/
│   └── codec_scalar.cpp
├── avx2/
├── avx512/
├── neon/
└── cuda/
```

规则：

```text
scalar = correctness oracle
optimized = 必须与 scalar 做 differential validation
```

禁止删除 scalar 版只留下最快版本。

---

# 30. SIMD 规则

## SIMD-001：不得改变算法语义

vectorization 后必须保持：

```text
symbol sequence
error bound
state
```

在规范允许范围内一致。

---

## SIMD-002：tail 必须专项测试

测试长度：

```text
0
1
vector_width - 1
vector_width
vector_width + 1
2*vector_width - 1
```

---

## SIMD-003：ISA fallback 必须记录

结果 metadata：

```text
isa_requested
isa_available
isa_used
fallback_path
```

---

## SIMD-004：禁止独立性能验证中静默 fallback

例如：

```text
要求 AVX512
实际跑 scalar
```

必须在结果中可见。

## SIMD-005：上游受支持 SIMD 路径必须复现并强制验路

上游 release build、公开 feature flag、CI 或正式测试覆盖的 SIMD ISA variant 默认是 `REQUIRED_PARITY`。不得因为 scalar 已正确而把已有 AVX2/AVX-512/NEON/SVE 等路径统一标记为 `OPTIONAL_OPTIMIZATION`。

每个 required ISA variant 必须：

- 有独立 build target 或可验证的 runtime dispatch 分支；
- 提供 forced-path 测试，证明实际进入目标 kernel，而不是静默 fallback；
- 与 canonical scalar 执行 differential、dataset、tail、unaligned input、边界长度和 special-value 测试；
- 记录 ISA requirement、feature detection、dispatch policy、fallback 路径和实际 `isa_used`；
- 在不支持该 ISA 的机器上安全拒绝或 fallback，不得执行非法指令；
- 保持上游承诺的 bitstream、误差、state、reset/finalize 和线程语义。

只有上游不存在的新增 ISA、明确未发布的实验 kernel，或经证据确认不属于锁定 source closure 的路径，才可归入 `OPTIONAL_OPTIMIZATION`。缺少对应硬件时应优先使用 CI runner、模拟/交叉环境或获得真实机器测试证据；确实无法验证时必须使用 `UNAVAILABLE_WITH_WAIVER`，不得标记 PASS。

---

# 31. 并行化

## THREAD-001：线程数必须固定和记录

```text
threads_requested
threads_used
```

---

## THREAD-002：不得把单线程算法与多线程算法直接比较而不标注

至少分：

```text
single-thread standalone measurement
multi-thread standalone measurement
```

---

## THREAD-003：并行版必须通过 TSan 或等效 data-race 检测

特别关注：

```text
shared dictionary
shared histogram
global scratch
static buffer
lazy initialization
```

---

## THREAD-004：determinism 必须定义

多线程压缩可能因为：

```text
parallel reduction order
hash table insertion order
task scheduling
```

导致输出不同。

必须说明：

```text
bitstream deterministic?
semantic deterministic?
quality deterministic?
```

## THREAD-005：上游受支持并行能力和线程安全必须等价保留

必须区分以下不同 capability，不得用一个 `multithread=true` 合并：

```text
internal parallel encode
internal parallel decode
caller-controlled thread count
concurrent independent handles
shared read-only dictionary/model
shared mutable service/context
async/task execution
```

上游公开、可构建且受测试的并行路径默认是 `REQUIRED_PARITY`。重写必须保留其适用方向、线程控制范围、状态隔离、错误传播、取消/终止语义和资源上限；不得用“调用方可以同时启动多个单线程实例”冒充上游的 internal parallel encode/decode。

required 多线程能力至少测试：

- `threads=1/2/3`、最大受支持线程数及大于工作单元数的情况；
- 同一输入和配置下与 scalar 的 differential/error-contract 结果；
- 上游承诺确定性时的重复 bitstream 或语义确定性；
- 多 handle 并发、reset/finalize 交错、异常/失败路径和资源回收；
- TSan 或等效 data-race 工具；
- 实际 `threads_requested`、`threads_used`、任务划分和 fallback 的可观测证据；
- 避免 oversubscription、全局 mutable singleton 和线程数为 0/非法值的确定行为。

若上游只保证 thread-safe handles 而不提供内部并行，只需保留该并发安全能力，不得虚构 internal multithreading。反之，上游有内部并行时也不能只验证 handle 并发。

---

# 32. 编译配置

建议至少四类 build。

## 32.1 Debug

```text
-O0/-Og
-g
warnings high
assertions
```

## 32.2 Sanitizer

```text
-O1/-O2
-g
ASan
UBSan
```

多线程另建：

```text
TSan
```

ASan 和 TSan 通常不要放同一 binary。

## 32.3 Canonical Release

```text
-O3
no fast-math
fixed language standard
fixed ISA baseline
```

## 32.4 Optimized Release / Standalone Performance

```text
-O3
target ISA
LTO policy fixed
vectorization policy fixed
```

---

# 33. Compiler Flag 记录

独立性能验证输出必须保存：

```text
compiler_name
compiler_version
language_standard
optimization_level
march
mtune
mavx/mavx2/mavx512...
mfpu / neon
ffast-math
ffp-contract
lto
openmp
debug_symbols
```

---

# 34. `-march=native` 的约束

`-march=native` MAY 用于：

```text
单设备峰值实验
```

但跨设备验证不应将它作为唯一 build。

推荐：

```text
portable baseline
+
native optimized
```

分别报告。

---

# 35. Warning Policy

建议 CI：

```text
-Wall
-Wextra
-Wpedantic
-Wconversion
-Wsign-conversion
-Wshadow
-Wformat=2
```

可按实际编译器调整。

项目应逐步实现：

```text
warnings-as-errors
```

但第三方代码可独立处理。

---

# 36. Sanitizer

## SAN-001：ASan

用于发现：

```text
heap OOB
stack OOB
global OOB
use-after-free
double-free
invalid free
```

## SAN-002：UBSan

用于发现：

```text
signed overflow
invalid shift
misalignment
null dereference
array OOB
invalid cast/conversion
```

## SAN-003：TSan

用于并行实现的数据竞争检测。

## SAN-004：Sanitizer build 禁止用于性能结论

---

# 37. Static Analysis

SHOULD 使用至少一种：

```text
clang-tidy
Clang Static Analyzer
GCC analyzer
Coverity
CodeQL
cppcheck
```

重点规则：

```text
integer overflow
lifetime
null pointer
bounds
uninitialized read
use-after-move
ownership
```

---

# 38. Correctness Testing 总体分层

必须至少分：

```text
L0 Unit
L1 Golden
L2 Roundtrip
L3 Differential
L4 Dataset Source-vs-Rewrite
L5 Native Capability Parity
L6 Cross Decode
L7 Malformed Input
L8 Sanitizer
L9 Fuzz
L10 Cross Platform
L11 Performance Regression
```

## 38.1 Qualification Preflight

进入 G6 发布前必须按 manifest capability 对独立重写 API 执行资格测试。至少包括：

```text
source/build/license/implementation identity
native capability matrix hash and classification closure
input buffer byte-for-byte unchanged
input/output guard canary
declared safe-overread contract
compress_bound capacity success
compress_bound - 1 deterministic failure
empty input and N = 1/2
block boundary B-1/B/B+1
reset and independent-object isolation
finalize output and repeated-finalize behavior
truncated/corrupt/oversized input
dtype/shape/stride/alignment mismatch
timestamp/value pairing and joint-codeword integrity
accounting component sum and physical-length closure
actual execution path, ISA and thread count
required streaming fragmentation/reset/finalize cases
required SIMD forced-path and no-silent-fallback evidence
required threading counts/concurrency/TSan evidence
waiver identity, approval and expiration
```

preflight 失败的任务只能产生资格诊断，不得声明 `REWRITE_DONE`。任何声明的 safe overread 必须有固定上限、可访问 padding 和 canary/guard-page 证据；不得把越界读取包装成“优化需要”。

## 38.2 基于 `datasets/` 的原实现与重写实现对照验证

真实数据集验证是判断重写是否完善的强制证据之一，其目的首先是发现 toy vector 难以覆盖的分布、状态、边界、异常值和长序列问题，不是进行 TSDataCompressBenchMark 接入或正式排名。

### 数据集兼容性要求（TEST-008）

只要项目 `datasets/` 中存在符合算法输入 dtype、维度、取值域、缺失值政策和 timestamp/value 关系的数据，每个重写任务必须选择适合的数据集，同时运行：

```text
冻结的原始实现 / reference oracle
同一算法的 canonical C/C++ 重写实现
适用时的 optimized C/C++ 实现
```

当前候选数据池包括但不限于：

| 数据类型/形态 | 可选文件示例 | 典型用途 |
|---|---|---|
| 浮点单变量或可选列时序 CSV | `ETTh1.csv`、`ETTh2.csv`、`ETTm1.csv`、`ETTm2.csv`、`exchange_rate.csv`、`weather.csv` | 浮点 value codec、timestamp/value pipeline、有损误差验证 |
| 大规模多变量 CSV | `electricity.csv`、`traffic.csv`、`national_illness.csv` | multivariate、长序列、block/state、dictionary/model codec |
| 多变量交通 NPZ | `PEMS03.npz`、`PEMS04.npz`、`PEMS07.npz`、`pems08.npz` | ND layout、shape/stride、跨通道和批处理路径 |
| 整数 Sprintz NPZ | `sprintz_u8_uts.npz`、`sprintz_i16_mts.npz` | `uint8` 单变量和 `int16` 多变量整数 codec |
| UCR 2018 单变量分类时序 | `UCRArchive_2018/<Dataset>/<Dataset>_TRAIN.tsv`、`*_TEST.tsv` | 大量不同长度和分布的独立浮点序列、逐序列 reset/finalize、长短 block 覆盖 |

文件名只是当前快照示例。实际执行必须重新发现 `datasets/` 内容并按 hash 锁定，不得依赖文件名推断 dtype、shape 或语义。

### 38.2.1 UCRArchive 2018 专项规则

`datasets/UCRArchive_2018` 是由多个单变量时序分类子数据集构成的集合，不是单条连续时序。每个子数据集通常包含 `<Dataset>_TRAIN.tsv`、`<Dataset>_TEST.tsv` 和 `README.md`；TSV 每行的第 1 列是分类标签，后续列才是一个独立时序样本的有序值。

使用 UCR 数据验证压缩算法时必须遵守：

- 默认压缩范围是每行第 2 列至行尾；第 1 列分类标签不得作为 value 序列的一部分；
- 标签仅用于 case provenance 或分层选样，默认不计入算法输入和 `FinalBits`；若算法合同确实压缩标签/metadata，必须作为独立字段、独立组件和独立测试对象声明；
- 分类准确率不是压缩重写正确性的替代指标；有损算法可以附加报告下游分类影响，但仍必须逐样本满足正式 error contract；
- 每行默认是一个独立编码对象，必须在行边界 reset/finalize；禁止无说明地把多行拼成一个 continuous stream，导致跨样本 predictor/dictionary 状态泄漏；
- 若显式测试 concatenated-stream variant，必须记录行顺序、每行长度、framing、reset interval，并将恢复行边界所需的 side information 计入 `FinalBits`；
- `TRAIN` 和 `TEST` 是不同 partition，不得直接拼接后冒充自然连续时序。非 learned codec 可分别把二者作为 correctness cases；learned/model codec 只能按 Algorithm Contract 使用 TRAIN 进行训练/拟合，并优先以 TEST 进行最终完善性验证；
- 不得使用 TEST 数据选择模型、字典、阈值、block size 或优化参数；任何 online adaptation 都必须在每个 case 的生命周期和计费中明确；
- UCR TSV 通常没有显式 timestamp。除非子数据集文档提供时间轴，否则只能测试 value codec 或使用明确声明的 synthetic/index timestamp；禁止把分类标签或行号伪装成真实 timestamp；
- 文本数值解析的目标 dtype、decimal parser、NaN/Inf、缺失值和 signed-zero policy 必须锁定。为减少 loader 差异，浮点 reference input SHOULD 先解析为 canonical `float64` bit pattern，再按算法合同执行显式转换；
- 每个 `README.md` 中的 series length、missing-value 声明和来源说明必须纳入数据审计；实际 TSV shape/hash 仍需独立验证，不能只信 README；
- `Missing_value_and_variable_length_datasets_adjusted/` 下的数据必须视为独立 dataset variant。不得与顶层同名子数据集混用或宣称字节等价；必须记录完整相对路径、调整版本、缺失值政策和文件 hash；
- `dataset_id` SHOULD 使用 `ucr2018:<relative-subdataset>:TRAIN|TEST`，每行 case 再附加稳定的 zero-based row index；
- 使用 UCR 作为验证套件时，若不运行全部兼容子数据集，必须给出确定性的 allow-list/selection rule。对通用浮点 value codec，SHOULD 至少选择 3 个具有不同序列长度、动态范围或缺失值特征的子数据集，禁止只挑选最容易通过的样本。

UCR case 的 `DATASET_TEST_PLAN.yaml` 至少补充：

```yaml
dataset_id: ucr2018:ECG5000:TEST
relative_path: UCRArchive_2018/ECG5000/ECG5000_TEST.tsv
partition: TEST
case_unit: ROW_AS_INDEPENDENT_SERIES
label_column: 0
label_policy: EXCLUDE_FROM_CODEC_INPUT
value_columns: "1:"
row_selection:
row_boundary_policy: RESET_AND_FINALIZE
target_dtype: float64
missing_value_policy:
source_file_sha256:
canonical_case_hashes: []
```

### 38.2.2 数据选择规则

- 至少选择 1 个兼容真实数据集；存在多个明显不同分布或 shape 时 SHOULD 选择不少于 3 个；
- 数据集必须覆盖算法声明的主要输入模式，例如单变量/多变量、整数/浮点、timestamp/value pairing、短块/长块；
- 不得为了“让测试通过”而把不兼容数据任意 cast、截断、排序、去 NaN 或归一化；必要转换必须属于公开、可复现的测试输入合同；
- 真实数据不能替代 N=0/1/2、B-1/B/B+1、极值、NaN/Inf、重复值和 malformed stream 等合成边界测试；两类测试都必须保留；
- P0 primitive 必须在其合法输入域测试；若它只能在完整 pipeline 中产生合法输入，应从 reference pipeline 捕获该阶段数据并记录 provenance；
- learned/model codec 必须严格分离训练、验证和测试区间；用于正确性判定的数据不得泄漏到训练、字典构建或调参阶段，除非 Algorithm Contract 明确允许 online adaptation。

### 38.2.3 相同输入与预处理证明

原始实现和 C/C++ 重写实现必须接收语义相同且可证明一致的输入。每个 case 至少记录：

```text
dataset_id and relative path
source file SHA-256
selected columns/channels and timestamp source
row/sample range and order
original dtype/shape/layout
target dtype/shape/layout
missing/NaN/Inf policy
normalization/cast/window/chunk/block rules
canonical input byte serialization and SHA-256
algorithm config and config SHA-256
random seed/model/dictionary/checkpoint SHA-256
reference and rewrite command lines
```

推荐先生成一份只读的 canonical input artifact，再由两个实现读取。若两个语言运行时必须使用不同 loader，loader 输出必须逐字节比较或按 dtype/shape/bit pattern 证明一致。数据准备脚本只能位于重写包的 `tests/datasets/` 或 `tools/`，不得通过 TSDataCompressBenchMark adapter 间接调用。

### 38.2.4 必须执行的对照路径

对每个选定 case，至少执行：

1. `source_decode(source_encode(x))`；
2. `rewrite_decode(rewrite_encode(x))`；
3. source 与 rewrite 的阶段性 differential trace/checksum；
4. `CROSS_DECODE`/`BYTE_IDENTICAL` 目标下的 `source_decode(rewrite_encode(x))`；
5. `CROSS_DECODE`/`BYTE_IDENTICAL` 目标下的 `rewrite_decode(source_encode(x))`；
6. optimized variant 与 canonical variant 的 differential validation。

当 source API 不能暴露某条路径时，必须在报告中说明限制、替代 oracle 和剩余风险，不能静默标记通过。

### 38.2.5 完善性通过条件

全部选定 case 必须同时满足：

- 原始实现和重写实现均处理了相同样本数、顺序、block/chunk 边界和 reset/finalize 周期；
- 无损算法的重建结果按声明 dtype 做 bit-exact 比较；浮点无损必须比较 bit pattern；
- 有损算法的每个样本和整体指标均满足正式 error contract，不得只比较平均误差；
- `SEMANTIC` 目标的中间状态、重建语义和边界行为在允许差异内；允许 bitstream 不同，但差异必须可解释；
- `CROSS_DECODE` 必须双向成功，`BYTE_IDENTICAL` 必须比较完整物理输出字节；
- `FinalBits`、side information、model/dictionary/checkpoint 等组件分别闭合；除非目标要求，不以压缩大小相同作为等价条件；
- canonical 和 optimized 路径均无 crash、hang、越界、UB、未初始化读取或 sanitizer failure；
- 数据集暴露的首个 divergence 必须定位到具体 stage，并修复或形成批准的 WAIVER；
- `dataset_validation_report.md` 包含逐 case 的 PASS/FAIL、命令、hash、关键指标、首个差异和日志/产物路径。

只要一个必须 case 失败，任务状态就是 `VALIDATING` 或 `BLOCKED`，不得进入 `REWRITE_DONE`。只运行重写实现、不运行原始实现，或两个实现使用不同预处理结果，均不能证明重写完善。

---

# 39. Golden Vector

每种算法至少准备：

```text
input.bin
config.json
expected_metadata.json
expected_output.bin       # 若 bitstream identity 有意义
expected_decoded.bin
expected_metrics.json
```

---

# 40. 无损测试矩阵

必须包含：

```text
empty input
1 element
2 elements
small blocks
exact block boundary
boundary + 1
all zero
all one
constant
monotonic increasing
monotonic decreasing
alternating
periodic
random
high entropy
low entropy
INT_MIN/MAX
UINT_MAX
overflow-prone delta
```

---

# 41. 浮点测试矩阵

至少：

```text
+0
-0
small normal
subnormal
FLT_MIN
FLT_MAX
DBL_MIN
DBL_MAX
NaN
+Inf
-Inf
values near quantization boundaries
very small dynamic range
very large dynamic range
constant arrays
```

---

# 42. Differential Testing

原则：

```text
same input
same config

Reference
↓
intermediate/output

Canonical C++
↓
intermediate/output
```

比较：

```text
preprocessing
predictor
residual
quantized symbol
entropy symbol
metadata
decoded output
```

这样才能知道差异首次出现在哪里。

---

# 43. 无损四路验证

当参考格式支持时：

```text
1.
C_ref(x)
↓
D_ref
↓
x

2.
C_new(x)
↓
D_new
↓
x

3.
C_new(x)
↓
D_ref
↓
x

4.
C_ref(x)
↓
D_new
↓
x
```

对应：

```text
self reference
self new
new → reference
reference → new
```

---

# 44. Bitstream Identity 不是所有算法都需要

必须区分：

```text
Algorithm Equivalence
Format Compatibility
Bitstream Identity
```

两个 encoder 可能：

```text
bitstream 不同
但都合法
且都可被 decoder 正确读取
```

因此不能将：

```text
compressed_bytes_equal
```

错误地当作所有压缩器的 correctness 条件。

---

# 45. 有损验证

至少计算：

```text
max_abs_error
MAE
MSE
RMSE
NRMSE
PSNR
relative error
L2 norm error
```

根据 codec 声明选择强制指标。

---

## LOSSY-VAL-001：先验证合同，再比较指标

如果配置声明：

```text
ABS <= 1e-3
```

第一判断必须是：

\[
\max_i |x_i-\hat{x_i}| \le 10^{-3}
\]

而不是：

```text
PSNR 看起来很高，所以算通过
```

---

# 46. Fuzz Testing

decoder SHOULD 使用 fuzzing：

```text
random bytes
mutated valid frames
truncated frame
corrupted length
corrupted checksum
oversized varint
invalid offset
unknown version
reserved flag
```

目标：

```text
no crash
no UB
no hang
no OOB
bounded resource consumption
clean error
```

---

# 47. Determinism Testing

相同：

```text
input
config
version
ISA
thread count
```

重复 N 次。

验证：

```text
FinalBits and accounting components
decoded output
quality metrics
bitstream if promised deterministic
```

---

# 48. 独立性能验证的公平性

本章至第 64 章中的“Benchmark”仅表示 `ReWrite/<algorithm_id>/tests/performance` 内的独立性能回归和参考实现对照，不表示 TSDataCompressBenchMark 接入、正式实验或排名。不得调用项目 adapter、registry、experiment config 或正式 Benchmark harness。

Benchmark 必须先回答：

> 我们是在比较“算法”，还是比较“具体实现”？

建议同时定义：

```text
Algorithm Benchmark
Implementation Benchmark
```

---

# 49. Algorithm Benchmark

目标：

```text
尽量减少实现技巧差异
```

推荐：

```text
scalar
single thread
统一编译器
统一优化等级
统一输入
统一 chunk
```

---

# 50. Implementation Benchmark

目标：

```text
测量实际最好实现
```

允许：

```text
SIMD
multithread
native ISA
GPU
```

但必须明确 variant。

---

# 51. 时间边界

必须使用以下 scope 名称并分别报告：

| Scope | 边界 |
|---|---|
| `CORE` | 已准备输入/状态/工作区上的 codec core；是否包含 reset/finalize 必须显式声明 |
| `PIPELINE` | 形成可独立解码对象所需的 preprocess、core、entropy、finalize 和 metadata 生成 |
| `E2E` | layout conversion、必要 allocation/copy、完整 pipeline 和结果物化；文件 I/O 仅在专门 profile 中包含 |
| `NATIVE` | upstream/native API 自报的内部时间；只作为并列观测，不能替代 harness wall time |

每个 inner iteration 必须处理一个完整、独立对象；不得把同一有状态对象重复编码来人为放大计时。create/context reuse、reset frequency、workspace reuse、GC/JIT、GPU context 和 finalize 边界必须记录。不同 scope 的数据不得直接排名。

---

# 52. Warmup

性能测试必须做 warmup，尤其存在：

```text
instruction cache
data cache
dynamic dispatch
lazy initialization
CPU frequency ramp
JIT（参考语言）
GPU context
```

FORMAL profile 默认至少 warmup 3 次且累计不少于 0.5 秒。若算法、JIT 或设备未稳定，应继续 warmup，并记录实际次数和时间。

---

# 53. Repetition

FORMAL profile 必须至少执行 10 个 repetitions；每个 repetition 所选 scope 的累计时间至少 1 秒，且不得超过项目 profile 允许的上限。QUALIFICATION 可以降低次数，但其结果不得进入正式排名。

至少记录：

```text
iterations
repetitions
mean
median
min
max
stddev
CV
P25
P75
bootstrap CI95
```

推荐主要展示：

```text
median
+
dispersion
```

避免单次结果。

---

# 54. Throughput

压缩：

\[
T_c=\frac{UncompressedBytes}{CompressionTime}
\]

解压：

\[
T_d=\frac{UncompressedBytes}{DecompressionTime}
\]

必须明确单位：

```text
MB/s  = 10^6 B/s
MiB/s = 2^20 B/s
```

禁止混用。

---

# 55. Compression Ratio 与 FinalBits

所有压缩指标必须从 `FinalBits` 和 canonical raw bits 派生：

\[
CompressionFactor=\frac{CanonicalRawBits}{FinalBits}
\]

\[
BitsPerValue=\frac{FinalBits}{ValueCount}
\]

\[
SpaceSaving=1-\frac{FinalBits}{CanonicalRawBits}
\]

跨多个对象的 micro ratio 必须先求和：`sum(FinalBits) / sum(CanonicalRawBits)`，不得平均各对象 ratio。参考实现自报的 ratio 只能用于交叉检查。

---

# 56. Memory Accounting

至少分：

```text
input bytes
output capacity
actual serialized physical bytes
serialized bits by component
external side-information bits
final bits
workspace bytes
codec state
dictionary bytes
temporary peak
total peak RSS（可选）
```

---

# 57. CPU 环境

性能结果至少记录：

```text
CPU model
architecture
cores
SMT
frequency
cache
RAM
OS
kernel
NUMA
```

---

# 58. CPU Frequency / Thermal

长时间 benchmark 必须关注：

```text
DVFS
turbo
thermal throttling
background load
```

如无法完全控制，至少记录并增加 repetition。

---

# 59. Thread Affinity

高精度 Benchmark SHOULD：

```text
pin thread
record CPU core
```

尤其多核设备。

---

# 60. NUMA

在多 socket 系统：

```text
memory placement
thread placement
```

会显著影响结果。

因此必须在高级 Benchmark 中固定或记录。

---

# 61. Dataset 规则

第 38.2 节的数据集对照验证适用于 correctness；本章的记录还用于独立性能验证。输入 dataset 必须保存：

```text
dataset_id
checksum
dtype
shape
bytes
sampling info
preprocessing
missing-value policy
selected columns/channels
row/sample range
partition and case unit
label inclusion/exclusion policy
row/sequence boundary and reset policy
canonical input SHA-256
config SHA-256
```

同一 case 的原始实现、canonical C/C++ 和 optimized C/C++ 必须使用完全相同的 canonical input 和配置。`datasets/` 原始文件按只读资产处理，不得就地清洗或覆盖；派生输入必须可由 plan 中记录的命令重新生成。

对 UCRArchive 2018，统计和性能汇总必须先保留 subdataset、TRAIN/TEST partition 和 row case 三层身份。不得把分类标签字节计入 value payload，不得在未声明 framing 的情况下跨行继承 codec state，也不得把 adjusted variant 与顶层原始 variant 合并统计。

---

# 62. 禁止算法特化污染公平性

一个算法不得偷偷做：

```text
if dataset_name == X:
    use special parameter
```

参数自动选择必须：

```text
公开
可复现
对所有算法采用公平规则
```

---

# 63. Preprocessing

例如：

```text
normalize
transpose
delta
shuffle
byte shuffle
scale
cast
remove NaN
```

必须明确属于：

```text
algorithm intrinsic
还是
external preprocessing
```

并统一计量。

---

# 64. Parameter Tuning

如果算法需要调参：

```text
compression level
block size
error tolerance
dictionary size
predictor order
```

必须定义：

```text
default track
tuned track
```

不得给某算法手工精调而其他算法只用默认参数，然后宣称算法优劣。

---

# 65. Cross-Platform 验证

至少推荐：

```text
Linux x86_64
Linux AArch64
```

如有条件：

```text
Windows x64
macOS ARM64
```

---

# 66. Serialization 的平台独立性

必须验证：

```text
encode on x86
decode on ARM

encode on ARM
decode on x86
```

对 `CROSS_DECODE` 或 `BYTE_IDENTICAL` 目标应成为正式测试。平台不可用时必须提交 WAIVER，说明缺失平台、风险、替代证据和到期时间。

---

# 67. 独立 C ABI 与 C++ ABI

重写包可以只提供 C++ API，也可以额外提供本包自有的稳定 C ABI。若提供 C ABI，C++ exception、STL type、RTTI object、allocator-owned container 和 compiler-specific enum/layout 不得越过 ABI 边界。

共享库的实际导出符号、calling convention、API/ABI version 和 manifest 必须在独立 CI 中检查。更改公开 ABI 需要新增版本，不得静默改变已发布结构体或函数语义。此处的 C ABI 不是 `tscb_adapter_v1`，也不得复制其插件入口。

---

# 68. 版本兼容

格式版本和实现版本必须区分：

```text
codec_implementation_version
bitstream_format_version
standalone_api_version
```

三者不可混为一谈。

---

# 69. 错误处理

若提供 C ABI，必须定义本重写包自有的稳定状态集合，例如：

```text
REWRITE_STATUS_OK
REWRITE_STATUS_INVALID_ARGUMENT
REWRITE_STATUS_UNSUPPORTED
REWRITE_STATUS_DST_TOO_SMALL
REWRITE_STATUS_CORRUPT_STREAM
REWRITE_STATUS_FINALIZE_REQUIRED
REWRITE_STATUS_VERSION_MISMATCH
```

内部实现可以使用更细的分类，但必须稳定映射到公开状态，并通过本地 `get_last_error` 或等价机制提供非空、可诊断且不泄露敏感数据的说明。状态集合和数值属于本算法 public API，必须版本化。

禁止：

```text
返回 -1 但不知道为什么
```

---

# 70. 日志

独立性能验证的 hot path 禁止 logging。

错误和 debug 日志必须：

```text
可关闭
不影响计时与算法输出
```

---

# 71. Global State

禁止算法依赖：

```text
global mutable singleton
environment variable without recording
current locale
current rounding mode without setting
random seed without recording
wall-clock time
```

---

# 72. Randomness

如果算法使用随机过程：

```text
sampling
dictionary training
random projection
initialization
```

必须记录：

```text
PRNG algorithm
seed
version
```

独立验证默认应 deterministic。

## 72.1 Learned/Model Codec 专项合同

使用训练、拟合、在线更新或外部模型的 codec 必须额外记录：

```text
training_dataset_id and hash
train/validation/test split and leakage audit
training code revision, environment and random seeds
initial model artifact hash and serialized size
online-update/reset/checkpoint semantics
model availability required for decoding
training and inference hardware
```

测试数据不得参与离线训练、超参数选择或字典构建，除非该 track 明确允许并对所有算法采用相同政策。解码所需的 model/dictionary 若未嵌入输出，必须计入 `ExternalSideInformationBits`。

训练时间、能耗和资源默认与 encode/decode 性能分开报告；不得静默排除后宣称 E2E 优势。模型缺失、版本不匹配或 checkpoint 损坏时，decoder 必须 deterministic fail。

---

# 73. Locale

字符串配置解析不得受 locale 隐式影响：

```text
1.5
1,5
```

必须采用明确规则。

---

# 74. File I/O

默认 codec kernel 独立性能验证 SHOULD 不包含文件 I/O。

若评估 end-to-end file compression，则单独报告：

```text
read
compress
write
read compressed
decompress
```

---

# 75. Checksum

Checksum 的性能开销必须明确：

```text
checksum enabled
checksum disabled
```

不能不同算法配置不同却不标注。

---

# 76. Reference Implementation 保留规则

参考实现 MUST：

```text
固定版本
保存 commit
禁止被优化版覆盖
```

它的作用是：

```text
oracle
```

不是独立性能比较中的候选实现。

---

# 77. Canonical Scalar 的原则

canonical scalar SHOULD：

```text
代码清晰
无 architecture intrinsic
无并行
无 fast-math
少模板魔法
中间状态易观察
```

即：

> 优先可审计性，而非极限速度。

---

# 78. Optimization Patch Rule

任何优化 PR 必须回答：

```text
优化了什么？
理论上为什么更快？
有没有改变算法语义？
有没有改变内存？
有没有改变 bitstream？
有没有改变误差？
独立性能变化是否显著？
```

---

# 79. 优化不得与算法修改混在一个 PR

例如禁止一个 PR 同时：

```text
rewrite predictor
+
change quantizer
+
add AVX2
+
change bitstream
```

应该拆分。

否则 regression 无法定位。

---

# 80. Code Review 最小检查

Reviewer 必须检查：

```text
integer width
overflow
shift
signedness
endian
bit order
bounds
alignment
aliasing
FP precision
rounding
FMA
state reset
block boundary
metadata size
decoder validation
license
```

---

# 81. 规范化规则编号建议

项目可以将规则细化为：

```text
PORT-xxx   总体迁移
GATE-xxx   准入阶段
SRC-xxx    来源
LANG-xxx   源语言与运行时语义
INT-xxx    整数
BIT-xxx    位操作
END-xxx    端序
MEM-xxx    内存
BUF-xxx    缓冲区
FP-xxx     浮点
ROUND-xxx  舍入
LOSSY-xxx  有损
LOSSLESS-xxx 无损
STATE-xxx  状态
API-xxx    接口
ABI-xxx    二进制接口
ACCT-xxx   位数与组件计费
SIMD-xxx   SIMD
THREAD-xxx 并行
TEST-xxx   测试
CAP-xxx    原生能力等价性
BENCH-xxx  Benchmark
SEC-xxx    安全
LIC-xxx    许可证
REPRO-xxx  可复现性
CI-xxx     CI
```

规则 ID 在正文和 Appendix A 中必须保持唯一含义。新增、废弃或改变规则语义时必须更新唯一规则注册表；禁止在不同章节复用同一 ID 表达不同要求。

---

# 82. 项目级硬约束

以下建议直接作为 MUST：

### PORT-001
禁止未经说明改变论文/参考实现的数学定义。

### PORT-002
第一版 C/C++ 必须先实现 scalar canonical version。

### PORT-003
canonical correctness 未通过前禁止性能优化进入主分支。

### PORT-004
任何行为差异都必须进入 porting report。

### PORT-005
每次单算法重写必须覆盖 G0-G6；进入 G3 后不得以阶段性交付代替完整 `REWRITE_DONE`。

### CAP-001
必须从上游 source closure、公开 API、build flags、文档、CI 和测试建立完整 `NATIVE_CAPABILITY_MATRIX.yaml`，不得只盘点 scalar 路径。

### CAP-002
所有 `REQUIRED_PARITY` capability 必须在 C/C++ 重写中实现并通过专项验证；任一缺失、失败或未测试均阻断 `REWRITE_DONE`。

### CAP-003
上游正式支持的 streaming、SIMD、多线程、random access 或 GPU 路径默认属于 `REQUIRED_PARITY`，不得无证据降级为 `OPTIONAL_OPTIMIZATION` 或 `NOT_APPLICABLE`。

### CAP-004
`UNAVAILABLE_WITH_WAIVER` 必须具有平台/硬件/工具链/法律阻断证据和有效批准；存在该状态时总体只能是 `PARTIAL_WITH_WAIVER`，不得声明 `FULL_PARITY`。

### SCOPE-001
重写与 TSDataCompressBenchMark 接入必须完全分离；本标准禁止创建或修改 adapter、registry、Benchmark config 和框架源代码。

### TOOL-001
缺少源语言工具链时必须建立隔离、锁版本、可校验的参考环境，不得因此跳过 oracle、differential 或 cross-decode。

### GATE-001
不得以仓库级 `primary_language` 或逻辑条目数量直接决定重写；必须完成 G0 去重、对象分类和 AlgorithmID 分配。

### SRC-001
必须锁定实际 source closure、upstream revision 和每文件 hash。

### SRC-002
必须记录 source closure 内每个文件/片段及第三方依赖的许可证和来源。

### SRC-003
`Source/<algorithm_id>/upstream` 不得混入重写代码；必要改动必须以可校验补丁保存。

下列详细规则同样是项目级 MUST，含义以其首次定义章节为准，不在此处重新编号：

- `LANG-001`/`LANG-002`/`LANG-003`：未列语言、binding/script 和异构语言必须先完成正确分类与语义审计；
- `INT-001`：serialized integer 必须有明确宽度；
- `INT-003`：禁止依赖 signed overflow；
- `INT-005`：size arithmetic 必须做 overflow check；
- `BIT-001`：shift count 必须满足位宽范围；
- `END-001`：bitstream 禁止使用 host-native endian；
- `BITSTREAM-001`/`BITSTREAM-002`：格式、byte order 和 bit order 必须显式声明；
- `MEM-001`/`MEM-002`：pointer punning、aliasing 和 alignment 必须满足对象模型；
- `LOSSY-001`、`ROUND-001`：error mode 与 quantizer rounding 必须明确；
- `FP-001`/`FP-003`：canonical 精度必须固定且禁止默认 fast-math；
- `STATE-001`/`STATE-002`：执行模式与 reset frequency 必须固定；
- `LOSSLESS-001`、`LOSSY-VAL-001`：必须验证相应 correctness/error contract；
- `SAN-001`/`SAN-002`：canonical 必须通过 ASan 和 UBSan。

### ABI-001
独立重写 API 必须通过 version、buffer、lifecycle、error 和 capability 检查；禁止在重写任务中实现 `tscb_adapter_v1`。

### ACCT-001
必须满足 `FinalBits = SerializedBits + ExternalSideInformationBits`，组件和实际物理输出必须闭合。

### TEST-001
original/reference implementation 必须保留作为 oracle。

### TEST-002
必须建立 golden 和 differential tests。

### TEST-003
decoder 必须测试 malformed input 和资源边界。

### TEST-004
无损必须 bit-exact round-trip。

### TEST-005
有损必须验证正式 error contract。

### TEST-006
`CROSS_DECODE`/`BYTE_IDENTICAL` 必须执行参考实现与新实现的双向交叉解码。

### TEST-007
G6 发布和 `REWRITE_DONE` 前必须通过独立 Qualification Preflight。

### TEST-008
存在兼容数据时，必须用 `datasets/` 的相同 canonical input 和配置运行原始实现、canonical C/C++ 与适用的 optimized C/C++，并满足第 38.2 节的完善性条件。

### BENCH-001
压缩指标必须从 `FinalBits` 派生，不得只统计 payload 或 bytes_written 的子集。

### BENCH-002
压缩与解压吞吐必须分别报告。

### BENCH-003
线程数、ISA、compiler flags 必须记录。

### BENCH-004
FORMAL 至少 warmup 3 次且 0.5 秒、10 repetitions、每 repetition 至少 1 秒。

### LIC-001
必须记录文件/片段级原始代码许可证、来源和 redistribution 状态。

### REPRO-001
必须保存 source/archive、closure、patch、compile commands、artifact 和 environment digest，并验证声明的可复现等级。

---

# 83. CI Pipeline 建议

```text
PR
│
├─ format
├─ manifest/schema/source-closure hash
├─ source-language semantic audit
├─ native capability inventory/classification check
├─ file-level license/REUSE/SBOM
├─ compile
│  ├─ GCC
│  └─ Clang
├─ warnings
├─ standalone API symbol/version/manifest smoke
├─ unit
├─ golden
├─ roundtrip
├─ differential
├─ dataset source-vs-rewrite differential
├─ required streaming/state capability matrix
├─ required SIMD forced-path/tail/differential matrix
├─ required threading/TSan/determinism matrix
├─ cross-decode（目标要求时）
├─ qualification preflight
├─ FinalBits accounting closure
├─ ASan
├─ UBSan
├─ static analysis
├─ fuzz smoke
├─ cross-platform
├─ CAP-GATE closure and waiver-expiry check
└─ standalone performance regression smoke
```

Nightly：

```text
full differential
large datasets
full dataset source-vs-rewrite matrix
full native capability parity matrix
TSan
long fuzz
performance regression
memory regression
cross-ISA
independent reproducible-build comparison
```

---

# 84. Performance Regression Gate

每个 algorithm/variant 维护 baseline：

```text
compression throughput
decompression throughput
FinalBits and accounting components
workspace
peak memory
```

如果 PR 导致：

```text
> X% throughput regression
或
> Y% FinalBits regression
```

必须人工审核。

阈值由项目统一定义，不建议算法各自定义。

---

# 85. Correctness 优先于性能

以下情况必须阻止合入：

```text
快 30%
但偶尔违反 error bound
```

```text
快 15%
但 sanitizer 报 UB
```

```text
压缩率更高
但 decoder 无法兼容格式
```

```text
速度更快
但改变了 block reset
```

因为这些不是“优化”，而是“算法/语义改变”。

---

# 86. License 与来源管理

仓库级 SPDX 标签不能替代文件/片段级审计。每个 source closure 至少记录：

```yaml
source_url:
source_commit:
source_tag:
source_archive_sha256:
source_closure_sha256:
paper_doi:
original_author:
original_language:
files:
  - path:
    sha256:
    copyright:
    concluded_spdx:
    generated_from:
dependencies:
submodules:
patches:
redistribution_status:
commercial_use_status:
port_method: TRANSLATED | CLEAN_ROOM | PAPER_BASED
```

---

## LIC-002：不得认为“改成 C++ 就不受原许可证约束”

语言转换本身不会自动消除原代码的版权/许可证问题。

---

## LIC-003：区分“参考论文独立实现”和“源码翻译”

这两者必须在 `SOURCE_MANIFEST.yaml` 和 `PORT_MANIFEST.yaml` 中明确。

---

## LIC-004：SPDX identifier SHOULD 用标准名称

例如：

```text
MIT
BSD-3-Clause
Apache-2.0
GPL-3.0-only
GPL-3.0-or-later
```

---

## LIC-005：文件级机器可读许可信息

项目 SHOULD 遵循 REUSE Specification 3.3：每个纳入 source closure 或重写交付物的文件应具有机器可读的版权与许可证信息，可使用文件内 SPDX header 或 `.reuse/dep5`。`LICENSES/` 必须包含对应许可证正文。

---

## LIC-006：第三方、生成代码和补丁必须纳入 SBOM

submodule、vendored dependency、代码生成器输入/输出、模型、字典和项目补丁都必须进入 dependency/SBOM 记录。必须分别说明上游许可、补丁版权归属以及最终二进制/源码能否再分发；结论不明确时 Gate G1 必须阻断。

---

## 86.1 可复现构建合同

“可复现”必须使用可验证定义：在声明相同的源码、构建环境和构建指令下，两个独立构建产生 bit-for-bit 相同的目标产物。至少保存：

```text
source/archive SHA-256
source-closure SHA-256
patch-set SHA-256
compiler/linker/build-tool exact versions
target triple, sysroot and dependency lockfiles
environment/container digest
canonical build command and compile_commands SHA-256
generated-file/tool hashes
artifact SHA-256
reproduction run IDs and comparison result
```

若工具链暂时不能产生 bit-for-bit 相同产物，必须将状态标记为 `NOT_YET_REPRODUCIBLE`，记录差异来源并提交 WAIVER；不得仅凭“能够再次编译”宣称 reproducible build。

---

# 87. Security Threat Model

Decoder 输入视为攻击者可控。

需要防：

```text
integer overflow
buffer overflow
out-of-bounds read
infinite loop
stack exhaustion
allocation bomb
decompression bomb
malformed Huffman tree
invalid offset
corrupted block table
oversized metadata
```

---

# 88. Resource Limit

Decoder SHOULD 支持：

```text
max_output_bytes
max_blocks
max_dictionary_bytes
max_metadata_bytes
max_tree_nodes
```

避免不受限分配。

---

# 89. Decompression Bomb

如果 frame 声明：

```text
compressed = 1 KB
uncompressed = 1 TB
```

必须在分配前检查用户或独立测试设置的最大输出。

---

# 90. CMake / Build System

推荐：

```text
core
algorithms
tests
tools
tests/performance
```

重写目录的 CMake 禁止添加 TSDataCompressBenchMark adapter target 或链接其内部库。

分 target。

canonical 和 optimized variant 应为独立 target，方便不同 flags：

```cmake
codec_scalar
codec_avx2
codec_neon
```

不要给整个工程全局加：

```text
-march=native
-ffast-math
```

---

# 91. 第三方库隔离

第三方：

```text
zstd
lz4
boost
eigen
...
```

必须通过明确 dependency boundary。

记录：

```text
version
build options
license
```

---

# 92. 重写实现和上游实现必须区分

独立验证中：

```text
native upstream implementation
```

和：

```text
our C++ reimplementation
```

必须有不同 algorithm/implementation ID。

否则无法判断正确性和性能来源。第三方 wrapper 只能用于运行 oracle，不得作为 C/C++ 重写产物冒充 `canonical_cpp`。

---

# 93. Implementation Identity

建议：

```text
algorithm_id = delta_rle
implementation_id = canonical_cpp
variant = scalar
```

另一个：

```text
algorithm_id = delta_rle
implementation_id = optimized_cpp
variant = avx2
```

---

# 94. 独立性能验证结果 Schema

结果 schema 必须能够还原参考/重写比较组、执行路径、计费和统计来源。它只保存在重写包的 validation 目录，不是 TSDataCompressBenchMark 正式结果。至少包含：

```json
{
  "algorithm_id": "...",
  "implementation_id": "...",
  "variant": "...",
  "object_level": "P1_STANDALONE_CODEC",
  "port_method": "TRANSLATED",
  "compatibility_target": "CROSS_DECODE",
  "config_id": "...",
  "dataset_id": "...",
  "dtype": "...",
  "shape": [],
  "canonical_raw_bits": 0,
  "serialized_bits": 0,
  "external_side_information_bits": 0,
  "final_bits": 0,
  "accounting_components": {},
  "compression_factor": 0,
  "measurement_mode": "FORMAL",
  "timing_scope": "PIPELINE",
  "encode_wall_ns": {},
  "decode_wall_ns": {},
  "native_timing_ns": {},
  "compression_throughput_mib_s": 0,
  "decompression_throughput_mib_s": 0,
  "workspace_bytes": 0,
  "peak_memory_bytes": 0,
  "threads_used": 1,
  "isa_used": "...",
  "execution_path_hash": "...",
  "native_capability_matrix_sha256": "...",
  "native_capability_parity_result": "FULL_PARITY",
  "required_capabilities_total": 0,
  "required_capabilities_passed": 0,
  "waiver_ids": [],
  "compiler": "...",
  "compiler_version": "...",
  "flags": [],
  "source_closure_sha256": "...",
  "artifact_sha256": "...",
  "preflight_passed": true,
  "correctness": true,
  "error_metrics": {}
}
```

`encode_wall_ns`/`decode_wall_ns` 应保存 repetition 级原始观测或可追踪引用，并汇总 n、median、P25、P75、mean、SD、CV 和 bootstrap CI95。不得只保存最快值。

`native_capability_matrix_sha256` 必须指向本次构建实际使用的冻结矩阵；`required_capabilities_total` 与 `required_capabilities_passed` 必须能够逐项回溯到矩阵中的 capability ID。存在有效 waiver 时，`native_capability_parity_result` 必须为 `PARTIAL_WITH_WAIVER` 且 `waiver_ids` 非空；任一 required capability 未通过时必须为 `FAIL`，不得通过修改计数字段伪装为完整支持。

---

# 95. Porting Report 模板

```markdown
# <Algorithm> Porting Report

## 1. Source
## 2. Paper
## 3. Version
## 4. License
## 5. Original Language
## 6. Source Closure and Hashes
## 7. Source Toolchain Acquisition and Reproduction
## 8. PortMethod / CompatibilityTarget / ObjectLevel
## 9. Rewrite-Only Scope and G0-G6 Evidence
## 10. Algorithm Contract
## 11. Source-Language Semantic Audit
## 12. Integer and Floating Semantics
## 13. Rounding / FMA / Special Values
## 14. Data Layout
## 15. State / Block / Finalize
## 16. Bitstream and FinalBits Accounting
## 17. Native Capability Inventory and Classification
## 18. Streaming / SIMD / Threading / Accelerator Parity Results
## 19. Known Differences and Waivers
## 20. Golden / Differential / Cross-decode Results
## 21. Dataset Selection, Canonical Input Hashes and Source-vs-Rewrite Results
## 22. Standalone API and Qualification Preflight
## 23. Sanitizer / Fuzz / Cross-platform Results
## 24. Canonical / Optimized Results
## 25. Reproducible Build Evidence
## 26. Performance and Remaining Risks
## 27. No-Integration Attestation
```

---

# 96. 单算法验收 Checklist

## 来源

- [ ] 论文确认
- [ ] 原仓库确认
- [ ] commit/tag 固定
- [ ] source closure 与文件 hash 固定
- [ ] submodule/生成代码/补丁固定
- [ ] 文件级 license/SPDX/redistribution 确认
- [ ] AlgorithmID/ImplementationID 去重
- [ ] PortMethod/CompatibilityTarget/ObjectLevel 确认

## 源语言语义

- [ ] language/compiler/runtime 精确版本
- [ ] compiler/runtime/SDK 下载 URL、archive hash、安装与复现命令
- [ ] 隔离环境和 environment digest
- [ ] backend/target/word size/build profile
- [ ] dependency lock 与 native/FFI closure
- [ ] binding、wrapper、生成代码与算法核心已分类
- [ ] overflow/shift/division/conversion 原语义
- [ ] rounding/FMA/special values 原语义
- [ ] layout/view/copy/alias/lifetime 原语义
- [ ] collection order、异常/panic 和并发状态
- [ ] JIT/GC/setup/finalization 的计时边界

## Contract

- [ ] 输入 dtype
- [ ] shape
- [ ] layout
- [ ] block size
- [ ] state
- [ ] error mode
- [ ] bitstream
- [ ] endian
- [ ] bit order
- [ ] special values

## Integer

- [ ] 所有固定宽度类型审核
- [ ] signed overflow 审核
- [ ] shift 审核
- [ ] narrowing 审核
- [ ] size arithmetic 审核

## Floating

- [ ] float/double 审核
- [ ] rounding 审核
- [ ] FMA 审核
- [ ] NaN/Inf 审核
- [ ] subnormal 审核
- [ ] fast-math 禁用

## Memory

- [ ] alignment
- [ ] aliasing
- [ ] lifetime
- [ ] capacity
- [ ] workspace
- [ ] allocation

## Correctness

- [ ] canonical encoder、decoder 和完整 pipeline 均已完成
- [ ] unit
- [ ] golden
- [ ] roundtrip
- [ ] differential
- [ ] cross-decode
- [ ] malformed
- [ ] ASan
- [ ] UBSan
- [ ] fuzz
- [ ] input immutable/canary/safe-overread
- [ ] bound-1 与 N=0/1/2、B-1/B/B+1
- [ ] reset/finalize/repeated-finalize
- [ ] T/V pairing 或 joint codeword

## NativeCapabilityParity

- [ ] 已从 public API、build flags、docs、CI、tests 和可达代码提取完整能力清单
- [ ] 已生成并冻结 `NATIVE_CAPABILITY_MATRIX.yaml`
- [ ] 每项能力已分类为 `REQUIRED_PARITY`、`OPTIONAL_OPTIMIZATION`、`UNAVAILABLE_WITH_WAIVER` 或 `NOT_APPLICABLE`
- [ ] 上游正式 streaming/stateful 能力已完成 fragmentation、flush/finalize、reset、interleaved-handle 和 bounded-memory 验证
- [ ] 上游正式 SIMD ISA variant 已实现 forced-path、tail、unaligned、fallback 和 scalar differential 验证
- [ ] 上游正式多线程能力已区分 internal parallelism 与 concurrent handles，并通过 thread-count、TSan 和 determinism 验证
- [ ] required GPU/accelerator/random-access/query 等其他能力均有专项证据
- [ ] 所有 `REQUIRED_PARITY` 状态为 PASS，不存在 `MISSING`、`FAIL` 或 `NOT_TESTED`
- [ ] 所有 waiver 已批准且未过期；存在 waiver 时 overall result 为 `PARTIAL_WITH_WAIVER`
- [ ] 已生成 `native_capability_validation_report.md`

## Dataset 对照验证

- [ ] 已生成 `DATASET_TEST_PLAN.yaml`
- [ ] 从 `datasets/` 选择了 dtype、shape、维度和语义兼容的数据
- [ ] dataset 文件、选择范围、预处理、config 和 canonical input hash 已固定
- [ ] 原始实现与 canonical C/C++ 使用相同输入和参数
- [ ] optimized C/C++ 在适用时使用相同输入重新验证
- [ ] 无损 bit-exact 或有损 error contract 逐 case 通过
- [ ] CompatibilityTarget 要求的 cross-decode/byte-identical 通过
- [ ] 已生成逐 case `dataset_validation_report.md`
- [ ] 不兼容或缺失数据集时已有证据和有效 WAIVER/补充数据
- [ ] 使用 UCR 时已排除首列分类标签，固定 TRAIN/TEST、row case 和 reset/finalize 边界
- [ ] 使用 UCR adjusted variant 时已记录完整路径、缺失值/变长政策并与顶层版本分离

## 独立 API 与计费

- [ ] 独立 public API、version 和 manifest
- [ ] uint64 capacity/used/shape 与 ownership
- [ ] error、query、accounting capability
- [ ] 未实现或修改 `tscb_adapter_v1`、registry 和 Benchmark 配置
- [ ] SerializedBits 组件闭合
- [ ] ExternalSideInformationBits 完整
- [ ] FinalBits 与实际物理输出闭合

## Performance

- [ ] warmup
- [ ] repetition
- [ ] compression throughput
- [ ] decompression throughput
- [ ] CORE/PIPELINE/E2E/NATIVE scope
- [ ] FinalBits/compression factor/bits per value
- [ ] workspace
- [ ] compiler flags
- [ ] ISA
- [ ] threads
- [ ] 所有 REQUIRED_PARITY optimized variant 已重验
- [ ] `OPTIMIZATION_NOT_APPLICABLE` 仅在上游不存在 required optimized capability 时使用
- [ ] OPTIONAL_OPTIMIZATION 已明确列入 backlog 或完成，不影响能力支持声明

## 范围与完成状态

- [ ] G0-G6 全部完成并有证据
- [ ] CAP-GATE 已闭合，总体结果为 `FULL_PARITY` 或有有效依据的 `PARTIAL_WITH_WAIVER`
- [ ] 最终状态为 `REWRITE_DONE`
- [ ] 未修改 TSDataCompressBenchMark adapter、native ABI、registry、实验配置或框架代码
- [ ] 接入未被作为本次任务的完成条件或附带工作

## 验证产物保留与清理（执行清理时适用）

- [ ] 已达到 `REWRITE_DONE`，最终发布包已生成，清理前的最终审计通过
- [ ] 已按第 113 章区分最小保留证据、运行必需资产和可重新生成的中间产物
- [ ] 清理清单记录明确路径、大小、SHA-256、引用关系和重新生成方法
- [ ] 原始源码、关键金样本、验证报告及关联日志、必需模型/字典和当前最终发布包仍可取得并校验
- [ ] 已更新受影响的 manifest、SBOM、验证引用和发布清单；重新打包及清理后最终审计通过
- [ ] 未通过删减用例、降低能力或容差、隐藏失败、保留失效 hash 引用来缩减体积
- [ ] 已记录实际空间变化、恢复位置及最终包 hash；未影响其他算法或用户数据

---

# 97. PR 模板建议

```markdown
## Algorithm
<name>

## Scope
- [ ] Rewrite only; no TSDataCompressBenchMark integration
- [ ] G0-G6 are included in this delivery

## Native Capability Parity
- Overall: FULL_PARITY / PARTIAL_WITH_WAIVER / FAIL
- Required total/passed:
- Waivers:
- [ ] Streaming/state parity
- [ ] SIMD parity
- [ ] Threading parity

## Change Type
- [ ] Canonical correctness
- [ ] Bug fix
- [ ] Bitstream
- [ ] Optimization
- [ ] SIMD
- [ ] Parallel
- [ ] Standalone API
- [ ] Complete G0-G6 rewrite

## Semantic Changes
None / Describe

## Bitstream Changes
None / Describe

## Error-bound Changes
None / Describe

## Tests
- [ ] unit
- [ ] golden
- [ ] differential
- [ ] sanitizer
- [ ] cross-platform

## Performance
Before:
After:

## Risk
...
```

---

# 98. 推荐的实施顺序

对大量算法，不建议随机开工。

建议先做基础设施：

```text
1. DType
2. Buffer/View
3. Checked arithmetic
4. Endian helpers
5. BitReader/BitWriter
6. Varint/ZigZag
7. ErrorSpec
8. Standalone public API
9. Golden/differential/cross-decode harness
10. Standalone qualification/performance harness
```

然后选 3–5 个代表算法打通：

```text
简单无损
LZ 类
预测 + entropy
简单有损 quantization
复杂有损
```

确认框架稳定后再批量扩展。

---

# 99. 不建议的开发方式

## 错误方式 A

```text
把 Python 全翻成 C++
↓
能编译
↓
跑几个数据
↓
开始 AVX
```

问题：

```text
缺少 semantic oracle
```

---

## 错误方式 B

```text
一开始追求最快
```

结果可能：

```text
不知道性能来自算法还是优化技巧
```

---

## 错误方式 C

```text
所有算法都强行套相同 chunk
```

会破坏：

```text
dictionary
predictor
state
```

---

## 错误方式 D

```text
只验证 decompress(compress(x)) == x
```

如果 encoder 和 decoder 同时犯相同错误，也可能“通过”。

---

## 错误方式 E

```text
只比较 compressed bytes
```

对合法但非唯一编码可能造成误判。

---

# 100. 典型 Bug 示例

## Case 1：Python → C++ rounding

Python：

```python
q = round(r / eb)
```

错误：

```cpp
auto q = std::round(r / eb);
```

结果：

```text
tie point symbol 变化
```

---

## Case 2：Java hash → C++

Java：

```java
int h = x * 0x9E3779B9;
```

错误：

```cpp
int32_t h = x * 0x9E3779B9;
```

原因：

```text
Java wrap
vs
C++ signed overflow UB
```

---

## Case 3：MATLAB → C++

MATLAB：

```text
column-major
```

C++ 代码按：

```text
row-major
```

线性扫描。

结果：

```text
预测邻接关系变化
```

甚至算法已经不同。

---

## Case 4：native endian

```cpp
fwrite(&header, sizeof(header), 1, f);
```

x86 工作。

换 CPU 后格式损坏。

---

## Case 5：错误的独立性能验证

算法 A：

```text
preallocate workspace
```

算法 B：

```text
每次 encode malloc
```

如果时间边界不一致，结果不具可比性。

---

# 101. 推荐的核心公共组件

```text
core/
├── checked_math.hpp
├── types.hpp
├── status.hpp
├── buffer.hpp
├── endian.hpp
├── bit_reader.hpp
├── bit_writer.hpp
├── varint.hpp
├── zigzag.hpp
├── fp_policy.hpp
├── error_spec.hpp
├── workspace.hpp
├── codec.hpp
└── validation/
```

原则：

> 将最容易出错的底层行为集中实现一次，而不是让每个算法重复写。

---

# 102. `checked_math.hpp` 应负责

```text
checked_add
checked_sub
checked_mul
checked_cast
```

目的：

```text
避免 size overflow
避免隐式 narrowing
```

---

# 103. `endian.hpp` 应负责

```text
load16_le/be
load32_le/be
load64_le/be
store16_le/be
store32_le/be
store64_le/be
```

---

# 104. `bit_writer.hpp` 应负责

```text
write_bit
write_bits
align_byte
flush
capacity
bytes_written
```

并规定：

```text
bit numbering
bit order
overflow behavior
```

---

# 105. `fp_policy.hpp`

建议：

```cpp
struct FloatingPolicy {
    PrecisionMode precision;
    RoundingMode rounding;
    FmaMode fma;
    SpecialValuePolicy special;
};
```

---

# 106. Debug Instrumentation

canonical 实现可以加入：

```text
dump_predictor
dump_residual
dump_quantized_symbol
dump_code_length
dump_block_header
```

用于 differential testing。

Release 时编译关闭。

---

# 107. 中间状态 checksum

大量数据时不必保存全部 trace。

可以对每阶段计算：

```text
hash(predictions)
hash(residuals)
hash(symbols)
hash(bitstream)
```

快速找到第一个 divergence stage。

---

# 108. 大规模批量迁移管理

必须维护由 G0 审计产生的总表；逻辑条目、去重仓库和 AlgorithmID 应使用不同字段：

| Logical Entry | Repository | AlgorithmID | ObjectLevel | Closure | Toolchain | Lang Audit | License | Contract | Capability Inventory | Required/Passed | Parity Result | Scalar | Full Codec | Diff | Dataset Diff | Preflight | Repro | Status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

状态：

```text
DISCOVERED
DEDUPLICATING
SOURCE_CLOSURE
CONTRACTING
ORACLE_READY
PORTING
VALIDATING
OPTIMIZING
RELEASING
REWRITE_DONE
BLOCKED
```

禁止将 `BENCH_READY`、`INTEGRATED` 或 adapter 状态写入重写总表。单算法一旦进入 `PORTING`，应在同一任务内依次完成 `VALIDATING`、`OPTIMIZING`、`RELEASING`，最终到达 `REWRITE_DONE`；遇到无法自行解除的硬阻断时转为 `BLOCKED` 并记录恢复条件。

---

# 109. Definition of Done

一个算法只有全部满足以下条件才是 `REWRITE_DONE`：

```text
来源明确
source closure/hash/patch 固定
source-language semantic audit 完成
原语言 compiler/runtime/SDK 和依赖环境已锁定并可运行 oracle
文件级许可证与 SBOM 完成
合同冻结
NATIVE_CAPABILITY_MATRIX 已冻结且不存在 UNCLASSIFIED
canonical encoder/decoder 和完整 pipeline 完成
correctness 通过
DATASET_TEST_PLAN 已冻结，原始实现与重写实现的兼容真实数据对照全部通过
dataset_validation_report 已记录逐 case hash、命令、指标和结论
sanitizer 通过
独立 public API、CLI/测试驱动与 preflight 通过
FinalBits 账本闭合
所有 REQUIRED_PARITY streaming/stateful、SIMD、多线程及其他原生能力均已实现并通过专项验证
native_capability_validation_report 已记录逐项证据和总体结果
CAP-GATE 为 FULL_PARITY，或存在有效 WAIVER 时为 PARTIAL_WITH_WAIVER
所有 REQUIRED_PARITY optimized variant 完成并重新通过 differential
OPTIONAL_OPTIMIZATION 已明确标识，不冒充当前能力
声明的可复现构建验证完成或有有效 WAIVER
文档完成
未创建或修改任何 TSDataCompressBenchMark adapter、registry、实验配置或框架代码
```

“能编译”不等于完成。

“能解压”不等于完成。

“速度快”不等于完成。

“scalar 正确”不等于原生能力完整。

“已经能被 Benchmark 调用”也不等于重写完成；反之，`REWRITE_DONE` 不表示已接入 Benchmark。

---

# 110. Exception / Waiver 流程

如果必须违反规范：

```text
Rule ID:
Reason:
Affected Algorithm:
Capability ID:
Requested Parity Class:
Upstream Evidence:
Blocking Platform/Hardware/Toolchain/Legal Evidence:
Semantic Impact:
Portability Impact:
Standalone Validation Impact:
Future Integration Impact:
Security Impact:
Tests Added:
Approver:
Expiration:
Revalidation Plan:
```

禁止口头豁免。

---

# 111. 最终原则

整个项目必须坚持下面的层次：

```text
论文/标准
↓
算法语义
↓
数值语义
↓
状态语义
↓
bitstream
↓
C/C++ object/memory semantics
↓
correctness
↓
standalone API 与资格验证
↓
optimization
↓
hardware specialization
↓
REWRITE_DONE
```

不能倒过来。

`REWRITE_DONE` 之后，如项目需要接入，必须另开独立任务；该任务不属于本规范的执行链路。

最危险的工程模式是：

```text
先优化
↓
能跑
↓
结果差不多
↓
认为正确
```

正确模式应是：

```text
先定义
↓
先冻结语义
↓
先建立 oracle
↓
先写 scalar
↓
逐层验证
↓
再优化
↓
优化后重新验证
```

---

# 112. 推荐参考资料

以下资料应作为本项目底层规则的外部参考。

## C/C++ 整数与对象模型

- cppreference, fixed-width integers\
  https://en.cppreference.com/cpp/types/integer

- cppreference, object model / strict aliasing / alignment\
  https://en.cppreference.com/cpp/language/object

- cppreference, `memcpy`\
  https://en.cppreference.com/c/string/byte/memcpy

## 浮点与编译器

- GCC Optimize Options\
  https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html

- Clang Compiler User's Manual — Floating Point Behavior\
  https://clang.llvm.org/docs/UsersManual.html

- C++ `std::round`\
  https://en.cppreference.com/cpp/numeric/math/round

- C++ `std::nearbyint`\
  https://en.cppreference.com/cpp/numeric/math/nearbyint

## Sanitizers

- AddressSanitizer\
  https://clang.llvm.org/docs/AddressSanitizer.html

- UndefinedBehaviorSanitizer\
  https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html

- ThreadSanitizer\
  https://clang.llvm.org/docs/ThreadSanitizer.html

## 压缩格式

- RFC 1951 — DEFLATE\
  https://www.rfc-editor.org/rfc/rfc1951

- RFC 8878 — Zstandard\
  https://www.rfc-editor.org/rfc/rfc8878

- LZ4 Frame Format\
  https://github.com/lz4/lz4/blob/dev/doc/lz4_Frame_format.md

## 有损压缩

- zfp Documentation\
  https://zfp.readthedocs.io/

- SZ3\
  https://szcompressor.org/

## Benchmark

- Google Benchmark User Guide\
  https://github.com/google/benchmark/blob/main/docs/user_guide.md

## 并行

- OpenMP Specifications\
  https://www.openmp.org/specifications/

## 源语言行为

- Python built-in functions (`round`)\
  https://docs.python.org/3/library/functions.html

- Python Expressions — binary arithmetic operations\
  https://docs.python.org/3/reference/expressions.html#binary-arithmetic-operations

- Go Language Specification\
  https://go.dev/ref/spec

- Rust Reference — Operator Expressions / Overflow\
  https://doc.rust-lang.org/reference/expressions/operator-expr.html#overflow

- Java Language Specification, Chapter 15\
  https://docs.oracle.com/javase/specs/jls/se21/html/jls-15.html

- C# Language Reference — arithmetic operators and overflow checking\
  https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/operators/arithmetic-operators

- .NET `Math.Round` midpoint rounding\
  https://learn.microsoft.com/en-us/dotnet/api/system.math.round

- ECMAScript Language Specification\
  https://tc39.es/ecma262/

- TypeScript Handbook\
  https://www.typescriptlang.org/docs/handbook/intro.html

- Kotlin — Numbers\
  https://kotlinlang.org/docs/numbers.html

- Zig Language Reference\
  https://ziglang.org/documentation/master/

- Fortran 2018 working document (J3/18-007r1)\
  https://j3-fortran.org/doc/year/18/18-007r1.pdf

- Julia — Integers and Floating-Point Numbers\
  https://docs.julialang.org/en/v1/manual/integers-and-floating-point-numbers/

- Julia — Mathematical Operations and Elementary Functions\
  https://docs.julialang.org/en/v1/manual/mathematical-operations/

- R Language Definition\
  https://cran.r-project.org/doc/manuals/r-release/R-lang.html

- MATLAB Row/Column Major Layout\
  https://www.mathworks.com/help/coder/ug/what-are-column-major-and-row-major-representation-1.html

- MATLAB `round`\
  https://www.mathworks.com/help/matlab/ref/double.round.html

## License

- SPDX License List\
  https://spdx.org/licenses/

- GNU GPL FAQ\
  https://www.gnu.org/licenses/gpl-faq.html

- REUSE Specification 3.3\
  https://reuse.software/spec-3.3/

## 安全整数与可复现构建

- SEI CERT C INT32-C — Ensure that operations on signed integers do not result in overflow\
  https://cmu-sei.github.io/secure-coding-standards/sei-cert-c-coding-standard/rules/integers/int32-c/

- Reproducible Builds — Definition\
  https://reproducible-builds.org/docs/definition/

---

# 113. 验证产物保留、清理与存储去重

## 113.1 清理条件与状态边界

验证期间允许保存模型、梯度、训练快照、CDF、编解码输出和实验结果。它们不必全部永久驻留在每个算法目录，但必须能够区分最终验收证据与可重新生成的中间产物。

**允许清理可重新生成的验证中间产物，常规清理应在该算法达到 `REWRITE_DONE`、最终发布包生成且最终审计通过后执行。** `FULL_PARITY` 只表示原生能力一致性通过，不等于 G0-G6 全部通过，也不自动授权删除证据、模型或数据。

处于 `IN_PROGRESS`、`PORTING`、`BLOCKED` 或验证失败状态的算法，不得套用“已完成算法清理”规则删除尚需诊断、差分定位或复现阻断的材料。可以先对已确认内容相同且不再写入的文件做保留路径与内容的存储去重。

清理是存储维护，不是改变算法结论的手段：不得减少必需能力、删去失败记录、放宽容差、改变输入/配置或以已完成的部分验证替代尚未完成的 Gate。

## 113.2 必须保留的最小证据与运行资产

以下内容必须保留，或存入有明确位置、可恢复并可校验的持久归档：

| 类别 | 必须保留的内容 |
|---|---|
| 来源与版本 | 原始 source closure、commit/version、文件 hash、必要补丁、来源/版权/许可证记录和依赖身份 |
| 算法合同 | 冻结的 Algorithm Contract、能力矩阵、参数、数值容差、状态/bitstream/误差语义和数据集选择方案 |
| 关键金样本 | 支撑当前兼容性、边界、真实数据对照及必要 cross-decode 结论的 canonical input、期望输出或确定性观测点 |
| 验证证据 | correctness、dataset differential、能力、preflight、sanitizer、静态分析、跨平台、可复现构建及性能报告，以及关联执行日志和结论所需的关键失败/阻断材料 |
| 运行必需资产 | 独立 encoder/decoder 或完整 pipeline 所需的模型、字典、码表、参数和状态，以及其来源和计费记录 |
| 发布与重现 | 当前最终发布包、发布清单、SBOM、源码/环境/命令/产物 digest、重新生成脚本及配置；需要冷存储的材料还须有归档索引 |

运行必需的模型、字典或码表不是可删除的验证缓存。不得通过移除它们降低 `FinalBits`，也不得让独立解码暗中依赖被删去的原始输入、训练结果或 source oracle。

“保留最小证据集”必须仍能核验当前 Gate 和能力结论、复现关键测试并独立消费交付包。仅保留一句 PASS 或一个 hash，无法取得对应文件、日志或可执行重现方法，不构成证据闭环。重新生成方法也不能替代必须保留的关键失败日志和当前验收报告。

## 113.3 可以清理的候选产物

在满足 113.1、113.2 和引用核查后，下列文件可以纳入清理候选：

- 内容完全相同的模型、字典、CDF 或其他大型资产的冗余物理副本；至少保留一个经校验的权威副本；
- 不属于运行依赖、关键金样本或当前结论必要证据的逐步梯度、训练中间快照和临时张量；
- 可由保留的输入、配置、源码、环境和脚本重新生成的临时压缩/解码输出；
- 已被最终合格验证覆盖、且无需继续复现独特失败或行为差异的实验中间结果；
- 不属于发布产物或可复现构建验收对象的构建目录、编译缓存和可恢复的工具下载缓存。

上述类别只是候选，不是按扩展名或目录名批量删除的授权。例如同为模型快照，有的属于中间训练产物，有的正是最终 decoder 必需模型；同为实验输出，有的可以重建，有的仍承载未解决的数值或 GPU 阻断证据。

## 113.4 清理与重新封包流程

执行清理必须按以下顺序完成：

1. **核验现有交付**：确认算法状态、G0-G6、CAP-GATE、最终包及现有证据审计；记录清理前的包 hash 和磁盘占用。
2. **建立清理清单**：逐项记录明确路径、大小、SHA-256、用途、所属算法、报告/manifest/SBOM/发布包引用、保留或移除理由；可重新生成的产物须记录脚本、输入/配置/环境身份、随机种子及适用的确定性条件。
3. **确定保留与恢复位置**：核验最小证据集、运行必需资产和权威副本仍可读取；需要归档的材料须先验证归档内容和 hash。清理后审计通过前，保留可以恢复旧交付的材料，优先采用可恢复移置。
4. **更新证据引用并重新打包**：更新实际受影响的 manifest、SBOM、验证材料索引、发布清单和 package digest，移除或改写已不成立的文件引用。不得给不存在的文件保留“当前本地文件已核验”的声明。记录原包与新包的关联及变更原因。
5. **执行限定清理并最终核验**：只处理清单中已核实的目标；核验当前路径/归档内容、hash、必要测试资产、独立构建/解码依赖和新包的可复现性，完成清理后最终审计。涉及代码、参数、模型或执行环境变化时，必须重跑相应验证；仅存储调整可依据不变的内容身份和产物身份核验。
6. **记录结果**：保存清理清单、前后占用、实际释放空间、保留/归档位置、最终包 SHA-256 和审计结论。审计失败时恢复旧交付或明确标记证据失效，不得继续宣称已核验完成。

现有验证文件可能被多个报告、SBOM 和发布清单交叉引用。直接删除 `validation/`、训练目录或历史目录，会使当前文件 hash 或归档清单失效；必须先完成上述核查与引用维护。更新 hash 本身不能修复丢失的必要证据，也不能代替重新执行受变化影响的测试。

## 113.5 未完成算法优先采用内容去重

大型模型和多轮验证中间产物可能占据主要空间；只清理已经完成的算法，不一定能明显降低总占用。对于尚未达到 `FULL_PARITY` 或仍有阻断的算法，优先考虑保留文件路径与字节内容的去重：

- 先核对长度、SHA-256 和来源，必要时逐字节比较；相同文件名或大小不能证明内容相同；
- 同一 source commit/closure 被多个 AlgorithmID 使用时，可以共享经校验的不可变源资产，但各算法的身份、能力矩阵、合同和报告必须分别保留；
- 在文件系统支持时，可对不可变文件采用 hard link、reflink 或内容寻址存储；选择方案必须保持现有读取路径和 hash 校验有效，不能引入断链或未经声明的外部运行依赖；
- 对仍会被训练、验证工具或用户原地改写的文件，不得直接共用 hard link；采用独立副本、写时复制或明确的不可变资产机制，避免一个算法修改另一个算法的证据；
- 去重前后必须核验源文件及所有保留路径的内容身份，使用实际磁盘分配量记录收益，不能把逻辑文件长度之和当成真实释放空间。

项目执行状态示例：当 TEC-TT 和 DZip 尚未达到 `FULL_PARITY` 时，其大型模型、CDF、梯度和阻断定位材料应先审核去重或归档；不得因为其他算法已经 `REWRITE_DONE` 就删除这些仍在使用的证据。该示例不固定算法的长期状态，实际操作必须读取最新 manifest 与审计结果。

---

# Appendix A：强制规则快速表

本表是规则 ID 的唯一快速注册表；要求摘要必须与第 82 章保持同义。

| Rule | Requirement |
|---|---|
| PORT-001 | 不得未经说明改变算法数学定义 |
| PORT-002 | 第一版必须先有 canonical scalar |
| PORT-003 | correctness 通过前不得进入正式优化 |
| PORT-004 | 所有行为差异必须进入 porting report |
| PORT-005 | 单算法重写必须端到端完成 G0-G6，进入 G3 后不得以阶段性交付代替 REWRITE_DONE |
| CAP-001 | 必须从上游源码闭包、公开接口、构建配置、文档、CI 和测试建立完整能力清单 |
| CAP-002 | 所有 REQUIRED_PARITY 能力必须实现并通过专项验证，否则阻断 REWRITE_DONE |
| CAP-003 | 上游正式支持的 streaming、SIMD、多线程、random access 和 GPU 等能力默认属于 REQUIRED_PARITY |
| CAP-004 | UNAVAILABLE_WITH_WAIVER 必须有阻断证据和有效批准，且总体不得声明 FULL_PARITY |
| SCOPE-001 | 重写和 TSDataCompressBenchMark 接入必须分离，本标准禁止实施 adapter/registry/config/framework 接入 |
| TOOL-001 | 必须建立隔离、锁版本、可校验的源语言工具链，不得因工具缺失省略 oracle 验证 |
| GATE-001 | 必须通过 G0 去重和对象分类，仓库语言统计不能直接生成重写任务 |
| SRC-001 | 必须固定 source closure、upstream revision 和文件 hash |
| SRC-002 | 必须记录文件/片段及依赖的许可证和来源 |
| SRC-003 | 原始快照不得混入重写代码，修改以补丁保存 |
| LANG-001 | 未列语言必须完成通用语义审计 |
| LANG-002 | script、binding、生成代码和算法核心必须分开 |
| LANG-003 | GPU/加速语言不得仅按扩展名判为非 C/C++ |
| INT-001 | serialized integer 必须有明确宽度 |
| INT-002 | 长度/容器大小、serialized integer 与算法整数不得混淆 |
| INT-003 | 禁止依赖 signed overflow |
| INT-005 | size arithmetic 必须 checked |
| BIT-001 | shift count 必须满足位宽范围 |
| END-001 | bitstream 禁止使用 host-native endian |
| BITSTREAM-001 | 每个格式必须声明版本、端序、bit order 与边界语义 |
| BITSTREAM-002 | bit order 和 byte order 必须分开声明 |
| MEM-001 | 禁止不安全 pointer punning |
| MEM-002 | alignment 必须显式 |
| BUF-001 | encoder 必须有 worst-case capacity |
| DEC-001 | decoder 必须验证所有长度 |
| DEC-002 | decoder 必须验证所有 offset |
| FP-001 | canonical 必须固定 float/double 精度 |
| FP-003 | canonical build 禁止默认 fast-math |
| ROUND-001 | rounding semantics 必须声明 |
| FMA-001 | FMA policy 必须固定 |
| SPECIAL-001 | NaN/Inf/±0 policy 必须声明 |
| STATE-001 | one-shot/block/chunk/streaming 必须区分 |
| STATE-002 | 重写实现不得擅自改变 reset frequency |
| STATE-005 | 上游正式 streaming/stateful 接口、状态边界和生命周期语义必须等价保留并验证 |
| LOSSLESS-001 | 无损必须 bit-exact reconstruction |
| LOSSY-001 | 有损必须定义 error mode |
| LOSSY-VAL-001 | 必须验证正式误差约束 |
| SIMD-001 | SIMD 不得改变算法语义 |
| SIMD-005 | 上游受支持的 SIMD variant 必须复现，并通过 forced-path、tail、unaligned、fallback 和 differential 验证 |
| THREAD-001 | 线程数必须记录 |
| THREAD-005 | 上游正式并行模式、并发 handle 和线程安全契约必须等价保留并验证 |
| ABI-001 | 独立重写 API 必须通过接口检查，且禁止实现 `tscb_adapter_v1` |
| ACCT-001 | FinalBits 及组件必须与物理输出闭合 |
| TEST-001 | reference implementation 必须保留 |
| TEST-002 | 必须 golden + differential |
| TEST-003 | decoder 必须测试 malformed input 与资源边界 |
| TEST-004 | 无损必须 bit-exact round-trip |
| TEST-005 | 有损必须验证正式 error contract |
| TEST-006 | CROSS_DECODE/BYTE_IDENTICAL 必须双向交叉解码 |
| TEST-007 | G6 发布前必须通过独立 Qualification Preflight |
| TEST-008 | 兼容 datasets 必须在相同输入和配置下完成原实现、canonical 与 optimized 对照验证 |
| SAN-001 | canonical 必须通过 ASan |
| SAN-002 | canonical 必须通过 UBSan |
| BENCH-001 | 压缩指标必须从完整 FinalBits 派生 |
| BENCH-002 | encode/decode throughput 分开报告 |
| BENCH-003 | compiler/ISA/thread 必须记录 |
| BENCH-004 | FORMAL 必须满足统一 warmup/repetition/最短时间 |
| LIC-001 | 文件/片段级许可证、来源和 redistribution 状态必须可追踪 |
| REPRO-001 | 必须保存并验证源码、环境、命令和产物 digest |

---

# Appendix B：开发者开始实现前的 34 个问题

开发者在写第一行 C/C++ kernel 前，必须能够回答：

1. 该逻辑条目是否已与重复仓库、binding、wrapper 和已有 C/C++ core 去重？
2. `algorithm_id`、`implementation_id` 和 ObjectLevel 是什么？
3. 原始算法的唯一可信来源及实际 source closure 是什么？
4. 当前参考代码对应哪个 commit/version/target，closure 与补丁 hash 是什么？
5. 每个源文件、片段、submodule、生成代码和依赖的许可证是什么？
6. PortMethod 和 CompatibilityTarget 是什么？
7. 算法是有损还是无损，primitive、codec、pipeline 还是 system？
8. 输入数据真实 dtype、shape、stride、alignment 和 ownership 是什么？
9. 数组是 row-major、column-major 还是非连续 view？
10. 参考语言及其版本、build profile 和目标架构是什么？
11. 参考语言整数是否可能 overflow，其原始语义是什么？
12. shift、division、remainder、narrowing 和 conversion 的原始语义是什么？
13. predictor 的边界样本如何处理？
14. block 之间是否共享状态，reset/finalize 的语义是什么？
15. dictionary/model 是否跨 block，其字节如何计费？
16. bitstream byte order 和 bit order 是什么？
17. frame/format/implementation/standalone API version 分别是什么？
18. rounding、浮点精度和 FMA policy 是什么？
19. NaN/Inf/signed zero/subnormal 怎么处理？
20. timestamp/value 是否共享 codeword 或状态，能否合法拆分？
21. correctness oracle、golden 和 differential 观测点是什么？
22. 是否要求 cross-decode 或 byte-identical，如何验证？
23. 从 public API、build flags、文档、CI、测试和可达代码中识别出了哪些原生 capability，每项的稳定 capability ID 和证据是什么？
24. 每项 capability 为什么被分类为 `REQUIRED_PARITY`、`OPTIONAL_OPTIMIZATION`、`UNAVAILABLE_WITH_WAIVER` 或 `NOT_APPLICABLE`，由谁审核？
25. 上游 streaming/stateful 的 fragmentation、flush/finalize、reset/reuse、backpressure、状态隔离和内存上界如何等价验证？
26. 上游 SIMD、多线程、GPU/accelerator、random-access/query 等正式能力如何 forced-path 验路，并证明未静默 fallback？
27. 独立 public API、manifest、config 和 capability 如何声明，并如何证明未包含接入代码？
28. compress bound、safe overread、输入不可修改和 repeated finalize 如何测试？
29. SerializedBits 各组件、ExternalSideInformationBits 和 FinalBits 如何闭合？
30. CORE/PIPELINE/E2E 及参考实现 native timing 的实际时间边界是什么？
31. learned/model codec 如何防止训练数据泄漏，训练成本如何报告？
32. 哪些平台必须验证，缺失平台是否有有效 WAIVER；可复现构建需要哪些 source/environment/command/artifact digest？
33. `datasets/` 中哪些数据与算法输入域兼容，如何证明原始实现和重写实现使用了相同 canonical input、参数和状态边界；使用 UCR 时如何处理标签、TRAIN/TEST、逐行 case 和 adjusted variant？
34. 所有 `REQUIRED_PARITY` 是否均已通过，waiver 是否有效，以及哪些完整证据齐全后才能声明该 C/C++ 重写 `REWRITE_DONE`？

如果这些问题有任何一个无法回答，应优先完成相应 Gate 和 Algorithm Contract，而不是继续编码。

---

# Appendix C：推荐团队口令

项目中建议形成统一工程习惯：

> **没有 Contract，不移植。**\
> **没有 Source Closure，不判定语言。**\
> **没有 Capability Inventory，不宣称功能完整。**\
> **上游正式 SIMD、多线程或 streaming 能力未通过，不宣称 FULL_PARITY。**\
> **没有 Oracle，不优化。**\
> **没有 Differential Test，不宣称等价。**\
> **没有真实数据集的 Source-vs-Rewrite 对照，不宣称重写完善。**\
> **没有 Sanitizer，不宣称安全。**\
> **没有独立 API Preflight，不发布重写产物。**\
> **没有 FinalBits 闭合，不报告压缩率。**\
> **没有环境记录，不比较性能。**\
> **没有许可证记录，不合并源码。**
> **没有完成 G0-G6，不宣称 REWRITE_DONE。**\
> **重写任务不做接入；接入必须另开任务。**
