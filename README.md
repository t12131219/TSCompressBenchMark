# Time Series Compression Benchmark V2

This repository implements the Python control plane and normative contracts for a
source-driven time-series compression benchmark. Layers 1 through 5 are implemented:
deterministic data preparation now feeds versioned source/codec registries, four-state
capability negotiation, explicit adapter and preprocess plans, parameter expansion,
deterministic task planning, runtime execution-path resolution, and hierarchical
comparability keys. The third layer adds Track-safe routing, input validation,
boundary/safety preflight, isolated codec lifecycles, mandatory Finalize, bit-first
accounting, lossless/lossy correctness gates, append-only raw evidence, and resumable
qualification execution. The fourth layer adds frozen measurement profiles, normative
warmup/repetition/min-duration control, scope-separated timing, process resource
evidence, deterministic query-workload identities, streaming capability gates, and
raw performance fields linked to the same correctness-qualified RunID.
The fifth layer reads only frozen task/raw evidence, records per-analysis exclusion
reasons, aggregates same-path PASS repetitions with robust statistics and deterministic
bootstrap intervals, computes per-dataset then corpus metrics, and publishes nested-key
Pareto/ranking/coverage views plus machine and human-readable reports.

The source collection remains read-only under
`/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code`. Phase 4 copies only the
reviewed translation-unit closure needed by an adapter. The native codecs are LZ4 Frame
1.10.0, Zstd Frame 1.5.7, Snappy Raw 1.2.2, Brotli Stream 1.2.0, zlib DEFLATE
1.3.2 (`deflate-zlib`, RFC1950 wrapper), and XZ LZMA2 5.8.3 (`xz-stream`, single-call), taken from
lzbench's vendored sources at a pinned commit. LZSS 0.9.1 (`lzss-raw`) uses the
spreadsheet's original alexkazik Rust implementation, driven through the same C ABI;
lzbench's different LZSSE formats are not substituted. Michael Dipperstein's native C
offset12/length4 binary-tree implementation is separately registered as
`lzss-dipperstein-c`; it is not a replacement or shared ranking identity. The explicitly requested
LZSSE8 Optimal Parse (`lzsse8-raw`, level 12, SSE4.1) is registered separately,
with immutable lzbench source and a hashed build-time safety patch. Their source, license, build, ABI,
accounting, and five-layer evidence are recorded under `registry/onboarding`.

## Environment

Use the supplied environment:

