# FastDifferentialCoding 阶段自省（2026-10-07）

本阶段按工程总计划 7.2–7.8、8.2–8.8、11.3–11.5、16.1–16.3 执行。
221 条全量目标保留，未将一个原生库或一个 SDK 通过等同于五层算法接入。

来源：`lemire/FastDifferentialCoding@714a9febba97ffb6b574c7a41cf1142090558727`，
clean，无 submodule。七个 vendor 文件与只读原仓库逐文件一致，Apache-2.0。
先审查本地 FastPFOR，确认其默认 SIMD D4 与该条目的 D1 不同；保持身份区别。
原 vendor 未修改。该库只有 uint32 D1/prefix-sum 变换，属于 P0，不能声称
独立压缩或通过 int64/float 截断获得 timestamp 支持。

已实现所有四原 API：DISTINCT/INPLACE 模式分别调用对应 encode/decode，
保留任意 uint32 starting_point。原输入在两模式下均 immutable，INPLACE 使用
内部 typed scratch；外部 alignment=1，safe overread=0。完整 FDC1 保存 length、
seed、mode、words、checksum；Python descriptor 保存 dtype/shape/units/identity。
独立 decoder 使用码流 seed/mode，拒绝 descriptor 与 native frame 不一致。
Finalize 零 bytes 仍为必须事件；reset 保留参数并清空 timer/对象状态。

安全：原 source unit+guard 各三档 PASS，source_guard 每档 520 cases。
bounded shared-library 与 same-object instrumented executable 各三档 PASS，
每程序 4160 组，合计 24960 组（不把额外 rejection/fault assertions 混入计数）。
测试覆盖 uint32 scalar 数学 oracle、原 API 字节等价和交叉 decode、实际 API
路由、两模式/四 seeds/26 长度/五 patterns/四 alignment offsets、只读源与
exact protected-page 输入输出、canary、容量不足、alias、畸形 metadata/长度/
checksum、错误原子性、reset/finalize、分配失败。ASan+UBSan 全启用，leak
detection 关闭；资格只覆盖本机 Linux x86_64/SSE4.1。

计时：native timer 只包所选原函数；query 非破坏、多调用累计、reset、disabled、
clock failure/backwards 通过 adapter fault injection；accumulator overflow 经共享
timer qualification 通过。开关不改变 bytes。baseline shim 与 SSE source 独立
编译；无 `-march=native` 或 fallback。主时间保留 staging、copy、checksum、
descriptor、FFI；Python allocation telemetry 报 requested bytes，不冒充 RSS。

直接 Python SDK 103 tests PASS：独立 encode/decode、空与尾部、uint32 全范围
模式、数学 oracle words、exact ledger、不可变输入、canary、determinism、
fresh decoder 的不同配置、计时开关、strided/reversed/misaligned、capacity/
alias/reset/lifecycle、损坏码流、伪造 descriptor、非法 dtype/seed/ISA。
P0 words=4N 且 wrapper 造成扩张，如实计费，没有筛掉不好压缩的数据。

来源/binding/binary/command/object/runtime library/compiled closure 有独立当前
审计。compiler -MD 的实际 dependency closure 含 system headers，共 release147、
debug142、sanitizer147 项。审计拒绝过期证据，SDK 报告保留原命令/JUnit/hash。
测试用隔离副本验证 source、binding、binary、compile command、compiled closure
和依赖缺失六种漂移不能继续使用资格。

中央 builder、factory、manifest 和 onboarding 已接入。框架资格 24 tests PASS，
包括 16 参数组合的完整 boundary、默认值 ConfigID、五层执行、Unsupported 和
factory 依赖漂移拒绝。参数矩阵为两模式 × 四 seeds（0、1、2^31、2^32-1）×
native timer 开关，所有参数点均在正式运行前固定。

第一层核对源 NPZ 与 canonical 原始字节；第二层保留全部参数、P0 身份、实际
SSE4.1 与来源依赖；第三层边界、Finalize、完整码流、fresh decode 和逐位恢复；
第四层每配置预热至少 3 次且 0.5 秒，20 次正式尝试，每次至少 1 秒，CPU0、
单线程、独立对象；第五层从 raw 独立重算 mean/median/sample SD 和 micro rate，
检查报告哈希、资格过滤、native 关闭时空值，核算真实物理位数。

正式批次 `fast-differential-u32-formal-20261007-1`：320 次尝试，314 PASS、
6 RESOURCE_PRESSURE（系统 VMSTAT 检测到换页），每配置仍有 17–20 次可统计
重复。没有补轮、挑选最快值或把压力次数删除。资格批次 16 次 PASS，不参与
正式排名；ETTh1 的 VALUE/TIMESTAMP ×16 参数共 32 条能力不匹配诊断，确认
actual ISA=NOT_EXECUTED、没有转换、码流、计时或预热，完整保留且不参与统计。

独立审计：`build/source-audits/fast-differential-u32-five-layer-audit.json`。
数学 oracle 不调用原 API，独立检查 D1 words 与模 2^32 prefix sum；独立解析
descriptor/FDC1、SHA256/FNV64 和每项物理账本，并用相反 mode/seed 的 decoder
恢复。两 timer 状态共享相同码流，八个 mode/seed 码流在正式和资格批次相同。

worklist 的范围状态为
`P0_D1_UINT32_FOUR_APIS_SCOPE_QUALIFIED_OTHER_DOMAINS_PIPELINES_PENDING`；
资格覆盖 8193 元素的 synthetic full-range uint32 UTS fixture，不能据此宣称真实
int64 timestamp、有后端的 P2 或全逻辑条目已通过，
`full_logical_entry_qualified=false`。native/SDK 报告中的 five-layer PENDING 是
此前阶段的职责边界，五层完成证据来自独立运行审计。

共享 factory 已改，既有四个 Stream VByte 入口的历史运行被重新核验并标记
`CURRENT_REQUALIFICATION_REQUIRED`，保留历史证据，没有绕过 source/binding
漂移门禁。全量 221 条目标仍保留，其他算法仍需逐条审查和运行。
