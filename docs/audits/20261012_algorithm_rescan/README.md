# 2026-10-12 已接入算法重新扫描

**结论：33 个活动入口的 C/C++ 核心及当前选定适配配置均可运行；不能判定每个算法已完整完成上游移植／重写。**

原生移植、原生复用和从其他语言重写是不同路线，无需让每个算法同时完成两种路线。Python 仍承担 Benchmark 调度、布局、FFI 和部分容器处理；“原生”在本报告中指算法核心。

本轮新执行：33/33 安装源码限定集合与字节闭包 PASS，17 个锁定原仓的 14,331 个 Git blob 检查通过；36 个真实登记入口工件／实际动态加载 PASS（另有 4 个 harness oracle）；33 活动入口的 41 个 Track/配置/fixture 案例全部 SCOPED_PASS。每例的边界安全、编解码正确性、成本账本及独立进程恢复检查均通过。

每个声明 Track 只选一个有限 fixture/config，不代表所有声明参数、长度、模型、ISA、平台、流式／查询能力均已覆盖。对有损算法按该入口合同验证，不能把 SCOPED_PASS 理解为逐位无损或质量全面达标。

完整门禁引用并核验最新冻结验收及后续构建补充：220 条适用条件为 3 PASS、32 FAIL、185 UNKNOWN，无入口获全部门禁通过。FAIL 包括未测试及 API／合同／独立交付缺项，不能读成 32 个算法运行失败；UNKNOWN 也不表示算法损坏。新资格案例不会自动替代完整 G/N/CAP 验收。

以下各行的源码、工件加载、本轮所列案例均通过；最后一列列出完整验收中仍明确 FAIL 的条件，其余未通过项为 UNKNOWN。N 族所有 N0–N5 仍为 UNKNOWN。

| 算法 | 路线 | 本轮通过案例（Track / fixture） | 完整验收中 FAIL |
|---|---|---|---|
| `abba` | 源码翻译重写 | VALUE / rewrite_float_mts | G3, G6, CAP-GATE |
| `alp` | 原生移植 | VALUE / exchange_rate | 无；N0–N5 UNKNOWN |
| `alp-rd` | 原生移植 | VALUE / exchange_rate | 无；N0–N5 UNKNOWN |
| `brotli-stream` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `chimp` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `chimp128` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `deepzip` | 源码翻译重写 | VALUE / rewrite_byte_uts | G3, G4, G5, G6, CAP-GATE |
| `deflate-zlib` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `dzip` | 源码翻译重写 | VALUE / rewrite_byte_uts | G2, G3, G4, G5, G6, CAP-GATE |
| `elf` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `elf-plus` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `elf-star` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `fabba` | 源码翻译重写 | VALUE / rewrite_float_mts | G3, G5, G6, CAP-GATE |
| `fse` | 原生复用 | VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `huff0` | 原生复用 | VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `leats-lossless-i64` | 原生移植 | VALUE / sprintz_i16_mts | 无；N0–N5 UNKNOWN |
| `lz4-frame` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `lzss-dipperstein-c` | 原生移植 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `lzss-raw` | 源码翻译重写 | TIMESTAMP / national_illness<br>VALUE / national_illness | G6, CAP-GATE |
| `neats-lossless-i64` | 原生移植 | VALUE / sprintz_i16_mts | 无；N0–N5 UNKNOWN |
| `self-star` | 源码翻译重写 | VALUE / rewrite_float_mts | G6, CAP-GATE |
| `serf-qt` | 原生移植 | VALUE / exchange_rate | 无；N0–N5 UNKNOWN |
| `serf-xor` | 原生移植 | VALUE / exchange_rate | 无；N0–N5 UNKNOWN |
| `simdcomp-u32` | 原生移植 | VALUE / streamvbyte_u32_uts | 无；N0–N5 UNKNOWN |
| `snappy-raw` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `sprintz-delta` | 原生移植 | VALUE / sprintz_i16_mts | 无；N0–N5 UNKNOWN |
| `sprintz-delta-u8` | 原生移植 | VALUE / sprintz_u8_uts | 无；N0–N5 UNKNOWN |
| `sprintz-fire` | 原生移植 | VALUE / sprintz_i16_mts | 无；N0–N5 UNKNOWN |
| `sprintz-fire-huff0` | 原生移植 | VALUE / sprintz_i16_mts | 无；N0–N5 UNKNOWN |
| `sprintz-fire-u8` | 原生移植 | VALUE / sprintz_u8_uts | 无；N0–N5 UNKNOWN |
| `xz-stream` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |
| `zfp-accuracy-1d` | 原生复用 | VALUE / exchange_rate | 无；N0–N5 UNKNOWN |
| `zstd-frame` | 原生复用 | TIMESTAMP / national_illness<br>VALUE / national_illness | 无；N0–N5 UNKNOWN |

## 逐项适配域与限制

