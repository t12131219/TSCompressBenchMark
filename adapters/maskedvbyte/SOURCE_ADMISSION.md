# Masked VByte / Delta + Masked VByte 准入调查（2026-10-07）

全量审计 index 113 / worksheet119（Masked VByte）与 index93 / worksheet99
（Delta + Masked VByte）共享 `fast-pack/MaskedVByte`，冻结 commit
`e2298b7a28002e08f3f74755353b7229bfe6475b`。原仓库 clean、无 submodule，
Apache-2.0。11 个实现/API/测试/示例/构建/许可文件原样复制，原 `_repos` 只读。

先审查本地 FastPFOR 的 `headers/simdvariablebyte.h`、`src/codecfactory.cpp`
和 `src/varintdecode.c`。它的 MaskedVByte 只包装 plain uint32 编码，输出补
0xFF 到 32-bit 边界，使用另一个 `masked_vbyte_read_loop_fromcompressedsize`
入口。该包装与本条目的原四 decode APIs、delta seed、精确 byte length 不同。
lzbench 未找到本条目公共 API。保留原来源身份，不把 FastPFOR 包装冒充此项。

已阅读 README、两个公共 headers、encode 实现、decode 控制流与 scalar tail、
SIMD/group/prefix/query 实现、unit/example、Makefile/CMake 与完整 LICENSE。
lookup 与 shuffle 常量随 translation unit 原样冻结。原 API 提供两个 encoder、
四个 decoder（已知 element count / 已知 compressed size，各 plain/delta），
以及 delta 的 select 与 lower-bound search。plain 输入 uint32，payload 为
classic unsigned LEB128；delta 是模 2^32 的 D1，保留任意 uint32 prev。decode
没有容量或畸形数据错误合同，必须在 Benchmark 边界独立验证长度/码字后调用。

plain codec 与带原 delta 的组合应分开身份，不能暗中给 int64 时间戳截断。
P0 先资格 uint32 原 API；checked int64/zigzag/backend 需另设 P2，并如实核算
count、seed、dtype/shape、metadata、checksums 和 padding。所有四原 decode
入口须分别保留参数/API 路由证据。查询 API 先独立检查，不能从 decode PASS
推导 query workload 已接入。search 的排序前提与无命中 sentinel 必须明示。

原 source 使用 SSE4.1，含 scalar tail；另有编译时 AVX2 分支。基线资格固定
SSE4.1、无 -march=native、无 runtime fallback。README 的 AArch64 支持依赖
`sse_to_neon.h`，当前固定 checkout 缺少该文件，不能声明 ARM 构建可用。
外部 exact buffers 和 protected pages 需验证，不能依据测试的大 malloc 推断
safe overread=0。typed uint32 staging 与内部 copy 的成本必须可观察。

源审查发现需验证的 signed-shift 风险：fromcompressedsize 的 scalar tail 将
uint8 提升为 int 后左移至 bit28，full-range uint32 可能溢出；16-byte signature
reload 的 int newsig 左移也需要 sanitizer 实证。保留原文件和原始失败日志，
如需修正只以独立 patch 记录，保持码流与原 release API 字节一致。

已确认原 sanitizer 在 `varintdecode.c:1380` 报告 `15 << 28` 的 int 溢出；原
release/debug 三类检查通过，原 sanitizer 的上游 unit/query 通过，decode guard
失败保留。`patches/0001-unsigned-shifts.patch` 将五处 signature reload 提升为
uint64，四处 scalar byte shifts 明确为 uint32。encoder 未改，原 vendor 未改，
补丁仅在 build 生成目录应用。使用 non-PIE sanitizer 可执行文件避免首次 PIE
query 启动时无诊断 SIGSEGV；首次失败报告也保留，不冒充算法通过证据。

