# TSBench 4.0：时序压缩标准测试协议与 Python 框架实施计划

版本：4.0。设计日期：2026-10-12；目标修订：2026-10-15。**默认目标为codec原生表现，默认边界为`native_core / prepared / natural`：Python负责准备、调度、资格与收集，C/C++ driver直接调用真实codec并在内部循环和计时。** 通用C1／RW `native_api`及完整对象`object_memory / independent_object / natural`保留为辅助目标。§1–§13已按此目标统一修订；§14分别保留历史实施事实与新原生结果，旧对象结果不变成原生结果。首批原生路径已实现，完整suite372项通过；六组新正式运行完成2534／2534 trial，范围与限制见§14.17、[原生结果](docs/native_results/README.md)及[独立证据索引](docs/native_evidence.json)。

目标论文：**各类时序压缩算法在各类时序数据上的标准测试**。主表比较同任务、同dtype／布局／有效数据量下codec的完整必要输出与真实原生编解码时间；正确性与质量在计时外验证并决定结果有效性。框架wire、适配开销和对象延迟另作辅助结果。“标准”指公开、可执行、可复现的协议，结论限定于声明输入、方法、质量、测量层和资源条件。

本计划重新组织研究问题、对象协议、产物接口、执行模型和实施顺序。保留已移植／重写 codec 的算法源码资产，用独立 Python 包从零构建 benchmark。计划版本 4.0、未来 Python 包版本、wire 格式版本、现有 C/RW ABI 版本分别管理。本文 §1–§13 定义设计与研究要求；新实现与实测证据在 §14 单独记录。设计示例数值不是测量结果，不能代替 raw observations。

## 1. 重新阅读得到的研究定位

### 1.1 本轮依据与阅读边界

先重新联网检索、获取原文和阅读，再编写本文。本轮六篇论文全文共 **85 页**；Gorilla 另做定向重读。开源项目按具名文件阅读全文或指定函数逐行阅读，具体范围、版本、SHA-256 和限制见 [V4 阅读索引](docs/research/README.md)。没有运行外部 benchmark，也没有重现论文中的性能数字。

