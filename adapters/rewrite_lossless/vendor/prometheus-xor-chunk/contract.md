# Prometheus XOR Chunk algorithm contract

## Identity and scope

- AlgorithmID: `prometheus-xor-chunk`
- ImplementationID: `prometheus-xor-chunk-canonical-cpp`
- ObjectLevel: `P3_SYSTEM`
- PortMethod: `TRANSLATED`
- CompatibilityTarget: `CROSS_DECODE`
- Upstream identity: `prometheus/prometheus` commit
  `8374d30cb3fe705773bbac72d7015eba17480557`

The object is the complete paired timestamp/value byte stream returned by
Prometheus `XORChunk.Bytes()`. Delta-of-delta and value XOR are internal stages,
not independent benchmark codecs. The outer TSDB segment length, encoding byte
and CRC-32C are not part of `XORChunk.Bytes()` and are outside this contract.

## Input

The input is an ordered sequence of zero to 65,535 paired samples:

```text
(timestamp: int64, value_bits: uint64 IEEE-754 binary64 representation)
```

Timestamps may be negative, duplicated, out of order or cross the signed
`int64` boundary. Timestamp subtraction and accumulation use Go's defined
two's-complement modulo-2^64 behavior. Values are never interpreted
arithmetically; all binary64 patterns, including NaN payloads, infinities,
subnormals and signed zero, are preserved exactly.

## Byte and bit format

1. A two-byte big-endian unsigned sample count.
2. Sample 0 timestamp as Go signed varint and value bits as 64 MSB-first bits.
3. Sample 1 unsigned timestamp delta as Go uvarint, followed by value XOR.
4. Later timestamp delta-of-delta values use the Prometheus 1/16/20/24/68-bit
   branches (control plus 0/14/17/20/64 payload bits), followed by value XOR.
5. Value XOR uses unchanged, reused-window or new-window branches. Leading zeros
   are clamped to 31. A six-bit significant-width value of zero means 64 bits.
6. The final byte is zero padded on the right. No internal checksum is present.

The public upper bound is `2 + 19 * sample_count` bytes, checked before
arithmetic. Capacity is never treated as the actual compressed length.

## Decode and error behavior

The canonical API returns status codes and never throws across its public
boundary. It rejects truncated headers and fields, overflowing varints, invalid
value windows, output-capacity mismatches, non-zero trailing bits, more than
seven padding bits and chunks longer than the format bound. A failure may leave
a partial output prefix, but it returns `samples_written = 0`.

This decoder is intentionally stricter than the upstream iterator for trailing
bytes and impossible value-window headers. It accepts all valid upstream
encodings and emits bytes accepted by the upstream semantics.

## State and lifecycle

The canonical one-shot encode/decode API is allocation-free after caller
buffers are supplied. `Cursor` supports reset/reuse, sequential iteration and
the upstream forward-only `Seek` behavior. `append` reconstructs timestamp,
delta and XOR-window state from an existing valid chunk and resumes at the
first padding bit. As in the upstream appender, resuming a one- or two-sample
chunk can choose a different valid value-window representation than a one-shot
encode; decoded samples remain identical and the result stays cross-decodable.

The package-owned C ABI accepts an array of `pxor_sample_v1` records. Each
record contains an `int64_t` timestamp and opaque `uint64_t` IEEE-754 value
bits. No STL type or C++ object crosses the ABI. `compress` is one-shot per
reset, `finalize` is mandatory and emits zero additional bytes, repeated calls
are rejected, and reset starts an independent object. The API owns only its
opaque handle; all input and output buffers remain caller-owned.

## Correctness and accounting

Lossless correctness compares timestamp values and all 64 value bits. The
G2/G3 evidence includes byte-identical golden vectors, deterministic property
vectors and bidirectional decode between the C++ implementation and the
standalone Go oracle.

The standalone ledger defines `SerializedBits` as physical chunk length times
eight and `ExternalSideInformationBits` as zero. `container_bits` is the
two-byte sample count; all remaining physical bits, including final padding,
are charged to `timestamp_value_joint_and_padding_bits`. Their sum equals
`FinalBits`. Local standalone performance results are not Benchmark results.

Dataset validation uses complete timestamped CSV columns as independent chunks.
The `date` field is parsed as UTC signed `int64` Unix milliseconds and the
selected decimal value is parsed as binary64. The canonical input hash is over
big-endian `(int64 timestamp, uint64 value_bits)` records. The frozen selection,
source hashes and preprocessing rules are in `validation/DATASET_TEST_PLAN.yaml`.
