# Changelog

All notable changes to the Time Series Compression Benchmark V2 project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Phase 0-3 Complete (2026-09-16)

Project foundation established with five-layer architecture fully implemented and tested.

#### Added

**Infrastructure & Architecture**
- Five-layer benchmark architecture (Data → Capability → Execution → Performance → Statistics)
- 25 JSON Schema v2 files defining all contracts
- Canonical JSON normalization and deterministic ID generation via SHA-256
- Append-only result storage (runs.csv, JSONL)
- Git repository initialization with structured directory layout

**Data Layer (Layer 1)**
- 13 dataset manifests with SHA-256 verification
- CSV/NPZ loaders with canonical binary stream generation
- Dataset characterization (exact vs sampled metrics)
- PEMS native 3D shape preservation
- Weather header encoding handling
- National illness heterogeneous dtype preservation
- Synthetic test fixtures

**Capability Layer (Layer 2)**
- 72 source code repository catalog
- Four-state codec negotiation (DIRECT/ADAPTER_LOSSLESS/ADAPTER_LOSSY/UNSUPPORTED)
- Codec/source registry system
- CompatibilityPlan with explicit adapter disclosure
- Parameter sweep expansion and ConfigID generation
- ExecutionPathHash binding (artifact, adapter, environment, ISA, threads, affinity)

**Execution Layer (Layer 3)**
- Track routing (Timestamp/Value/SYSTEM) with independent accounting
- Oracle adapters (identity/corrupt/timeout/OOM/nondeterministic)
- Boundary/safety preflight gates
- FinalBits accounting at physical stream boundaries
- Isolated codec lifecycle with timeout/memory limits/CPU affinity
- Worker process protocol with fork/spawn support
- Lossless correctness validation (integer exactness, IEEE byte equality)
- Lossy correctness gates (error-bounded validation)

**Performance Layer (Layer 4)**
- Formal profiling protocol (≥3 warmups, ≥0.5s, ≥10 repetitions)
- CORE/PIPELINE/E2E timing scope separation
- Resource measurement (CPU user/system/total, memory RSS/PSS/USS, I/O, faults, context switches)
- Query workload matrix generation
- Qualification vs formal profile distinction

**Statistics Layer (Layer 5)**
- Eligibility tracking with explicit reason codes
- Summary aggregation (median, P25/P75, mean, SD, CV, bootstrap intervals)
- Per-dataset and corpus-level metrics
- Coverage reporting (partial/failed/unsupported/OOM/timeout)
- Comparability key expansion (semantic/execution/resource contexts)

**Testing**
- 44 test cases covering all layers (100% pass rate)
- 7 contract tests (JSON Schema, dataset manifests, codec registry)
- 8 data layer tests (canonical JSON, PEMS shape, weather encoding)
- 2 capability layer tests (negotiation, sweep expansion)
- 12 execution layer tests (track routing, oracle finalization, boundary suite)
- 5 performance layer tests (formal profiling, query matrix)
- 2 storage layer tests (append idempotency)
- 8 integration tests (layer 1-3 pipelines, runner resume)

**Documentation**
- Comprehensive README.md with five-layer invariants
- Master implementation plan (1,506 lines, Phase 0-10 roadmap)
- Native C ABI header files for future codec integration

#### Fixed
- Python 2 to Python 3 syntax migration (6 exception handling clauses)
  - `src/tscompbench/execution/isolation.py:31`
  - `src/tscompbench/measurement/resources.py:18,33,44,56,76`

#### Implementation Details

**Key Design Decisions Validated**
1. Semantic→Execution→Resource hierarchical keys enforced
2. Temporal Fidelity as SHOULD, not universal gate
3. Track family orthogonal subdivision (no leakage)
4. Layer 3/4 share same Formal Repetition lifecycle

**Constraint Compliance (§2 of Master Plan)**
- ✅ No hidden data transforms (sorting/interpolation/filling)
- ✅ T/V independent modeling, billing, validation
- ✅ Canonical vs physical separation
- ✅ Boundary suite covers capacity and special values
- ✅ FinalBits = Serialized + External
- ✅ Physical stream boundary closes exactly once
- ✅ runs.csv per-repetition, summary.csv only same-path PASS

**Code Metrics**
- ~9,936 lines of Python source code (55 files)
- 25 JSON Schema files
- 20 registry files (13 datasets + sources + codecs)

### Pending

**Phase 4-10 Implementation**
- Phase 4 follow-on: remaining spreadsheet-listed native codec batches after the
  completed LZ4 Frame, Zstd Frame, Snappy Raw, and Brotli Stream Batch 1
- Phase 5: Timestamp primitives (Delta/DoubleDelta/ZigZag/StreamVByte)
- Phase 6: Value UTS/MTS codecs (Gorilla/Chimp/ALP/Sprintz)
- Phase 7: Lossy/ND algorithms (Serf/SZ3/zfp)
- Phase 8: SYSTEM benchmarks (Prometheus/TsFile/streaming)
- Phase 9: Learned/Hardware codecs (NeaTS/GPU/FPGA)
- Phase 10: Statistics layer completion and publication

