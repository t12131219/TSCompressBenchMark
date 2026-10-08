# SIMDComp 源码准入初审（2026-10-07）

依据工程计划 7.2、7.6、8.3、11.5、13.3、20.3，处理工作簿“全量审计”
第 137 条 SIMDComp。当前完成原始源码冻结、独立补丁、SSE4.1/AVX2 源码
API、有界 uint32 C ABI 和直接 Python SDK 范围资格。三个 P0/P2 身份已注册，
支持与拒绝的五层资格、三组正式重复与独立审计已通过。其他 ISA 和 checked
int64 Timestamp 仍 pending，不宣称完整逻辑条目已完成。

本地仓库 `lemire_simdcomp` 对应 `lemire/simdcomp`，当前 clean commit 为
`d5301778fe5045ca8099252de5a6ed8016a287df`，无 submodule。需要的八个
translation units、九个 public headers、两项上游测试、两个 benchmark、
示例与构建/许可文件原样放在 `vendor/simdcomp/`。每份文件都与固定 Git
tree 的 bytes 比较；复制清单和 SHA-256 在 `SOURCE_LOCK.json`。共享原目录
只读，未改动。BSD-3-Clause 许可证完整保留。

优先审阅了 FastPFOR 的 `SIMDBinaryPacking` benchmark 路径：其接口为
`encodeArray/decodeArray`，包含 count、16 个 mini-block 的 width 元数据，
使用 `SIMD_fastpackwithoutmask_32`，要求输入长度满足 128 的块约束。
它与原始 SIMDComp 的公开 API 和容器不同，不能名称匹配后直接替代。
两者的 commit、实际相关文件 hash 均记录，FastPFOR 仅作为参考。

原 SIMDComp 本身的 `benchmarks/benchmark.c` 与
`benchmarks/bitpackingbenchmark.cpp` 调用原始 SIMD pack/unpack/D1 API。
后者报告 fastest，前者使用旧计时循环；这两套数字均不导入本项目统计。
新 CMake 默认 `-march=native` 且 benchmark 会 FetchContent 下载 counters。
资格构建须禁用这两个默认行为，明确 compiler/ISA，全部 out-of-tree；
正式测量仍由 Python 的统一 warmup/repetition/resource/FinalBits 流程驱动。

已确认 API 与数据合同：

- 这是 uint32 位打包 primitive；README 明确不定义压缩格式。不得直接
  以 P1 完整 codec 身份参加统计。count、width、seed、分块和 padding
  必须进入明确的可解码包装及账本。
- `simdpack` 和 `simdpackd1` 会按 width 掩码。无损资格必须验证数值或
  模 2^32 residual 全部可由 width 表示，不能丢掉高位后标 PASS。
- `simdpackwithoutmask` / `simdpackwithoutmaskd1` 有范围前提；调用前须
  检查原始 `maxbits` / `simdmaxbitsd1` 并独立复核。
- plain full block 为 128 × uint32，实际输出 width 个 128-bit vector，
  即 `16*width` bytes。文档示例中的另一 byte 倍数不能用作计费真值。
- arbitrary-length plain 有 `simdpack_length` / `simdunpack_length`；其
  shortlength 的四 lane padding/word rounding 必须由实际返回 pointer
  和独立 packed-byte oracle 验证。width=32 的 tail 为实际 `4*N` bytes。
- 原始 `simdpack_compressedbytes` 返回 int、参数 length 为 int，需检查
  算术上界；返回 pointer 不总是 16-byte 对齐，不可直接做 vector 数量
  推断。N=0/1/2、127/128/129、width=0/1/31/32 都必须独立覆盖。
- 原 D1 API 是 successive uint32 模运算。plain、D1、FOR、SSE/AVX2/
  AVX512 是不同 API/路径，不得与 checked int64 timestamp 混为一体。
