# Sprintz native port binding

Consumes the released `sprintz-family-native-20261017` sources unchanged. The four active IDs are `sprintz-delta`, `sprintz-fire`, `sprintz-delta-huffman`, and `sprintz-fire-huffman`. All old `adapters/sprintz` implementations and patches were removed after archival; the old u8 IDs and fire-huff0 ID have no aliases.

`_sprintz_family_command` checks `FROZEN_SOURCES.json`, compiles native/dispatch units with AVX2/BMI1/BMI2/LZCNT/POPCNT and API/binding units for baseline x86_64, then links the local frozen Huff0. Every native operation checks CPU support before entering ISA code. There is no fallback, float quantization, or automatic chunking.

Native core consumes physical row-major 8/16-bit integer bytes and returns caller storage in both directions. Its staging, safety scan, allocations, complete SZF1 serialization and decode materialization are inside encode/decode timing. Native `sz_*` output is copied by the released safe API; caller storage does not imply zero allocation.

C1 accepts a 16-byte SZI1 descriptor: magic, width in bytes (u8), reserved zero (u8), dimensions (u16), element count (u64), then row-major data. This flat API also admits incomplete rows, as qualified by the native port. Object matrices have complete rows. C1 requires one compress, one zero-byte finalize and supports reset. It uses the same SZF1 output as core; object-level dtype, shape and order are restored by the outer object format.

SZF1 is a 24-byte little-endian header followed by **unchanged** native payload:

| Offset | Field |
|---|---|
| 0 | magic `SZF1` (4 bytes) |
| 4 / 5 / 6 / 7 | width in bytes / predictor / Huffman / path (u8 each) |
| 8 / 10 | dimensions (u16) / reserved zero (u16) |
| 12 / 16 / 20 | decoded bytes (u32) / native payload bytes (u32) / reserved zero (u32) |

Decode takes its path from the frame, including when core decoder parameters are `{}`. Library predictor/Huffman identity and requested core geometry must match. Frame count, payload extent, reserved fields and released structural safety validation are enforced before output commit. This format has no checksum: structurally valid payload modifications can decode successfully. It is a memory-safe recovery contract, not a corruption-authentication claim. Complete header, EOF, native metadata, entropy envelope and padding are counted.

Paths: 0 auto RLE, 1 general RLE, 2 lowdim RLE (u8 dims<=4, u16 dims<=2); Delta additionally 3 bitpack and 4 noRLE; FIRE additionally 5 historical noRLE, u8 only. Input <=65536 bytes; dimensions 1..128; one call per object. Signed integers preserve the same underlying bits. The native raw16 final-byte repair and author Huff0 `reported_elements*2+1` convention are preserved.

Scope, fresh verification, limitations, archive and commands: [Bench integration report](../../docs/sprintz_integration/README.md). Standalone provenance and per-file license notices remain under `vendor/sprintz_family`; source oracle assets are research-only and are not linked into production. Query, legacy primitives, other entropy combinations and other platforms are not admitted.
