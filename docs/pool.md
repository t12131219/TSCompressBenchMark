# 外部进程对象集合 executor

`python -m tsbench.pool benchmark/examples/pool.toml` 是独立 workload 工具；不修改已经冻结的 CPU object runner、worker 或其历史实现身份。它比较同一固定对象集合、相同 method／task／每进程 native 线程资源下的 1／2／4 个进程。原生实现同进程的全局 mutex 不会被误当作可并行线程路径。

```bash
export PYTHONPATH="$PWD/benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
python benchmark/examples/generate_fixtures.py
python -m tsbench build zstd-frame
python -m tsbench.pool benchmark/examples/pool.toml
python -m pytest benchmark/tests/test_pool.py -q
```

配置的 `[experiment]` 是正常 CPU experiment。一个 pool 请求固定整组 datasets 和一个 method；多个 methods 分别运行，不把不同 codec 混入同一吞吐分母。每个 per-worker profile 的 `object_workers=1`，外部进程数由顶层 `workers` 声明。整个集合先通过正常 runner 的 capability、implementation suite、exact-input 独立恢复及一个正式 round；这些证据保存在 `admission/`，其时间不进入 pool 指标。任一成员不合格时整组请求保留实际 unsupported／unavailable／error 等原因，不能只挑剩余成功成员计算固定集合吞吐。

父进程的 canonical 对象已准备就绪。编码 worker 从这些对象的显式 dtype／shape／order／schema／bytes 建立自己的副本，并与 admission 的内容及实现身份核对。解码 worker 的初始化只有安装 roots 和 resource profile，操作只接收实际 wire；没有 original、method 参数或 shape 模板。每个 worker 都通过 `Popen` exec 新的 Python interpreter，不在继承父进程 native 状态的 fork 子进程内运行 codec。线程环境、affinity、RLIMIT_AS 和显式 runtime preload 在导入 NumPy／codec 前实施。

`encode_collection` 的连续 wall 从调度开始到父进程得到完整可保存集合产物结束；包括 worker 调度、IPC、实际 encode、结果序列化、收集及目录构建。`decode_collection` 从完整集合 wire 在父进程内就绪，到目录解析／校验、逐 wire IPC、独立 decode、恢复对象 IPC 和有序集合重组完成。主吞吐用固定集合 canonical raw bytes 除以该 wall，不以 codec 内部时间或成功对象数推算。

`cold_pool` 每个 collection 使用新进程，clock 包含进程启动、对象分发、profile 和库准备；`persistent_pool` 每个独立 session／operation 建立池，setup 和完整集合 warmup 单独保存，之后保留进程而每对象的 codec session 仍独立。编码／解码池分阶段存在，主测量不会同时保持两组参与池。**两种 availability boundary 都在完整结果已返回时停止，pool shutdown 另计 `close_ns`；不能称这些数值是进程整个生命周期 wall。** 输入 fingerprint 检查、每份 wire 的独立恢复验证、质量验证和保存文件均在 collection clock 外；每个 encoder 的输入副本与每轮实际产物都验证。warmup 的产物同样恢复验证。

集合文件使用独立 checked directory，保存对象 ID、offset、length 和每个 standalone wire 的 checksum；prefix 对目录也校验。stored bytes 为实际集合文件长度，即各对象 wire 之和加真实 collection prefix／index。单对象原有 descriptor、model、chunk 等仍在自己的 wire 内，仅计一次。解码后依据目录顺序恢复；并行完成顺序不能改变对象对应关系。

每个 session 的成员顺序按固定 seed 洗牌，并按 worker 固定分派，进程数变化不改变对象集合／chunk 几何。全部 planned／started／terminal 和 assignments 保存在 JSONL／manifest；PID、实际 Threads、CPU consumed time、进程 lifetime ru_maxrss、affinity／限制及 runtime maps／hash 按参与者记录。父进程在开始／结束和每轮 clock 前／完成后／验证后都有独立的累计资源快照，采集在主 clock 外；验证后快照也包含验证、保存和关闭开销，不能与 codec CPU 时间混同。父进程承担协调／序列化工作，其 affinity 和线程数独立明示，worker 的进程数乘 native 线程数是 worker 预算。ru_maxrss 的 Linux 单位为 KiB，不能称每 trial 增量峰值；不能简单把各进程 lifetime high-water 相加当同一时刻总峰值。per-worker native 线程预算乘进程数不能超过允许 CPU 数；不支持 worker oversubscription 请求。

stdin 和 stdout 都非阻塞并受整体 collection deadline 约束，大 wire 写入不能绕过 timeout。每进程独立 process group，正常关闭或错误／超时后有界等待并清理整组；即使 leader 先退出仍清理后代。一次池失败后同 condition／session／operation 的剩余 collection 为 not_run，不静默重试。编码池失败前已完成且验证通过的 bundle 仍可由独立解码池测量；没有可用 bundle 的 decode round 为 not_run。未知 SIGKILL 保持 crash／signal，不推断 OOM。该工具没有 resume／retry；已有输出禁止覆盖。

