# V4 native codec 资格证据汇总（2026-10-13）

原 native grid 包含 **36 个真实 native codec、834 个成功案例、14 个预期源域拒绝、0 个未解释失败**，总计 848 个案例。此 0 错误只属于原 grid；后续 exact timestamp 资格已经记录 NEATS／LEATS 的真实 `bitwise_mismatch` 错误，不能解释为全仓库 0 错误。`raw-store` 参考实现未计入。此文只汇总已保存证据，未触发编译、原生测试或 benchmark。资格结论只适用于记录中的输入、已解析参数、binary 和 bridge；不代表上游全域一致性。

完整逐 codec 的 `build_id`、`artifact_sha256`、dtype、成功／拒绝／错误计数，以及 62 个按 codec 分组的唯一参数配置均在 [汇总 JSON](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/native_qualification_summary.json)。每个配置保存原始 `params`、规范 JSON 和完整 SHA-256，拒绝案例也计入配置统计。参数身份按 `json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` 的 UTF-8 字节计算 SHA-256；配置 hash 本身不包含 codec、binary 或 bridge，比较时需一并使用这些身份。

## 执行批次与 bridge 身份

该记录是首轮 grid 与 SIMD 修复后的完整再资格合并结果：其余 35 个成员保留首轮的 786 个成功和 14 个预期拒绝；`simdcomp-u32` 在修复 empty 输入的 typed stride（由 NumPy 的 0 改为 dtype itemsize）后独立完成全部 48 个成功案例。其余 35 个成员所在分支不受该 SIMD 修复影响，但**没有在完全相同的最终 bridge 文件 hash 下重新执行**。原始报告顶层 hash 已更新为最终文件，不能据此宣称所有案例都在同一个最终 hash 下运行。该批次关系来自资格执行者的交接说明；原始 JSON 没有逐案例保存首轮 bridge hash。

| 文件 | 原始报告记录的最终 SHA-256 | 汇总时仍匹配 |
|---|---|---|
| `benchmark/src/tsbench/bridges/__init__.py` | `f8073dd42c0f9d45085d8c7896609e4510ae326504bbd2fd9278f90a4dc24b10` | 是 |
| `benchmark/src/tsbench/bridges/c_abi_v1.py` | `5b3973a9ef42193d5217e5743d2584e52da518611a5bbff7daecf5915021d885` | 是 |
| `benchmark/src/tsbench/bridges/rw_abi_v1.py` | `456fd0ae73743b07ad482454da2fdb4774c503c2faa462ada6e86a02a1e9f396` | 是 |
| `benchmark/src/tsbench/registry.py` | `e9acc9184665970e475e344f43a2bd1e0f813a9cd276ecc28024e00862e02309` | 是 |

## 成员与案例

下表使用 NumPy dtype 标记：`<` 为小端，`|` 表示字节序不适用；`i/u/f` 分别为整数／无符号整数／浮点，数字是字节数。各行完整 binary 身份和配置 hash 见汇总 JSON 同名 `records`，逐输入／payload／恢复结果的 hash 保留在原始 grid。

