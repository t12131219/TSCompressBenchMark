# 整个匹配轮的干扰分类与重试合同（实现组件，尚未接入全量）

对应设计 §8.12、§8.13、§12.6。`tsbench.supervisor.matched_round_retry` 服务于**每槽每次尝试均新建进程**的匹配轮。它不是宿主租约、系统独占或计量准入。v13/v14 已冻结的诊断不符合这个合同，不能补填字段、回写账本或据此重新分类。

1. 计时前由上层冻结匹配范围、已随机化的全轮顺序、各 slot 的逻辑 CPU 预算、预期 governor 和重试次数上限。`policy_id` 覆盖这些内容。这里不修改 governor 和亲和性；上层须另记录实际宿主配置、隔离与预留证据。
2. 每个 terminal 记录保留实际会话身份和环境证据。启动前后 governor、worker 有效亲和性和实际观测到的 CPU 都有专用位置；不适用或观测不到保留 `null` 或缺失的单 CPU 值。看到的 CPU 子集不证明运行期间没发生短暂迁移；集内迁移不叫预算越界。负载、IRQ、NUMA 和散热并不由这些信号保证。
3. 只在观测到 governor 不符、worker 亲和性违反冻结预算或实际在预算外 CPU 执行时，可将全轮标为干扰并在上限内重跑。保留原 attempt 和原终态，重跑全轮的所有方法及方向，沿用冻结顺序和 slot ID，换新 attempt 与会话。超时、崩溃、校准不足、质量拒绝或慢样本本身都不是干扰证据。缺测不等于干净，也不是重跑理由。
4. 复算报告分列首轮和末轮验证数、各轮环境状态和可能的候选轮；候选必须是同一轮所有 slot 通过且所需信号齐全，禁止按方法拼接各轮。即使存在候选，也仍需上层证明资源、原始时钟、功能和质量资格。
5. 接入生产执行器时，实际环境观测必须来自监督器和实际工作进程，关联真实会话；不能用计划中的 CPU 集合回填。原始记录与派生轮终态由单写者按阶段合同持久化。若执行器中断，只能报告已发布的原始记录，不得补造完整 attempt。本组件的回调不代替持久化、恢复或宿主独占。

## Native witness wiring

New native drivers can call `worker_checkpoint()` in `native/measurement/common/worker_environment.hpp` immediately outside the operation clock at entry and exit. Its CPU sample comes from `sched_getcpu()`, and its mask from `sched_getaffinity(0, ...)` on the calling thread. `worker_environment.project` must receive that worker's records from its supervised output, along with actual governor snapshots taken by the controller before and after execution. It preserves the raw endpoint observations. If only one endpoint exists, a recorded budget violation is still retained; otherwise missing data stays missing rather than borrowing the planned mask. Namespace PID/TID identify the worker within its own process namespace, not the wrapper process PID. The verified supervisor session and raw observation must be bound together by the executing adapter.

A standalone non-codec smoke probe observed an exact CPU 0 mask and rejected an intentionally wider CPU 0/1 mask as violating the same frozen budget. The probe is unisolated, sampled only the calling thread, and is not evidence of host reservation or of any v13/v14 codec or timing run. It does not observe OpenMP/pool workers, transient migration, or the entire process-lifetime affinity history. Formal drivers must declare any extra thread observation they need for the relevant execution contract.

## 单写者与封账复算

`tsbench.supervisor.matched_round_ledger.execute` 为新建运行目录写冻结合同；每次完成先持久化原始 worker 元数据，再向 `ledger.jsonl` 追加绑定运行、slot、attempt、会话和原始文件摘要的终态。全轮终态写完才追加轮处置，并决定是否重跑整轮。只有经 `replay` 从原记录重新投影并得到相同报告，才写 `completion.json`。`verify` 会检查封印并重算 worker 原件、终态和轮处置的对应关系。中途异常保留已写终态，不发布封印，也不自动续跑。尚不包含正式 codec 计时执行器、宿主租约或跨轮恢复。

独立双槽探针以 CPU 0 为冻结预算；首轮第二槽故意使用 CPU 0/1，两个槽都执行了第二轮。四份原生 worker 观测和两轮处置已封账并复算。探针不运行 codec，不属于正式测量；详见 `results/m3-matched-round-ledger-probe-20261120-r1/probe.json`。

## Zstd/XZ 真实 codec 定向对照

`native/measurement/matched_abi/` 可独立构建带入口、出口观测的 ABI worker，复用既有 ABI worker 源码而不改历史构建。`tools/m3_matched_abi_control.py` 已冻结 ETTh1 的首个 65,536 B 交错值字节单元、v13 构建锁中的 Zstd/XZ 库、一个逻辑 CPU、governor、方向内随机顺序与整轮重试规则。每轮两种方法各独立编码、独立恢复；恢复只挂载同轮对应方法产物，验证原始位、schema 和实际单线程路径。运行入口先取得 TSBench 协作锁，保留 Bubblewrap 禁网及最小挂载。当前这是单单元功能诊断，不是整文件、原生精确计时或正式独占性能结果；尚未在 v13 运行期间启动。
