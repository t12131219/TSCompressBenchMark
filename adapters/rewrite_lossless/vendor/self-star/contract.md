# SElfStar standalone contract

Source revision: 457ceb0033e98d516fef42e39d17c9d4b8abbfdb. The complete 151-file
snapshot is immutable. The selected codec is SElfStarCompressor paired with
SElfStarXORCompressor and corresponding decoder, for both binary32 and binary64.
The original 32-bit utility class fails compilation because an unused helper
omits a local declaration. The documented reference overlay repairs that compile
error; the selected streaming path calls a different overload and is unchanged.
Original failure, patch, overlay and source hashes are retained.

ObjectLevel P1_STANDALONE_CODEC; PortMethod TRANSLATED; compatibility target
CROSS_DECODE. Implementation and G3-G6 status are recorded in PORT_MANIFEST.yaml.
The source audit executes 23 cases, including three real datasets and public
per-value network APIs. Source errors, timeouts and NaN loss are distinct from
successful bitwise source self-roundtrips.

Each session has ordered blocks of IEEE754 values with explicit width. A new
session starts in Elf+ style beta-prefix mode; subsequent blocks use a Huffman
code derived from the preceding block's erasing-symbol frequencies. END does not
contribute to that frequency table. All symbols, including zero-frequency ones,
participate in Java PriorityQueue construction. Frequency/height ties require
Java heap sift order, not an arbitrary stable or std::priority_queue ordering.

Leading/trailing distributions count nonzero XORs, including the final END XOR.
If the current pre-close compression ratio is worse than the stored ratio,
PostOfficeSolver selects the next quantization positions. Those positions are
written before the next block's first XOR value. Dynamic-programming loop order,
strict cost comparisons, pruning and deterministic ties are source semantics.
Sharing uses quantized leading/trailing windows and the original cost inequality.

refresh resets block output, beta, value count, first-XOR flag and distributions,
but retains session Huffman state, quantization positions, compression ratio and
saved XOR window. The decoder similarly retains the prior window and adaptive
positions. Native full-session reset must be separate from source block refresh.
Treating blocks as independent streams would violate compatibility.

The binary64 INetCompressor/INetDecompressor APIs are required capabilities:
each value yields a byte-aligned fragment with one reserved byte (the source
transport wrapper strips it); compressAndClose/decompressLast finalize the
block and build the next Huffman state. No external socket/network application
is part of this rewrite. The source's per-fragment compressed-bit counter reset
and its effect on adaptive close decisions must be reproduced and measured.
Binary32 has no corresponding source network interface and may not be falsely
claimed as a required missing native source capability.

Input layout is explicit little-endian bit patterns; compressed bits are MSB-first.
Java modulo-width shifts and casts, float intermediate rounding, decimal power
parsing, initial significant-count search (different from the separate Elf+
revision), finite magnitudes, sign and reconstruction formulas must be translated.
NaN inputs are outside the lossless domain: source canonicalization can lose bits
or encounter END. Extremely small values may fail to terminate; some large values
throw. Native bounded rejection must not silently fall back to another codec.
Signed zeros and infinities are source-supported, with bitwise validation.

Standalone framing must retain width, session/block counts and boundaries, exact
payload lengths, integrity checks and all state required by a fresh decoder.
FinalBits includes headers, table updates, END, padding and per-value reserved
bytes when applicable. Derived Huffman state is legitimate only when every prior
block needed to reconstruct it is retained and charged. No hidden model or table
may be supplied by a source oracle during production decoding.

Qualification requires complete encoder/decoder, sequence/raw source differential,
both cross-decode directions, adaptive multi-block and fragment paths, tails,
resource/capacity limits, no-write shortage, malformed rejection, independent
handles, sanitizers, static analysis, cross-platform/reproducible builds and
recorded real-data performance. No source license-only stop or framework
integration applies.

SST1 layout (all integers little-endian): 32-byte header consisting of magic
SST1[4], width[1], network-mode[1], reserved-zero[2], block-count[4], total-value-
bytes[8], payload-bytes[8], CRC32[4]. CRC covers header bytes 0..27 followed by the
payload, excluding the CRC field. The checksum detects corruption, not forgery.
Each block begins with value-count[4]. Block mode then stores raw-length[4] and
the source bytes; network mode instead stores packet-length[4] and reserved-byte-
inclusive source packet for each value. The last packet carries END. Padding must
be zero and less than one byte. Complete source table updates are carried in-band.
Frame FinalBits is exactly frame bytes * 8, including every block/packet record.
meaningful_bits is diagnostic source codec bits only and must not replace FinalBits.

Limits: 1024 blocks/session, 16384 values/block, 16 MiB total value bytes and
64 MiB encoded frame. These bound work and integer DP costs below Java int
overflow. Empty ordinary blocks/sessions are supported; network blocks must be
nonempty and binary64. Encoder.close and decoder END consumption automatically
perform source refresh; full-session reset is a distinct operation. append uses
temporary owned state to guarantee failure atomicity and never retains a borrowed
pointer. Capacity APIs finish/validate before writing; malformed input, bad width,
wrong floating-point rounding mode and shortages cause no partial output.

All numeric CSV columns use the first 3000 rows split into three blocks of 1000.
The original source audits are retained separately from the extended differential.
Every accepted standalone value must reconstruct bitwise; source recovery loss
causes explicit input rejection rather than a silently lossy lossless frame.
