# ALP / ALP-RD native port contract v1 (frozen 2026-10-17)

Route: NATIVE_PORT, source cwida/ALP commit
31ca0ed11c93c99d3f5b5c30e01a3e1c3832d3ce, MIT. Shared source is deduplicated;
two selectable methods are delivered in one independent package. Object: VALUE,
lossless IEEE binary32/binary64, contiguous arrays, no timestamps/null bitmap.
This is a bounded native profile, not an upstream FULL_PARITY claim.

## Required profile

ALP adaptive (upstream first/second level sampling, automatic RD selection), and
forced ALP-RD. Vectors have 1024 values, rowgroups have 100 vectors. The final
vector is padded with positive zeros BEFORE rowgroup sampling. Padding is a
declared wrapper view and is discarded on recovery; no RAW fallback exists.
All IEEE bits, including NaN payloads, signed zeros, infinities and subnormals,
must roundtrip bit-for-bit. Decimal conversion safety patches define behavior
on source UB paths and are recorded as the `safe-v1` variant. Source defined
paths target identical decisions and complete raw vector objects (metadata,
FFOR words, exception positions and values). Added framing has no upstream
standard file format counterpart. Upstream ratio benchmarks use a hypothetical
format and do not constitute a serialized bitstream.

Portable x86_64 GCC 11 / Clang 14, C++17, LP64 little endian, and an explicitly
compiled AVX2 profile are required. AVX2 is compile-time, never silently run on
unsupported hardware. No runtime dispatch claim. FP: round-to-nearest,
FE_TONEAREST, FTZ/DAZ off, no fast-math, no contraction, no strict aliasing
(upstream uses signed/unsigned and float/integer views). AArch64 portable QEMU
is an additional measured target, not a physical ARM performance claim.
FP traps must be masked; unsupported rounding/flush/trap modes are rejected
before core entry. IEEE exception status flags may be set by sampling arithmetic.

API is version 1 C ABI (`alp_port.h`), one-shot and stateless. Input/output are
borrowed for the duration of the call; input can be unaligned and is copied to
typed owned workspace. Input size is n*dtype bytes, n <= 2^24. Caller must
provide accessible buffers of declared sizes. Buffer overlap is rejected.
All shape/size/capacity arithmetic is checked before access. bound includes
header, rowgroup descriptors, padded blocks and exceptions. Output publication
is atomic; on any error output is unchanged, used/consumed/count set to zero.
Buffer and result pointer aliasing is outside contract. No handles, incremental
update, flush, reset or finalize; encode returns the finalized complete object.
Independent calls may run concurrently. C++ exceptions never cross C ABI.

## Wire v1

All integers and FFOR words are little endian, never host structs. Header 32
bytes: magic `ALPRW001`, dtype u8 (4/8), method u8 (0 adaptive, 1 RD), reserved
u16=0, logical count u64, payload bytes u64, CRC32 u32. CRC covers header bytes
0..27 then payload; polynomial 0xedb88320. It detects corruption, not forgery.
No external model/dictionary/length is required. No trailing bytes accepted.

Each rowgroup: 32-byte descriptor: scheme u8 (1 RD, 2 ALP), right width u8,
left width u8, dictionary size u8, logical count u32, 8 dictionary u16 values,
8 reserved zero bytes. Decimal descriptor widths/dictionary must be zero.
Then ceil(group_count/1024) blocks. Block header 16 bytes: logical count u16,
exception count u16, bitwidth u8, factor u8, exponent u8, reserved zero u8,
signed base bitpattern u64 (binary32 uses only low 32 bits). Decimal payload:
bw*128 bytes of FFOR then exceptions (position u16, original IEEE bits).
RD block header bw/factor/exponent/base are zero; payload right_width*128 bytes
FFOR right words then left_width*128 bytes FFOR u16 words, then exceptions
(position u16, left bits u16). Dictionary and right/left bases are upstream
values (zero FOR bases for RD). Exception positions are strictly increasing
in 0..1023; may address padding. No implicit source array or encoder state.

Decoding validates resource caps, complete lengths, reserved fields, widths,
dictionary membership of non-exceptions and sorted positions before patching.
Untrusted bytes are copied to fully initialized typed 1024-word workspaces.
CRC is checked before core entry. Complete consumed/produced sizes are checked.
FinalBits = actual complete encoded byte count * 8; includes padding, headers,
dictionary, exceptions and CRC. No hidden recovery asset.

## Frozen verification plan

Fresh independent public-API upstream driver (compiled against unmodified
source, separate TU/binary) compares raw decisions, FFOR and exceptions, and
performs both cross-decode directions. Source UB counterexamples are separately
run under sanitizers; modified-source comparisons cannot prove unmodified UB
semantics. Additional independent bitpattern oracle is original input, including
all IEEE specials. Lengths 0,1,2,31,32,33,1023/4/5,2047/8/9,102399/400/401;
constants, decimals, mixed scales, random IEEE, all-exception vectors. Exact
capacity and minus-one, unaligned data, immutable input, overlap, unsupported
parameters/FP, truncated/mutated/rechecksummed frames, limits and concurrency.
ASan+UBSan with leak checks, TSan concurrent calls, seeded libFuzzer malformed
decoder and valid encoder roundtrip. Portable/AVX2/GCC/Clang comparison.

Real corpus frozen before execution: all numeric columns, original row order,
all rows of ETTh1, ETTh2, ETTm1, ETTm2, exchange_rate, national_illness, weather
from `/home/fzg/PycharmProjects/材料/TSBench_Corpus`; first column is date,
remaining fields must parse, no filtering. binary64 and explicitly rounded
binary32 are separate input cases. Hash original files and canonical columns.
Source/target, methods, cold process decode and FinalBits are checked. Release
timing is diagnostic only; no FORMAL comparison or Bench integration claimed.

N0–N5 evidence, toolchain/runtime/source/patch hashes, independent clean build,
replay tools, source/license inventory and release archive required. All
unopened ISA/experimental/publication capabilities remain in inventory.
