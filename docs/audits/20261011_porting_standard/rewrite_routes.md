# 33 个活动入口：移植／重写路线与证据范围（2026-10-11）

本表针对当前 `registry/algorithm_scope.json` 的 33 个活动入口：11 个核心重写、22 个原生路线。3 个 legacy、4 个 harness oracle 和 LZ77 alias 不计入本表。路线名称按移植标准 §2.6 用于文档分类，没有新增 registry enum。完整字段与逐入口规则映射见 [rewrite_routes.json](rewrite_routes.json)。

用户授权的是完整阅读、审查、必要修正和验证；Markdown 中的操作命令、默认端到端授权与清理说明属于验收依据和被审查内容，不作为额外用户指令。本轮不新增算法、不恢复退出项、不改写历史证据。

## 结论与门禁

不能给 33 个入口统一签署“完整重写条件全部满足”。`SOURCE_REWRITE` 按 G0–G6/CAP-GATE，`NATIVE_REUSE/NATIVE_PORT` 按 N0–N5；薄 binding 不等于核心翻译。已取得的源对照、当前安全/API/构建和 Benchmark 资格分别表达。完整独立发布与上游 FULL_PARITY 本轮没有重新授予；原有资格仍按冻结身份、范围及当时证据读取。

`UNKNOWN` 表示本轮未对该入口的全部独立门禁签完整结论，不把限定 profile 的成功视为原作全部能力已通过，也不是声明测试执行失败。实际当前 vendor/binding/build/runtime admission 由[本轮主审计](README.md)登记。旧 FORMAL 绑定旧闭包；当前修正后的正式性能需要新 RunSet，不能重签旧测量。

- G 族适用 `PORT-004/005`、`CAP-001/002`、`SRC-001`、`TOOL-001`、`EVID-001/002`、`XFER-001`；缺失 REQUIRED_PARITY 或未验证源/平台阻断完整独立 `REWRITE_DONE`。仅有限 CPU 模型 profile 不构成 waiver。
- N 族适用 `NATIVE-001…007`，特别是 patch 重放、所有权/容量/状态、真实执行 ISA、源与包装格式比较对象，以及 N0–N5 限定范围交接。原生路线不机械重造 scalar。
- 数据/对象/模型/执行能力依 `GEN-001…005`、总计划 §8/13/14/16 和能力矩阵验收；矩阵“已接/已验”不能反向替原生门禁签 PASS。

## 本次 fresh 源对照

最终记录：[fresh_source_summary.json](fresh_source_summary.json)、[精确 Java 环境恢复](java_oracle_restoration.json)、[CLI→当前 vendor 逐 SHA 关联](lossless_cli_vendor_link.json)。实际全部命令、源/driver/CLI/log/hash 保存在 `build/port-standard-v30-20261011/source-oracles-final/report.json` 和 `lzss-source-oracle-final/report.json`；旧报告保留。原参考源码与旧报告共 21,244 个文件 hash 前后无变化。

- 六个 Java 入口 613 个有效无损 raw equality＋双向 cross decode 通过，SElf* 另有 6 个 network 案例通过。Elf+ 2 个 fresh NaN END 案例单列；8 个原 source TIMEOUT/ERROR 的预期来自存档，本次只执行 bounded native rejection，不能称 fresh 原 Java 失败复现。Elf*/SElf* 保留缺失 temp 声明的无关 helper 构建 overlay，选定算法路径未改变。
- 上述 fresh standalone CLI 实际编译的 canonical cpp/header、仓库独立快照、当前 vendor 与 FROZEN_APIS 对应 SHA 全等。该关联证明核心字节相同；RWF1、descriptor、多列块状态、FFI 和 Benchmark binding 仍由独立入口资格验证。
- LZSS 原 Rust implementation 在隔离项目离线重建，void1.0.2 原 crate SHA 核验；282 个 EI10/EJ4/C32 raw equality＋双向 cross decode 通过。Rust 不成为生产 C++ 运行依赖；不授全部 Rust API。
- ABBA 当前新 CLI：74 阶段组合差分＋64 alternate capability。fABBA 当前新 CLI：73 差分＋32 partition；73 中 26 调未改原 AGG、46 采用声明稳定化、1 仅 decode。二者通过所声明范围，不能授未改全 Python 调用图 FULL_PARITY。

