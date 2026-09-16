# Layer 2 Capability and Configuration Self Check

## Contract coverage

- [x] Layer 2 consumes frozen Layer 1 canonical metadata and characterization, and
  verifies their canonical content hashes match before planning.
- [x] SourceRegistry keeps audited external source identities separate from logical
  spreadsheet rows and built-in harness oracles.
- [x] All 221 logical entries are deterministically classified before any decision to
  assign an independent AlgorithmID; ambiguous entries remain pending onboarding.
- [x] Codec manifests declare ObjectLevel, Track/subtrack, topology, dtype/rank/layout,
  validity, timestamp behavior, coupling, loss/reconstruction semantics, lifecycle,
  ISA/device/thread/fallback, feature, parameter, and adapter contracts.
- [x] Negotiation produces exactly four structured states with reason codes and missing
  capability keys. UNSUPPORTED plans are retained in `task_plan.jsonl` and cannot be
  applied by the compatibility adapter.
- [x] Compatibility operations are explicit and account for copies, allocations,
  padding, side information, timing scopes, reverse mapping, and validation method.
- [x] Post-adapter validation is independent from operation planning and checks input
  immutability, shape, bit-exact lossless inverse, or the separately declared lossy bound.
- [x] Algorithmic preprocessing is a separate A/B/C/D plan; its class must agree with
  explicit stages, and its validator cannot borrow an adapter or codec error allowance.
- [x] Sweep expansion performs a deterministic Cartesian product, expands defaults,
  normalizes decimal strings, retains invalid points as SCHEMA_ERROR, and includes the
  benchmark seed in ConfigID.
- [x] TaskID is based on DatasetID, AlgorithmID, ConfigID, Track, and ProfileID; task
  plans are sorted, canonical JSONL, duplicate-free, and refuse a differing rewrite.
- [x] Execution resolution hashes the actual loaded adapter artifact and records source,
  adapter, toolchain, environment, requested/actual ISA, affinity, thread/process budget,
  device, alignment, tail, state/cache/allocation/GC/JIT, and fallback facts.
- [x] SemanticComparabilityKey feeds ExecutionComparabilityKey, which feeds
  ResourceProfileKey. Tests assert this nesting and fallback path separation.
- [x] The C ABI uses fixed-width lengths, opaque handles, explicit capacity/used bytes,
  dtype/shape/stride/alignment/ownership descriptors, stable status codes, and compiles
  as both C11 and C++17.

## Deliberate scope boundaries

- The four built-in codec manifests are Batch 0 harness oracles. They validate routing
  and planning and are never eligible for an algorithm leaderboard.
- No third-party algorithm source was copied. Layer 2 needs manifests and source audit
  evidence, not a native build closure. Source is copied only when a concrete adapter is
  onboarded in a later batch.
- Actual codec invocation, worker isolation, boundary/safety preflight, final bitstream
  accounting, repetitions, and raw `runs.csv` records belong to Layers 3 and 4. Layer 2
  preserves terminal unsupported/invalid tasks so those layers cannot silently omit them.
- Per-entry ObjectLevel and independent-codec qualification remain intentionally pending
  until that entry's implementation/API/build/license closure is reviewed. The framework
  does not fabricate 221 qualified algorithms from inventory metadata.

## Verification evidence

- `27 passed` under Python 3.14.5 in `CompressBench14`.
- Codec/source registry verification: 4 Batch 0 manifests and 72 available source
  identities (71 external available repositories plus one built-in oracle source).
- Source classification: 221/221 entries, one stable classification report ID.
- Layer 2 smoke plan: 8 tasks from one dataset, four codecs, and two block sizes;
  capability counts are 2 direct, 2 lossless-adapter, 2 lossy-adapter, and 2 unsupported.
- C/C++ ABI smoke: `-std=c11 -Wall -Wextra -Werror` and
  `-std=c++17 -Wall -Wextra -Werror` both pass.
