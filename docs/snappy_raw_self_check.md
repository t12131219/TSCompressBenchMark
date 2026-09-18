# Snappy raw five-layer integration self-check

Date: 2026-09-17  
Scope: third spreadsheet-listed Batch-1 native codec (`snappy-raw`)  
Environment: `CompressBench14`

## Source and admission gate

- [x] Reread the master plan, expanded edge-case standard, and C/C++ algorithm analysis.
- [x] Used Snappy vendored by clean lzbench commit
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`; no network source was substituted.
- [x] Kept lzbench and upstream Google Snappy checkouts clean. Upstream commit
  `26aa88cbb235a35d4604d2dd5f5284566862de77` is comparison evidence only.
- [x] Copied the exact three-translation-unit lzbench closure, dependency headers,
  format description, and BSD license without modifying vendor files.
- [x] Recorded closure digest, immutable SourceArtifactID, scalar build identities,
  license decision, tests, unsupported modes, and version-label discrepancy.

## Layer-by-layer gate

### Layer 1 - Data

- [x] Routed buffers retain their declared order, dtype, shape, logical bits, and raw
  IEEE/integer bytes. No cast, sort, fill, interpolation, or column removal occurs.
- [x] Empty, tiny, 64-KiB boundary, incompressible, signed-zero, infinity, subnormal,
  and NaN-payload cases are exercised by native or framework tests.
- [x] Canonical raw bits, not CSV size or output capacity, remain the denominator.

### Layer 2 - Capability, configuration, and fairness

- [x] Snappy is registered as a P1 lossless byte codec for T1/V0 with a fixed level 1,
  no checksum, no dictionary, scalar CPU, one thread, and no runtime fallback.
- [x] The format is explicitly `snappy-raw`: one raw stream per routed object, not a
  frame. Its Semantic, Execution, and Resource comparison keys differ from LZ4/Zstd
  frame profiles, and a planning regression test freezes that separation.
- [x] Streaming, query, random access, framing, checksum, and dictionary capabilities
  are false or structured unsupported modes rather than inferred features.

### Layer 3 - Lifecycle, correctness, and accounting

- [x] Lifecycle is `bound -> RawCompress -> zero-byte Finalize -> exact accounting ->
  independent RawUncompress -> close`, with a distinct decode handle.
- [x] Input length is rejected above `UINT32_MAX`; compression requires the official
  `MaxCompressedLength` capacity, but only actual written bytes enter FinalBits.
- [x] Decode reads and validates the embedded length, requires exact destination size,
  validates the full stream, and rejects truncation/corruption.
- [x] Structural parsing validates the canonical uint32 varint and every literal/copy
  tag, offset, decoded extent, and trailing byte. Literal bytes are assigned to the
  routed data bucket; prefixes/tags/offsets and the TSCB prefix are container bits.
- [x] Finalize writes zero bytes exactly once; repeated Finalize is rejected.
- [x] Release and ASan/UBSan ABI smoke passes N = 0, 1, 2, 65535, 65536, 65537,
  131073. The lzbench compression fuzzer harness passes 100 deterministic cases.

### Layer 4 - Measurement

- [x] Shared FORMAL profile completed 3 algorithms x 10 raw repetitions; all 30 are PASS
  and performance-eligible. Every selected-scope repetition exceeds one second.
- [x] Each algorithm completed at least 3 warmup iterations and 0.5 seconds, with
  independent-object lifecycle semantics and Python FFI/container work included.
- [x] Final RunSet: `runset-20260917T125955Z-fd44e35213d5`.

### Layer 5 - Statistics and report

- [x] Report contains three complete summaries and 30/30 eligible repetitions.
- [x] Fairness output contains two groups: LZ4/Zstd share frame Semantic/Execution/
  Resource keys, while Snappy raw has separate keys and is not directly ranked with them.
- [x] Snappy reports 293,968 FinalBits, 36,746 physical bytes, SizeRatio
  0.67927388346643005, CompressionFactor 1.4721602351276329, about 25.86 MB/s encode,
  and 239.59 MB/s decode for this recorded pipeline execution path.
- [x] Report ID:
  `v2:report:sha256:ba6edff0215d348f08542bffbdf97cf63a5c9ad4c35e05ac40765ce8b1d57bfb`.

## Current limitations

Snappy's native format is a raw self-delimiting stream, not a checksummed frame, so it is
published in a separate fairness group from LZ4/Zstd Frame even when measurement profiles
match. lzbench labels this source tree 1.2.2 in `CMakeLists.txt` and `NEWS`, but its
checked-in generated `snappy-stubs-public.h` still contains patchlevel 1; this mismatch is
preserved rather than patched. LeakSanitizer remains unavailable under the host ptrace
policy, so sanitizer evidence uses `detect_leaks=0`.
