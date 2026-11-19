# ALP Auto（selection 9）：批编码与解码后端

锁定 `alp-native/unique-v1` 源码归档 SHA-256
`684ec6ef490b263cda133867ccfa5437d14c9c9d6024f5fefd244e2f7476e605`。
Unique 的 `fix_ReWrite/alp-native/FUNCTIONAL_REPORT.md` 与归档中同名成员逐字节一致；
[发布验证](../../third_party/provenance/alp-native/unique-validation.json) 记录 `test_codec` 历史通过。
复用该结论，不重跑 Unique 整套用例；以下内容只验证 TSBench 当前封装、实发分支和实际后端。

| 原生操作组 | 实际入口与判定 | 不能外推 |
|---|---|---|
| `auto-batch` | `alpn_compress(..., ALPN_AUTO, ...)`；按 `ALN1` 实发编码分别检查 decimal、RD、raw group 和 raw vector，以及恢复位。 | RD 是 Auto 内部选出的分支，不是另一个 selection、强制 RD 方法或独立性能成绩。raw group 不记录回退前的候选。 |
| `decode-backends` | `alpn_inspect` 核对 dtype/count，`alpn_decompress_ex` 解码；后端是否编译、运行时是否可用、实际 dispatch 和 decimal 内核计数分别记录。 | dispatch 不代表实际处理过 decimal vector；AVX2 专用计数器不代表所有 SIMD 路径，更不代表编码 SIMD、线程并行或加速比。 |

## 数据、产物与恢复

`alp-auto` ABI 路线是单线程批处理，输入限 little-endian、连续、无 validity 的 rank-1 f32/f64
V。逻辑数据最大 64 MiB，schema 最大 64 KiB；`BMKALP` 32 字节封装、schema 和 `ALN1` payload
分别计字节。省略 `decode_backend` 时使用 `scalar-unfused`；选用解码后端不改变编码格式。
直接调用验证编码和解码均拒绝非 `FE_TONEAREST` 浮点环境。

[用例清单](../../configs/suites/dev_alp_v1/cases.json) 锁定四种合成输入各跑 f32/f64，另取 v2
气象 `co2` 测试分区首 1,029 个 f64 值。逐字节对照封装中的 native payload 与直接调用输出；独立解析器识别
1,024 值 vector、102,400 值 rowgroup、跨组 decimal→RD 切换和气象尾块。混合 decimal/raw
样本的 decimal sidecar 保存六种特别位模式（负零、最小 subnormal、正负无穷、两种带 payload 的
NaN），按原始位校验。移除 staged 输入后以新 worker 恢复同一产物，独立核对数据值字节和 schema；
这不宣称操作系统禁止访问所有原始数据路径。

## 实际后端和证据边界

开发诊断在九个产物上得到 32 次精确恢复、13 次预期的后端不可用拒绝与 27 次异常产物拒绝。
f32 的 FALP Auto 实际选 `falp-scalar`；本机 f64 的 FALP Auto 实际选 `falp-avx2`，只有
含 decimal vector 的产物出现对应内核工作计数。RD-only/raw 产物即便显示相同 dispatch，
decimal 工作仍为零。`falp_avx2_vectors` 只统计 AVX2 decimal 内核，`native_falp_simd_counter`
是兼容别名。f64 AVX512BW 已编译，当前宿主没有向进程暴露 AVX512F/BW/DQ；显式请求按合同
拒绝，属于运行环境不满足，不是实现失败。**保留在原生功能清单中，状态为待兼容环境实测。**
具备三项 ISA 且原生探测可用时，在含 decimal vector 的 f64 产物上核对显式 `falp-avx512bw` 和
`falp-auto` 的实际 dispatch 及独立进程逐位恢复；不以 AVX2 计数器或仅 RD/raw 的输入作证。
NEON/SVE 不属于当前 x86-64 插件范围。异常产物测试不代表对任意不可信外部码流的安全承诺。

[验证器](../../tests/isolation/alp_control.py) 用
`ctest --test-dir <build> -R tsbench.worker.alp-auto.branches --output-on-failure` 运行，
`alp-native-control/report.json` 记录构建、窗口、分支、字节、后端与恢复结果。统一预检封存九份完整帧
和一份 8,232 字节的气象尾块原值；其余合成输入在离线复算时按冻结规则再生成，不重复封存。
九个新增绑定覆盖两种宽度的分支、特殊位 sidecar、跨组切换、舍入模式拒绝、异常侧信息和后端行为。
针对 f32 和 f64 的真实 decimal sidecar 分别做两种等长变更：将位置改为越界、将后一位置改为与前一位置重复。
这四个产物必须由原生 decoder 拒绝且不写恢复值；它们不是简单截断或封装长度错误。

