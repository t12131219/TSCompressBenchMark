# Gorilla / Prometheus XOR contract v1

Frozen source: prometheus/prometheus 8374d30cb3fe705773bbac72d7015eba17480557,
`tsdb/chunkenc/xor.go` + `bstream.go`. Algorithm ID `gorilla-prometheus-xor`,
implementation `gorilla-prometheus-xor-cpp-v1`, SOURCE_REWRITE / TRANSLATED /
BYTE_IDENTICAL / P1_STANDALONE_CODEC. This is the Prometheus millisecond XOR
chunk variant of Gorilla, not the paper's second-resolution timestamp buckets.
The complete timestamp/value chunk is the comparison object. No Bench integration.

## Input and numerical semantics

A one-dimensional ordered series of 0..65535 `(int64 timestamp, binary64 bits)`
pairs. Public `Sample` stores value as uint64 bits; double helpers use memcpy.
All IEEE patterns (NaN payloads, signaling NaNs, infinities, signed zero,
subnormals) are preserved, with no arithmetic on values. Timestamps have no
monotonicity restriction for encode/decode; forward Seek requires sorted timestamps
for the usual lower-bound meaning. No missingness/validity field, histogram,
integer value, float32, multivariate prediction or implicit cast. Multicolumn
CSV verification is explicitly independent series, not a native matrix codec.

Go signed overflow and signed/unsigned conversion use two's complement modulo
2^64. C++ performs all timestamp/delta/delta-of-delta arithmetic in uint64;
conversion to int64 is explicit without implementation-defined narrowing. No
floating arithmetic, quantization, rounding or FMA. C++17, no fast-math,
FP contraction disabled. LP64 Linux amd64 and AArch64 are validation targets.

## Format and stages

Raw format identifier: Prometheus EncXOR=1 (identifier is API metadata, not an
extra byte in the raw chunk). Format is pinned by source revision, no new header.
Two-byte big-endian uint16 sample count. Remaining bits are MSB-first.
First timestamp is Go binary.PutVarint (unsigned base-128 of zigzag); first
value is 64 bits. Second timestamp is unsigned base-128 modular delta; value
uses XOR coding. Subsequent timestamps encode modular delta-of-delta:
0 -> `0`; [-8191,8192] -> `10` +14 bits; [-65535,65536] -> `110` +17 bits;
[-524287,524288] -> `1110` +20 bits; otherwise `1111` +64 bits.
The positive midpoint is positive, not the standard signed sign-bit boundary.

Value XOR zero -> `0`. Changed -> `1`; then `0` reuses the previous leading /
trailing zero window if initialized and fitting; `1` defines a new window with
5-bit leading zeros (clamped to 31), 6-bit significant length (0 means 64), and
significant bits. Encoder starts leading=255; decoder starts leading=trailing=0,
matching source, including a reacquired appender before the first value change.
No terminator/footer/checksum; uint16 count ends decoding; final byte is zero
padded. Header=16 bits + timestamp bits + value bits + padding = bytes*8.
ExternalSideInformationBits=0, FinalBits=SerializedBits. No model/dictionary.

## State, ownership and failures

RAII Encoder supports append, flush (snapshot of raw bytes without sealing),
reacquire (decode current bytes to reconstruct source Appender state), compact,
reset, raw reset, finalize and accounting. finalize seals the local writer;
repeated finalize is idempotent; reset clears the seal. Source Compact is not a
seal and is mapped to compact, not finalize. No original-input caching.
One chunk is bounded by 65535 samples and compress_bound(65535) output bytes.
Iterator defaults to an immutable byte snapshot; an explicit Borrowed mode reads
without copying raw input and snapshots the final byte as the source does. Borrowed
backing memory must stay valid at the same address and all bytes except the
original last byte must remain immutable until reset/destruction. Concurrent
append is supported by default snapshots; borrowed use requires the caller to
prevent reallocation. reset_owned transfers a vector without payload copying
after validation, matching raw ownership transfer in C++ rather than GC aliasing.
Iterator is noncopyable and supports incremental next / at /
forward seek / reset / error by exception. Snapshot creation must not race with
writer modification; after creation it may be iterated concurrently with append.
Independent handles share no mutable global state. Same writer requires external
synchronization; no internal multithreading, ISA dispatch or GPU.

Raw reset followed by append reproduces source bstream.Reset: writer free bits=0,
so append begins at the next byte even if previous stream ended partially.
This is an upstream source defect: arbitrary serialized partial-byte chunk
resume does not necessarily roundtrip. This behavior is NOT silently repaired.
Tests retain the source/rewrite reset-append bytes and decoding behavior; normal
incremental append/reacquire uses the live writer's free-bit count and roundtrips.

Public failures are typed C++ Error exceptions; messages own their storage.
No C ABI. Invalid arguments, short capacity, malformed/truncated stream and
chunk overflow are distinguished. One-shot encode/decode validate before touching
caller output; failure leaves caller buffers unchanged. Append reserves worst
capacity before state changes. Reset of invalid raw data leaves writer unchanged.
Pointer arguments must be valid for the specified size; Sample pointers must be
naturally aligned. Raw bytes may be unaligned; safe overread=0. No overlap between
sample/output regions. Invalid declared pointer extent remains caller error.

compress_bound(N)=2+ceil(157*N/8), checked and limited to N<=65535.
The conservative maximum is first sample 144 bits, second 157, later <=145.
Buffer compress requires at least the declared bound (bound-1 always fails).
Decompress requires capacity >=header count. Strict decoding (default) checks
varint overflow, XOR widths, input/resource limits and <=7 zero tail bits.
Relaxed decoding permits ignored tail bytes as upstream does, but retains memory
safety and width checks; it supports investigation of source reset defects.
No checksum exists: undetectable bit corruption is not promised detectable.

## Qualification and applicability

All public chunk functionality and upstream scalar decoder fast paths are
REQUIRED_PARITY. Canonical bit-at-a-time serves as baseline; a separately forced
optimized scalar byte-at-a-time writer/reader preserves those fast mechanisms.
G5 follows G3/G4; new SIMD/GPU/internal parallelism is NOT_APPLICABLE, no waiver.
Required evidence: independent Go oracle; full raw byte equality, four decoding
routes, append state trace, lifecycle/seek/concurrency, malformed/fuzz, ASan/UBSan,
real full CSV columns, amd64/AArch64 cross-run, reproducible builds and physical
FinalBits closure. Test-only GRI1/GRS1 batching envelopes are not codec output;
per-chunk raw bytes are the accounting and compatibility unit.