- **abba**：f64 有限序列；KMEANS/INCREMENTAL、norm/scl/max_len 以参数白名单为准；多列独立编码。 完整性限制：阶段 oracle 是来源 Python 分段/重建＋原 CKmeans 组合，未重新授予完整未改 Python 调用图、全部数据集/required 优化 G0–G6。
- **alp**：f32/f64；显式拒绝源不支持输入；完整自有 ALP frame。 完整性限制：强制 decimal 路径不等于上游自适应 ALP/ALP-RD 选择；source-reject RAW composition 是独立对象。
- **alp-rd**：f32/f64；完整自有 ALP-RD frame。 完整性限制：不等于全部上游 adaptive/ISA/参数集合。
- **brotli-stream**：完整 Brotli stream；声明字节视图、stream 生命周期。 完整性限制：不把 lzbench one-shot 调用图、全部字典/参数/平台视为已验。
- **chimp**：f32/f64；N=1 raw profile；Bench frame、descriptor、多列绑定另验。 完整性限制：raw 对照不授予不同的 RWF1/FFI/binding 或上游全部能力 G6。
- **chimp128**：f32/f64；N=128 raw profile；共用 Chimp 包，保留独立入口身份。 完整性限制：其它 N/上游调用方式未由该 profile 的112例验证。
- **deepzip**：uint8 alphabet 0..3；17 frozen portable model，完整 frame 含模型成本；本 Bench 禁 HDF5/CUDA。 完整性限制：Exact TF-GPU1.8/Keras2.2.2/NumPy1.16.4 runtime and source GPU execution are now available. Current fixed-weight four-symbol biGRU has a retained independent-prediction CDF difference; finite fixed-weight/archived context evidence does not cover all original trained checkpoints, native GPU, complete source codec or full required dataset/capability scope. No valid waiver/full parity.
- **deflate-zlib**：RFC1950完整 zlib stream；声明字节视图和 stream 生命周期。 完整性限制：不是裸 DEFLATE/所有 strategy/dictionary/平台资格。
- **dzip**：uint8；BOOTSTRAP/COMBINED；NATIVE_SEEDED_UNTRAINED_INPUT_ALPHABET；AVX wrapper＋runtime dispatch与3线程预算。 完整性限制：Exact TF1.14 CPU/GPU runtime is restored and probed. Current public native-seeded untrained initialization is distinct from original TF initialization and trained PRNN; no DZip source model/training/codec execution occurred in the fresh diagnostic. Full required capabilities and legal four-state classification remain unclosed.
- **elf**：f32/f64；源域拒绝保持；Bench frame独立。 完整性限制：有既有本地许可决定，仍按该来源/许可证范围消费；全G/CAP发布未重签。
- **elf-plus**：f32/f64；82合法无损域＋NaN END sentinel；8个源失败域有界native拒绝。 完整性限制：8案例不得算fresh原Java失败复现；END不算无损PASS；Bench RAW escape/composite不能反向扩大源域。
- **elf-star**：f32/f64；one-shot声明profile。 完整性限制：不能称完全无patch原Java构建；所选算法路径未改，未覆盖完整上游CAP发布。
- **fabba**：f64 有限输入；稳定化 norm/std/tie；partition profile按白名单。 完整性限制：不能把稳定化oracle说成未改原作全部路径；完整 G0–G6/CAP/发布未重签。
- **fse**：uint8 symbol/完整frame；失败容量和模式独立验证。 完整性限制：RAW/RLE数据不是全payload运行FSE；P2 byte桥独立于原uint8熵核心。
- **huff0**：uint8 熵核心；当前 typed-byte 视图/完整frame 是 P1 standalone codec。 完整性限制：上游HUFF字典/全部API不自动开放；当前P1 wrapper资格不能反授原熵core全部能力。
- **leats-lossless-i64**：i8/i16/i32/i64归一到int64 per-column min shift；lossless frame/model/index/checksum、query/random-access；scalar。 完整性限制：完整源closure为修改后vendor；未重新执行全部未改源差分/ISA；旧正式资格不迁到新patch身份。
- **lz4-frame**：完整 LZ4 frame流；typed byte视图与descriptor；非lzbench raw块。 完整性限制：来源raw block与当前frame比较对象不同；不授所有上游dictionary/参数/平台。
- **lzss-dipperstein-c**：固定LZSS token profile；空输入special case＋严格token validator。 完整性限制：New r3 supplement verifies exact original lzss/bitfile/optlist authority trees/gitlinks and selected vendor bytes. Original native API/affected-path semantic baseline, complete capability and isolated delivery still need acceptance; the earlier local missing-authority snapshot is historical.
- **lzss-raw**：EI=10/EJ=4/C=32 raw bytes；完整Bench typed container另验。 完整性限制：旧专项的生产Rust标签过时；当前C++仅固定profile，不代表整个Rust generic/dynamic/in-place API G/CAP完成。
- **neats-lossless-i64**：i8/i16/i32/i64归一到int64 per-column min shift；lossless完整frame/model/index/checksum、query/random-access；scalar。 完整性限制：只改说明性patch为真实可重放patch，不把修改后核心说成原作未改或原SIMD完整parity。
- **self-star**：f32/f64；one-shot＋network选定profile；Bench frame另验。 完整性限制：6 network为standalone路径证据，不能授Bench未开放stream/network capability；全G/CAP未重签。
- **serf-qt**：f32/f64按column/block；nonfinite/unrepresentable/overflow RAW有成本。 完整性限制：含RAW对象不是每块纯upstream Qt；query/random-access未开放。
- **serf-xor**：f32/f64按column/block；非finite等RAW透明计费。 完整性限制：Qt与XOR不能混用来源PASS；RAW不得推广为上游源域。
- **simdcomp-u32**：u32；5个plain API/ISA组合；P0 primitive经frame包裹。 完整性限制：非FastPFOR SIMDBinaryPacking，不授delta/全部bitpack入口；P0不能冒称上游完整codec。
- **snappy-raw**：完整Snappy raw流；scalar；外层typed descriptor归项目。 完整性限制：不是Snappy framed格式，也没有dictionary/checksum能力。
- **sprintz-delta**：声明i8/u8/i16/u16按二维分组、signed转换与tail；bounded API完整项目frame。 完整性限制：layout/group和尾块属于合同；不能称所有Sprintz域/平台完成。
- **sprintz-delta-u8**：声明uint8低维profile；AVX2/BMI2/LZCNT；tail。 完整性限制：低维u8 profile不能替代full8/16-bit能力。
- **sprintz-fire**：声明i8/u8/i16/u16 UTS/MTS、维度分组、signed转换与tail；AVX2/BMI2/LZCNT。 完整性限制：不是FIRE+Huff0链，也非全部FIRE平台/参数资格。
- **sprintz-fire-huff0**：完整组合frame与两个stage成本；声明i8/u8/i16/u16、signed转换/ISA/group/tail。 完整性限制：组合PASS不能反向扩大Sprintz/HUF原生域；不得归成单kernel。
- **sprintz-fire-u8**：声明uint8低维profile；AVX2/BMI2/LZCNT；tail。 完整性限制：低维u8不代表full8/16-bit全部能力。
- **xz-stream**：preset6，data check NONE但结构CRC存在；完整XZ stream。 完整性限制：不是raw LZMA/所有XZ filter/字典/参数模式。
- **zfp-accuracy-1d**：f32/f64逐列accuracy；NaN/Inf/negative-zero/subnormal RAW成本透明。 完整性限制：rate/precision/reversible/ND/CUDA未开放；RAW列不等于ZFP payload。
- **zstd-frame**：完整Zstd frame；禁asm/BMI2dispatch/legacy/dict/MT profile。 完整性限制：不授全部dict/MT/平台；frame/API的scope须与source raw或lzbench对象区分。

