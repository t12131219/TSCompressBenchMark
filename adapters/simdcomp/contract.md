# SIMDComp bounded source API contract v1

This is the frozen uint32 primitive, plus an explicitly charged SBP1 wrapper.
It does not accept int64 timestamps or convert floats. Plain is P0; original
modular D1 and fixed-base FOR compositions are distinct P2 identities. Native
source, original failures, common patches and the additional AVX2 zero-width
patch remain separately traceable. No runtime fallback is allowed.

Native canonical configuration has exactly api, coding, isa, starting_point:
`{"api":"LENGTH","coding":"PLAIN","isa":"SSE4_1","starting_point":0}`.
SSE plain supports LENGTH/MASKED/WITHOUTMASK, D1 supports MASKED/WITHOUTMASK,
and FOR supports LENGTH/FULL. AVX2 supports plain MASKED/WITHOUTMASK only.
Plain requires seed 0; D1/FOR accept every uint32 seed. Unknown/duplicate fields,
noncanonical JSON and invalid combinations are rejected before source calls.

Input is one contiguous U32_LE vector, rank 1, stride 4, N<=16777216. No
validity, query or incremental Benchmark streaming profile is admitted. External
alignment 1 is supported by explicit internal 32-byte staging; external overread
is zero. Full vector descriptors, extents, shape, unused slots, alignment,
ownership, reserved fields and disjoint input/output capacities are checked.
Calls cannot borrow caller buffers after returning or mutate source bytes.

One update is followed by one required zero-byte Finalize. Empty input still
produces a complete 48-byte frame. Repeat update/finalize fails; Reset0 clears
state/timer totals while retaining configuration and timer enablement. Decode
uses a fresh context with the same wire mode, any configured seed, and the seed
stored in the stream. Unsupported mode/ISA changes cannot silently dispatch.

SBP1 is little endian: TSCBSBP1 magic8, count u32, seed u32, wire mode u32,
block size u32, block count u32, reserved-zero u32, body bytes u64, block records,
then FNV1a64 over preceding bytes. Every record contains logical count u16,
width u8, layout u8, payload bytes u32 and original API payload. Header/trailer
overhead is 48 bytes, records cost 8 bytes each. API choice MASKED/WITHOUTMASK
does not alter bytes. Exact count, seed, mode, layouts and physical sizes are
always serialized; none of this is hidden side information.

Wire modes: 0=SSE plain exact 128-value blocks; 1=D1 padded 128-value blocks;
2=FOR LENGTH exact 128-value blocks; 3=FOR FULL padded 128-value blocks;
4=AVX2 plain exact 256-value blocks. Layout0 uses the original four-lane
length/tail API, layout1 a padded full four-lane block, layout2 a full eight-lane
AVX2 block. AVX2 tails explicitly use SSE simdpack_length/simdunpack_length.
D1 pads the final partial block with its last logical value; FOR FULL pads with
the fixed base. Padding does not change canonical count or raw denominator.

Width=1..31 uses the original interleaved lane words, with zero unused bits.
Width=0 has no payload. Width=32 is original absolute little-endian uint32
storage for plain, D1 and FOR; it must not be interpreted as stored residuals.
D1 carries the last logical value to the next block, beginning at stream seed.
FOR uses the explicit fixed seed in every block. Width calculation is checked
against a separate scalar range calculation; source truncation cannot become
a lossless result. Bound is a checked worst-case allocation bound. Exact
actual output capacity is accepted even when smaller than that bound.

Before unbounded decode calls, the shim checks the complete frame, checksum,
count/resource limits, mode/ISA, record geometry, width, exact payload size,
tail padding and canonical unused bits. Source reconstruction occurs only in
aligned bounded staging. Minimal width and padded reconstruction are verified
before a final caller copy. Bad descriptors, alias, capacity, malformed frames,
allocation failures and invalid original API lengths leave caller bytes, used
length and lifecycle unchanged. Attempted source calls retain their native time.

FinalBits must count container8, fixed metadata32, record metadata8 each,
checksum8 and every payload byte. Logical value codeword bits and physical
tail padding are computed from actual widths/layouts; their sum equals payload
bytes*8. Native timing wraps only original width/pack/unpack APIs. Scalar
validation, copies, allocation, framing and checksums remain in CORE/PIPELINE.
No hidden preprocessor, backend compressor or conversion is introduced.

Native qualification must consume shipped shared binaries and same-object fault
executables in release/debug/ASan+UBSan, including all source routes, exact
guard pages, misalignment, atomic failure, allocator faults, timer faults and
actual bytes against an independent oracle. This contract does not itself claim
ABI, Python SDK or five-layer qualification.
