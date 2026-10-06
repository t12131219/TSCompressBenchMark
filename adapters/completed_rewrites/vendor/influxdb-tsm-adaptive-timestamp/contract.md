# Frozen historical TSM Adaptive Timestamp contract

Source: InfluxDB Go v1.12.4, commit f9befe3459b689dc6dd1dd11e1e58e2943434ab1.
One timestamp pipeline includes all delta, decimal scaling, RLE, Simple8b,
raw fallback and selector stages. Target CROSS_DECODE, with exact original
bytes for both Stream and Batch profiles. No sorting or implicit conversion
of int64 timestamps is performed. Reverse/duplicate timestamps and signed
wrap boundaries follow uint64 modulo arithmetic as tested by upstream.

Empty input produces zero bytes. Nonempty byte0 has high-nibble type0 raw,
type1 Simple8b or type2 RLE; low nibble is decimal exponent0..12 from encoding.
Decoding accepts source exponent0..15. First timestamp is a BEuint64 modulo
representation. Subsequent differences are computed modulo2^64.
RLE is selected first for N>1 and all equal deltas, even when delta>2^60-1.
Otherwise raw fallback is selected if ANY unscaled delta>2^60-1; scaling does
not rescue this raw case. Packed deltas are divided by the largest common
power of10 no greater than10^12. Singleton uses packed exponent12.
Raw stores first timestamp and subsequent unscaled deltas in BE64 words.
Packed stores first timestamp plus BE64 Simple8b words. RLE stores first
timestamp, Uvarint(scaled delta), Uvarint(sample count); no checksum.
Every byte, including header and unused selector bits, contributes to FinalBits.
Each byte slice is one complete stream with its length supplied by the buffer
API, as in the source; no external model/type/initial timestamp is required.

Simple8b selectors0..15 have counts [240,120,60,30,20,15,12,10,8,7,6,5,4,3,2,1]
and widths [0,0,1,2,3,4,5,6,7,8,10,12,15,20,30,60]. Width0 means implicit ONES.
Other values occupy little-endian bit positions within the BE64 physical word.
Unused bits are zero in source encoding. Batch uses the InfluxDB fork's
prefix-only run-of-ones selection. Stream uses Jason Wilder's original
240-value buffered encoder; its canPack width0 examines ALL currently buffered
remaining values. These profiles can emit different valid compressed streams.
Decoder behavior is independent of encoding profile on valid standalone streams.

The source encoder reduces its stored timestamps in place. Source Bytes is
treated as a terminal operation before Reset; it is not an idempotent query.
Native append stores immutable copies, finalize caches exact source bytes,
repeated finalize is stable, and append after finalize fails until reset.
Batch source overwrites its input scratch; native batch preserves caller input
as required by the standalone safety API. These ownership/lifecycle adaptations
do not change either profile's compressed bytes or fresh-decoder output.

The legacy TimeDecoder.Init(empty) after RLE retains n/delta and emits ghost
values. Native Cursor::source_init explicitly preserves this observable quirk;
Cursor::reset provides a clean independent reset. The oracle retains both
fresh-empty and legacy reused-empty tests. Native never reproduces source panic,
unsafe slice casts or allocation bombs on malformed streams: explicit errors
replace them. Stream and batch malformed-input laxness is not a valid-stream
wire guarantee. Safe overread is0. Native sample limit is16777216 by default,
with a caller-specified smaller decoder limit. Counts are checked before
allocation/traversal. Shared handles require synchronization; separate handles
are independent. There is no upstream SIMD, GPU or internally parallel path.

Real inputs are complete timestamp columns from ETTh1, exchange_rate and
national_illness in original row order. Text dates are interpreted as UTC and
converted exactly to signed nanoseconds without float arithmetic. All rows,
duplicate timestamps and original spacing remain. No numeric value columns
are added or encoded. Synthetic/property cases cover all selector widths,
scaling exponents, raw/RLE precedence, stream/batch differences and wrap.

Source timestamps and primitives are unchanged. The oracle's minimal build
module excludes unrelated TSDB/Flux code and projects an exact upstream
slice-view helper and test printing/global helpers; full source files, exact
symbol hashes and original tests are retained in ORACLE_BUILD_PROJECTION.json.
G6 requires both-profile cross-decode, datasets, direct capability/preflight,
safety, portability, performance, licenses and two relocated identical builds.
