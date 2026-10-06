# Chimp / Chimp128 frozen contract (2026-10-06)

Canonical source: panagiotisl/chimp, commit 320d397157c7e0696b3c64dc1711fc17a3add3da,
Apache-2.0. Chimp128 is ChimpN with exactly 128 history entries, for both binary32
and binary64. Other ChimpN history sizes are different algorithm variants.
Native Data-Stream-Compression's 64-entry "128" path and TsFile's different
32-bit bucket table cannot replace these identities. Both algorithms are P1 codecs.

Input is a contiguous little-endian sequence of IEEE bits. Preserve signed zero,
infinities and noncanonical NaN payloads; reject the canonical NaN END pattern
(32: 7fc00000; 64: 7ff8000000000000). No raw fallback or numerical conversion.
Independent objects are limited to 16,777,216 values to bound allocation and
avoid Java signed counter overflow. Null input is allowed only for count zero.

Raw format: MSB-first, first value full width, flags 00 repeat/history index,
01 trimmed XOR/history index+bucket+significant count, 10 reused leading bucket,
11 new leading bucket. Both widths use buckets 0,8,12,16,18,20,22,24.
Thresholds are 5/6 for Chimp32/64, 12/13 for Chimp12832/64. Preserve the original
64-bit ChimpN stale trailing-zero decision after hash candidate rejection.
Finish writes canonical NaN, one zero bit, and zero byte padding. Raw decode
accepts an upstream allocated buffer, returns consumed bits including finish,
and bounds output by actual bits. Invalid windows, missing END and truncation
raise exceptions. A decoder returns raw values one at a time and owns its input.

Encoder append preserves history/window across calls; finalize once, append
after finalize and repeated finalize fail. Reset produces a new independent
stream. Invalid input is rejected before any append mutation. No concurrent
use of one handle; independent handles are safe. No SIMD/GPU/threaded upstream
codec paths exist. No optimized fallback is declared.

CMP1 wrapper is distinct from upstream raw bytes: 40-byte little-endian header
(magic[4], version[1]=1, width[1], history[2]=1 or128, count[8], meaningful_bits[8],
payload_bytes[8], checksum[8]), then exact padded raw payload. Checksum is FNV-1a
64 over first32 header bytes and payload; it detects accidental corruption,
and is not authentication. Exact length, padding, END position and decoded count
are checked. FinalBits=8*complete CMP1 size; no external side information.
compress_into/decompress_into do not write on insufficient capacity.

Frozen oracle uses unmodified public Java APIs and reflection only for final
writtenBits. Dependencies and JDK are SHA-256 locked in Source/chimp.
G2 oracle cases precede canonical implementation; real-data plan uses all value
columns of ETTh1, exchange_rate and weather, first 1000 rows, both widths, plus
multiple block boundary and branch/history patterns. Same serialized bytes feed
both implementations. NaNs are tested as raw bits, never float comparison.
