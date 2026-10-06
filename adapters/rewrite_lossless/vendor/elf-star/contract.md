# Elf* contract (2026-10-06)

Freeze Spatio-Temporal-Lab/SElfStar 457ceb0033e98d516fef42e39d17c9d4b8abbfdb
ElfStarCompressor and ElfStarXORCompressor, binary32/64, with block Huffman
coding and optimized post-office tables. This is independent block Elf*, not
the native Serf no-Huffman variant or the adaptive streaming SElf*.
NOASSERTION; local workflow override USER_DECISIONS.md (2026-10-06).
Same decimal helpers and numerical domain as SElf*: NaN END, signed zero
and infinity supported, original nonterminating significance searches and
non-lossless decimal recoveries rejected. No raw fallback.
Append buffers values; finalize computes block distributions excluding END,
builds exact Java PriorityQueue Huffman ties, serializes every symbol code,
computes post-office lead/tail tables, then encodes values and END. No
cross-block history. Reset matches upstream refresh. Huffman and position
metadata are included in raw bytes and FinalBits, with zero byte padding.
Original binary32 compressor has a fixed 1001-slot array, limiting ordinary
input to 1000 values; binary64 window constructor is supported up to 16384.
ESF1 frame uses a 32-byte little-endian checked header (same field layout as
ELP1), count, CRC32 and exact raw payload. Raw cross-decode is available.
Invalid code lengths, prefix conflicts, unsorted position tables, missing
windows, missing END, malformed count, truncation or nonzero padding reject.
Independent objects and code tables are instance-owned, fixing upstream
static decoder Huffman-array sharing without changing the serialized format.
Independent APIs append/finalize/reset, capacity no-write and owned output.
No accelerated upstream paths. Selected 32-bit Java oracle has only the
already documented unused-helper declaration build overlay, never a codec
semantic change. Dataset plan uses all first1000 numeric columns in ETTh1,
exchange_rate and weather, both widths, both cross-decodes and byte equality.
