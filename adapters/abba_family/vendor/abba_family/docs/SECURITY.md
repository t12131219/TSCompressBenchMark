# Decoder and API threat model

Untrusted JSON requests, explicit models and binary frames may be malformed.
The caller owns and correctly sizes addressable buffers; dangling pointers and
aliasing the size-counter objects with other arguments are caller errors. The
API does not execute code, load plugins, invoke a shell or deserialize pickle.
No original data file is consulted during decoding.

AFS1 validates total bytes, header/version, metadata length, payload accounting,
and CRC before parsing models. Depth/node/byte limits prevent unrestricted JSON
nesting. It validates model sizes, finite starts/centers/scales, width ranges,
stream counts, output limits, symbol IDs, Huffman tables/oversubscription,
context-table size, LZW dictionary growth, padding and exact input consumption.
bzip2 uses its streaming API so trailing compressed garbage is rejected too.
LZMA decode memory is capped at 256MiB. Huffman lookup uses bounded code width
and an indexed decoder rather than a table-wide scan for each bit.

Resource limits are public and deterministic. Work caps bound quadratic source
stages. Encoders/decoders can still use significant memory within those limits;
process RSS is measured and no zero-workspace claim is made. CRC detects accidental
corruption only. Performance numbers are not sanitizer numbers. Native source
libraries are built from bundled sources and included in sanitizer builds.

Evidence includes guard/canary/immutability/capacity tests, truncation at every
byte of representative frames, checksum-valid random mutations, width 1..64,
persistent OOM, concurrency, Clang static analysis and coverage-guided libFuzzer.
Fuzzer outputs that remain valid are accepted; rejection counts are not treated
as a correctness metric by themselves. No universal proof for all possible
floating-point inputs is asserted.
