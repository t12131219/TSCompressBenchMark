# LittleIntPacker / Fixed-width Bit Packing 源码准入

当前范围：**原源码、build-only 修复后的 kernels、uint32 有界 C ABI 和
Python SDK 已执行并通过独立证据审计，五个原 API 实例已注册**。
当前SDK、五层资格验证和正式统计已在新的不可覆盖目录重新通过。
历史正式统计限于当时的合成 uint32 VALUE/UTS，公共factory改动后不能替代重测；
清单第 134、138 条均未完整接入。

## 来源与完整范围

- 原仓库：`https://github.com/fast-pack/LittleIntPacker`。
- 固定 commit：`8777f574a5ab3c653881371819383c986292843c`。
- 原 `_repos/fast-pack_LittleIntPacker` 只读；vendor 的 14 个文件逐一与
  固定 Git bytes 比较，无裁剪、无源码修改、无 submodule。
- Apache-2.0，`RUN_ALLOWED`；保留原 LICENSE。
- 使用原仓库的公共 API、完整 unit 与 `benchmarks/bitpackingbenchmark.c`。
  benchmark 的 RDTSC / fastest-of-50000 只作为行为参考，不用于正式统计。

| API 实例 | encode / decode | 实际 ISA |
| --- | --- | --- |
| PACK32 | `pack32` / `unpack32` | baseline scalar packing |
| TURBO | `turbopack32` / `turbounpack32` | baseline scalar packing |
| SC | `scpack32` / `scunpack32` | baseline scalar packing |
| BMI2 | `bmipack32` / `bmiunpack32` | AVX2 + BMI2 |
| HORIZONTAL | `pack32` / `horizontalunpack32` | SSSE3 + SSE4.1 |

`util.c` 的 `maxbits_length` 使用 SSE2，不能把整个源码闭包描述成纯 scalar。
固定每个 translation unit 的编译选项，禁止 `-march=native`、AVX512 和
自动向量化。源 API 接收 uint32 values、count 和调用方给定的 width 0–32；
它是 primitive，没有独立、自描述且有界的压缩对象，不自行提供 streaming/query。

## 原源码已实测的缺陷

1. PACK32、TURBO、SC、BMI2 的 width=0 decoder 每块只清零 32 bytes，
   实际应清零 32 个 uint32。完整原 unit 预先清零 decoded buffer，掩盖此问题；
   独立探针用 `0xa5` 初始化后，在 release/debug 每档发现 380 次 inverse failure。
2. 奇数 width 的连续块偏移为 `4 * width` bytes，TURBO/SC/BMI2 的 uint64
   pointer 访问出现真实 UBSan misalignment。原 sanitizer unit 在 SC width=1
   失败，独立 matrix 在 TURBO width=1 失败，原错误栈保留。
3. 原 API 无 capacity/length 检查。guard-page 实测的 exact input、packed
   output/input、decoded output 与 invalid width 均不安全。普通 kernel 按
   32 values 处理，HORIZONTAL decoder 按 128 values 写入；64-bit word
   访问还有额外 readable bytes。头文件的 padding 提示不能代替有界 ABI 合同。
4. 原 `byte_count` 的 uint32 乘法存在 overflow 风险。width/count 必须进入
   对象 metadata 和完整计费，不能由外部未计费配置隐式补齐。

原 release/debug 的完整 unit 输出 `All tests OK!`。独立 API matrix 每档
18,975 cases，release/debug 均完整执行并保留已知失败；原 sanitizer 执行到
真实 UB 后终止，不宣称它完成整套 matrix。三档共 90 次 raw probe，
**78 次失败**保留；其余 12 次返回也不代表原 API 具备安全资格。

首次 PACK32 width=0、N=15 的失败报告、探针、驱动、source lock 与构建文件
保留在 `build/source-audits/littleintpacker-initial-zero-width-failure/`。

## Build-only 修复与已执行验证

`patches/0001-zero-width-and-word-access.patch` 的 SHA-256 为
`8f44ce97d1a63eb2de0c151aa462070c09f2884da5ebde1e1a887093a0d5beb6`。
`PATCH_LOCK.json` 记录原/改文件 hash、生成器 hash 和修改数量。补丁只在
`build/source-audits/littleintpacker-patched/generated/` 应用：修复四个
zero-width memset，以 memcpy 读写 packed words，并去掉 pointer-to-pointer
type punning，保留原 kernel、selector、stride 和位布局。vendor 保持原样。

