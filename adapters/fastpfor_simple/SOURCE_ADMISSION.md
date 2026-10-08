# Simple-9 / Simple-16 源码准入初审（2026-10-07）

依据工程计划 7.2、7.6、8.3、11.5、13.3、20.3；对应“全量审计”第 145、
146 条。当前完成原始源码冻结、三档直接 API 探针、有界 C ABI 及独立证据
审计。原 API 的不安全调用证据保留；完整原上游自测、Python SDK 和注册
已完成，持久化五层资格运行与正式重复的独立审计均通过。资格仅限合成
uint28 VALUE/UTS；其他数据集和输入域仍 pending，不能标记完整条目已接入。

## 来源与 Benchmark 比对

工作簿源为 `fast-pack/FastPFOR@2457e1ed1af35bbf7f4c509c863fa9797e637cb3`，
Apache-2.0。冻结 13 个原样文件：七个实现/依赖头文件、Simple16 上游测试、
上游 test driver/helper、LICENSE/AUTHORS/README。每文件与固定 Git tree
逐 byte 比较；无源码补丁、dirty 或 submodule。共享原源码目录保持只读。

先审查本地 Sprintz-lzbench `580c4f085381f31b1ad669525ed04e63cbc385f3` 的
factory、codec 头和 `_lzbench/compressors.cpp`。其 factory 有 Simple9/16，
但 lzbench 公共注册入口只暴露 Simple8b 等其他算法；通用 FastPFOR wrapper
会把非四 byte 原始长度向上补齐，并直接调用不检查 capacity 的原 API。
不能复制该 wrapper 后宣称满足 Benchmark 的安全和输入合同。

因此使用工作簿指定 FastPFOR 的公开 `encodeArray/decodeArray`，将该仓库
自身的 `src/inmemorybenchmark.cpp`、`src/unit.cpp` 和 factory/CMake 作为
参考。参考文件 commit/hash 已锁定，历史 benchmark 的最快值不进入统计。
现代 FastPFOR 与 lzbench vendored 版本有各自身份，不做名称匹配替代。

上游 Simple16 gtest 使用本地 NeaTS commit
`2d804ff492e45222e841dc1a50904476fa64f4a0` 内原样 vendored Google Test，
只复制所需 include/src/LICENSE，共 38 个文件、BSD-3-Clause。此依赖仅用于
源码测试，不是压缩算法的依赖；未进行 CMake 的网络下载或运行自动 ISA 探测。

## 数据与码流合同

- 原始输入是 uint32 存储的 **28 位无符号整数**，允许 `[0, 2^28-1]`；
  不接受完整 uint32 或原始 int64 Timestamp。不得静默截断、量化或套用
  32-bit limb pipeline。任何 Delta/ZigZag/分 limb 都需单独 P2 身份和阶段合同。
- `MarkLength=true` 在第一个 uint32 word 存逻辑 count，后续 word 由顶部
  四位 selector 与 28 位 payload 组成。false 版本从调用方 `nvalue` 获取
  count，必须明确纳入 descriptor/包装和计费。
- Simple9 普通格式有九个 selector；`hacked=true` 另有 selector9 的 28 个
  零值路径，属于不同格式。Simple16 有 16 个 selector，包含混合 bit widths。
- encode/decode 长度单位均为 uint32 **words**；真实输出 bytes 必须由
  返回 word count 精确换算。Simple16 `fakeencodeArray` 只算 payload words，
  不含 MarkLength 的 count word，不能直接作为整个 stream 的 bound/FinalBits。
- 解码 `len=0` 是未知输入长度模式，仍须有真实可读的完整码流与输出 count；
  不能用它绕过包装的完整长度、selector 和输出校验。
- 源 API 没有 reset/finalize 状态，但 Benchmark 对象仍须显式 lifecycle。
  Count、selector、tail padding、descriptor/container 都进入物理账本；不存在
  native incremental streaming、query 或 random-access 的资格声明。

## 当前验证与已确认限制