- plain 128-bit kernels 至少 SSE2；D1 编译条件会选择 SSSE3/AVX 的实现，
  部分 util/FOR/query API 使用 SSE4.1。必须冻结实际 compiler flags 和
  当前路径；本机不支持的 AVX512 不能宣称已执行。
- select/search 依赖 slot/count 及排序前提，原 API 不接收 buffer capacity。
  bounded shim 需要安全输入/输出检查和失败原子性。query 合同单独审查。
- 原 `simdfastset` 的 width=32 移位已由独立 UBSan 实测确认；原始失败
  与显式补丁证据见下文，不以原上游 unit PASS 代替这些边界检查。

## 当前源码资格与已复现缺陷

原和补丁版本各运行 release/debug/ASan+UBSan 的 unit、unit_chars、example，
共 18 次上游程序均 PASS；默认断言保持启用。独立 source_guard 分别执行
plain、D1、FOR、两种查询和三种修改 API，每来源 24 个进程检查。
原版本保留 13 项失败；补丁后的 24 项全部 PASS。

- 原 width=32 的 fastset 触发 UBSan，修正 mask 的 32-bit 特例。
- 原 D1 width=32、length=0 lower-bound 返回错误位置，提前返回空搜索结果。
- 原 FOR 查询未命中会调用越界 slot，protected page 触发 SIGSEGV，ASan
  栈明确在 simdselectFOR 的 READ。修正不再读取 length 位置。
- 原 D1/FOR 的 width=32 码流实际存 absolute uint32；原 setter 错把差值
  当 absolute value。修正 FOR 直接设置 absolute，D1 保留其文档约定的
  suffix 模 2^32 位移，两种 D1 setter 路由保持一致。

三个 patch 位于 `patches/`，仅在 build 的生成副本应用；原 27 个 vendor
文件逐份保持锁定 hash。补丁未改 pack/unpack 码流；原和补丁都逐 byte
与独立四 lane scalar wire 一致，包括 width=32 的 absolute 特例。

每档补丁程序共 36432 场景、484638 次 select/search 检查，覆盖 33 个
width、四 seeds、三 patterns、28 个 length、所有 128 slots、空与未命中、
unsigned 分界、模溢出、read-only 输入、exact guard page 和前 canary。
D1 packing 原 API 只处理完整 128 值；不冒充任意 tail API。
部分 full-block/FOR/D1 width=32 内核要求 16-byte alignment，本轮完整块
满足该前提，不能据此声明 alignment=1。有界 ABI 必须显式 staging 或拒绝。

`tools/audit_simdcomp_source.py` 重查实际二进制/对象、compiler -MD 闭包、
断言和 sanitizer flags、固定 ISA、原失败、guard 的真实命令/覆盖，并在
独立临时目录重放三补丁、逐份比较测试生成源码。实际上游 compiler closure
original/patched 各档为 release182、debug175、sanitizer182，含 system headers。
证据篡改反例覆盖源码/patch/binary/driver 漂移、缺失 API/命令/依赖、伪造
覆盖率和未实际启用 sanitizer 的报告。最终证据入口为
`build/source-audits/simdcomp-source-current-audit.json`。

## AVX2 源码范围资格

原版与应用三个公共补丁、一个 AVX2 专属补丁的版本分别运行三档构建，
每档执行 unit、unit_chars、example 和九种独立 guard 模式，共 72 个程序。
原版保留 16 个失败（SSE 的 13 项及 AVX2 的 3 项）；补丁版全部通过。
每档 AVX2 guard 额外覆盖 1584 个场景：33 widths × 6 patterns × 8 alignments，
逐 byte 与独立八 lane scalar wire 比较，并检查输入只读和输出 guard page。

原 `avxunpackblock0` 的 `memset(pout,0,256)` 只清零 256 bytes，实际需要
256 个 uint32，即 1024 bytes。三个档位都复现 width=0 解码错误。补丁
`patches/avx2/0001-zero-width-unpack-byte-count.patch` 使用
`256 * sizeof(*pout)`。首次仍含此缺陷的报告、driver、guard 和三个失败
可执行文件保存在 `build/source-audits/simdcomp-avx2-initial/`，报告为
`build/source-audits/simdcomp_avx2_source_initial_tests.json`。

