# Histogram-ST and FloatHistogram-ST frozen contract

The AlgorithmID covers both complete Prometheus joint histogram streams at
commit 8374d30cb3fe705773bbac72d7015eba17480557. Compatibility target CROSS_DECODE;
reference physical bytes, decoding behavior and append/recode/resume semantics
are the oracle. No independent timestamp-only stream or framework integration
is produced. Native output is precisely upstream Chunk.Bytes(); caller supplies
the encoding type as in Prometheus FromData. A transport carrying multiple
chunks must separately account for that transport's framing.

Header bytes 0–1 contain the 14-bit sample count and two counter-reset bits.
Byte2 records first-ST-known and first-ST-change-on. Payload is MSB-first,
with zero padding at the end of the physical byte. Limit is 16383 samples.
ST starts at zero if unknown; the first known ST uses a Go signed varint of
timestamp-ST. Later ST fields use the source varbit grammar, including forced
first-change-on=127. Timestamp and integer histogram counts/bucket deltas use
the source signed/unsigned varbit and modulo64 delta/DoD arithmetic. Float
count/zero/sum/buckets preserve IEEE-754 binary64 bits through XOR coding.

Layout includes signed schema, zero threshold, positive/negative spans and
custom bounds when schema=-53. Zero threshold 0 and small powers of two have
compact encodings; custom upper bounds have the source thousandths fast path
and raw binary64 fallback. Empty/nil slices have the same wire representation.
Decoder accepts known reserved schemas [-9,52] and -53; retrieval reduces schema
>8 to 8 according to source bucket-index/count arithmetic. Public integer-to-
float retrieval converts signed adjacent bucket deltas to absolute counts.

Counter/gauge hints, stale-NaN marker 0x7ff0000000000002, decreasing counts,
schema/threshold/custom-bound changes and bucket insertions determine whether
append requires replacement, recoding or rejection. A recode retains ST and
chunk reset header. The previous compatible appender can determine the first
sample's reset header. Public retrieval reports unknown on the first counter
sample, not-reset subsequently, and gauge throughout gauge chunks. Stale public
samples are empty histograms with the original stale sum bits.

Append resume must restore the decoder's exact bit position and XOR window
state, which can legitimately produce different bytes from uninterrupted append
after a first sample while preserving source semantics. Input ownership is
native-owned copies: public append does not mutate caller spans/buckets even
though the Go appender may expand its histogram argument in place. Error paths
must preserve the current chunk. No independent seek index is added; seek is
forward traversal with source semantics.

Native resource limits are explicit: 100000 spans, bounds and buckets per side,
16383 samples and checked allocations. Malformed/truncated input must fail
without overreads or unbounded allocation; C++ must translate upstream panic
cases into explicit errors. No global mutable codec state is allowed.

Source oracle corpus has 34 synthetic semantic vectors and 12 measured-data-
derived histogram cases. The real cases aggregate all OT observations, in source
order, from ETTh1, exchange_rate and national_illness into fixed windows of64
with custom upper bounds [-10,0,1,10,20,40,80]. All partial last windows are kept.
Both gauge window counts and cumulative counter counts are represented as
integer-delta and binary64-absolute buckets. Timestamp is last-row UTC Unix
milliseconds; counter ST is the first source timestamp, gauge ST is zero.
Aggregation defines the test input, not codec preprocessing or a claim that
the CSV already contains native histogram samples. No data-dependent tuning,
normalization, missing-value removal, sorting or unrelated reshape is used.
Both implementations consume the same frozen input.txt bytes. These workloads
are supplemented by synthetic schema/span/reset/NaN/ST boundary cases.

G4 independently exposes append/import/export/query/finalize/reset/compact,
cursor next/seek/reset, integer-to-float conversion and resource/lifecycle
errors. G5 records OPTIMIZATION_NOT_APPLICABLE: upstream has no histogram SIMD,
GPU or internal-threaded encoding variant. G6 requires source↔native cross
decode, qualified data, safety, capability closure, reproducible builds and
source/license/SBOM evidence; frozen source gates alone do not establish release.
