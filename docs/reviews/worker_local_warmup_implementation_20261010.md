# F06：每个测量 worker 内预热的实施记录

依据 V3.2 §9.2、§10.1、§10.3 和独立审查 F06，本批把独立预热 worker 改为每个 repetition 的同进程预热。执行顺序为：启动隔离进程 → 应用 affinity/内存限制 → 该进程执行声明的预热对象 → 启动资源 sampler 和测量 → 停止采样 → 返回证据 → 确认进程退出。每个新 repetition，包括 resume 后尚未执行的 repetition，都重新走该顺序。

## 可核对的证据

`run_components.jsonl` 的每次 `diagnostics.worker_measurement` 使用独立版本 `tscb.worker-measurement-evidence.v1`，记录 warmup/measurement 的 PID、时间边界、每个预热对象的时间轨迹及原有 warmup 汇总。`diagnostics.worker_lifecycle` 使用 `tscb.isolated-worker-lifecycle.v1`，记录父/子 PID、start method、父/子开始时点、父结束时点、退出码和退出确认。事件日志保存同一逐 worker 证据。

orchestrator 检查 warmup PID、measurement PID 与实际隔离 worker PID 一致、时间顺序成立、门槛满足及 worker 已退出。不能把另一个进程的预热证据用于该 repetition。预热和正式阶段抛错时，原 exception 类型、失败阶段及已产生的预热轨迹仍进入失败 raw；超时/无 envelope 的死亡记录未知阶段，不补造已完成预热。

原有 `warmup/*.json` 和 `TaskExecutionResult.warmup` 继续提供首个成功测量 worker 的兼容摘要；其计数只描述该 worker。完整覆盖以每次 raw 的证据为准。未增加字段到旧 `tscb.warmup-observation.v2` 或 timing 文档。

## 协议和身份边界

新的执行路径 hash 和 execution comparability key 包含 `WORKER_LOCAL_WARMUP_V1`。同批的持久化恢复协议 `PERSISTED_DECODE_CONTEXT_V1` 及 `OWNED_CANONICAL_BUFFERS` 也进入执行身份。旧 task plan 不得被覆盖为新实现，deterministic rebuild 会拒绝不一致计划；已有历史 raw、ID 和 FORMAL 资格不重写。

固定预热次数/时长与重复/方向时长门槛继续标为 `LEGACY_V2`。此改动证明预热在同一测量进程中发生，不能单独证明统计稳态、充分独立来源、随机化/配对 schedule 或 pilot 预算已成立。默认隔离仍按平台选 fork/spawn，并记录具体方法；fork 明确继承父状态快照，因此本协议不证明冷启动。隔离 API 支持显式 `start_method="spawn"`，供独立冷恢复证明使用。

codec 编码和解码 context 仍按每个对象分别新建，不声称复用 warmed context。预热不进入正式计时和资源 CPU 增量采样；进程 peak RSS 是生命周期高水位，包含预热占用，证据中明确标注该范围。worker timeout 覆盖预热与测量的合并生命周期。

## 验证

真实多进程回归证明：独立 warmup worker 无法把 PID 内 codec 状态迁移到另一个测量 worker；三个测量 worker 各自完成两次预热，正式对象分别使用该进程的第五个新 context；warmup/measurement 的 OOM 阶段保存与原分类保留；支持显式 spawn；跨进程 PID 证据拒收；三个 repetition 的持久化和重复执行保持 raw 字节不变。

`CompressBench14` 环境下，measurement/execution/planning 与 Layer 3/worker-local 集成测试合计 34 项通过；新增执行代码及测试的 Ruff 检查通过。这些是合同/回归验证，不是正式性能稳态证书。
