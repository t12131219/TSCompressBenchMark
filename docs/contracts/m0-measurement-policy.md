# M0 计时、计费与验证政策：进程与原生批候选边界

[配置](../../configs/profiles/measurement_policy_v1.json)经[本地 schema](../../schemas/measurement-policy.schema.json)
校验后进入 `bmk native-plan`，并由 `m1_lossless_candidate_v2` 的 `smoke-plan` 锁定配置、schema 与监督器源码摘要。
进程观测用于 M1 候选闭环；原生批观测用于验证稳态/冷上下文和同工作量对照。**两者都不是正式性能计划，也不授予阶段或算法资格。**

## 可执行的候选剖面

| 字段 | `process_frame_preflight` 的实际含义 |
|---|---|
| `frame` / `process` | 每次 encode/decode 各启一个新进程。从父进程调用 `Popen` 前到子进程被 `wait` 回收后，使用同一个单调墙钟。包括启动、动态加载、读取已准备的文件、上下文与原生处理、序列化/写文件、输出诊断和退出。不等同于纯 codec 时间、稳态吞吐或从原始 CSV 加载到恢复的端到端时间。 |
| `reset_per_message` / `copied_return` / `result_ready` | 不复用 codec 或模型状态；插件返回对象由 worker 写成文件并释放。成功的子进程退出时完整结果应可消费，父进程另行检查实际文件及其字节。Linux `waitid(..., WNOWAIT)` 通知后回收，不用 20 ms 睡眠轮询来估算完成时刻；监督和调度开销仍在进程边界内。 |
| `artifact_each` / `outside_extent` | 规范化及写入 staged 输入在开始前；encode 后移除 staged 原始值和 schema。新进程解码实际帧，不把原始值传给 decoder。父进程在时钟外比对原始位模式及 schema；原生完整性校验仍随 API 执行。 |
| `full_frame` | 计实际完整帧字节，包括外层、schema、原生载荷，不把 Zstd byte-codec 记作原生 typed V；不将文件空间分配、缓冲 capacity 或峰值 RSS 混入已序列化字节。当前每 slot 的 256 KiB 是成品检查，不是分配硬限。 |
| `natural_uncontrolled` / 1 次、1 个原生线程 | 不宣称进程冷启动等于缓存冷。相同输入、schema、O 轨道任务及冻结 scope 共用诊断比较 ID；后端与实际线程由本次调用的元数据记录。只采样一次，不报告稳定性、排序或纯框架开销。 |

实际启动的操作在统一 observation 中保留 `process_wall_ns` 与终态，包括超时、崩溃及运行中取消；
未启动的操作不伪造零。封存的 schema 及计划均可用于独立复算；成功时必须有每个实际产物的同 slot
验证和完整帧费用。报告展示原始诊断时间，不用失败或缺失记录填充成功组。

## 原生批候选边界

[批配置](../../configs/experiments/measurement_controls/frame_batches_v1.json)随 `bmk native-plan` 冻结。
`tsbench.control.frame-batches` 在同一个外层预检 run 中串行执行；不会把内部子进程变成多个提交或多份账本。

| 字段 | 批诊断中的实际含义 |
|---|---|
| `frame`、`result_ready` | 每方向每批一次 C++ 单调墙钟。时钟内完成真实插件 API、返回独立 owned 产物，包含批循环、ABI 及编码后 capacity 防护；不含进程启动、模块加载、文件读写、外部逐产物验证、产物释放。解码使用本批每个实际编码帧。时钟外逐一比对完整帧、恢复值位模式和 schema；释放单独计时。 |
| `steady` / `cold` | 稳态在时钟外分开创建 encoder/decoder context，每个对象仍在时钟内 `reset(0)`；**Zstd 当前 reset 重建原生 context**，不能声称重复使用热 codec workspace。冷上下文每次在时钟内创建、操作并销毁对应 context；owned 产物在销毁后仍验证。不是进程冷启动，也不是冷缓存。 |
| `dlopen` / `linked_entry` | 两侧调用同一份重定位插件、同一 ABI 表及相同输入/有效选项。链接侧也验证实际入口属于绑定 DSO。模块装载在批时钟外，不能用两侧差值推断 `dlopen` 成本；不同于绕过 ABI 直接调用 codec 核心的功能差分。backend、线程声明等路径元数据取自本进程预热操作，不冒充各计时操作的独立硬件计数。 |
| 校准、预热、配对 | 每组每侧一个单操作 pilot（各有固定两次预热）；共享 loops 由两侧两方向最短 pilot、目标批时间、帧保留能力和 loops 上限决定。随后每组做三轮配对，计划内固定 seed 生成轮内顺序，串行执行，每次启动都预热两次。校准不是样本；一次配对轮最多提供一个独立配对观测，loops 不是样本数。3 ms 是校准目标，不是保证；保留原始时间，不补采较快或较慢的单个结果来满足目标。 |
| 产物与资源 | 每组保留 `frame_bytes_each`、实际帧 capacity 合计、恢复对象的逻辑值与 schema 字节合计；两侧各操作逐项核验，已经证明字节相同的编码帧仅保留一份预热参考（每 `case × method`）。可离线重算参考摘要、raw 帧原值、压缩帧外层结构和账本绑定，不能据此宣称历史中每个已释放结果仍可独立重放。16 MiB 是参考帧 + 累计帧 capacity + 解码逻辑字节的保留政策，不能代表 allocator 硬限、scratch 或 RSS。 |
| 环境与覆盖 | 当前是重复输入的自然缓存，只记录 Linux 内核、进程允许 CPU 集合及两方向计时前后的 CPU 编号；端点相同不是没有迁移的证明。不声明专核、NUMA、频率或外部干扰。4 种 f64 形状覆盖 31 行、64 KiB、ALP 行组边界加尾块、4 MiB raw 拷贝；不是缓存层级验证，也不是算法间排名。 |

离线验证拒绝轮序、校准 loops、逐产物计数、参考摘要、容量、后端或构建身份不匹配的记录。当前不计算
速度比或显著性。计划、软件、工作负载及环境控制冻结前，不把这些批时间用作正式报告样本。

## 后续正式准入

M1 和组件资格必须 `artifact_each`。M2–M4 的正式 timing-only 套件可冻结 `artifact_each` 或
`artifact_replay`，同一配对组不得混用；`sample_only` 不授资格或正式计时准入。Profiling 是单独的诊断执行，
不能补签主测量。策略 ID 不是阶段验收结论。正式 session 的 CPU/NUMA/缓存及独占预算、可审计的保留硬限和恢复、
保留失败前的批状态、线程和干扰证据、整轮重跑及 attempt 选择仍待实现并冻结；候选记录不代替这些条件。
