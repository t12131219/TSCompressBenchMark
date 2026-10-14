# cuSZp 原始误差违约与 90% 参数敏感性配置

原始配置的 task ABS 请求与 codec 参数相同，但 f32 真实恢复出现严格误差违约。原始 run、qualification、正式 observation 和 artifact 全部保留；新配置不会修改旧 trial、放宽 verifier、改 kernel 或替换失败记录。

| 原始 task / codec 请求 | 输入 | Host / device 资格 max_abs | 每种边界 violation_count | 原始正式计划 |
|---|---|---:|---:|---|
| 0.01 / 0.01 | f32，32769 点 | 0.010000228881835938 | 5 | 该两种边界合计 42 槽位 not_run |
| 0.01 / 0.01 | f32，1048576 点 | 0.010000228881835938 | 77 | 该两种边界合计 42 槽位 not_run |
| 0.1 / 0.1 | f32，1048576 点 | 0.10000228881835938 | 10 | 该两种边界合计 42 槽位 not_run |

[`cuszp-formal-0p01-20261013`](../runs/gpu/cuszp-formal-0p01-20261013/report.md) 的 252 槽位为 168 ok / 84 not_run；[`cuszp-formal-0p1-20261013`](../runs/gpu/cuszp-formal-0p1-20261013/report.md) 为 210 ok / 42 not_run。失败发生在该实际输入的 admission 质量验证，随后对应正式槽位明确不运行；不能把 not_run 计为压缩成功。两轮 Python/native 来源均未变，host 与 device 同输入的 artifact 和误差相同。

## 失败机制

冻结 upstream [f32 kernel](../adapters/cuszp/vendor/cuszp/src/cuSZp_kernels_1D_f32.cu) 的 quantization（第 3–18 行）使用 `mul.f32(x, reciprocal)`、`add.f32(0.5)`、向零取整与负数修正。第 48 行计算 `reciprocal = 0.5f / eb`；第 490/513 行以 f32 运算恢复 `currQuant * eb * 2`。理想实数最近整数格点可以得到 ABS 上界，但实际 reciprocal、product、加法、int-to-float 及恢复乘法存在舍入。单纯把输入容差向下转换成可表达 f32，不能去掉这些后续算术误差。

两个从已有 CSP1 payload 的实际 quantized integer 解析得到的 witness 可确定此次违约：

- Task 0.01，medium 输入索引 1727：原值 `18.59000015258789`，实际 `eb=0.009999999776482582`，reciprocal 为 `50.0`，quantized integer `q=930`。精确 `2*q*eb` 的误差是 `0.009999431669712067`，仍满足 task；f32 恢复额外舍入约 `7.972121238708496e-7`，实际恢复 `18.600000381469727`，最终误差 `5243/524288 = 0.010000228881835938`。
- Task 0.1，large 输入索引 525697：原值 `26.09999656677246`，实际 `eb=0.09999999403953552`，reciprocal 为 `5.000000476837158`。f32 product 落在 `130.5`，最终 `q=131`；相对精确格点的偏移超过半格，精确 `2*q*eb` 已有误差 `0.10000187158584595`。恢复再舍入约 `4.172325134277344e-7`，最终值 `26.19999885559082`，误差 `26215/262144 = 0.10000228881835938`。

CPU-only NumPy f32 算术重放以上源公式，对六个原始 f32 输入精确复现已有 GPU max_abs 与 violation_count；重放结果保存在新 [preparation.json](../benchmark/experiments/gpu-margin90/preparation.json)。该重放仅解释算术机制，不能替代 CUDA bitstream decode、资格或性能测量。Native `2**28` quantization guard 防止保守 signed-int 域溢出，不证明严格 ABS 质量；较大 q 的 f32 integer conversion 舍入同样需要考虑。

## 独立新配置

新 profile 使用固定十进制 `codec_parameter = 0.9 * task_request`，两种 dtype 采用同一声明比例。Task 阈值、原始数据、verifier 和完成边界保持各自冻结定义，codec 参数显式改变，因此方法身份和 artifact 不同。0.9 是观察原始违约后声明的参数敏感性政策；它不是盲测最优参数或普遍误差保证。下面保存的有限输入现已逐项通过资格与正式质量检查；每个实际输入仍须独立资格并验证每轮质量，不因 margin 而增加容差。