补丁版本的 upstream unit/decode guard/query guard 分别通过 release/debug/
ASan+UBSan。每 decode guard 1872 场景，覆盖 plain/delta、四 seeds、39 长度、
六 patterns；每 query guard 936 场景、175344 次 select/lower-bound 检查，
覆盖 unsigned 分界、重复和未命中 sentinel。保护页 input/output 为 exact
长度、read-only source/encoded data，无外部 padding；scalar oracle 独立生成
LEB128 bytes。这里只证明测试范围，畸形码流仍须由有界 ABI 拒绝。

原与补丁共 18 个 executable 检查完整落盘，原失败不删除。compiler -MD 保存
系统 header 在内的实际闭包：original/patched 每档 release179、debug171、
sanitizer177。独立 audit 重查文件/测试/可执行/闭包/原失败，并在临时目录
重新应用补丁验证生成源码一致性。

报告：`build/source-audits/maskedvbyte-source-both-tests.json`；独立审计：
`build/source-audits/maskedvbyte-source-current-audit.json`。源码阶段的历史状态为
`SOURCE_BOUNDED_ABI_DIRECT_SDK_QUALIFIED_REGISTRATION_AND_FIVE_LAYERS_PENDING`。
当前注册与五层有限范围资格见本文末尾；未签署整条逻辑算法接入成功。

本轮补充有界 MVB1 C ABI 和 out-of-tree 三档构建；baseline shim/encoder
与 SSE4.1 decoder 分离。构建前核对原 source lock，补丁只作用于生成目录；
compiler -MD 闭包 release149、debug144、sanitizer150 个依赖全部冻结。
三档 shared 与同对象故障 executable 各通过 9360 场景（共 56160），保留
六个原 API 路由、scalar payload、39 长度、六 patterns、两 coding、两 decoder
与适用 seeds、alignment1、只读 input、exact guard page、canonical malformed
LEB128、短容量、alias、lifecycle、分配失败、错误 API 返回长度、timer fault。
实际 allocation 请求、free 次数与 staging/copy telemetry 单独核对。共享 timer
overflow 检查也通过，不从可用墙钟误推累计溢出安全。

直接 Python SDK 的 159 项通过，共同 perform_roundtrip 验证 immutable/canary/
determinism 与 ledger；相反 decoder API、不同 configured seed 可独立恢复。
两语义 key 区分 plain 与原 modular32 delta+VByte；descriptor 固定各自 stage。
decoder_api/native_timing 为执行参数，不进入 serialized wire parameters。
每个 FinalBits 与最终 bytes 对账，native payload/metadata/checksum 全计入。
SDK 解码借用 immutable bytes frame，不隐式复制 payload；strided/reverse gather
显式进入 telemetry。源码、native、SDK 三类独立 auditor 分层重查，SDK 记录
76 个实际导入的项目 Python 文件；变更后不得复用旧通过状态。

新证据：`build/source-audits/maskedvbyte-native-tests.json`、
`maskedvbyte-native-current-audit.json`、`maskedvbyte-sdk-tests.json` 与
`maskedvbyte-sdk-current-audit.json`（后三项同目录）。原完整源码故障矩阵仍保留。

正式框架已修正为 encode/decode 各自达到最短时长后结束。当前两身份在
固定 CPU 0、PIPELINE、每配置预热 ≥3 次且 ≥0.5 秒、正式 20 次下完成五层：
`maskedvbyte-u32-formal-20261007-2` 为 4 配置 / 80 eligible；
`delta-maskedvbyte-u32-formal-20261007-2` 为 16 配置 / 320 固定尝试、315
eligible、5 RESOURCE_PRESSURE。压力记录原样保留，不补测替换。
资格和 Unsupported 对应 run ID 使用同一 `qualification-20261007-2` 后缀。
独立 `audit_maskedvbyte_run.py` 的两个五层报告均 PASS。这里只签署原
plain uint32 和原融合模 2^32 D1+LEB128 的范围，int64 checked timestamp
pipeline、其他 dtype/API 范围仍需另建身份及资格，两条完整逻辑条目仍未完成。
