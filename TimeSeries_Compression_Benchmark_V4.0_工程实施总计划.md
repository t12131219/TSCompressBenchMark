# TSBench 4.0：时序压缩标准测试协议与 Python 框架实施计划

版本：4.0。设计日期：2026-10-12；实施更新：2026-10-13。状态：CPU 主路径、三源长度／误差梯度、native 边界对照与第二软件环境已实测，实际证据及扩展范围见 §14。§1–§13 的设计要求仍有效。

目标论文：**各类时序压缩算法在各类时序数据上的标准测试**。这里的“标准”指公开、可执行、可复现的测试协议与基准套件，结论限定于所声明对象、方法、质量和资源条件。

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

ALP 论文的300K内循环只测一个L1驻留vector，第一阶段row-group采样不在该微测量内；完整COMP才包含。本轮固定源码的Release驱动为30K，论文实验与该代码快照分别记录。nvCOMP样例的device event排除输入传输、配置和分配；NVBench的cold仍预热且主要处理L2缓存。它们分别回答具体问题，不能拼成一种通用“压缩时间”。

### 1.2 论文需要回答的五个问题

| RQ | 问题 | 需要的实验，而非仅有接口 |
|---|---|---|
| RQ1 | 哪些数据特征改变算法适用性和条件排名？ | 跨独立来源、dtype、长度、UTS/MTS、规则/不规则时间的空间/速度/覆盖 |
| RQ2 | 完整恢复成本会怎样改变方案选择？ | payload与完整产物对照；短/长对象；timestamp/mask、模型/字典和共享scope消融 |
| RQ3 | 计时边界和资源环境会怎样改变结论？ | native API与对象路径；scalar/SIMD、线程；GPU驻留与主机完成路径 |
| RQ4 | 同一质量目标下有损方案如何取舍？ | 原始域质量阶梯、约束违例、rate-quality-speed前沿；明确保证类别 |
| RQ5 | 结论有多少来自实现、输入变换或调参？ | 原版/移植/重写身份；必要的布局、分块、默认参数与开发集选择消融 |

拟验证的贡献是：typed时序对象和独立恢复协议、完整成本与同边界测量、失败覆盖与分层实验，以及这些选择对实际算法结论的影响。协议的价值要通过对照和消融证明；提交前继续核查相关工作，不预设“首个”或唯一总体排名。

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
| 最小闭环 | raw-store、zstd-frame、lzss-raw | 真正原生调用、完整长度/descriptor、Finish、独立恢复 |
| 浮点与两ABI | chimp128、alp-rd、ABBA | 源域拒绝、block/forced scheme、RW frame与经验质量 |
| 误差与SIMD | serf-qt、zfp-accuracy-1d、sprintz-fire | ABS原始域验证、特殊值/tail、真实整数/ISA路径 |
| 其余保留资产 | 按能力分批，含fABBA、DeepZip、DZip、SIMDComp | 模型、线程、词表、primitive及格式限制 |

`alp` / `alp-rd` 目前为forced decimal / forced RD，不能称完整自适应ALP。SIMDComp目前是primitive；DeepZip词表0..3不代表一般浮点域；fABBA binding当前固定1线程；DZip存在持久Eigen workers。GPU从官方可构建实现另行接入，当前保留资产没有已接入GPU成员。退出或未完成方法另走新接入，不恢复来凑数量。

## 3. 先确定比较对象，再生成实验矩阵

### 3.1 原始对象与恢复任务

canonical对象由具名组件构成：V可以是float32/64或整数，T可以是int64或声明的其他原生类型，validity可以是有明示语义的mask。保留shape、字节序、C/F顺序、列/通道、时间单位、采样与series边界。第一版支持UTS、同步MTS；异步/ragged保持独立series和关联关系，不静默填成同步矩阵。

| task | 必须恢复的内容 | 原始字节分母 |
|---|---|---|
| values | 声明的V；若声明validity也必须恢复mask | 所需V与mask的canonical bytes |
| timestamps | 声明的T与其顺序 | T的canonical bytes |
| records | 所有声明的T/V/mask及schema语义 | T/V/mask bytes之和 |
| component | 同一实际typed输入的primitive/API结果 | 该实际输入bytes，另存对应原始对象分母 |

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