| Task ABS 请求 | Codec 十进制参数 | f32 effective native 参数 | f64 effective native 参数 |
|---:|---:|---:|---:|
| 0.01 | 0.009 | 0.008999999612569809 | 0.009 |
| 0.1 | 0.09 | 0.08999999612569809 | 0.09 |

配置位于 [`benchmark/experiments/gpu-margin90`](../benchmark/experiments/gpu-margin90/preparation.json)：

- [gpu-synthetic-margin90-abs-0p01.toml](../benchmark/experiments/gpu-margin90/gpu-synthetic-margin90-abs-0p01.toml)
- [gpu-synthetic-margin90-abs-0p1.toml](../benchmark/experiments/gpu-margin90/gpu-synthetic-margin90-abs-0p1.toml)
- [gpu-real-single-f64-margin90-abs-0p01.toml](../benchmark/experiments/gpu-margin90/gpu-real-single-f64-margin90-abs-0p01.toml)
- [gpu-real-single-f64-margin90-abs-0p1.toml](../benchmark/experiments/gpu-margin90/gpu-real-single-f64-margin90-abs-0p1.toml)

Synthetic 两配置各保留原六个 NPY 文件及位元，不重新生成数据；每配置 12 cases × 3 sessions × 7 rounds = 252 槽位。Real 两配置直接解析外部原始 CSV 的 `<f8>` 单列 V：ETTh1 的 `OT`、weather 的 `T (degC)`，行 `[2048,2176)` 和 `[2048,2560)`，每配置 8 cases × 3 sessions × 7 rounds = 168 槽位。不做归一化、插补、重采样、多个通道 flatten 或再分发源数据。128 点是 512 点的前缀，这些 source windows 已被 CPU 真实数据研究使用，不能称为未观察 holdout。

weather T 的单位按列名记录为 degree Celsius；ETTh1 OT 仅有 oil-temperature 描述，冻结来源证据没有核实精确物理单位，故记录 `source_units_unverified`。相同数值 ABS 请求不意味着跨 source 的物理任务等价，结果应按 source/column 分开描述。GPU host_to_host 与 device_resident 是两种完成估计，CPU object_memory 又是独立边界；当前配置没有 CPU baseline，不进行跨单位、canonical schema、storage 或 boundary 的 pooled ratio/吞吐比较。

全部新配置请求 `device_index=0`、host affinity `[0]`、adapter host thread 1、object worker 1、`RLIMIT_AS=16384 MiB`、3 sessions、7 rounds、2 warmups、120 秒 timeout、保存 artifacts。VRAM 没有请求可强制 cap，实际 limit 仍为 null 并记录原因。

## 冻结与运行

新 [preparation.json](../benchmark/experiments/gpu-margin90/preparation.json) 包含全部新 config SHA/configuration ID、真实 CSV hash/column/window/单位与许可证据、canonical object ID、实际 native 参数、原始失败 run manifest/observations/summary/report SHA 与失败 artifact SHA，以及纯算术重放结果。`freeze_id=sha256:729d8d83326ee512b0f8f9fc6fdbca5186b1f838a176fc867783003b95703366`，冻结时 GPU execution source ID 为 `sha256:742ab710be4354a9bcc393cb1b02388606bf39f7c7423c4303d6cb076bca7074`。生成器 [prepare_gpu_followup.py](../benchmark/tools/prepare_gpu_followup.py) 和快照均保存； preparation 未加载 native library、未执行 CUDA、未改历史或 measurement source。

执行新配置需使用新的空 output。以 task 0.01 synthetic 为例：

```bash
PYTHONPATH=benchmark/src python -m tsbench.gpu qualify benchmark/experiments/gpu-margin90/gpu-synthetic-margin90-abs-0p01.toml --output runs/gpu/cuszp-margin90-synthetic-qualify-0p01-20261013
PYTHONPATH=benchmark/src python -m tsbench.gpu run benchmark/experiments/gpu-margin90/gpu-synthetic-margin90-abs-0p01.toml --output runs/gpu/cuszp-margin90-synthetic-formal-0p01-20261013
```

