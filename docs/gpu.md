# GPU P4 独立对象执行器

[`benchmark/src/tsbench/gpu.py`](../benchmark/src/tsbench/gpu.py) 使用独立 schema `tsbench.gpu-experiment/1` 和入口 `python -m tsbench.gpu`。CPU C1 的配置与 runner 保持自己的对象边界；GPU opaque device owner 不进入 CPU buffer ABI。当前 GPU 扩展是 [`cuszp-fixed-1d`](../registry/gpu/cuszp-fixed-1d.json)：冻结的官方 cuSZp 3.0.0 一维 FIXED CUDA f32/f64 kernels 加已检查的 host wrapper。编译完成和 PCI 设备存在均不等于运行资格。

## 输入资格与质量

输入必须是单个连续小端 `<f4` 或 `<f8` 一维 V 数组，长度 `1..16777216`。负零、subnormal、NaN、infinity、mask 和多通道数组均明确拒绝；不会替换特殊值、隐式转 dtype 或回退 CPU。另检查 `abs(value)/(2*actual_bound) <= 2**28`，以及有限的 dtype 域 reciprocal。这些条件来自 native source 的保守整数域 guard，不能被解释为 cuSZp 对任意浮点输入的质量保证。

配置保留 `_requested_error_bound` 的原始十进制文本，将通过验证的 codec 参数转换成 Python binary64 标量，再传给严格原生 API。f32 容差向下转换为可表达的 normal f32，f64 保留 binary64 转换；实际容差写入 CSP1 wire。`codec_requested_absolute_tolerance_text`、`codec_requested_absolute_tolerance` 和 `codec_effective_absolute_tolerance` 分别记录文本请求、送入 API 的标量及实际 native 参数。task 的 `error_bound` 仍是独立请求，验证始终针对原始 dtype/domain 的所有有效有限值，以严格比较判定；point-relative 的 floor、分母、violations 以及 NRMSE/PSNR 分母和 null reason 来自公共 verifier。

每个实际 dataset/method/boundary/device case 都运行完整编码、解码、质量与输入未修改检查，再从该真实 artifact 启动独立 decoder 解释器。decoder 只收到 wire、实现路径及资源 profile；dtype/count/actual-bound/mode/对象 schema 均从字节解析，不接收原始数组或 shape/schema 模板。native 边界 suite、错误 frame、原生 source/rate/owner-kind/config rejection 和资源回收证据由 [`benchmark/tools/qualify_cuszp.py`](../benchmark/tools/qualify_cuszp.py) 单独产生；有限资格样例不构成普遍误差定理。

## 两个完成边界

两类 case 分别保存，报告不会混合吞吐。库加载、CUDA driver/context 初始化和 dataset parsing 位于对象时钟之外。每个实验 session 使用新 worker 解释器，每次 encode 和 decode 在主时钟内创建及关闭独立 `Session`，包含 stream 创建、控制状态初始化、实际 CUDA 工作完成、scratch/event/stream 的检查回收；没有预创建 codec session。

| 项目 | host_to_host | device_resident |
|---|---|---|
| Encode 开始 | 原始 host typed array | 已完成上传的 DeviceInput |
| Encode 主时钟 | fresh Session、H2D、kernel、完成、D2H、CSP1/完整对象 checks 与 packing、owner 回收、Session close | fresh Session、kernel/完成、scratch/event 回收、构造 host recovery descriptor、Session close；device payload 输出 owner 存活 |
| Encode 停止时 artifact | 完整独立 host wire | device payload owner + 已构造的 host recovery descriptor |
| Decode 开始 | 完整 host wire | 从实际 wire 独立安装并完成的 DevicePayload 与已检查 recovery metadata |
| Decode 主时钟 | wire 解析、fresh Session、H2D、kernel/完成、D2H、对象构造、owner 回收、Session close | fresh Session、kernel/完成、scratch/event 回收、schema 拷贝、Session close；device decoded 输出 owner 存活 |
| Decode 主时钟外 | 原始域质量、输入 fingerprint、日志、保存 | decoded D2H、对象构造、原始域质量、输入检查、输出/input/payload owner release、日志、保存 |

device_resident encode 的 host descriptor 在主时钟停止前已包含完整 schema、component、dtype/count/shape/order、actual bound、FIXED mode、native source format 及 host/device 所在位置。停表后不会再补上恢复必需参数。DevicePayload 和 DeviceDecoded 输出 allocation 的所有权独立于已经关闭的 Session。

