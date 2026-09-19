# LZSS native-source five-layer self-check

Date: 2026-09-18  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`  
Codec: `lzss-raw`, original Rust LZSS 0.9.1 through project C ABI

## Source admission and implementation decision

The master plan sections 3.2, 7.2, 12.2, 18.1 and 20.3 require identifying the
actual source, retaining its implementation language, independent validation,
and completing all five layers. The expanded ODT's bit-first accounting,
finalize/flush, independent-object and warmup/repetition contracts were checked
when interpreting the headerless one-shot API.

Spreadsheet-listed `Value-Compress` row 3 maps LZSS to `alexkazik/lzss`, confirmed
by the local logical metadata. Workbook provenance SHA256:
`012cc79f9855f839100fcc3e81449e8dc1dd80d7c175b2b90d1b8d1e07f3be23`.
The analysis document's previous claim of an independent matching lzbench LZSS
entry was not supported by source review. Its LZSSE2/4/8 implementations are
different wire formats, not substitutes for the specified Okumura-style LZSS.
They remain separate, unfinished user files and were not changed by this work.

- [x] Re-scanned the complete local source collection: 72 repository entries,
  71 available/clean, 221 logical entries and 145,830 non-generated files.
  Retained `build/source-audits/lzss-onboarding-20260918.json`.
- [x] Reviewed original compressor/decompressor, MSB-first bit reader/writer,
  safe slice writers, generic build generator/API, benchmark and upstream tests.
  Original source commit: `512b9163d8a936003c925e24f7f682eeaeda8307`.
- [x] Copied only the library/build/tests/benchmark, documentation/license/lock
  closure on demand. The shared source checkout remains clean, and all copied
  original files were compared byte-for-byte after the final run.
- [x] `adapters/lzss_raw/vendor` contains 34 unmodified source/reference files.
  Closure SHA256: `82cb61ecc9d31fd48a31624fd2b45f310fcf641d5fcd8e2dcca11d361feced2c`.
  Digest uses sorted relative POSIX path UTF-8 + NUL + complete file bytes.
- [x] `void` 1.0.2 archive SHA256 matches the original Cargo.lock exactly:
  `6a02e4885ed3bc0f2de90ea6dd45ebcbb66dacffe03547fadbb0eeae2770887d`.
  Acquisition: `https://static.crates.io/crates/void/void-1.0.2.crate`.
  Runtime builds are offline; no Cargo registry/system/pip codec substitution.
- [x] MIT local execution is allowed. LZSS's original license is preserved.
  The void archive declares MIT in Cargo.toml/README but lacks full license text;
  redistribution remains explicitly review-required, not unconditionally approved.

## Layer 1 - Data preparation

- [x] Existing dataset manifest/loader/characterizer is reused without hidden
  cast, sorting, timestamp construction, fill, flatten or column selection.
- [x] Formal VALUE `national_illness` retains 966 rows, all seven heterogeneous
  channels and canonical denominator 432,768 bits. Timestamp data is not encoded
  in the VALUE input. Both TIMESTAMP and VALUE boundary suites pass.
- [x] Frozen canonical/input hashes and full descriptors remain traceable from
  the task plan, raw records and report; original dataset/source files are read-only.

## Layer 2 - Identity, capability and fairness

- [x] Separate AlgorithmID/SourceArtifactID/AdapterID and registered factory:
  `registry/codecs/lzss-raw.json`, `registry/sources/lzss-alexkazik.artifact.json`,
  `registry/onboarding/lzss-raw.json`.
- [x] Actual native algorithm remains Rust, as the plan explicitly permits.
  C++ only supplies the common ABI/safety/timing shim; Python supplies all
  negotiation, standard enforcement, planning, validation and reporting.
  No C/C++ rewrite or LZSSE qualification is claimed.
- [x] Fixed generic EI=10/EJ=4/C=0x20 matches benchmark parameters; stack work
  buffers and safe/std/alloc features are explicit. Alternate parameters are
  rejected. Single thread, scalar/no dispatch, no fallback/external dictionary.
- [x] P1 standalone lossless byte-view codec: one stream per routed object,
  all MTS buffers, exact dtype/shape/channel/IEEE bits, no validity support.
  SYSTEM, query, random access and continuous streaming are unregistered.
- [x] The fixed variant is identified by container version and manifest. Shape,
  dtype, buffer lengths/names and segment metadata are serialized, not external
  free side information. The fixed 0x20 initial window is public format knowledge,
  not a trained/external dictionary.
- [x] All defaults enter ConfigID. Invalid parameter points are retained with
  SCHEMA_ERROR. Comparison-key tests distinguish this lifecycle/format from the
  other six native codec formats; instrumentation on/off splits execution/resource
  keys, not semantic keys. The registry now has 11 codecs, 79 sources and one alias.
- [x] `block_size` is the framework boundary-fixture parameter, not an implicit
  segmentation stage or an adjustable LZSS window.

## Layer 3 - Execution, safety and accounting

- [x] Lifecycle: worst-case bound -> one source compress_stack including native
  BitWriter.flush -> mandatory zero-byte Finalize -> accounting -> independently
  created exact decoder -> common correctness -> teardown.
  Repeated update/finalize and finalize-before-update are rejected; ABI reset
  clears state/timing and preserves instrumentation enablement.