**Known Limitations**
- Four real codec adapters are currently integrated; the remaining spreadsheet-listed
  algorithms have not yet been onboarded.
- LZ4 and Zstd currently use one finalized frame per independent object and do not claim
  streaming/query support. Zstd dictionary and multithread modes are not registered.
- LeakSanitizer is unavailable under the host ptrace policy; ASan/UBSan ran with leak
  detection disabled.

### Phase 4 First Native Codec (2026-09-17)

#### Added

- Pinned lzbench-vendored LZ4 1.10.0 source closure with BSD license notices and source
  artifact/onboarding records.
- Stable C ABI shim and Python ctypes driver for mandatory LZ4 Frame finalization,
  independent decode, exact used-length reporting, and structured status errors.
- Versioned self-contained descriptor container preserving routed buffer order, dtype,
  shape, and IEEE payload bytes.
- Release and ASan/UBSan build profiles, native ABI smoke test, qualification/formal
  experiment configurations, and source-onboarding contract tests.
- First complete real-codec Layer 1-5 evidence: 10/10 FORMAL repetitions eligible,
  49/49 boundary checks, and deterministic report generation.

#### Changed

- Runtime adapter selection now resolves registered native codec factories instead of
  being limited to Batch-0 oracles.
- Missing native artifacts produce the explicit `BUILD_UNAVAILABLE /
  EXECUTION_ARTIFACT_MISSING` planning result.
- Conservative compression bounds may use less than their declared capacity; the
  boundary validator no longer treats safe `bound - 1` success as a contract failure.
- Test suite now contains 53 passing tests.

### Phase 4 Second Native Codec (2026-09-17)

#### Added

- Pinned lzbench-vendored Zstd 1.5.7 single-thread source closure with BSD/GPL license
  notices and immutable source artifact/onboarding evidence.
- Scalar, single-thread, dictionary-free Zstd C ABI adapter with explicit pledged input
  size and mandatory `ZSTD_e_end` loop until the frame is complete.
- Python ctypes driver, self-contained descriptor container, exact Zstd frame/block/
  checksum accounting, independent streaming decode, and adapter factory registration.
- Release and ASan/UBSan builds, native boundary smoke, fixed-seed upstream fuzzer run,
  qualification config, and direct LZ4/Zstd formal comparison config.
- Five-layer Zstd evidence: 49/49 boundary cases and 10/10 eligible FORMAL repetitions.

#### Changed

- Zstd disables assembly, BMI2 runtime dispatch, legacy decode, dictionaries, and worker
  threads in the registered scalar execution variant; other modes require new variants.
- Common byte-frame manifests use algorithm-neutral decodability, frame, and tail labels,
  allowing LZ4 and Zstd to share valid Semantic/Execution/Resource comparison keys while
  retaining distinct artifact and execution-path identities.
- Test suite now contains 57 passing tests.

### Phase 4 Third Native Codec (2026-09-17)

#### Added

- Pinned lzbench-vendored Snappy source closure matching the benchmark's three compiled
  translation units, with BSD license, format description, source artifact, and admission
  records.
- Scalar C++ adapter behind the stable C ABI using `RawCompress`, `RawUncompress`, and
  `MaxCompressedLength`, with exact decoded-length enforcement and exception containment.
- Versioned descriptor container followed by one Snappy raw stream, required zero-byte
  one-shot Finalize, independent decode, and exact literal/copy structural accounting.
- Release and ASan/UBSan builds, ABI boundary smoke, 100-case deterministic upstream
  fuzzer harness, qualification/formal configs, raw-stream parser tests, and fairness-key
  regression coverage.

#### Changed

- Snappy is registered as `snappy-raw`, not a frame: it has no native framing layer,
  footer, checksum, or dictionary and remains in a separate comparability group from
  LZ4/Zstd Frame.
- Codec registry now contains seven manifests and source registry contains the additional
  immutable Snappy closure.

### Phase 4 Fourth Native Codec (2026-09-18)

#### Added

- Pinned lzbench-vendored Brotli 1.2.0 common/encoder/decoder closure, MIT license,
  source artifact, and admission record.
- C ABI adapter using PROCESS plus FINISH-until-complete, independent decode, native API
  timing, exact used-length accounting, and a versioned descriptor container.
- Release and ASan/UBSan builds, ABI boundary smoke, 100-case deterministic vendor API
  harness, qualification/formal configs, 49-case boundary coverage, and fairness tests.
- Five-layer evidence with 10/10 eligible FORMAL repetitions and a deterministic report.

#### Changed

- Brotli's RFC 7932 stream, built-in static dictionary, and finalize semantics place it
  in a separate comparability group from LZ4/Zstd frames and Snappy raw.
- Codec registry now contains eight manifests.

## [0.0.0] - 2026-09-16

### Added
- Initial project structure
- Phase 0-3 implementation complete per master plan
- Git repository initialization (commit f4fa055)

---

**Legend:**
- Phase 0: Repository & decision baseline
- Phase 1: Contracts, ID, storage, oracle loop
- Phase 2: Data layer
- Phase 3: Registry, negotiation, execution isolation
- Phase 4-10: Algorithm batches & statistics (pending)
