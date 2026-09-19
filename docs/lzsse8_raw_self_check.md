# LZSSE8 Optimal Parse source integration self-check

Date: 2026-09-18. Environment: `CompressBench14` (Python3.14).
Canonical destination: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`.
Registered codec: `lzsse8-raw`, level12, x64 SSE4.1, single thread.

## Design and source admission

The master plan source-admission SOP, Layers1-5, timing/accounting and definition
of done were rechecked. The expanded ODT resolved raw-storage, empty/finalized
objects, bit-first side information, independent-object and repetition rules.
Documents are design references, not unrelated execution authority.

- [x] Renewed full source/TSBench inventory: 72 repository entries, 71 clean/available,
  221 logical entries, 145830 non-generated files. Retained full scan:
  `build/source-audits/lzsse8-onboarding-20260918.json`.
- [x] Read LZSSE8 actual implementation/API/platform/license/README and lzbench
  init/compress/decompress/function-table entries. Pinned clean benchmark commit:
  `fa871e66b3543a70fd4d060f7c12719343ff4ac3`.
- [x] Copied only five needed original files on demand. BSD-2-Clause notices,
  including the platform author's notice, are preserved. Original collection
  is read-only; vendored files are byte-identical after the final formal run.
  Path+NUL+bytes closure SHA256: `7cec9c0598058e8501aa4a37d0c841b03f2a3a4617f911acdbdbf9709aee6cf2`.
- [x] The original allocator dereferenced malloc failure before checking it.
  A build-time patch also replaces unaligned scalar accesses with memcpy and
  clamps safe-end pointer formation. Parser/format are not rewritten; vendor
  bytes remain unchanged. Patch SHA256: `f0ab56c80d3d2c807b7636c0134b2c1593827ca9af68b715ab8c71925f0a8c49`.
- [x] Release/O3 and debug ASan/UBSan/O1 builds retain commands, compiler and hashes;
  generated translation-unit and patch hashes are verified by the final auditor.
  `registry/onboarding/lzsse8-raw.json` retains real evidence, not placeholder PASS.
- [x] The explicit user LZSSE8 request is a scoped spreadsheet-selection exception.
  It is NOT the alexkazik LZSS spreadsheet row. Original LZSS remains independent;
  unfinished LZSSE2 and all prior algorithms/user changes are preserved.

## Layer 1 - Data preparation

- [x] Reused Python dataset registry, canonical loader and characterization.
  VALUE national_illness retains all 966 rows and seven heterogeneous channels
  (two float64, five int64), with canonical denominator 432768 bits.
- [x] No implicit sorting/casting/filling/column selection or timestamp compression
  in the VALUE input. Shape/dtype/channel/order/IEEE payload hashes are preserved.
  TIMESTAMP and VALUE framework boundary suites are both tested.

## Layer 2 - Configuration and fairness

- [x] Separate codec/source/adapter identities, factory, build recipe and closed
  parameter schema. Optimal Parse level12 is a registered preset, not a tuned
  winner. Levels1/17, Fast, SCALAR and checksum are not silently substituted.
- [x] P1 lossless full-matrix byte-view codec; independent complete object state.
  No validity/SYSTEM/continuous streaming/query/random-access claim is made.
  block_size controls boundary fixtures, not an unrecorded segmentation stage.
- [x] CPU SSE4.1 capability now maps to `sse4_1`; missing ISA stays ISA_UNSUPPORTED
  without fallback. Tests distinguish all semantic/execution/resource keys.
  Instrumentation on/off changes execution/resource identity, not logical semantics.
- [x] Default parameters are expanded into ConfigID; invalid points remain errors.
  Registry verification: 12 codecs, 80 source artifacts, one alias; original 221
  spreadsheet logical entries remain unchanged.
- [x] Exact length/shape/dtype/name/Track descriptors and explicit raw-storage flag
  are serialized inside the unique versioned LZSSE8 container. No free decoding
  dependency is hidden. Vendor raw mode is intrinsic, not another-codec fallback.

## Layer 3 - Execution, safety and accounting

- [x] Source optimal state is allocated/freed for each object, with bound max(1,n),
  exactly one update, mandatory zero-byte Finalize, accounting and independent
  decoding. Extra empty capacity is not serialized. Reset clears native timers
  and lifecycle state; repeated Finalize is rejected.
- [x] Independent structural walker checks controls, carried lengths, differential
  offsets, exact tail and every unconditional SIMD16-byte load/store before vendor
  entry. No external overread padding, overlap or unauthorized tail read is allowed.
- [x] Release and ASan/UBSan pass 180 exact-buffer roundtrips each, with bound-1,
  guard pages, canaries, immutability, truncated tails, reset/timing, and 2048 hostile
  streams each. Forced first/second malloc failures and null free pass both profiles.
- [x] 44 cases match encode bytes and direct decode against unmodified original
  source. Python tests additionally decode the format with an independent scalar
  oracle, covering random bytes and signed zero/Inf/subnormal/NaN payloads.
  No dedicated upstream LZSSE test suite exists locally; project suites are not
  mislabeled as absent upstream tests. LSan is disabled; alignment UBSan is enabled.
- [x] Final ledger: 96 container + 6192 descriptors
  + 253888 opaque VALUE stream = 260176 bits =
  32522 physical bytes. Raw denominator is 432768 bits.
  External side information/dictionary/model/index/checksum are zero.
  Opaque nibble controls and internal literal tail are already inside VALUE stream
  bytes; no separately claimed zero excludes them from FinalBits.
- [x] Native format has no checksum; structurally valid corruption can decode.
  Common bit-exact benchmark correctness still checks against original input.
  Formal raw block count: 0; raw storage bytes:
  0. Raw mode is also exercised in short/random fixtures.

## Layer 4 - Authoritative formal measurement

- [x] Qualification: `runset-20260918T083609Z-9f8091a88c60`; PASS, zero leaderboard-eligible
  runs. Formal: `runset-20260918T083617Z-3f7abca84f5d`; 49/49 preflight observations, 10/10 complete
  eligible PASS repetitions with identical encoded object hashes.
- [x] Warmup: 94 independent objects,
  504921315 ns. Every selected PIPELINE repeat >=1s;
  observed range 1000028554..1004375993 ns.
  No own build/test/native sessions overlapped this final measurement.
- [x] CLOCK_MONOTONIC wraps actual source CompressOptimalParse and Decompress,
  including zero-length API calls. State allocation/free, explicit validation,
  Python/FFI/copies/descriptors are outside NATIVE but inside declared CORE/PIPELINE.
  One-shot Finalize adds no native API time. Native <= CORE <= PIPELINE was verified
  from the same inner iterations, not a second speed loop; missing data stays null.
- [x] Fixed CPU0 is a logical P-core (HT sibling1, max4.6GHz; E-cores max3.3GHz),
  verified through topology/frequency evidence, not a claimed speed calibration.
  Evidence: `build/source-audits/lzsse8-cpu-affinity-20260918.json`.
  Governor is powersave; sibling/background tasks are not reserved. Environment,
  resource/eligibility evidence and machine-specific affinity remain explicit.
- [x] Full regression: 360 PASS; Ruff PASS. Finalization/reset/disabled/old-library/
  timing query/error/default equivalence are covered by shared and adapter tests.

## Layer 5 - Statistics and reporting

- [x] Formal report includes ten eligible records and one summary, with the framework's
  robust statistics/CI/coverage; qualification report has no formal summary.
  SizeRatio: 0.60119047619047619; CompressionFactor: 1.6633663366336634.
  Selected PIPELINE encode/decode about 11.07/201.32 MB/s on this one dataset/profile,
  not pure-kernel lzbench speeds or cross-codec speed claims.
- [x] Report: `runs/runset-20260918T083617Z-3f7abca84f5d/report/report.html`.
  ReportID: `v2:report:sha256:cea882cea1a0ad956a543d8f5062d62ea9ba38d3baee77661356cf720f655414`.
- [x] Auditor: `tools/audit_lzsse8_run.py`. Machine evidence:
  `build/source-audits/lzsse8-final-audit-20260918.json`; checks ten raw records,
  real streams/raw-mode flag, warmup, gates, accounting, build/source/patch/log hashes
  and report admission, independently of the CLI status envelope.
- [x] Stage self-check found a pre-existing explicit-affinity resume defect: typed
  tuple vs frozen JSON list. BenchmarkProfile.as_document now emits JSON arrays;
  real resume/report/append-only tests pass without changing ProfileID or ConfigID.
  Earlier runsets `runset-20260918T083232Z-9f8091a88c60` and
  `runset-20260918T083247Z-3f7abca84f5d` remain intact, not overwritten.
- [x] All implementation, vendor, patches, registries, configs, tests, docs, build,
  runs and reports are in the user's canonical project, not only the Codex worktree.

Qualification scope is this fixed Optimal Parse variant on the tested execution path.
Formal dataset coverage is VALUE national_illness only; TIMESTAMP boundary coverage
is not a formal speed measurement. Optimal parser state is memory-heavy, limited
to INT32_MAX decoded bytes and actual worker memory; theoretical size support is
not a promise that huge inputs fit physical RAM. No Fast or LZSSE2 admission is implied.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py lzsse8-raw --profile all
conda run -n CompressBench14 python tools/qualify_lzsse8.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzsse8-raw-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/lzsse8-raw-formal.toml --output-root runs \
  --run-set-id runset-20260918T083617Z-3f7abca84f5d --resume
PYTHONPATH=src conda run -n CompressBench14 python tools/audit_lzsse8_run.py \
  runset-20260918T083617Z-3f7abca84f5d runset-20260918T083609Z-9f8091a88c60
```

Review CPU affinity on a different machine. Rebuilding release/source/driver after
measurement requires a new run set; do not reuse frozen evidence with altered binaries.
