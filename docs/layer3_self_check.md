# Layer 3 Execution and Validation Self Check

## Contract coverage

- [x] Track routing reads frozen canonical buffers: Timestamp routes only T, Value routes
  V/validity without T, and SYSTEM requires T+V plus a hashed common SegmentPlan.
- [x] Actual dtype, shape, row count, endianness, mutability, special values,
  timestamp unit/epoch, value units, CanonicalRawBits, DatasetID, Track, and input hash
  are checked against the Layer 2 task and retained in Preflight evidence.
- [x] Compatibility operations are applied before codec invocation and independently
  validated. Lossy adapter error is charged to the same loss gate as codec error.
- [x] Non-empty Algorithmic Preprocess plans cannot be silently skipped; execution is
  refused until a stage executor is registered.
- [x] The generated boundary suite covers N and M boundaries, integer/floating special
  values, entropy/expansion inputs, C/F/strided/misaligned views, partial/exact/multiple
  blocks, empty final, reset, repeated Finalize, output bound-minus-one, and canary.
- [x] Preflight checks source/license/build/adapter identity, boundary/safety,
  minimal correctness, FinalBits closure, worker limits, and execution-path evidence
  before any formal repetition.
- [x] Terminal Layer 2 tasks produce diagnostic RunRecords and never invoke an adapter.
- [x] Each formal repetition creates a fresh codec session/output buffer, calls update,
  calls Finalize, accounts the finalized stream, decodes independently, validates, and
  only then records a terminal status.
- [x] CPU/resource evidence is sampled immediately after the measured encode/decode;
  the deterministic re-encode is a validation probe and is excluded from that sample.
- [x] Worker processes enforce deadlines, distinguish TIMEOUT/OOM/CRASHED, apply CPU
  affinity, and apply an address-space limit with explicit existing-VM headroom evidence.
- [x] AccountingLedger enforces non-negative, mutually exclusive component bits,
  one final byte-rounding boundary, physical-stream closure, external side information,
  and Track ownership.
- [x] Common correctness validates names/order, length/shape, timestamp exactness,
  integer exactness, float IEEE bytes including signed zero/NaN payloads, validity,
  T/V pairing, deterministic streams, input immutability, and output canary.
- [x] Error-bounded validation reports raw and numerical violations; raw violations are
  a hard BOUND_VIOLATION. Per-channel MAE/RMSE/NRMSE/MaxAE/percentiles/bias/PSNR and
  applicable time-weighted RMSE are emitted. Temporal fidelity is explicitly non-gating.
- [x] `run_components.jsonl` retains complete evidence; `runs.csv` is its recoverable
  flat projection. Bitstream hashes are always retained and small Batch-0 streams are
  stored as artifacts.
- [x] Resume reuses terminal tasks and does not duplicate RunIDs or CSV rows.
- [x] The planned execution artifact now hashes the actual Batch-0 oracle module, and
  Preflight rejects a runtime AdapterID different from the frozen Layer 2 AdapterID.

## Qualification scope and deferred work

- Batch 0 uses project-internal lifecycle oracles and never becomes leaderboard-eligible.
  No third-party source is needed or copied for this layer.
- ASan/UBSan/guard-page proof is mandatory when the first native adapter is onboarded.
  It cannot be truthfully produced for an in-process Python oracle and is not fabricated.
- Full warmup/min-time/10+ repetition policies, synchronized PROCESS resource collection,
  and capability-gated query/stream workload contracts are now implemented by Layer 4
  around this same lifecycle. Cgroup/device collectors remain explicit unsupported
  resource observations until the required host capability exists.
- RATE_CONTROLLED_LOSSY actual-rate comparison and SUMMARY_ONLY reports require their
  dedicated codec/profile manifests; the state branches exist but are not claimed as
  qualified without such an adapter.

## Verification evidence

- `39 passed` in `CompressBench14` after adding accounting, routing, lifecycle,
  boundary, loss-gate, isolation, run-store, and full Layer 3 integration tests.
- Full capability smoke: eight planned tasks produced six PASS formal oracle records
  and two retained UNSUPPORTED diagnostic records; all six PASS records have non-zero
  Finalize bytes and stored finalized bitstreams.
- Resume smoke produced zero new executions and kept exactly eight raw CSV rows.
- Repeated source audit: 221 logical entries, 72 repositories, 71 available/clean,
  145,830 scanned files; shared source remained read-only.
