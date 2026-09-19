# XZ LZMA2 five-layer integration self-check

Date: 2026-09-18  
Scope: spreadsheet `Value-Compress!B9`, LZMA / xz, `xz-stream` single-call LZMA2  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and admission

- [x] Reviewed the master plan, algorithm analysis, spreadsheet and expanded ODT
  requirements for bound, Finalize, physical accounting and fairness. No unlisted
  algorithm was added. The original spreadsheet was read-only.
- [x] Scanned the shared source catalog: 72 repository entries, 71 available and
  clean, 221 logical entries and 145,830 non-generated files. Evidence:
  `build/source-audits/xz-onboarding-20260918.json`.
- [x] Copied only the required liblzma/common/CMake/test/license/format closure,
  341 files, from clean lzbench commit `fa871e66b3543a70fd4d060f7c12719343ff4ac3`.
  Every copied file was compared byte-for-byte with its source; vendor files are
  unchanged. Library/test license is 0BSD, with original notices retained.
- [x] Compared clean upstream `9fc6f5cd8774ebef8d4e030f7081fb6984c0dc3f`.
  Both report 5.8.3; index/decoder/API/hardware trees differ. Only lzbench supplies
  runtime sources; identical lzma2_encoder.c is not claimed as full-tree equality.
- [x] Closure digest:
  `ef43c1771d2d12fdb35b9d53a15394f81da23770f97891d78f1e97e3504d3574`.
  SHA256 over sorted relative POSIX path UTF-8 bytes + NUL + full file bytes.
  Tests pin both the file count and digest.

## Layer 1 - Data

- [x] national_illness retains 966 rows, seven heterogeneous float/integer channels,
  original dtype/order and 432,768 canonical raw bits. Dataset file size is not the
  compression denominator.
- [x] Routing has no cast, sorting, fill, transform or algorithm-specific preprocessing.
  Empty/tiny inputs, NaN payloads, signed zero, infinities, subnormals, timestamp
  duplicates/order/epoch extremes, layouts and tails pass 49/49 boundary cases.

## Layer 2 - Capability and fairness

- [x] P1 lossless T1/V0, CPU scalar, one thread, no runtime fallback. Default preset
  6; registered presets 0-9 have separate ConfigIDs. EXTREME is not registered.
- [x] Physical object is TSCB descriptors plus one complete .xz LZMA2 stream, with
  no data check and mandatory structural CRC32. It is not raw LZMA or .lzma.
- [x] Internal LZMA2 history is not an external trained dictionary; serialized
  filter properties are charged. Index presence does not imply query/random access.
- [x] Semantic/Execution/Resource keys remain distinct from other frame/raw/stream
  contracts; no incompatible total ranking or lzbench-equivalent timing is claimed.
- [x] Checked-in qualification/formal sweeps are validated against the registered
  parameter schema by regression tests; DEFLATE window_bits is not an xz parameter.

## Layer 3 - Lifecycle, safety and accounting

- [x] Documented single-call bound -> lzma_easy_buffer_encode -> mandatory zero-byte
  Finalize acknowledgement -> accounting -> fresh-context exact decode -> close.
  The encode API completes all block/index/footer work before returning. Repeated
  update/Finalize is rejected; this path does not advertise streaming workloads.
- [x] Native decoder flags 0, memlimit 1 GiB; requires STREAM_END, full input
  consumption and exact output length. Python independently checks the registered
  zero/one-block LZMA2 format before allocation. No concat/alternate filter fallback.
- [x] Exact lengths, capacities, canaries, input immutability, determinism,
  independent decoder sessions and Python stdlib compatibility oracle are covered.
  stdlib lzma never supplies the benchmark encoder or decoder.
- [x] Truncation, trailing data, concatenation, header/block/index/footer structural
  corruption and unsupported checks are rejected. With no data check, framework
  IEEE/integer exactness remains the payload correctness gate.
- [x] Physical conservation: 224 container + 6,152 metadata + 64 index +
  128 structural checksum + 16 alignment padding + 169,552 value = 176,136 bits
  = 22,017 bytes. Mandatory index/CRCs are not free; internal header/index padding
  stays in those respective fields. Capacity is never treated as encoded size.