## 正式运行与证据边界

既有新 FORMAL 队列共 16 lane，当前只确认 entropy、stream、query-warm、query-fresh 共 4 lane。entropy 为 CORE_COMPLETE 16/16，包含 fse、huff0、lz4-frame、zstd-frame；后三项为 PROFILE_COMPLETE。pipeline pilot 不具资格，其余保留资源压力、停止、不支持或汇总缺口。cold 修复后另有原 raw 重分析回执，未重测。lane 缺口不能归因为每个参与算法都编解码失败。

精确 TF 旧源环境和 GPU 已恢复；DeepZip 的新源对照仍有独立预测 CDF 1/15 整数差异；DZip 当前 native-seeded untrained 模型不同于原 TensorFlow 初始化和已训练 PRNN。环境可用不自动授予模型／源码语义一致性。

`lzss-raw` 当前生产核心为 C++，固定 EI=10/EJ=4/C=32；Rust 原作对照不属于生产依赖，固定 profile 通过不能证明原 Rust 全部 generic/dynamic/in-place API 完整重写。

bzip2-stream、lzsse2-raw、lzsse8-raw 仅保留登记并通过加载，本轮未授活动资格。未在本轮重新执行 67 构建配置、33 strict release 构建、全部 pytest 或性能测量；这些已有记录均按各自原范围引用。

证据哈希重新核验：最终旧索引 25 项、冻结验收输入 24 项、后续补充输入 8 项、本轮源码输入快照 2431 项全部匹配。算法和 SourceArtifact 身份在新源码、工厂及资格计划之间逐项一致。

机器可读逐项结果及 SHA 见 [report.json](report.json)；实际资格记录见 [summary.json](../../../build/algorithm-rescan-20261012/active33-r1/summary.json) 与 [four_matrices.json](../../../build/algorithm-rescan-20261012/active33-r1/four_matrices.json)。旧证据未改签，完整上游 parity／独立交付／全域运行及性能资格均未由本次有限检查授予。

复现命令：

```bash
/home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261011_closure_formal_verification/source_closure/audit_sources.py --output-dir <新的源码审计目录>
PYTHONPATH=src /home/fzg/anaconda3/envs/CompressBench14/bin/python docs/audits/20261012_algorithm_rescan/check_factory.py
/home/fzg/anaconda3/envs/CompressBench14/bin/python tools/qualify_v32_active_entries.py --output build/algorithm-rescan-20261012/active33-r1 --resume --execute
```

工厂脚本及本汇总脚本使用排他写入以保护现有回执；再次新测须先使用副本配置新的输出位置。
