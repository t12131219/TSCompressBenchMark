# TSBench V4.0 框架结构与执行流程

绘制日期：2026-10-13。依据：[V4.0 工程实施总计划](../../TimeSeries_Compression_Benchmark_V4.0_工程实施总计划.md) §3–§11。CPU object_memory 主路径已实施；外部进程pool、native边界实验及source-cluster统计为独立工具，复用对象／bridge协议而各存执行身份。cuSZp GPU plugin 已完成 host_to_host 与 device_resident formal 路径；图中的 GPU 节点对应真实执行器，具体分母、质量失败和身份见总计划 §14 及 GPU run。stream/query仍为未声称的设计扩展。

图中 V / T / mask 分别代表数值、时间戳与有效性标记；wire 是包含恢复描述、payload 和必要依赖的序列化产物。实线表示核心关系或流程，虚线标注可选扩展、独立 profiling 或父进程异常补记；每条虚线的具体含义以标签为准。

## 1. 模块结构

![模块结构](architecture.png)

[SVG 矢量图](architecture.svg)。三个核心职责是 **bridge 调 codec、scheme 产完整对象、executor 落实计时和完成**。worker 是进程隔离单位，codec session 是每个独立对象的状态生命周期，二者不可混用。

```mermaid
flowchart TB
  cfg["一份 experiment.toml<br/>方法、对象、质量、边界、资源 profile"] --> cli["CLI / config<br/>解析与展开默认值"]
  sources["数据源<br/>npy / CSV / source catalog"] --> data["data<br/>canonical V / T / mask 与身份"]
  assets["保留 codec 源码 / 模型"] --> build["registry / build<br/>能力、factory、构建库"]
  cli --> runner
  data --> runner
  build --> runner
  subgraph parent["父进程"]
    runner["runner<br/>case 矩阵、schedule、预算、恢复"] <--> cache["资格缓存<br/>implementation / exact-input"]
  end
  runner -->|"按 schedule 调度 / IPC"| executor
  subgraph worker["隔离 worker：method × resource profile × session"]
    executor["executor<br/>CPU wall；边界、生命周期、资源与完成"] -->|"encode 计时"| scheme["scheme / artifact<br/>适配、组合、Finish、完整 wire"]
    executor -->|"decode 计时"| decoder["DecoderRegistry<br/>wire → 新 decoder session → 恢复对象"]
    scheme -->|"wire + 已计费依赖"| decoder
    scheme --> bridge["bridges<br/>C ABI v1 / RW ABI v1"]
    decoder --> bridge
    bridge --> native["构建后的 CPU native codec"]
    decoder --> verify["validate：计时外<br/>恢复 / 质量 / 输入不变性"]
  end
  data -->|"原始对象：验证端使用"| verify
  build -->|"库、factory、能力"| bridge
  verify --> records["records / run artifacts<br/>manifest + observations.jsonl + 代表 wire"]
  runner -.->|"crash / timeout 等父进程补记"| records
  records --> report["report / study<br/>描述、覆盖与失败；配对与source-cluster统计"]
  records -.->|"读取 manifest，另开 pass"| profile["可选 profiling<br/>RSS / 显存 / perf / 能耗"]
  profile -.->|"独立 profile 结果"| report
  extension["P4 GPU plugin<br/>cuSZp opaque owners / completion"] --> executor
  extension --> gpu_native["独立 CUDA native API<br/>DeviceInput / payload / decoded ownership"]
  gpu_native --> verify
  pool["独立 process pool workload<br/>cold/persistent；任务完成 wall"] --> scheme
  pool --> decoder
  pool --> records
```

CPU/GPU executor 使用各自真实 API。GPU 插件不能把 device 指针传给现有 host C/RW ABI；上图中的 C/RW bridge 是当前保留资产的路径。CPU 的 ISA／内部线程属于实现和资源因素，不能从 CPU 支持 SIMD 或配置写了线程数推定已经执行该路径。

