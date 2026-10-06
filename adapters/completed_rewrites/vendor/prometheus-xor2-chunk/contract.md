# Prometheus XOR2 Chunk algorithm contract

## Identity and scope

- AlgorithmID: `prometheus-xor2-chunk`
- ImplementationID: `prometheus-xor2-chunk-canonical-cpp`
- ObjectLevel: `P3_SYSTEM`
- PortMethod: `TRANSLATED`
- CompatibilityTarget: `CROSS_DECODE`
- Upstream: `prometheus/prometheus` commit
  `8374d30cb3fe705773bbac72d7015eba17480557`

The object is the complete byte stream returned by Prometheus
`XOR2Chunk.Bytes()`. Timestamp delta-of-delta, value XOR, the stale marker and
optional start timestamps share one stateful stream and are not independent
codecs. The outer TSDB segment framing and CRC are outside this contract.

## Input

The input is zero to 65,535 ordered records:

```text
(start_timestamp: int64, timestamp: int64, value_bits: uint64)
```

`value_bits` is the opaque IEEE-754 binary64 representation. All bit patterns
are lossless. The exact stale marker is `0x7ff0000000000002`; it is emitted as
the XOR2 stale symbol and does not replace the last non-stale value baseline.
`start_timestamp == 0` means no ST value for that sample. Go `int64` timestamp
and ST arithmetic uses defined modulo-2^64 two's-complement behavior.

## Header and joint stream

The physical chunk begins with a big-endian uint16 sample count and one ST
header byte. Header bit 7 means the first sample has ST. Bits 6-0 contain the
first sample index at which changing/per-sample ST begins. A zero lower field
means there are no later ST payloads. At index 127 the field is forced to 127,
so all later samples carry ST data.

Sample 0 contains signed Go varint timestamp, 64 value bits and optional signed
Go varint `(timestamp - start_timestamp)`. Sample 1 contains unsigned Go
uvarint timestamp delta, XOR2 value coding and optional ST varbit value.

For samples at index 2 and later, the joint prefix is:

```text
0      dod=0 and value unchanged
10     dod=0 and value changed
110    signed 13-bit dod, then value coding
1110   signed 20-bit dod, then value coding
11110  signed 64-bit dod escape, then value coding
11111  dod=0 and exact stale NaN marker
```

For nonzero dod, value coding is `0` unchanged, `10` reused XOR window, `110`
new XOR window, or `111` stale marker. For the `10` joint case, value coding is
`0` reused window or `1` new window. New windows use five leading-zero bits,
six significant-width bits where zero means 64, and the significant payload.
Leading zeros are clamped to 31. All fields are MSB-first and the final byte is
right-zero-padded.

## Start timestamps

When ST becomes active, the first payload is `previous_timestamp - ST` encoded
with signed varbit. Later payloads encode the delta of that difference. Signed
varbit buckets contain 1, 5, 9, 13, 17, 24, 32, 64 or 72 bits with the exact
prefixes in frozen `varbit.go`. ST payloads follow their sample's complete
joint timestamp/value payload.

## State and correctness

State comprises timestamp, unsigned timestamp delta, last non-stale value,
leading/trailing XOR window, ST, ST difference, sample count and header flags.
The canonical implementation must support independent reset, full encode and
decode, forward seek and append/resume without changing established header or
state semantics.

Lossless correctness compares ST, timestamp and every value bit. G2 freezes a
Go oracle built from the unmodified repository, golden physical chunks and a
dataset plan. G3 must pass self round-trip, byte comparison where deterministic,
both cross-decode directions, malformed input, sanitizer and the dataset plan.

## Accounting

`SerializedBits` is the complete physical byte length times eight.
`ExternalSideInformationBits` is zero. The component ledger separates the
three-byte container/ST header from the joint timestamp/value/ST/padding bits;
their sum must equal `FinalBits`. Dataset and performance validation remain
standalone rewrite evidence, not TSDataCompressBenchMark results.