release、debug、ASan+UBSan 实际执行完整原 unit，五种 API、widths 0–32、
lengths 0–512、每 width 100 trials 均保留，无过滤。独立线性 little-endian
bit oracle 验证实际 serialized prefix；只保留精确序列化 bytes，清零内部
readable padding 后再解码。每档 **18,975 cases**、三档 **56,925 cases**
全部通过；另有每档五种 odd-width multi-block probes，共 **15** 次通过。
使用 `ASAN_OPTIONS=detect_leaks=0`，不宣称 LeakSanitizer 通过。

- `build/source-audits/littleintpacker_source_tests.json`：原执行和失败证据。
- `build/source-audits/littleintpacker_patched_tests.json`：实际补丁应用、
  三档构建、完整 unit、独立 matrix、命令与 compiler `-MD` 闭包。
- `build/source-audits/littleintpacker_source_current_audit.json`：独立审计
  PASS，仅资格化原来源和修复后 kernels；重新实际应用补丁核对生成文件，
  核对源码/object/executable hash、编译选项、compiler 闭包、原失败与
  sanitizer executable symbols。
- `tests/unit/test_littleintpacker_source_evidence.py`：30 项验证，包括
  同步篡改 raw/nested 日志、重算依赖报告 hash、重算非法生成文件 hash、
  以 release 替换 sanitizer 二进制等情形仍无法通过审计。

## 有界 C ABI 和实际执行证据

`native/tscb_littleintpacker.cpp` 调用修复后的原函数，保留五种 API；
`build_native.py` 按 translation unit 独立 ISA flags 生成三档 shared library，
补丁实际应用在每档 `build/adapters/littleintpacker/<profile>/generated/`。
vendor 和上一阶段生成文件均保持原样；发布库为 `libtscb_littleintpacker.so`。

输入为连续 little-endian uint32、N=0–16,777,216，外部 alignment=1、无需
padding。规范化配置为 `{"bit_width":1,"codec":"PACK32","isa":"SCALAR"}`，
bit_width 允许 0–32 或 `"AUTO"`。AUTO 对完整对象取最小位宽，使用原 scalar
`bits` helper；位宽选择与扫描计入 wrapper 工作，不计作原 pack/unpack 调用。
固定宽度遇到超出该宽度的合法 uint32 值，返回 UNSUPPORTED，零值不被拒绝。
BMI2 配置要求 `AVX2_BMI2`，HORIZONTAL 要求 `SSE4_1` 并实际检查 SSSE3+
SSE4.1；无自动 fallback。每个对象调用原 encode/decode 公共 API 各一次。

LIP1 对象包含 32-byte little-endian header、精确 payload 与 8-byte FNV64。
magic=`TSCBLIP1`；header 记录 count、API kind、actual width、FIXED/AUTO mode
及 payload byte count。总长度为 `40 + ceil(N * width / 8)`，精确 bound 支持
合法零宽度输入；decoder 使用对象 metadata，不依赖外部宽度配置。预验证
长度、checksum、kind、count、width、尾部 unused bits；AUTO 还在原 decoder
执行后验证最小位宽。完整账本为 container 64、metadata 192、checksum 64
bits，加实际 value bits 和最后一字节 padding；内部 staging 不计作码流。

encode 内部 input 增加 32 values、packed output 增加 136 bytes；decode
内部 packed input 增加 528 bytes、decoded output 增加 128 values。
HORIZONTAL 的内部输出检查 16-byte alignment，再调用原 SIMD stores。
容量/descriptor/alias/源数据域失败在 native 调用前拒绝；其他失败也不发布
调用方 output 或 used 字段，并允许重试。一次 compress、零字节 finalize，
reset 清理状态；不声明 streaming/query。

release/debug/ASan+UBSan 的实际 shared library 均完成独立线性 bit oracle
矩阵：每档 **94,875**，合计 **284,625** 场景，包含五种 API、全部宽度、
23 种长度、五种 pattern、四种外部偏移以及 AUTO。另完成 **152,580** 次
所有截断/非法结构/checksum/非零 tail/非最小 AUTO 拒绝，**4,455** 次精确
容量、只读 input 与 guard-page 往返。所有失败核对 output 和 descriptor
不变，合法场景核对 header、原 payload、计费、timer toggle 和累计。