## 2. 一次实验的运行流程

![运行流程](workflow.png)

[SVG 矢量图](workflow.svg)。图展开一个比较 block/session 内的主流程，runner 对完整矩阵重复相应准备和调度。首版同一时刻只有一个主计时任务；不同方法可以有独立待命 worker。

```mermaid
flowchart TB
  config["读取一份配置"] --> resolve["解析对象 / 方法 / 质量 / 边界 / profile<br/>展开请求 case 矩阵"]
  resolve --> available{"静态能力与环境支持？"}
  available -->|"否"| casefail["保留 case 与真实原因<br/>unsupported / unavailable"]
  available -->|"是"| prepare["建立 method / session worker<br/>在 pool、设备初始化和 first-touch 前落实资源政策"]
  prepare --> load["加载实际库与当前 block<br/>核验有效线程 / affinity / NUMA / backend"]
  load --> resource{"有效资源符合比较条件？"}
  resource -->|"否"| resfail["拒绝当前 profile 或显式另建资源层<br/>记录原因；重建对应 case / schedule"]
  resource -->|"是"| hit{"两种资格缓存的所需项都命中？"}
  hit -->|"否：只补缺项"| qualification["必要 implementation suite / exact-input 检查<br/>输入检查含 wire-only 新进程恢复"]
  qualification --> passed{"资格通过？"}
  passed -->|"否"| qfail["真实资格失败 / 不可执行 case<br/>保留 stage、reason 与证据"]
  passed -->|"是"| savecache["保存 PASS 范围与资格缓存"]
  savecache --> warmup
  hit -->|"是"| warmup["计时粒度诊断 / 校准<br/>本 worker 预热，丢弃预热 codec session"]
  warmup --> schedule["最终可执行 case 的随机 round schedule<br/>保存实际 schedule 与 resolved manifest"]
  schedule --> start["父进程记录 planned / started<br/>按 schedule 发出 trial"]
  start --> encode["encode 计时<br/>对象 → 完整 wire；本次 encoder 关闭完成"]
  encode --> decode["decode 计时<br/>wire → 新 decoder session → 完整恢复对象"]
  decode --> verify["计时外验证<br/>恢复、原始域误差、输入未改变；记录 bytes / hash"]
  verify --> valid{"验证通过？"}
  valid -->|"是"| ok["ok + 原始 encode/decode 时间<br/>大小、质量与实际资源"]
  valid -->|"否"| error["error + stage / reason<br/>quality_violation 是 reason；已测时间仅作诊断"]
  encode -->|"native 返回错误"| error
  decode -->|"native 返回错误"| error
  start -.->|"父进程持续监控；异常可发生在任意 stage"| abort["crash / timeout / 有证据的 oom<br/>失效 worker 不复用；GPU 恢复未确认则设备余项 not_run"]
  ok --> raw["追加 JSONL 与必要工件<br/>历史 attempt 不覆盖"]
  error --> raw
  abort --> raw
  casefail --> raw
  resfail --> raw
  qfail --> raw
  raw --> more{"runner 还有待执行计划项？"}
  more -->|"是"| ready{"对应 worker 就绪且健康？"}
  ready -->|"是：既定下一 trial"| start
  ready -->|"否：新 case/session 或失效 worker"| prepare
  more -->|"否"| close["关闭剩余 worker / session<br/>设备停用后已记 not_run 的项不再调度"]
  close --> report["读取 raw 生成描述报告<br/>覆盖 / 失败 / 条件性能；可选推断"]
  report -.->|"同 manifest，独立 pass"| profile["可选资源 profiling<br/>附加独立结果，报告可重生成"]
```

静态支持检查只是提前拒绝显然不支持的 case；实际内容域、资源和动态资格仍在后续确认。不支持 case 不生成虚假的重复 trial；计划可执行后未运行的 trial 保留 not_run。资源不符时不能沿原资源层继续比较；另建层后重新生成相应条件和调度。当前 GPU formal 中 f32 大输入的严格质量违例就是这种 admission failure，成功 case 与失败分母分开报告。

