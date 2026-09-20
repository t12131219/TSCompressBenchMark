# Serf-Qt / Serf-XOR five-layer self-check

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source admission and identity

- [x] Re-read the master plan and C/C++ algorithm analysis before admission.
- [x] Selected the upstream benchmark/test source at immutable commit
  `b38450b56825eabc96be8e25d6880127dc688c95`; copied only the required 35-file closure.
- [x] Verified closure SHA-256, three-patch set SHA-256, four build artifacts and four
  canonical compile-command hashes.
- [x] Preserved CC BY-NC 4.0 as `REDISTRIBUTION_RESTRICTED`; no commercial or general
  redistribution permission is implied.
- [x] Registered Qt and XOR as distinct AlgorithmIDs sharing one SourceArtifactID.

## Layer 1 - Data

- [x] Routes only VALUE bytes and preserves row/channel order, dtype, shape and logical
  bit count. No sort, fill, cast or hidden preprocessing is introduced.
- [x] UTS and synchronous MTS paths preserve all columns; row-major matrices are copied
  explicitly to independent native columns and reconstructed to the declared layout.
- [x] The standard qualification gate passes 39/39 cases per algorithm, including empty,
  tiny, IEEE edge, layout, dimension and tail cases.

## Layer 2 - Contract and fairness

- [x] Both codecs are P1, scalar CPU, single-thread, one-shot and
  `ERROR_BOUNDED_LOSSY`; the only error contract is positive finite `ABSOLUTE`.
- [x] Explicit lossless requests return `LOSS_MODE_UNSUPPORTED`; negotiation does not
  relabel a lossy manifest as lossless.
- [x] Block size, error bound, XOR adjustment, native timing and ISA are frozen in
  ConfigID. Qt and XOR state semantics remain visible in separate manifests.
- [x] Invalid dtype, topology, validity, size, loss mode, bound type and unsupported
  query/stream requests are rejected instead of silently converted.

## Layer 3 - Native execution, safety and accounting

- [x] Python drives vendored C++ through C ABI v1 with checked output bounds, exact used
  lengths, mandatory zero-byte finalize, reset semantics and independent decode context.
- [x] Complete native frames are self-contained and checked for truncation, trailing
  bytes, descriptor mismatch, checksum corruption and malformed block records.
- [x] Raw exception blocks are explicit and fully charged. Error-bound correctness uses
  raw high-precision comparisons and records both numerical and raw violation counts.
- [x] Three replayed patches eliminate the sanitizer-discovered bit-reader, shift and
  prefix-mask failures; the ABI shim avoids unaligned typed float64 access.
- [x] Release and ASan/UBSan smoke pass for both algorithms. Bound-minus-one, canaries,
  input immutability, repeated finalize and corrupted streams are exercised.
- [x] Native timing is accurately labeled `NATIVE_SERF_FRAME_ENCODE_DECODE_V1`; shared
  statistics accept one consistent declared boundary and reject mixed-boundary groups.

## Layer 4 - Formal measurement

- [x] Final qualification RunSet: `runset-20260920T062542Z-83ecd524822d`.
- [x] Final formal RunSet: `runset-20260920T062606Z-db4b8711b0a0`.
- [x] Each algorithm has 10/10 eligible PASS repetitions; all 20 formal correctness
  records have zero raw absolute-error violations.
- [x] Every repetition uses independent objects and satisfies the selected PIPELINE
  minimum-duration policy. Native, CORE and PIPELINE observations come from the same
  repetitions.
- [x] Historical run sets remain intact. Runs with the old manifest or hard-coded native
  timing label are diagnostic and not final evidence.

## Layer 5 - Statistics and scope

- [x] The final report has two summaries and two PASS coverage tasks with no eligibility
  exclusions. ReportID:
  `v2:report:sha256:5a6da23d5b12e92bdb4d3611b224fa7949aec9e5fa829b1a278a6d172f22dea0`.
- [x] `serf-qt`: SizeRatio 0.052370931075382182; CF 19.094562182990603.
- [x] `serf-xor`: SizeRatio 0.10142659462308909; CF 9.8593470846191327.
- [x] Report: `runs/runset-20260920T062606Z-db4b8711b0a0/report/report.html`.
- [x] Full regression: 807 PASS. Focused post-format regression: 65 PASS. Ruff and
  codec registry verification pass.
- [x] NATIVE results are labeled with their complete native-frame boundary and are not
  described as upstream benchmark or lzbench kernel speeds.
- [x] Evidence covers one `exchange_rate` float64 task, block size 1000 and error 0.001.
  No universal performance conclusion, lossless claim, streaming/query support or
  zero-raw-exception claim is made.

## Reproduce

```bash
conda run -n CompressBench14 python tools/build_codec.py serf-qt --profile all
conda run -n CompressBench14 python tools/build_codec.py serf-xor --profile all
conda run -n CompressBench14 python adapters/serf/tests/run_native_tests.py
PYTHONPATH=src conda run -n CompressBench14 pytest -q tests/adapters/test_serf.py
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench codecs verify
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/serf-qualification.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run validate \
  configs/experiments/serf-formal.toml --output-root runs
PYTHONPATH=src conda run -n CompressBench14 python -m tscompbench run report \
  configs/experiments/serf-formal.toml --output-root runs \
  --run-set-id runset-20260920T062606Z-db4b8711b0a0 --resume
```
