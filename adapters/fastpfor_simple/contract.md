# FastPFOR Simple9 / Simple9hacked / Simple16 source contract

Source: `fast-pack/FastPFOR@2457e1ed1af35bbf7f4c509c863fa9797e637cb3`, Apache-2.0.
This is an original-source P0 primitive. No semantic preprocessing is enabled.

Input is one immutable VALUE/UTS vector stored as little-endian uint32. Every value
must be in `[0, 268435455]`; count is at most 16,777,216. Wider uint32, int64
timestamps, floating point, MTS and validity are rejected. Rejection precedes any
caller output write; no narrowing or quantization is permitted. External alignment
is 1 and external readable/writable padding is 0. Python gathers non-contiguous
logical views explicitly; the compatibility layer owns Benchmark layout changes.

The three codec keys have separate AlgorithmIDs. Both original marked/unmarked
instances are preserved. `mark_length` changes bytes and ConfigID. The marked count
word is retained. A fresh decoder obtains marked/count from the serialized stream;
it must have the matching codec kind. ISA is fixed scalar, one thread, no fallback.

SPC1 stores a canonical JSON logical descriptor and SHA-256, followed by SPF1.
SPF1 uses little-endian magic/count/kind/marked/word-count/reserved fields, unchanged
original selector words, and FNV1a64. Scalar validation checks grammar, count,
consumption and unused low tail bits before invoking the original decoder.
Internal input padding and output headroom are 28 uint32 words. They are staging
costs, not serialized bits. Caller output changes only after complete success.

One compress, mandatory zero-byte finalize, reset/reuse and independent decode are
supported. Streaming, query and random access have no Benchmark qualification.
Worst-case physical bytes are `44 + descriptor bytes + 40 + 4*(N + marked)`.
Values, tail padding, selectors/count metadata, descriptor, container and checksums
are disjoint physical bit buckets; their sum equals actual serialized bytes * 8.
All side information needed for standalone decode is serialized.

CORE/PIPELINE include Python descriptor/FFI, domain/grammar validation, gathering,
native staging/allocation/copy, checksum and finalize costs. Optional native timing
measures only original encodeArray/decodeArray calls, including exception interval
termination. It is enabled by default and explicitly disabled when requested.
It never replaces the full CORE/PIPELINE/E2E observation or affects wire bytes.

Source probes preserve known unsafe original public API calls. The bounded ABI has
release/debug/ASan+UBSan evidence. The complete unchanged upstream unit/factory has
release evidence with assertions enabled; that is not a claim that all other
FastPFOR codecs have native Benchmark qualification. Leak detection is unavailable.
Registration is not five-layer or full logical workbook-entry qualification.