三档 fault executables 链接对应发布库的全部七个实际 objects，以 linker
wrap 注入 allocation、原 API 异常/非法 output 与 clock failure/backward/
overflow，合计 **510** 项检查。原 handle 创建时计时关闭，Python session
将默认启用；setter 清零、reset 保留开关并清零、查询不清零。wrapper 提前
拒绝不计 native 时间，执行后 source failure 计入；C++ 异常/坏时钟使计时
不可用，不发布伪零值。计时关闭不改变 wire；零字节 finalize 不追加原 API
interval。仍使用 `detect_leaks=0`，不扩大 LeakSanitizer 资格。

- `build/source-audits/littleintpacker_native_tests.json`：全部三档真实构建、
  shared/fault 执行、原始命令、源快照、compiler 闭包和同 objects 证据。
- `build/source-audits/littleintpacker_native_current_audit.json`：独立审计
  PASS，核对固定补丁、完整构建/测试 profile、实际 objects/library/export、
  编译/链接选项、raw/nested 日志、source snapshot、sanitizer symbols。
- `tests/unit/test_littleintpacker_native_evidence.py`：19 项验证，拒绝缺失
  profile/fault/raw command/compiler dependency、替换 shipped objects、伪造
  场景数或 fault output、删去 AVX2/sanitizer/runtime 依赖、源码/object/library
  变更，以及由 native 证据直接声明 SDK 或完整条目通过。连同 source 与
  worklist 回归，本阶段 **54 passed**，记录为
  `build/source-audits/littleintpacker-source-native-worklist-tests.xml`。

## Python SDK 和注册

`src/tscompbench/adapters/littleintpacker.py` 保留五个原 API 实例，支持
VALUE/UTS uint32、FIXED 0–32 和 AUTO。AUTO 的 SDK 参数使用规范化
`bit_width=32` 占位，传入 native 时显式使用 `"AUTO"`；不隐含 Delta/ZigZag。
逻辑 strided/reversed/misaligned 数组通过显式 gather 保持顺序。新 decoder
从完整对象恢复参数，不依赖其创建时的位宽配置。

SDK 对象为 `TSCBLPC1`、44-byte prefix、规范 JSON descriptor、SHA-256 和
原 LIP1 frame，完整账本包括全部 descriptor/header/checksum 和 tail bits。
计时默认开启，显式关闭到达实际 native library，并保持相同 wire。

实际执行 `tests/adapters/test_littleintpacker.py`：**499 passed、零 skip**。
验证全部宽度与 uint32 tails、布局、原 wire oracle、账本、容量/数据域/alias
原子拒绝、lifecycle/fresh decoder、真实 timer toggle、全部截断/非法对象、
参数/dtype/routing 拒绝、AVX2+BMI2（不额外要求 LZCNT）和
SSSE3+SSE4.1 同时满足的解析合同。`execution.required_cpu_flags` 为显式
额外特性要求，缺少任一特性时在 planning 阶段拒绝，不调用 native 或 fallback。
`tools/audit_littleintpacker_sdk.py` 独立核对原始 JUnit、完整 testcase universe、
执行命令和 **82 个实际导入的项目 Python 文件**，当前审计 PASS。
当前证据保存在 `build/source-audits/littleintpacker-sdk-20261007-2/`，包含实际
导入源字节、driver、JUnit和命令。原81-file执行目录和报告保留为历史证据。

`tools/onboard_littleintpacker.py` 已实际运行，登记 source artifact 和
`littleintpacker-{pack32,turbo,sc,bmi2,horizontal}-u32` 五份 manifest/onboarding
卡片，共用经验证的发布库；完整 registry schema/ID 校验通过。
补齐 ISA 合同前，注册后的五条 factory 路径已实际创建 session、执行 AUTO uint32 往返，
核对独立 wire oracle、完整账本、immutable/canary/determinism；每条路径
验证 415 个构建/运行/Python 依赖文件，记录为
`build/source-audits/littleintpacker_registered_factory_smoke.json`。
旧 495-case SDK 与该 factory smoke 的完整证据、102 个文件快照保留于
`build/source-audits/pre-horizontal-required-cpu-flags/`；当前 SDK 为重新实际
执行的 499-case 版本，未重算旧报告冒充新验证。

## 五层资格验证

`tools/qualify_littleintpacker_benchmark.py --phase qualification` 已实际执行
五个 API × supported/unsupported/source-domain rejection，合计 **15 个 run set、
90 条记录**。supported 覆盖 AUTO/FIXED32 × 原生计时开启/关闭，20 条 PASS；
不支持 dtype/topology/track 产生 40 条 UNSUPPORTED；FIXED0/1/31 位宽不足
产生 30 条原子拒绝，保留完整 boundary/preflight 原因，没有 cast 或 fallback。

