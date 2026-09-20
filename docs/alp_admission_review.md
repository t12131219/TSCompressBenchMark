# ALP / ALP-RD admission review

Date: 2026-09-20

## Identity decision

The spreadsheet rows `ALP` and `ALP_RD` map to `cwida/ALP` commit
`31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce`. The local TSBench ALP entry contains
metadata only, so the executable source closure comes from the benchmark and publication
benchmarks in the upstream ALP repository.

Upstream `alp::encoder::init` may select `Scheme::ALP_RD`. Registering that adaptive entry
as `alp` would make `alp` and `alp-rd` execute the same path on some inputs. The project
therefore uses two non-overlapping identities:

- `alp`: decimal ALP only. If rowgroup sampling selects ALP-RD, execution returns
  `UNSUPPORTED`; fallback is forbidden.
- `alp-rd`: ALP-RD is explicitly initialized and used for every rowgroup.

Results from these AlgorithmIDs must not be merged. Both are lossless float codecs, but
their semantic comparability does not imply identical execution paths.

## Stream and accounting

The adapter is a one-shot C ABI v1 implementation driven by Python. Input columns remain
independent and use upstream 1024-value vectors and 102400-value rowgroups. The native
frame serializes every item required for independent decoding:

- dtype, shape, scheme, vector and rowgroup structure;
- ALP exponent/factor, FOR base/width, FastLanes packed payload, exception positions and
  raw IEEE exception values;
- ALP-RD dictionary, left/right widths, both FastLanes payloads, exception positions and
  exception left parts;
- exact logical tail counts.

The outer descriptor preserves buffer names, dtype, shape and layout transformation.
`FinalBits` is the exact outer prefix plus descriptor plus complete native frame. Upstream
logical compression-size estimates are never used for accounting.

## Correctness policy

Correctness is byte-for-byte IEEE representation equality, not numeric equality and not
the upstream benchmark's weaker `isnan()` category check. Qualification covers `+0`, `-0`,
both infinities, positive and negative subnormals, and multiple NaN payloads for float32
and float64. Tail padding is never exposed in the reconstructed object.

## Replayed safety patches

The vendored tree remains byte-identical to the audited source closure. Builds copy it to
`build/` and replay three patches:

1. bound float factor indices to the actual `FACT_ARR<float>` range 0..9;
2. perform decoder multiplication in the floating domain instead of overflowing signed
   integer intermediates;
3. check the destination signed-integer range before conversion and retain the safe check
   in vector encoding.

These defects were found by the project's ASan/UBSan qualification, not hidden with
sanitizer exclusions.

## Five-layer evidence

- Layer 1: two codec manifests reference one hashed SourceArtifact and a complete
  onboarding card.
- Layer 2: capability negotiation admits homogeneous little-endian float32/float64 VALUE
  UTS/MTS without validity; all other representations are rejected.
- Layer 3: 42 Python adapter tests and native release plus ASan/UBSan suites cover vector
  and rowgroup boundaries, hostile truncation/trailing bytes, canaries and lifecycle.
- Layer 4: the real `exchange_rate` float64 dataset produced 10 eligible PASS repetitions
  for each algorithm.
- Layer 5: the formal run produced two summaries and two coverage tasks.

Formal report: `runs/runset-20260920T042909Z-b99a85c9c901/report/report.html`.

## Limits

This admission covers scalar FastLanes fallback execution only. SIMD kernels, heterogeneous
columns, validity, asynchronous MTS, streaming, query and random access are not admitted.
The formal evidence is one real dataset and does not establish universal performance.
