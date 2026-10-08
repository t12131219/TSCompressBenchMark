# SIMD Differential Coding 准入调查（2026-10-07）

对应全量审计 index 95 / worksheet row 101，来源
`lemire/FastDifferentialCoding@714a9febba97ffb6b574c7a41cf1142090558727`。
本地源 clean、无 submodule；本卡与 SOURCE_LOCK 在写 adapter 前落盘。
只复制实现/API、自测、example、构建入口与许可七个原样文件，原 `_repos` 只读。

已按计划 7.2、13.3 阅读完整 README、公共 header、实现、unit test、example、
makefile 和 Apache-2.0 LICENSE。原 API 有四个入口：D1 successive differences
及 prefix sum，各提供 distinct-output 与 in-place 版本；uint32，starting_point
显式传入，void 返回，无分配、错误码、码流 metadata 或 finalize。
差值和恢复都是模 2^32 运算，任意位模式可逆，包含重复、OOO、负方向与边界。
它不缩短字节数，属于 P0 变换 primitive；后接压缩器时需独立 P2 身份。

先审查本地 Benchmark 的 `fast-pack_FastPFOR/headers/deltautil.h` 和 example.cpp：
`Delta::fastDelta` 是 D1，而其 `Delta::deltaSIMD` 为 D4，按 i-4 求差。
example 中的默认 SIMD 示例并不是本条目的 D1 算法。`fastDelta` 也使用不同
循环、seed/空数组处理，不能把它标成已冻结 FastDifferentialCoding 的原 API。
本地 inikep_lzbench 与 TSBench 未找到该确切 `compute_deltas` 公共 API。
因此选择清单指定的精确原来源；Benchmark D1/D4 可作为额外对照，保持来源区别。

原实现明确使用 `_mm_lddqu_si128`、`_mm_alignr_epi8` 和 `_mm_extract_epi32`，
完整 groups of 4 之外为 uint32 scalar tail；需要固定 SSE4.1 和 runtime CPU gate，
禁止 makefile 的 `-march=native`。无 runtime scalar fallback。SIMD loads/stores
不要求 16-byte alignment，但 scalar tail 是 typed uint32 access；对外 alignment 1
如需注册，shim 必须 memcpy 到合法 typed staging，并记录 copy 和 timing boundary。
实现只读取完整 4-word groups 与合法 tail，源码无 external padding 需求，需 guard
pages/sanitizer 实证。distinct API 标记 restrict，不允许重叠；in-place API 需单独路径。

starting_point 是逆变换所需元信息。P0 的 Benchmark 对象必须把 count、seed、
dtype/shape、实际 transformed uint32 bytes 和 wrapper 计入 FinalBits，不把原 API
的裸 transformed buffer 冒充自包含 codec。native timer 只包原 API 调用；staging、
FFI、descriptor 和全部 wrapper 包含于主 CORE/PIPELINE。uint32 P0 不能隐式截断
int64 时间戳；后续 timestamp pipeline 需声明精确 limbs 或 checked-domain 方案。

本轮实际运行：原上游 unit.c 和独立 `tests/source_guard.c`，各通过 release/debug/
ASan+UBSan。独立 unsigned scalar D1 oracle 共 520 cases/档，覆盖四个原 API、
四种 starting_point、empty/tail/SIMD 边界、fullrange、重复/OOO/模溢出、read-only
输入和精确长度 protected-page 输出。日志与编译命令、可执行文件 hash 保存在
`build/source-audits/fast-differential-source-tests.json`。leak detection 关闭，
平台仅 Linux x86_64/SSE4.1；不存在跨平台或 leak-clean 声明。

当前新增有界 ABI 与 Python SDK 驱动，合同见 `contract.md`。bounded shared ABI
与链接相同 objects 的 fault-injection 程序分别通过 release/debug/ASan+UBSan，
每程序 4160 组，两 API 模式、四 seeds、26 长度、五 patterns、四 alignment offsets。
覆盖原 API/unsigned scalar oracle 字节等价、保护页、源只读、capacity/alias、
corruption、reset/finalize、分配失败、原 API 实际路由与 timer query/reset/fault。
原生报告：`build/source-audits/fast-differential-native-tests.json`。实际编译依赖
由 compiler -MD 产生，含 system headers；baseline shim 单独构建，原 API TU
固定 SSE4.1，避免 ISA gate 本身先执行 gated 指令。source vendor 未补丁或改写。

Python 直接 SDK 资格覆盖完整可解码 descriptor/FDC1、精确计费、测量开关不改
码流、fresh decode 按 wire seed/mode、readonly/stride/reverse/misalignment、
非法 dtype/params 与失败原子性。来源、binary、binding、commands、实际 compiled
closure 的当前一致性需以独立 audit 为准。

registry/factory/central-builder 已准入，框架完整 boundary、ConfigID 和五层测试
24 tests PASS。16 参数组合的正式批次各保留 20 次尝试，共 314 PASS 与 6 次系统
换页压力诊断，各配置 17–20 次可统计；没有补轮或删除失败尝试。额外保留
16 次非排名资格 PASS，以及 ETTh1 两 tracks ×16 参数共 32 条未执行的能力
不匹配诊断。独立五层审计已通过，报告见
`build/source-audits/fast-differential-u32-five-layer-audit.json`，自省见
`docs/fast_differential_self_check.md`。原 source API、bounded ABI、Python SDK 和
Benchmark 五层资格分别记账；当前范围限 synthetic uint32 UTS 的四原 API、
两模式、四 edge seeds 和 timer 开关。int64 timestamp/P2 后端资格仍未声明，
全逻辑条目保持未完成。