`tools/audit_littleintpacker_run.py --phase qualification` 独立审计 PASS：
核对 Layer1 canonical bytes、完整任务/记录/产物集合、源码/补丁/构建/SDK hash、
配置与 ISA、线性逐 bit wire oracle、完整 descriptor/LIP1 计费、真实原 API 与
staging 成本、timer toggle、不同位宽配置 fresh decoder、raw/Coverage/report。
90 条资格记录 Eligibility 均为 false，没有进入正式排名。

## 历史正式重复与独立统计

以下是20261007-1在当时Python源码下的实际结果；公共factory和Simple SDK变化
以后，不能把这些结果直接标为当前资格。变更前120个源码/registry/report文件和
独立审计结果已保存在 `build/source-audits/littleintpacker-before-rle-sdk-20261007-1/`。

五个 API × AUTO/FIXED32 × 原生计时开启/关闭，CPU0 串行、单线程单进程，
每个配置 **20 次正式重复**，合计 **400 条原始记录**。
每条记录编码和解码 selected 时长均至少一秒；每个任务预热次数至少三次，
累计至少 0.5 秒。每次 inner iteration 是独立 codec object，计时和源码
staging 成本按既定 CORE/PIPELINE 与 CODEC_API_ONLY_V1 边界分别记录。

**385 条符合统计资格**；另 15 条保留为 `RESOURCE_PRESSURE`，原因均为
`SWAP_OBSERVED_DURING_FORMAL_REPETITION`，没有删掉、重标 PASS 或混入统计。
五个 API 分别为 PACK32 80/80、TURBO 76/80、SC 79/80、BMI2 74/80、
HORIZONTAL 76/80；每配置实际 accepted 数为 16–20，均满足至少十次的门禁。

`tools/audit_littleintpacker_run.py --phase formal` 独立审计 **PASS**。
核对 100 个实际导入的项目 Python 文件、全部 run set/任务/20 次 repetitions/
压缩文件、CPU0/ISA/warmup/时长、资格与正式 wire 相同、真实 API/staging
及完整计费。核对 raw projection 与 Coverage，独立重算 **20 份 summary**
的 mean/median/P25/P75/SD/CV、1000 次 bootstrap CI95 和总 bytes/总 time
的 micro throughput；关闭原生计时的结果与汇总保持 null，没有伪零值。

证据位于 `build/source-audits/littleintpacker_{qualification,formal}_five_layer_runs.json`、
对应 `*_current_audit.json` 和 `runs/littleintpacker-*-{qualification,formal-20}-20261007-1/`。
新增合同、SDK/factory 证据拒绝、独立 wire/ledger/诊断拒绝与 worklist 回归
合计 **88 项通过**。FIXED32/AUTO 的合成 UTS 资格不扩大到其他宽度的正式
数据分布、其他数据集、timestamp pipeline 或清单完整条目。

## 后续接入条件

当前重新资格验证使用20261007-2：SDK499项、五层90条记录独立审计PASS。
五份registry/onboarding更新当前SDK闭包，SourceArtifactID保持不变，AlgorithmID
随Python闭包变更重算，前后registry字节和身份映射均保存。
当前正式重测为CPU0串行、20次/配置，400次实际执行完成，独立统计审计PASS。
382次有效，18次swap排除且全部保留；PACK32/TURBO/SC/BMI2/HORIZONTAL
分别75/75/78/75/79次有效，每配置16–20次，满足至少10次门禁。
101个实际导入项目Python文件已逐字节冻结；全部20份summary由独立审计
重新计算统计与bootstrap区间，原生计时关闭的值和统计保持null。
证据另存 `build/source-audits/littleintpacker-{qualification,formal}-20261007-2/` 和
`runs/littleintpacker-*-{qualification,formal-20}-20261007-2/`，当前审计为
`build/source-audits/littleintpacker_{qualification,formal}_current_audit.json`。
没有覆盖或重hash原执行报告；完整条目仍未完成，其他数据集/数据域仍待验证。

后续继续扩大实际数据集/位宽分布与明确 timestamp pipelines 的验证范围。
BMI2 路径要求 AVX2+BMI2，不额外假定 LZCNT。
原 unit 或修复后 kernel PASS 不替代这些门禁；完整条目标志保持 false。