在 CPU2 out-of-tree 构建 release、debug、ASan+UBSan 三档，固定 x86-64、
禁用自动向量化，断言开启。六种原始实例（Simple9、Simple9hacked、Simple16
各 marked/unmarked）每档各 5,075 场景，总计 **91,350**。覆盖 29 个整数
width、25 个 N、七种内容模式；独立 greedy selector oracle 逐 word 验证
原编码器输出，所有合法 selector 有实际覆盖。原解码器分别验证已知/未知
输入长度、返回 consumed pointer、完整逻辑值及输入不变。

此有效码流矩阵为原 hacked 输入显式提供 28 个可读零值、为原 decoder 提供
28 个输出 headroom；它不是 alignment=1、exact-capacity 的 ABI 资格。
另外以独立进程、只读输入和 protected page 实测以下限制：

| 原始调用 | 实测结果 | 有界封装要求 |
| --- | --- | --- |
| decode 短尾、exact N 输出 | 最多扩写到完整 selector，越界失败 | 内部 scratch/headroom，精确逻辑 count 后再发布 |
| decode 截断输入 | 原 decoder 不在读取前检查 len，越界失败 | 全码流结构、count、consumption 预验证 |
| encode 短输出 | 原 encoder 忽略传入容量，越界失败 | checked bound，完整 scratch encode 后原子发布 |
| Simple9 非法 selector | null unpacker 调用失败 | 按声明格式验证 selector，普通/hacked 不混用 |
| hacked 全零短输入 | tail 调用 full 28 检查，越界读取 | 显式内部 readable padding 或独立 build-only 修补 |
| 29 位数输入 | 抛异常；marked 已写 count word | 先验范围验证，失败不改变调用方输出 |

三档共 **72** 个 guard-page 不安全调用均确认；ASan/UBSan 档有实际错误栈，
不会把原失败改标 PASS。另有 18 个范围拒绝诊断。原 Simple16
`DecodesWithUnknownLength` 上游 gtest 三档全部通过，无 disabled/skipped。
完整原上游 `src/unit.cpp` 已另行构建和执行，见后续专项证据；不能将
Simple16 gtest 的三档结果套用为完整 factory 的三档结果。

第一轮测试把 fake payload count 错当完整 count，失败快照保留在
`build/source-audits/fastpfor-simple-initial/`，已修正测试假设。LeakSanitizer
在当前 ptrace 环境失败，完整记录保留在 `fastpfor-simple-lsan-initial/`。
后续 ASan/UBSan 使用 `detect_leaks=0`；**未声明泄漏检测通过**。

证据入口：

- `SOURCE_LOCK.json`：51 个原样算法/测试依赖文件与 benchmark references。
- `build/source-audits/fastpfor_simple_source_tests.json`：真实命令、stdout/stderr、
  12 个 object 的 compiler `-MD` 依赖、原始错误、上游 JUnit 和二进制 hash。
- `build/source-audits/fastpfor_simple_source_current_audit.json`：独立审计。检查
  当前固定 Git bytes、完整命令/探针集合、全部 selector、实际编译依赖与
  二进制 sanitizer symbols，禁止凭探针 PASS 声明有界或五层资格。

## 有界 C ABI 与当前资格

`native/tscb_fastpfor_simple.cpp` 调用冻结的原编码器/解码器，vendor 无补丁。
输入和输出 alignment=1；内部负责可读尾部 padding 和 decoder headroom。
编码前检查完整输入域，在 scratch 完成编码后检查精确容量再发布；解码前
验证完整 grammar、selector、count、尾部零 padding 和 consumption。所有失败
保持调用方输出与 descriptor 不变，重叠 buffer 拒绝，checked count 上限为
16,777,216。支持一次 compress、零字节 finalize 和 reset，不声明 streaming/query。

SPF1 包装使用 little-endian：32 byte 头记录 count、codec kind、marked 和
payload word count，保留原 marked count word，后附 8 byte FNV64。总长度为
`40 + 4 * word_count`。value、selector/count metadata、padding、container
和 checksum 进入完整物理账本；内部 staging/padding 不冒充序列化码流。

release、debug、ASan+UBSan 的实际 shared library 共通过 **91,350** 个
有界场景，覆盖六种实例、全部 selector、四种输入偏移、精确容量与短容量、
guard page、只读输入、canary、错误 descriptor、重算 checksum 后的非法
结构及所有截断。独立 greedy oracle 验证 wire，不用 shim scanner 自证。

