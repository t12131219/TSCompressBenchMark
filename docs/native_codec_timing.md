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

Nanosecond units do not imply nanosecond accuracy. The selected-scope duration
threshold does not guarantee a long enough native interval. Differences between
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
