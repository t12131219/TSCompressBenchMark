# NeaTS / LeaTS five-layer self-check

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source admission and identity

- [x] Re-read the master plan and C/C++ algorithm analysis before admission.
- [x] Pinned clean upstream commit `2d804ff492e45222e841dc1a50904476fa64f4a0`,
  retained its license notices and hashed the 172-file source closure.
- [x] Audited `main_simd.cpp`, `LeaTS.cpp`, the lossless benchmark, public model headers,
  serialization/index code and bundled SDSL/sux dependencies used by the build.
- [x] Registered NeaTS nonlinear and LeaTS linear models as distinct AlgorithmIDs sharing
  one patched SourceArtifactID.
- [x] Recorded all three compatibility/correctness patches and four reproducible build
  artifacts; no shared source checkout was modified.

## Layer 1 - Data

- [x] Routes only homogeneous signed integer VALUE UTS or synchronous MTS.
- [x] Preserves row/channel order, dtype, shape and logical bits. Row-major matrices and
  SOA columns are transformed explicitly and reconstructed to the declared layout.
- [x] The per-column minimum shift is checked for int64 span overflow and serialized as
  codec metadata; it does not mutate the canonical object.
- [x] Invalid dtype, endian, rank, validity, dimensions and input-size cases are rejected.

## Layer 2 - Contract and fairness

- [x] Both codecs are P1, lossless, learned object-local, scalar CPU, single-thread and
  `COLUMN_INDEPENDENT`; model family remains visible in separate manifests.
- [x] `max_bpc`, ISA and native-timing enablement are frozen in ConfigID. Only max_bpc
  16 and 32 are registered.
- [x] Model fitting occurs independently inside each compression call. No external
  training data, checkpoint, train/test split, cross-object state or test leakage exists.
- [x] Unsupported unsigned, float, lossy, streaming, SIMD, device and thread requests
  produce explicit planning/adapter rejection instead of fallback.

## Layer 3 - Native execution, safety and accounting

- [x] Python drives vendored C++ through C ABI v1 with checked bounds, exact used length,
  zero-byte mandatory finalize, reset and independent decode.
- [x] The complete descriptor, bias, record metadata, model, residual/index structures
  and checksum are serialized and charged; external side-information bits are zero.
- [x] Frames reject truncation, trailing bytes, descriptor mismatch, checksum corruption,
  invalid sizes and reconstruction overflow.
- [x] Native query is correctness-checked and reports full-frame bytes touched because
  checksum validation reads the complete frame.
- [x] Release and ASan/UBSan smoke tests pass all admitted widths and critical boundaries.
  LeakSanitizer remains unexecuted because of the managed ptrace environment.
- [x] The LeaTS predictor-precision mismatch exposed by qualification is fixed with a
  hashed patch; the original failing run remains append-only evidence.

## Layer 4 - Measurement

- [x] Final qualification RunSet: `runset-20260920T081824Z-26d63b8dfcfa`; both full
  round trips and both query workloads PASS.
- [x] Final formal RunSet: `runset-20260920T081952Z-a30140b62718`.
- [x] Each algorithm has 10/10 eligible PASS repetitions; all 20 correctness and all
  20 query results PASS.
- [x] Every formal repetition reaches at least one second of selected PIPELINE work,
  uses independent objects, one CPU thread and the same object for correctness/resource
  evidence and timing.
- [x] NeaTS and LeaTS share semantic, execution and resource comparability keys while
  retaining different AlgorithmIDs and bitstreams.

## Layer 5 - Statistics and limits

- [x] The final report contains two summaries and two PASS coverage tasks with no
  eligibility exclusions. ReportID:
  `v2:report:sha256:efda2ecb9b0e8988c490b1ee68534a3dac77dede0d3491d69212ec48277c2f70`.
- [x] `neats-lossless-i64`: SizeRatio 0.43829345703125; CF 2.2815763821194820.
- [x] `leats-lossless-i64`: SizeRatio 0.46856689453125; CF 2.1341669923147063.
- [x] Report: `runs/runset-20260920T081952Z-a30140b62718/report/report.html`.
- [x] Historical `080622` incomparable and `080839` correctness-fail run sets remain
  intact and are excluded from final evidence.
- [x] Results are limited to deterministic synthetic `sprintz_i16_mts`; no real-data,
  unsigned, float, SIMD, multithreaded or joint-MTS performance conclusion is made.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py neats-lossless-i64 --profile all
conda run -n CompressBench14 python tools/build_codec.py leats-lossless-i64 --profile all
conda run -n CompressBench14 python adapters/neats/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/adapters/test_neats.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/neats-leats-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/neats-leats-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/neats-leats-formal.toml --output-root runs \
  --run-set-id runset-20260920T081952Z-a30140b62718 --resume
```