```bash
PYTHONPATH=src conda run -n CompressBench14 python -m pytest
conda run -n CompressBench14 python tools/generate_sprintz_fixture.py
conda run -n CompressBench14 python tools/build_codec.py sprintz-delta-u8 --profile all
conda run -n CompressBench14 python tools/build_codec.py sprintz-fire-u8 --profile all
conda run -n CompressBench14 python tools/qualify_sprintz_native.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-u8-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-u8-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/sprintz-u8-formal.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume
conda run -n CompressBench14 python tools/generate_sprintz_i16_mts_fixture.py
conda run -n CompressBench14 python tools/build_codec.py sprintz-delta --profile all
conda run -n CompressBench14 python tools/build_codec.py sprintz-fire --profile all
conda run -n CompressBench14 python tools/qualify_sprintz.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/sprintz-formal.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py huff0 --profile all
PYTHONPATH=src conda run -n CompressBench14 python tools/build_codec.py fse --profile all
PYTHONPATH=src conda run -n CompressBench14 python tools/qualify_entropy_fse.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/entropy-fse-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench datasets verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs classify-sources
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench datasets prepare etth1 --output build/data
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run init \
  configs/experiments/data-preparation-smoke.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run plan \
  configs/experiments/capability-configuration-smoke.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/capability-configuration-smoke.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/performance-evaluation-smoke.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/performance-evaluation-smoke.toml --output-root runs \
  --run-set-id <existing-run-set-id> --resume

# Build and qualify the native codecs.
conda run -n CompressBench14 python tools/build_codec.py lz4-frame --profile all
conda run -n CompressBench14 python tools/build_codec.py zstd-frame --profile all
conda run -n CompressBench14 python tools/build_codec.py snappy-raw --profile all
conda run -n CompressBench14 python tools/build_codec.py brotli-stream --profile all
conda run -n CompressBench14 python tools/build_codec.py deflate-zlib --profile all
conda run -n CompressBench14 python adapters/deflate_zlib/tests/run_native_tests.py
conda run -n CompressBench14 python tools/build_codec.py bzip2-stream --profile all
conda run -n CompressBench14 python adapters/bzip2_stream/tests/run_native_tests.py
conda run -n CompressBench14 python tools/build_codec.py xz-stream --profile all
conda run -n CompressBench14 python adapters/xz_stream/tests/run_native_tests.py
conda run -n CompressBench14 python tools/build_codec.py zfp-accuracy-1d --profile all
conda run -n CompressBench14 python adapters/zfp/tests/run_native_tests.py
conda run -n CompressBench14 python tools/build_codec.py lzss-raw --profile all
conda run -n CompressBench14 python tools/qualify_lzss.py
conda run -n CompressBench14 python tools/build_codec.py lzss-dipperstein-c --profile all
conda run -n CompressBench14 python tools/qualify_lzss_dipperstein.py
conda run -n CompressBench14 python tools/build_codec.py lzsse8-raw --profile all
conda run -n CompressBench14 python tools/qualify_lzsse8.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzsse8-raw-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lzsse8-raw-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz4-frame-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/zstd-frame-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/snappy-raw-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/brotli-stream-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/deflate-zlib-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/bzip2-stream-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/xz-stream-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/zfp-accuracy-1d-qualification.toml --output-root runs

ALP and ALP-RD use the audited `cwida/ALP` C++ source closure as two forced, non-overlapping
schemes:

```bash
conda run -n CompressBench14 python tools/build_codec.py alp --profile all
conda run -n CompressBench14 python tools/build_codec.py alp-rd --profile all
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/alp-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/alp-formal.toml --output-root runs
```

Serf-Qt and Serf-XOR use the audited upstream C++ benchmark implementation as separate
lossy AlgorithmIDs. Both accept homogeneous little-endian float32/float64 VALUE UTS and
synchronous MTS, enforce a positive absolute error bound, and fully charge their project
container and native frame. Qt resets at every block; XOR carries adaptive state only
across finite blocks in one column. Non-finite or unsafe-to-quantize blocks use an
explicitly charged raw exception record. The vendored source is CC BY-NC 4.0, so
redistribution and commercial use remain restricted. See the
[Serf admission review](docs/serf_admission_review.md) and
[Serf five-layer self-check](docs/serf_self_check.md).

```bash
conda run -n CompressBench14 python tools/build_codec.py serf-qt --profile all
conda run -n CompressBench14 python tools/build_codec.py serf-xor --profile all
conda run -n CompressBench14 python adapters/serf/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/serf-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/serf-formal.toml --output-root runs
```

NeaTS and LeaTS use the audited `and-gue/NeaTS` C++ source at one pinned commit but
remain separate AlgorithmIDs for nonlinear and linear piecewise models. The admitted
path is lossless signed int8/int16/int32/int64 VALUE UTS or synchronous MTS, scalar,
single-threaded and column-independent. Model fitting happens inside every compression;
there is no external checkpoint or training split, and all serialized model/index bytes
are charged. See the [NeaTS/LeaTS admission review](docs/neats_leats_admission_review.md)
and [five-layer self-check](docs/neats_leats_self_check.md).

```bash
conda run -n CompressBench14 python tools/build_codec.py neats-lossless-i64 --profile all
conda run -n CompressBench14 python tools/build_codec.py leats-lossless-i64 --profile all
conda run -n CompressBench14 python adapters/neats/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/neats-leats-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/neats-leats-formal.toml --output-root runs
```

# A FORMAL run uses >=3 warmups, >=0.5 s warmup time, 10 raw repetitions,
# and >=1 s of selected-scope work in every repetition.
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/zstd-lz4-formal-comparison.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/snappy-lz4-zstd-formal-comparison.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/brotli-stream-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/deflate-zlib-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/bzip2-stream-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/xz-stream-formal.toml --output-root runs
```

The package can also be invoked with `PYTHONPATH=src` without installing it.

Sprintz is registered through the two codec APIs actually exposed upstream:
`sprintz-delta` and `sprintz-fire` (FIRE is named XFF in parts of lzbench).
Both admit homogeneous signed/unsigned 8-bit and little-endian 16-bit integer
UTS or synchronous MTS with 1--128 dimensions on AVX2/BMI2/LZCNT. The older
`sprintz-delta-u8` and `sprintz-fire-u8` IDs preserve the earlier restricted
single-channel evidence; they are not aliases for the expanded codecs. There
is no predictor-neutral upstream Sprintz API from which an honest single
`sprintz` AlgorithmID could be derived. Both registered datasets are synthetic
and their generated NPZ files are intentionally ignored by Git. See the
[Sprintz admission review](docs/sprintz_admission_review.md) for source hashes,
safety patches, residual limitations and five-layer evidence.

The paper-defined full pipeline is separately registered as `sprintz-fire-huff0`
(`P2_PIPELINE`): FIRE/XFF prediction, Sprintz bit packing and zero-block RLE, followed
by one Huff0 block. It supports the same integer UTS/MTS domain but limits canonical
raw input to 120 KiB so the entropy stage remains a single bounded block. Raw and
constant Huff0 outcomes are explicit, charged modes. See the
[SprintzFIRE+Huf admission review](docs/sprintz_fire_huff0_admission_review.md).