| 来源 | 本轮范围 | 对 V4 的直接作用 |
|---|---|---|
| [TerseTS，EDBT 2026 demo](https://openproceedings.org/2026/conf/edbt/paper-286.pdf) | 4页全文；官方README、Python binding及关键源码 | 统一API、多方法、pipeline和Pareto已有先例；明确论文差异 |
| [FCBench，PVLDB 2024](https://www.vldb.org/pvldb/vol17/p1418-tao.pdf) | 14页全文 | 分开压缩、查询、profiling；跨域数据、GPU传输、失败覆盖 |
| [ALP，SIGMOD 2024作者版](https://ir.cwi.nl/pub/33334/33334.pdf) | 14页全文；官方用户数据与benchmark文档、驱动 | 原生精度、scalar/SIMD、L1微测量与完整COMP边界 |
| [Sprintz，arXiv v1](https://arxiv.org/pdf/1808.02515v1) | 23页全文 | 整数/MTS、量化和拼接、在线状态、内部块和SIMD路径 |
| [cuSZ，arXiv v1](https://arxiv.org/pdf/2007.09625v1) | 13页全文 | GPU产生的数据、kernel/D2H/overall、误差语义和真实适用维度 |
| [Benchmarking Crimes，arXiv v1](https://arxiv.org/pdf/1801.02381v1) | 17页全文，含附录 | 微／宏边界、适用范围、变异和聚合；不外推其安全领域调查 |
| lzbench、pyperf、Google Benchmark | 固定commit的具名文档、runner或相关函数，范围见笔记 | 简洁路径、计时循环、worker预热、原始分布、独立profiling |
| nvCOMP官方样例与其固定NVBench依赖 | 生命周期、计时函数、实际依赖commit | completion、逐chunk状态、hardware DE、cache cold和batch hot |

TerseTS 已提供 Zig/C API 与 Python 等绑定、多类无损/有损方案、中间表示与多阶段组合、RMSE/空间/时间分析。V4 不以这些已有功能单独主张创新。FCBench 的方法数也需限定作者口径：正文称13种方法，表格另展开实现/组合变体；本项目的36个注册key同样不能直接当36种独立算法。

2026-10-15补读本地`/home/fzg/PycharmProjects/lzbench/bench/lzbench.cpp`的`print_speed`、`print_stats`和`lzbench_process_single_codec`：内部原生循环、prepared workspace、FASTEST／median和十进制MB/s有不同含义。本项目默认median／IQR，不照搬最快值或其输出复用／验证覆盖。本地HEAD为`3d22c4115e5e99069c30bef00aa4ec59aecd2f66`，runner SHA-256为`5f19e92fd9855052dad4bac4004092c8d13627c861441aec8dfb09dfc42f86bf`；固定来源与各codec输出分类见[原生参考笔记](docs/research/native_reference_notes.md)，既有来源对照见[专项核查](docs/research/lzbench_comparison_20261015.md)，本次未运行lzbench。本地项目及研究索引尚未定位可核验TFBench源码／论文，故不声称已阅读或采纳其细节。

ALP 论文的300K内循环只测一个L1驻留vector，第一阶段row-group采样不在该微测量内；完整COMP才包含。本轮固定源码的Release驱动为30K，论文实验与该代码快照分别记录。nvCOMP样例的device event排除输入传输、配置和分配；NVBench的cold仍预热且主要处理L2缓存。它们分别回答具体问题，不能拼成一种通用“压缩时间”。

### 1.2 论文需要回答的五个问题

| RQ | 问题 | 需要的实验，而非仅有接口 |
|---|---|---|
| RQ1 | 哪些数据特征改变算法适用性和条件排名？ | 跨独立来源、dtype、长度、UTS/MTS、规则/不规则时间的空间/速度/覆盖 |
| RQ2 | codec必要输出与接入成本怎样改变方案选择？ | codec完整恢复输出为主；实际codec／ABI envelope／framework wire逐层分解；模型／索引不漏计 |
| RQ3 | 计时边界和资源环境会怎样改变结论？ | native_core主表；native_api／object辅助，prepared／fresh_request分列；真实ISA／线程／GPU边界 |
| RQ4 | 同一质量目标下有损方案如何取舍？ | 原始域质量阶梯、约束违例、rate-quality-speed前沿；明确保证类别 |
| RQ5 | 结论有多少来自实现、输入变换或调参？ | 原版/移植/重写身份；必要的布局、分块、默认参数与开发集选择消融 |

拟验证的贡献是：以相同typed输入和真实原生计时比较codec，以完整必要输出避免漏计恢复信息，以对象路径解释接入成本，并保留失败覆盖与分层实验。协议的价值要通过对照和消融证明；提交前继续核查相关工作，不预设“首个”或唯一总体排名。

## 2. 从现有 codec 资产起步

### 2.1 本轮重新核对的事实

[codec与开源阅读清单](docs/research/codecs_and_open_source.md)核对36个真实codec key、4个框架oracle及 `lz77 → deflate-zlib` 别名。32个key走 `tscb_*` C ABI，ABBA/fABBA/DeepZip/DZip四个走 `rw_*` ABI。这是 2026-10-12 的实施前盘点：当时 build 目录不存在、登记共享库均缺失；2026-10-13 已通过新配方重建，见 §14。

本轮还核验六个无损重写包的46个冻结文件、四个completed rewrite包的1215个冻结文件，以及17个DeepZip模型的实际SHA-256，未发现缺失或漂移。**静态哈希一致仅证明这些冻结资产未漂移**；动态依赖、构建、安全、恢复与新协议性能仍需实际验证。

| 继续使用的资产 | 新框架重新编写的内容 |
|---|---|
| vendor/native codec、无损重写包、LZSS C++实现 | Python配置、对象加载、registry、两种ABI bridge |
| completed rewrite源码、必要模型、来源/许可与补丁 | typed envelope、方案组合、独立decode、质量验证 |
| 真实构建命令和依赖信息 | 独立build helper、worker、计时、缓存、JSONL与报告 |
| 算法原有block/state/Finish语义 | 实验矩阵、统计、环境与复现入口 |

不导入旧 `tscompbench` Python包。构建配方可以提取其真实编译命令，但新流程使用新输出与新验证记录。旧移植完成证据用于来源说明，不能替代新接口正确性。oracle不进入算法性能表；新写真正的raw-store方案作为空间与调用路径基线。

### 2.2 首批接入与扩充顺序

| 批次 | 成员 | 验证目的 |
|---|---|---|
| 最小原生闭环 | raw-store、zstd-frame、lz4-frame、snappy-raw | 直接codec入口、C++内部循环、完整encode+Finish／decode、prepared／fresh与逐次验证；对象路径保留 |
| 浮点与两ABI | chimp128、alp-rd、ABBA | 源域拒绝、block/forced scheme、RW frame与经验质量 |
| 误差与SIMD | serf-qt、zfp-accuracy-1d、sprintz-fire | ABS原始域验证、特殊值/tail、真实整数/ISA路径 |
| 其余保留资产 | 按能力分批，含fABBA、DeepZip、DZip、SIMDComp | 模型、线程、词表、primitive及格式限制 |

2026-10-12盘点时，`alp` / `alp-rd` 为forced decimal / forced RD；2026-10-17按用户要求替换为冻结safe-v1的adaptive ALP / forced RD，新接入范围与验证单列于[ALP接入报告](docs/alp_integration/README.md)，不继承旧正式运行身份。SIMDComp目前是primitive；DeepZip词表0..3不代表一般浮点域；fABBA binding当前固定1线程；DZip存在持久Eigen workers。GPU从官方可构建实现另行接入，当前保留资产没有已接入GPU成员。退出或未完成方法另走新接入，不恢复来凑数量。

## 3. 先确定比较对象，再生成实验矩阵

### 3.1 原始对象与恢复任务

canonical对象由具名组件构成：V可以是float32/64或整数，T可以是int64或声明的其他原生类型，validity可以是有明示语义的mask。保留shape、字节序、C/F顺序、列/通道、时间单位、采样与series边界。第一版支持UTS、同步MTS；异步/ragged保持独立series和关联关系，不静默填成同步矩阵。

| task | 必须恢复的内容 | 原始字节分母 |
|---|---|---|
| values | 声明的V；若声明validity也必须恢复mask | 所需V与mask的canonical bytes |
| timestamps | 声明的T与其顺序 | T的canonical bytes |
| records | 所有声明的T/V/mask及schema语义 | T/V/mask bytes之和 |
| component | 明示且固定的typed primitive输入 | 真正有效typed bytes，不含ABI头／padding，原始对象及实际ABI输入身份另存 |

`logical_input_bytes`是当前恢复任务真正有效的数据量，不含ABI envelope、对齐padding、scratch或逐列重复的共享T。默认bitwise任务保留masked位置的V，故这些V仍在分母；只恢复valid值是另一个显式任务。Gorilla records共享T只计一次，实际pair字节另列诊断。native_core／native_api比较固定任务、dtype、shape、layout和有效bytes，不能由实现输入扩张提高压缩倍数或吞吐。

十种整型/浮点dtype是对象表示目标，不要求所有codec都支持。默认bitwise任务连masked位置的V bits也保留；只恢复valid位置属于另一个明确任务，声明无效位置填充值与mask政策。有损质量只在声明的valid/finite位置计算，T、mask及特殊值恢复规则另验证。

CSV加载指定目标dtype、列、时间解析、单位与缺失规则，保存源文件hash和解析规则。比较从声明的canonical对象开始，不能把数值恢复称原CSV字符恢复。排序、去重、插值、降精度、归一化、量化、widening、跨series拼接必须显式声明。

### 3.2 两种输入身份与三种 chunk

- `raw_object_id`：当前task投影后的canonical内容和恢复语义。原始文件/解析lineage另存；不同合法编码表示仍共享这个原始对象。
- `codec_input_id`：实际送进codec的内容、dtype、shape和layout；由方案产生，可能是byte view、逐列buffer或量化整数。
- `transform_id`：变换实现、参数与版本；没有变换时为identity。逆变换所需信息存进产物。

| 层次 | 含义 | 处理方式 |
|---|---|---|
| codec_block | 原算法预测/XOR/packing/Huffman内部块 | 方法参数与状态，不强制算法间一致 |
| workload_chunk | 需要独立恢复、随机访问、并行或超显存分段的片段 | 明确跨chunk状态、索引、顺序和完整成本 |
| timing_batch | 一个计时sample重复逻辑operation的次数 | 只提高计时粒度，不改变对象、不增加统计独立样本 |

默认整个选定对象是一次独立operation。共同外部分片实验固定chunk几何；按方法选择外部分片属于另一部署策略，要报告开发预算和选择政策。不能把小native block当作外部独立片段，也不能为计时拼接更多数据使压缩更有利。

### 3.3 公平条件与测量层

默认原生比较固定raw_object／恢复任务、质量、dtype、shape、layout、逻辑有效bytes、外部分片、边界、生命周期及资源。实际ABI输入身份仍保存，byte view或ABI元数据不改变逻辑分母。

- `native_core`：原生driver直接调用具名codec算法API，主表仅纳入该层真实入口和完整算法工作。
- `native_api`：driver调用完整C1／RW接口，包含shim内部转换／扫描／解析／分配，作为辅助；同为C++不代表与core起止相同。
- `object_memory`：同原始任务和质量，比较完整wire与全部对象处理时间；合法转换／组合成本全部计入辅助表。
- 环境／SIMD／线程消融固定任务与受控因素；GPU明确驻留与completion，不以CPU／GPU线程数直接对齐。

运行前保留全部请求case。数据域、真实core入口、输出完整性和生命周期分别检查；core未接入或无法核实必要输出时明示unsupported／null，不静默fallback为API或对象计时。报告给请求／可执行case、计划／完成trial和全部原因。共同有效子集需标条件，不称原计划总体。

## 4. 一个独立 Python 包，三个清楚的职责

模块结构、流程及计时边界见[框架图](docs/diagrams/README.md)（2026-10-15修订）。首批原生默认分支已实现，实际支持范围见§14.17；历史对象／GPU路径保持原身份。

```text
benchmark/
  pyproject.toml                 独立包；Python >=3.11、NumPy为核心依赖
  src/tsbench/
    cli.py / config.py           build、inspect、run、report、profile；一份TOML
    data.py                      canonical对象、窗口、lineage和内容身份
    registry.py / build.py       capability card、factory、真实配方和build cache
    schemes.py / artifact.py     对象方案、有限channel/chunk组合、typed wire
    validate.py                  bitwise、原始域质量、输入不变性
    runner.py / worker.py        矩阵、资格缓存、顺序调度、隔离与恢复
    records.py / report.py       JSONL、终态、描述与可选研究分析
    bridges/                    c_abi_v1.py、rw_abi_v1.py
    executors/                  CPU对象与原生driver调度；GPU／pool独立入口
    native/                     C/C++ batch driver；真实core入口按成员逐项接入
  tests/                        有意义的协议与真实adapter测试
  examples/                     小型配置；论文配置按RQ另列
```

新包从声明的asset root读取现有native源码/模型，不依赖旧控制面。Python最低版本与论文锁定版本分开；GPU依赖选与其SDK实际兼容的解释器。统计/绘图、Parquet、GPU SDK属于extras，核心不要求全装。无需通用DAG调度、远程服务或dashboard才能运行。

三个职责是：binding明确真实codec接口／格式；Python控制面负责数据／资格／隔离／调度／记录；原生driver落实内部循环、状态reset、原生时钟及真实输出。scheme／artifact继续承担辅助对象目标和计时外恢复包装，框架JSON／hash／来源不进入原生主计时和codec大小。以下ObjectScheme协议保留为对象辅助接口，不能代替core入口；stream／query不以空壳冒称支持。

```python
from dataclasses import dataclass
from typing import Mapping, Protocol
import numpy as np

@dataclass(frozen=True)
class TimeSeriesObject:
    components: Mapping[str, np.ndarray]
    schema: Mapping[str, object]

@dataclass(frozen=True)
class EncodedObject:
    wire: bytes  # descriptor、payload、必要依赖已序列化

    @property
    def stored_bytes(self) -> int:
        return len(self.wire)

class ObjectScheme(Protocol):
    # 内部包含本次对象所需create/reset/分配/变换/Finish/packing/close。
    def encode_once(self, obj: TimeSeriesObject) -> EncodedObject: ...

class DecoderRegistry(Protocol):
    # 从wire配置新decoder；只依赖已安装解码实现及已计费依赖。
    # 返回对象在本次decoder关闭后仍拥有有效独立存储。
    def decode_once(self, obj: EncodedObject) -> TimeSeriesObject: ...
```

dataclass冻结字段不等于冻结NumPy buffer。loader持有可信原始fingerprint；bridge保证不原地改输入，确需in-place时在encode段内复制scratch。每trial在计时外核对原始fingerprint，防止native写坏输入后拿同一被污染数组验证。encoder的运行时配置不能成为decoder免费的恢复信息。

### 4.1 两种 native bridge 的实施要求

| 接口 | Python bridge必须实现 |
|---|---|
| C ABI v1 | ctypes结构size/version、dtype/rank/shape/stride/capacity/ownership；create、bound、compress、需要时finalize、decompress、destroy及真实状态/错误复制 |
| RW ABI v1 | RwConfig布局与model字符串存活；bound/encode/decode、返回值/used bytes/容量、frame参数与shape恢复 |

C1的finalize行为逐codec核实：可能补写tail或重写输出，不能机械追加任意返回buffer。容量不足后native状态可能已改变，按真实API处理，必要时reset并完整重编码。状态返回成功仍须完整恢复验证。32个C1入口不是一个匿名通用压缩函数；小bridge按真实格式落实Finish与decoder配置。

RW frame若已含必要模型／参数只计一次；Python增加的列目录／hash另记账。C1 payload未必自包含，shape／tail／参数等必要信息须实际核实和计费，不能把生产payload直接改名为codec完整输出。C1／RW driver只提供native_api；core须直接算法入口。准确入口依据本仓库 [C头文件](native/include/tscb_adapter_v1.h) 和 [RW头文件](adapters/completed_rewrites/native/binding.hpp)。

## 5. codec必要输出与框架对象分开记账

### 5.1 两种产物、逐层账单与独立恢复

主大小`codec_complete_bytes`必须来自实际可核验输出，包括codec恢复所必需的header、参数、字典／模型、索引、exceptions、尾部及finalize数据。不能因它叫metadata就扣除。已安装decoder程序不计压缩数据，输入相关模型／字典属于数据依赖。standalone默认包含完整依赖；共享模式另冻结scope、集合和依赖hash，同时给未摊销与scope只计一次的成本。不能真正移出内嵌模型时不虚构免费共享版本。

辅助对象目标继续采用typed envelope：prefix→canonical JSON descriptor→payload／dependency区。wire2的dtype／shape／roles、来源、hash、chunk／channel目录和必要参数支持独立恢复，但整个wire不是codec原生输出。原生实验可在计时外保存该验证包装：

| 范围／字段 | 定义 |
|---|---|
| `native_output_bytes` | 被测API实际返回used bytes，含该API真实输出的shim frame；未必等于codec必要输出 |
| `codec_complete_bytes` | 经格式审核的完整codec恢复输出及必要依赖；用于主表压缩倍数／bits |
| `abi_envelope_bytes` | 真实格式区间识别出的纯适配／传输封装，辅助记录，禁止估计扣除 |
| `framework_bytes`／`stored_bytes` | 框架记录／完整typed wire成本，仅对象辅助范围 |
| `output_accounting_status` | 格式、区间与依赖完整性证据；不可核实则空间主指标null及原因 |

记录每份真实输出的互斥字节区间、used长度、hash、依赖及format版本。必要header／模型已在输出时不重复收费；capacity、scratch、对齐预留和原输入不计压缩大小。C1／RW wrapper无法剥离或必要参数未实际保存时，不以`payload - guessed_header`制造codec大小。API时钟可作诊断，大小不完整者不进主Pareto。

独立恢复只接收真实输出、必要格式参数、已计费依赖及安装decoder，不拿original、encoder context或原配置模板。公共固定任务schema若是调用接口前提须明确scope；数据相关恢复信息不作免费参数。typed wire的shape／长度限制、校验、资源上限继续适用于验证产物；wire1历史兼容不赋予wire2完整性保证。

### 5.2 默认主指标与辅助指标

```text
logical_input_bytes       = task真正有效输入bytes（不含ABI头／padding／重复共享T）
compression_ratio         = logical_input_bytes / codec_complete_bytes
bits_per_value            = 8 * codec_complete_bytes / 输入V标量数
bits_per_timestamp        = 8 * codec_complete_bytes / 输入T数量
native_encode_MiB_s       = logical_input_bytes * loops * 1e9 / native_encode_total_ns / 2**20
native_decode_MiB_s       = restored_logical_bytes * loops * 1e9 / native_decode_total_ns / 2**20
object_compression_ratio  = task_raw_bytes / 完整wire及必要外部依赖bytes
object_encode_MiB_s       = task_raw_bytes * 1e9 / object_encode_ns / 2**20
object_decode_MiB_s       = task_raw_bytes * 1e9 / object_decode_ns / 2**20
```

压缩倍数标清`raw/compressed`方向；`stored_fraction=compressed/raw`可辅助显示。恢复后逻辑bytes须与输入一致；质量／恢复失败时间仅诊断。timestamp-only bits/value为null，MTS value数是标量数而非行数。records bits/value若含T／mask成本须明示，shared T输入只计一次；组合输出及必要目录全部计费，不能称某一个成员的原生timestamp算法。空输入或零时间的比例／吞吐为null及原因。文件大小、实际ABI输入、H2D／D2H copied bytes另存；传输带宽不扩大codec吞吐分母。

raw-store同时保留真实原生memory-copy参考与typed对象参考，二者分层，不把裸bytes基准和对象wire混称相同压缩格式。

## 6. 时间边界、运行时与缓存分别定义

### 6.1 原生默认与辅助边界

| boundary | 编码段 | 解码段／用途 |
|---|---|---|
| `native_core`（默认CPU） | driver直接codec API的完整采样／建模／编码／finish；不含shim和Python | 对应完整codec decode，必要格式解析与安全检查政策明确；无真实入口则unsupported |
| `native_api`（辅助） | driver调用完整C1／RW reset／compress／必要finalize；内部转换／扫描／分配照实计入 | 完整ABI decode并等输出可用，不称pure algorithm |
| `object_memory`（保留辅助） | 对象→create／reset／适配／分配／encode／Finish／wire／关闭 | wire→解析／新decoder／恢复／逆变换／完整对象／关闭；Python wall |
| `device_resident` | 已准备device输入→完整device输出与completion | 完整device恢复；metadata位置、event覆盖和host辅助单列 |
| `host_to_host` | host输入→配置／传输／GPU／完整host输出完成 | host恢复完成的部署边界，不替代CPU原生主表 |
| `gpu_to_host`／`file_end_to_end` | 单列驻留变化或文件读取／解析／写入 | 明确cache／flush／fsync及完成边界 |

native_core也必须包含算法必需采样、在线更新、建模与finish。不是只取一个内核或已有可选timer字段；native_api包含shim开销不能冒称core。模型读取／配置按生命周期真实计账，不免费复用输入相关预计算结果。

### 6.2 生命周期、原生循环和缓存

默认`native_core / prepared / natural`。Python在计时外解析数据、配置、资格、加载库、准备输入并保存记录；driver复用合法context／buffer容量，**每次operation独立reset预测／字典／在线状态**。reset及输入相关算法准备计入原生段，不继承前一输入压缩历史。prepare／bound／workspace建立／close另报范围和耗时；API内部仍有的分配不能声称已消除。初版直接core已实现raw-store／Zstd／LZ4-frame／Snappy；其余codec请求保留core unsupported，按真实实现逐项扩展。

`fresh_request`另列首次请求成本：原生计时包含context创建、配置／reset、bound、caller buffer分配、完整操作及context关闭；压缩／恢复产物为计时外逐份验证保留，最终buffer释放在计时外，不称全部产物释放在内的总端到端生命周期。它不含Python调度或进程启动；首次指context／buffer首次使用，不声称cache冷。不能实现prepared安全reset或上述fresh边界的成员拒绝相应组合。辅助object保留`independent_object`；fresh-process（spawn／import／IPC）及stream另设任务。

原生driver使用monotonic高分辨率wall时钟（如`std::chrono::steady_clock`），返回clock／分辨率、encode与decode batch totals、真实loops和输出数。Python一次调用batch，循环和起止在C/C++内，没有Python重复调用循环。内部线程／异步工作完成才停表。默认固定`native_loops=8`，记录实际预算；有界校准只调loops，不改输入／算法参数。一个batch平均是一个round样本，loops不是独立统计样本。

每个被计时operation的真实输出及每份恢复结果都要在计时外验证；不覆盖buffer只验证最后一份。以`native_batch_memory_mb`约束保留量，超限减loops或明确拒绝并记录原因。可将有界batch拆成多个真实计时段、在段外验证并汇总ns，必须记录段数／loops／覆盖。禁止从实测减空调用、raw-store或估计封装开销。

cache默认natural，不保证hot或cold；预热、first-touch、输出复用和干预政策进manifest，fresh进程不保证共享cache冷。decode使用本次真实产物与独立逻辑decoder状态；保存后读取另标origin。最终质量／bitwise、输入fingerprint／hash、实验JSON与落盘均在原生计时外。对象模式保留其原先descriptor／checksum／copy真实范围，不能回算native时间。

```text
Python: parse → capability／qualification → prepare actual input／driver → one batch call
C++:   repeat independent reset → time complete encode+finish → retain each real output
C++:   independent decode state → time full decode → retain each restored output
Outside timers: verify every output／restored + input unchanged + exact byte accounting
Python: append original native totals／loops／status → scope-aware read-only report
```

首批入口已按此契约实现，实际范围和372项测试见§14.17；性能结论仍需新source／build／driver身份及正式run。

### 6.3 GPU 的 completion 扩展

现有host C ABI不接收device指针。GPU executor与插件显式实现prepare、submit、complete、device event及host materialize；不要求CPU成员具备这些方法。

```python
def measure_async_completed(operation, input_view):
    operation.quiesce()  # 排空上次工作，不让它污染本次时间
    t0 = perf_counter_ns()
    pending = operation.submit(input_view)
    result = pending.complete()  # 所有相关工作结束，status/尺寸/输出就绪
    return result, perf_counter_ns() - t0
```

需要在submit内创建manager/分配/传输的成本按该boundary计入；steady预分配另命名。independent_object的complete还需在停止wall前关闭本次manager、释放非输出scratch并完成必要teardown，与CPU生命周期一致；输出存储转交给返回产物的owner，不能提前释放。reusable生命周期才允许跨请求保留manager/scratch，并另报setup/close。独立decode从wire与已计费依赖重建配置，不借encoder CompressionConfig。CUDA events只包选定stream及已建立依赖覆盖的工作，读elapsed前等待event完成；hidden streams必须纳入completion保证，无法覆盖时该device-event指标为null及原因。

记录CUDA/hardware DE实际backend、stream数、chunk数、pinned/pageable、scratch/输出分配、driver/runtime/library版本和host辅助资源。异步launch成功不代表逐chunk成功；完成后的status和实际恢复必须核对。库的checksum/受检查与unchecked选项进入implementation参数，不静默混同。

device event是设备细分指标；host_to_host的主指标是完成wall。重叠传输与计算直接测完成时间，不能简单相加各段或拼接各段最好值。nvCOMP样例commit、其固定NVBench commit和所安装nvCOMP二进制版本分别记录。NVBench hot批均值与cold L2处理不改名为独立请求/新进程时间。

## 7. 运行器：资格只检查变化的东西

### 7.1 两种缓存及其范围

| 缓存 | 必要键 | 实际省掉的工作 |
|---|---|---|
| implementation check | binary/相关依赖、bridge/wire、参数、backend/有效资源、validator与suite版本 | 已完成的小型能力/边界suite和其独立恢复 |
| exact-input check | 上述键+raw_object/实际输入/变换/partition身份+恢复与质量目标 | 该确切输入的predicate检查与一次wire-only新进程恢复 |

suite按宣称能力测试empty/tail、支持dtype、源域拒绝、状态/Finish及必要native安全项。每codec接入CI独立完成，不让全部资产都通过后才能运行一个方法。固定dtype/shape的通过不能证明新内容合法；Chimp/Elf等源域拒绝以实际内容判定。

预检产生真实codec输出及必要恢复信息，另启动decoder进程；只拿产物、安装decoder及已计费依赖，不拿original或encoder context。对象目标仍作wire-only恢复。旧输入资格不授予新输入；native正式round仍编码自己的输入，用独立逻辑decoder状态恢复，计时外验证每份真实输出。边界／生命周期／driver和输出账单进入资格身份，命中缓存不跳过正式操作。

报告样式/统计代码变化只影响analysis identity。binary、相关bridge、validator、实际backend/runtime或依赖变化仅失效受影响缓存；不冻结整个Python控制面。缓存保留PASS范围与证据，timeout/OOM/缺库等瞬时失败不缓存成永久不支持。

### 7.2 worker 和 round 的具体生命周期

每个 `(session, method, resource_profile)` 使用独立worker进程，避免native崩溃影响主进程。default资源profile内主计时顺序运行：即使存在多个待命worker，同一时刻只有一个计时任务。大型矩阵分组启动/关闭worker，控制待命内存；策略写入resolved记录。

一个session顺序：加载实际库／数据 → 未命中资格 → 准备原生入口／workspace → 有界校准／固定loops及预热 → reset逻辑状态 → 已保存schedule的正式round → 逐产物计时外验证／原始记录 → 关闭workspace／worker。对象目标预热session继续丢弃。下一session新建进程。临时资格/校准进程已预热，不能当作测量worker已经预热。

在会创建pool、初始化设备或first-touch数据之前实施resource profile的affinity、线程环境和NUMA政策，并核对有效值。数据按当前比较block加载/预热，不要求所有catalog同时驻留各worker。固定预热次数/对象政策在相应输入下执行，相关状态丢弃。

```python
import random

def make_schedule(method_ids, sessions, rounds, seed):
    rng = random.Random(seed)
    for session in range(sessions):
        for round_id in range(rounds):
            order = list(method_ids)
            rng.shuffle(order)
            for sequence, method_id in enumerate(order):
                yield session, round_id, sequence, method_id
```

这段只为一个固定raw_object/task/质量/边界/profile的比较block生成方法顺序；实际runner将它展开成完整case_id并保存block与schedule，不跨不同对象/资源条件错误配对。存schedule本身及生成器版本，避免只存seed却因Python/调度实现变化无法复现。

原生路径从首轮使用C/C++ batch driver；真实loops／输出数／验证覆盖／reset范围遵守§6.2，encode／decode totals分开保存。对象路径保留loops=1和Python wall，过短告警。校准不改输入或算法参数，不能把包含verifier的Python循环冒充native batch；prepared／fresh_request分别生成case与schedule。

工程起步为1session×7rounds、每worker2个warmup objects；这是可修改默认，不是科学充分性阈值。论文pilot按变异、独立层次与预算决定更多sessions/rounds，确认后固定；不根据赢家追加到显著。

### 7.3 真失败、超时和恢复

parent先写planned/started事件，worker返回终态；被native杀死仍由parent补crash/timeout等。CPU/GPU任务都设置具名timeout和可实施的内存限制，能力不足的平台报告限制未实施。SIGKILL单独不能证明OOM，只有错误码、OS/cgroup或设备证据才标oom，否则保留signal和未知原因。

终态分为 `ok / unsupported / unavailable / error / crash / timeout / oom / not_run`，另有stage/reason，例如encode.finalize、decode、validation、quality_violation、budget_exhausted。unsupported描述合法域限制；unavailable描述库/ISA/设备无法取得。error的已测时间只作诊断，不参与性能摘要；恢复未通过不能写ok。

resume补尚未完成项；retry增加attempt，不覆盖旧失败。论文不得只留成功attempt作主结果，retry政策事前声明。保留截断JSONL尾行及标记，在可确认有效前缀后恢复，不能假装整run已完成。预算耗尽的计划项仍有not_run终态和原因。

GPU异常/timeout后由executor清理failed context及其拥有的工作/资源，并核对该设备可继续使用；新worker的quiesce不能证明上一失败context已经干净。无法确认时停止该设备session，余项记录not_run及device_recovery_unconfirmed；不自动重置影响其他任务的整设备。

代表/失败wire按hash保存，失败产物有真实内容时才保存；随机编码可配置更多保留比例。默认不落盘每个巨大wire，但每trial记录hash与实际长度，stream方法按自己的产物/验证政策另定义。

## 8. 一份配置即可开始

这是修订后的首个native values目标配置，当前CLI与首批core入口已支持；正式结果须另运行取得。`temperature.npy`由使用者准备，示例不暗示已有数据或本机运行成功。npy已有dtype/shape，不隐式转float64。配置省略字段用小型明确默认并在resolved中展开；未知字段/未知参数给具体错误。

```toml
schema = "tsbench.experiment/1"
name = "native-values-pilot"
output = "runs/native-values-pilot"

[[datasets]]
id = "temperature"
format = "npy"
path = "data/temperature.npy"
component = "V"

[[methods]]
id = "raw"
codec = "raw-store"

[[methods]]
id = "zstd-3"
codec = "zstd-frame"
params = { compression_level = 3 }

[[methods]]
id = "lz4-frame"
codec = "lz4-frame"

[[methods]]
id = "snappy-raw"
codec = "snappy-raw"

[task]
kind = "values"
fidelity = "bitwise"
boundary = "native_core"
lifecycle = "prepared"
cache_policy = "natural"

[[profiles]]
id = "cpu-single"
device = "cpu"
native_threads = 1
object_workers = 1

[execution]
sessions = 1
rounds = 7
warmup_objects = 2
seed = 20261012
timeout_s = 120
qualification_cache = true
native_loops = 8
native_warmup_loops = 2
native_batch_memory_mb = 256

[analysis]
summary = "median_iqr"
inference = "none"
```

profile请求与effective资源分开：没有真实thread knob或固定后台workers不匹配时，拒绝该profile或明确放入另一个有效资源层，不能说明后仍进入cpu-single/同预算线程scaling结论。相同profile_id本身不证明实际资源相等；不能填effective_threads=1伪装。`workers`不作为模糊总开关：object_workers表示并发工作负载，测量session进程仍顺序调度。profiling默认关闭，用同一resolved实验另开pass。

```bash
# 首批native入口已实现；旧对象raw不证明原生性能，正式结果须使用新run。
python -m tsbench build zstd-frame lz4-frame snappy-raw
python -m tsbench build-driver
python -m tsbench inspect experiment.toml
python -m tsbench run experiment.toml
python -m tsbench report runs/native-values-pilot
python -m tsbench profile runs/native-values-pilot/manifest.json
```

显式`task.boundary="object_memory"`与`task.lifecycle="independent_object"`保留旧目标；冻结TOML／manifest／raw原字节不改。新配置省略boundary默认native_core；未接入成员保留unsupported，不静默fallback。native_api辅助可选C1／RW真实支持入口；初版只做单组件、无外部分块／transform，RW仅rank1，复合／rank2列目录尚未计费时明确拒绝。

inspect只展开任务／参数、支持与环境信息，不执行正式测量。build固定source/recipe/compiler/flags与产物hash，输出到 `build/tsbench/<build-id>`；资格缓存按内容键保存。无需用户手写额外资格、发布或冻结合同。

## 9. 语料、有损与模型：明确适用总体

### 9.1 三类数据集

| 集合 | 组成 | 用途 |
|---|---|---|
| correctness fixtures | empty/tail/特殊值/溢出/状态/源域边界，含合成 | 验证接入；不用于主性能总体排名 |
| core time-series corpus | 工业IoT、能源、交通、气象环境、生理、业务监测等独立来源 | 时序RQ1–4；保留time axis、实体和原生series边界 |
| extension workloads | 科学field、极长流、symbolic、极端dtype/噪声、cache/通道扫参 | 特定机制/部署问题；明确不是额外独立时序领域 |

先核实当前ETT、PEMS、电力等来源、许可、版本和解析精度。UCR/UEA可作公开扩充，但不默认照搬拼接与插值；科学数组明确空间/时间轴，不把所有连续浮点field都叫时序。

pilot至少覆盖不同性质的少量来源，先让协议成立。论文按source/domain冻结选择规则与权重后确定规模；20–40个具名对象可以作为初步预算估计，不能替代独立来源覆盖，更不作为普通run门槛。

每个窗口保留source/entity、起点、长度、通道、采样规则与seed。可按短窗口、跨cache和长对象形成长度阶梯；不足长度的series不重复/插值补足来凑矩阵。多个同源窗口是嵌套样本。统计domain、dtype、规则/不规则时间、missingness、decimal precision、趋势/噪声等覆盖；数据特征分析放在计时外。

### 9.2 质量任务分开

| fidelity | 验证与可比较条件 |
|---|---|
| bitwise | dtype/shape/order/组件语义和全部bits相同，含NaN payload、Inf和−0；input未被修改 |
| numeric_equivalent | 明示NaN/−0等政策；独立表，不进入bitwise总体 |
| bounded_abs / range_relative / point_relative | 原始域按声明公式验证；requested/effective/actual与特殊值政策全部记录 |
| empirical_quality | 固定开发集参数/质量网格，记录actual max_abs、RMSE等；不称通用点误差保证 |

ABS为max absolute error；range-relative为ε×(max−min)；逐点relative明确zero/near-zero分母政策。验证用足够精度并防整数/浮点溢出，不能简单在原dtype减法；定义浮点容许政策，任何放宽均可见。T、mask和特殊值单独验证。

所有有损任务记录max_abs、RMSE、所用NRMSE/PSNR分母；constant-series、零误差和非有限值的null/∞表达政策明确，JSON不写非标准NaN/Infinity。ABBA/fABBA tolerance不提供通用最大点误差保证，进入经验质量曲线，不能凭参数名进入ABS保证组。

量化后无损的方案按原始对象任务计算误差与完整成本。按预定参数网格展示事后经验Pareto是描述性分析；若选每个测试对象最佳点，标oracle envelope，不能当已部署自动选择器。误差约束违例和不可达到的质量目标仍在矩阵中。

### 9.3 固定算法、外部训练和在线适应

固定算法／参数只按§6.2校准原生loops／计时粒度，不需要development corpus。外部选择codec、level、block、model或研究者调参用独立开发/评价来源、实体或时间段，相关窗口不跨界泄漏。模型seed、开发数据与选择预算在评价前固定。

ALP内部采样、FIRE在线更新必须进入原生编码段；prepared复用workspace不能移出输入相关工作。decoder状态从真实格式恢复。独立对象边界reset遵循真实算法语义，SElf*/Serf-XOR的连续状态不得为并行任意切断。

训练另报数据、时间、硬件/能耗与模型大小；默认压缩请求不包含一次完整训练，但模型加载/推理属于其声明边界。单对象standalone与显式共享scope摊销一起报告，不选择最有利摊销点作唯一结果。DeepZip扩至一般符号/浮点词表映射属于新具名pipeline，映射表/模型和成本全部计入。

## 10. 原始结果与统计，不用失败制造排名

### 10.1 自动生成的最小结果目录

```text
runs/<run-id>/
  manifest.json           输入配置+resolved矩阵/schedule+数据/方法/环境身份
  observations.jsonl      计划/开始/终态及phase；原始时间、验证、失败
  artifacts/              真实codec输出与依赖；对象／验证wire单列
  report/                 描述表、覆盖、可选推断与图
  profile/                另一次资源profiling及其identity
```

用户只维护一个配置。manifest保存确切resolved参数、source/build/bridge/wire/validator/measurement代码身份、相关动态库/模型和环境。Git revision/dirty摘要用于复现，报告代码仅进analysis identity，不把整个checkout内容冻结成执行资格。

```json
{
  "schema": "tsbench.observation/1",
  "phase": "measurement",
  "run_id": "example-only",
  "case_id": "temperature/zstd-3/cpu-single",
  "task": "values",
  "raw_object_id": "sha256:example",
  "codec_input_id": "sha256:example",
  "transform_id": "identity",
  "implementation_id": "sha256:example",
  "profile_id": "cpu-single",
  "boundary": "native_core",
  "lifecycle": "prepared",
  "cache_policy": "natural",
  "session": 0,
  "round": 2,
  "sequence": 1,
  "attempt": 0,
  "loops": 8,
  "status": "ok",
  "stage": "complete",
  "raw_bytes": 8000,
  "codec_input_bytes": 8000,
  "native_output_bytes": 3264,
  "codec_complete_bytes": 3264,
  "output_accounting_status": "verified_complete",
  "native_encode_total_ns": 1200000,
  "native_decode_total_ns": 960000,
  "verification": {"passed": true, "fidelity": "bitwise"}
}
```

这是原生目标schema示例，数字不是实测；实际字段若有兼容别名，须保留明确metric scope。还须记录timer／driver／函数身份、实际loops／子批次／输出数／逐产物验证覆盖、逻辑与实际ABI输入、setup／close与输出账单。旧对象rows的encode_ns／decode_ns／stored_bytes保持原对象语义。其他字段可通过case_id关联manifest，避免重复巨大配置。另存environment identity、实际backend/资源、产物hash、质量与实际模式。失败行同样关联case、attempt、stage/reason和可取得的诊断。warmup/calibration标phase，不能混入measurement统计。

### 10.2 两层报告

默认describe主表给codec必要完整输出bytes、压缩倍数、bits/value及原生encode／decode吞吐、median／IQR、完成／计划数与全部状态；native_core／api、prepared／fresh分表，API与wire／对象结果在辅助表。输出完整性或时钟未取得时主指标null及原因。单次结果仅给实际描述。部分round失败时，成功时间摘要明确标为“成功条件下的性能”，同时显示ok/计划trial数及超时/质量违例等；不能将截掉慢失败轮次的median称总体请求性能。report读取raw可重新生成，不执行codec，不要求infer通过才能看到结果。min可作最好情况辅助，不是唯一主结果；噪声告警保留全部raw，不默默删慢值。

论文infer根据RQ另启，保留重复与数据依赖结构：

```text
测量重复：inner loops → round → worker/process session（按实际设计）
数据采样：window → entity/series → source；domain是声明的分层
交叉条件：method × task/object × resource profile/environment × session block
```

这些不是一条严格嵌套链：worker/session可跨多个对象，同源数据可在多个环境重复；environment通常是固定比较条件。重采样保留实际配对、嵌套与交叉依赖，不把循环、同源窗口或每台机器当新增独立数据源。

固定数据上的噪声效果用相同session/round设计的成对差值或time ratio，在实际独立层次重采样。跨语料推断先取得对象摘要，再按source/domain分层或cluster分析；一个session多round的区间不能表达跨进程/跨来源泛化。Friedman/Nemenyi只在共同完整block矩阵与假设适配时用；不填0或任意大罚值补缺失。

论文配置事前声明完整case或成对有效round的纳入规则、retry处理和对应分母。主性能推断默认只纳入该组全部预定measurement rounds成功的case，并另报全矩阵覆盖；有理由选择成对有效round时必须标成功条件化，给失败率/timeout和敏感性分析。未知耗时不插入任意罚值；若研究成功工作吞吐，另实测整工作负载wall并计失败/重试开销，不能由成功trial均值推算。

完整矩阵覆盖、共同有效子集的性能、pairwise可用子集分母分别显示。多重比较声明family/校正，实际效应和不确定性一起给出；不因p值生产一个全序赢家。

### 10.3 可重算的聚合量

- 总压缩倍数：同scope下`sum(logical bytes) / sum(codec complete bytes)`；必要共享依赖只计一次。对象wire另表；对象等权typical ratio不混层。
- 总原生吞吐：同边界／生命周期下`sum(w_i*logical_bytes_i) / sum(w_i*representative_native_time_i)`；或相同schedule累计`logical_bytes*loops / native_total_time`，不以loops改变对象权重。对象throughput另用对象时钟。
- 成对speedup：同条件absolute time之比；跨source可给预先权重的geometric mean，同时保留每对象时间与coverage。不同环境绝对吞吐不直接平均成算法总分。
- 随机编码大小/模式同样记录分布。retry成功、被排除样本或完整case选择均有规则与敏感性分析，不替换原失败历史。

首批论文图以codec完整输出／原生encode／decode Pareto、rate-quality-speed、分领域、配对speedup与失败覆盖为主，ABI／框架wire和对象延迟作为辅助边界消融。综合分数只有在明确部署权重和敏感性分析时才有意义。

## 11. 多环境扩展与独立 profiling

### 11.1 资源profile

采集CPU型号/拓扑/ISA、物理核/SMT、affinity/NUMA、频率/电源、OS/Python、编译器/flags、动态库、GPU/显存/driver/runtime、请求和effective线程、host辅助资源。无法取得的字段为null及原因。不自动修改BIOS、系统电源、ASLR或清系统cache。

| 扩展 | 共同工作负载 | 防止的混淆 |
|---|---|---|
| 内部线程scaling | 相同对象、实现和外层chunk几何；改变真实thread knob | 主线程CPU time不当等待时间；固定后台线程不伪装单线程 |
| 外部object/series pool | 同一固定corpus/chunk集合，任务完成wall | 与内部并行分开；队列/IPC/调度/重组计入，cold/persistent pool分别声明 |
| scalar/SIMD | 可验证同来源受控变体；operation级路径/flags | CPU支持ISA不等于代码用了ISA；禁自动向量化不能移除显式intrinsics |
| GPU部署/设备驻留 | 同原始任务/质量，各自明示资源和驻留 | GPU thread不能与CPU thread数量直接对齐；kernel吞吐不代表主机完成 |
| 多机/多OS | 同逻辑配置各环境独立resolved运行、汇集raw | 不依赖远程调度服务；按environment分层，不冒称全算法可移植 |

当前Sprintz依赖AVX2/BMI2/LZCNT、LZSSE依赖SSE4.1；当前ALP bridge scalar。能否在ARM或不同OS执行以真实构建和测试为准。没有受控scalar变体就记录该消融不可做；缺硬件写unavailable。线程speedup/效率以同环境同工作负载基线为分母，变更chunk或大小的优化另实验。

六个无损重写shim的 `call()` 在各共享库内使用全局mutex，同库不同handle的同进程并发调用也会串行（[源码](adapters/rewrite_lossless/native/tscb_rewrite_lossless.cc)，第129行）。首批外部并行用独立进程executor；Python释放GIL不能绕过该锁。后续去锁需有状态/线程安全证据并作为新implementation，不凭线程池配置宣称原实现已支持并行。

外部pool的throughput boundary覆盖从已就绪任务开始调度到完整产物/恢复集合可用；初次pool建立是否计入由lifecycle声明。进程数与codec内部线程共同占用资源，限制/记录oversubscription。连续流和随机访问另设实际push/finish、checkpoint/query任务，不能从分块对象推断支持。

### 11.2 Profiling 独立执行

主计时不启动高频collector。profile读取同manifest，生成 `pass_kind=profile` 和新attempt，测RSS/children、显存、CPU consumed time、perf/Nsight、能耗等被RQ需要的项。profiling失败只使该项缺失；codec错误、超时/OOM、验证失败依然真实记录。

采样peak是下界，注明频率/scope；OS ru_maxrss是process lifetime high-water，不能把持久worker的累计值称每trial峰值。allocator used/reserved与整设备/进程显存分开，Python tracemalloc不代表native/GPU memory。给baseline和总峰值；incremental口径需要其测量范围证据，不直接把历史high-water减当前RSS冒充本次新增。

pool/子进程资源包含所有参与者；GPU/能耗传感器若是设备或socket范围明确其他负载和采样窗口。profile与主时间不是同次观测，不能拼成同次精确峰值或能量主张。主worker资源限制仍可独立实施；没有观测证据时不宣称资源或线程因果已证明。

## 12. 从原生默认改造到论文套件

原有P0–P5对象历史验收保留于§14。新目标按下表实施，不以旧对象成功数证明原生完成：

| 阶段 | 顺序与交付 | 完成证据 |
|---|---|---|
| N0 文档先行 | 计划／架构／实施报告统一core默认、API／对象辅助、真实输出与生命周期 | 三份文档一致，尚未实现／运行明确pending |
| N1 最小原生闭环 | C++ batch driver → raw／Zstd／LZ4-frame／Snappy直接API → 完整输出账单 → prepared／fresh | 真clock／loops、完整操作、计时外逐产物恢复与失败终态 |
| N2 两ABI和兼容 | 通用C1／RW native_api → scope-aware报告与资格 → 保留object显式配置 | 未接入core／复合／输出不完整保留unsupported与null，不冒称core |
| N3 真实输入与扩展core | 按格式逐项core入口 → 同binary／参数／dtype／layout／分片 → 新正式run | 主表全部来自新native raw，逻辑分母和必要字节可核，旧对象表保留 |
| N4 研究与资源 | 真实ISA／线程／GPU completion → 长度／质量梯度／pool等辅助实验 | 同边界同任务，资源／状态证据；无能力明确拒绝 |
| N5 复现交付 | 新driver／source／build身份、两环境、数据获取与新的私有导出 | 数字追到新raw；保留旧包和raw；许可／失败／范围完整 |

先完成N0再编辑实现。没有现成core不阻塞已支持成员，但辅助API不能代替默认core。测试针对ABI布局／ownership、reset隔离、Finish／容量、输入不变、逐operation输出覆盖、验证计时外、真实clock／loops、字节区间／模型／tail、unsupported分母、crash／timeout／retry及历史报告兼容。正式测量独占串行，不与CI／构建／数据准备／绘图并行。

## 13. 论文实验包与框架自身验证

### 13.1 主实验与扩展实验分工

| 实验 | 主要主张 | 最低应交付的结果 |
|---|---|---|
| 核心无损 | 同typed任务的codec空间／原生速度／覆盖 | codec必要完整输出、core主表、API辅助、prepared／fresh、全部状态 |
| 核心有损 | 相同质量语义下的取舍 | actual质量、violation/infeasible、rate-quality-speed |
| 接入辅助成本 | ABI／框架怎样改变部署成本 | 短／长对象、codec必要输出／适配envelope／wire、object延迟与shared scope |
| 边界与绑定 | Python/native/device差异的实际含义 | 匹配输入/时钟条件的直接native对照；对象开销拆解 |
| 多环境 | 线程/ISA/GPU何时有效 | 环境内speedup与scaling；主机/设备完成对照；实际资源 |
| 可选任务 | 仅对论文声称的stream/query/downstream/energy | 真实工作负载、状态/质量/延迟/资源，不由普通压缩结果推导 |

框架至少用若干代表codec与直接native调用对照输出、字节数和相同计时起止；验证薄bridge的归因，量化Python/packing的规模效应；至少在第二种环境复现主协议。当前native移植/重写与upstream差异单独说明，不能把所有实现差异归因于理论算法。

保留实现是第一批实验成员。P3时核对它们是否足以覆盖各RQ，以及TerseTS等相关工作所代表的强竞争方法；确需新增成员则固定来源单独接入，不能仅以“已有36key”证明研究覆盖。新方法/模型依赖和许可不成为其他已可运行实验的全局门槛。

### 13.2 公开复现内容

复现包包含数据source/license/version/hash与获取/解析脚本、窗口/任务与开发评价划分、codec/variant/source/build/模型依赖、各环境信息、单份实验配置及resolved matrix/schedule、raw JSONL和代表产物、图表/统计代码、失败/预算/retry与排除政策。不能再分发的数据提供可核对hash和取得方式。

论文图表每个数字可关联 `run/case/session/round/attempt`。绘图重生成不执行codec；修改报告逻辑可生成新的analysis记录，原测量保留。论文覆盖只按实际完成实验声称，不以GPU/stream接口预留代替运行证据。

日常默认路径是：**一份native配置 → 相关资格复用 → 准备／有界校准／预热 → C++内部重复完整编解码 → 计时外逐产物验证 → raw及分scope主／辅助报告**。显式object配置继续走原对象路径。接入CI、研究统计、资源profiling、论文复现与发布各自承担任务，核心框架不引入新的全局验收台账。

## 14. 2026-10-13 实施事实、实现选择与验收入口

**本节是历史事实记录：CPU大小／时间默认均为object_memory完整wire／对象处理成本，GPU按各自host_to_host／device_resident边界，不作为修订后native主结果。部分旧raw已不在当前checkout，原数字保留历史声明，本轮未重新核实者不充当新证据。** 本节不将新原生目标或研究扩展标成已完成。软件包版本 `tsbench 0.1.0`、typed wire 版本 2（兼容读取历史版本 1）、C ABI 版本 1 与 RW ABI 版本 1 分别管理。

### 14.1 先清理，再生成

[清理记录](docs/cleanup_20261013.md)列出删除范围。旧 `src/tscompbench`、tools 控制面、schemas、configs、tests、Dataset_Verify、local_lab、outputs、历史审核/架构与重复 Compression_Rewrite 副本已删除。保留 adapters 的冻结 native/vendor/patches/tests/模型、native/include、真实 codec 的 capability/source JSON、许可、V4 研究溯源与图。Git 和工作区管理目录保留。

原始 CSV/NPZ 数据移至 `/home/fzg/PycharmProjects/材料/TSBench_Corpus`，旧 univariate 生成副本删除；legacy catalog 仅供来源核查，不导入新运行器。首轮 pilot 仅冻结本地文件，后续已核实三源远程精确 CSV、解析与开发／评价窗口，见 §14.7；天气预处理包装与 ILI 数据许可仍有明确未知项，不能称全部语料可自由再分发。

新的 [独立包](benchmark/pyproject.toml)只依赖 NumPy，不导入任何旧框架模块；旧构建命令中的必要原生配方被提取为新 `_native_recipes.py`，新 build/qualification/run 记录分别生成，历史 PASS 不授予资格。

### 14.2 已实现的主路径和具体选择

- `config/cli/data`：严格 TOML、未知字段/参数拒绝、NPY 保留原 dtype、具名 NPZ、显式 CSV dtype/时间解析/窗口与 source hash；values/timestamps/records/component 投影分别计算原始分母。对象支持十种数值 dtype，mask 可为 0/1 uint8 或 bool；具体 codec 仍遵守自己的 dtype/rank/domain。
- `registry/build/bridges`：36 个真实 key 和 raw-store；`lz77` 只解析成 deflate-zlib。C1 结构体尺寸/offset 对照真实 C 头；每 encode/decode 新 handle，状态错误立即复制，bound/used/capacity、Finish 与 finally destroy 实现。RW1 逐列配置与帧目录恢复，模型字符串保持存活。decoder 仅加载已安装二进制并校验，不自动构建，也不读取外部原始模型；DeepZip/DZip 所需模型已在原生帧内。
- `schemes/artifact`：固定 `<8sHI>` prefix、canonical JSON descriptor、连续 payload；dtype/shape/order、roles、每 part 的真实 codec/参数/版本/长度/hash、显式独立 row chunks/channel table 均进最终 wire。校验重复 JSON key、非标准 NaN/Infinity、shape checked product、区间重叠/遗漏与 payload checksum；wire 版本 2 对 canonical descriptor（排除其自身 checksum 字段）要求 SHA-256 校验，检测 shape/参数/逆变换元数据损坏；历史版本 1 仅兼容读取，缺少 header 校验的限制随历史记录保留。对象解压总量上限 2 GiB、descriptor 上限 16 MiB、part 上限 65536。所有原生 decoder 都受 worker 资源与超时约束。
- `codec_input_id` 使用 C1 实际输入（包含 TAI1/RWI1/SRI1/NTI1/ZFI1/TSI1 头及真实 SoA/row layout；SIMDComp 为 typed u32），RW1 为实际逐列输入。另存 typed 中间 part 身份，避免把 bridge 前后两种输入混为一谈。当前实现的输入 hash、payload/descriptor checksum 和必要 descriptor 构建均在 object encode 段，策略写入 wire；该成本不能从时间中扣去。
- `validate`：bitwise 含 NaN payload、±Inf、−0、masked 位置的原始 bits；有损在 valid/finite 原始域计算，mask/T、特殊值与无效位置独立精确恢复。整数差值先用 Python int，质量累计使用 longdouble 与缩放 RMSE 防溢出；ABS/范围相对/逐点相对不加隐藏容差。ABBA/fABBA 只能进入 empirical_quality。
- `runner/worker/cpu`：同资源主测量顺序调度，按 block 保存确定的随机 schedule；worker 加载后校准、独立对象预热、loops=1、每 trial 编码自己的 wire、另建 decoder session、计时外核对可信 input fingerprint。资格的 implementation 小 suite 与 exact-input wire-only 新进程恢复分别按内容键缓存；report 不进入资格 identity。默认 timeout=120 s、RLIMIT_AS=4096 MiB（虚拟地址空间上限，非 RSS），affinity/线程环境在 NumPy/native 首次加载前实施。DZip 的调用线程及两个固定 Eigen worker 单列 native_threads=3，不进入单线程层。
- `records/report/profile`：append-only JSONL 保存 planned/started/stage/terminal、真实 crash/timeout 与未知 signal；SIGKILL 本身不当 OOM 证据。resume 校验数据/执行实现/环境身份；retry 增加 attempt，主摘要保留 attempt 0。截断尾行先保存再恢复。默认 report 只读 raw，含全请求分母、成功条件性能、质量和完整/payload/header 成本。Linux profile 另开 pass，记录 runner 及可观测子进程 RSS/CPU/threads；采样峰值是下界，不能称每 trial 精确峰值。

已安装解码程序的 `.so`、runtime 依赖与 capability card 是 decoder 实现配置；模型/字典的数据成本在 frame 内计入。card 不是 original shape 模板，组件 shape/params 始终来自 wire。实际恢复测试另有无源码/无外部模型安装目录验证。

### 14.3 验证与结果位置

可复跑入口见 [README](README.md) 与 [examples](benchmark/examples)。三组全资产实验分别使用 bitwise、bounded_abs 和 empirical_quality，避免将经验 tolerance 混成 ABS 保证。每个可执行 case 首版预算为 1 session × 7 rounds / 2 warmups；不支持的请求仍保留在矩阵，未伪造 trial。

具体测试数量、资格覆盖与正式运行数字在本节后续实测表及 [CPU 实施结果](docs/implementation.md)记录。所有数字指本机、这些输入与这些配置，不表示已取得跨领域、跨环境或上游原版算法的总体排名。

### 14.4 尚未由当前实现/环境覆盖的设计

核心正式 executor 接受 CPU `object_memory / independent_object / natural`。匹配 native API／完整对象边界对照、外部 pool、三源研究统计和 GPU `host_to_host`／`device_resident` 分别作为独立工具实现并保存自身身份，不把不同边界时间混入对象主表。file、stream/query、共享模型移出原生帧及可变 native 线程 scaling 仍无相应运行证据。

原沙箱内 `nvidia-smi` returncode9只证明该执行surface不可见设备。宿主范围只读探测已成功枚举RTX2070／driver535.288.01，见[宿主证据](docs/research/gpu_host_probe.json)；不把沙箱设备隔离写成宿主driver不可用。cuSZp 真实 GPU 资格和两组 host／device formal run 已完成运行并保存，具体状态见 §14.13；两个网格均有严格 f32 原始域 `quality_violation`，不能标记为 complete success。第二软件环境复跑不等于第二台机器、第二 OS／ISA 或独立第三方复现。source／解析／窗口冻结和分层描述已推进，完整论文覆盖、未明数据许可及投稿实验包仍按实际范围列出，不能由36个 key 的成功替代这些要求。

### 14.5 无版本目录、运行库绑定和可逆整数方案

按用户要求，工程路径统一为 `benchmark/`、`build/tsbench/`、`runs/`、`docs/research/` 与 `docs/diagrams/`；文件名不附加 `_v4`。V4.0 仍是本计划的设计版本，wire/ABI 各自具有格式版本。旧测量的 manifest 与 observations 原字节保留，[迁移映射](docs/path_relocation.json)记录前后路径及 raw hashes；旧配置/实施身份不被改写成新身份。36 个 native 成员已在新构建路径全部重建成功，新的正式实验使用新 run 目录。

DZip 原先的 unavailable 来自此 Conda 环境的旧 `libstdc++` 缺少 `GLIBCXX_3.4.30`；不是算法质量失败。profile 可声明 `runtime_preload` 绝对库路径，在新 worker 的 `Popen` 之前加入 `LD_PRELOAD`，wire-only decoder 继承相同环境。请求 preload 的 literal path、当前解析 target 和 hash 也进入 implementation identity；resume 即使没有剩余 trial 仍重新核对，不能让同名 symlink 换库后沿用旧资格。prepare 在加载 NumPy 与 codec 之后读取 `/proc/self/maps`，把实际 runtime 的 canonical paths 和 SHA-256 写入 effective profile／implementation identity；独立 decoder 另存实际映射证据。`ldd` 的构建依赖仅是磁盘解析证据，不能代替进程真实映射。不安装或替换系统／Conda 库，原 unavailable 历史保留。

NeaTS／LeaTS 直接编码 fixture 的纳秒时间轴，257／257 个恢复值不一致、最大误差 512000 ns。已按真实 native frame 定位到 float32 斜率量化与零位残差选择，详见 [反例分析](docs/research/neats_timestamp_failure_analysis.md)。源 codec 未静默修改；新 `integer_affine_gcd` 是单独声明的可逆 scheme：每 part 取 bias=min、scale=整数差值 GCD（常量/empty 为 1），使用 Python int 计算，归一化值仍须满足原 dtype 及 codec 的真实能力范围。bias/scale/version 保存于 wire；逆变换先核原 dtype 范围再 cast。超过原 dtype 的归一化值明确拒绝，例如 `[INT64_MIN, INT64_MIN+1, INT64_MAX]` 的 GCD=1，不以无声溢出换取接入。

该 fixture 的 bias=0、scale=60_000_000_000，归一化为含重复值的 0..256。encode 包含 GCD/扫描/变换成本，decode 包含整数逆变换，元数据包含于 header/stored_bytes；原对象、typed 中间输入与实际 native 输入身份分别保留。支持判定针对变换后输入，实际资格及正式每轮恢复仍逐位核原纳秒域。数学可逆性不替代 codec 的 exact-input 和新进程恢复资格，也不表示已解决 codec 全 int64 域问题。

### 14.6 最终 CPU 闭环实测

最终核心测试 **83 passed / 6.62 s**。覆盖真实 ABI、特殊值、shape/tail、输入不变、独立 wire 恢复、mask 的 implementation/exact 资格、整数变换极值/溢出与原域恢复、wire 版本 2 header 损坏拒绝与版本 1 兼容、两级缓存、native crash/signal、timeout 进程组、截断恢复、retry 原失败保留、runtime 真实映射及 symlink 变动拒绝 resume。构建36／36成功。最终6组正式实验使用当前 core 与 wire 版本 2，均为1 session ×7 rounds、2 warmups、loops=1，**1,092／1,092 measurement trials 通过**，**36／36真实 codec key至少有一个完整合资格 case**；raw-store另列参考。

| 最终实验（2026-10-13） | 请求与资格 | 正式 trial |
|---|---|---:|
| [全部无损](runs/all-lossless-explicit-runtime-final-20261013/report/README.md) | 384请求；119 ready、265 unsupported；DZip显式兼容runtime层 | 833／833 ok |
| [整数归一化时间轴](runs/timestamps-integer-affine-final-20261013/report/README.md) | 4 ready；raw、raw＋变换、NeaTS＋变换、LeaTS＋变换 | 28／28 ok |
| [ABS质量](runs/bounded-quality-final-20261013/report/README.md) | 9 ready；Serf-QT／Serf-XOR／ZFP，ABS=0.01 | 63／63 ok |
| [经验质量](runs/empirical-quality-final-20261013/report/README.md) | 4 ready；ABBA／fABBA，实际误差 | 28／28 ok |
| [records组合](runs/records-composite-final-20261013/report/README.md) | 5 ready；异构组件、独立chunks、channel routes | 35／35 ok |
| [三源values pilot](runs/three-source-values-pilot-final-20261013/report/README.md) | 15 ready；三个本地CSV来源各512个float64 ×五方法 | 105／105 ok |

每个trial的时间、完整字节与质量见对应报告；[final_evidence.json](docs/final_evidence.json)保存run IDs、manifest/raw hashes和总覆盖，[CPU实施结果](docs/implementation.md)包含完整表图与限制。覆盖主图只统计前5组406请求（141完整、265不支持），三源pilot另绘，合计421请求；不把条件不同的case次数用作算法排名。原始DZip unavailable、直接纳秒时间轴error与早期fixture错误均保留，不因后续新方法/新环境成功而改写。

最终小型CLI复验另保存于 `runs/cli-smoke-20261013`：21／21 trial、保存wire独立decode、无剩余项的resume/retry保持observations字节不变；独立profile pass未改变主raw。完整native资格grid的当前binary／bridge身份复核另列于CPU实施结果，不把性能trial与资格案例累计成同一计数。

### 14.7 三源身份、长度／质量梯度与统计实现

[数据来源说明](docs/data_sources.md)、[冻结 catalog](registry/datasets/catalog.json)和[获取／验证脚本](benchmark/tools/fetch_datasets.py)保存完整 CSV SHA-256、精确获取路线、许可证据、typed V／T hash 与开发／评价分区。ETTh1 绑定原作者 ETDataset commit `1d16c8f4f943005d613b5bc962e9eeb06058cf07`，专用数据仓库许可为 CC-BY-ND-4.0；weather／ILI 的官方 Autoformer 单文件分发与本地 hash 完全匹配。weather 全52696行、21数值列与 MPI 2020a／b 官方数据逐位一致，MPI 原始数据为 CC-BY-4.0；预处理包装许可未核实。ILI 原始提取版本／转换及精确 CSV 许可为 unknown。仓库不捆绑原始 CSV，提供精确获取与 hash 校验，不从代码许可推定数据许可。

冻结的[study design](benchmark/experiments/cpu-study/study_design.json)在测量前声明全部网格，未用评价对象选择参数。ETT／weather 开发为 `[0,1024)`、评价为 `[1024,1536)`；ILI 开发为 `[0,256)`、评价为 `[256,768)`。每源128点是512点前缀，不能当作独立来源。历史 pilot 使用 `[0,512)`，因此 ILI 的 `[256,512)` 已被观察过；当前 ILI 评价不声称完全未观察的 holdout，固定网格也不能抹去数据重用。

正式五组共 **132 ready cases／2772 successful trials**，均为3 independent sessions ×7 rounds、2 warmups、loops=1：42个无损长度 case（882 trials）；Serf-QT／Serf-XOR／ZFP 各3个 ABS 界0.001／0.01／0.1（54 cases、1134 trials）；ABBA／fABBA 的0.01／0.1／1经验网格（36 cases、756 trials）。实际误差按原始单位验证，经验参数不转写成 ABS 保证。

[study.py](benchmark/src/tsbench/study.py)只读 raw，按最早实际执行 attempt 保留失败；完整成功 case 才进入同 run／raw_object_id／task／profile 的 Zstd 配对比较。先取 session 内 round median，再在 source 内聚合 log ratio；bootstrap 重采样来源且等权，3个选定来源的95%区间仅为探索性描述，不声称总体代表性、显著性或总体冠军。实际误差／完整大小／encode／decode 的四维 Pareto 仅是逐对象事后 oracle envelope，不是可部署 selector。逐 trial 行号／身份、有效分母和分析代码 hash 保存于[分析结果](docs/study_results/summary.json)，绘图入口为[plot_study.py](benchmark/tools/plot_study.py)。

### 14.8 最终 native 资格与匹配边界对照

[最终资格 grid](docs/research/native_qualification_final_summary.md)在当前完整 bridge／binary／runtime 身份下重新执行全部36个成员：**848 cases＝834成功＋14预期源域拒绝，0非预期拒绝／error**，62个配置、17个 DeepZip model。没有合并旧资格 rows，原历史文件与时间戳反例保留。120个唯一文件 hash 与36个当前 build／binary index 再次核对；该 grid 的耗时不是 benchmark 性能。

[boundary_experiment.py](benchmark/tools/boundary_experiment.py)对 Zstd／LZSS 的0／1／257／4096／65536／1048576 byte固定输入，完成 **252／252 paired rounds**（2 codecs ×6 lengths ×3 sessions ×7 rounds）。真实直接 C、prepared ctypes API 和生产 object wire 三条路径的实际 native input／payload／恢复 bytes一致。C和Python各自读取实际 runtime maps，双 preload 控制重叠库身份，252组全部一致；每个 C／Python ABI size／offset核对，全部产物读回并校验 hash，见[边界报告](docs/boundary.md)。

只有 compress＋finalize／decompress 起止匹配的 prepared Python／C API 计算比率；完整 object 含独立 session、分配、packing／checksum／descriptor，与 native API 分列。C 每round重启进程而Python同session重复，cache／process状态仍不同，观测比率不等于单一 FFI 因果成本；比率小于1不说明负FFI开销。完整 wire始终计 header，空LZSS payload虽为0，完整wire仍为1327bytes。

### 14.9 第二软件环境的独立重建与复跑

同一物理主机／Linux／编译工具链，使用已安装的 Python **3.14.5／NumPy2.5.3**，在 `build/alternate-environment` 独立重建36／36成员，并复跑全部无损、ABS与经验质量主协议：**924／924 trials通过**，请求／资格与Python3.11.5／NumPy1.24.3基线一致，36个真实key均有合资格case。环境未安装／修改包，实际 runtime映射及独立资格按新环境身份记录。

构建记录见[alternate_environment_build.json](docs/alternate_environment_build.json)，逐case质量／大小／时间及raw trace见[环境比较](docs/alternate_environment_results/summary.json)。[replay_environment.py](benchmark/tools/replay_environment.py)提供选择已安装解释器后独立构建／复跑的通用入口；[compare_environments.py](benchmark/tools/compare_environments.py)只读两组raw并核对输入／恢复任务／边界匹配。环境运行顺序未随机化且每case只有1session，不据此作软件版本导致性能变化的因果结论，也不称第二机器／OS／ISA复现。已完成测量的路径迁移只改目录位置，manifest／observations原字节与hash保留于[path_relocation.json](docs/path_relocation.json)。

### 14.10 实际外部进程池

[pool.py](benchmark/src/tsbench/pool.py)为独立workload executor；使用新interpreter的Popen，不fork含native状态的父进程。固定4个typed对象、raw／Zstd两方法、W=1／2／4、cold／persistent两生命周期，3sessions×7rounds×encode／decode，最终[正式run](runs/process-object-pool-final-20261013/README.md) **504／504集合操作通过**；24个operation group均21／21，和W1配对的session分母均3／3。每组先通过正常runner完整对象资格和独立wire恢复；某成员不合格时不删除该成员来计算更小集合的吞吐。

编码连续wall从任务派发到父进程收到完整带目录集合产物，解码从完整集合wire就绪到目录解析／IPC／独立decoder／有序对象集合恢复完成。cold包含spawn／对象分发／prepare，persistent单列setup／warmup；输入fingerprint／逐产物验证和pool关闭在availability clock外，各存成本／证据，不能把该指标称整个进程生命周期wall。完整集合index真实计费，单对象wire内模型／descriptor不漏计。decoder初始化只含安装roots／resource profile，实际操作仅接收wire，无原始shape／method模板。

父进程及全部实际worker分别保存CPU／RSS／threads／runtime／affinity；这些是累计snapshot和process-lifetime high-water，不能当每trial增量峰值。IPC读写均非阻塞且有整体deadline；整process group在异常和关闭时清理。父进程退出而后代持有stdout的故障分类已有真实回归，完整最终run与修复后的源码hash绑定；先前504成功集合的首轮run及其修复前源码单独保留。详见[pool报告](docs/pool.md)。

speedup只对同集合／method／lifecycle／operation的完整session配对W1计算，失败或缺失保留分母且不生成speedup。条件顺序固定、对象很小，4个逻辑任务实际只有3个唯一canonical对象（float64与records的V投影相同），结果是这组重复对象workload的描述，不是4个独立来源、线性scaling、native内部线程或通用并行收益结论。

### 14.11 SIMDComp真实路径及最终扩展验证

[SSE4.1／AVX2路径实验](docs/isa.md)使用相同MASKED API、同一20-bit `<u4` 输入prefix，长度257／4096／65536／1048576元素，raw参考与两条实际codec路径，3sessions×7rounds，共 **12 ready cases／252 successful trials**。canonical对象与实际codec input身份相同；每trial独立恢复，保存SBP1的mode0／128-block与mode4／256-block，per-TU真实flags及source dispatch证明对应SSE／AVX2函数被选择。4长度×21rounds有84个完整配对，8种保存frame几何经read-back审计。

AVX2尾部仍使用SSE长度API，内部block几何、目录／tail／staging／checksum成本随路径变化。这里没有现成scalar对应实现，不称scalar/SIMD消融，不把观测差异归因于独立向量位宽。session波动会改变部分时间比率方向，完整wire尺寸差异另列，不声称总体赢家。

扩展工具完成后，完整suite最终 **116 passed／12.88s（Python3.11.5／NumPy1.24.3）**，同一suite在第二软件环境 **116 passed／16.35s（Python3.14.5／NumPy2.5.3）**。新增风险测试覆盖collection directory／IPC非阻塞timeout／native leader退出但后代仍持pipe／close竞态／输入变更／整process group清理、匹配边界产物与session统计、分析精确schedule／缺失／失败attempt／完整条件分组、replay历史证据与失败checkpoint。测试耗时不进入benchmark表。

最终当前catalog本地三CSV再验证通过；历史路径迁移的26份manifest／observations逐文件hash未变。图表只读raw重建，长度／rate-quality／quality-speed保存PNG与SVG及[trace](docs/study_results/figures/trace.json)。[扩展证据索引](docs/completion_evidence.json)分别记录core、study、alternate、ISA、pool和boundary，资格网格与不同完成边界不相加为一个性能trial总数。

P0–P2 CPU主路径和现有codec在实际约束下的完整case已完成；P3具备此次固定三源的可复跑研究基础，P4外部pool／真实ISA路径／cuSZp真实host-device运行和P5第二软件环境／获取脚本已实施。cuSZp 两组 formal 网格仍保留严格 f32 质量失败，详见 §14.13，不能称全部槽位成功。原returncode9来自沙箱surface，不能推导宿主GPU不可用。完整广域论文覆盖、weather包装／ILI未知许可、共享模型成本、可变native线程／受控scalar消融、第二机器／OS／ISA和独立第三方投稿复现不能由当前实验替代。stream/query/downstream/energy仅对具体声称的任务需要，当前不声称已实现或测得这些结果。本文设计要求没有因这些限制被降低为纯CPU验收。


### 14.12 数据投影、质量参数、精确分母与执行来源补强

本节是后续实现修正，不把旧raw赋予新实施身份。CSV／NPZ多列选择现在对V／mask／schema.columns同步投影，保持T行对齐和声明顺序。row bounds／step／column indices拒绝布尔、非整数、负索引、重复列与越界静默截短；零长度窗口仍可显式声明。原C／F布局在窗口／列选择后保留，显式order可覆盖；requested与resolved窗口进入lineage。配置阶段采用相同纯规则预检。

原始域质量验证先保存全部可计算的actual error，再报告最早恢复／质量失败。point-relative记录`max(abs(original), floor)`分母政策、实际阈值范围、零分母及违例数量；NRMSE／PSNR保存原valid finite V全对象range分母及null原因。task requested／effective constraint与codec自身参数分开；ZFP的requested／effective native tolerance从实际经过checksum与列目录检查的ZFA1 payload读出，记录binary64 hex、part位置／hash和raw-exception mode；解析在encode／decode时钟外。quality配置拒绝boolean数值，历史有效界alias明确只表示taskconstraint。

[trial_analysis.py](benchmark/src/tsbench/trial_analysis.py)作为纯分析共享模块检查确切case/session/round/attempt，拒绝duplicate schedule、duplicate terminal attempt及unscheduled终态。report／study／environment比较／replay共同使用；额外成功行不能抵消缺失，最早实际执行失败不会被成功retry覆盖。新分析保留missing keys、行号trace和分析依赖hash。已有48组core格式运行的只读重分析全部通过，manifest/raw原hash未变，见[审计](docs/research/schedule_integrity_audit.json)。

[provenance.py](benchmark/src/tsbench/provenance.py)保存具名执行sourceclosure，包含runner／config／records／worker／measurement／bridges，并将实际Python源码快照写入每个新run的source目录；原native source／binary／compiler／runtime闭包仍由实际build证据保存。新run的[environment collector](docs/environment.md)在admission前和measurement后保存相邻快照，物理拓扑／NUMA／cpufreq／powercap／cgroup／Python包inventory／只读Git字段缺失时保留null及理由。瞬时诊断不作为resume严格身份，也不表示trial内控制／采样；旧run缺失字段不倒填。worker实际RLIMIT_AS设置后保存soft／hard readback，compiler证据使用真实`compilers`和commands，不再读取不存在的singular字段。

本节代码改变了数据／验证／worker资格身份，必须使用新run重新资格和测量；旧六组1092trial仍表示其原始实施身份。补强后的 CPU current-core、真实 ETT／weather 对象网格和 cuSZp formal run 已使用各自的新run身份执行，结果见 §14.13；尚未完成的全计划范围继续保留。

### 14.13 当前源码身份的 CPU、真实对象与 GPU 增量结果

补强后的六组 [CPU current-core run](runs/current-core-20261013/) 共 **1092／1092 measurement trials 成功**：无损833、时间戳 affine 28、ABS 63、经验质量28、records35、三源pilot105。每组 manifest／source snapshot／raw 独立绑定当前身份；本节结果不将 §14.6 或更早的同名数字回填为新代码的结果。完整测试在 Python3.11／NumPy1.24 与 Python3.14／NumPy2.5 均为 **267 passed**，测试耗时不计入 benchmark。

[真实对象冻结网格](benchmark/experiments/real-objects/README.md)在新窗口 `[2048,2560)` 使用 ETT 全7通道和weather全21通道，128点为512点前缀，覆盖timestamps、records、MTS、温度ABS、C/F layout、channelwise和64／256行独立chunk。五组 [current-real run](runs/current-real-20261013/) 完成 **152／152 requests、3192／3192 trials**；[只读分析](docs/real_object_results-current-20261013/summary.json)保存全部状态、120个scheme pairs和60个layout pairs及逐trial溯源。C/F保留不同raw_object_id，通过C-order组件hash建立配对；32个任务对象描述对应26个canonical object IDs，不能按32个独立来源计算统计。

cuSZp native [correctness qualification](docs/research/cuszp_qualification_20261013.md)完成 **48个成功样例、48个fresh decoder、30个预期失败、0意外错误**。资格记录核对资源释放及binary/runtime身份，但该48＋48＋30不是吞吐或延迟结果，也不证明任意浮点输入。

| GPU formal run | 预定slots | 实际状态 |
|---|---:|---|
| [cuszp-formal-0p01-20261013](runs/gpu/cuszp-formal-0p01-20261013/) | 252 | 168 `ok`；84 `not_run`／`quality_violation` |
| [cuszp-formal-0p1-20261013](runs/gpu/cuszp-formal-0p1-20261013/) | 252 | 210 `ok`；42 `not_run`／`quality_violation` |

两组formal均保留f32 requested／effective bound和严格原始域quality policy。未运行slot来自exact qualification的质量约束拒绝，不等同于codec崩溃、OOM或设备不可用；未完成case的性能保持null，不能把两组run标记为complete success。`host_to_host`与`device_resident`各自计量完成边界并分列，这个synthetic一维网格不代表真实ETT／weather MTS的GPU覆盖，也未证明可强制VRAM上限、OOM／kernel fault恢复或stream/query/downstream/energy。

本次增量补全了上述固定输入和边界的运行证据。广域真实语料、weather包装／ILI许可、共享模型成本、可变native线程／scalar控制、第二物理环境、独立第三方复现与完整投稿包仍未覆盖；历史manifest、raw和原始失败继续保留自己的source／环境身份。

### 14.14 GPU 参数敏感性、有限真实来源与可安装包

严格 GPU 原参数的失败保持原身份：f32 ABS=0.01 中等/大对象最大误差为 `0.010000228881835938`，ABS=0.1 大对象为 `0.10000228881835938`。从已保存 artifact 的量化整数和源公式可精确复现：f32 reciprocal、乘法/加法量化及 `q * bound * 2` 的恢复舍入都会产生误差；向下转换 native bound 并不能证明全域严格 ABS。诊断与独立冻结配置见 [gpu_margin90.md](docs/gpu_margin90.md)。

后续配置显式保持任务 ABS=0.01/0.1，将 native 参数改为0.009/0.09，全部按原始域严格验证。这是观察失败后声明的90%参数敏感性实验，不能当盲选、最优参数或普遍误差定理。synthetic 两组 [margin90 run](runs/gpu/) 各完成252/252成功trial；真实ETT `OT` 与weather `T (degC)` 单列 `<f8>` 的128/512前缀，两组各完成168/168成功trial。所有case都有wire-only decoder和完整3×7 schedule；host_to_host和device_resident仍分列。真实单列结果不代表GPU多变量能力；ETT OT单位未核实、weather degree_Celsius均保留来源声明，源之间不以同单位混合。

当前源码CPU native网格重新完成834成功、14预期源域拒绝、36/36成员；[当前证据索引](docs/current_evidence.json)保存这些资格及19个本轮run各自的源码、raw、report和build身份。当前CPU图只读取新core/pilot raw，[图trace](docs/figures/current-20261013/trace.json)记录精确schedule helper及贡献行hash。分析源修改不改变测量资格，仍须单独绑定分析hash。

可安装的纯Python wheel保存在 `build/package/tsbench-0.1.0-py3-none-any.whl`。从该wheel独立解包，在仓库之外的cwd以isolated interpreter、明确asset/build roots，仅给保存的真实Zstd wire恢复257×3 f64对象，原域bitwise核对通过，见 [package_verification.json](docs/research/package_verification.json)。该验证说明包可运行和恢复；它依赖声明的native安装roots，不等于独立机器、第三方复现或全部数据可再分发。

### 14.15 三维 PeMS、安装构建修复与本机交付

本节补充独立的新证据，不改写此前raw或已冻结网格。新目录统一使用 `benchmark/`、`build/`、`runs/`，新增文件／目录不使用 `_v4`、`-v4` 标记；本计划保留用户指定原文件名。

**三维输入与获取决策。** [来源核查](docs/research/additional_data_sources.md)重新计算4份本地PeMS NPZ的SHA-256，并以Git blob SHA-1和长度核对作者固定树 `guoshnBJTU/ASTGNN@9c2e19b98c4cedf1f35214d8789685b6381b3aad`，4/4匹配。保持原生time／sensor／feature rank3 `<f8`、C-order、V-only，不flatten或伪造时间轴、采样频率、单位和mask。processed数据许可、单位、传感器映射仍unknown；4文件同属Caltrans采集体系，不作为4个独立物理总体。

[冻结配置](benchmark/experiments/pems-values/README.md)取start1024，4文件×128／512／8192行共12个嵌套对象。48个请求中raw-store／Zstd／deflate共36 ready，Chimp128因rank3共12 unsupported。独立构建后的[正式结果](docs/pems_results/README.md)为 **36/36 executable cases、756/756 measurement trials ok**，另有216 warmup和108 calibration，不把这些资格／预热活动加入正式trial数。每case为3sessions×7rounds、完整wire计费、bitwise恢复和输入不变检查；unsupported没有伪造trial或性能。8192行对象的raw bytes为23,461,888／60,358,656／57,868,288／33,423,360，超过本机cpu0所记录L3容量20,971,520；natural cache、没有pin或缓存干预，仅作容量描述。

每个ready case另有独立子进程的wire-only恢复。保存的CPU恢复结果没有逐项decoder PID、execution provenance、native cleanup或effective profile，不能补造逐项过程核对；主worker准入profile与build/runtime身份单独保留。manifest run窗口在安装测试结束之后，正式测量串行执行；raw没有逐trial绝对UTC，不能声称该字段已记录。

[精确获取器](docs/pems_acquisition.md)使用固定source版本／长度／SHA与新的append-only JSONL manifest，拒绝覆盖、symlink、HTTPS降级和长度／内容不符；下载采用临时文件和不覆盖的原子安装，读后比较fd／路径身份及修改时间。few-byte fixtures验证损坏、缺失、重复manifest和读取期间变更；这些测试不是额外真实大文件下载的证据。

**安装构建与GPU身份。** 仓库外安装曾在将package配方路径解析为外部asset root相对路径时失败，现同时保存package配方标识、真实source_path与hash；缺registry或空native选择明确失败。8项[安装构建测试](docs/research/installed_build_verification.json)包括实际wheel安装、新Zstd native编译和仅wire的新解释器恢复257×3 f64。当前wheel在 `build/package-installed/tsbench-0.1.0-py3-none-any.whl`，33个Python源逐文件匹配workspace；旧wheel和旧验证继续表示历史scope。

build.py不在CPU执行闭包内，当前CPU身份仍 `sha256:d7d0f84e75c49b0a5fa330f17ec0e8319e8aa43dce0c454e65c840cc4743517f`。GPU闭包含该文件，因此新完整身份为 `sha256:1e37ea146c0e477862fc732278ab1394162c5c9cc5dcf7eb90a6ed63f4c56cd1`，不修改闭包排除规则或回填旧run。新的[GPU控制面配置](benchmark/experiments/gpu-builder-check/gpu-fixed-smoke.toml)保持task strict ABS0.01、native0.009，在f32长度33／f64长度32769、host_to_host／device_resident共4case完成 **28/28正式trial**，execution/native unchanged均true。该有限验证不能替代旧身份的840trial完整margin90矩阵或原始质量失败。

**工程验收边界。** 本机框架搭建、现有codec在资格／源域／资源条件下的完整case、拒绝记录与bench结果已完成；[需求审计](docs/research/remaining_requirements_audit.md)逐项区分已实现、合法unsupported与未声称的研究扩展。没有现成scalar／可变native线程／共享模型格式时不制造实现；stream／query／downstream／energy没有当前任务主张，第二物理机器和第三方独立复现不是本机工程目标的隐含门槛。广域论文结论仍需对应的新证据。

[复现导出工具](docs/reproduction.md)按当前索引选择source、license／model／patch、冻结配置、manifest／raw／report／source snapshots和实际引用的build records，拒绝hash漂移、越界、symlink和覆盖。默认源码包排除binary／wheel，显式include-binaries只选择当前引用产物；真实原始／恢复数组不入包，合成wire以明确来源allowlist判定。归档内保留旧证据字节与路径，ledger逐成员核对SHA-256。导出属于私有本地备份和审阅，不授予ELF／DZip或未知许可数据公开再分发权，也不宣称独立第三方复现。

最终完整suite在基线Python3.11／NumPy1.24与同机第二Python3.14／NumPy2.5环境均 **308 passed**，分别38.79s／35.00s，串行且晚于所有正式测量；failures／errors／skips均0。此前267项和中间303项仍表示各自源码时点，最新log／JUnit列入[current_evidence.json](docs/current_evidence.json)的builder_tests。当前索引包含 **21个独立run**，分别保留CPU、GPU资格、原始失败、显式margin90、PeMS和有限GPU控制面检查的分母与实施身份；不把不同边界和资格case累计成一个吞吐数字。

### 14.16 2026-10-15 指标边界与 lzbench 对照诊断

[指标核查](docs/research/metrics_diagnosis_20261015.md)明确 `stored_fraction=compressed/raw` 与 `compression_ratio=raw/compressed`，以及 task input／codec input、native payload／完整 wire、原生调用／对象处理的不同边界。现存 Gorilla 的24case／504个measurement trial大小公式重算一致，但 object 时间不能作为 native 性能。历史其他 run raw 不在当前 checkout，本次不重新确认旧性能表。

[LZ／Zstd／Snappy专项核查](docs/research/lzbench_comparison_20261015.md)检查实际 build commands与 lzbench wrapper，并对6个真实 V-only 矩阵执行18个object及24个直接原生编解码组合，全部按位恢复。Snappy 的6组raw输出与现有payload逐字节一致；Zstd在相同checksum设置下6组亦一致，关闭checksum每组减少4bytes。LZ4当前frame API与lzbench raw block API不同，不能统一扣除header换算。详细产物、双侧源文件hash与binary身份见[不计时诊断记录](runs/lzbench-payload-check-20261015/results.json)。当前vendored Zstd／Snappy／LZ4共82个文件与所读参考源树对应文件相同，不代表构建和计时协议相同。

已经确认的性能比较差异包括：Zstd禁用动态BMI2与汇编路径；Snappy显式关闭SSSE3／BMI2等路径并在RawUncompress前完整验证压缩流；Zstd／LZ4解码先创建不需要的编码context；完整对象路径另有生命周期、复制、hash／JSON／wire与重复Registry解析成本。lzbench Ratio是百分数，默认选择FASTEST且使用十进制MB/s；其公开语料、硬件、binary与版本也不能自动视作本机的匹配条件。

后续性能主表须实现具名 `native_core`／`native_api`／`object_memory` 边界，以原生C/C++批次循环、独立重置逻辑状态的prepared workspace、明确fresh生命周期和计时外核对取得真实native数据。优化构建新增身份，LZ4 raw/frame、Zstd checksum／level／window、Snappy源版本与实际ISA逐项对应；保留现有完整对象结果，不给旧raw回填新计时语义。此节为新增设计要求与字节诊断事实，**尚未实施通用native性能入口或复现lzbench带宽**。


### 14.17 2026-10-15 原生目标实施与正式结果

§1–§13、架构及实施报告已统一为native_core／prepared／natural默认，真实C1／RW native_api辅助，object_memory／independent_object保留。主大小包含codec必要header／参数／模型／索引／finish，排除框架JSON／hash／来源及纯ABI envelope；不能核实则主大小null，不估计扣除。分母不含padding／ABI头／重复共享T。

首批实现已完成：`benchmark/native/driver.cpp`在原生C++循环中用CLOCK_MONOTONIC分别测完整encode／decode批次；`core.hpp`直接调用raw-store／Zstd／LZ4-frame／Snappy真实入口。C1／RW辅助native_api支持单组件identity route、无外部分块／channelwise／transform，RW仅rank1；未接入direct core的成员保持unsupported，未审完整codec输出的API大小为null。`native.py`在时钟外逐份验证warmup与正式产物、核原始输入和实际native runtime maps；报告以core／prepared为主，其余boundary／lifecycle分组辅助，legacy缺boundary仍对象。完整suite **372 passed**，不将测试时长作为性能。

默认[原生示例](benchmark/examples/native.toml)省略boundary／lifecycle并解析core／prepared，8loops、2warmups、256MiB保留上限；[fresh示例](benchmark/examples/native_fresh.toml)显式fresh_request。`python -m tsbench build-driver`提供独立driver构建入口。fresh时钟含context创建、bound／caller buffer分配、完整操作及context关闭；为验证保留的输出buffer最终释放在时钟外，不称完整端到端生命周期。

[固定原生设计](benchmark/experiments/native/design.json)的六组正式运行均已完成，manifest为`complete`且`execution_source_unchanged=true`。各case为2 sessions ×7 rounds，native trial固定8次正式内循环及2次warmup；2254个native trial逐份验证22540对真实压缩／恢复产物，其中18032对正式、4508对warmup。loops不当独立样本，统计使用每round batch均值并保留session层次。

| 新run／测量范围 | 请求 | ready | unsupported | 正式trial |
|---|---:|---:|---:|---:|
| [core prepared](runs/native-core-real-20261015/report/README.md) | 190 | 20 | 170 | 280／280 ok |
| [core fresh_request](runs/native-core-fresh-20261015/report/README.md) | 190 | 20 | 170 | 280／280 ok |
| [API lossless](runs/native-api-lossless-20261015/report/README.md) | 384 | 113 | 271 | 1582／1582 ok |
| [API bounded](runs/native-api-bounded-20261015/report/README.md) | 6 | 6 | 0 | 84／84 ok |
| [API empirical](runs/native-api-empirical-20261015/report/README.md) | 2 | 2 | 0 | 28／28 ok |
| [object对照](runs/object-reference-real-20261015/report/README.md) | 20 | 20 | 0 | 280／280 ok |
| 合计 | 792 | 181 | 611 | 2534／2534 ok |

core主表及object对照覆盖3来源的5种真实V表示：ETT `[2048,10240)`、8192×7 `<f8>`、C/F；weather `[2048,34816)`、32768×3 `<f8>`、C/F，列为`T (degC), Tdew (degC), Tlog (degC)`；ILI `[0,512)`、512个标量、rank1 `(512,)`、`<f8>`、C-order、`OT`。不计原CSV时间列，layout不增加独立来源，ILI不能称全新holdout。主表仅core prepared；fresh、API和对象各有辅助表。首批core只有raw-store参考与Zstd／LZ4-frame／Snappy三个codec，其他core请求保持unsupported。

通用API辅助覆盖36／37个真实CPU codec key在各自合法输入上的完整case（无损values 31、bounded 3、empirical 2），不表示36个direct core。Gorilla联合records入口仍只具有历史对象证据；API lossless的271个unsupported为144个dtype、114个线程profile、12个Gorilla联合入口及1个DeepZip alphabet exact拒绝。ABBA／fABBA使用合法ILI rank1，DeepZip使用0..3符号输入。typed fixtures主要验证接入与资格，不作为跨真实语料排名；bounded与empirical分别保留任务／质量层。

API lossless中45个ready case／630 trial完整输出大小已核实，68个case／952 trial仍未知；bounded六case／84 trial的主空间指标全为null，empirical两个case已核实。未知大小不能由ABI输出或wire补齐。真实totals、产物验证、输入及runtime身份、raw／report和分析溯源见[原生总报告](docs/native_results/README.md)与[证据索引](docs/native_evidence.json)。新测量绑定各自source／build／driver身份，不回填旧raw；§14.16继续保存实施前诊断原文。

本轮已完成首批direct core及通用API辅助的本机工程证据，其他direct core、更广真实语料、第二物理机器及独立第三方复现仍需对应新实现与实测。用户指定的旧`build/reproduction-bundles/current-private-source.tar.gz`在当前checkout缺失，本轮未使用或验证该包，不改变既有导出历史。

### 14.18 全codec direct core扩展与持续开发记录（本轮已完成）

本阶段已为现有codec逐项提供真实`tsbench_core_*`接口，使用codec API及其原生完整输出，绕过C1／RW envelope和不必要复制。prepared可准备context与加载固定模型；每次输入相关采样、训练、在线更新、逻辑状态重置和finalize仍须计入完整encode。decoder不得免费依赖encoder状态或未计费的外部输入相关数据。统一结果可持有caller buffer或codec vector，释放与计时范围单独说明。

ABBA／fABBA／DeepZip／DZip维持合法rank1任务；Gorilla新增无mask的UTS联合T/V直接入口，交错LE int64／f64位型，每行16有效bytes，config声明BYTES、rank2、shape=(rows,2)、C-order。其他codec按真实功能、源域、参数及资源约束逐项接入，不把通用API或当前成功资格视作direct core已完成。

**后续每次变更必须同步更新[开发日志](docs/development.md)**，记录具体问题、解决办法、实际参考、验证与限制；并行分组先写明细再合并。该要求适用于实现、配置、测量、报告及文档。本轮统一构建、测试、独立恢复、新run测量与只读审计已完成，实际范围见§14.20；既有结果不回填新实现身份，§14.16历史诊断原文继续保留。

### 14.19 统一direct契约、验证边界与全CPU入口设计（已实现并验证）

本轮实现范围为当前registry的37个真实CPU codec key，加raw-store参考，共38个key；cuSZp继续使用自身host／device完成边界，不并入CPU core主表。统一`tsbench_core_*`契约传入实际dtype、shape、C／F order、完整配置和原始物理连续bytes；不是在Python中转置、扩宽、生成C1／RW envelope或重复共享时间戳。无mask／无channelwise／无外部分块的合法任务进入对应direct入口，不满足真实功能与源域条件的请求仍明确unsupported，不静默fallback到API或对象。

| 入口组 | 输入与输出约定 |
|---|---|
| raw及通用字节压缩、Huff0／FSE、LZSS／LZSSE | 实际输入物理bytes，完整native frame或恢复所需最小count／mode／tail前缀加真实packed输出；不使用旧实验／ABI目录 |
| ALP／ALP-RD、Chimp系列、Elf系列、Serf、ZFP | 原始浮点width与C／F物理顺序保持；采样、块构造、exceptions、结束与必要序列化在encode内；ZFP为完整原生header |
| Sprintz、SIMDComp、NeaTS／LeaTS | 原typed宽度与有效bytes保持；算法内部对齐／归一化／padding不扩大分母；恢复必需metadata／tail／模型索引完整收费 |
| ABBA／fABBA、DeepZip／DZip | 合法rank1输入；完整原生模型／参数／字典／结束输出；固定DeepZip模型可prepared加载，DZip默认输入相关模型每次encode重新初始化 |
| Gorilla | 无mask UTS联合records，交错LE int64 T与f64位型，每行16有效bytes；完整Prometheus EncXOR，不构造Sample staging数组或C1 envelope |

`tsbench_core_storage()`声明两位flag：bit0表示encode写caller buffer，bit1表示decode写caller buffer。0为两侧owned，1为encode caller／decode owned，2为encode owned／decode caller，3为两侧caller。driver仅在相应caller路径分配容量；owned结果移动vector所有权或持有codec owner，context销毁后仍有效，计时结束再逐份验证并release。实际caller预留与保留owner capacity单独记录，不冒称内部工作区或峰值RSS。

附加源域准入由可选`tsbench_core_validate_input(encoder,input,size)`在主计时前执行；prepared使用已有encoder，fresh可用独立临时context准入后销毁。附加完整流安全检查由可选`tsbench_core_validate(decoder,stream,size)`在decode主计时外对每份产物执行；允许独立验证context，随后decode按已验证、不可变stream契约调用无界原生primitive，不重复完整prepass。SIMDComp的count／profile／width／extent检查属于该hook。检查失败使结果无效，不产生主性能。原生算法自身必需的字典转换、采样、建模、reset、在线train、header／参数读取、结束和原有格式工作仍照实计时，不能借validation名义预计算编码模型。

独立decoder只获得任务dtype／shape／order、`parameters_json={}`和空model；全部恢复依赖来自真实完整压缩输出。Python保存输入content hash、dtype／shape／layout及有效bytes，driver和独立恢复使用同一原始输入身份；按同任务、dtype、布局、有效数据量和质量约束比较。校验、正确性／质量及输入不变核对均在主计时外覆盖所有warmup和正式产物，不能只验证最后一份。

当前接口、分组实现和专用测试已通过统一验证，38个key均在prepared及fresh_request下有共同合法输入的完整成功案例；实际ready／unsupported、测试、source／build／runtime身份和独立新run见§14.20。该覆盖不意味着全域支持或跨任务可比。§14.17的2534trial、API／object及GPU历史结果保留原边界与原始证据，不改字段名或回填本轮身份。

### 14.20 全CPU原生正式运行、统一审计与完成范围（2026-10-15）

默认测试目标为`native_core / prepared / natural`；`fresh_request`独立给出包含context创建、配置、bound与caller分配的首次请求成本，两者均在主计时外保留、验证并最终释放产物。Python在计时外解析、调度与收集，C/C++ driver内部循环围绕完整codec操作计时。codec自身恢复必需的header、参数、字典／模型、索引、tail与finalize全部计入`codec_complete_bytes`，实验JSON／hash／来源与纯ABI envelope另存；有效原始分母不含padding、扩宽或重复共享T。显式`native_api`和`object_memory / independent_object / natural`配置保留原有辅助目标。

最终统一构建37／37个真实CPU codec成功，raw-store由driver提供，共38个key。最终完整suite为**715 passed、0 failures／errors／skips，70.91s**，证据为[构建日志](build/verification/all-core/build-final.log)、[构建状态](build/verification/all-core/build-status-symbolic-final.json)、[测试日志](build/verification/all-core/pytest-symbolic-final.log)和[JUnit](build/verification/all-core/junit-symbolic-final.xml)。新增direct测试覆盖typed原始布局、tail、caller／owner生命周期、空encoder参数与无外部模型的独立恢复、损坏格式及容量拒绝；ABBA／fABBA encode-only修正有24项完整原生stream逐字节对照，不修改冻结vendor或旧对象API行为。

正式运行绑定统一执行源`sha256:9f67a210226e2432d848229b9742fbec0457b89ef905da4073f7ba3dfb830d08`，codec／driver构建、编译闭包、工具链及实际加载runtime身份保存在各run和[全量证据索引](docs/all_core_evidence.json)。[基础设计](benchmark/experiments/native-all/design.json)24配置／352请求与[神经补充设计](benchmark/experiments/native-neural/design.json)4配置／6请求分别保留冻结身份，28配置全部串行完成；正式计时不并行构建、测试、绘图或profiling。每个ready case为2 sessions ×7 rounds，内循环不是独立样本。

| 当前全CPU direct范围 | 实际结果 |
|---|---:|
| 冻结请求 | 358 |
| ready／完整有效case | 348／348 |
| unsupported | 10，逐请求保留原因 |
| 正式主trial | 4872／4872成功 |
| 额外attempt | 0 |
| 正式阶段压缩／恢复产物记录 | 48216对，含38472对正式操作与9744对warmup |
| exact资格压缩／恢复产物记录 | 3444对，含warmup |

统一严格审计已通过，`audit_passed=true`，日志见[report-audit.log](build/verification/all-core/report-audit.log)，结果入口为[全量原生报告](docs/all_core_results/README.md)、[逐请求覆盖](docs/all_core_results/coverage.md)及[逐案例CSV](docs/all_core_results/primary.csv)。38个key在两个生命周期均有共同输入的完整成功案例；不支持仍保留请求分母及原因，不能把成功覆盖外推为全部dtype、源域、任务、参数或资源支持。吞吐和空间只在相同任务／dtype／shape／layout／有效bytes／质量及资源条件下比较，prepared和fresh分列；不同case的合法案例总览不构成总体排名。审计复核保存的验证记录与完整压缩产物，未重新执行decoder；逐份恢复文件按协议删除后保留digest和计时外验证记录，[审计边界](docs/all_core_results/audit.md)明示该限制。

神经结果区分两份设计：基础64符号DeepZip／DZip短流每次编解码均0 predict／0 train，仅覆盖均匀概率与完整模型／容器成本；补充257符号完整fixture覆盖DeepZip biGRU及DZip BOOTSTRAP／COMBINED，每次encode和decode各193次预测。COMBINED另含1个128-window训练batch／1次Adam更新，其后65次预测使用更新权重；次数是源码推导值，不是动态counter，也不作为独立性能样本。DeepZip使用随库固定`biGRU.dzm`模型，prepared可预载而完整模型仍计费，本轮未确认其训练来源；DZip是按输入alphabet创建的seeded初始模型，每次encode重新初始化，在线训练及decoder重放照实计时，不能称导入预训练模型。这些结果是完整codec操作性能，不能称单独预测或训练内核吞吐。

§14.16历史诊断原文、§14.17首阶段2534trial、API／对象及GPU结果全部保留原身份。GPU的host_to_host与device_resident边界及严格质量失败不因CPU完成而改变。更广真实来源、跨物理机器／OS／ISA和独立第三方复现仍无本轮证据；当前结果限于已冻结输入、机器、参数与资源profile。用户指定的旧`build/reproduction-bundles/current-private-source.tar.gz`在当前checkout缺失，本轮未使用或验证，不能当本轮复现依据。

### 14.21 ALP / ALP-RD safe-v1 替换接入（2026-10-17）

按用户明确要求，原 ALP 旧 vendor／三项补丁和 forced decimal 接入已退出活动构建，替换前源码及未提交修改、codec card和来源登记先归档。消费同级独立工程 `alp-cwida-safe-v1-20261017` 发布包，56个文件按归档成员／SHA-256冻结，核心／公开API／ALPRW001格式保持原字节；alp现为adaptive ALP/RD，alp-rd为forced RD。新source／binding／build身份与旧结果分离，Python bridge拒绝旧同名库。完整说明和证据见[接入报告](docs/alp_integration/README.md)、[索引](docs/alp_integration/evidence.json)及[开发日志](docs/development.md)。

native_core使用真实`alp_port_*` API及完整ALPRW001输出，按输入C/F物理顺序处理标量流，两方向caller buffer。每次采样／内部复制／分配／padding／编码／序列化／CRC保持在调用内；prepared／fresh遵守§14.19边界。辅助C1／对象使用TAI1→APS1逐列完整frame并独立恢复，API空间主指标继续为null，不估计扣除适配目录。当前只开放portable（isa=SCALAR）、LP64 little endian、f32/f64、单调用线程和总2^24元素资源限制，不宣称满上限已实测。

本次重新验证：独立CMake reference ctest **3/3**；targeted **155 passed**；完整Python suite **798 passed、0 failures/errors/skips**。与独立新构建safe-v1完成 **284 case／10,004,036个处理值** 的完整字节一致、双向解码和C1 frame逐位恢复，另有28个reference CLI冷恢复；两个方法完整绑定／核心各22个sanitizer case通过，初次LSan ptrace退出失败与成功非ptrace重跑均保留。8个实际native边界／生命周期短批次组合逐产物验证；16个f32/f64×C/F×整块／分列分块对象组合均由新进程CLI恢复，保存重放脚本。

该结论是限定safe-v1的独立Bench接入资格，不签上游FULL_PARITY，不继承独立包AVX2／AArch64／TSan／fuzz或可复现构建资格。本次未重跑FORMAL吞吐；§14.20的715项suite与4872trial保持原源码时点，不能改签为新ALP实现的性能。更换核心／绑定／ISA／工具链／runtime后按实际依赖重新资格和测量。

### 14.22 Chimp 家族研究发布包替换接入（2026-10-17）

按用户明确请求，先完整阅读相关标准与独立包说明／报告，并建立N0接入计划，归档旧Chimp／Chimp128源码、卡片、共享shim及其未提交修改后，删除活动旧资产／分支和旧来源清单。消费chimp-family-research-20261017发布包，62个文件逐归档成员哈希冻结，核心保持原字节；没有展开整个133004条目发布包或修改共享硬链接。现注册chimp／chimp32／chimp128／chimpn／chimp128-no-index／chimpn32，以及PMC-MR和三个Swing方法，共10个key。Chimp128=ChimpN(128)，32/64位显式区分，FPC／filter2不开放。当前45个真实CPU codec另加raw-store；§14.20正式覆盖仍对应旧时点37+1。

默认native_core消费真实owning-vector API，输入暂存／对象创建／reset／帧序列化／重构与strict检查计时；结果独立生存至release。无损返回完整CFP1分块流，有损core限单列；辅助C1／对象CFS1容器按独立列保存完整CFP1，计入全部头／CRC／EOF／padding与列长度，解码不依赖编码器参数。有限f32有损路径使用单位索引时间轴，默认strict_abs按实际重构验证并拒绝源误差／非有限失败，compatible仅empirical_quality；不把源码阈值误当普适质量界或外部真实时间戳支持。

本次Bench独立验证：reference ctest 2/2；完整Python suite **962 passed**；最终新编译Java源码差分、存档基线重放、完整帧与独立CLI／Bench冷解码 **11537案例／5679407输入值**（含别名重复）。123个已知源码质量失败案例均strict拒绝；选择排除的未请求方法／非128窗口／外部时间戳和8个独立非PASS条目全部明示。40对象组合通过新进程CLI恢复；40组native core/API×prepared/fresh验证120份产物和独立冷恢复。实际最终绑定ASan+UBSan+LSan 64案例通过，detect_leaks=1、stderr为空；10个key各验证1048576值常量的编码／冷恢复并拒绝1048577。四个未替换核心的Elf／SElf入口重建并通过回归。配置、构建、源／runtime身份、边界和复现见[报告](docs/chimp_integration/README.md)、[证据](docs/chimp_integration/evidence.json)和[开发日志](docs/development.md)。

状态为LOCAL_RESEARCH_BINDING_QUALIFIED，保留独立包RESEARCH_REWRITE_VALIDATED与本地研究授权到2026-11-17的限定，不改签FULL_PARITY／REWRITE_DONE，不继承Clang／AArch64／fuzz／TSan／可复现构建资格。本轮未重跑FORMAL吞吐，所有历史run保持原身份。核心、绑定、参数、编译器、ISA或runtime变化时重新资格和测量；不为性能旁路原实现的分配或验证工作。


### 14.23 Sprintz 原生发布包替换接入（2026-10-17）

已按用户请求删除全部旧Sprintz活动实现／补丁／五登记及来源卡，仅接入新包四主键 sprintz-delta、sprintz-fire、sprintz-delta-huffman、sprintz-fire-huffman；不保留旧u8／fire-huff0别名，归档与历史设计原hash保留。当前44个真实CPU key+raw-store。

消费独立限定NATIVE_PORT发布包，1593文件核验且核心不修改。8/16位整数、1–128维、64KiB、Linux x86_64和明确ISA；baseline API与native ISA TU分离，path显式配置。native_core物理输入、caller输出；core／C1完整SZF1（24字节恢复头+原样payload）均计费，safe API内部暂存／scan／分配及序列化在计时内。冷decoder从帧恢复参数；16位raw尾字节修复与作者Huff0+1约定保持。

774源码差分（722字节一致、52修复／源截断拒绝）、76canonical／真实整数、32对象CLI、32原生组合96产物、96 ASan/UBSan/LSan绑定案例通过，完整Python1259 passed。未重跑FORMAL吞吐，不签完整FULL_PARITY，不继承独立包其它平台／TSan／fuzz资格；query等未验能力不开启。详见[接入报告](docs/sprintz_integration/README.md)、[N0计划](docs/sprintz_integration/PLAN.md)和[证据索引](docs/sprintz_integration/evidence.json)。

### 14.24 字节算法与 lzbench 的当前一致性审计（2026-10-17）

按用户请求，对当前 Zstd／LZ4／Snappy／zlib／Brotli／BZip2／XZ／LZSS／LZSSE2/8 审计同源性、真实调用边界、完整格式和独立源码交叉恢复；本节不替代已有接入资格或历史正式性能身份。606个vendor文件与固定lzbench fa871e66提交逐哈希相同，LZSSE派生源码安全补丁、Zstd／Snappy编译配置另记录。独立参考为未修改lzbench wrapper及同提交压缩库的单独构建，XZ库采用上游CMake，未运行性能主程序。

当前主路径702组组合、C1 110组均恢复通过；624组参考双向恢复含585组真实lzbench wrapper与39组补充LZ4F。另回放alexkazik原作282向量，现有相关测试127 passed。结论区分核心payload一致与完整格式／配置差异；不将LZ4 frame等同raw block、不忽略LZSSE8字节头、不忽略Zstd默认checksum或XZ编码API差异，两种LZSS亦不冒充该lzbench中不存在的对应实现。没有更换生产codec或补签FULL_PARITY／FORMAL；详见[审计报告](docs/research/lzbench_consistency_20261017/README.md)及其工件索引。

### 14.25 LZSS 异常排除（2026-10-17）

按用户明确要求，lzss-raw与lzss-dipperstein-c标记EXCLUDED，原因“算法接入异常，处于排除状态”。三边界准入、组件路由、显式构建及bridge加载／操作统一拒绝；默认选择、build --all和当前示例／生成器不纳入。CLI保留状态展示和来源查询，源码／原生工件／历史运行／冻结设计保留。LZSSE2／8未被排除；当前42个可用真实CPU key另加raw-store。专项142 passed；完整回归1255 passed、4 subtests passed，无失败／skip。详见[排除记录](docs/lzss_exclusion_20261017.md)。§14.24及历史性能仍对应排除前审计／实验身份，不能作为当前执行准入依据。


### 14.26 ABBA 家族重写发布包替换接入（2026-10-20）

用户授权删除旧ABBA/fABBA后接入ABBA/fABBA/QABBA。依[N0计划](docs/abba_family_integration/PLAN.md)归档旧源码/补丁/登记/共享配方/测试和indexes，移除活动旧分支；新消费发布包SHA ec70b59fd9e0a48303604596df43fa8e21090b6f577513f11894e727a6240b1e，7830成员核验且核心无修改。保留LGPL >=3 CKmeans、全部补丁/许可证及重链接源码。生产库静态包含字节库且仅导出绑定符号，实际CMake/Autotools依赖均记录；build使用私有副本，冻结源码不被Autotools改写。

主路径rank1 binary64 owning encode/decode，API/对象可矩阵独立列；全部AFS1和AFM1恢复信息计费，decoder不需编码参数或外部模型。拟合、分配、源encode内部重建、完整帧及额外原网格恢复检查均计时。单worker、FE_TONEAREST、无fast-math、关闭contraction；最多1048576总值、4096列、256MiB帧及源码工作预算。容差仅empirical_quality；QABBA恢复长度变化对象unsupported，禁止补点/重采样。未开放共享多序列模型/复用/图像等独立包其它路径。

187组26670值中144完整frame和双向恢复成功、43预期QABBA网格拒绝；120数据对象的99成功/21拒绝全部保留分母。重新执行源码数值对照、独立CMake参考与ctest1/1通过；12主边界/生命周期组合36产物、24对象新进程恢复、147绑定+共享发布核心ASan/UBSan/LSan案例通过。最终完整Python1387 passed、4 subtests passed、无失败/skip。当前43可用真实CPU key+raw-store，LZSS两项继续排除；新实现状态BENCH_BINDING_QUALIFIED_LIMITED_SCOPE，不继承独立FULL_PARITY/跨架构/fuzz/OOM资格，历史FORMAL结果不改签，正式吞吐未重跑。详见[报告](docs/abba_family_integration/README.md)及[证据](docs/abba_family_integration/evidence.json)。