`tools/audit_simdcomp_avx2.py` 独立核对所有 72 项、实际编译闭包和 ISA/
sanitizer flags，并重放四补丁。当前 compiler closure 为 release199、
debug191、sanitizer199（每来源每档，含 guard/system headers）。额外
AVX2 补丁不会改变已冻结 SSE driver/guard 或其三个补丁的证据。

## 有界 C ABI 范围资格

`contract.md` 定义 SBP1：count、seed、wire mode、block geometry、各块
width/layout/实际 payload size 以及 checksum 全部序列化。固定开销 48
bytes，另每块 8 bytes；logical value bits 和 physical padding bits 独立
计费，实际物理长度闭合。D1/FOR width32 沿用原 absolute-value 特例。

`build_native.py` 生成副本应用四补丁；shim 固定 baseline x86-64，关闭
自动向量化/SSSE3/SSE4.1/AVX。六个源 TU 固定 SSE4.1，AVX 原内核与 bridge
分别编译为 AVX2；不编译 AVX512 TU。创建上下文前检查 CPU ISA，无 fallback。
保存 release/debug/ASan+UBSan 的命令、九个对象、库和 -MD 闭包；原 vendor
不变。当前 native compiler closure 为 release163、debug158、sanitizer163。

每档分别运行实际共享库、相同对象链接的故障可执行文件，每个可执行文件
覆盖 31878 个独立 scalar SBP1 场景（9 配置、33 widths、23 lengths、8 外部
对齐偏移、D1/FOR 四 seeds），共 191268 个场景检查。额外验证 exact guard
pages、只读输入、最小输出容量、alias/非法描述符、截断与畸形 frame、非零
padding、非最小 width、空输入、Finalize/Reset、fresh decoder 和真实账本。
故障路径检查 allocator 失败及对应释放数、API route、width/length 错误、
时钟失败/倒退、计时累计/重复查询/清零、失败 API 的计时与 caller 输出原子性。
共享 timer 的 overflow fixture 也执行，leak sanitizer 未启用，如实记录。

初稿把长度型 API 返回 NULL 当成功；独立故障注入复现了三种 API 的编码/
解码共六条错误成功及 caller 写入。修复为仅 void API 不检查返回 pointer，
长度型 API 必须严格等于期望末端。初稿 shim、可执行文件和 0/6 原子拒绝
观察保存在 `build/source-audits/simdcomp-native-initial/`；修复后各档六条
路径全部原子拒绝。wrong non-NULL pointer 与 AVX2 的 SSE 尾块也独立注入。

证据入口：`build/source-audits/simdcomp_native_tests.json` 和
`tools/audit_simdcomp_native.py`。独立审计核对真实共享库加载、same-object
链接、所有 compiler dependencies/flags、原始错误及三档完整矩阵。

## 直接 Python SDK 范围资格

`src/tscompbench/adapters/simdcomp.py` 驱动已验证的 release 共享库，三种独立
身份分别为 `simdcomp-u32`、`delta-simdcomp-u32`、`for-simdcomp-u32`。仅接收
VALUE/UTS 的 rank1 `<u4`，九个原始 API/ISA 组合使用明确的 coding/seed。
float、int64、MTS、validity 与不同 wire mode 均拒绝，未进行隐式转换。

容器采用 canonical JSON descriptor、SHA256 和原生 SBP1。独立 Python
scalar wire oracle 验证九种配置、33 widths、块边界、strides、生命周期、
最小容量、畸形流与计费；888 项全部通过，无失败或跳过。原生计时默认开启，
关闭计时不改变码流。描述符、checksum、logical codeword 与 physical padding
全部精确计费。输入 gather 与原生 staging 均在 telemetry 中显式记录。