```bash
conda run -n CompressBench14 python tools/qualify_sprintz_fire_huff0.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-fire-huff0-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/sprintz-fire-huff0-formal.toml --output-root runs
```

Native codec API timings are enabled by default for LZ4, Zstd, Snappy, Brotli, DEFLATE,
bzip2, XZ, LZSS, LZSSE8, Huff0, FSE, Sprintz-Delta, Sprintz-FIRE, SprintzFIRE+Huf,
ALP, ALP-RD, Serf-Qt, Serf-XOR, NeaTS and LeaTS (including the historical restricted u8 Sprintz
registrations).
Disable them with `native_timing = [false]` in `[sweep]`. They supplement CORE and
PIPELINE rather than replacing the selected timing scope. See
[native codec timing](docs/native_codec_timing.md) and the formal example in
`configs/experiments/native-timing-formal-comparison.toml`.

XZ uses one single-call LZMA2 stream, preset 6, one CPU thread, no data check and
mandatory structural CRC32. Its index and headers are fully charged. Finalize is a
mandatory zero-byte acknowledgement, not streaming support. Raw LZMA/.lzma, EXTREME,
BCJ/delta and multithreading are not registered. See [XZ self-check](docs/xz_stream_self_check.md).

The spreadsheet's `LZ77` row points to zlib/RFC1951, the same executable codec as
DEFLATE. Select `algorithms = ["lz77"]` to use its audited mapping to `deflate-zlib`.
This measures complete DEFLATE (dictionary matching plus Huffman), not pure LZ77.
Selecting both names generates one canonical task, not duplicate ranking entries.
`codecs list` discloses mappings separately; runs freeze codec_alias_snapshot.json.
See [LZ77 mapping self-check](docs/lz77_self_check.md).

The spreadsheet label `BZ2 (Huffman Coding)` is registered as `bzip2-stream`, a
complete bzip2 1.0.8 BWT + MTF/RLE + Huffman codec rather than a pure Huffman
primitive. The default is level 9, single-thread scalar execution, normal-memory
decode and one exact stream; all bzip2 stream bytes are charged. See the
[bzip2 five-layer self-check](docs/bzip2_stream_self_check.md).

LZSS fixes EI=10/EJ=4/initial byte 0x20, upstream safe code and stack work buffers.
Its one-shot call flushes bits internally; mandatory Finalize acknowledges completion
with zero bytes. Exact token/decoded-length/zero-tail validation supplements upstream
EOF tolerance, and all descriptors/token/padding bytes are charged. Alternative LZSS
parameters, LZSSE, streaming and query are not qualified by this variant. See
[LZSS five-layer self-check](docs/lzss_raw_self_check.md), including sanitizer coverage
and the void dependency's redistribution-review limitation.

`lzss-dipperstein-c` retains Michael Dipperstein's 12/4 bitstream, 4096-byte
space-filled window and binary-tree matcher. A hashed out-of-tree patch fixes upstream
sentinel out-of-bounds operations and is release-bitstream-equivalent on 48 retained
cases. The original Rust `lzss-raw` and all its evidence remain available; the two
AlgorithmIDs and rankings are never merged. See
[Dipperstein C LZSS self-check](docs/lzss_dipperstein_c_self_check.md).

```bash
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz77-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz77-formal.toml --output-root runs
```

## Layer 1 invariants

- Dataset identity is derived from content hashes and declared semantics, never an
  absolute path.
- CSV/NPZ file size is provenance only and is never used as the compression denominator.
- Timestamp, value, validity, topology, and physical layout are separate contracts.
- Loaders reject undeclared casts, sorting, filling, interpolation, reshaping, and null
  handling.
- PEMS arrays retain their native three-dimensional shape and have no synthesized time
  axis.
- Characterization receives immutable arrays and records whether metrics are exact or
  sampled.
- The canonical stream is versioned, little-endian, sequentially readable from C/C++,
  and protected by SHA-256.
- Run sets are append-only, refuse overwrite, serialize preparation with a lock, and
  reuse only identity- and hash-verified artifacts after an interrupted run.

## Layer 2 invariants

- A source folder or upstream benchmark is evidence, never automatic codec qualification.
- All 221 logical source entries receive a deterministic pre-onboarding classification;
  only reviewed codec manifests receive an AlgorithmID.
- Capability negotiation always returns DIRECT_SUPPORTED, ADAPTER_LOSSLESS,
  ADAPTER_LOSSY, or UNSUPPORTED with structured reasons.