离线复算读取 `ALN1` 结构、raw 向量与 decimal 异常位，不加载 codec；检查每次新进程恢复的 schema、
行数和原值摘要，复算异常侧信息变更及对应产物 SHA-256。它不在离线解析器中重算所有 decimal 或 RD 压缩值；
全量逐位恢复是在执行时用每个可用后端完成的。`FE_DOWNWARD` 拒绝在锁定的 C 接口直接验证，记录两个方向的状态、
零输出计数，以及退出该探针后的舍入模式恢复。

对首批 Linux x86-64 集成构建，探针要求 f64 的 `alpn_backend_built` 为真；缺失时明确报构建回归，
只有已构建且 `alpn_backend_available` 为假才记录 `pending_supported_runtime`。
**两组都只是开发诊断**，不提供正式计时样本，不授阶段或服务资格。

## `extended-v15`：同一 ALN1 裸帧的后端对照

在 [统一运行](../../results/m0-alp-decode-unified-20261119-r2/report.json)
`65e9e48d345640fca0a12ec3ef15c135` 中，`decode-backends` 使用既有九个冻结用例、原有四项必需义务和
两项条件义务。与 `auto-batch` 各自绑定，不增加 selection。C 诊断工具直接链接同一冻结 `libalp_native.so`；
每个用例用 `ALPN_AUTO` 编码一次，随后将同一裸 `ALN1` 文件分给五个独立进程：`scalar-unfused`、
`falp-scalar`、`falp-auto`、`falp-avx2`、`falp-avx512bw`。解码进程不挂原列、语料、外部 schema
或其他帧；父进程验证输出 SHA-256。九帧共 285,886 B，不留恢复值；[独立恢复](../../results/m0-alp-decode-unified-20261119-r2/restore.json)
从封存裸帧重跑请求及拒绝，再用标量恢复值重编码核对同一裸帧。复算报告只读封存证据，不执行 codec；独立
恢复要求与本次记录匹配的后端条件，兼容宿主的新增结论必须来自该宿主的新冻结运行。

| 用例范围 | 本次结果 |
|---|---|
| f32：20 次请求 | 12 次逐位恢复；Auto 选择 fused scalar；显式 AVX2/AVX512BW 共 8 次按宽度拒绝。 |
| f64：25 次请求 | 20 次逐位恢复；Auto 选择 AVX2；5 次显式 AVX512BW 请求按运行条件拒绝（`ALPN_INVALID`、`written=0`、无恢复输出）。 |
| f64 混合帧、跨 rowgroup 帧 | Auto 实测分别 1、100 个 AVX2 decimal vector；跨组帧另外有 2 个 RD vector。RD-only 与 raw-only 帧的 decimal 计数为 0，虽仍显示 AVX2 分派。 |

AVX2 条件有同次候选证据；f64 AVX512BW **已编译、未能在本机执行**，报告单列 `pending_supported_runtime`，不计通过。
兼容宿主上要求两个请求均实际分派 AVX512BW，并从含 decimal 的同一帧逐位恢复；该实现没有 AVX512BW 专用
decimal 计数，不以 `falp_avx2_vectors` 冒充。不提供吞吐或正式资格。

首轮在迁移、禁网环境空构建，15/15 CTest 通过，但策略路线顺序不符，提交前拒绝，没有运行账本。
第二轮只读复用并逐字节重锁该构建，重新执行 174 个 Python 测试，生成一份修正的冻结计划和一个运行账本；
旧 `extended-v14` 报告仍可逐字节复算，两个版本不拼接证据。

[计划拒绝检查](../../results/m0-alp-decode-unified-20261119-r2/controls.json) 与 [ALP 重封存负例](../../results/m0-alp-decode-unified-20261119-r2/alp-decode-reseal.json)
分别拒绝计划改写和证据篡改，包括删 AVX512BW 构建、把拒绝伪装成有写出、把 RD 误报为 decimal 工作、
给独立解码额外挂载原始值；不是安全认证或对外部不可信输入的保证。
