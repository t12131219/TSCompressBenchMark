# zfp fixed-accuracy 1D admission review

Date: 2026-09-20  
Environment: `CompressBench14`  
Canonical project: `/home/fzg/PycharmProjects/TSDataCompressBenchMark`

## Source and identity

The spreadsheet lists `zfp` at `参考TSBench` row 14 and `Value-Compress` row 65. Both
entries resolve to LLNL/zfp. The admitted source is the clean local checkout at commit
`c0c2c40b30d99f1787664b51c593fb6e0d729253`; the 94-file vendor closure has SHA-256
`98e179e7aa8ccc6bf81d38c917ada7387a0e8bfbc74ac343bf156fcadfb2d591` and retains the
BSD-3-Clause license.

The registered AlgorithmID is `zfp-accuracy-1d`. It is deliberately narrower than the
whole upstream library: float32/float64, fixed-accuracy, serial CPU, and one independent
1D zfp field per VALUE channel. The complete serial C library translation-unit set is
built because upstream `zfp.c` references every dimensional/type entry point, but the
shim admits only `zfp_field_1d` with float types. Fixed-rate, fixed-precision, reversible,
OpenMP, CUDA and native 2D/3D/4D execution are rejected and require distinct identities.

## Error and exceptional-value contract

Only positive finite `ABSOLUTE` bounds are accepted. zfp rounds the requested tolerance
down to a supported power of two. The outer descriptor records the requested decimal and
the exact hexadecimal actual tolerance; the native frame repeats both as binary64 and
each compressed column carries `ZFP_HEADER_FULL`. For the formal `0.001` request, the
actual zfp setting is `0.0009765625`.

The framework, not zfp's return status, is the correctness authority. It compares every
finite reconstructed value in extended precision against the requested `0.001` bound.
Any violation is `BOUND_VIOLATION`. A column containing NaN, infinity, negative zero or
subnormal data is stored as an explicit raw IEEE record and fully charged. Positive zero
and ordinary finite values do not silently fall back; a zfp failure is an execution
failure.

## Stream, accounting and timing

The self-contained object consists of the project prefix, canonical descriptor, checked
native header, one record per column, complete zfp streams or raw exception bytes, and a
64-bit frame checksum. Exact used length, not zfp capacity or an estimated ratio, defines
`FinalBits`; the checksum is accounted separately. Decode rejects descriptor mismatch,
truncation, trailing bytes, checksum changes, inconsistent record sizes and wrong zfp
mode/header metadata.

NATIVE timing is `NATIVE_ZFP_ACCURACY_1D_FRAME_ENCODE_DECODE_V1`. Encode includes the
registered native frame construction, exception decision, allocations, zfp headers and
zfp calls. Decode checksum/global-header prevalidation is excluded; record parsing,
raw-copy or zfp decode and result writes are included. It is diagnostic complete-object
timing, not upstream `examples/speed.c` timing and not native-ND kernel timing.

## Qualification and scope

Release and ASan/UBSan native suites pass float32/float64 at lengths 0, 1, 2, 3, 4, 5,
7, 8, 9 and 17, with two columns, special IEEE records, input immutability, canaries,
bound-minus-one, repeated finalize and corruption checks. Python tests independently
cover UTS/MTS reconstruction, requested/actual tolerance identity, source hashing and
unsupported mode rejection.

The qualification and formal runs use the real `exchange_rate` float64 dataset with
eight independent columns. The formal preflight has 34/34 observations PASS and zero
raw/numerical absolute-error violations over 60,704 values; maximum observed absolute
error is `0.00056105468749989562`.

This evidence applies only to that dataset, error bound and registered 1D execution
profile. It does not establish performance for other tolerances, data, native ND arrays,
parallel devices or zfp modes.

Final evidence:

- qualification: `runs/runset-20260920T072311Z-861332410bb3`;
- formal: `runs/runset-20260920T072326Z-c296325d2eac`, 10/10 eligible PASS;
- report: `runs/runset-20260920T072326Z-c296325d2eac/report/report.html`;
- ReportID: `v2:report:sha256:edc3e9e4606c8cf253f42cb65cba5d2f06c17b29f569ce3bef992e9430003b1e`;
- full regression: 838 PASS; Ruff and codec registry verification: PASS.

Earlier `071544`, `071632` and their report remain append-only diagnostic evidence from
before checksum component accounting was separated. They are not the final evidence.