其余三配置同样先检查 exact-input qualification，再串行运行新 formal。任何未通过资格、质量、来源身份或资源回收的槽位继续保留失败/null/not_run，不覆盖原始 equal-bound 结果。`preparation.json` 中的 pending 是配置冻结时的历史状态，保留原文件；实际运行证据见下表。

## 2026-10-13 实际结果

| 正式 run | 数据与 task ABS | 正式槽位 | exact-input 独立 decoder | warmup |
|---|---|---:|---:|---:|
| [cuszp-margin90-0p01-20261013](../runs/gpu/cuszp-margin90-0p01-20261013/report.md) | 原六个 synthetic，0.01 | 252/252 ok | 12 | 72 |
| [cuszp-margin90-0p1-20261013](../runs/gpu/cuszp-margin90-0p1-20261013/report.md) | 原六个 synthetic，0.1 | 252/252 ok | 12 | 72 |
| [cuszp-real-f64-0p01-20261013](../runs/gpu/cuszp-real-f64-0p01-20261013/report.md) | ETTh1 OT / weather T，128/512 点，0.01 | 168/168 ok | 8 | 48 |
| [cuszp-real-f64-0p1-20261013](../runs/gpu/cuszp-real-f64-0p1-20261013/report.md) | ETTh1 OT / weather T，128/512 点，0.1 | 168/168 ok | 8 | 48 |

四轮共 **840/840 正式槽位**、40 cases，每 case 3 个新 worker sessions × 7 rounds；另有 40 个 exact-input 新解释器 decoder 与 240 个 warmup。只读审计逐项检查 manifest/planned/started/terminal 的精确 slot multiset、输入未修改、严格 task 质量、实际持久化 wire hash/大小/typed bound、资源 profile 与 native counters。原始 equal-bound 的 126 个 not_run 槽位保持原有状态，不计入这 840 个成功槽位。

两种完成边界的结果分别保存；完整的每-case median/IQR、ratio、误差、外围成本和原始证据 SHA 见 [GPU 实测表](gpu_results/README.md) 与 [机器可读审计](gpu_results/summary.json)。例如 synthetic f32 1048576 点在 task 0.01 / codec 0.009 下的 `max_abs=0.009000778198242188`，task 0.1 / codec 0.09 下为 `0.09000205993652344`：满足 task 阈值，但仍略超过 codec 参数，不能把 margin90 结果解释为 kernel 的严格 native 参数保证。真实单列分别按 source/column/单位描述，不建立 CPU speedup 或跨边界、跨单位的合并估计。

实际设备为 NVIDIA GeForce RTX 2070（compute 7.5，CUDA runtime 11080 / driver API 12020），affinity `[0]`、adapter algorithm host parallelism 1、object worker 1；worker 与 decoder 读回的 `RLIMIT_AS` soft/hard 均为 `17179869184` bytes。VRAM cap 为 null 并保留无法强制的原因。40 次成功资格对象对、240 次 warmup 和 840 次正式对象对的 calling-thread native counter 合计为 allocation/free `11200/11200`、stream create/release `2240/2240`、event create/release `4480/4480`，每对象对始末 live bytes 均为 0。该计数覆盖 adapter 自有对象，不测量 driver/context cache 或整设备 VRAM 峰值。

40 个正式资格独立 decoder 均从对应实际 artifact 恢复且通过质量，PID 全局唯一且不属于 16 个 encoder workers，来源/build/device/profile 与 run 相符。正式 `independent_recovery` 未保留各 decoder 自身的 allocation/event/stream counters 或 `process_snapshot`，因此这些值为 null 并附原因；不补填这些 decoder 的计数或线程快照。[独立 native qualifier](research/cuszp_qualification_20261013.md) 的 48 个 fresh decoder 回收证据属于该资格 suite，不移用到这 40 个进程。

四轮 execution source ID 与 preparation 一致，native build identity 为 `a61617a03e2e244a9ac87ecf83178d2feb3580ea4b43d3d088cdfc94e0da6498`，Python/native 来源末尾均未变。只读分析工具为 [summarize_gpu_results.py](../benchmark/tools/summarize_gpu_results.py)，未执行 CUDA；六个原始与 follow-up run 的 trace 集合 ID 为 `sha256:91968563430644d68b3cc0a3f515642f5304d7a0916a24353fc80678ee8212cd`，分析前后全部 trace 与 artifact SHA 一致。
