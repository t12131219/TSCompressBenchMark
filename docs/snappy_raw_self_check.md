# Snappy raw five-layer integration self-check

Historical evidence date: 2026-09-17 (pre-native-timing identity; current refresh below)
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

## Current build evidence refresh — 2026-10-05

The wrapper and manifest gained optional native timing after the original admission.
The release binary was rebuilt but the onboarding card still held the earlier hashes;
the historical runs used AlgorithmID `48368427…`, whereas the current registration uses
`1af7afbe…`. This explains the stale build evidence and zero current-identity rows.
The old runs remain historical evidence and are not relabelled.

- Release rebuild reproduces the current SHA-256 exactly:
  `fa7e16cdb385bb73383aa4ed58ef2868e1c568c6de3b0e62989d96526235d493`.
- ASan/UBSan is rebuilt from the current wrapper:
  `641dfac78a563ccb58e8fadf647377ae4a35e0655f14aaf5fb6b99b30f0fd145`.
- Both current hashes and compile-command digests match their build records and the
  updated onboarding card. The pinned SourceArtifactID and AlgorithmID are unchanged.
- All 10 retained vendor files match the clean pinned lzbench checkout byte for byte.
  The refresh records an explicit sorted path/NUL/content inventory separately from
  the historical source-closure digest, whose serialization was not specified.
- Release and ASan/UBSan C ABI smoke pass all seven length cases; the existing adapter
  suite passes 9 tests and Snappy native timing passes 6 tests. Named fixture IDs allow
  the latter to be selected reliably with `-k snappy_raw`.
- Current qualification `runset-20261005T092712Z-a89763b0308a` passes 1/1, including
  preflight/boundary, correctness, exact accounting and native timing checks.
- Formal attempts retain swap-related `RESOURCE_PRESSURE`. The latest saved attempt,
  `runset-20261005T092726Z-b248fb2d87c3`, has 10/10 correctness PASS and 9 individually
  eligible repetitions, but one swap rejection disqualifies the full group: the report
  has **zero eligible runs and no ranked summary**. No formal performance pass is claimed.

The [refresh report](snappy_raw_evidence_refresh.json) retains commands, output, old
card hashes, current build identities and file/run SHA-256 evidence. Verify synchronization
without rebuilding or rerunning with:

```bash
PYTHONPATH=src conda run -n CompressBench14 python tools/refresh_snappy_evidence.py --verify-card
```

Coverage is Linux CPU scalar/single-thread and `national_illness` VALUE, not all datasets
or parameters. ASan/UBSan were enabled; LeakSanitizer remains disabled. Raw-stream,
framing/checksum/query/streaming restrictions remain as registered.