- Adapter operations disclose before/after descriptors, copies, allocations, padding,
  side-information bits, timing scopes, inverse mapping, and validation method.
- Algorithmic preprocessing has a separate versioned plan and independent validator.
- ConfigID includes expanded codec defaults and framework seed; invalid parameter points
  remain present with SCHEMA_ERROR.
- Unsupported tasks remain in deterministic task_plan.jsonl and never invoke a codec.
- ExecutionPathHash binds the loaded artifact hash, adapter/source identity, environment,
  requested/actual ISA, affinity, thread/process budget, alignment, tail, and fallback.
- Semantic, execution, and resource keys are nested in that order; unknown facts are not
  removed to manufacture comparability.

## Layer 3 invariants

- Timestamp, Value, and SYSTEM routes cannot leak data objects across Track boundaries;
  SYSTEM requires a hashed common SegmentPlan.
- Boundary/safety and minimal correctness pass before formal repetitions. Unsupported
  tasks remain diagnostic rows and never call a codec.
- A codec lifecycle is `update -> finalize -> accounting -> independent decode`; capacity
  is not size, and only finalized used bytes enter FinalBits.
- Lossless values use integer exactness or IEEE byte equality. Error-bounded lossy values
  use raw violations as a hard gate; numerical tolerance is diagnostic only.
- Correctness, accounting, timing, and resource observations come from the same formal
  repetition; they are never spliced from separate correctness and speed runs.
- Complete evidence is append-only JSONL; `runs.csv` is an atomic recoverable projection.
  Batch-0 oracles validate the harness and are never leaderboard eligible.

## Layer 4 invariants

- `FORMAL` profiles enforce at least three warmups and 0.5 seconds, at least ten raw
  repetitions, and a registered 1–3 second minimum duration per repetition.
- Minimum-duration loops default to `INDEPENDENT_OBJECT`: every inner iteration creates,
  finalizes, decodes, and closes an independent codec object.
- CORE, PIPELINE, and in-memory E2E boundaries are retained together; the selected scope
  determines direct throughput comparison and is part of ExecutionComparabilityKey.
- CPU user/system/total time, equivalent cores, core-seconds/GB, baseline/peak/incremental
  memory, faults, context switches, I/O, thread count, and swap evidence are raw fields.
- A requested resource scope that is unavailable is explicitly `UNSUPPORTED`; it is not
  silently replaced by zero. Perf counters and energy likewise retain null values plus a
  reason when no active collector exists.
- Query sets are seeded and generated outside timers from the standard range/projection
  matrix. Query and streaming paths run only when codec capability and adapter protocol
  both exist; Batch-0 oracles therefore report NOT_REQUESTED/UNSUPPORTED, never invented
  latency.
- `QUALIFICATION` profiles remain available for fast framework tests and are never enough
  to make a third-party codec leaderboard-eligible.

## Layer 5 invariants

- `run_components.jsonl` and `task_plan.jsonl` are hashed read-only inputs. Derived files
  never rewrite raw evidence or invoke a codec.
- Eligibility is recorded for space/quality, performance, and resource analyses. Every
  excluded repetition retains explicit reason codes in `eligibility.csv`.
- `summary.csv` groups only formal, complete, PASS repetitions with the same DatasetID,
  AlgorithmID, ConfigID, ExecutionPathHash, ProfileID, and RunRecord schema. Incomplete
  or duplicate repetition groups are excluded as a whole.
- Times are normalized by declared independent inner iterations. Median, P25/P75, mean,
  sample SD, CV, and deterministic bootstrap median intervals are retained; fastest-only
  values never become the ranking statistic.
- Per-dataset summaries are primary. `corpus_summary.csv` separately publishes micro
  size/throughput, compression-factor geometric mean, peak-memory max/p95, and CPU cost.
- Coverage uses the frozen task universe and exposes partial/failed/unsupported/OOM/
  timeout outcomes. Coverage is never converted into a weighted score.
- Space, speed, and resource comparisons respectively require Semantic, Execution, and
  Resource keys. Pareto and dense per-metric ranks never cross those boundaries.
- `comparability.csv` expands each key into readable semantic, execution, and resource
  contexts, including TimingScope, ISA/device, thread budget, fallback, and adapter scope.
- The HTML report embeds deterministic SVG coverage and space/throughput charts. Each
  throughput chart is split by DatasetID, ExecutionComparabilityKey, and ProfileID so
  visually adjacent points remain directly comparable.
- Every summary carries its RunIDs, input/bitstream/canonical hashes, SourceArtifactID,
  adapter/binary hash, EnvironmentID, ConfigID, ExecutionPathHash, and comparison keys.

LZSSE8 evidence and limitations: [five-layer self-check](docs/lzsse8_raw_self_check.md).
