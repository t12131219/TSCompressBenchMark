# V3.2 测量协议、交错计划与资源证据实现

本实现对应工程计划 §9、§10.1–10.3、§15、§17 及独立审查 F06。旧 V2 固定门限仍保留 `LEGACY_V2`；其文档和身份不因新可选字段自动升级。新 comparison executor 首先只接入已实现的 `STEADY_PROCESS`、`PIPELINE`、固定重复、无自动重试 CPU lane。协议类型允许表达冷启动、固定预算和预声明 precision 停止，但类型存在不等于执行器已实现这些 lane；执行器须显式拒绝未实现组合。

## 冻结协议与开发集 pilot

`measurement/v32_protocol.py` 的 `MeasurementProtocol` 保存分别独立的 encode/decode 最短累计时间、worker 内预热、spawn/fork 初始状态、时钟、cache/context、最大内层次数、外层次数、trial/总墙钟预算、有限重试、collector、噪声和环境门限。所有进入身份的比例、置信度和门限使用十进制字符串；实际浮点观测递归转换为十进制字符串，NaN/Inf 拒绝持久化。JSON 的未知字段和 identity 不符被拒绝。完整机器示例位于 `examples/comparison_v32/measurement_protocol.json`，schemas 位于 `schemas/measurement/v3.2/`。运行前冻结协议；pilot 失败后调整预算必须形成不同 ProtocolID 和新 RunSet，不改写旧证据。

`run_pilot(protocol, workload, development_corpus_id=..., test_corpus_id=..., harness_probe=..., collector_enabled_probe=...)` 在一个实际选定的 worker 中先执行声明预热，再随机执行同一 index 的 collector ON/OFF 成对探测。spawn 参数必须可 pickle，推荐顶层 callable 或 dataclass callable。probe 返回 `encode_ns`、`decode_ns`，若返回的是校准后累计时间，还必须返回 `inner_iterations`。原始累计时间、次数、方向每对象估计、worker PID、边界、时钟粒度和所有进度事件保留。collector 扰动采用成对的每对象方向时间比；不能比较两个都刚好达到固定累计时间预算的 aggregate totals 来掩盖减速。噪声和推荐内层次数也按每对象时间计算。harness probe 为调用者提供的空驱动；其计时从 worker 发送 `PROBE_STARTED` 生命周期事件之后、callback 执行之前开始，控制面 IPC 不计入 callback/harness 时长；实际边界必须披露，外部 dispatch probe 不自动证明所有 codec 内部 timer/循环开销。任何开销均不从实测时间中扣除。

父进程对整个 pilot（含 spawn）和每次回调设墙钟期限；挂起回调被终止，已经接收的完成探测继续保留。预算终止、错误、扰动、噪声或信号不足返回 `INCONCLUSIVE`。进程终止清理有界，但清理本身可能使返回时点晚于截止时点；这不被描述成硬实时保证。`validate_pilot_evidence(protocol, document)` 重新核对 ID、原始投影、方向单位、随机成对顺序、噪声/collector/时钟门限、warmup、worker 启动与退出、线程插桩及实际预算，返回 `eligible/status/reasons/recomputed_metrics`，畸形或修改后的冻结证据抛 `MeasurementProtocolError`。`PASS` 标签本身不是准入凭证；该校验也不是对整份伪造执行记录的密码学签名。

precision 停止仅接受冻结 checkpoints 上的独立外层 sample unit、注册的 Bonferroni look 置信度、有限非负十进制 halfwidth 和噪声门限。超出总预算后的 precision 不升级为成功；预算用完但精度或噪声未达标为 `INCONCLUSIVE`。推荐 inner iterations 不增加独立外层 N。

## 随机计划、终态和恢复

`execution/schedule.py` 的 `build_schedule` 以 `dataset_methods={DatasetID: {唯一参数变体键: ExecutionJobID}}` 冻结全体成员。按 block、round、dataset 生成成对 slot；每对内通过 `SHA256_KEYED_ORDER_V1` 和 seed 排定方法/变体顺序。dataset 顺序为规范排序，方法顺序在每个 dataset/block/round 随机交错，所有参数变体保留，指向同一 ExecutionJob 的别名不能增加成员数。trial/pair/repetition/sequence 身份与 seed/design 共同绑定，跨语言可以重新计算。

`write_frozen_schedule` 不覆盖不同计划。`FrozenSchedule.from_document` 从设计和 seed 重建并核对完整序列。`append_trial_event` 使用文件锁追加终态 attempt，记录 planned sequence 和实际 event index、开始/结束、结果/原始证据引用；成功不能重跑，失败仅按冻结预算重试。读取和 resume 校验字段、成员、attempt identity、连续 attempt/event 索引、时间边界和成功终态，拒绝日志截断、重复或篡改。失败耗尽重试后保持终态，真正缺失 slot 继续 pending，原始计划始终保持全分母。实际 comparison driver 也必须保留全计划，不能把过滤后的成功子集称为完整组。

