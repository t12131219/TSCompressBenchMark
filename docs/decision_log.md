# Engineering Decision Log

## D001 Dataset identity excludes local paths

DatasetID hashes the source content digest, byte count, format, parser policy, logical
semantics, expected structure, split policy, and canonical policy. Display names,
absolute locations, and the local relative file path do not define identity. This lets
the same bytes and semantics retain an ID after relocation while any content or semantic
change produces a new ID.

## D002 CSV parsing is schema directed

Layer 1 uses Python's strict CSV parser and per-column NumPy buffers. Dates accept only
manifest-listed formats and naive source times are interpreted as UTC only because each
manifest states that policy. Numeric values are parsed directly into declared dtypes;
there is no Pandas inference, sorting, missing-value repair, or homogeneous matrix cast.

## D003 PEMS has no synthesized timestamp

The four NPZ archives contain only a `data` array. In the absence of provenance for a
sampling interval or epoch, their timestamp origin is `NONE`. Their `[time, sensor,
feature]` shapes remain native three-dimensional arrays.

## D004 National illness remains heterogeneous

The percentage columns use little-endian float64 buffers; the age, total, provider, and
target count columns use little-endian int64 buffers. The canonical physical view is a
structure-of-arrays column set, preventing NumPy from silently promoting every field to
float64.

## D005 Weather header corruption is provenance

The raw UTF-8 header already contains replacement characters. Its exact bytes and hash
are frozen in the manifest; normalized display labels are separate metadata and never
rewrite the raw file or DatasetID source content. The one duplicate timestamp is allowed
and preserved, not deduplicated.

## D006 Canonical binary is sequential and C readable

`tscb-canonical-v1` uses fixed little-endian file and buffer headers, canonical JSON
metadata, ordered raw buffers, per-buffer hashes, and one whole-file hash. It does not
embed Python objects, pickle, NumPy private ABI, or local paths. The matching C header is
`native/include/tscb_canonical_v1.h`. The standalone inspector in
`native/tools/inspect_canonical_v1.c` walks metadata and every declared buffer without
NumPy or Python.

## D007 Source inventory is not codec qualification

The 221 spreadsheet-derived logical entries are classified by deterministic rules, but
they do not automatically receive AlgorithmIDs. TSBench rows remain reference-only;
algorithm candidates remain pending until source/API/build/license and object-level
ambiguity are reviewed. Shared repositories retain SourceArtifactIDs independently from
the multiple logical algorithms or pipeline stages that may use them.

## D008 Negotiation and validation are framework decisions

Codec manifests declare facts. The framework alone assigns the four capability states,
constructs explicit adapter operations, validates post-adapter logical content, routes
lossy transformations, and decides task status. An adapter cannot turn a mismatch into
PASS, hide a copy, sort data, or remove an unsupported task.

## D009 Adapter and algorithmic preprocessing are distinct

Compatibility adapters only satisfy declared physical/API requirements and expose their
copy/allocation/padding/timing evidence. Delta, quantization, model training, and other
algorithm stages use a separate ordered A/B/C/D preprocess plan and validator. Loss
budgets and timing cannot move silently between these two contracts.

## D010 Configuration and task identities retain the full task universe

ConfigID hashes expanded codec defaults plus framework parameters such as the benchmark
seed. Cartesian sweep points that violate a closed parameter schema remain records with
SCHEMA_ERROR. TaskID then binds DatasetID, AlgorithmID, ConfigID, Track, and ProfileID;
deterministic task JSONL includes unsupported and lossy-routed tasks instead of deleting
them before execution.

## D011 Comparability narrows hierarchically

SemanticComparabilityKey defines the compression task. ExecutionComparabilityKey embeds
that semantic key and adds timing, adapter boundary, ISA/device/thread/fallback, layout,
alignment, tail, allocation/cache/GC/JIT facts. ResourceProfileKey embeds the execution
key and adds resource attribution and sampling. Unknown facts are explicit values and
are never removed to manufacture a direct comparison.

## D012 Execution uses an explicit update/finalize protocol

The adapter protocol exposes output bound, update, finalize, accounting, decode, and
close as separate operations. Output capacity is runtime memory, while only used bytes
after finalize enter the ledger. Batch-0 frames include a real footer and checksum so a
missing Finalize is observable rather than a zero-cost no-op. Repeated Finalize behavior
is exercised in the boundary suite.

