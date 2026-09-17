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
reviewed translation-unit closure needed by an adapter. The first qualified native
codec is LZ4 Frame 1.10.0, taken from lzbench's vendored source at a pinned commit and
stored under `adapters/lz4_frame/vendor/lz4`; its source, license, build, ABI, accounting,
and five-layer evidence are recorded in `registry/onboarding/lz4-frame.json`.

## Environment

Use the supplied environment:

```bash
PYTHONPATH=src conda run -n CompressBench14 python -m pytest
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

# Build and qualify the first native codec.
conda run -n CompressBench14 python tools/build_codec.py lz4-frame --profile release
conda run -n CompressBench14 python tools/build_codec.py lz4-frame --profile sanitizer
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz4-frame-qualification.toml --output-root runs

# A FORMAL run uses >=3 warmups, >=0.5 s warmup time, 10 raw repetitions,
# and >=1 s of selected-scope work in every repetition.
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/lz4-frame-formal-smoke.toml --output-root runs
```

The package can also be invoked with `PYTHONPATH=src` without installing it.

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
