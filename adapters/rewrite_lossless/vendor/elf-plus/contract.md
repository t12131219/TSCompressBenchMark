# Frozen Elf+ contract (2026-10-04)

Source: Spatio-Temporal-Lab/elf development revision
`64e0d6004be322d9d8eaf9931e371df202f1a0eb`. The complete canonical algorithm is
AbstractElfCompressor + ElfXORCompressor + their decoders and decimal utilities,
in both binary32 and binary64. The VLDB2023 release and the separately named
ElfOnChimp/ElfOnChimpN/ElfOnGorilla, Chimp, Gorilla and FPC codecs are distinct
algorithms, not selectable backends of ElfCompressor.

The immutable 154-file snapshot, Java8 environment and 20 compiled source
classes are recorded in Source/elf-plus. `golden/source_audit.json` executes the
original public APIs. The test bridge only observes the bitstream position.

Input consists of ordered IEEE754 bits in explicit little-endian order. Width
is 32 or 64. The original algorithm has no timestamp, vectorization, threads,
GPU or parallel block operation. Its incremental addValue capability and
independent codec instances are required. The C++ package owns state and input
data; append, finalize and reset are explicit. Same-handle concurrent mutation
requires caller synchronization; independent handles may run concurrently.

Compatibility target is CROSS_DECODE for the Java raw format on inputs where
the source terminates successfully. Erasure beta state, quantized XOR leading
windows, modulo-width Java shifts, decimal power parsing and float intermediate
rounding are preserved. FMA and fast math are disabled. No numerical tolerance
is allowed for supported lossless inputs: decoded bit patterns must agree.

Source limitations are measured, not silently repaired: input NaN becomes the
canonical NaN END marker and causes early termination; very small finite inputs
can loop forever; large initial values can throw for a negative decimal scale.
The compatibility raw encoder retains NaN-as-END behavior. The standalone
lossless API rejects NaNs, rejects source-invalid scales, and bounds significance
search to detect nontermination. It does not fall back to another codec or raw
value coding. The measured boundary cases and native rejection must be tested.
Signed zero and infinity are source-supported raw values. Full arbitrary-float
losslessness is not claimed. Source-domain limitations are not capability waivers.

Raw bits are MSB-first. Close emits raw control 10, canonical NaN through XOR,
an extra zero bit, and zero byte padding. Source getSize excludes close; native
payload_bits includes close and padding. Source allocated 5000/10000-byte arrays
are not compressed size. Standalone ELF+ framing includes magic/version, width,
count, payload length and CRC32 of the payload; FinalBits is all frame bytes *8.
Frames have no external dictionary or uncharged parameters. Framing is a native
extension; raw source cross-decode remains a separate tested API.

Input/output size is bounded (16 MiB raw values, 64 MiB encoded input). Checked
size arithmetic, byte loads, bounded bit readers, window validation, count and
CRC checks protect untrusted input. Capacity APIs perform no output writes on
insufficient capacity or invalid input. Encoder reuse after finalize is rejected
until reset. Decoder output remains owned; fresh calls never share state.

G2 validation plan freezes source goldens, native raw byte equality and both
cross-decode directions, bitwise framed roundtrip, append partition invariance,
capacity/canary/unaligned/guard-page checks, malformed fuzz, ASan/UBSan/LSan,
GCC/Clang builds and real datasets. Three CSV datasets use numeric value columns
only, first 1000 rows per selected column, separately for both widths. Loader,
input/file hashes and source timing are saved. No adapters, registry or benchmark
integration is part of this package. FULL_PARITY/REWRITE_DONE requires all G0-G6
evidence; a partial implementation is not completion.

2026-10-06 audit: complete-frame compression and Encoder.finalize also compare recovered raw bits against owned original values. A source decimal sequence that fails lossless recovery is rejected before output; raw compatibility APIs retain upstream behavior. This check is included in standalone frame and Benchmark PIPELINE timing.