## D013 JSONL is the recoverable raw-run authority

`run_components.jsonl` is append-only and contains the complete nested RunRecord. The
flat `runs.csv` is an atomically rebuilt projection under the same run-store lock. This
means a crash cannot require deleting or rewriting raw evidence: an idempotent retry can
recover the CSV projection from JSONL, while a duplicate RunID with different content is
rejected.

## D014 Layer 3 qualification and Layer 4 measurement share one lifecycle

Layer 3 performs boundary/safety preflight. Layer 4 then wraps the same update, finalize,
accounting, independent decode, and correctness lifecycle with warmup, minimum-duration,
timing, and resource collectors. A separate speed-only loop is forbidden. Statistical
aggregation remains a Layer 5 responsibility and cannot be inferred from qualification
or warmup observations.

## D015 Formal and qualification measurement profiles are explicit

`FORMAL` is the publishable measurement mode and enforces the contract minimums:
warmup count/time, ten repetitions, and one-to-three seconds of selected-scope work in
each repetition. `QUALIFICATION` exists for short framework and adapter checks, records
the same evidence shape, and cannot make a third-party run leaderboard-eligible. The
distinction is frozen into ProfileID and therefore into TaskID/comparability evidence.

## D016 Unavailable resource and workload evidence is null with a reason

The initial synchronized collector implements Linux PROCESS evidence with getrusage and
`/proc`. A request for process-tree cgroup, device, system E2E, perf, or energy data is
not silently relabeled as PROCESS and never becomes numeric zero. Requested/actual
scope, availability, reason, and null measurement fields are retained. Query and
streaming observations are similarly capability-gated; false capability never produces
synthetic latency.

## D017 Layer 5 is a deterministic read-only derivation

Statistics consumes `task_plan.jsonl` as the frozen coverage denominator and
`run_components.jsonl` as the authoritative repetition evidence. Both files are hashed
before analysis. Eligibility is analysis-specific and every rejection gets reason codes;
there is no adapter callback and no correctness reclassification in reporting.

Per-dataset summaries require the same ConfigID, ExecutionPathHash, ProfileID, and schema.
Only complete FORMAL PASS groups enter aggregation. Corpus metrics are a second derived
layer using explicit micro and geometric-mean formulas. Direct comparison tightens from
Semantic to Execution to Resource keys; Pareto and dense metric ranks stay within the
appropriate key and Coverage is published separately without a weighted total score.

## D018 The first native codec is a pinned lzbench LZ4 Frame closure

Phase 4 starts with LZ4 Frame as required by the engineering plan and the spreadsheet-
to-benchmark analysis. The source authority is lzbench commit
`fa871e66b3543a70fd4d060f7c12719343ff4ac3`; only the reviewed LZ4 1.10.0 translation-
unit closure and license notices are copied into the project. Files are kept unmodified,
while project-specific behavior lives in a separate stable C ABI shim. The local
upstream LZ4 checkout is comparison evidence, not a second execution authority.

## D019 Output bounds are conservative capacities, not expected sizes

The first real codec exposed an oracle-specific assumption in the original boundary
validator: it required `bound - 1` to fail. Native compression bounds such as
`LZ4F_compressBound` are conservative, so valid data can fit below them. The corrected
contract requires the declared bound to succeed safely and account only actual written
bytes. A `bound - 1` attempt may either fail with a stable capacity error or succeed if
it independently finalizes, stays within capacity, round-trips, and passes canary
checks. A genuinely under-reported bound still fails the normal bound-capacity case.

## D020 LZ4 uses one self-contained frame inside a versioned descriptor container

Each independently measured object serializes the routed canonical buffers into a
versioned TSCB descriptor prefix followed by one complete LZ4 frame. The container
records buffer order, dtype, shape, and byte lengths, allowing independent decode
without Python objects or out-of-band metadata. `LZ4F_compressEnd` is mandatory;
physical size and structural accounting are computed from actual finalized bytes, not
capacity. Python FFI and container work are included in the declared PIPELINE boundary.
The adapter currently makes no streaming, query, or random-access claim.
