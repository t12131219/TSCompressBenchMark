# Zstd Frame five-layer integration self-check

Date: 2026-09-17  
Scope: second spreadsheet-listed native codec (`zstd-frame`) and direct comparison with
`lz4-frame`  
Environment: `CompressBench14`

## Source and admission gate

- [x] Reread the master plan, expanded edge-case standard, and C/C++ benchmark analysis.
- [x] Used Zstd 1.5.7 vendored by lzbench commit
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`; no network source was substituted.
- [x] Kept both shared source checkouts clean and used upstream Zstd commit
  `d9c0c7e2cf8a8bf9fb98d3bee546dcf8dc9ac59a` only as comparison evidence.
- [x] Copied the reviewed single-thread source closure and both license choices without
  modifying vendor files.
- [x] Excluded dictionary builder, legacy/deprecated APIs, CLI/examples,
  `zstdmt_compress.c`, and the x86 assembly translation unit from both the copied closure
  and execution build; retained `zstdmt_compress.h` only because internal headers include it.
- [x] Recorded source identity, closure digest, build flags/hashes, tests, license choice,
  limitations, and structured unsupported modes.

## Layer-by-layer gate

### Layer 1 — Data

- [x] The formal comparison uses `national_illness` through the existing manifest and
  canonical loader.
- [x] Seven heterogeneous Value buffers retain declared order, dtype, shape, units, and
  raw IEEE/integer bytes; the adapter performs no sorting, cast, fill, interpolation,
  or column dropping.
- [x] The denominator is 432,768 canonical raw bits, not CSV file size.

### Layer 2 — Capability, configuration, and comparison keys

- [x] Zstd is a reviewed P1 standalone lossless byte codec with explicit Track, topology,
  dtype, validity, parameter, and lifecycle declarations.
- [x] Registered execution is scalar CPU, one thread, no dictionary, no legacy decoder,
  no fallback, and no runtime dispatch.
- [x] Missing binary remains `BUILD_UNAVAILABLE / EXECUTION_ARTIFACT_MISSING`.
- [x] LZ4 and Zstd common byte-frame profiles share one algorithm-neutral Semantic,
  Execution, and Resource key; their AlgorithmID, ConfigID, artifact hash, and
  ExecutionPathHash remain distinct. A regression test freezes this rule.
- [x] Streaming/query/random-access and dictionary/multithread modes are not inferred.

### Layer 3 — Execution, correctness, and accounting

- [x] Lifecycle is `bound -> continue update -> end-until-zero -> accounting ->
  independent streaming decode -> close` with a new context per independent object.
- [x] `ZSTD_CCtx_setPledgedSrcSize` makes content size explicit; checksum is configurable.
- [x] Finalize loops on `ZSTD_e_end` until zero and repeated Finalize is rejected.
- [x] Capacity is not size; exact used lengths and finalized frame bytes enter FinalBits.
- [x] Structural parsing accounts for descriptor metadata, Zstd frame header, every
  three-byte block header, physical raw/RLE/compressed payload, and optional checksum.
- [x] Buffer order, dtype, shape, signed zero, infinity, and NaN payload bits reconstruct
  exactly under independent decode.
- [x] Framework boundary suite passed 49/49 cases for Zstd and LZ4.
- [x] Native Release and ASan/UBSan smoke passed N = 0, 1, 2, 131071, 131072, 131073,
  and 262145; fixed-seed upstream fuzzer passed 100 cases.

### Layer 4 — Formal measurement

- [x] Both codecs use one shared `FORMAL`, `PIPELINE`, PROCESS-resource profile with
  Python FFI/container work included.
- [x] Each codec completed more than 3 warmup iterations and at least 0.5 seconds.
- [x] Each codec produced 10 raw repetitions; every selected-scope observation is at
  least one second and uses independent object lifecycle semantics.
- [x] All 20 repetitions are PASS, correctness PASS, and performance eligible.
- [x] Run set: `runset-20260917T104254Z-9205f57f9d3a`.

### Layer 5 — Statistics, coverage, and report

- [x] Frozen task universe contains two tasks in one direct comparison group; coverage is
  PASS 2/2 with no failed, unsupported, OOM, timeout, or eligibility exclusion.
- [x] Zstd reports 214,936 FinalBits, 26,867 physical bytes, SizeRatio
  0.49665409642117717, and CompressionFactor 2.0134737782409648.
- [x] Zstd median-derived micro throughput is approximately 69.71 MB/s encode and
  258.80 MB/s decode on this recorded execution path.
- [x] The recorded LZ4 comparison point reports 263,912 FinalBits, SizeRatio
  0.60982327713694173, approximately 53.59 MB/s encode, and 288.41 MB/s decode.
- [x] Report ID:
  `v2:report:sha256:d614d0b097ed78bc03612bf5d37df7897c01c73379008a7396f65993103ff161`.

## Result and limitations

Zstd satisfies the project's current definition of integrated across Layers 1–5:
source provenance, license, frozen build, manifest/negotiation, preflight, bit-exact
correctness, Finalize, structural accounting, formal raw repetitions, comparison keys,
coverage, statistics, and report generation are closed.

This qualification applies only to the scalar, single-thread, no-dictionary frame
variant. lzbench's table uses `ZSTD_compress2`, while this adapter uses the same vendored
implementation's streaming API to satisfy the plan's explicit Finalize contract. The
wrapper currently issues one update per independent object and does not claim a common
continuous-stream protocol. LeakSanitizer could not run under the host ptrace policy;
ASan/UBSan ran with leak detection disabled and that limitation remains recorded.
