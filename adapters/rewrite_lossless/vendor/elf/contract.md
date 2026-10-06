# Elf VLDB2023 contract (2026-10-06)

Freeze Spatio-Temporal-Lab/elf vldb2023-release at
386d69348e6c30475761d3519ee0bfe10ed473d3, not dev/Elf+.
NOASSERTION; local workflow override USER_DECISIONS.md (2026-10-06).
Little-endian binary32/64 arrays, MSB-first raw encoding. Each value has
one erasure flag; erased values carry beta (3/4 bits). No beta reuse.
The XOR stream transmits the full significant range, including its low one
bit; first value transmits trailing count then width-trailing bits.
Flags/window buckets match the original source. Finish adds a zero erasure
flag, canonical NaN XOR terminator, zero finish bit and byte padding.
All NaNs are source END, not lossless input. Preserve signed zeros/infinities.
Bound original unbounded significance loops and reject original decimal
recovery failures rather than silently change arithmetic or fall back to raw.
Java saturation and masked shift distances are reproduced using safe C++.
Use original log10 semantics (float rounding of encoder log10 in binary32;
decoder uses double log10), positive decimal power scales, and original
significant count without removing decimal zeros.
Independent APIs append/finalize/reset, raw encode/decode and ELF1 checked
32-byte self-contained frame are distinct. Frame layout follows Elf+ ELP1
layout but uses ELF1 magic; all CRC, count, reserved bits and exact padding
checked. FinalBits counts the complete frame. Capacity failures write nothing.
No source SIMD/thread/GPU paths. Same serialized dataset columns feed original
Java and C++; contract forbids substituting the mislabeled native dev baseline.