三档故障可执行文件链接各自实际发布的 `shim.o`，共 **198** 项分配和
时钟注入检查通过：异常不跨 ABI、失败输出不变且可重试；默认计时、关闭、
累计、重复查询、finalize/reset、时钟失败/倒退/溢出均验证。计时开关不改变
wire。仍使用 `detect_leaks=0`，不扩大为 LeakSanitizer 通过。

- `build/source-audits/fastpfor_simple_native_tests.json`：三档构建、shared
  tests、同对象故障测试、实际命令/编译依赖和文件 hash。
- `build/source-audits/fastpfor_simple_native_current_audit.json`：独立审计
  **PASS**，范围仅为 uint28 有界 C ABI。核对源证据、真实 object/library、
  compiler `-MD` 闭包、编译/链接选项、sanitizer symbols 和完整执行结果。
- `tests/unit/test_fastpfor_simple_native_evidence.py`：**22 passed**。验证缺失
  profile/fault/raw 命令、删减 compiler 闭包、替换 shipped object、伪造场景
  数与输出、移除 sanitizer，以及源码/object/library 变更均不能通过审计；
  禁止由 native 证据直接声明 SDK 或完整条目已完成。

## 完整上游自测、Python SDK 与注册

`UPSTREAM_UNIT_LOCK.json` 单独冻结完整上游 unit target 的 55 个文件，位于
`third_party/fastpfor_upstream_unit/`。原 `src/unit.cpp`、factory 与全部 codec
实现均无裁剪/补丁，实际编译依赖与固定 Git bytes 一致。release（`-O3`、
`-UNDEBUG`、固定 SSE4.2）执行全部 factory：完整 0–28 widths、原长/短输入
循环及 2⁵/2¹⁰/2¹⁵/2²⁰/2²⁵ Zipf 数组通过，原 terminal success 保留。
完整 factory 的 debug/sanitizer 未执行；Simple 的安全资格仍来自单独三档
原 API probes 和有界 ABI，不能给其他 factory codec 套用资格。

`src/tscompbench/adapters/fastpfor_simple.py` 使用实际 shared library，独立
decoder 读取 SPC1/SPF1 descriptor。**322** 个直接 SDK 测试通过，独立
Python selector oracle 比较全部格式的原 payload 和账本；保存实际 **83**
个 Python 文件的导入闭包。完整上游和 SDK 独立审计均 PASS：

- `build/source-audits/fastpfor_simple_upstream_tests.json` 与
  `fastpfor_simple_upstream_current_audit.json`。
- `build/source-audits/fastpfor_simple_sdk_tests.json` 与
  `fastpfor_simple_sdk_current_audit.json`。

已注册 `simple9-u28`、`simple9hacked-u28`、`simple16-u28` 三个 P0 身份，
原 marked/unmarked 均保留；标记参数改变 ConfigID，标准/hacked 的格式身份
不合并。source artifact、onboarding、factory 和构建 CLI 已接通；shared
library 的实际名字与三个 codec key 分别核验。factory 校验实际源码/object/
library、编译命令和 Python 依赖闭包，过期构建不能直接执行。

集成 **19** 个测试通过，其中三类运行实际经过五层：合法 uint28、dtype/
track 不支持、同 uint32 存储但超出 28 位输入域。每类保留 marked/timer 的
全部配置、canonical 数据、diagnostic/raw、summary/Coverage；qualification
记录不进入正式排名。原生实际计时显式关闭，不仅隐藏 Python 观测。

## 持久化五层运行与驱动回归

修正后的驱动执行九个 `*-qualification-20261007-3` 类 run sets：三个
codec 各保留合法、dtype/track 不支持、超出 uint28 域三类运行，总计
**12 PASS + 36 UNSUPPORTED**。独立审计实际 canonical、原 payload greedy
selector oracle、descriptor、完整计费、fresh decoder、timer 不改变 wire、
原 API/staging telemetry，以及 raw/summary/Coverage；qualification 的
Eligibility 全为 false，不进入正式排名。