当前 add-on 的 IPC 单条消息上限 64 MiB、完整集合及原始集合上限 512 MiB，超过时明确拒绝。这是内存安全限制，不代表 codec 原生域限制。小对象中 Python／JSON／base64 和进程启动成本可能占主导，这些成本属于所声明 workload boundary；不能由其结果宣称内部线程、SIMD 或 GPU scaling。报告给实际成功集合的 median，并同时保留完成／计划与全部终态。1／2／4 worker 的描述性 speedup 只配对同 method／lifecycle／operation／session 的完整 round 集合，先取该 session 的 baseline／target median 之比，再报告 session speedup 的 median；不完整 session 不进入该数字，明确报告完整 session pair 分母。session 和 round 对应固定输入／seed 条件，条件依固定顺序执行；此处不产生置信区间或线性 scaling 主张。

## 2026-10-13 实际证据

最终代码的八项 add-on 测试通过，覆盖真实 raw／Zstd 的 cold／persistent 集合、NaN payload／signed zero／F layout、PID 重用／隔离、阻塞写超时、crash、孤儿进程组清理、leader 退出后的 buffered close 结果、输入修改拒绝和真实失败产物保留。它们不替代核心 runner 已有的测试，也不把合成对象当跨领域性能总体。

[最终运行](../runs/process-object-pool-final-20261013/README.md)有 **12 个 ready 条件、24 个 operation 组、504/504 个 collection trials 成功**；每组为3个独立池 session ×7 rounds，encode／decode 分列。正常 object admission 为8/8个 case 成功。主记录包含2016项逐对象恢复验证，每个 encode 产物都在计时外由独立 wire-only decoder 恢复；计时后的 decode 产物另行验证。manifest、raw、report 和运行时的精确 [pool.py 快照](../runs/process-object-pool-final-20261013/source/pool.py)都保留在该 run 内。

固定集合包含四个逻辑 task、三种唯一 canonical 对象；`float64.npy` 和 `records.npz` 的 V 投影具有相同 dtype／shape／schema／bytes，但按两个声明的任务分别执行、传输和计费。该重复是固定 workload 的一部分，不代表四个独立来源。每次集合 raw 分母为19532 bytes；raw-store 完整集合25445 bytes（24848对象 wires＋597目录／prefix），Zstd 完整集合13155 bytes（12559＋596）。重复的对象 wire 也实际存两次，没有免费去重或模型摊销。

以下为完整 session 内的 median 时间比，再取3个 session 比值的 median，基线是同 method／lifecycle／operation 的1-worker条件。所有单元格均为3/3个完整 session pairs、各21/21个 collection trials；不是单个 native kernel speedup。

| Method | Lifecycle | 2 workers encode | 2 workers decode | 4 workers encode | 4 workers decode |
|---|---|---:|---:|---:|---:|
| raw-store | cold_pool | 1.153 | 0.956 | 1.225 | 0.944 |
| raw-store | persistent_pool | 1.278 | 1.256 | 1.457 | 1.536 |
| Zstd-3 | cold_pool | 1.261 | 1.022 | 1.409 | 0.986 |
| Zstd-3 | persistent_pool | 1.343 | 1.495 | 1.727 | 2.521 |

condition 按 method／worker count／lifecycle 的固定顺序执行，三个 session 的成员顺序按 seed 分别固定洗牌；这些比值保留时间顺序、短对象和 warmup／runtime 的条件限制，不据此宣称线性扩展、统计显著性或普遍加速。父进程协调／IPC／目录工作，以及 cold 的输入分发／实现身份核对，都是该 workload 的真实成本。

只读审计确认504个 raw terminal 的 `(workload_id, session, round, attempt, operation)` 与 manifest schedule 完全一一对应，没有缺失或重复。两个实际集合文件的目录顺序、完整长度和每个 wire checksum 均通过；1176个 worker 资源快照都是1个实际线程、affinity为CPU0–15，672个不同的主测量 worker PID均有正常 close／wait／进程组清理记录，没有 setup／close failure，复核时这些 PID均已不可见。实际 mapped runtime 的三个库 hash 与文件一致。资源快照不是连续采样峰值，PID只标识该次执行中的参与者。

[首轮运行](../runs/process-object-pool-20261013/README.md)也完成504/504个 collection trials，其原始记录和精确源码独立保留。随后修正的是“leader已失败退出、后代仍持有stdout”的 crash 分类，并补充 valid close drain race、输入修改和失败产物回归；最终运行重新执行全部504个 collection trials，没有将首轮结果回写成最终实现的测量。
