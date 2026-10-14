# V4 从零设计研究记录：时序压缩、异构环境与计时边界

研究日期：2026-10-12。目的：为 Python Benchmark 新框架确定可解释的输入、状态、计时和资源口径。本文只记录本轮重新联网取得的原始论文、官方文档和固定版本源码；不将已有 TSBench 的流程或旧计划视为设计依据。**事实**指可在指定原文位置直接查到的内容；**设计推论**是据此提出的 V4 取舍，不冒充论文共同标准。

## 1. 阅读范围与可复核身份

本轮重新下载材料位于 `/tmp/tsbench_v4_research_20261012/papers_b/`。PDF 经 `pdftotext -layout` 提取，并与 arXiv HTML 正文对照；关键图表另用系统 Poppler 渲染查看。以下“全文”包括正文、算法、表格说明、结论和参考文献，不声称逐一打开并阅读被引用的所有论文。

| 材料 | 版本及本轮阅读范围 | 原始入口 |
| --- | --- | --- |
| Sprintz: Time Series Compression for the Internet of Things | arXiv `1808.02515v1`，23 页；全文。另视觉核验 PDF 第 15–16 页的统计比较、吞吐图和 SIMD 说明 | [PDF](https://arxiv.org/pdf/1808.02515v1)、[HTML](https://arxiv.org/html/1808.02515v1) |
| cuSZ: An Efficient GPU-Based Error-Bounded Lossy Compression Framework for Scientific Data | arXiv `2007.09625v1`，13 页；全文。另视觉核验第 9–10 页的 Table VI–IX 和 rate-distortion 图 | [PDF](https://arxiv.org/pdf/2007.09625v1)、[HTML](https://arxiv.org/html/2007.09625v1) |
| Gorilla: A Fast, Scalable, In-Memory Time Series Database | VLDB 2015，12 页；本轮定向重读 §4.1–4.2 和 §5–6，含 Figure 2–8 的文字与说明；不将此次定向阅读称为全文重读 | [PDF](https://www.vldb.org/pvldb/vol8/p1816-teller.pdf) |
| nvCOMP high-level C++ quickstart | 官方在线页面，本轮全文阅读 API 生命周期、两种解码配置来源、bitstream kinds、batching 和 checksum 说明 | [文档](https://docs.nvidia.com/cuda/nvcomp/samples/highlevel_cpp_quickstart.html) |
| nvCOMP low-level C quickstart | 官方在线页面，本轮全文阅读工作区、chunk 约束、异步返回和逐 chunk 状态、解码尺寸发现、可关闭状态/OOB 检查 | [文档](https://docs.nvidia.com/cuda/nvcomp/samples/lowlevel_c_quickstart.html) |
| NVIDIA/nvcomp | `f0f982e1965da56f12b4253ed57549ec98cdab87`；完整读取归档 README，确认官方示例已迁移 | [固定 README](https://github.com/NVIDIA/nvcomp/blob/f0f982e1965da56f12b4253ed57549ec98cdab87/README.md) |
| NVIDIA/CUDALibrarySamples/nvCOMP | `07c4f09223302ce4310eef945ed458e092598d17`；benchmark README 全文，`benchmark_hlif.cpp/.hpp` 全文；共享 chunked 模板重点逐行阅读 327–518、577–830，common helper 83–156，CMake 的 NVBench 依赖定义 | [固定目录](https://github.com/NVIDIA/CUDALibrarySamples/tree/07c4f09223302ce4310eef945ed458e092598d17/nvCOMP/benchmarks) |
| NVIDIA/NVBench | **实际 sample 依赖** `4a33a61591666f48cb5fd714d00d7d2df5977ff1`；`docs/benchmarks.md`、cold timer core、cold `.cuh`、hot `.cuh/.cu`、CPU/CUDA timer 和 `state_exec.cuh` 全文；cold `.cu` 定向阅读初始化、样本记录、停止条件和计时摘要至第 385 行 | [固定目录](https://github.com/NVIDIA/nvbench/tree/4a33a61591666f48cb5fd714d00d7d2df5977ff1) |

GitHub API 本轮触发限流后，用 `git ls-remote` 确认仓库 HEAD，并从 `raw.githubusercontent.com` 下载固定 commit 文件。NVBench 最新 HEAD 是 `16761f0bf755ba53889a4a964997bcd906b07582`，**没有将这个最新版当成 sample 使用的版本**：sample 的 CMake 第 149–163 行固定了上述 `4a33…`。

## 2. Sprintz：应借鉴实验分解，同时公开数据变换

### 2.1 原文事实

- §2 及 §4：输入是每行一个 sample 的多变量整数序列，算法主要处理 8/16-bit 整数；小块通常为 8 个 sample。小块是算法自身格式的一部分，不是 benchmark 为摊薄计时噪声而创造的循环单位。
- Algorithms 1–3（PDF 第 6–9 页）：FIRE 的预测系数状态、累积梯度和前值从确定状态开始，在编码中在线更新，解码同步更新。§4.2 的学习率 `1/2` 来源于 preliminary experiments。
- §5（第 12 页）：单线程、2013 Macbook Pro、2.6 GHz Intel Core i7-4960HQ；时长和吞吐取十次中的最佳值。这里没有给出独立进程次数、CUDA/运行时冷启动、置信区间或普适预热规则。
- §5.1（第 12 页）：文本先转连续 numeric array，计时前载入主存。85 个 UCR 数据集各自拼接短序列，并在相邻序列间插入五个线性插值样本。浮点输入按 min/max 缩放后 floor 到 8/16-bit 整数。多变量竞争方法获准逐列处理，Sprintz 处理 row-major；作者明确说明这相当于给竞争方法无限缓冲，属于对竞争者乐观的设置。
- §5.2–5.3（第 13 页）：压缩比实验里 Zlib/Zstd 选 level 9，因为该实验不惩罚压缩时间；85 数据集上的算法总体秩采用 Nemenyi，FIRE 对 delta 这一配对假设采用 Wilcoxon signed-rank。两种统计方法分别服务不同问题。
- §5.4–5.6（第 15–17 页）：速度实验用一亿个覆盖整数全域的随机值、1–80 列；不能整除的尾部采用 memcpy。完整压缩原型在 §5.5 **没有 vectorize**；单独 FIRE 预测器 §5.6 使用向量化；解压跨变量 SIMD。不能给整个“算法名称”贴一个 SIMD 标签就认为压缩和解压具有相同 ISA 路径。
- §5.7–5.8（第 17–20 页）：真实数据用于 ratio-speed 权衡；整数化浮点是有损变换。论文明确没有借量化实验声称 Sprintz 是最佳浮点压缩算法，并讨论 GPS/时间戳的精度风险。

### 2.2 对新框架的推论

1. 数据谱系要记录原始 source、canonical numeric representation、变换参数、产生的 sample 数和字节数。原始浮点量化为整数后再无损压缩，只能称“变换后表示无损”，同时报告对原始数据的误差和反变换 metadata。
2. 不能默默复制插值、跨独立序列拼接、逐列布局重排。数据任务可以指定这些操作，但必须让所有方法获得同一逻辑输入，或明确列为不同 workload/adapter pipeline，并计入恢复所需信息和转换成本。
3. 固定算法内部在线适应属于编码工作。其解码可复现状态、一次性码本/预测状态的存储、每次 trial 的状态重置，比强制为它创造一个“模型训练集”更重要。用研究者开发集选择 FIRE 学习率，与运行时在线更新，是两个不同问题。
4. 不照搬“best of 10”为所有实验唯一主结果。保留每次原始时长，按研究问题报告描述统计及跨数据集比较；数据集是总体比较单位，trial 不是新的独立数据集。
5. 最小 baseline 之外，用独立 workload 检查通道数、布局、小批延迟、算法内部块大小及 ISA；不能把一份随机输入的吞吐当成所有真实时序的速度。

## 3. cuSZ：GPU 驻留、传输和误差不能被一个 throughput 隐藏

### 3.1 原文事实

- §III：预测和量化采用 dual-quantization，后续有 histogram、codebook、编码、deflate 等阶段。1D/2D/3D 预测块分别考虑 `32`、`16×16`、`8³`；Huffman deflate/inflate chunk 另有实验扫参。它们是不同层次的块。
- §IV-A（第 7 页）：V100、两颗各 20 核 Xeon Gold 6148、PCIe 3.0 ×16、CUDA 9.2；使用 CUDA 默认 profiler 测 kernel time。测试 SDRBench 的五类科学模拟数据，维度 1D–4D，各数据集只用一个 snapshot，合计报告 112 fields；单 field 超出显存时分块处理。
- §IV-B1 与 Table VI（第 8–9 页）：选 chunk/并发量是具体 V100 与数据上的经验结论；不能把“约 2e4 GPU concurrent threads”改写成一般硬件标准。
- Table VII（第 9 页）：单独列 kernel compression、GPU-to-CPU 和 overall compression。第 8 页明确 overall compression 加入 **GPU-to-CPU** 传输，目标情境为数据本来产生在 GPU，压缩后经 CPU 落盘。没有依据据此宣称包含 Host-to-Device 或实际文件写盘。
- 所有 throughput 都以**原始未压缩字节数**作分子。Nyx 的 cuSZ kernel、D2H effective、overall compression 分别约 `41.1`、`134.1`、`31.6 GB/s`；`134.1` 是按原始体积折算后的有效速率，不是 PCIe 实际传输 payload 的带宽。
- §IV-B1（第 9 页）：OpenMP-SZ 32 CPU cores 基于分块顺序 SZ，只支持 3D；1D/2D/4D 是 `N/A`。GPU thread 的工作量和 CPU thread 的工作量没有对应关系。
- §IV-B2、Figure 6–8（第 9–10 页）：cuSZ 采用 error-bound 模式，cuZFP 采用 fixed bitrate，使用 rate-distortion 曲线和 PSNR 比较；不能认为固定 bitrate 等于相同 pointwise max error。PSNR 定义是 `20 log10((max-min)/RMSE)`。
- 本版本论文没有充分说明完整 trial 重复数、运行顺序、预热、精确 CUDA-event 区间和 CI；正文 kernel launch/synchronization 的实现讨论不能填补这些报告空白。

### 3.2 对新框架的推论

- 至少需要 `device-resident` 与 `host-to-host` 两种可选择、可独立汇总的任务。前者回答在 GPU 内存中处理数据的性能；后者回答主机输入、主机可消费输出的端到端成本。GPU 设备时间可作为细分指标，两者之间不直接合并排名。
- host-to-host encode 需要 H2D 输入、算法必要处理、压缩长度/metadata 获得、D2H 完整压缩结果以及完成等待；decode 需要压缩输入 H2D、必要解析和解码、原始结果 D2H 与等待。文件读取/落盘是另行明确定义的 file-I/O workload。
- 若 pipeline 重叠传输和计算，记录真实完成墙钟，不能把阶段时长直接相加当成端到端实测，也不能以各阶段最佳值拼装一次不存在的 pipeline。
- 标明 `throughput_original_Bps` 与 `transport_payload_Bps`；统一十进制 GB/s 或明确 GiB/s。压缩体积、原始体积和单位必须可还原。
- error-bound 验证独立实现并针对完整恢复数据。ABS、range-relative、pointwise-relative、固定 rate、PSNR target 的可行域不同；符合约束的点才可比较速度/存储，跨 error semantics 使用 rate-distortion/Pareto 描述。
- 科学场数据不因“连续 numeric array”就自动是时序数据。纳入 TSBench 时，数据 catalog 必须标明 time axis 与空间/通道语义；若是空间 field，就作为明确的扩展任务，不能冒充时序覆盖。

### 3.3 Gorilla 对输入与状态边界的补充

Gorilla §4.1（PDF 第 4–6 页，出版页 1819–1821）每个 data point 是 64-bit timestamp 和 64-bit double value；timestamp 用 delta-of-delta，value 用前值 XOR 和前一个有效 bit window。只压缩同一 series 内部，不跨 series 压缩；两小时 block 的第一条记录与 block header 构成恢复入口。Figure 6 的两小时选择源于生产数据上存储收益与范围查询解码成本的权衡，不是一般 benchmark 应硬编码的 chunk 常数。

§4.2（PDF 第 6–7 页）查询复制整个 compressed block 给 client，由 client 在 Gorilla 外解压。因此 Figure 8 的系统 query latency 不能当成独立 codec 解压吞吐。§4.4、§6 的容灾/部分数据可用性是数据库系统要求；允许系统故障丢小量数据，不能推导 lossless codec 可少恢复数据点。

对新框架的推论：分别定义 values-only、timestamps-only、timestamp-value pair 任务，后者的分母和 artifact 都包含两个数据域。values-only 方法可组合共同 timestamp codec，但组合后的执行时间与完整体积需要实测、明确报告。序列边界与重置规则属于 workload；避免将多个无关 series 拼接后允许状态传播，再把压缩收益归因于单条时序。对于 range decode，要报告解码的完整内部 block 和返回范围，不能只用返回字节数掩盖需要额外解码的工作。

## 4. 官方 nvCOMP sample：明确哪些成本在计时之外

### 4.1 当前官方入口与计时事实

归档 `NVIDIA/nvcomp` README 将源码入口迁到 `NVIDIA/CUDALibrarySamples/nvCOMP`。benchmark README 提供 file、chunk size、GPU、重复数、compressed inputs、输出 compressed/decompressed chunks 等选项；独立命令 round-trip 会按 chunk 顺序恢复并与原始文件 `diff`。

共享模板 [`benchmark_template_chunked.cuh`](https://github.com/NVIDIA/CUDALibrarySamples/blob/07c4f09223302ce4310eef945ed458e092598d17/nvCOMP/benchmarks/benchmark_template_chunked.cuh)：

- `run_compression` 默认 `exec_tag::no_batch`（约 350–371 行）；输入合法性、H2D、对齐、最大输出尺寸、temporary workspace 查询与分配都在 `state.exec` 前。
- `state.exec` lambda（约 449–464 行）调用异步 batched compressor。立即返回状态检查表示调用成功；之后才将逐 chunk 状态与最终大小拷回 host 检查。压缩 payload D2H 和文件输出在计时区之后（约 466–517 行）。
- `run_decompression` 在计时前发现输出尺寸、同步、分配工作区和输出（约 588–692 行）；lambda（约 697–712 行）只调用 batched decode。
- device 的 hardware Decompression Engine 可能从 host 视角同步提交，样例在约 714–733 行自动加 `exec_tag::sync`，避免 NVBench blocking kernel 造成虚假 deadlock。因此 GPU backend 必须写清 `CUDA` / `hardware DE` / `best available`，自动选择也要记录最终实际 backend。
- 计时后逐 chunk 检查状态、尺寸，并 D2H 逐字节验证，或调用有损验证（约 736–811 行）。OOM 以明确错误/退出记录，不是某个虚构 throughput。

high-level sample [`benchmark_hlif.hpp`](https://github.com/NVIDIA/CUDALibrarySamples/blob/07c4f09223302ce4310eef945ed458e092598d17/nvCOMP/benchmarks/benchmark_hlif.hpp) 本轮全文核验：

- manager 在读取和调用 `run_benchmark` 前构造；H2D、compression configuration、GPU 分配、event 创建都在正式事件区间外。
- 压缩/解压各执行一次预热并同步，然后重复测量；两次 event 同 stream，结束后 `cudaStreamSynchronize`，event elapsed time 为主结果。compressed-size 获取在事件测量之后，decompression configure 与 output allocation 在解压循环之前。
- 最后才 D2H 并比较原始值。CLI 默认重复数 `1`，不是自动为论文建立充分重复。
- `-m` 打印的解压 memory 标签虽写 `input+output+temp`，当前源码表达式仅加 `decomp_bytes + comp_out_bytes`。不能照抄这个输出为完整内存成本；manager 内部分配的 temporary/state 仍应独立记录或测量。

### 4.2 解码身份与状态来源

官方 high-level guide 给出两种 `configure_decompression`：

1. 从压缩 buffer 解析：可能要读 GPU header，API 明确同步 user stream；RAW LZ4 等甚至需要解析整个 compressed buffer。
2. 从仍存活的 `CompressionConfig` 构造：host 已持有配置，因此不需要该同步。

设计推论：后者是有效的配套使用路径，但若论文研究“可独立恢复的存储”，正式解码需要从保存的压缩 bytes 和已计入体积的 metadata/模型重新建 decoder，不得无意共享 encode session 的未保存状态。可将 config-reuse decode 作为明确的补充任务，报告其不同前置条件。一次性 qualification 至少要有独立 decoder round-trip，不必每个 timing trial 都重跑完整边界套件。

官方 low-level guide 还明确：`CompressAsync` / `DecompressAsync` 返回成功表示成功 launch，不保证每个 chunk 成功；逐 chunk status 与恢复校验不可省掉。某些格式将 `device_statuses=nullptr` 会关闭 OOB 检查、提高 CUDA 解压吞吐。新框架必须声明库内 validation/checksum 策略，默认受检查路径与 unchecked 路径不可混为同一个实现配置。Benchmark 的离线正确性校验仍独立保留。

## 5. NVBench：三个时间标签的源码含义

下表均针对 sample 实际固定的 `4a33…`，不是仓库任意新版本。

| 名称 | 源码实际边界 | 对 TSBench 的含义 |
| --- | --- | --- |
| cold / isolated GPU measurement | cold timer core 先 `flush_device_l2` + `sync_stream`，随后开 CPU timer、blocker/频率采样，再 CUDA start；stop 时 CUDA stop、unblock、stream sync 后关闭 CPU timer。cold `.cuh` 仍先执行 warmup | “冷”主要是每次 L2 cache 处理，不是 fresh process、driver/context 或新 manager |
| `nv/cold/time/cpu/*` | `cpu_timer.cuh` 第 48–57 行采用 `std::chrono::high_resolution_clock::now()` 前后差 | 主机经过时间；不是进程/thread 消耗的 CPU 时间；包括这条测量路径中的控制与等待 |
| `nv/cold/time/gpu/*` | `cuda_timer.cuh` 在选定 stream 放 start/stop event，`cudaEventSynchronize(stop)` 后读取 elapsed time | 设备 event 时间，只有被 stream 顺序/依赖覆盖的工作才受测量 |
| hot / batch GPU measurement | hot `.cuh` 先一次 warmup，用其估计 batch 大小；一对 CUDA events 内重复 launch，整批完成后同步；均值是累计 CUDA time / 累计 executions | 连续提交下的批次平均值，不等于单次请求延迟 |
| `nv/batch/walltime` / `nv/cold/walltime` | 整个测量循环的 host wall time | 包含试验控制，是测量工作耗时；不可改名为单个 codec workload 的端到端时间 |

`state_exec.cuh` 在没有 explicit measure tags 时，`no_batch` 选择 isolated/cold 而不编译 hot。`sync` 和 manual `timer` 都禁用 batch；官方指南要求所有 GPU 工作在 `launch.get_stream()` 执行，或和该 stream 建立依赖。文档也提醒参数维度组合爆炸，建议聚焦 sweep；这支持使用较小的默认 workload 加显式扩展矩阵，不支持所有环境全量交叉成为唯一入口。

NVBench cold 源码含频率阈值检测、丢弃 throttled trial 和恢复等待。**不能据此给 TSBench 发明所有机器适用的噪声阈值或默默丢样规则**。新框架应保存原始失败/样本、检测值与排除原因；预先声明排除准则和敏感性分析。

## 6. V4 可采用的最小可解释计时契约

下列为本轮设计推论，而非某篇论文原样规定。

### 6.1 三条独立轴

```yaml
measurement:
  residency: host_to_host        # 或 device_resident；输入和输出位置必须完整定义
  lifecycle: steady             # 或 fresh_process；注明 runtime/manager 是否包含
  cache_policy: natural         # 或显式 cpu/gpu cache 操作；不能等同于 lifecycle
  clock: completed_wall         # 主机 monotonic elapsed；device_event 是额外指标
  decode_origin: persisted      # 或 session_config_reuse，后者独立标识
```

`fresh_process` 只是生命周期标签；启动 Python/native worker 是否计入时间，要另行定义“程序启动到输出可用”的边界。`steady` 也不允许继承上一条序列的自适应编码状态，除非 workload 本来定义连续流。缓存干预本身通常属于准备阶段，但其方式、对象和保证能力要报告。

### 6.2 测到完成，而不是测到提交

统一主计时使用 monotonic host elapsed wall clock。CPU 多线程 operation 必须 join 所有参与 worker；GPU operation 必须等所有相关 streams/device work 完成。只同步一个不覆盖 hidden internal streams 的 stream 无法证明完成，应由 adapter 提供覆盖全部工作依赖的 completion，或在独占 GPU 场景使用明确的 device sync。

下面只是语义草图，adapter 的实现需要依据对应库的完成保证：

```python
from time import perf_counter_ns

def measure_completed(operation, input_view):
    # 先清理上次 operation 的 pending work；不继承未完成任务。
    operation.quiesce()
    start_ns = perf_counter_ns()
    pending = operation.submit(input_view)
    result = pending.complete()   # join / GPU wait / obtain required sizes and metadata
    elapsed_ns = perf_counter_ns() - start_ns
    return result, elapsed_ns

# 根据 residency 定义，complete 返回 host bytes 或完整 device artifact。
# equality / error verification 在计时之外执行，但本次结果必须被实际校验。
```

`device_event_ns` 可以同时记录作为 GPU 细分；不用 device event 替换可跨 CPU/GPU 解释的 completed host wall time。CPU consumed time、RSS、显存、功率与 hardware counters 属独立 profiling run；不强制采样器侵入正式主计时，不用采样器扰动差异阻断所有压缩实验。

### 6.3 reset、setup、分配与 storage

- per-operation 不可避免的动态分析、header 解析、码本生成、在线更新、编码/解码内部工作属于 codec 时间。共享输入加载、与配置无关的 benchmark bookkeeping 和离线 fidelity verifier 在主段之外。
- reusable scratch/pool 的首次建立可在 steady workload 准备中发生，但声明 `allocation_policy` 并另报 setup cost。若普通 API 每次 operation 本来会分配，不能通过改造而默认去掉该成本；可以提供注明预分配要求的另一种路径。
- compressed artifact 包括 payload、codec header、chunk index/lengths、layout/shape、缺失值掩码、反变换参数、必要字典/模型。工作区和最大输出容量属于峰值内存，不是保存体积。
- 共享离线模型按明确 corpus/workload 记一次总大小，并同时报告 amortized 和未摊销数字，不能默认外部免费。训练/研究者调参报告时间、开发数据、冻结模型身份。测试输入因因果在线编码被观察，不自动构成开发集泄漏。
- 正式重复需按 workload reset 编码状态和输入；warmup/calibration 得到的学习状态不流入测试 trial。只估计计时循环大小的 calibration 不需要“独立开发数据集”，但它不能选择 codec 参数/质量。
- batching 是摊薄计时分辨率的工具；batch 内每次必须完成同一个逻辑任务并采用同样 reset 语义。不能为了凑最低时长偷偷重复/拼接数据、切断 stream 依赖或更改 compressed artifact 的数量。

### 6.4 三种 chunk 需要不同字段

| 层次 | 控制对象 | 公平比较注意点 |
| --- | --- | --- |
| codec internal block | Sprintz 八样本块、cuSZ predictor/Huffman block | 算法/实现参数，计入版本和参数，不要求所有算法内部块相同 |
| workload chunk | 独立可解码片段、GPU 超显存分段、流消息 | 改变状态范围、随机访问和存储 metadata；必须显式定义是否保留跨 chunk 状态 |
| timing batch | 为一个 timing sample 重复逻辑 operation | 不改变数据/codec 语义，不把 batch iteration 当成独立统计样本 |

固定相同外部 chunk 大小是一个有用的任务；允许每种算法自行调 chunk 是另一任务，必须报告开发预算和参数来源。也可提供共同 latency/memory budget 下的配置 Pareto，比强制内部块相同更有研究价值。

## 7. 资源公平与覆盖范围

1. CPU 比较明确单核、分配物理核集合、SMT、NUMA/affinity、实际线程数与线程库；scalar/SIMD 用独立 implementation variant 和 operation 级 ISA 标识。编译 flag、CPU ISA support 不等于证明实际使用指定向量路径。
2. GPU 比较明确具体 device、显存、driver/runtime、host assist 核/线程、streams、backend（含 hardware DE）、H2D/D2H 内存类型与 interconnect；GPU thread 数不能与 CPU thread 数对齐构造“相同线程公平”。
3. 公平性的主要依据是**同一可恢复数据、任务语义、质量、存储口径和资源配置的透明性**。CPU/GPU 跨资源对比回答系统预算/场景问题，可展示 Pareto；不强行给所有机器、ISA、GPU 产生单一算法排名。
4. Unsupported、timeout、OOM、decode mismatch、error-bound violation、process crash 都是原始结果。保留实际执行/尝试的分母、缺失原因和覆盖率；不把不支持的维度或被排除的数据点静默从平均排名删去。
5. 默认资格检查只覆盖宣称支持的输入类型/边界、可独立恢复与质量。版本、adapter、输入语义或关键环境变化后失效相应资格；不因为报告 renderer 变化而重新冻结整条执行路径。

## 8. 可直接使用的源码核验清单

| 原始路径 | 已确认的事实位置 |
| --- | --- |
| `CUDALibrarySamples/nvCOMP/benchmarks/CMakeLists.txt:149` | 固定 NVBench `4a33…` |
| `benchmark_template_chunked.cuh:350` | 默认 `exec_tag::no_batch` |
| `benchmark_template_chunked.cuh:449` | encode 被计时的 lambda |
| `benchmark_template_chunked.cuh:466` | timing 后逐 chunk status |
| `benchmark_template_chunked.cuh:697` | decode 被计时的 lambda |
| `benchmark_template_chunked.cuh:714` | hardware DE host 同步分支 |
| `benchmark_template_chunked.cuh:751` | decode 状态校验 |
| `benchmark_template_chunked.cuh:780` | 恢复内容校验 |
| `benchmark_hlif.hpp:81` | encode warmup 和同步 |
| `benchmark_hlif.hpp:101` | encode CUDA event 区间 |
| `benchmark_hlif.hpp:157` | decode CUDA event 区间 |
| `benchmark_hlif.hpp:150` | memory 输出未显式计入 manager 内部 scratch |
| `nvbench/detail/measure_cold_launch_timer_core.cuh:100` | L2 flush、同步与起始 timer 顺序 |
| `nvbench/detail/measure_cold_launch_timer_core.cuh:137` | event stop、同步与 host timer stop 顺序 |
| `nvbench/cpu_timer.cuh:48` | high_resolution_clock 的 host elapsed timer |
| `nvbench/cuda_timer.cuh:59` | 指定 stream 上 events |
| `nvbench/detail/measure_hot.cuh:149` | warmup 后估计批次大小 |
| `nvbench/detail/measure_hot.cu:96` | batch CUDA 累计值 / executions |

以上是阅读指针。真正实现新 adapter 时，还需固定所安装 binary/library 的版本与 API，不能把示例仓库 commit 当成 nvCOMP binary 的版本。

## 9. 下载与源码 SHA-256 清单

```text
sprintz_v1.pdf                    ee5a98097bb3b1c70b5e0e0d27ba6c9fb08d0ead094080cd66358146c1410f70
sprintz_v1.html                   fb6b8a21c5511c329f56f67f027a7da6de81e6b3080940e4e30da3915fc6c620
cusz_v1.pdf                       56e18b8592b686fbc5a343441bf632a0993901bebec26fd04ba3c2f90993d660
cusz_v1.html                      fd6fbed4a03e84d5cdb5a5a0f181c84df3c2d07da2fb952b53bbd7755a2c65ca
gorilla_vldb2015.pdf              fb906c0295115ba0013fa4db8fb2eadd0e7a57d2d212ee546ed3b56f14db3259
nvcomp_cpp_quickstart.html        d6a3dd531ec0d8adf46fc91d53a3863de1e46f06d8b55b60ea939c2dd1ef1ead
nvcomp_c_quickstart.html          acd529e31b1e2075d4f9aac32663b93dcf3d2e438fd61dc5f853c1ddc6874c72
nvcomp_archived_README.md         c113829583058f61317ff08ba0db08e0a925bcec6b5011b3cd24289c93b3b28d
nvcomp_README.md                  716d2067f5c636ea20b2878aaad964a1d57d53fe6d5c92b08827237bf25b7468
nvcomp_benchmark_template_chunked.cuh 7c3233bcdb6e489d6003469233307fcd0bf9c84d398b177fed83ad84f3b3049e
nvcomp_benchmark_hlif.cpp         321e81ed6ea8f3dd5d9b8b1581e9afe36c0a3caf252f56c3a603edd8589c1b94
nvcomp_benchmark_hlif.hpp         a51876352216eb5403f455cc7506ca7d6552598039e0af2466c3897d5edeb58f
nvcomp_benchmark_common.h         68e3fb0cf002d621500a44276feedefbfac2ac47b2f5db232f2747a9073aa083
nvcomp_CMakeLists.txt             ade18789839fd6bf40b9ffaec87238eb123dde525a5e76709bce0f708547aeed
NVBench docs/benchmarks.md        0590fd6c939c65251e5c8758bf57f9099b826f4cda48d9b9a0ff49dbb06fda33
NVBench detail/state_exec.cuh     95c7eba4be0ededf6656afd5ef03a7e86f2cf43eeb318dcddb7113df6e82f76a
NVBench detail/measure_cold.cuh   7ab90904517683d8f5f955ca551689e3d57d30f5a8088e240bec6385bcaf7569
NVBench detail/measure_cold.cu    a63e1324c42d42baf7dfcf8b0da9869b3ff11df4888e4df7e50bbcbf33bcc638
NVBench detail/measure_cold_launch_timer_core.cuh 1523fc1bff5fd396d27126889bce6aa9e3a49d353fb6787400ee7d176cd88e24
NVBench detail/measure_hot.cuh    f0c87040a6d6746aaa8adada6a9f8f3ff65c11b959207b88126a919e4cd7a696
NVBench detail/measure_hot.cu     41fc474fc2901ee5b0857d8d75c64726a1ed67f2373b83e240c0418a3d2cbc9c
NVBench cuda_timer.cuh            6998f0a386551207272cae09c13df3daad7ba305f6d5a72dd5efa4451dde91f7
NVBench cpu_timer.cuh             5d8f1b3174e8cbaa806da8bf41eefdc4a8399268ae61e5760def0463a795f0fa
```

限度：本轮完成论文阅读与源码计时核验，没有运行这些 GPU benchmark，也没有测量本机 GPU 可用性、真实性能、采样扰动或显存峰值。文中的 V4 契约为待实现和验证的设计参考。
