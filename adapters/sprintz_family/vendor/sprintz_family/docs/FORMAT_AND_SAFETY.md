# Raw format and ownership

The C ABI accepts flat little-endian 8/16-bit integer representations. No float,
timestamp, dictionary, learned model or source-language runtime is hidden in it.
The decoder must receive the same width, predictor, entropy and dispatch profile
as the encoder. Native metadata checks dimensions and output count; it does not
authenticate data or identify the predictor. Structurally valid modified bytes
may decode successfully. Safety checks do not promise corruption detection.

RLE streams: LE u32 ngroups, LE u16 trailing element count, LE u16 dimensions.
Each group has two sets of dimensions * (3/4)-bit width codes. Maximum code maps
7->8 or15->16. Zero total width means a 7/15-bit run count of 8-row blocks.
Lowdim payload packs each dimension's 8 values in width bytes; general payload
packs each row in ceil(sum(widths)/8) bytes. Trailing elements are raw.
Bitpack-only/Delta-noRLE use LE u32 original element count + LE u16 dimensions.
Legacy FIRE-noRLE uses LE u48 element count + LE u16 dimensions. No-RLE groups
always contain exactly 16 rows. Short inputs (<128 elements) are copied.

Huff0 preserves author's envelope: compressed = u32 raw bytes + HUF bytes;
incompressible (including HUF ret9) = zero u32 + u32 raw bytes + raw payload;
constant = u64 raw bytes + one constant byte (9 bytes total). Native metadata
prevents a constant all-byte raw buffer from representing an admitted Sprintz
stream with dimensions1..128, so the constant *encoder* branch is unreachable
for the qualified pipeline; its decoder is still bounded before use. Huff0's
128KiB block limit is respected by the 64KiB input contract.

Source 16-bit compressor reports floor(actual_byte_extent/2) elements when a
group header or RLE byte leaves the destination odd. Port raw output contains
all actual bytes; the author non-Huffman wrapper truncates an odd final byte.
Author Huffman always compresses reported_elements*2+1 bytes, including one
initialized padding byte when actual size is even. This convention is retained.
Do not label repaired raw streams byte-identical to the truncated source API.

Ownership: API copies input into a real zero-filled 8192-byte suffix allocation,
prevalidates all structural reads and expanded counts, decodes into owned output
with an 8192-byte SIMD suffix, then commits exactly expected bytes. Native
scratch allocations have a real initialized 64-byte suffix for wide loads.
Header storage is also corrected to its actual unpacked/vector extent. Every
native allocation is checked and tracked per thread; RAII releases outstanding
allocations on failure. Outer C++ staging failures map to SZ_MEMORY. Caller
buffers remain unchanged on error. Fault injection specifically targets native
scratch allocations; it does not override the system C++ allocator.

The validator rejects leading empty runs and nonfinal empty slots, preventing a
later run from repeating dest-ndims before the first output row. Resource limits
bound allocations, groups, dimensions and expanded output independently of data
checksums. Width arithmetic is unsigned for zigzag and explicit modulo32 for
FIRE products; signed right shift follows the supported GCC/Clang x86 behavior.
Packed scalar views use their supported aligned(1),may_alias extension. This is
an x86 compiler profile, not a claim of ISO-only, ARM or big-endian portability.
Baseline C ABI/CPU probing and ISA-enabled dispatch are separate translation
units. The four main public functions check ISA before entering native code.

RawSize is the exact API output byte count. This is not a self-describing frame.
Recovery requires config and expected output size. Golden sidecars store these
explicitly; full recovery cost is payload bytes plus sidecar bytes. Hashes and
manifest/validation logs are evidence overhead, not native bitstream fields.
Standalone timings/sizes do not establish Bench FinalBits or FORMAL eligibility.
