# Brotli stream five-layer integration self-check

Date: 2026-09-18  
Scope: fourth spreadsheet-listed Batch-1 native codec (`brotli-stream`)  
Environment: `CompressBench14`

## Source and admission gate

- [x] Reread the master plan and C/C++ algorithm analysis; consulted the expanded
  edge-case standard where lifecycle and accounting details required clarification.
- [x] Used Brotli 1.2.0 vendored by clean lzbench commit
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`; no network source was substituted.
- [x] Kept lzbench and upstream Google Brotli checkouts clean. Upstream commit
  `4508218e7fef90fa4273286f7a415065946f2c43` is comparison evidence only.
- [x] Copied the unmodified common/encoder/decoder/include closure and MIT license.
  Relative-file closure digest:
  `99c9b5c8815308fa57543c3188ca1bb37b42a411785d10f9ed0ecbe214e4d06a`.

## Layer-by-layer gate

### Layer 1 - Data

- [x] Routed buffer order, dtype, shape, logical bits, and IEEE/integer bytes are
  serialized without casts, sorting, filling, interpolation, or column removal.
- [x] Empty, tiny, 64-KiB boundary, multi-buffer, signed-zero, infinity, subnormal, and
  NaN-payload cases are covered by native or framework tests.
- [x] Canonical raw bits remain the denominator; output capacity is never counted.

### Layer 2 - Capability, configuration, and fairness

- [x] Registered as P1 lossless T1/V0, quality 5, lgwin 22, generic mode, scalar CPU,
  one thread, built-in static dictionary only, no external dictionary, and no checksum.
- [x] One RFC 7932 Brotli stream per routed object has separate Semantic, Execution,
  and Resource keys from both LZ4/Zstd frames and Snappy raw.
- [x] Query, random access, and streaming-workload claims remain false; unsupported
  modes are structured rather than silently falling back.

### Layer 3 - Lifecycle, correctness, and accounting

- [x] Lifecycle is `bound -> PROCESS update -> FINISH until finished -> accounting ->
  independent one-shot decode -> close`; repeated Finalize is rejected.
- [x] Both PROCESS and every FINISH API call contribute to native encode timing;
  `BrotliDecoderDecompress` contributes to native decode timing.
- [x] TSCB prefix and canonical descriptor are container/metadata bits; all bytes of
  the finalized Brotli stream are assigned to the routed data bucket. Accounting method
  is `EXACT_TSCB_CONTAINER_AND_BROTLI_STREAM_LENGTH` and checksum bits are zero.
- [x] Release and ASan/UBSan ABI smoke passed N = 0, 1, 2, 65535, 65536, 65537,
  and 131073. The direct vendor API harness passed 100 deterministic cases in both builds.
- [x] Framework preflight passed all 49 required boundary cases.

### Layer 4 - Measurement

- [x] Qualification RunSet `runset-20260918T051810Z-33dd0667685e` passed.
- [x] FORMAL RunSet `runset-20260918T051826Z-a1980b4fbecf` completed 10/10 PASS and
  eligible repetitions. Every selected-scope repetition exceeded one second.
- [x] Warmup completed 270 independent objects in 500.112601 ms, exceeding both the
  3-iteration and 0.5-second minima.
- [x] Native API timing is present for all ten repetitions under
  `CODEC_API_ONLY_V1 / CLOCK_MONOTONIC` and remains inside pipeline time.

### Layer 5 - Statistics and report

- [x] Report contains one complete summary and 10/10 eligible repetitions.
- [x] FinalBits are 202,816 (25,352 physical bytes) from 432,768 canonical raw bits:
  SizeRatio 0.46864832889677610 and CompressionFactor 2.1337961502051120.
- [x] Pipeline throughput is about 37.40 MB/s encode and 144.83 MB/s decode; native
  Brotli API throughput is about 67.67 MB/s encode and 269.80 MB/s decode.
- [x] Report ID:
  `v2:report:sha256:dea5f26860e87d25d50151ab2a7dfda27f381be2f4a5c8559391a1b85289b38c`.

## Build identities and limitations

Release `.so`: `36f6cea7fd8207e23e3a527191f6fdce631d38f9994afbdfd2c9ca8ebe08da35`.
ASan/UBSan `.so`: `e872be83f1f7c3943ec463aaa3ef6dbb033e1088617b73d18c9faaeb4191b0f6`.
The formal execution artifact hash `40d1680f09d9f109badac98775d9ba3a71571f3e5cddd0f7e807358f5db1d208`
also binds the Python adapter support module.

lzbench uses the one-shot encoder entry point. The project intentionally uses the same
vendored implementation through PROCESS/FINISH to make Finalize observable as required
by the benchmark contract. Brotli does not store an uncompressed length in the stream;
the independently readable TSCB descriptor supplies the exact destination length.
LeakSanitizer is unavailable under the host ptrace policy, so sanitizer evidence uses
`detect_leaks=0`.
