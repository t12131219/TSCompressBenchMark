# Serf-Qt / Serf-XOR admission review

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and identity decision

The spreadsheet rows `Serf-Qt` and `Serf-XOR` map to the benchmark and correctness
drivers in `Spatio-Temporal-Lab/Serf` commit
`b38450b56825eabc96be8e25d6880127dc688c95`. The admitted 35-file source closure has
SHA-256 `6b3424d94d4c169b373664277c3882ceb2f95d01b9983899567ce5aa2f399aff`.
Both benchmark entries use the same SourceArtifactID but remain separate AlgorithmIDs:

- `serf-qt`: `v2:algorithm:sha256:c0ef0c1825cd6c68d9e917714d990a1d41a0ecd6d8824ebfe72799401634a5dd`;
- `serf-xor`: `v2:algorithm:sha256:7ee484d7b255aa343a42f0b1ca1cb2edb0e6465b45eec0cea6edd289d8c7bb98`.

The completed source-onboarding card has stable ID
`v2:source-onboarding:sha256:df6e34f7d5fe852119a9f693faf366ab0376954898ecb58dc5a232a37352a00c`.

Qt starts a new predictor/quantizer for every block. XOR carries its previous approximate
value and adaptive zero positions across finite blocks within one column. Those state
machines and bitstreams are not aliases and their results must not be merged.

## Registered contract

Python drives two separately linked C++ artifacts through C ABI v1. The registered domain
is homogeneous little-endian float32/float64 VALUE UTS or synchronous MTS without
validity. Only positive finite `ABSOLUTE` error bounds are admitted; default block size is
1000 and the registered range is 1..65535.

The outer container freezes algorithm, dtype, shape, column layout, error bound, block
size and XOR adjustment. The native frame records exact logical counts, exact valid bits,
byte-rounded payload lengths, reset flags, raw-exception records and a complete frame
checksum. `FinalBits` is the physical outer container plus complete native frame. Capacity
and upstream ratio estimates never enter accounting.

Non-finite or unsafe-to-quantize blocks are stored exactly in an explicit raw-exception
record and fully charged. That is registered fallback behavior, not a silent algorithm
switch. Qualification exercises it. The formal report proves zero absolute-error
violations, but does not project raw-exception-block telemetry; therefore it does not
support a claim that no formal block used that path.

## Safety qualification

ASan/UBSan identified three upstream boundary issues: unconditional bit-reader access at
the physical end, unsigned subtraction followed by an invalid large shift, and an
out-of-range prefix-mask index. Three build-time patches replay those fixes from the
immutable vendor closure. The C ABI shim additionally copies potentially 4-byte-aligned
float64 input into aligned native storage before typed access.

Patch-set SHA-256:
`e040202e3ecd0413e08497dcdabe92cb88169b0de5a6ed921a4682c97b423674`.
Release and ASan/UBSan ABI smoke tests pass for Qt/XOR and float32/float64 across empty,
tiny, block-boundary, multi-block and special-value cases. LeakSanitizer is disabled only
because the host ptrace policy prevents it; ASan and UBSan stay enabled and fail-fast.

## Timing and comparability

NATIVE uses `NATIVE_SERF_FRAME_ENCODE_DECODE_V1`. Encode includes aligned column copies,
native frame construction, upstream block calls, record serialization and checksum.
Decode begins after frame checksum/header prevalidation and includes record parsing,
upstream block calls and result copies. Context lifecycle, Python layout/FFI/container,
native input-descriptor parsing and final encoded-output copy are outside this interval.
It is not presented as an lzbench-equivalent kernel measurement.

The two algorithms share loss mode, requested error bound, input topology, execution
device and resource policy, but their AlgorithmID and semantic comparison keys remain
distinct. Results with another error bound, block size, state policy, native timing
boundary or raw-exception behavior must not be merged into the same ranking group.

## License decision

The upstream README declares CC BY-NC 4.0. The source is admitted for noncommercial
evaluation with attribution. Redistribution and commercial use remain restricted and
require a separate license decision; benchmark admission is not a license expansion.

## Final evidence

- Qualification: `runs/runset-20260920T062542Z-83ecd524822d`, two tasks, 39/39 boundary
  cases PASS for each algorithm.
- Formal: `runs/runset-20260920T062606Z-db4b8711b0a0`, 20/20 eligible PASS repetitions,
  two summaries and two PASS coverage tasks.
- ReportID:
  `v2:report:sha256:5a6da23d5b12e92bdb4d3611b224fa7949aec9e5fa829b1a278a6d172f22dea0`.
- Report: `runs/runset-20260920T062606Z-db4b8711b0a0/report/report.html`.
- Full regression: 807 PASS; focused post-format regression: 65 PASS; Ruff and codec
  registry verification: PASS.

Earlier run sets remain append-only diagnostic evidence. `061256`/`061323` predate the
accurate manifest timing boundary; `062105`/`062129` exposed the shared recorder's former
hard-coded boundary. None is used as final admission evidence.

The formal input is only the real `exchange_rate` float64 task at absolute error 0.001.
Its size and speed observations are reproducible evidence for that task, not universal
performance conclusions for Serf, other datasets or other parameter values.
