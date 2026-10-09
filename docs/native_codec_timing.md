# Optional native codec timing

Native timing is enabled by default for the registered native adapters that expose the
optional timing ABI, including `serf-qt`, `serf-xor`, `neats-lossless-i64` and
`leats-lossless-i64`. Set
`native_timing = [false]` in an experiment's `[sweep]` to disable it. See
`configs/experiments/native-timing-formal-comparison.toml` for a formal example.
Rebuild the release adapters before using the extension:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py lz4-frame --profile release
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py zstd-frame --profile release
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py snappy-raw --profile release
```

`native_encode_wall_ns` and `native_decode_wall_ns` are auxiliary totals from the
same objects and inner iterations used by CORE and PIPELINE. They do not replace
selected timing, affect minimum-duration termination, or participate in rankings.
The timing-observation v2 schema accepts these optional fields; historical records
without them continue to work. JSON null / blank CSV / report n/a means disabled,
unsupported, or unavailable, not zero cost.

The optional ABI extension has a size/version-tagged output struct and separate
enable/query functions. Queries do not clear counters. Native handle creation starts
disabled; Python sessions enable timing by default before codec work;
reset clears totals and preserves enablement. Enabling is intended before codec
work and clears previous totals. Failed library calls contribute elapsed time;
wrapper-rejected calls do not. Clock failure, overflow, or a C++ exception makes
the timing unavailable until reset. Failed round trips remain ineligible.

The clock is CLOCK_MONOTONIC. CODEC_API_ONLY_V1 includes:

| Codec | Encode | Decode |
| --- | --- | --- |
| LZ4 | LZ4F_compressBegin, LZ4F_compressUpdate, LZ4F_compressEnd | LZ4F_decompress |
| Zstd | Every ZSTD_compressStream2 call, including e_end | Every ZSTD_decompressStream call |
| Snappy | RawCompress | RawUncompress |
| Serf-Qt / Serf-XOR | Complete native frame encode, including alignment copy, block calls, record serialization, and checksum | Complete native frame decode after checksum/header prevalidation, including record parsing, block calls, and result copies |
| zfp fixed-accuracy 1D | Complete native frame encode, including exception classification, per-column allocation, full zfp headers, serial 1D calls, records, and checksum | Per-column raw copy or serial zfp 1D decode after outer checksum/header prevalidation, including record parsing and result writes |
| NeaTS / LeaTS | Per-column object-local model fit, residual/index construction and complete upstream serialization | Load each serialized column model and reconstruct values after frame checksum/header prevalidation |

Explicit context create/free, parameter setters, bounds, Snappy length/validity
prechecks, Python FFI, descriptors, input/output copies, allocation, and accounting
are excluded. Allocations, copies, initialization, validation, and frame work
performed *inside* the measured library calls remain included. Finalize is essential:
buffered short LZ4/Zstd input can be compressed there rather than during update.

Python queries after CORE stops and before closing the handle. Query overhead is
outside CORE but inside PIPELINE. Native clock reads and counter bookkeeping add
overhead to CORE/PIPELINE. Instrumentation enablement is recorded in ConfigID and
ExecutionComparabilityKey so enabled and disabled experiments are not directly ranked.
The optional extension works with old binaries by returning missing measurements.

Raw native throughput uses `codec_input_bytes_per_iteration * inner_iterations *
1000 / native_wall_ns` (decimal MB/s). Dataset summaries use total bytes / total
elapsed time across repetitions, not an average of per-repetition rates. They
also provide per-object median, quartiles, mean, SD, CV, and bootstrap interval.
Native summaries require every eligible repetition to have a valid observation;
observation counts remain visible when incomplete. Corpus rates use summed
codec-input bytes divided by summed per-dataset median native time and are missing
if any dataset is missing native timing. CORE/PIPELINE auxiliary rates use canonical
bytes. Reports show all three layers side by side, retaining existing selected metrics.

Nanosecond units do not imply nanosecond accuracy. Each selected encode/decode direction
must reach the configured repetition duration; E2E also checks its complete duration.
This threshold does not guarantee a long enough native interval. Differences between
CORE/NATIVE/PIPELINE are diagnostic, not a disturbance-free exact decomposition.
Frame/raw, streaming/one-shot, context reuse, build flags, and hardware differences
still prevent automatic equivalence with lzbench. Existing run evidence and XLSX
artifacts cannot acquire native timings retrospectively; new measurements are required.

Serf uses the separately named `NATIVE_SERF_FRAME_ENCODE_DECODE_V1` boundary. It is
broader than `CODEC_API_ONLY_V1` because the upstream API is a stateful per-value block
interface and the registered decodable object is the project native frame. Native input
descriptor parsing, the final encoded-output copy, decode checksum/header prevalidation,
context lifecycle, Python layout work, FFI, and the outer Python container remain outside
that native interval. This boundary is diagnostic and must not be presented as an
lzbench-equivalent kernel measurement.

zfp uses `NATIVE_ZFP_ACCURACY_1D_FRAME_ENCODE_DECODE_V1`. Its encode interval includes
the complete registered native object because allocation, special-value classification,
full per-column zfp headers and raw exception records are part of that object's cost.
Decode checksum/global-header prevalidation remains outside; column record parsing,
raw-column copies and zfp calls are inside. The boundary is limited to serial 1D fields
and must not be presented as upstream native-ND kernel timing.

NeaTS and LeaTS use `NATIVE_OBJECT_FIT_SERIALIZE_AND_LOAD_DECODE_V1`. The encode
interval includes object-local fitting and every serialized model/index byte; there is
no separately amortized training phase. Decode checksum/global-header prevalidation is
outside, while loading the serialized per-column object and reconstruction are inside.
The admitted build is scalar and single-threaded, so these measurements must not be
presented as upstream AVX or benchmark-program timings.

# 三种主计时范围的接入状态（2026-10-08）

当前注册入口支持 `CORE`、`PIPELINE`、`E2E` 独立对象模式。18 个完成重写入口曾因
`execution.timing_scopes` 只列出 PIPELINE/E2E 而在规划时拒绝 CORE，现已补齐。
完整验证方法与逐项结果见 [三模式验证](all_algorithm_timing_scopes.md)。

本项目 CORE 使用 harness 对 session API 的 wall clock：encode 为
`compress_update + finalize`，decode 为 `decompress`。外层输入准备、context 创建、
encode 输出容量申请在 CORE 之外；API 内部的描述符、staging、copy、完整帧、模型工作及
decode 结果物化仍在 CORE 内。每次 inner iteration 用新 context，reset 通过新建 context
实现；finalize 在 encode CORE 内。CORE 不表示纯 native kernel 时间。
PIPELINE 包含外层准备、创建、bound/allocation、CORE、stream 物化、accounting、
telemetry 和 close，decode 还包括逆兼容操作。E2E 包含完整对象 encode/decode 及阶段间开销，
输入为内存中的 canonical routed view；文件读取及计时后的正确性检查不在边界内。

缺少 native timer 的实现仍将 `native_*` 记录为 null，不能用 CORE 数值填入。
注册声明变化会生成新 AlgorithmID；旧冻结运行及正式证据保持原身份和原结果。
