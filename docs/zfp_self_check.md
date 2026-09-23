# zfp fixed-accuracy 1D five-layer self-check

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source admission

- [x] Re-read the master plan and C/C++ algorithm analysis; confirmed both spreadsheet
  entries resolve to LLNL/zfp.
- [x] Pinned clean commit `c0c2c40b30d99f1787664b51c593fb6e0d729253`, hashed the
  94-file build closure and retained BSD-3-Clause.
- [x] Read the upstream benchmark, fixed-accuracy tests, high-level C API, header code,
  maximum-size calculation and serial end-to-end tests before writing the shim.
- [x] Kept fixed-accuracy 1D separate from rate, precision, reversible and native ND.

## Layer 1 - Data

- [x] Routes only homogeneous little-endian float32/float64 VALUE UTS or synchronous MTS.
- [x] Preserves row/channel order, names, dtype, shape and logical bits; introduces no
  sort, fill, cast or uncharged preprocessing.
- [x] Row-major MTS conversion to independent columns is explicit and reversed exactly.

## Layer 2 - Contract and fairness

- [x] Registers P1, `ERROR_BOUNDED_LOSSY`, `ABSOLUTE`, serial CPU, single-thread and
  `COLUMN_INDEPENDENT` semantics.
- [x] ConfigID freezes mode, requested bound, dimensionality, full-header policy,
  backend, ISA and native-timing setting.
- [x] Unsupported dtype, validity, topology, mode, ND, device, query and streaming paths
  are rejected instead of silently converted.
- [x] Requested and actual zfp tolerance are both persisted; correctness gates on the
  requested bound, which is the user-visible contract.

## Layer 3 - Native execution and correctness

- [x] Python drives vendored C through C ABI v1 with checked maximum size, exact used
  length, mandatory zero-byte finalize, reset and independent decode.
- [x] Every compressed column carries `ZFP_HEADER_FULL`; complete framing and checksum
  reject truncation, trailing bytes and corruption.
- [x] NaN, infinity, negative zero and subnormal columns use explicit, fully charged raw
  records. Ordinary finite columns cannot silently fall back.
- [x] Release and ASan/UBSan suites cover both dtypes and 1D block/tail boundaries;
  Python adapter tests cover MTS, error bounds, identities and hostile containers.
- [x] Native timing has a zfp-specific complete-frame boundary and is not labeled as an
  lzbench or upstream ND kernel measurement.

## Layer 4 - Measurement

- [x] Qualification RunSet: `runset-20260920T072311Z-861332410bb3`.
- [x] Formal preflight: 34/34 boundary cases PASS; 60,704 values, zero raw and numerical
  violations; max absolute error `0.00056105468749989562 < 0.001`.
- [x] Formal measurement uses ten independent repetitions, PIPELINE selected timing,
  one CPU thread and the same correctness/measurement objects.

## Layer 5 - Statistics and limits

- [x] Formal evidence produces one PASS coverage task and one per-dataset summary with
  no eligibility exclusions.
- [x] Final formal RunSet: `runset-20260920T072326Z-c296325d2eac`; ReportID
  `v2:report:sha256:edc3e9e4606c8cf253f42cb65cba5d2f06c17b29f569ce3bef992e9430003b1e`.
- [x] Final report:
  `runs/runset-20260920T072326Z-c296325d2eac/report/report.html`.
- [x] Physical accounting includes the outer descriptor, all eight zfp column streams,
  full headers, record framing and checksum exactly once.
- [x] Results remain in the 1D fixed-accuracy comparison identity and cannot be merged
  with native 2D/3D/4D, rate, precision, reversible, OpenMP or CUDA results.
- [x] Evidence is one real dataset at one bound; no universal zfp performance claim is
  made.
- [x] Full regression: 838 PASS. Focused zfp/shared-contract tests: 54 PASS. Ruff and
  codec registry verification pass.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py zfp-accuracy-1d --profile all
conda run -n CompressBench14 python adapters/zfp/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/adapters/test_zfp.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/zfp-accuracy-1d-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/zfp-accuracy-1d-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/zfp-accuracy-1d-formal.toml --output-root runs \
  --run-set-id runset-20260920T072326Z-c296325d2eac --resume
```
