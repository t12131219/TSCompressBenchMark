# Layer 5 Statistics and Reporting Self Check

## Contract coverage

- [x] Statistics reads frozen `task_plan.jsonl` and append-only
  `run_components.jsonl`; it does not import adapters, call codecs, or rewrite either
  input. Their SHA-256 values, the frozen config/environment/registry/preparation
  records, and the Layer 5 implementation files are stored in the report identity.
- [x] Eligibility is evaluated independently for SPACE_QUALITY, PERFORMANCE, and
  RESOURCE. Every RunID receives an `eligibility.csv` row with explicit reasons.
- [x] PASS, FORMAL mode, correctness, error-bound, accounting closure, timing duration,
  bitstream artifact hash, dataset provenance, source provenance, comparison-key chain,
  and global benchmark eligibility are all checked before aggregation.
- [x] Repetition sufficiency is checked on the complete DatasetID + AlgorithmID +
  ConfigID + ExecutionPathHash + SchemaVersion group. Fewer than the frozen repetition
  target, fewer than ten formal repetitions, or duplicate indices excludes the group.
- [x] `summary.csv` is per dataset and path. Per-operation timing divides aggregate
  repetition timing by `inner_iterations`; throughput uses total bytes divided by total
  time rather than averaging throughput values.
- [x] Median, P25, P75, mean, sample SD, CV, and deterministic percentile-bootstrap
  confidence intervals for the median are produced. No fastest-only field drives rank.
- [x] `corpus_summary.csv` is derived only after per-dataset summaries. It implements
  micro SizeRatio/CompressionFactor, micro encode/decode throughput, CompressionFactor
  geometric mean, peak-memory max/p95, and corpus CPU core-seconds/GB.
- [x] Resource peak memory is never summed across datasets. Process CPU is normalized
  per independent inner iteration before corpus CPU cost is recomputed.
- [x] Coverage uses every frozen TaskID, retains exact status counts and RunIDs, and
  labels incomplete/partial PASS task executions as failures rather than survivors.
- [x] Pareto space/encode and space/decode views use ExecutionComparabilityKey;
  space/memory uses ResourceProfileKey; rate-distortion uses SemanticComparabilityKey.
- [x] `comparability.csv` and the human reports expand key hashes into readable Track,
  ObjectLevel, LossMode, topology, adapter, TimingScope, ISA/device/thread/fallback, and
  resource-scope contexts.
- [x] HTML output includes deterministic SVG coverage and space/throughput charts; every
  throughput panel is isolated by DatasetID, ExecutionComparabilityKey, and ProfileID.
- [x] Per-metric dense ranking stays inside the appropriate comparison group. No
  arbitrary weighted score or cross-Track/LossMode/ObjectLevel/device ranking exists.
- [x] Machine `report.json` includes complete eligibility, summary, corpus, coverage,
  Pareto, ranking, environment, dataset preparation evidence, codec, and source snapshots.
  Markdown/HTML expose the environment, dataset hashes, frozen source identity, exclusion
  reasons, ratio direction, units, and TimingScope/thread/model-index/cold-start cautions.
- [x] Summary traceability includes RunIDs, repetition indices, input/bitstream hashes,
  dataset source/canonical hashes, SourceArtifactID, AdapterID, execution binary hash,
  EnvironmentID, ConfigID, ExecutionPathHash, and all comparison keys.
- [x] Empty eligible sets produce header-only result tables and a complete Coverage
  report; Batch-0 Oracle PASS runs remain correctly excluded from leaderboards.

## Layer 1-4 adaptation checks

- Layer 1 preparation records supply source, canonical artifact, and canonical content
  hashes. Missing provenance is an eligibility failure, not an empty report cell.
- Layer 2 now freezes `source_registry_snapshot.json`; task comparison documents are
  machine-checked for Semantic → Execution → Resource nesting before use.
- Layer 3 accounting is recomputed from component bits and checked against serialized,
  external-side-information, FinalBits, and final physical-byte invariants.
- Layer 4 raw aggregate times, iteration semantics, duration gate, measurement mode,
  resource scope, and observed pressure statuses are respected. Statistics never splices
  correctness from a different repetition.

## Verification evidence

- 49 tests pass under Python 3.14.5 in `CompressBench14`; Ruff lint, Ruff formatting,
  and compileall pass.
- A synthetic two-codec formal fixture proves 10-repetition summaries, deterministic
  bootstrap output, nested-key Pareto/ranks, timeout exclusion, frozen-universe Coverage,
  and unchanged raw-evidence SHA-256 after report generation.
- A real eight-task CLI qualification run completed Layers 1-4 and then `run report`.
  It produced eligibility/summary/corpus/coverage/Pareto/ranking CSVs, JSON, Markdown,
  HTML, and three SVG charts. Its zero summary rows are intentional because Batch-0
  Oracles and QUALIFICATION measurements are not leaderboard eligible; all eight tasks
  remain in Coverage.
- The repeated source audit matched the frozen catalog semantically: 221 logical
  entries, 72 repositories, 71 available/clean, and 145,830 scanned files.