- `build/source-audits/fastpfor_simple_qualification_five_layer_runs.json`：实际
  Python 执行闭包、配置、身份、全部五层文件 hash。
- `build/source-audits/fastpfor_simple_qualification_current_audit.json`：独立
  **PASS**；范围仅为合成 uint28 VALUE/UTS。
- `tests/unit/test_fastpfor_simple_run_audit.py`：**16 passed**，确认重算 checksum
  的伪造 payload、转移 value/padding 计费、伪造计时/路径/Eligibility、给拒绝
  记录添加正式资格都不能通过。
- 新增两项实际 Runner 回归：四个任务各三次重复产生 12 条记录，能力拒绝
  各只产生一条 diagnostic；驱动核对 `sum(len(result.records))`，不能把
  TaskResult 数量误当重复数。证据为
  `build/source-audits/fastpfor-simple-driver-repetitions-tests.xml`。

首次正式启动的 CPU2 亲和限制与正式 CPU0 配置不一致，12 条
`CPU_AFFINITY_UNAVAILABLE` 诊断原样保留。第二次 Simple9 已执行 80 条记录，
但旧驱动错误的汇总数量检查抛异常；其失败快照、旧驱动 source 与实际记录
均保留。该 run 的内容和统计另行审计通过（76 eligible、4 resource pressure），
但不将失败 driver 改标为 PASS。最终使用修正后的驱动与新 run IDs 完成正式执行。

## 正式重复与独立统计资格

`simple9-u28`、`simple9hacked-u28`、`simple16-u28` 各执行
`*-formal-20-20261007-3`：每个 marked/unmarked × native timer 开/关配置
20 次 attempt，CPU0 串行；每配置预热至少三次且累计 0.5 秒，每次 selected
encode/decode 各至少一秒。实际 **240** 条记录全部保存，其中 **232 eligible**
（Simple9 75、Simple9hacked 79、Simple16 78），八条 resource pressure 原样
保留并排除于统计；每个配置仍至少十条 eligible。

`build/source-audits/fastpfor_simple_formal_current_audit.json` 独立 **PASS**。
审计实际运行闭包、全部产物 hash、逐重复正确性/计费/计时、timer wire 一致、
formal/qualification wire 一致、raw CSV/Coverage 完整性，并独立重算各 CORE、
PIPELINE、native 的均值、中位数、p25/p75、标准差/CV、bootstrap CI 与按总
bytes/总时间计算的 micro throughput。四组 summary/codec 均核对，不调用
生产统计函数自证。实际执行证据为
`build/source-audits/fastpfor_simple_formal_five_layer_runs.json`。

## 下一步门禁

继续其他数据集与声明输入域的资格评估。本次合成 uint28 corpus 不代表真实
数据集或其他输入域资格。完整工作清单仍
保留 221 条逻辑条目、115 个原生候选，两条目的 full qualification 均为 false。

```bash
python tools/freeze_fastpfor_simple_source.py
taskset -c 2 python tools/qualify_fastpfor_simple_source.py
taskset -c 2 python tools/audit_fastpfor_simple_source.py
taskset -c 2 python adapters/fastpfor_simple/tests/run_native_tests.py
taskset -c 2 python tools/audit_fastpfor_simple_native.py
taskset -c 2 python tools/qualify_fastpfor_simple_upstream.py
taskset -c 2 python tools/audit_fastpfor_simple_upstream.py
PYTHONPATH=src taskset -c 2 python tools/qualify_fastpfor_simple_sdk.py
taskset -c 2 python tools/audit_fastpfor_simple_sdk.py
PYTHONPATH=src taskset -c 2 python tools/onboard_fastpfor_simple.py
PYTHONPATH=src taskset -c 2 python tools/qualify_fastpfor_simple_benchmark.py --phase qualification --suffix UNIQUE_RUN_SUFFIX
PYTHONPATH=src taskset -c 2 python tools/audit_fastpfor_simple_run.py --phase qualification
PYTHONPATH=src taskset -c 0 python tools/qualify_fastpfor_simple_benchmark.py --phase formal --suffix UNIQUE_RUN_SUFFIX
PYTHONPATH=src taskset -c 2 python tools/audit_fastpfor_simple_run.py --phase formal
```