资格驱动重新确认原始仓库 clean、commit 未变、27 个 vendor 文件逐份一致。
注册阶段实际加载的项目 Python 闭包为 80 个文件，包括复用的 MaskedVByte buffer
helper、Deflate ABI descriptor 和 NativeTimingProbe。独立 SDK auditor 逐份
校验闭包/hash/JUnit/native 证据；篡改反例包含删掉 buffer helper 并同步伪造
闭包摘要，防止仅凭自报 PASS 接受不完整证据。

入口为 `tools/qualify_simdcomp_sdk.py`、`tools/audit_simdcomp_sdk.py` 和
`build/source-audits/simdcomp_sdk_current_audit.json`。

## P0/P2 注册与五层范围资格

三种身份使用同一个冻结源码与实际 release 共享库、九个分离 ISA 对象和
四个显式补丁。注册工厂核对 source/binding/object/patch/generated-source/
compile-command/runtime dependency hash，以及实际 Python 源码闭包。
SOURCE_LOCK 保留原冻结时的 pending 事实，不回写其 hash；当前资格见独立
审计及接入清单，不能根据初始 lock 中的状态推断当前资格。

`src/tscompbench/preprocess/simdcomp.py` 为 D1 与 FOR 提供各自 A/B/D 合同。
A 是原始模 2^32 残差，B 是原 lane packing，D 是完整容器；没有后端 C。
关闭 A 选择独立 P0 身份。原始源码 API 融合 A/B，分阶段时间记 null，不
伪造数值。独立 scalar oracle 验证残差、逆变换、width32 absolute 特例、
尾块 padding 和每个实际字节。FOR LENGTH/FULL 使用不同 wire mode。

163 项框架测试通过。持久化资格矩阵包括 44 个支持配置任务（42 PASS、
2 个非法 AVX2 LENGTH 组合为 SCHEMA_ERROR），88 个真实 float/int64 拒绝
任务（84 UNSUPPORTED、4 SCHEMA_ERROR）。所有任务均进入 raw/coverage，
QUALIFICATION 不进入正式性能排名。三个资格与三个拒绝 run set 位于
`runs/<key>-{qualification,unsupported-qualification}-20261007-1/`。

`tools/audit_simdcomp_run.py` 独立解析实际 lane words，不调用源码或阶段
validator；核对原始 fixture/canonical bytes、三种身份、API/ISA/seed/timer
矩阵、逐次完整物理账本、真实 API 与 staging telemetry、解码、raw CSV、
Coverage 和统计。运行审计与 SDK 证据测试共 45 项通过（13 SDK、32 run），
包含正确 checksum 下的伪造 payload/seed/descriptor、不执行任务的伪造计时/
资格，以及正式统计分位数、CI、CV 的篡改反例。

`tools/qualify_simdcomp_benchmark.py --run-suffix 20261007-1 --formal` 已串行
完成三个 `formal-20` 配置：CPU0、单线程、至少 3 次且 0.5 秒预热、每有效
配置 20 次、编码/解码各至少 1 秒。普通组 202 条（198 PASS、2
RESOURCE_PRESSURE、2 SCHEMA_ERROR）；D1 组 80 条（78 PASS、2
RESOURCE_PRESSURE）；FOR 组 80 条（79 PASS、1 RESOURCE_PRESSURE）。
共 355 次 eligible，每合法配置至少 10 次；所有资源压力与非法配置留在 raw。

三个独立审计均 PASS，证明 wire/raw/coverage/summary 和完整账本一致，
重新计算正式统计与 CI。driver 终态、九个 run set 与实际导入的 95 个框架
文件 hash 均已核对；最终报告名使用下划线，避免混入冻结 SSE 证据 glob：
`build/source-audits/<key_with_underscores>_five_layer_audit.json`。
本次正式范围为 uint32 UTS P0/P2，仍不代表完整逻辑条目或 int64 Timestamp。