| Codec | 记录 dtype | 成功 | 预期拒绝 | 错误 | 唯一配置 |
|---|---|---:|---:|---:|---:|
| `abba` | <f8 | 3 | 0 | 0 | 1 |
| `alp` | <f8, <f4 | 8 | 0 | 0 | 1 |
| `alp-rd` | <f8, <f4 | 8 | 0 | 0 | 1 |
| `brotli-stream` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `bzip2-stream` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `chimp` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `chimp128` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `deepzip` | &#124;u1 | 21 | 1 | 0 | 17 |
| `deflate-zlib` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `dzip` | &#124;u1 | 5 | 1 | 0 | 2 |
| `elf` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `elf-plus` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `elf-star` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `fabba` | <f8 | 3 | 0 | 0 | 1 |
| `fse` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `huff0` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `leats-lossless-i64` | &#124;i1, <i2, <i4, <i8 | 14 | 0 | 0 | 2 |
| `lz4-frame` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `lzss-dipperstein-c` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `lzss-raw` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `lzsse2-raw` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `lzsse8-raw` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `neats-lossless-i64` | &#124;i1, <i2, <i4, <i8 | 14 | 0 | 0 | 2 |
| `self-star` | <f4, <f8 | 8 | 2 | 0 | 1 |
| `serf-qt` | <f8, <f4 | 12 | 0 | 0 | 2 |
| `serf-xor` | <f8, <f4 | 12 | 0 | 0 | 2 |
| `simdcomp-u32` | <u4 | 48 | 0 | 0 | 5 |
| `snappy-raw` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `sprintz-delta` | &#124;i1, &#124;u1, <i2, <u2 | 24 | 0 | 0 | 1 |
| `sprintz-delta-u8` | &#124;u1 | 4 | 0 | 0 | 1 |
| `sprintz-fire` | &#124;i1, &#124;u1, <i2, <u2 | 24 | 0 | 0 | 1 |
| `sprintz-fire-huff0` | &#124;i1, &#124;u1, <i2, <u2 | 24 | 0 | 0 | 1 |
| `sprintz-fire-u8` | &#124;u1 | 4 | 0 | 0 | 1 |
| `xz-stream` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |
| `zfp-accuracy-1d` | <f4, <f8 | 12 | 0 | 0 | 2 |
| `zstd-frame` | <i8, <i4, <i2, &#124;i1, <u8, <u4, <u2, &#124;u1, <f8, <f4 | 42 | 0 | 0 | 1 |

## 覆盖与限制

基础 grid 覆盖记录 dtype 的 17／257 长度、允许的三列矩阵及 empty。适用字节 codec 的 rank 3／4 案例只使用首个声明 dtype。SIMDComp 的五种合法 ISA／API 配置覆盖长度 0／17／127／128／129／255／256／257 和完整 u32 高位模式；Sprintz 包含 i8／u8／i16／u16 的有符号极值或高位模式。DeepZip 的 17 个 model_key 用 tiny symbol 输入完成 round trip；DZip 记录 BOOTSTRAP 与 COMBINED 模式。14 个拒绝包括 Chimp／ELF 系列的 NaN 源域和 DeepZip／DZip 的模型 alphabet 限制，它们是预期拒绝，不能计作成功 round trip。

**原 grid 未覆盖 i64 大整数跨度／epoch 或完整极值。** dtype 列表包含 i64，以及 NEATS／LEATS 的 `max_bpc=16/32` 案例，不构成上述输入域的证据。也未穷举所有配置、长度、ISA／平台、特殊浮点位型或多维 rank。此 object bridge 资格不建立 streaming／query／GPU executor 已完成的结论。资格运行时长不是性能结果。

有损成员仅按保存的案例解释：Serf-Qt、Serf-XOR、zfp 检查各案例的实际绝对误差及其请求的 0.001／0.00001 界。ABBA／fABBA 仅检验有限恢复并报告经验误差，不能将 compression／digitization 参数解释为严格重构界。

| Codec | 本轮观察到的最大绝对误差 |
|---|---:|
| `abba` | 0.60004178856861756 |
| `fabba` | 0.5036702882922377 |
| `serf-qt` | 0.00099805643212869111 |
| `serf-xor` | 0.00099862180650234222 |
| `zfp-accuracy-1d` | 0.00044491301234450553 |

## 后续已知反例

后续 [timestamp observations](/home/fzg/PycharmProjects/TSDataCompressBenchMark/runs/timestamps-20261013/observations.jsonl) 中，`irregular-time-axis/neats/cpu-single` 和 `irregular-time-axis/leats/cpu-single` 的 exact qualification 均为 `status=error`、`reason=bitwise_mismatch`。两个案例使用 i64、257 个不规则 timestamps 与 identity transform；implementation 小样本套件通过并不能替代该实际输入的 exact qualification。该错误必须保留，不能改写成 `unsupported`。原 grid 的 834／14／0 统计保持其原记录含义，并不覆盖这两个后续错误。

