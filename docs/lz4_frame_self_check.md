# LZ4 Frame five-layer integration self-check

Date: 2026-09-17  
Scope: first spreadsheet-listed native codec only (`lz4-frame`)  
Environment: `CompressBench14`

## Source and scope gate

- [x] Reread the master plan before implementation and selected its prescribed first
  Batch-1 codec.
- [x] Reread the expanded edge-case standard for output-bound, Finalize, accounting,
  correctness, repetition, and reporting details.
- [x] Used the benchmark-vendored implementation, not a fresh website download.
- [x] Pinned lzbench commit
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3` and kept the shared checkout unchanged.
- [x] Copied only the reviewed LZ4 1.10.0 build closure and license notices.
- [x] Recorded source artifact, build closure, license, tests, build hashes, limitations,
  and unsupported reason codes in the registry.
- [x] Compared against the available local upstream LZ4 checkout without changing the
  selected execution authority.

## Layer-by-layer gate

### Layer 1 — Data

- [x] `national_illness` is loaded through the existing manifest/canonical pipeline.
- [x] Its heterogeneous seven-column Value object remains ordered and typed; the codec
  receives serialized buffer bytes and does not sort, cast, fill, interpolate, or drop.
- [x] Canonical raw bits remain the denominator and are distinct from physical file size.

### Layer 2 — Capability and planning

- [x] `lz4-frame` has a reviewed P1 standalone-codec manifest and immutable
  SourceArtifactID.
- [x] Track, topology, dtype, rank, layout, validity, parameters, execution backend, and
  unsupported features are explicit.
- [x] Native artifact resolution is hashed into the execution path; a missing shared
  library maps to `BUILD_UNAVAILABLE / EXECUTION_ARTIFACT_MISSING`.
- [x] No streaming/query/random-access capability is inferred from the library name.

### Layer 3 — Execution and validation

- [x] C ABI lifecycle is `bound -> update -> finalize -> accounting -> independent
  decode -> close` with a new context per independent object.
- [x] `LZ4F_compressEnd` is mandatory and repeated Finalize is rejected.
- [x] Output capacity is never counted as compressed size; exact used bytes are returned.
- [x] The descriptor prefix and one complete LZ4 frame are sufficient for independent
  multi-buffer reconstruction.
- [x] Integer/IEEE bytes round-trip exactly, including signed zero, infinity, and NaN
  payloads exercised by adapter tests.
- [x] Framework boundary suite passed 49/49 cases.
- [x] Native smoke passed N = 0, 1, 2, 65535, 65536, 65537, 131073 for release and
  ASan/UBSan builds; repeated Finalize was included.
- [x] Vendored upstream `frametest` completed basic tests and 100 deterministic fuzz
  cases with seed 20260917.

### Layer 4 — Formal measurement

- [x] Profile is `FORMAL`, timing scope is `PIPELINE`, resource scope is `PROCESS`, and
  Python FFI/container work is included.
- [x] Single-thread scalar CPU execution, independent-object iteration, reset per
  repetition, and no fallback are recorded.
- [x] Warmup satisfies at least 3 iterations and 0.5 seconds.
- [x] All 10 raw repetitions contain at least one second of selected-scope work and the
  same correctness/accounting/resource lifecycle.
- [x] Run set: `runset-20260917T062158Z-06b907ea7d66`.

### Layer 5 — Statistics and reporting

- [x] 10/10 repetitions are PASS and eligible; no repetition was spliced or selected by
  fastest-only timing.
- [x] Every repetition reports 432,768 canonical raw bits, 280,672 final physical bits,
  compression factor 1.5418994413407821 and size ratio 0.6485507246376812.
- [x] Summary reports approximately 78.25 MB/s micro encode throughput and 313.58 MB/s
  micro decode throughput for this recorded machine/path.
- [x] Coverage is PASS 10/10 with no failed, unsupported, OOM, or timeout task.
- [x] Report ID:
  `v2:report:sha256:d2a11069755ecfbcee0e1471c74dc66bbe9693f1b3218ef664f0646ec0867888`.
- [x] Raw JSONL/CSV evidence, eligibility, comparability, coverage, summary, and HTML
  report were generated from the frozen run set.

## Verification result and limitations

The first algorithm satisfies the project definition of “integrated”: source provenance,
build, licensing, registry, negotiation, preflight, correctness, exact accounting,
formal measurement, statistics, coverage, and report generation all close across Layers
1–5. The full Python suite passes 53 tests and Ruff reports no violations.

This result qualifies only the recorded LZ4 Frame execution path. lzbench's codec table
benchmarks the raw LZ4 block API, whereas the same benchmark tree vendors the frame
implementation required by this project's plan. The current adapter uses one update per
independent object, has no dictionary, and makes no streaming/query claim. ASan/UBSan
passed; LeakSanitizer could not run under the host ptrace policy and was explicitly
disabled rather than reported as covered.