`execute_task(..., trial_deadline_ns=...)` 把同一个 `PERF_COUNTER_NS` 绝对截止时点传到 preflight 的每个隔离步骤和 measured worker。`preflight_task(..., deadline_ns=...)` 与 `run_isolated(..., deadline_ns=...)` 不给每个后续步骤重新发一份完整预算；截止过期返回 TIMEOUT 且不启动新 worker，实际 materialization 或父进程验证过期也拒绝正式资格。父进程同步输入/正确性验证采用阶段后的 deadline 检查，不能声称能抢占所有父进程 Python 运算；终止清理可能越界并在 raw 中可见。调度器还须把 trial deadline 限制在总预算剩余量内。

## 协作资源租约与环境

`measurement/resource_lease.py` 的 `ResourceLease` 是 Linux 同账户、同 lock namespace 的合作式 host `flock`。默认 `/tmp/tscompbench-resource-leases-<uid>/host.lock` 让不同 RunSet 和进程互斥；CPU 子集也不会令同一 host lease 并发。明确记录物理 core/SMT/NUMA 可得性，校验线程×进程不超过逻辑 CPU 分配、禁止未声明的 SMT siblings、按声明验证 NUMA CPU 节点，并实施调用线程及未来子进程的 CPU affinity。释放和异常退出恢复 affinity。进程退出时 kernel 在最后一个继承 descriptor 关闭后释放锁；owner 必须先停止所有 workers，不能声称对 orphan process tree 进行了 fence。

内存仅进行 host `MemAvailable` 边界准入，不是硬内存预留、硬 RSS 限制或 cgroup process-tree 限制；CPU affinity 也没有实施 NUMA memory binding。这些限制都写入 lease evidence。隔离 worker 的旧 `RLIMIT_AS_WITH_EXISTING_VM_HEADROOM` 同样不升级为硬 RSS 上限。外部非协作负载不会被逐出，也不宣称操作系统独占。

`to_document()` 在租约持有期间返回新的 `boundary`；`environment_gate(protocol, before_copy, after_copy)` 核对同一个租约并保存 trial 前后环境快照。频率/governor、host load、最大可见 thermal/hwmon sensor、current cgroup v2 aggregate 节流计数、host MemAvailable、当前进程边界线程数都保存 scope。不可得指标为 null + reason。只按冻结 load/temp/throttle 门限排除，只有声明 `require_environment_observations` 时才因为所要求门限的观测缺失失败。cgroup aggregate throttle 和 host/system swap 不能归因为 codec 自身。

## 可选父进程线程观测

`run_isolated(..., thread_monitor_interval_ns=N)` 默认 None，保持旧执行行为。启用后 supervisor 读取实际 `/proc/<worker_pid>/status`，记录 PID、采样序列、实际间隔/可用性与峰值；worker 仅在函数入口/退出读取边界，不增设采样线程。最短支持间隔 1ms。`lifecycle.thread_observation.classification=INSTRUMENTED_SAMPLED_LOWER_BOUND`，scope 为该 worker 的全线程，不含 descendant processes。两次读取间创建并 join 的线程可能漏掉，因此 `captures_all_transient_threads=false`。

`MeasurementProtocol.thread_monitor_interval_ns` 进入新 ProtocolID；pilot 在 ENABLED 探测期间打开同一 parent sampler，DISABLED 探测期间关闭。原始 sampler 模式/间隔及证据必须匹配；默认 None 的正式记录不声称线程高水位。`thread_budget_evidence` 中采样超额证明 `EXCEEDS_BUDGET`，orchestrator 将正式记录标 `OVERSUBSCRIBED`；`NO_EXCESS_OBSERVED` 只表示已观察样本无超额，`strict_high_water_verified=false`。这既不宣称完整高水位，也不宣称完整 process-tree 总线程预算已经强制执行。

## 验证

针对协议/计划/租约/父进程线程/测量/同 worker 集成与 schema 的 71 项测试通过。测试包含真实 spawn 的 ON/OFF pilot、挂起 probe 的有界终止和原始证据保留、固定累计预算掩盖减速的负例、伪造 PASS/gate/lifecycle 的拒绝、同一 worker warmup、两个真实进程互斥及 owner 异常退出、affinity 恢复、线程结束前峰值、预算和冷启动负例、环境 unknown 与声明门禁、随机序列重建、失败重试/缺失分母、日志篡改与 deadline 后不启动 worker。上述实现与测试的 Ruff 已通过；5 个新 schema 经 Draft 2020-12 检查并验证真实生成的 protocol/schedule/event/environment/HELD 与 RELEASED lease 文档；这份文档不主张完整 OS 资源隔离或整个组已完成 FORMAL。