- [x] Release and ASan/UBSan ABI smoke pass lifecycle, capacity, corruption, reset
  and native counters. Direct vendored API harness passes 100 seeded cases
  (20260918), presets 0-9, in both profiles; it is not lzbench's MT entrypoint.
- [x] Vendored library CTest: six PASS and six SKIP per profile. PASS: filter_flags,
  filter_str, index, index_hash, stream_flags, vli. SKIP: bcj_exact_size, block_header,
  check, hardware, lzip_decoder, memlimit (disabled features). CLI shell suites excluded.
  Logs: `build/adapters/xz_stream/<profile>/native-tests.log`.
- [x] Static PIC liblzma and local ELF function binding; ABI smoke passes under a
  competing globally preloaded lzma_easy_buffer_encode. No system liblzma dependency.

## Layer 4 - Measurement evidence

- [x] Final qualification: `runset-20260918T064148Z-cbb750a373ef`, task PASS.
- [x] Final formal: `runset-20260918T064155Z-610165c750cb`, 10/10 eligible PASS
  repetitions, each with correctness and resource evidence from that repetition.
- [x] Warmup: 42 independent objects, 501,867,060 ns, both minima satisfied.
- [x] Selected PIPELINE duration: 1,000,191,680 to 1,009,790,720 ns; every repetition
  >=1 s. Native encode/decode observations are positive and within pipeline timing.
- [x] Native API CLOCK_MONOTONIC timing includes all intrinsic single-call encode
  allocation/finish; explicit decoder init/end and prechecks are excluded only from
  auxiliary native timing. Zero-byte Finalize does not increase native encode time.
  Pipeline includes Python container/accounting and lifecycle. Scope minima do not
  imply a separate one-second minimum for each native encode/decode observation.

## Layer 5 - Statistics and report

- [x] One dataset summary, ten eligible raw repetitions, no exclusions.
  SizeRatio about 0.40699867; CompressionFactor about 2.45701049.
- [x] PIPELINE encode/decode about 5.03/56.03 MB/s; auxiliary NATIVE about
  5.43/74.65 MB/s, explicitly scope-separated and not lzbench-equivalent.
- [x] Report ID:
  `v2:report:sha256:049f6e8ecd3d53b640c8253fa2e6744119b28dbefd7dda900ce03861e804644e`.
  Report: `runs/runset-20260918T064155Z-610165c750cb/report/report.html`.
- [x] All source/build/config/test/admission/runtime/report artifacts are in the
  canonical project, preserving previous DEFLATE integration changes.

## Build identities and limitations

Release `.so`: `8676b8a44671f5f80a8e8828f55cadb26cb21d9cba6d39a4ae83b6e03e5822c8`.  
ASan/UBSan `.so`: `492a6d6947e54ab598203577974c6f72afe6cb22ca2e3a0cee2bf89645e2124a`.  
Formal combined Python/native support artifact:
`e41049f9f6a19cc2ada7297fb50856780f6354f33a4f9c6f3f05b5a1f8af549d`.

Full dependency configuration, translation-unit commands, static archive hash and
shim compile/link command are persisted in each profile's compile-command.json.
Generic scalar decoder copies, no specialized CRC dispatch/SIMD matching, and no
vendor CLI/MT build. XZ_SANDBOX=no does not disable framework worker isolation.

Historical qualification runsets `runset-20260918T063736Z-dcc43055efe4` and
`runset-20260918T064031Z-dcc43055efe4`, and formal
`runset-20260918T063832Z-89e061ca0ff4`, contain SCHEMA_ERROR for an inherited
window_bits sweep. They remain append-only diagnostic evidence, not successful
admission runs. The command envelope's PASS was insufficient; raw task eligibility
was inspected, the config corrected, and regression coverage added before admission.

lzbench's MT stream API/concat-ignore-check decoder is deliberately not transplanted.
This qualification covers the default VALUE national_illness path, not formal speed
coverage of every track/dataset/preset. Query/random access, raw/.lzma, BCJ/delta,
EXTREME, external dictionaries and multithreading remain unregistered. LeakSanitizer
is disabled under host ptrace policy; ASan/UBSan remain enabled. The shared source
repositories remain clean.
