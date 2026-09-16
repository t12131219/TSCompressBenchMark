# Layer 4 Performance Evaluation Self Check

## Contract coverage

- [x] Layer 4 begins only after Layer 3 source/capability/boundary/correctness/accounting
  preflight passes; a terminal task never reaches warmup or performance measurement.
- [x] Formal timing, resource collection, Finalize, accounting, decode, and correctness
  share the same isolated repetition and RunID.
- [x] FORMAL profiles enforce warmup count >= 3, warmup duration >= 0.5 s,
  repetitions >= 10, and selected-scope minimum duration in the registered 1–3 s range.
- [x] Minimum-duration loops declare `INDEPENDENT_OBJECT`; every inner iteration creates
  fresh encode/decode sessions and a complete finalized object. Unsupported continuous
  stream semantics fail explicitly rather than reusing hidden state.
- [x] Raw timing retains selected Encode/Decode, CORE Encode/Decode, PIPELINE
  Encode/Decode, E2E, process CPU, inner iteration count, canonical/codec bytes, rows,
  value elements, and decimal-MB throughput.
- [x] Adapter preparation and inverse consumption are inside PIPELINE/E2E but outside
  CORE. E2E records its actual input mode as a canonical in-memory routed view; it does
  not claim file I/O.
- [x] PROCESS monitoring records user/system/total CPU, equivalent cores, allocated-CPU
  utilization, core-seconds/GB, baseline/peak/incremental RSS, PSS/USS when readable,
  faults, context switches, block I/O, logical/physical bytes, syscall counts, threads,
  swap, and sampler overhead.
- [x] Requested versus actual resource scope and availability are explicit. Cgroup,
  device, perf, and energy values remain null with a reason when no active collector is
  present; zero is reserved for an observed zero.
- [x] Swap or an observed thread count above the frozen budget changes the overall run
  to `RESOURCE_PRESSURE` or `OVERSUBSCRIBED` while preserving correctness PASS evidence.
- [x] Query positions/ranges/projections are deterministically pre-generated from the
  seed for lengths 1/16/100/1000/full and widths 1/2/4/min(8,M)/M.
- [x] Query/streaming results are capability-gated. Batch-0 manifests declare both false,
  so the framework records NOT_REQUESTED or UNSUPPORTED instead of timing full decode and
  mislabeling it random access/streaming.
- [x] Complete nested evidence is in `run_components.jsonl`; `runs.csv` projects raw
  timing/resource/workload fields and is recoverable on resume.
- [x] Layer 1 canonical bits/elements feed throughput denominators, Layer 2 profile and
  execution/resource keys freeze comparison boundaries, and Layer 3 correctness and
  FinalBits remain attached to every Layer 4 record.

## Deliberate capability boundaries

- The current qualified adapters are internal Batch-0 oracles. They prove the framework
  lifecycle but are never leaderboard-eligible, even in FORMAL mode.
- No current qualified codec manifest truthfully declares query or streaming support.
  The generic engines, deterministic generation, capability gates, exact query-slice/
  stream-reconstruction checks, latency/amplification accounting, and result slots are
  in place; non-null production observations require the first source adapter that
  implements the reviewed protocols.
- PROCESS_TREE_CGROUP, DEVICE, SYSTEM_E2E, perf, and energy collection require host or
  adapter integration not available in this environment. Their explicit unsupported
  state prevents cross-scope resource ranking.
- Median/P25/P75/mean/SD/CV/bootstrap aggregation belongs to Layer 5. Layer 4 preserves
  all raw observations and does not select fastest runs.

## Verification evidence

- `44 passed` under Python 3.14.5 in `CompressBench14`; compileall also passes.
- Ruff 0.16.7 reports `All checks passed`, and all 76 Python files pass
  `ruff format --check`.
- Formal acceptance used one task, 3+ warmups for >=0.5 s, 10 independent raw
  repetitions, and >=1 s selected PIPELINE work in every repetition. All ten retained
  independently finalized objects and the same-repetition correctness flag. Nine were
  PASS; one observed system swap and was correctly retained as `RESOURCE_PRESSURE`
  rather than entering eligible performance aggregation.
- The acceptance run produced 10 CSV rows with the complete flat timing/resource/
  workload projection; resume executed zero new tasks and retained exactly the original
  ten RunIDs.
- Repeated source audit remained semantically unchanged at 221 logical entries,
  72 repositories, 71 available clean repositories, and 145,830 scanned files.