### 3.3 公平条件是投影，不是所有身份相等

观测完整保存method族、variant、implementation、参数、backend、环境及attempt。比较组只包含其RQ需要的公共条件：

- 完整对象比较：同raw_object、恢复/质量目标、工作负载、计时边界、生命周期与缓存政策。允许不同合法表示和方案结构，全部转换/恢复成本计入。
- native API比较：同实际输入dtype/layout/内容、同恢复目标及API起止/准备条件；不混入完整对象表。
- 环境内比较：资源profile相同。CPU/GPU部署比较可以资源不同，但显式列出CPU、GPU、host辅助核和内存预算，用相同用户任务与完成边界回答部署问题。
- SIMD/线程消融：同来源、对象和受控实现路径，改变声明的ISA/线程因素；其他变化另记，不归因给单一因素。

方法ID不进入“所有成员必须相等”的比较键。完整对象分组不以codec_input_id排除合法byte/bitcast方案；native API分组也不能以相同source-file名字掩盖输入精度不同。

运行前生成选定case矩阵，case包含对象/task/method/质量/边界/profile。支持检查后为可执行case生成trial schedule；不支持case记录原因，不伪造七次运行。报告分开显示请求case总数、可执行case数与其计划/完成trial数，未执行case同样在原矩阵中。可显示共同有效子集，但不能把事后共同成功子集称原计划总体。

## 4. 一个独立 Python 包，三个清楚的职责

模块结构、实验流程与单 trial 计时边界见 [V4.0 框架结构流程图](docs/diagrams/README.md)（2026-10-13）。

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
    executors/                  cpu.py；后续gpu.py、object_pool.py
  tests/                        有意义的协议与真实adapter测试
  examples/                     小型配置；论文配置按RQ另列
```

新包从声明的asset root读取现有native源码/模型，不依赖旧控制面。Python最低版本与论文锁定版本分开；GPU依赖选与其SDK实际兼容的解释器。统计/绘图、Parquet、GPU SDK属于extras，核心不要求全装。无需通用DAG调度、远程服务或dashboard才能运行。

三个职责分别是：bridge正确调用真实codec；scheme产生可恢复的完整对象；executor落实边界、计时与完成。简单codec直接包成一个scheme，额外能力才扩展；stream/query不用空壳方法冒称支持。

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

RW frame已有模型/参数时直接计其wire bytes，不重复加模型账单；外层只补其缺失的对象语义。C1 payload不能自动视为自包含文件：shape、tail、参数或其他恢复信息由新scheme保存。准确入口依据本仓库 [C头文件](native/include/tscb_adapter_v1.h) 和 [RW头文件](adapters/completed_rewrites/native/binding.hpp)。

## 5. 完整产物：保存以后仍能独立解码

### 5.1 wire和依赖

第一版采用小型versioned envelope：固定magic/版本/descriptor长度 → UTF-8 JSON descriptor → 具名payload/dependency区。descriptor包含组件角色、dtype/shape/order、codec/format版本、必要解码参数、精确长度、chunk table、逆变换信息及依赖hash/offset/length。非JSON可精确表达的参数用明示binary区或精确编码，不通过pickle保存。

统一envelope不意味着重写每种native格式。保留native frame，外层只补独立恢复所缺信息；包装成本真实计入，另外显示payload-only诊断。decoder不接收original、原配置文件、其shape模板或encoder context。共享库作为已安装的解码程序，模型/字典作为数据依赖，二者计费政策分别说明。

```python
import json
import struct

PREFIX = struct.Struct("<8sHI")
MAGIC = b"TSB4OBJ\0"
MAX_DESCRIPTOR_BYTES = 16 * 1024 * 1024