`boundary_costs` 保留 `prepare_device_input_ns`、`encode_materialize_csp1_ns`、`persisted_object_pack_ns`、`encode_output_release_ns`、`prepared_input_check_d2h_ns`、`prepared_input_release_ns`、`decode_descriptor_parse_ns`、`install_device_payload_ns`、`decode_materialize_d2h_ns`、`decode_output_release_ns`、`installed_payload_release_ns`。这些实际辅助成本不从主时钟减去、不混入主估计。DeviceInput 回拷位元与原始 input 比较，每轮同时检查 host fingerprint。

持久化采用公共 TSB 对象 frame，包含被 hash 保护的 schema/component 路由和完整 CSP1 native wire。CSP1 检查 metadata SHA-256、payload SHA-256、类型/长度/参数及 FIXED rate table/size。`stored_bytes` 始终计入整个实际持久化 wire，`payload_bytes` 仅为 native compressed payload，二者间全部元数据、目录、checksums 均计入 `header_bytes`。Device live representation 和持久化字节数不是同一个存储估计。

## 资源、失败与证据

Host affinity 在实际 worker 内设置并读回。`native_threads=1` 表示 adapter algorithm host parallelism；driver/runtime helper threads 另在 `/proc/self/status` 的 `Threads` 中观察。Host `RLIMIT_AS` 是整个进程虚拟地址空间，包括 CUDA driver 映射，不能标作 RSS 预算。若指定 `host_memory_limit_mb`，无法严格设置即拒绝资格；未指定则记录 inherited readback 和原因。冻结有限 host limit 前，应读取真实 CUDA 初始化/encode/decode 的 VmSize；CPU 空进程数值不足以选择 CUDA 的虚拟地址预算。

当前 adapter 没有可强制的每进程 VRAM cap。未请求的 limit 是 null，附明确原因；若配置显式请求 `vram_limit_mb`，资格返回 unsupported，不能悄悄使用无预算设备。Native Info 的 `owned_allocation_peak_bytes` 是 adapter 同时存活的成功申请 capacity：host encode 包括本次 input、output capacity 和 scratch；device encode 排除预先准备的 DeviceInput；decode 排除预先安装的 payload。它排除 context/runtime/cache、allocator granularity 和其它进程，属于 source accounting，不能标作采样的实际 VRAM peak。原始记录同时保留每种 input/output/capacity/scratch/payload byte 数。

CUDA events 测量已完成 stream 工作，encode 含 scratch zero、host 路径 H2D、真实 FIXED kernel 及 size/rate D2H；decode 含 scratch/output zero 及真实 kernel。`device_event_ms` 不能标作纯 kernel 时间或作为包含生命周期的 wall-clock 的替代。每次正常测量前后采集 calling-thread adapter counters，要求 live bytes 不变、allocation/release、stream create/release、event create/release 增量分别相等；不平衡会使 trial 失败并停止设备。

父进程在任何 native 操作前持久化所有正式 `planned` 槽位，随后保存 `started`、阶段事件和唯一 terminal。真实 CUDA error、OOM、crash、timeout 或回收未确认会停止该设备后续全部 case/session，剩余槽位逐项保存 `not_run/device_recovery_unconfirmed`；不会 reset、retry 或启动替代 CPU 路径。wire-only decoder 使用独立解释器且继承 worker process group，外层 timeout 会连同该子进程一起清理。即使 worker leader 已退出，GPU 终止器仍杀整个 group。

每次 run 使用新的空目录，保存原始/解析配置、源快照、配置/输入/source/binary/build/dependency hash、actual mapped CUDA/NVIDIA/runtime 库及版本、GPU device/runtime identity、实际 profile、相邻 environment/process snapshot、资格和正式 observation、全部请求保存的 artifacts。Parent 源 ID 必须与第一个 admission worker 一致；末尾 Python/native/runtime 来源变更会锁存 invalid，并使汇总指标为 null。频率、功率、NUMA 和显存预算未控制的事实仍显式保留，不由相邻快照推断为全程控制。

报告按 `(run_id, case_id, session, round, sequence, attempt, block_id)` 检查精确覆盖，不接受相同数量但缺少/重复/错位/跨 run 的 trial。每个 case 仅在全计划槽位恢复与质量均成功、来源未变时生成 median/IQR、吞吐、ratio、bpv 和 max error；失败或未运行槽位保留原状，部分成功不会变成正式性能结论。

## 冻结网格与运行入口

[`benchmark/experiments/gpu-p4/preparation.json`](../benchmark/experiments/gpu-p4/preparation.json) 冻结 `<f4>/<f8>` 的 33、32769、1048576 点 synthetic trend + periodicity + deterministic noise 输入，分别覆盖部分 32-value block、32768 CUDA tile 的越界尾部和 1M-value 大对象。它是生成数据，不能称为真实 corpus。两个独立配置 task/native 请求为 0.01 和 0.1；每个配置 6 datasets × 2 boundaries × 3 sessions × 7 rounds = 252 正式槽位，每 case/session 另有 2 个 warmup。真实 CUDA 初始化的 VmSize 为 5,063,843,840 bytes，配置据此请求 `host_memory_limit_mb=16384`，并在 executor 资格时实际强制、读回。数据/误差界/轮次数在 executor 实测前冻结，preparation 不执行 CUDA；generator source snapshot 与 fixture/config SHA 均保存。