- [x] Bound is `n + ceil(n/8)`: literals cost nine bits per byte; references cost
  fifteen bits for at least two bytes. Only actual written bytes are charged.
  Empty/tiny, window/tail/block boundaries, random/expansion, IEEE NaN payloads,
  signed zero/Inf/subnormal, integer/timestamp extremes and layouts are covered.
- [x] Upstream EOF tolerance is not copied as the project contract. Python and
  native validators independently inspect token coverage, exact decoded length
  and 0..7 zero padding bits. Truncated tokens, extra/concatenated bytes, nonzero
  tail padding and inconsistent descriptors/capacity are rejected.
- [x] Rust uses safe upstream code and bounded writers; the ABI enforces output
  descriptors, no input/output overlap and limits. catch_unwind prevents Rust
  panics crossing FFI and invalidates incomplete timing. Input immutability,
  output canaries, determinism, independent oracle and upstream golden bytes pass.
- [x] Original release suites include all ignored generic/dynamic tests and
  seven doctests: 30 tests pass. ASan library/in-place suites: 14 tests pass.
  Native ABI qualification passes 39 cases per profile. Reproduction/log:
  `tools/qualify_lzss.py`, `build/source-audits/lzss-native-tests-20260918.log`.
- [x] Rust codec/FFI are ASan-instrumented with pinned host rustc 1.94.0,
  RUSTC_BOOTSTRAP=1/-Zsanitizer=address; C++ ABI is ASan/UBSan-instrumented.
  Prebuilt Rust std is not instrumented; LeakSanitizer is disabled under host
  ptrace restrictions. These limitations are explicit, not full-stack claims.
- [x] Final physical accounting: 96 container + 6,048 descriptor metadata +
  252,024 VALUE token bits + 0 tail padding = 258,168 bits = 32,271 bytes.
  External side information, dictionary/model/index/checksum bits are zero.
  Nonzero tail padding is separately charged in fixtures, with one final rounding.
  No checksum means arbitrary structurally valid payload changes are not always
  detectable by the codec; benchmark common correctness still checks original bits.

## Layer 4 - Authoritative raw measurement

- [x] Final qualification: `runset-20260918T074915Z-9c95a77d4d12`; task PASS,
  qualification remains ineligible for formal performance ranking.
- [x] Authoritative formal: `runset-20260918T074940Z-f8855e7299f1`; 49/49 preflight
  observations and ten distinct complete eligible PASS repetitions.
  All local build/upstream/regression sessions finished before formal measurement.
- [x] Warmup: nine independent objects, 527,203,621 ns; both minima satisfied.
  Selected PIPELINE range: 1,001,130,462..1,055,143,819 ns; every repeat >=1 second.
  Correctness, accounting, resources and timing are from each same repetition.
- [x] API-only CLOCK_MONOTONIC timing surrounds original compress_stack and
  decompress_stack inside the Rust bridge, excluding bridge slice preparation,
  catch/error handling, explicit validators, lifecycle and Python container work.
  Source-internal buffer initialization and bit flush are included. Instrumentation
  and clock-bridge overhead still exist; NATIVE is auxiliary, not the selected scope.
- [x] Default/disabled bitstream equivalence, native <= CORE <= PIPELINE,
  accumulation, repeated queries, zero-byte finalize, reset/close and precheck
  rejection are covered by shared/native tests. Missing clocks remain null.
- [x] The first qualification/formal runsets remain append-only evidence.
  `runset-20260918T074546Z-f8855e7299f1` measured the earlier bridge-inclusive
  native interval and is superseded by the authoritative final run, not deleted.

## Layer 5 - Statistics, report and scope

- [x] One dataset summary, ten eligible repetitions, no formal exclusions.
  Qualification report has zero eligible runs and no formal summaries.
- [x] Final SizeRatio about 0.59655058; CompressionFactor about 1.67630380.
  Selected PIPELINE encode/decode about 1.60/2.15 MB/s. Python's exact token
  inspection/accounting is included; these are not lzbench or Criterion timings.
- [x] Final report:
  `runs/runset-20260918T074940Z-f8855e7299f1/report/report.html`.
  ReportID: `v2:report:sha256:fa7d1c5f244fec21f90a767f0e53bda9a071df70f3bc286196a3829745e96954`.
  Full machine self-check: `build/source-audits/lzss-final-audit-20260918.json`.
- [x] Release SHA256: `95a6d962a98cf03960f44e8b3afa50fbf5b939909c13c7d2beea5836a7dc1fc0`.
  Sanitizer SHA256: `a6657b73c4a7feaf04c8e408c4fecf0aba09a6770c45f1d0416d40686bb39fbc`.
  Combined native/Python support SHA256:
  `b1dcea6e3e7f69f907fb57618a89176dc8e43e78be92da3212bb7e5b4f8913ea`.
- [x] Full regression: 298 PASS; Ruff PASS; automated five-layer qualification
  verifies report filtering, stable reports and append-only resume.
  All implementation/config/source/card/test/doc/build/run/report files exist in
  the canonical project, not only the Codex worktree. Unrelated changes are preserved.

Formal performance coverage is default VALUE national_illness only; TIMESTAMP
boundary coverage is not a formal speed result. Qualification applies to this
fixed original Rust variant, not every LZSS family member or future C/C++ rewrite.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py lzss-raw --profile all
conda run -n CompressBench14 python tools/qualify_lzss.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzss-raw-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzss-raw-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/lzss-raw-formal.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume
```