核心重复箭头从“写入 raw”经安全调度回到健康 worker 的“下一 trial”，不回到完整资格套件。case 拒绝只推进其他 case；新 case/session 或失效 worker 需要准备／重建，按内容身份查询资格复用范围。GPU 恢复未确认时结束该设备 session、余项记 not_run，不继续该设备测量。资格命中不能跳过正式编码、独立恢复或逐 trial 验证。retry 增加 attempt，resume 补未完成项，均保留历史失败。

## 3. 单个 CPU trial：数据与计时边界

```mermaid
sequenceDiagram
  participant W as Worker / executor
  participant S as ObjectScheme
  participant B as C/RW bridge + native codec
  participant D as DecoderRegistry
  participant V as Validator
  participant R as Records
  Note over W,R: canonical 对象已就绪；库加载、资格与预热已完成
  rect rgb(231, 241, 255)
    Note over W,B: encode_ns：t0 → t1
    W->>S: encode_once(original)
    S->>B: 本次状态、适配、bound、encode、必要 Finish
    B-->>S: payload / 实际长度 / 状态
    S->>S: descriptor、依赖与完整 wire；关闭 encoder
    S-->>W: EncodedObject(wire)
  end
  rect rgb(234, 247, 241)
    Note over W,D: decode_ns：t1 → t2
    W->>D: decode_once(wire)
    D->>D: 解析描述；新建 decoder session
    D->>B: 只用 wire 与已计费依赖配置恢复
    B-->>D: decoded components
    D->>D: 逆变换、完整对象；关闭 decoder
    D-->>W: 拥有独立有效存储的 restored
  end
  W->>V: original + restored；输入 fingerprint
  V-->>W: bitwise / quality / input unchanged
  W->>R: 时间、完整 bytes、wire hash、实际资源、终态
  Note over D,V: decoder 不拿 original、encoder context 或免费配置
```

正式 trial 的新 decoder session 可以位于同一 worker。新 decoder **进程**属于未命中的 exact-input 独立恢复资格检查，不是默认每个 trial 的开销。默认刚生成的 wire 不表示冷 cache，natural 只表示不主动干预缓存。

GPU 扩展保留同一逻辑：先 quiesce，再从 submit 计到 complete；所选边界需要的传输、status、materialize 与独立对象 teardown 均完成后停止 wall timer。device-event 时间作为独立细分指标，不能代替 host_to_host 完成时间。

## 4. 与计划的对应关系

| 图中部分 | V4.0 计划依据 |
|---|---|
| V/T/mask、case 与公平条件 | §3 |
| 独立包、bridge/scheme/executor、两 ABI | §4 |
| wire、依赖和完整大小 | §5 |
| encode/decode、生命周期、GPU completion | §6 |
| 两资格缓存、worker、随机 round、失败恢复 | §7 |
| 一份配置、有效资源与 inspect/build/run | §8 |
| 正确性与质量验证 | §9 |
| JSONL、覆盖与失败、描述／研究统计 | §10 |
| 线程／SIMD／GPU／pool 与独立 profiling | §11 |

最小实现从 raw-store + zstd-frame + lzss-raw 的对象闭环开始（P0），随后补两 ABI／对象能力与可靠重复（P1/P2）。资源扩展按 P4 接入，不成为首轮 CPU 有效测量的前置条件。

两张静态图由 [render_diagrams.py](render_diagrams.py) 生成 SVG，使用 Pillow、Noto Sans CJK 字体与 `rsvg-convert` 生成预览；上面的 Mermaid 是可编辑的逻辑图源。重新生成命令在仓库根目录执行：

```bash
python docs/diagrams/render_diagrams.py
rsvg-convert docs/diagrams/architecture.svg -o docs/diagrams/architecture.png
rsvg-convert docs/diagrams/workflow.svg -o docs/diagrams/workflow.png
```
