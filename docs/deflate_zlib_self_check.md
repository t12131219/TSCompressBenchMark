# DEFLATE zlib five-layer integration self-check

Date: 2026-09-18  
Scope: spreadsheet-listed CPU DEFLATE, implemented by benchmark-vendored zlib 1.3.2  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and admission

- [x] Followed the master plan, C/C++ analysis and expanded edge-case standard;
  DEFLATE is spreadsheet Value-Compress row 4. No unlisted algorithm was added.
- [x] Used clean lzbench commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`.
  Copied its complete 48-file `lz/zlib` tree without changing vendor bytes or license.
- [x] Built the same 15 zlib translation units listed by lzbench's Makefile.
  Python drives the native artifact; Python stdlib zlib is only a checksum/oracle,
  never the benchmark encoder or decoder.
- [x] Compared with clean upstream commit `e3dc0a85b7032e98380dec011bc8f2c2ee0d8fca`
  (1.3.2.1). Differences include version/build files and gzip/inflate-tree changes;
  upstream source is not mixed into the 1.3.2 baseline.
- [x] Closure SHA-256: `90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0`.
  Algorithm: sorted relative POSIX path UTF-8 bytes, NUL, full file bytes, repeated
  for every file. A regression test pins the count and digest.

## Layer 1 - Data

- [x] The `national_illness` preparation preserves 966 rows, seven heterogeneous
  float/integer channels and canonical denominator 432,768 bits.
- [x] Routed bytes retain buffer order, dtype, shape, logical bits and IEEE payloads.
  No cast, sorting, fill, transform, column removal or value preprocessing is added.
- [x] Empty/tiny inputs, NaN payloads, signed zero, infinities, subnormals, timestamp
  order/duplicates/epoch extremes, layouts and tails pass the 49-case boundary gate.

## Layer 2 - Capability, parameters and fairness

- [x] `deflate-zlib` is P1 lossless T1/V0, CPU scalar, single thread, no fallback.
  Defaults are level 6, windowBits 15 (32 KiB), memLevel 8, default strategy,
  no preset dictionary and mandatory Adler32. Level range is 0-9; window range is 9-15.
- [x] The registered object is TSCB descriptors plus RFC1950 zlib containing RFC1951
  DEFLATE. It is not raw DEFLATE, gzip or a hardware DEFLATE implementation.
- [x] Tests keep Semantic/Execution/Resource keys separate from LZ4/Zstd frames,
  Snappy raw and Brotli stream. Context reset and native instrumentation policies
  remain visible. No incompatible cross-format total ranking is claimed.
- [x] Query, random access, streaming workload, preset dictionary and optional
  checksum modes are not advertised or silently substituted.

## Layer 3 - Lifecycle, safety, correctness and accounting

- [x] `deflateBound -> Z_NO_FLUSH update -> Z_FINISH until Z_STREAM_END -> accounting
  -> independent inflate -> close` is observable. Repeated update/finalize is rejected.
- [x] Native decoder creates a fresh context, consumes all input and produces exactly
  the descriptor length. Truncated, trailing, concatenated, invalid-header and
  corrupt-Adler32 streams are rejected, including by a new decoder-only session.
- [x] Exact returned lengths, output canaries, input immutability and deterministic
  bytes are checked. Capacity is never treated as encoded size.
- [x] Prefix plus two zlib header bytes are container bits; JSON is metadata; four
  Adler32 bytes are checksum bits. All DEFLATE bytes, including internal bit padding,
  are charged to the routed data bucket, not estimated as padding or omitted.
- [x] Physical conservation: 112 container + 6,080 metadata + 32 checksum +
  209,920 value = 216,144 bits = 27,018 bytes.
- [x] Release and ASan/UBSan passed ABI smoke for N=0/1/2/65535/65536/65537/131073,
  reset/reuse, insufficient finalize capacity and timing-counter reset.
- [x] Direct benchmark API `compress2/uncompress` harness passed 100 seeded cases
  (20260918) in both profiles. This is a project harness, not the upstream test suite.
- [x] Python covers 80 level/window/tail combinations, multi-buffer IEEE exactness,
  independent stdlib decode compatibility, invalid parameters and closure identity.
- [x] Competing global deflateInit2_ reproduced the old ELF binding risk. The final
  `-Wl,-Bsymbolic-functions` build passes ABI smoke with that LD_PRELOAD competitor;
  internal codec calls stay within vendor source. `ldd` has no system libz dependency.

## Layer 4 - Measurement evidence

- [x] Qualification: `runset-20260918T061832Z-d8ca7a21abd6`, PASS.
- [x] Formal: `runset-20260918T061850Z-6e262c4d405a`, 10/10 PASS, eligible and
  same-repetition correctness/measurement; all 49 preflight observations PASS.
- [x] Warmup: 166 independent objects, 500,905,276 ns; both minima satisfied.
- [x] Selected-scope duration range: 1,000,429,294 to 1,002,718,294 ns, each >=1 s.
- [x] All native update/finalize/inflate calls are timed under
  `CODEC_API_ONLY_V1 / CLOCK_MONOTONIC`; all encode/decode observations are positive
  and within pipeline time. Context lifecycle/prechecks/Python container are excluded
  only from native timing, not silently removed from pipeline measurement.
- [x] Native timing is auxiliary: the 1-second minimum applies to the configured
  PIPELINE combined work, not separately to native encode or decode.

## Layer 5 - Statistics and report

- [x] One complete per-dataset summary, 10/10 eligible raw repetitions, no exclusions.
  SizeRatio is about 0.49944543; CompressionFactor about 2.00222074.
- [x] Pipeline encode/decode: about 20.78/149.56 MB/s. Native API encode/decode:
  about 28.29/298.44 MB/s. Rates are scope-separated and not called lzbench-equivalent.
- [x] Report ID: `v2:report:sha256:3a046c2d9c5ecaca505a4f9db5cec1ea298b5443431e5836c997c9a604b5f636`.
  Report: `runs/runset-20260918T061850Z-6e262c4d405a/report/report.html`.
- [x] Admission card, registry, builds, configs, tests and all runtime/report artifacts
  are present in the canonical project, not only the Codex worktree.

## Build identities and limitations

Release `.so`: `c4c61655f2513661a8e6766025b45a1790ddc2ed8837b18ce2974a0c3d19aeb7`.  
ASan/UBSan `.so`: `c77375acebdc092c8b11de12712f2602f0d6cd0aa951bc2274525850cb1e1494`.  
Formal combined native/Python support artifact:
`45e9c1ceeb2a2dd6badb84fcc6c802bc01d67b355ff63aca9ead9839366e66ca`.

Earlier qualification `runset-20260918T061126Z-d8ca7a21abd6` and formal
`runset-20260918T061248Z-6e262c4d405a` remain append-only historical evidence;
the final symbol-bound builds and later runs above are the authoritative admission.

lzbench uses one-shot compress2/uncompress; this adapter uses the same implementation
through explicit update/finish to satisfy project lifecycle requirements. No gzip/raw
variant, custom memLevel/strategy, context-reuse benchmark, parallelism or streaming
protocol is registered. The current single-update ABI is bounded by UINT_MAX for input
and output capacity. Exact decode allocation is descriptor-based because zlib carries
no uncompressed-length field. ASan/UBSan run with LeakSanitizer disabled due to ptrace.
The formal result qualifies the tested default VALUE configuration and dataset, not a
claim of formal performance coverage across every dataset or parameter variant.
