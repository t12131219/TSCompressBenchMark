# Layer 1 Data Preparation Self Check

## Contract coverage

- [x] Runner initialization freezes canonical config and environment data.
- [x] Existing RunSet IDs are never overwritten; resume validates the frozen config,
  EnvironmentID, append-only event log, and every reused Layer 1 artifact.
- [x] A non-blocking per-RunSet lock covers initialization and the complete preparation
  pass; concurrent writers fail instead of racing.
- [x] Output append capability, free space, file limits, clocks, and process-isolation
  facts are captured or probed.
- [x] Thirteen dataset manifests freeze file bytes, SHA-256, parser policy, timestamp
  semantics, topology, dtype policy, validity policy, expected shape, and split state.
- [x] CSV and NPZ source files are verified before loading.
- [x] Canonical logical and physical descriptors are distinct.
- [x] Canonical arrays are immutable and characterization verifies the content hash
  before and after analysis.
- [x] Canonical raw bits are computed from T/V/validity semantics; source file bytes are
  provenance only.
- [x] PEMS arrays retain three dimensions and use `TimestampOrigin=NONE`.
- [x] National illness uses heterogeneous per-column buffers.
- [x] Weather raw header bytes, normalized display labels, and duplicate timestamp are
  represented separately.
- [x] Characterization records exact/sampled mode, seed/sample evidence, timestamp
  delta/DoD behavior, and per-channel numeric/entropy/ACF statistics.
- [x] Canonical bytes have a Python reader/writer, fixed golden SHA-256, a C header
  layout smoke test, and a standalone C inspector that reads every buffer.
- [x] The shared algorithm source tree was scanned and remained unmodified; no source
  was copied for this layer.

## Explicit unresolved provenance

- Dataset upstream source URLs and licenses were not present in the supplied files.
  Manifests say `UNSPECIFIED` and `REVIEW_REQUIRED`; release or redistribution remains
  blocked until evidence is added.
- Learned-codec split policies are `UNSPECIFIED` and `learned_eligible=false`; Layer 1
  will not invent train/validation/test boundaries.
- The workspace exposes an empty read-only `.git` mount. `git init` cannot create Git
  metadata in this session, so source versioning is the only unfinished Phase 0 item.

## Verification commands

```bash
PYTHONPATH=src conda run -n CompressBench14 python -m pytest
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench datasets verify
cc -std=c11 -Wall -Wextra -Werror -I native/include -fsyntax-only \
  tests/golden/canonical_header_smoke.c
PYTHONPATH=src conda run -n CompressBench14 python -m compileall -q src tools tests
```