DeepZip/DZip 的具体缺项见 [learned_oracle_availability.json](learned_oracle_availability.json)。未恢复旧 TF runtime/模型轨迹是 `NOT_RUN`，不是源执行 `FAIL`、不是 waiver。DeepZip 原 trained xor20 checkpoint authority 仍在且 SHA 匹配，仅没有部署于当前 4-symbol CPU profile；完整原作 CUDA、HDF5、训练能力未由本轮 CPU 资格覆盖。

## 逐入口路线

表中的输入/ISA/线程完整声明以 JSON 的 `declared_input/declared_execution` 为准；source、adapter、card 身份更新由主审计索引绑定，避免把迁移中的身份写成最终当前证明。所有“另验”的接入结论均来自主审计的当前闭包证据。

| 入口 | 路线／适用门禁 | ObjectLevel | 实际核心及限定范围 | 本次／已有源证据 | 完整门禁边界 |
| --- | --- | --- | --- | --- | --- |
| abba | SOURCE_REWRITE；G0–G6＋CAP | P2_PIPELINE | Python ABBA 流水线翻译；原生 CKmeans 是复用组件，不能把整个 ABBA 说成仅包装 kernel。 f64 有限序列；KMEANS/INCREMENTAL、norm/scl/max_len 以参数白名单为准；多列独立编码。 | 74 阶段组合差分＋64 alternate capability；修正 reconstructed length 转换/容量 UB。 | 阶段 oracle 是来源 Python 分段/重建＋原 CKmeans 组合，未重新授予完整未改 Python 调用图、全部数据集/required 优化 G0–G6。 |
| alp | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 ALP/FastLanes C++；build-copy 安全修补＋强制 decimal ALP。 f32/f64；显式拒绝源不支持输入；完整自有 ALP frame。 | authority 15/15 文件一致；build copy 有3个声明安全 patch；当前 API/构建闭包另验。 | 强制 decimal 路径不等于上游自适应 ALP/ALP-RD 选择；source-reject RAW composition 是独立对象。 |
| alp-rd | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 ALP-RD/FastLanes C++；build-copy 安全修补＋强制 RD。 f32/f64；完整自有 ALP-RD frame。 | 与 ALP 共用冻结来源；实际强制 RD 路径、API/构建闭包另验。 | 不等于全部上游 adaptive/ISA/参数集合。 |
| brotli-stream | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 直接调用冻结 Brotli C stream API；Python 只布局/FFI/容器。 完整 Brotli stream；声明字节视图、stream 生命周期。 | authority 110/110 文件一致；当前流式 API、typed container、独立恢复另验。 | 不把 lzbench one-shot 调用图、全部字典/参数/平台视为已验。 |
| chimp | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java Chimp/Chimp32 → 当前冻结 C++ canonical core。 f32/f64；N=1 raw profile；Bench frame、descriptor、多列绑定另验。 | 112 raw equality＋双向 cross decode；CLI/core/header SHA 与 vendor/FROZEN_APIS 一致。 | raw 对照不授予不同的 RWF1/FFI/binding 或上游全部能力 G6。 |
| chimp128 | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java ChimpN/ChimpN32 → 当前冻结 C++ canonical core。 f32/f64；N=128 raw profile；共用 Chimp 包，保留独立入口身份。 | 112 raw equality＋双向 cross decode；CLI/core/header SHA 与 vendor/FROZEN_APIS 一致。 | 其它 N/上游调用方式未由该 profile 的112例验证。 |
| deepzip | SOURCE_REWRITE；G0–G6＋CAP | P2_PIPELINE | 原 Python/Keras 推理路径 → 原生 CPU 模型＋arith codec；17原构造器未训练 fixture。 uint8 alphabet 0..3；17 frozen portable model，完整 frame 含模型成本；本 Bench 禁 HDF5/CUDA。 | 当前 C++ 对17×3=51个存档 TF context 概率一致；17 model SHA匹配；当前 CPU API另验。 | TF-GPU1.8/Keras2.2.2/NumPy1.16.4 runtime 未恢复，nvidia-smi exit9；xor20 trained 二词表 checkpoint authority 尚存但未部署；无有效 waiver，required 全源/训练/CUDA 项不签 G0–G6/CAP/FULL_PARITY。 |
| deflate-zlib | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 zlib C stream；非单独 LZ77、非 Python zlib 编码。 RFC1950完整 zlib stream；声明字节视图和 stream 生命周期。 | authority 48/48 文件一致；native stream、typed container、独立恢复另验。 | 不是裸 DEFLATE/所有 strategy/dictionary/平台资格。 |
| dzip | SOURCE_REWRITE；G0–G6＋CAP | P2_PIPELINE | 原 Python/TF PRNN 流水线 → C++ TFCPU 模型/update；当前 initializer 为独立声明 native seeded 变体。 uint8；BOOTSTRAP/COMBINED；NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET；AVX wrapper＋runtime dispatch与3线程预算。 | 当前模型/frame/更新 CPU API另验；完整 frame 计入模型/alphabet；原 TF initializer 和 loaded trained PRNN 不等同。 | Python3.6.13/TFCPU1.14/Keras2.2.2/NumPy1.16.4 reference runtime、旧model/轨迹未恢复；不能用native seed自回环补充源 expected；完整 G0–G6/CAP 未重签。 |
| elf | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java Elf(VLDB) → 当前冻结 C++ canonical core。 f32/f64；源域拒绝保持；Bench frame独立。 | 109 raw equality＋双向 cross decode；CLI/core/header SHA 同 vendor。 | 有既有本地许可决定，仍按该来源/许可证范围消费；全G/CAP发布未重签。 |
| elf-plus | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java Elf+ → 当前冻结 C++；源缺陷边界显式拒绝。 f32/f64；82合法无损域＋NaN END sentinel；8个源失败域有界native拒绝。 | 82 raw/双向；2 fresh原Java NaN END；8 native rejection通过，源TIMEOUT/ERROR取自存档未重跑。 | 8案例不得算fresh原Java失败复现；END不算无损PASS；Bench RAW escape/composite不能反向扩大源域。 |
| elf-star | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java Elf* → 当前冻结 C++ canonical core。 f32/f64；one-shot声明profile。 | 109 raw equality＋双向；保留无关 helper 缺temp声明修补；core/header SHA同vendor。 | 不能称完全无patch原Java构建；所选算法路径未改，未覆盖完整上游CAP发布。 |
| fabba | SOURCE_REWRITE；G0–G6＋CAP | P2_PIPELINE | Python fABBA pipeline 翻译＋stable-norm2-scl1-v1 稳定化变体。 f64 有限输入；稳定化 norm/std/tie；partition profile按白名单。 | 73差分＋32 partition；73中26未改原AGG、46稳定化digitization、1仅decode；修正长度转换/容量UB。 | 不能把稳定化oracle说成未改原作全部路径；完整 G0–G6/CAP/发布未重签。 |
| fse | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 FSE C entropy core＋显式项目 RAW/RLE/9-byte mode/length frame。 uint8 symbol/完整frame；失败容量和模式独立验证。 | FSE/Huff0组16/16 authority文件一致；frame、RAW/RLE、typed container另验。 | RAW/RLE数据不是全payload运行FSE；P2 byte桥独立于原uint8熵核心。 |
| huff0 | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 HUF C entropy core＋显式项目 RAW/RLE/9-byte mode/length frame。 uint8 熵核心；当前 typed-byte 视图/完整frame 是 P1 standalone codec。 | FSE/Huff0共用authority组16/16；frame、RAW/RLE和当前API另验。 | 上游HUFF字典/全部API不自动开放；当前P1 wrapper资格不能反授原熵core全部能力。 |
| leats-lossless-i64 | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 C++ LeaTS 核心已修改 scalar/serialization/binary64 predictor；不是未改上游。 i8/i16/i32/i64归一到int64 per-column min shift；lossless frame/model/index/checksum、query/random-access；scalar。 | 3实际patch按序从锁commit重放；172/172 vendor一致；新source身份；当前构建/ABI另验。 | 完整源closure为修改后vendor；未重新执行全部未改源差分/ISA；旧正式资格不迁到新patch身份。 |
| lz4-frame | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 LZ4 C frame API复用；本轮修的是binding output/state生命周期。 完整 LZ4 frame流；typed byte视图与descriptor；非lzbench raw块。 | authority 11/11一致；新增output.used/EOF/reset/交叉解码回归；API模块属NATIVE_PORT。 | 来源raw block与当前frame比较对象不同；不授所有上游dictionary/参数/平台。 |
| lzss-dipperstein-c | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 Dipperstein C LZSS/bitfile＋tree sentinel安全patch。 固定LZSS token profile；空输入special case＋严格token validator。 | 12 vendored文件在指定Source_Code authority中无独立副本；当前构建/token/typed container另验。 | 不能称独立原始来源完全比对PASS；N1 authority缺口、全N族资格未重签。 |
| lzss-raw | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 alexkazik Rust LZSS dynamic行为 → 当前纯C++ core；Rust只作隔离oracle。 EI=10/EJ=4/C=32 raw bytes；完整Bench typed container另验。 | 原source与fixture逐SHA一致；void1.0.2 crate SHA核验；offline cargo oracle282 raw equality＋双向decode。 | 旧专项的生产Rust标签过时；当前C++仅固定profile，不代表整个Rust generic/dynamic/in-place API G/CAP完成。 |
| neats-lossless-i64 | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 C++ NeaTS scalar/平台API修改＋serialization；不是未改上游。 i8/i16/i32/i64归一到int64 per-column min shift；lossless完整frame/model/index/checksum、query/random-access；scalar。 | 3实际patch从锁commit重放；172/172一致；patch set/source身份已同步；当前build/ABI另验。 | 只改说明性patch为真实可重放patch，不把修改后核心说成原作未改或原SIMD完整parity。 |
| self-star | SOURCE_REWRITE；G0–G6＋CAP | P1_STANDALONE_CODEC | 原 Java SElf* → 当前冻结 C++ canonical core；network另验。 f32/f64；one-shot＋network选定profile；Bench frame另验。 | 89 raw/双向＋6额外network案例；helper temp overlay；core/header SHA同vendor。 | 6 network为standalone路径证据，不能授Bench未开放stream/network capability；全G/CAP未重签。 |
| serf-qt | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 C++ Serf Qt＋3安全patch＋显式RAW record。 f32/f64按column/block；nonfinite/unrepresentable/overflow RAW有成本。 | authority36/36一致；安全patch在build copy；当前API/frame分支另验。 | 含RAW对象不是每块纯upstream Qt；query/random-access未开放。 |
| serf-xor | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 C++ Serf XOR＋3安全patch＋显式RAW record。 f32/f64按column/block；非finite等RAW透明计费。 | 同Serf authority36/36；声明XOR branch/安全API另验。 | Qt与XOR不能混用来源PASS；RAW不得推广为上游源域。 |
| simdcomp-u32 | NATIVE_PORT；N0–N5 | P0_PRIMITIVE | 原 C SSE4.1/AVX2 pack/unpack P0＋4安全patch＋bounded ABI/SBP1。 u32；5个plain API/ISA组合；P0 primitive经frame包裹。 | authority27/27一致；source/AVX2/native/SDK专项audit PASS；factory保留独立门禁。 | 非FastPFOR SIMDBinaryPacking，不授delta/全部bitpack入口；P0不能冒称上游完整codec。 |
| snappy-raw | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 Snappy C++ raw API，Python仅FFI/容器。 完整Snappy raw流；scalar；外层typed descriptor归项目。 | authority10/10一致；raw/frame容量、typed保存对象另验。 | 不是Snappy framed格式，也没有dictionary/checksum能力。 |
| sprintz-delta | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 AVX2/BMI2/LZCNT Sprintz delta＋安全build copy/staging。 声明i8/u8/i16/u16按二维分组、signed转换与tail；bounded API完整项目frame。 | Sprintz17core＋LICENSE=18/18一致；真实ISA/维度/tail/安全路径另验。 | layout/group和尾块属于合同；不能称所有Sprintz域/平台完成。 |
| sprintz-delta-u8 | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 Sprintz u8 delta＋安全patch/有界staging。 声明uint8低维profile；AVX2/BMI2/LZCNT；tail。 | 同Sprintz18/18；u8低维独立参数/API测试。 | 低维u8 profile不能替代full8/16-bit能力。 |
| sprintz-fire | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 Sprintz FIRE＋安全patch/有界staging。 声明i8/u8/i16/u16 UTS/MTS、维度分组、signed转换与tail；AVX2/BMI2/LZCNT。 | 同Sprintz18/18；FIRE分支/真实ISA/容量另验。 | 不是FIRE+Huff0链，也非全部FIRE平台/参数资格。 |
| sprintz-fire-huff0 | NATIVE_PORT；N0–N5 | P2_PIPELINE | 原 Sprintz FIRE → 原 HUF 两组件显式P2串联。 完整组合frame与两个stage成本；声明i8/u8/i16/u16、signed转换/ISA/group/tail。 | Sprintz18/18＋FSE/HUF16/16来源；stage逆恢复、FinalBits/RAW分支另验。 | 组合PASS不能反向扩大Sprintz/HUF原生域；不得归成单kernel。 |
| sprintz-fire-u8 | NATIVE_PORT；N0–N5 | P1_STANDALONE_CODEC | 原 Sprintz u8 FIRE＋安全patch/有界staging。 声明uint8低维profile；AVX2/BMI2/LZCNT；tail。 | 同Sprintz18/18；u8 FIRE分支独立测试。 | 低维u8不代表full8/16-bit全部能力。 |
| xz-stream | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 liblzma C XZ/LZMA2 stream。 preset6，data check NONE但结构CRC存在；完整XZ stream。 | authority341/341一致；stream生命周期、typed保存对象独立恢复另验。 | 不是raw LZMA/所有XZ filter/字典/参数模式。 |
| zfp-accuracy-1d | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 ZFP serial C fixed-accuracy 1D＋显式异常RAW column/frame。 f32/f64逐列accuracy；NaN/Inf/negative-zero/subnormal RAW成本透明。 | authority94/94一致；误差/actual tolerance/full header与RAW独立验证。 | rate/precision/reversible/ND/CUDA未开放；RAW列不等于ZFP payload。 |
| zstd-frame | NATIVE_REUSE；N0–N5 | P1_STANDALONE_CODEC | 原 Zstd C单线程frame复用；本轮修binding output/state。 完整Zstd frame；禁asm/BMI2dispatch/legacy/dict/MT profile。 | authority64/64一致；output.used/EOF/reset/交叉decode回归；API模块属NATIVE_PORT。 | 不授全部dict/MT/平台；frame/API的scope须与source raw或lzbench对象区分。 |

