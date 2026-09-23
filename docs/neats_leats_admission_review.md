# NeaTS / LeaTS lossless integer admission review

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and identity

The spreadsheet lists NeaTS in `参考TSBench` row 16 and `Value-Compress` row 71,
and identifies the NeaTS/LeaTS family in `Value-Compress` row 75. Both admitted
implementations come from the clean `and-gue/NeaTS` checkout at commit
`2d804ff492e45222e841dc1a50904476fa64f4a0`. The 172-file closure has SHA-256
`71c668cfb78ced6e95b5d8e21a274a230d699c5b052e13aa4c8f0a105bcd3644` and retains
the upstream GPL-3.0 and bundled dependency notices.

The two codecs share SourceArtifactID
`v2:source-artifact:sha256:3901f0276c7c6c841174b4a0267e92ea8e1887e68b70bb8d0e71fa9e66784d10`
but have distinct AlgorithmIDs. `neats-lossless-i64` selects the upstream nonlinear
piecewise model; `leats-lossless-i64` selects the linear model. Their model families,
serialized objects and bitstreams are not aliases and their results are not merged.

## Patches and native execution

Three hashed build-time patches, with combined SHA-256
`76172f500afe359f5c5831e0db33f2ae559e3a91e5fe8088fe1c405216d44268`, are replayed
outside the immutable vendor closure. The first replaces C++23-only helpers and the
upstream SIMD residual writer with GCC 11-compatible scalar code. The second restores
LeaTS serialization/load code that is commented or references the wrong fields upstream.
The third makes LeaTS encode use the same double-precision predictor evaluation as
decode. Without that correction, the 4096-by-4 qualification object had 24 reconstructed
values differing by one.

Python drives two separately linked C++20 artifacts through C ABI v1. Compiler automatic
vectorization is disabled, so the admitted path is scalar, CPU-only and single-threaded.
The registered domain is lossless signed int8/int16/int32/int64 VALUE UTS or synchronous
MTS, with at most 65,536 rows, 64 columns and 262,144 elements. Channels are independent.
Unsigned integers, floats, validity, asynchronous MTS, streaming, lossy modes, AVX paths
and multithreading are rejected rather than converted or silently dispatched.

## Learned-model and accounting contract

`implementation_class=LEARNED` describes the object-local fitted model. Compression
fits a new model for every column of every object; there is no external training corpus,
train/test split, checkpoint, cross-object state or amortized fitting. Model fitting is
inside compression timing, so there is no test leakage or uncharged training cost.
The checked per-column minimum shift is internal codec framing, not a separately timed
framework preprocessing stage.

The self-contained stream contains the canonical outer descriptor, variant header,
signed per-column bias, payload lengths, complete upstream serialized model, residuals,
Elias-Fano/rank index and a full-frame FNV-1a checksum. Every model and index byte is
included in `serialized_bits`/`FinalBits`; external side information is zero. Decode
rejects descriptor mismatch, truncation, trailing data, checksum changes, invalid record
sizes and signed-range overflow.

## Query, timing and safety

The native query entry point loads the selected serialized column and checks its result
against the canonical query workload. `bytes_touched` is the entire native frame because
checksum validation scans the full frame before selecting a range. It must not be
interpreted as sub-frame I/O amplification.

The native timing boundary is `NATIVE_OBJECT_FIT_SERIALIZE_AND_LOAD_DECODE_V1`. Encode
includes model fitting, residual construction and complete upstream serialization.
Decode includes loading serialized column objects and reconstructing values; Python
layout conversion, FFI/container work and decode checksum/header prevalidation remain
outside. This is not an upstream SIMD benchmark or lzbench-equivalent kernel timing.

Release and ASan/UBSan ABI suites pass all four signed widths at 1, 2, 3, 17 and 128
rows, including UTS/MTS round trips, native query, checksum corruption, truncation,
canaries and undersized destinations. LeakSanitizer is not claimed: managed ptrace is
incompatible, so the sanitizer run uses `ASAN_OPTIONS=detect_leaks=0` while ASan and
UBSan remain fail-fast.

## Evidence and limitations

- Qualification: `runs/runset-20260920T081824Z-26d63b8dfcfa`; both algorithms have
  lossless correctness and query PASS.
- Formal: `runs/runset-20260920T081952Z-a30140b62718`; 20/20 eligible PASS repetitions,
  ten per algorithm, with 20 query PASS results.
- Report: `runs/runset-20260920T081952Z-a30140b62718/report/report.html`.
- ReportID:
  `v2:report:sha256:efda2ecb9b0e8988c490b1ee68534a3dac77dede0d3491d69212ec48277c2f70`.

The formal fixture is deterministic synthetic `sprintz_i16_mts`. It establishes a
reproducible integration result, not a performance claim for real data, other integer
widths, floating point, SIMD, joint multivariate modeling or other parameters.

Historical run sets remain append-only. `080622` records the initially misdeclared
preprocess executor and is incomparable. `080839` records the 24-value LeaTS lossless
failure that motivated the precision patch. Neither is rewritten or used as final
admission evidence.