def pack_bundle(descriptor: dict, body: bytes) -> bytes:
    header = json.dumps(
        descriptor, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    if len(header) > MAX_DESCRIPTOR_BYTES:
        raise ValueError("descriptor too large")
    return PREFIX.pack(MAGIC, 1, len(header)) + header + body

def read_bundle_prefix(wire: bytes) -> tuple[dict, bytes]:
    if len(wire) < PREFIX.size:
        raise ValueError("truncated prefix")
    magic, version, n = PREFIX.unpack_from(wire)
    if magic != MAGIC or version != 1:
        raise ValueError("unknown wire format")
    if n > MAX_DESCRIPTOR_BYTES or n > len(wire) - PREFIX.size:
        raise ValueError("invalid descriptor length")
    end = PREFIX.size + n
    descriptor = json.loads(wire[PREFIX.size:end])
    if not isinstance(descriptor, dict):
        raise ValueError("descriptor must be an object")
    return descriptor, wire[end:]
```

这段为最初 wire 版本 1 的设计示例，仅示范envelope的prefix与packing，**不是完整decoder或完整校验器**。当前 wire 版本 2 的 descriptor checksum 实现在 `benchmark/src/tsbench/artifact.py`，实测以 §14 及 actual prefix 版本为准。实现时还需限制dtype/rank/shape乘积、解压总量、依赖数量，核对区间、实际used bytes、格式参数和checksum策略；decoder资源限制与worker timeout仍有效。模型提取或嵌套native frame的分解需有实际格式依据。

### 5.2 大小、分母与模型

完整单对象成本是最终wire的实际长度，加它必须依赖的外部文件及序列化索引；空对象仍有真实固定成本。最大输出capacity、scratch、原始输入和decoder程序不当作压缩存储体积。payload/header/model/dictionary/index/tail分解只在可核实时报告，互斥字节区间防止重复计费；精确总bytes始终必须可重算。

默认standalone模式包含所需模型/字典。另做shared模式时先声明共享scope、对象集合和依赖内容hash，同时报告未摊销成本与按scope只计一次的总体成本。native frame已嵌入模型却无法实际移出时，不能算成免费共享模型。压缩包/模型下载体积与解码后文件实际占用分开，选定口径明确。

```text
stored_fraction       = complete_stored_bytes / task_raw_bytes
compression_ratio     = task_raw_bytes / complete_stored_bytes
bits_per_value        = 8 * complete_stored_bytes / recovered_V_scalar_count
bits_per_timestamp    = 8 * complete_stored_bytes / recovered_T_count
encode_MiB_s          = task_raw_bytes * 1e9 / encode_ns / 2**20
decode_MiB_s          = task_raw_bytes * 1e9 / decode_ns / 2**20
```

timestamp-only的bits_per_value为null。records的bits/value含T/mask成本并显式标注；MTS的value count为标量元素数，不是行数。分母为0或time≤0的派生指标用null并记录原因。source CSV大小、codec_input_bytes、H2D/D2H实际copied bytes另存；传输带宽用copied bytes，codec吞吐用任务原始bytes。

第一版records组合只做具名channelwise + fixed independent chunks，例如 `zstd(T)+chimp(V)+raw(mask)` 与 `zstd(all components)`。包含所有索引/拼接/descriptor和时间，不能称Chimp原生timestamp算法。raw-store使用相同envelope；另列原始裸bytes作为参考，二者含义明确。

## 6. 时间边界、运行时与缓存分别定义

### 6.1 主边界

| boundary | 编码段 | 解码段 |
|---|---|---|
| object_memory（默认CPU） | canonical对象就绪→本次create/reset、适配/分配、编码、Finish、最终wire及关闭本次encoder session | wire就绪→新decoder配置/解析/分配、解码、逆变换、完整对象及关闭本次decoder session |
| native_api | 已准备input/context/output容量→具名native API实际完成 | 已准备payload/context/output→具名API完成；准备状态另存 |
| device_resident | 已准备device输入→完整device artifact可用；必要metadata位置明示 | device artifact→完整device对象可用 |
| host_to_host | host对象→配置/分配/适配、H2D、GPU工作、大小/status、D2H最终wire与本次独立session关闭完成 | host wire→独立配置/解析、H2D、GPU恢复、D2H完整host对象与本次独立session关闭完成 |
| gpu_to_host | device对象→完整host wire与完成 | 另声明解码的输入/输出驻留 |
| file_end_to_end | 源文件读取/解析→编码并写最终文件 | 最终文件读取→恢复并写目标数值对象；声明cache及flush/fsync |

bridge的FFI、布局copy、bound、必要模型读入、包装和逆变换属于对象段。进程启动、共享库加载、canonical数据准备、资格/校准/预热、验证与报告不在object_memory内，另报run总wall开销。API内部重新读模型/算bound的工作照实计时；resident-model优化是另一个明确实现/生命周期。

### 6.2 独立的三条轴

1. **residency/boundary**：输入、压缩产物、恢复输出分别在哪里，何时真正可用。
2. **lifecycle**：默认已预热worker、每对象新codec session；另有明确的reusable buffer/manager/model、fresh process或持续stream。保存setup/load/reset成本。
3. **cache_policy**：默认natural，表示不主动操纵cache，不保证warm或cold。CPU/GPU缓存干预单列策略及证据；新进程也不保证清掉共享cache/page cache。

默认object_memory可以在已预热进程中保持对象独立；预热session丢弃，预测/模型在线状态不得流入下一独立对象。fresh-process启动延迟用父进程wall另设边界，明示启动、import、上下文、IPC及输出返回成本，不能拿它的结果替代默认对象段。

CPU用 `perf_counter_ns` 的monotonic wall，内部线程必须完成/join；主线程CPU consumed time仅作profiling诊断。下面是默认CPU示意，输入不变性和错误包装由外层实现：

```python
from time import perf_counter_ns

def measure_object(scheme, decoders, original, verifier):
    t0 = perf_counter_ns()
    artifact = scheme.encode_once(original)
    t1 = perf_counter_ns()
    restored = decoders.decode_once(artifact)
    t2 = perf_counter_ns()
    verification = verifier(original, restored)  # 不计入encode/decode
    return {
        "encode_ns": t1 - t0,
        "decode_ns": t2 - t1,
        "stored_bytes": artifact.stored_bytes,
        "verification": verification,
    }
```

默认decode使用本次刚生成的wire，独立于encoder状态，但不宣称产物或cache冷。保存后读取的解码性能另设artifact-origin条件。短输入诊断Python/FFI空调用开销，不从实测值减掉估计开销；研究native内核时使用另边界的native timer/薄batch helper。

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

输入预检产生真实产物，另启动decoder进程；该进程只拿wire、解码实现及已计费依赖，不拿original或encode配置，父/验证端核对恢复。旧输入的cold recovery不授予新输入资格。正式round仍编码自己的输入、用新的decoder session恢复并验证自己的wire；缓存不跳过这些工作。

报告样式/统计代码变化只影响analysis identity。binary、相关bridge、validator、实际backend/runtime或依赖变化仅失效受影响缓存；不冻结整个Python控制面。缓存保留PASS范围与证据，timeout/OOM/缺库等瞬时失败不缓存成永久不支持。

### 7.2 worker 和 round 的具体生命周期

每个 `(session, method, resource_profile)` 使用独立worker进程，避免native崩溃影响主进程。default资源profile内主计时顺序运行：即使存在多个待命worker，同一时刻只有一个计时任务。大型矩阵分组启动/关闭worker，控制待命内存；策略写入resolved记录。

一个session的顺序是：加载实际库与数据 → 未命中的必要资格 → 校准timer粒度 → 在本worker预热并丢弃其独立codec session → 执行预先生成的随机round → 关闭worker。下一session新建进程。临时资格/校准进程已预热，不能当作测量worker已经预热。

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

第一版object_memory固定loops=1，校准记录时钟/空调用诊断和本次段长，过短时告警并保留raw，不用包住verifier的外层循环冒充纯encode/decode批时间。更多重复仍是明确round预算，不改level/block/model/误差。batch仅作为后续native_api/device helper扩展：须分别测encode/decode batch totals、保留有界数量真实产物供计时外验证、记录实际loops/输出数/验证范围和session reset政策。每个operation的实际产物都须有恢复／质量验证覆盖，不能只验证最后一份。batch仍只有一个外层sample；不把循环次数当独立样本，内存预算不足时减少loops或拒绝该扩展。

工程起步为1session×7rounds、每worker2个warmup objects；这是可修改默认，不是科学充分性阈值。论文pilot按变异、独立层次与预算决定更多sessions/rounds，确认后固定；不根据赢家追加到显著。

### 7.3 真失败、超时和恢复

parent先写planned/started事件，worker返回终态；被native杀死仍由parent补crash/timeout等。CPU/GPU任务都设置具名timeout和可实施的内存限制，能力不足的平台报告限制未实施。SIGKILL单独不能证明OOM，只有错误码、OS/cgroup或设备证据才标oom，否则保留signal和未知原因。

终态分为 `ok / unsupported / unavailable / error / crash / timeout / oom / not_run`，另有stage/reason，例如encode.finalize、decode、validation、quality_violation、budget_exhausted。unsupported描述合法域限制；unavailable描述库/ISA/设备无法取得。error的已测时间只作诊断，不参与性能摘要；恢复未通过不能写ok。

resume补尚未完成项；retry增加attempt，不覆盖旧失败。论文不得只留成功attempt作主结果，retry政策事前声明。保留截断JSONL尾行及标记，在可确认有效前缀后恢复，不能假装整run已完成。预算耗尽的计划项仍有not_run终态和原因。

GPU异常/timeout后由executor清理failed context及其拥有的工作/资源，并核对该设备可继续使用；新worker的quiesce不能证明上一失败context已经干净。无法确认时停止该设备session，余项记录not_run及device_recovery_unconfirmed；不自动重置影响其他任务的整设备。

代表/失败wire按hash保存，失败产物有真实内容时才保存；随机编码可配置更多保留比例。默认不落盘每个巨大wire，但每trial记录hash与实际长度，stream方法按自己的产物/验证政策另定义。

## 8. 一份配置即可开始

这是首个values实验的目标配置。`temperature.npy`由使用者准备，示例不暗示已有数据或本机运行成功。npy已有dtype/shape，不隐式转float64。配置省略字段用小型明确默认并在resolved中展开；未知字段/未知参数给具体错误。

```toml
schema = "tsbench.experiment/1"
name = "float-values-pilot"
output = "runs/float-values-pilot"

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
id = "chimp128-b1000"
codec = "chimp128"
params = { block_size = 1000 }

[[methods]]
id = "alp-rd"
codec = "alp-rd"
params = {}

[task]
kind = "values"
fidelity = "bitwise"
boundary = "object_memory"
lifecycle = "independent_object"
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

[analysis]
summary = "median_iqr"
inference = "none"
```

profile请求与effective资源分开：没有真实thread knob或固定后台workers不匹配时，拒绝该profile或明确放入另一个有效资源层，不能说明后仍进入cpu-single/同预算线程scaling结论。相同profile_id本身不证明实际资源相等；不能填effective_threads=1伪装。`workers`不作为模糊总开关：object_workers表示并发工作负载，测量session进程仍顺序调度。profiling默认关闭，用同一resolved实验另开pass。

```bash
# 以下核心 CLI 已在 CPU 首版实现；实际支持边界和可复跑配置见 §14。
python -m tsbench build zstd-frame lzss-raw chimp128 alp-rd
python -m tsbench inspect experiment.toml
python -m tsbench run experiment.toml
python -m tsbench report runs/float-values-pilot
python -m tsbench profile runs/float-values-pilot/manifest.json
```

inspect只展开任务/参数、支持与数据/环境信息，不偷偷执行正式测量。build固定source/recipe/compiler/flags与产物hash，输出到 `build/tsbench/<build-id>`；资格缓存按内容键保存。无需用户手写额外资格、发布或冻结合同。

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

固定算法/参数仅诊断计时粒度（首版loops=1，后续批测量才校准loops），不需要development corpus。外部选择codec、level、block、model或研究者调参用独立开发/评价来源、实体或时间段，相关窗口不跨界泄漏。模型seed、开发数据与选择预算在评价前固定。

ALP内部采样、FIRE在线更新是实际编码工作，计入请求段；decoder状态从格式正确恢复。独立对象边界reset遵循真实算法语义，SElf*/Serf-XOR的连续状态不得为并行任意切断。

训练另报数据、时间、硬件/能耗与模型大小；默认压缩请求不包含一次完整训练，但模型加载/推理属于其声明边界。单对象standalone与显式共享scope摊销一起报告，不选择最有利摊销点作唯一结果。DeepZip扩至一般符号/浮点词表映射属于新具名pipeline，映射表/模型和成本全部计入。

## 10. 原始结果与统计，不用失败制造排名

### 10.1 自动生成的最小结果目录

```text
runs/<run-id>/
  manifest.json           输入配置+resolved矩阵/schedule+数据/方法/环境身份
  observations.jsonl      计划/开始/终态及phase；原始时间、验证、失败
  artifacts/              代表/失败wire和必要依赖
  report/                 描述表、覆盖、可选推断与图
  profile/                另一次资源profiling及其identity
```

用户只维护一个配置。manifest保存确切resolved参数、source/build/bridge/wire/validator/measurement代码身份、相关动态库/模型和环境。Git revision/dirty摘要用于复现，报告代码仅进analysis identity，不把整个checkout内容冻结成执行资格。

```json
{
  "schema": "tsbench.observation/1",
  "phase": "measurement",
  "run_id": "example-only",
  "case_id": "temperature/chimp128-b1000/cpu-single",
  "task": "values",
  "raw_object_id": "sha256:example",
  "codec_input_id": "sha256:example",
  "transform_id": "identity",
  "implementation_id": "sha256:example",
  "profile_id": "cpu-single",
  "boundary": "object_memory",
  "lifecycle": "independent_object",
  "cache_policy": "natural",
  "session": 0,
  "round": 2,
  "sequence": 1,
  "attempt": 0,
  "loops": 1,
  "status": "ok",
  "stage": "complete",
  "raw_bytes": 8000,
  "codec_input_bytes": 8000,
  "stored_bytes": 3264,
  "encode_ns": 150000,
  "decode_ns": 120000,
  "verification": {"passed": true, "fidelity": "bitwise"}
}
```

这只是schema示例；其他字段可通过case_id关联manifest得到，避免每行重复巨大配置。另存environment identity、实际backend/资源、产物hash、质量与实际模式。失败行同样关联case、attempt、stage/reason和可取得的诊断。warmup/calibration标phase，不能混入measurement统计。

### 10.2 两层报告

默认describe给每对象完整大小、median/IQR、mean/std、实际样本数、完成/计划数、边界和覆盖/失败；单次结果仅给实际描述。部分round失败时，成功时间摘要明确标为“成功条件下的性能”，同时显示ok/计划trial数及超时/质量违例等；不能将截掉慢失败轮次的median称总体请求性能。report读取raw可重新生成，不执行codec，不要求infer通过才能看到结果。min可作最好情况辅助，不是唯一主结果；噪声告警保留全部raw，不默默删慢值。

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

- 总存储率：按声明scope计算 `sum(stored bytes) / sum(raw bytes)`；共享依赖只在该scope计一次。对象等权typical ratio另表，明示统计量。
- 总吞吐：`sum(w_i * raw_bytes_i) / sum(w_i * representative_time_i)`，对象权重及代表时间如median事前声明；或者用各方法相同session/round矩阵的累计bytes/time。重复预算不同不能改变数据权重。
- 成对speedup：同条件absolute time之比；跨source可给预先权重的geometric mean，同时保留每对象时间与coverage。不同环境绝对吞吐不直接平均成算法总分。
- 随机编码大小/模式同样记录分布。retry成功、被排除样本或完整case选择均有规则与敏感性分析，不替换原失败历史。

首批论文图：size/encode/decode Pareto、rate-quality-speed曲线、分领域结果、成对speedup区间、失败覆盖矩阵、payload/完整成本与边界消融。综合分数只有在明确部署权重和敏感性分析时才有意义。

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

## 12. 从第一轮代码到论文套件

阶段以真实可运行行为完成，不堆积版本签发条款，也不承诺固定小时数或性能倍数。

| 阶段 | 编码与交付顺序 | 完成证据 |
|---|---|---|
| P0：最小对象闭环 | 独立pyproject/config → raw-store → zstd/lzss C1 bridge/build → envelope → wire-only decoder/verifier | 新包不import旧包；落盘wire在新进程恢复；真实失败能记录 |
| P1：数据与能力 | npy/CSV/records对象 → capability/predicate → chimp128/alp-rd/RW-ABBA → bitwise/质量/成本 | 两ABI可用；tail/源域/输入不变性有测试；frame/模型不漏计 |
| P2：可靠重复 | parent/worker与JSONL → 两cache → 校准/warmup/schedule → timeout/resume → describe | 命中缓存不重跑suite；每round验自己输出；crash也有终态；profile默认关闭 |
| P3：论文CPU基础 | source catalog/解析/窗口 → values/T/records组合 → error梯度与开发选择 → 配对/分层报告 | 固定matrix/scope；有效分母；raw可重建表图；直接native交叉核对 |
| P4：资源扩展 | 真实thread/ISA → external pool → 一个真实GPU成员host/device → 视RQ加stream/query/profile | completion/status/实际资源有证据；同任务scaling；无能力明确拒绝 |
| P5：复现与投稿 | 第二环境 → build/environment lock → 数据获取/许可 → 原始结果/图脚本 → 独立复跑 | 每论文数字追到raw；公开命令覆盖所声称实验；限制与失败完整 |

第一轮只要求P0完成，随后P1/P2；不会因36个codec、全部数据、GPU或完整统计尚未接入阻止第一次有效运行。records成本在P1进入，不永久只做values。每阶段一个小demo、一种真实失败和针对本阶段风险的测试；完整suite属于接入CI，不在每trial运行。

关键测试：ctypes布局/ownership/越界与释放；Finish语义；输入不变；独立decoder无encoder状态；shape/dtype/model/逆变换与完整大小；特殊值/tail/质量违例；内容hash缓存及相关失效；crash/timeout/OOM证据/retry；调度与统计层次；report变化不失效测量。使用真实codec交叉验证，mock仅用于调度/故障机制。

## 13. 论文实验包与框架自身验证

### 13.1 主实验与扩展实验分工

| 实验 | 主要主张 | 最低应交付的结果 |
|---|---|---|
| 核心无损 | 相同typed对象的空间/速度/覆盖 | values、T、records各条件表与全部状态 |
| 核心有损 | 相同质量语义下的取舍 | actual质量、violation/infeasible、rate-quality-speed |
| 完整成本 | payload-only可能误导部署选择 | 短/长对象、metadata/model/shared scope消融 |
| 边界与绑定 | Python/native/device差异的实际含义 | 匹配输入/时钟条件的直接native对照；对象开销拆解 |
| 多环境 | 线程/ISA/GPU何时有效 | 环境内speedup与scaling；主机/设备完成对照；实际资源 |
| 可选任务 | 仅对论文声称的stream/query/downstream/energy | 真实工作负载、状态/质量/延迟/资源，不由普通压缩结果推导 |

框架至少用若干代表codec与直接native调用对照输出、字节数和相同计时起止；验证薄bridge的归因，量化Python/packing的规模效应；至少在第二种环境复现主协议。当前native移植/重写与upstream差异单独说明，不能把所有实现差异归因于理论算法。

保留实现是第一批实验成员。P3时核对它们是否足以覆盖各RQ，以及TerseTS等相关工作所代表的强竞争方法；确需新增成员则固定来源单独接入，不能仅以“已有36key”证明研究覆盖。新方法/模型依赖和许可不成为其他已可运行实验的全局门槛。

### 13.2 公开复现内容

复现包包含数据source/license/version/hash与获取/解析脚本、窗口/任务与开发评价划分、codec/variant/source/build/模型依赖、各环境信息、单份实验配置及resolved matrix/schedule、raw JSONL和代表产物、图表/统计代码、失败/预算/retry与排除政策。不能再分发的数据提供可核对hash和取得方式。

论文图表每个数字可关联 `run/case/session/round/attempt`。绘图重生成不执行codec；修改报告逻辑可生成新的analysis记录，原测量保留。论文覆盖只按实际完成实验声称，不以GPU/stream接口预留代替运行证据。

日常最短路径始终是：**一份配置 → 相关资格复用 → 计时校准与本worker预热 → 重复完成编码／独立恢复／验证 → raw与描述报告**。接入CI、研究统计、资源profiling、论文复现与发布各自承担任务，核心框架不引入新的全局验收台账。

## 14. 2026-10-13 实施事实、实现选择与验收入口

本节记录此次从零重建的事实，不将研究设计的全部扩展自动标成已完成。软件包版本 `tsbench 0.1.0`、typed wire 版本 2（兼容读取历史版本 1）、C ABI 版本 1 与 RW ABI 版本 1 分别管理。

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
