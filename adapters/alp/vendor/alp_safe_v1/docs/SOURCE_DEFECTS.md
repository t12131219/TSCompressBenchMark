# Source defects and safe-v1 deviations

The frozen source is unmodified in Source/alp-cwida/upstream. Initial fresh
differential run is preserved in reports/history/synthetic-first-run. Three
binary32 adaptive source frames selected factor=10, exponent=10: a single 1.25,
two signed zeros, and the last rowgroup of a 102401-value decimal sequence.
`Constants<float>::FACT_ARR` has only 10 entries (0..9), while MAX_EXPONENT=10.
The original sampling decoder reads FACT[10]. Such streams are outside the
defined source format domain. They are expected malformed rejections, not
successful source cross-decodes. The fixed predicate is factor >= table length;
no generic source mismatches may be excused by this rule. Initial failed run is
not rewritten; the corrected expectation has its own fresh report.

safe-v1 excludes that undefined sampling candidate. Source's decimal fast path
also uses unchecked float->signed casts, a binary64 upper sentinel for binary32,
and can round an in-range double beyond INT64_MAX by its magic-number step.
The patched implementation checks both pre-round and post-round values and uses
an in-range integer sentinel. Values failing reconstruction remain original-bit
exceptions, not RAW. Signed multiplication in `decoder::decode_value` can
overflow during sampling; unsigned modulo product plus memcpy to signed matches
the generated FALP arithmetic without UB. All fixes are in the exact diff and
pre/post hashes in patches/INDEX.json. No RD algorithm change is made.

These patches preserve source-defined arithmetic behavior but add a defined
safety policy on source UB paths. Decisions/bytes on UB paths are not claimed
original-equivalent. Empirical release parity is reported per fixture, and
cannot prove a universal source domain despite successful raw byte equality.
Original-input bitpattern recovery, independent original-source decoding of
safe output, and original-source encoding on legal records are separate checks.
The new versioned frame and padding/ownership checks are wrapper changes.
