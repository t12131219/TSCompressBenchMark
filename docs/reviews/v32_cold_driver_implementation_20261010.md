# V3.2 独立冷启动执行器实现记录

本次实现新增 `tscompbench.execution.cold_driver`，供 `COLD_PROCESS` 比较轨道使用。每个独立对象严格启动两个 `spawn` 子进程：编码子进程重建 manifest、adapter、准备输入并完成一次编码；父进程复制已 finalize 的 stream 与持久化 decode context 后，启动只接收 `stream + context + manifest/dependencies` 的解码子进程。解码子进程没有原始数组、编码器会话或 routed input，且在子进程内恢复出 owned canonical buffers；父进程再复制为 readonly owned output。

方向时间从各自的 parent launch boundary 开始，持续到父进程完成 owned output materialization，并包含 spawn、Python import、adapter loading、参数/IPC 传输和 worker exit。两个方向共享同一个绝对 `PERF_COUNTER_NS` deadline；截止前未启动的 worker 留有 `worker_launched=false`，超时保留此前方向的实际 lifecycle 证据。冷轨道固定 `inner_iterations=1`、无 warmup、`OS_CACHE_UNCONTROLLED`，不声明 core/native timer，也不通过 batching 达到方向最小时间。

子进程在函数退出、IPC 返回前读取 `RUSAGE_SELF` 累计 user/system CPU 与 peak RSS，明确包含 startup/import，明确排除 result pickling 和 process exit CPU。父进程采集独立的 parent delta；两类证据分别保存，RSS 仅表示两个顺序子进程的 max pre-IPC high-water，未宣称 process-tree/cgroup 硬限制。`ResourceSampler` 的 enabled/disabled 证据与 collector mode 必须逐方向匹配；enabled 模式可配合父线程采样，采样分类为 instrumented sampled lower bound，不宣称严格瞬时高水位或后代线程覆盖。

`run_cold_pilot` 在单独 development/test corpus 标识上以随机化的 disabled/enabled 成对顺序运行相同驱动，保留成功及失败 raw attempts。`validate_cold_pilot_evidence` 重算 pilot identity、配对顺序、方向 wall、子进程 PID/退出、shared deadline、context/stream hash、独立恢复成本、resource projection、线程采样和 `_pilot_metrics` gates；修改 raw projection 或派生 admission 字段会被拒绝。正式测量禁止 collector override，override 仅用于 development matched pair。

当前能力边界：未实现 OS cache 清理、进程树/硬 RSS cgroup 限制、NUMA memory binding、orphan fencing、严格 PSS/USS startup high-water；这些字段以 scope/reason 明确记录。冷 pilot 与正式测试必须使用不同的 corpus 内容。

`comparison.runner` 现在已接入完整冷轨道：`prepare_comparison` 仅允许 `COLD_PROCESS + PIPELINE + spawn + inner_iterations=1`；开发 pilot 使用 `ColdPilotProbe/run_cold_pilot`，正式 trial 将同一对象的编码/解码、correctness、完整 ledger、paid recovery context 和两个真实 lifecycle 保存为 RunRecord。`analysis.trial_issues` 按 profile 验收两个独立 PID、零预热、方向 launch-through-parent-owned-output 时间、共享 deadline、资源 projection、线程预算和同次独立解码，不接受将 steady 记录改标签后取得 cold 资格。

ALP source-reject composite 只能通过 frozen cell 的 `SOURCE_REJECT_RAW` 显式声明选择；相同 bool 传到 fresh encode/decode worker 并绑定 pilot evidence。codec key 本身不会启用 fallback。原始源拒绝、普通错误和容量错误保留相应终态，不强制转 RAW。

同一 runner 另支持已注册无损 byte 方法的 `COMMON_NATIVE_API + STEADY_PROCESS + CORE` 独立轨道。`CORE_API` 测量外部 component API 边界（包含声明的 FFI/container 工作），不把辅助 `CODEC_API_ONLY_V1` native timer 升为主观察。该轨道拒绝 source fallback/P2 composite；native component 的主要成本为实际 `serialized_bits`，完整对象的 persisted decode context 与 `final_bits` 保留单列。实际输入内容/schema 标识不包含算法身份，相同 byte 输入才能取得同一公共投影。

针对性测试：`tests/unit/test_cold_driver.py` 覆盖两个真实 fresh PID、独立 recovery、paid context cost、资源 scope、共享 deadline、单对象最小时间、collector 配对、pilot 证据重算及篡改拒绝，共 8 项通过。

新增真实集成验证位于 `tests/integration/test_v32_comparison_runner.py`：cold 与 native API 分别取得 12/12 core cells、24 个真实 formal trial 的 `CORE_COMPLETE`，验证只读报告、无操作 resume、fixed denominator 和原始 SHA 保持；冷轨道另有 warmup、PID 复用、物化和时间边界篡改负例，native API 有 PIPELINE 记录伪装 CORE 的负例。这里使用单独 integration 合同与两次外层重复，证明执行链，不能替代预注册正式协议的性能结论。