```bash
PYTHONPATH=benchmark/src python -m tsbench.gpu prepare benchmark/experiments/gpu-p4
PYTHONPATH=benchmark/src python -m tsbench.gpu qualify benchmark/experiments/gpu-p4/gpu-abs-0p01.toml --output runs/gpu/new-qualification
PYTHONPATH=benchmark/src python -m tsbench.gpu run benchmark/experiments/gpu-p4/gpu-abs-0p01.toml --output runs/gpu/new-formal
PYTHONPATH=benchmark/src python -m tsbench.gpu report runs/gpu/new-formal
```

准备目录及 run output 均拒绝覆盖已存在的内容。`qualify` 不生成正式 timing schedule，其编码/解码时间只作为 admission diagnostics；`run` 为全部真实输入重新资格验证后再执行 frozen schedule。CPU-only 单元测试验证 framing、配置、生命周期、精确 schedule、故障传播及实际 process-group 清理；mock 成功不作为 CUDA codec 资格或性能证据。

## 2026-10-13 资格与正式结果

原始 task/native equal-bound 两轮已实测，但存在严格 f32 误差拒绝：task 0.01 的 32769/1048576 点分别有 5/77 个 violation，`max_abs=0.010000228881835938`；task 0.1 的 1048576 点有 10 个 violation，`max_abs=0.10000228881835938`。同输入的两种边界均拒绝对应 case。原始 252 槽位分别为 168 ok / 84 not_run 和 210 ok / 42 not_run；不报告被拒 case 的正式性能。

观察失败后冻结了显式 `codec_parameter=0.9*task_request` 的敏感性政策，保持 task ABS 0.01/0.1，codec 请求改为 0.009/0.09。两轮原 synthetic 和两轮真实单列 f64 共 **840/840 正式槽位**全部恢复并通过严格 task 质量；40 cases 各含 3 sessions × 7 rounds，另有 40 个 exact-input 独立 decoder 与 240 个 warmup。每轮来源与精确覆盖审计通过。0.9 是观察失败后的固定政策，有限输入成功不提供普遍误差保证；synthetic large f32 误差仍略超过 codec 参数。原因、冻结配置和原始失败见 [gpu_margin90.md](gpu_margin90.md)。

真实输入为 ETTh1 `OT` 和 weather `T (degC)`，直接读取冻结 CSV 的 `[2048,2176)` / `[2048,2560)`，分别 128/512 个 `<f8>` 值。weather T 记录为 degree Celsius；ETTh1 OT 精确物理单位未核实。128 是 512 的前缀，窗口已有 CPU 研究暴露；结果分别按 source、长度、task 和 boundary 保存，没有 CPU baseline。完整持久化 wire ratio 已包含 schema/provenance、checksums 与 rate table，小数组可能 expansion。逐 case 的 wall median/IQR、bytes、ratio、误差、辅助成本与 raw SHA 链见 [GPU 实测结果](gpu_results/README.md) 和 [summary.json](gpu_results/summary.json)。

四轮实际设备为 NVIDIA GeForce RTX 2070，compute 7.5，CUDA runtime 11080 / driver API 12020；worker/decoder affinity 为 `[0]`，adapter algorithm host parallelism 1，object worker 1。`RLIMIT_AS` soft/hard 均为 `17179869184` bytes 并实际强制，VRAM cap 为 null 并记录原因。资格、warmup、formal 共 1120 个成功 encode/decode 对的 calling-thread native counters 为 allocation/free `11200/11200`、stream create/release `2240/2240`、event create/release `4480/4480`，各对始末 live bytes 为 0。这是 adapter 申请与回收证据，不是整设备 VRAM 峰值或 runtime/cache 清空证明；event 值也不是纯 kernel 时间。

40 个正式资格独立 decoder 均有 exact wire hash、全局唯一且不同于 16 个 encoder workers 的 PID、原始域质量、来源/build/device 身份与实际资源读回。正式 `independent_recovery` 未保留 decoder 各自的 native allocation/event/stream counters 或 `process_snapshot`，机器结果明确填 null 与原因；不能补填这些进程的计数/线程快照，或把 [native qualifier](research/cuszp_qualification_20261013.md) 的 48 个 fresh decoder 回收计数移用于这些进程。每 trial 新建 Session，新 worker 解释器的边界是 session。两种完成边界的数值保持各自估计，不合并吞吐或解释为 CPU object_memory speedup。