资格执行者的纯解析说明记录了 float32 coefficients `[60000002048, 120000004096, 60000002048]`、`starts=[0,5,7]`、`bpcs=[0,0,0]`、`residualbitssize=0`；257／257 个 timestamps 不一致，最大绝对误差为 512000（整数输入单位）。详细分析见 [分析 JSON](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/neats_timestamp_failure_analysis.json) 和 [分析说明](/home/fzg/PycharmProjects/TSDataCompressBenchMark/docs/research/neats_timestamp_failure_analysis.md)。这些诊断来自执行者的后续纯解析，本次汇总未运行 codec；原 observations 的 verification 字段未直接记录该数值误差。

汇总 JSON 的 `known_later_counterexample` 保存两个 exact 错误的 case／run／implementation／artifact／codec-input 身份、observations 文件快照 hash，以及后续分析文档定位。该 observations 快照 SHA-256 为 `295adb47ff6c7702bc867e0e863a0426ae1e60c958c8370d186aadc5fc37346b`。后续反例不回写原 grid 的历史计数，也不建立新的非显式输入域规则。

## 独立 decoder 与构建缓存

资格执行者报告 DeepZip／DZip 使用新的 decoder 进程，在只安装 library、codec card、index／build 记录与 payload 的临时 root 中完成 bitwise 恢复；没有 adapters／source／model 资产目录，系统 runtime 仍可用。原始 decoder 记录对二者均保存 `status=ok`、`decoder_process_has_source_or_model_assets=false` 及下表恢复 hash。bitwise 比较结论来自执行者说明；其原始记录未单独保存显式比较字段、build／artifact／params／input／payload 身份或进程命令，因此不能只凭该 decoder JSON 完成与主 grid 案例的全部身份绑定。

| Codec | Native payload bytes | decoded SHA-256 |
|---|---:|---|
| `deepzip` | 144527 | `487e12436e968f99773b34162531f1b55f70230f2cdfaacfbf4774d62e6a9057` |
| `dzip` | 115409 | `487e12436e968f99773b34162531f1b55f70230f2cdfaacfbf4774d62e6a9057` |

真实缓存漂移审计修改的是自有 build 目录中的 compiler-generated dependency header。记录显示 `cache_recompiled=true`、冻结资产未修改，恢复后输出 binary SHA-256 为 `7709f581b3673c3d64b5960d8df2bc1f8979086a17e4be49641d8f1bc05000d4`，与主 grid 的 `alp` artifact 对应；依赖闭包包含 180 个系统头文件。这证明该次真实漂移触发重新编译，不等同于穷举全部工具链或 runtime 漂移路径。

原依赖 SHA-256 为 `33aace1b36f3371e7347017c3175421399124c4aa90491d0822be6a44df21afc`；漂移后为 `980a535624df4712649c21e95520f55a63dca1f8fb63fb1d8c39f91340a47e73`。完整审计原字段保留在汇总 JSON 和原始文件。

## 原始证据定位

原始逐案例证据保留于本机 `build/tsbench`。下表 SHA-256 对应本次汇总读取的完整文件字节；汇总 JSON 同时保存相对路径、绝对路径和字节数，便于追溯。

| 原始文件 | 字节数 | SHA-256 |
|---|---:|---|
| [native_qualification.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/tsbench/native_qualification.json) | 944016 | `86cb911aff4ae6d0636e45db1c05f134cc1d7b0eaf8be3e313da5de6a8e6617a` |
| [wire_only_decoder.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/tsbench/wire_only_decoder.json) | 635 | `9f6dc51354d6b70c336807f4468b547508e8d830510caddded8fc97c22f95bd8` |
| [build_dependency_cache_audit.json](/home/fzg/PycharmProjects/TSDataCompressBenchMark/build/tsbench/build_dependency_cache_audit.json) | 521 | `0fff934b2802871f12cfa922ea9ae010aa3a984e244492053d8d072ccc65f528` |

本汇总没有重新执行资格，也没有运行 benchmark。正式性能测量应使用其自身保存的 session／round、配置和 artifact 身份；这里的成功数量不可替代正式工作负载的资格判定。