## 本轮修正与历史差异

NeaTS/LeaTS 三份说明性 patch 已变成实际可按序应用的 patch。锁定 commit `2d804ff492e45222e841dc1a50904476fa64f4a0` 重放后 172/172 vendor 文件相同；vendor 保持当前修改后 variant，source identity 和 patch set identity 已更新。该修正证明可重放性，不把 scalar／serialization／predictor 修改擦除。

ABBA/fABBA `double(SIZE_MAX)` 检查在 x64 可放行 2^64，再转 `size_t` 触发 UB。已在当前 vendor 转换前用 2^digits 排除不可表示值，并在逐段循环前核剩余 sample 容量；旧 core、旧测试 driver、实际 patch、sanitizer 复现及修复对照均保存。合法算法公式与 frame 不变。独立历史 `Compression_Rewrite/ReWrite` 快照保持历史，新 vendor 资格不反向授予旧发布包。

较早 `native_agent.md` 中“lzss-raw 仍生产 Rust”的结论对应当时实现，现已被纯 C++ 重写和本表的新 Rust oracle 对照取代。其来源逐 SHA 记录保留历史价值；不复写旧报告。root 实施的 LZ4/Zstd 状态/容量、typed decode、strict CTest/driver/source closure、factory 和 onboarding 修正见主审计。
